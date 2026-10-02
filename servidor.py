"""Servidor local do Claude Office 3D (somente biblioteca padrão).

Serve esta pasta e expõe:
  GET /config                         -> configuração pública (título, tema, agentes, GitHub) para a página
  GET /eventos?desde=<n>[&ultimos=<k>] -> {"total": N, "eventos": [...]} a partir de dados/eventos.jsonl
  GET /kanban                         -> cartões do GitHub Projects (via gh, em cache)
  GET /prs[?forcar=1]                 -> pull requests abertos do repositório configurado (via gh, em cache)
  GET /xp                             -> placar de XP e níveis (dados/xp/placar.json, gerado por xp.py; opcional)
  GET /api/alertas?desde=<id>         -> fila de alertas (alertas.py); GET /api/push/chave e POST /api/push/inscrever|sair|prefs|teste
                                         (Web Push, push.py: só aparelho pareado com sessão + CSRF, ou o PC)
Só escuta em 127.0.0.1, na porta do config.json (padrão 8765) — a não ser que o acesso pelo celular esteja ligado
("rede_local": true no config.json ou --rede-local): aí escuta em 0.0.0.0 e só aceita IPs de rede privada que tenham
o cookie do QR code (rede.py). O celular é só leitura.

Opções: --porta N (ignora a do config)  --sem-navegador (não abre o navegador)  --rede-local (liga o acesso pelo celular)
"""
import json
import mimetypes
import os
import re
import subprocess
import sys
import threading
import time
import webbrowser
from collections import deque
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import alertas  # noqa: E402
import configuracao  # noqa: E402
import rede  # noqa: E402

HOST = "127.0.0.1"
PASTA = Path(__file__).resolve().parent
EVENTOS = PASTA / "dados" / "eventos.jsonl"
VENDOR = PASTA / "vendor" / "three"
XP_PLACAR = PASTA / "dados" / "xp" / "placar.json"  # gerado por xp.py
XP_PASTA = PASTA / "dados" / "xp"
XP_PY = PASTA / "xp.py"
MAX_POR_RESPOSTA = 500  # evita respostas gigantes se o cliente ficar muito para trás
KANBAN_VALIDADE = 120   # s; o gh leva alguns segundos, então o quadro é lido no máximo a cada 2 min
PRS_VALIDADE = 60       # s
CDN_THREE = f"https://cdn.jsdelivr.net/npm/three@{configuracao.VERSAO_THREE}/"

mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/javascript", ".mjs")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("application/manifest+json", ".webmanifest")

_cfg = {"mtime": None, "dados": None}


def cfg():
    """config.json relido quando o arquivo muda (a porta só vale ao reiniciar o servidor)."""
    arq = configuracao.caminho_config()
    try:
        mtime = arq.stat().st_mtime
    except OSError:
        mtime = 0
    if _cfg["dados"] is None or mtime != _cfg["mtime"]:
        _cfg.update(mtime=mtime, dados=configuracao.carregar(arq))
    return _cfg["dados"]


def gh():
    return configuracao.localizar_gh()


def config_publica():
    c = cfg()
    g = c["github"]
    kanban_ok = bool(g["projeto_owner"] and g["projeto_numero"])
    return {
        "titulo": c["titulo"], "tema": c["tema"], "apelidos": c["apelidos"], "agentes": c["agentes"],
        "github": {"repo": g["repo"], "kanban": kanban_ok, "prs": bool(g["repo"]),
                   "projeto_owner": g["projeto_owner"], "projeto_numero": g["projeto_numero"],
                   "check_revisao": g["check_revisao"], "times": g["times"], "colunas": g["colunas"]},
        "xp": {"ativo": c["xp"]["ativo"], "niveis": c["xp"]["niveis"]},
        "gh_disponivel": bool(gh()),
        "three_local": three_local(),
    }


def three_local():
    return (VENDOR / "build" / "three.module.js").is_file() and \
        (VENDOR / "examples" / "jsm" / "controls" / "OrbitControls.js").is_file()


def ler_eventos(desde=0, ultimos=0):
    """Devolve (total, eventos). Lê o arquivo em streaming, guardando só o que interessa."""
    if not EVENTOS.exists():
        return 0, []
    total = 0
    coletados = deque(maxlen=ultimos if ultimos > 0 else MAX_POR_RESPOSTA)
    try:
        with open(EVENTOS, "rb") as f:
            for bruto in f:
                completa = bruto.endswith(b"\n")
                texto = bruto.decode("utf-8", errors="replace").strip()
                if not texto:
                    continue
                try:
                    obj = json.loads(texto)
                except ValueError:
                    obj = None
                    if not completa:
                        break  # linha ainda sendo escrita: ignora por enquanto
                total += 1
                if (total > desde or ultimos > 0) and isinstance(obj, dict):
                    coletados.append(obj)
    except OSError:
        return 0, []
    return total, list(coletados)


def rodar_gh(args):
    exe = gh()
    if not exe:
        raise RuntimeError("GitHub CLI (gh) não encontrado — instale em https://cli.github.com e rode 'gh auth login'")
    r = subprocess.run([exe, *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or "gh falhou").strip()[:300])
    return r.stdout


def _campo(item, nome):
    """Valor de um campo do Projects no JSON do gh (as chaves vêm com a 1ª letra minúscula)."""
    if not nome:
        return ""
    for k in (nome, nome.lower(), nome[:1].lower() + nome[1:]):
        if item.get(k) not in (None, ""):
            return item[k]
    return ""


class Cache:
    """Resultado do gh em cache; renova em segundo plano quando vence (a primeira leitura espera)."""

    def __init__(self, validade, ler, vazio):
        self.validade, self.ler, self.vazio = validade, ler, vazio
        self.quando, self.dados, self.lendo, self.chave = 0.0, None, False, None
        self.trava = threading.Lock()

    def _atualizar(self, chave):
        try:
            dados = self.ler()
        except Exception as e:  # sem gh, sem rede ou sem permissão: mantém o último resultado e avisa
            dados = dict(self.dados or self.vazio(), erro=str(e)[:300])
        with self.trava:
            self.quando, self.dados, self.lendo, self.chave = time.time(), dados, False, chave

    def obter(self, chave, forcar=False):
        with self.trava:
            if chave != self.chave:   # configuração mudou: descarta o cache
                self.dados, self.quando = None, 0.0
            vencido = forcar or time.time() - self.quando > self.validade
            iniciar = vencido and not self.lendo
            if iniciar:
                self.lendo = True
            primeira = self.dados is None
        if iniciar:
            if primeira or forcar:
                self._atualizar(chave)
            else:
                threading.Thread(target=self._atualizar, args=(chave,), daemon=True).start()
        espera = time.time() + 90
        while self.dados is None and time.time() < espera:
            time.sleep(0.2)
        return self.dados or dict(self.vazio(), erro="tempo esgotado esperando o gh")


def _ler_kanban():
    g = cfg()["github"]
    saida = rodar_gh(["project", "item-list", str(g["projeto_numero"]), "--owner", g["projeto_owner"],
                      "--format", "json", "--limit", "500"])
    cartoes = []
    for i in json.loads(saida or "{}").get("items", []):
        c = i.get("content") or {}
        cartoes.append({"numero": c.get("number"), "titulo": i.get("title") or c.get("title") or "",
                        "url": c.get("url") or "", "tipo": c.get("type") or "",
                        "status": i.get("status") or "Sem status",
                        "time": str(_campo(i, g["campo_time"]) or ""),
                        "prioridade": str(_campo(i, g["campo_prioridade"]) or "")})
    owner = g["projeto_owner"]
    url = f"https://github.com/users/{owner}/projects/{g['projeto_numero']}"
    try:  # organização usa /orgs/; o gh informa a URL certa
        info = json.loads(rodar_gh(["project", "view", str(g["projeto_numero"]), "--owner", owner, "--format", "json"]))
        url = info.get("url") or url
    except Exception:
        pass
    return {"configurado": True, "projeto": url, "cartoes": cartoes, "atualizado": time.strftime("%H:%M:%S"), "erro": ""}


def _ler_prs():
    g = cfg()["github"]
    saida = rodar_gh(["pr", "list", "-R", g["repo"], "--state", "open", "--limit", "50", "--json",
                      "number,title,url,headRefName,isDraft,mergeable,reviewDecision,statusCheckRollup,"
                      "author,updatedAt,labels,closingIssuesReferences"])
    check = g["check_revisao"]
    prs = []
    for pr in json.loads(saida or "[]"):
        checks = {(c.get("context") or c.get("name") or "?"): (c.get("conclusion") or c.get("state") or "PENDING")
                  for c in pr.get("statusCheckRollup") or []}
        if check:
            revisao = checks.get(check, "")
        else:  # sem check configurado: usa a decisão de review do GitHub
            revisao = {"APPROVED": "SUCCESS", "CHANGES_REQUESTED": "FAILURE"}.get(pr.get("reviewDecision") or "", "")
        prs.append({"numero": pr["number"], "titulo": pr["title"], "url": pr["url"], "branch": pr["headRefName"],
                    "rascunho": pr.get("isDraft", False), "conflito": pr.get("mergeable") == "CONFLICTING",
                    "revisao": revisao, "checks": checks,
                    "rotulos": [lb["name"] for lb in pr.get("labels") or []],
                    "fecha": [i["number"] for i in pr.get("closingIssuesReferences") or []],
                    "autor": (pr.get("author") or {}).get("login", ""), "atualizado": pr.get("updatedAt", "")})
    return {"configurado": True, "repo": g["repo"], "check": check, "prs": prs,
            "atualizado": time.strftime("%H:%M:%S"), "erro": ""}


_kanban = Cache(KANBAN_VALIDADE, _ler_kanban, lambda: {"configurado": True, "projeto": "", "cartoes": [], "atualizado": ""})
_prs = Cache(PRS_VALIDADE, _ler_prs, lambda: {"configurado": True, "repo": "", "prs": [], "atualizado": ""})


def kanban():
    g = cfg()["github"]
    if not (g["projeto_owner"] and g["projeto_numero"]):
        return {"configurado": False, "projeto": "", "cartoes": [], "atualizado": "",
                "erro": "Kanban não configurado: preencha github.projeto_owner e github.projeto_numero no config.json "
                        "(ou rode o instalar.py de novo)."}
    return _kanban.obter((g["projeto_owner"], g["projeto_numero"], g["campo_time"], g["campo_prioridade"]))


def prs(forcar=False):
    g = cfg()["github"]
    if not g["repo"]:
        return {"configurado": False, "repo": "", "prs": [], "atualizado": "",
                "erro": "Painel de PRs não configurado: preencha github.repo (owner/nome) no config.json "
                        "(ou rode o instalar.py de novo)."}
    return _prs.obter((g["repo"], g["check_revisao"]), forcar)


def index_html():
    """index.html; com o three.js baixado em vendor/, o importmap aponta para lá (funciona sem internet)."""
    texto = (PASTA / "index.html").read_text(encoding="utf-8")
    if three_local():
        texto = texto.replace(CDN_THREE, "/vendor/three/")
    titulo = cfg()["titulo"].replace("&", "&amp;").replace("<", "&lt;")
    return re.sub(r"<title>.*?</title>", f"<title>{titulo}</title>", texto, count=1)


ACOES_XP = {"/api/xp/conferido": "--conferido", "/api/xp/liberar": "--liberar", "/api/xp/desfazer": "--desfazer"}
_xp_trava = threading.Lock()   # uma ação por vez


def _ler_json(arq, padrao):
    try:
        return json.loads(Path(arq).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return padrao


def acao_xp(rota, dados, ident):
    """(código, resposta) da ação de XP dos botões do Placar; recalcula só a partir do cache (xp.py --so-placar)."""
    flag = ACOES_XP[rota]
    pr = dados.get("pr")
    if isinstance(pr, bool) or not isinstance(pr, int) or pr <= 0:
        return 400, {"ok": False, "erro": "pr deve ser um inteiro positivo"}
    if not cfg()["xp"]["ativo"]:
        return 400, {"ok": False, "erro": "XP desligado no config.json"}
    placar = _ler_json(XP_PLACAR, None)
    if not isinstance(placar, dict) or not isinstance(placar.get("agentes"), dict):
        return 500, {"ok": False, "erro": "placar de XP indisponível (rode 'python xp.py')"}
    ags = [a for a in placar["agentes"].values() if isinstance(a, dict)]
    abertos = {"--conferido": {x.get("pr") for a in ags for x in a.get("conferir", [])},
               "--liberar": {x.get("pr") for a in ags for x in a.get("auditoria", [])},
               "--desfazer": set(_ler_json(XP_PASTA / "conferidos.json", [])) | set(_ler_json(XP_PASTA / "auditorias_resolvidas.json", []))}
    if pr not in abertos[flag]:
        return 404, {"ok": False, "erro": f"PR #{pr} não está na lista desta ação"}
    if flag == "--desfazer" and ident.get("permissao") != "pc":   # celular só desfaz o que foi "conferido" (amarelo)
        liberadas = set(_ler_json(XP_PASTA / "auditorias_resolvidas.json", []))
        if pr in liberadas or pr not in set(_ler_json(XP_PASTA / "conferidos.json", [])):
            return 403, {"ok": False, "erro": "o celular só desfaz PRs marcados como conferidos; liberar/desfazer liberação é só no PC"}
    if not XP_PY.is_file():
        return 500, {"ok": False, "erro": "xp.py não encontrado"}
    if not _xp_trava.acquire(blocking=False):
        return 409, {"ok": False, "erro": "outra ação de XP está em andamento"}
    try:
        r = subprocess.run([sys.executable, str(XP_PY), flag, str(pr), "--so-placar"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=180, cwd=str(PASTA), env=dict(os.environ, PYTHONUTF8="1"))
    except (OSError, subprocess.SubprocessError) as e:
        return 500, {"ok": False, "erro": str(e)[:200]}
    finally:
        _xp_trava.release()
    if r.returncode != 0:
        return 500, {"ok": False, "erro": ((r.stderr or r.stdout).strip().splitlines() or ["xp.py falhou"])[-1][:300]}
    novo = _ler_json(XP_PLACAR, None)
    if not isinstance(novo, dict):
        return 500, {"ok": False, "erro": "placar não foi regravado"}
    print(f"[xp] {flag} PR #{pr}", flush=True)
    return 200, {"ok": True, "placar": novo}


# ---- Alertas (alertas.py / push.py): detector em segundo plano, fila e Web Push -------------------------------------
ALERTAS = None   # criado no main(), só quando o servidor sobe de fato


def criar_alertas(obj_rede):
    """Liga o detector aos dados que o servidor já tem (PRs em cache, placar de XP, eventos, escalonamentos opcionais)."""
    global ALERTAS

    def placar():
        return _ler_json(XP_PLACAR, None) if cfg()["xp"]["ativo"] else None

    def escalonamentos():   # opcional: alertas.escalonamentos = caminho de um JSON {"semana": [{cartao, motivo, aberto, fechado, resultado}]}
        caminho = cfg()["alertas"].get("escalonamentos") or ""
        return _ler_json(caminho, None) if caminho and Path(caminho).is_file() else None
    fontes = {"prs": prs, "placar": placar, "eventos": lambda desde: ler_eventos(desde), "escalonamentos": escalonamentos}
    ALERTAS = alertas.Alertas(PASTA / "dados", fontes, cfg()["alertas"], TITULO, obj_rede)
    obj_rede.ao_revogar.append(ALERTAS.push.remover_aparelhos)   # revogar o aparelho apaga a inscrição de push
    return ALERTAS


def alertas_get(rota, qs, ident):
    """GET /api/alertas?desde=<id> (fila), /api/push/chave (chave VAPID pública) e /api/push/estado?h=<id da inscrição>."""
    A = ALERTAS
    if A is None or rota not in ("/api/alertas", "/api/push/chave", "/api/push/estado"):
        return None
    disponivel, motivo = A.push.disponivel()
    if rota == "/api/alertas":
        try:
            desde = max(0, int(qs.get("desde", ["0"])[0]))
        except ValueError:
            desde = 0
        lista, ultimo = A.listar(desde) if A.opcoes["ativo"] else ([], 0)
        return 200, {"ok": True, "ativo": A.opcoes["ativo"], "alertas": lista, "ultimo": ultimo, "titulo": TITULO(),
                     "tipos": alertas.tipos_publicos(A.opcoes), "push": {"disponivel": disponivel, "motivo": motivo}}
    if rota == "/api/push/chave":
        if not disponivel or not A.opcoes["ativo"]:
            return 200, {"ok": True, "disponivel": False, "motivo": motivo or "alertas desligados"}
        return 200, {"ok": True, "disponivel": True, "chave": A.push.chave_publica()}
    h = qs.get("h", [""])[0]
    ins = A.push.estado(ident["id"], h) if len(h) == 12 and all(c in "0123456789abcdef" for c in h) else None
    return 200, {"ok": True, "inscrito": ins is not None, "tipos": ins["tipos"] if ins else None}


def alertas_post(rota, dados, ident):
    """POST /api/push/inscrever|sair|prefs|teste (a guarda do rede.py já exigiu sessão pareada + CSRF, ou o PC)."""
    A = ALERTAS
    if A is None or not A.opcoes["ativo"]:
        return 400, {"ok": False, "erro": "alertas desligados"}
    if rota == "/api/push/inscrever":
        ok, erro, id_ = A.push.inscrever(ident["id"], ident["nome"], dados.get("subscription"), dados.get("tipos"))
        return (200, {"ok": True, "id": id_}) if ok else (400 if A.push.disponivel()[0] else 503, {"ok": False, "erro": erro})
    if rota == "/api/push/sair":
        endpoint = dados.get("endpoint")
        return 200, {"ok": True, "apagou": isinstance(endpoint, str) and A.push.sair(ident["id"], endpoint)}
    if rota == "/api/push/prefs":
        h = dados.get("h")
        if not isinstance(h, str) or not A.push.atualizar_tipos(ident["id"], h, dados.get("tipos")):
            return 404, {"ok": False, "erro": "este navegador não está inscrito"}
        return 200, {"ok": True}
    if rota == "/api/push/teste":
        alerta, r = A.alerta_teste(ident["id"])
        return 200, {"ok": True, "alerta": alerta["id"], "push": {k: r[k] for k in ("enviados", "falhas", "limitados", "removidos", "motivo")}}
    return None


def manifesto():
    """manifest.webmanifest (PWA): necessário para o push no iPhone (só funciona com o escritório na Tela de Início)."""
    nome = TITULO()
    return {"name": nome, "short_name": nome[:12], "start_url": "/", "scope": "/", "display": "standalone",
            "background_color": "#0f1419", "theme_color": "#161c24", "lang": "pt-BR",
            "icons": [{"src": "/icone-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
                      {"src": "/icone-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"}]}


class Handler(rede.HandlerSeguro):
    def api_post(self, rota, dados, ident):
        if rota.startswith("/api/push/"):
            return alertas_post(rota, dados, ident)
        return acao_xp(rota, dados, ident) if rota in ACOES_XP else None

    def api_get(self, rota, qs, ident):
        return alertas_get(rota, qs, ident)

    def caminho_bloqueado(self):
        # não expõe dados brutos, configuração com caminhos locais nem scripts
        p = urlparse(self.path).path.lower()
        return p.startswith(("/dados", "/.")) or p.endswith((".py", ".bat", ".sh", ".json", ".md", ".txt"))

    def rotas_get(self):
        url = urlparse(self.path)
        qs = parse_qs(url.query)
        if url.path == "/config":
            return self.responder(config_publica())
        if url.path == "/eventos":
            try:
                desde = max(0, int(qs.get("desde", ["0"])[0]))
            except ValueError:
                desde = 0
            try:
                ultimos = max(0, min(200, int(qs.get("ultimos", ["0"])[0])))
            except ValueError:
                ultimos = 0
            total, eventos = ler_eventos(desde, ultimos)
            return self.responder({"total": total, "eventos": eventos})
        if url.path == "/kanban":
            return self.responder(kanban())
        if url.path == "/prs":
            return self.responder(prs("forcar" in qs))
        if url.path == "/xp":
            if not cfg()["xp"]["ativo"]:
                return self.responder({"ativo": False, "agentes": {}})
            try:
                corpo = XP_PLACAR.read_bytes()
                json.loads(corpo)
            except (OSError, ValueError) as e:
                corpo = {"agentes": {}, "erro": f"placar de XP indisponível (rode 'python xp.py'): {str(e)[:120]}"}
            return self.responder(corpo)
        if url.path == "/manifest.webmanifest":
            return self.responder(json.dumps(manifesto(), ensure_ascii=False).encode("utf-8"), "application/manifest+json; charset=utf-8")
        if url.path in ("/", "/index.html"):
            texto = index_html()
            self.csp_html = texto  # o hash do importmap inline entra na Content-Security-Policy
            return self.responder(texto.encode("utf-8"), "text/html; charset=utf-8")
        self.servir_estatico()


def opcoes_rede(args):
    """(em_rede, https, tailscale): --rede-local liga; config.json: "rede_local", "rede_https" (padrão true), "rede_tailscale"."""
    c = cfg()
    return ("--rede-local" in args or bool(c.get("rede_local"))), c.get("rede_https") is not False, c.get("rede_tailscale") is True


def TITULO():
    return cfg()["titulo"]


def abrir_servidores(args, porta, em_rede, https, tailscale):
    """Sobe os servidores. Modo rede com HTTPS: HTTP só em 127.0.0.1:porta (o PC), HTTPS em 0.0.0.0:porta+1 (celular) e
    uma porta auxiliar 0.0.0.0:porta+2 só com o certificado público da CA. Sem HTTPS (ou sem como gerar o certificado):
    HTTP em 0.0.0.0:porta, com aviso. Devolve (principal, [extras]) ou (None, []) se a porta estiver ocupada."""
    obj = Handler.rede = rede.Rede(PASTA, em_rede)
    usa_https = bool(em_rede and https and "--sem-https" not in args and obj.iniciar_tls(porta, tailscale))
    if em_rede and https and "--sem-https" not in args and not usa_https:
        print("AVISO: HTTPS indisponível (" + obj.tls_info.get("erro", "?") + "). Caindo para HTTP na rede local.")
    host = "0.0.0.0" if (em_rede and not usa_https) else HOST
    try:
        principal = ThreadingHTTPServer((host, porta), partial(Handler, directory=str(PASTA)))
    except OSError:
        return None, []
    extras = []
    if usa_https:
        try:
            https_srv = rede.ServidorHTTPS(("0.0.0.0", porta + 1), partial(Handler, directory=str(PASTA)), obj.tls_ctx)
            HandlerCA = rede.HandlerCA
            HandlerCA.rede = obj
            extras = [https_srv, ThreadingHTTPServer(("0.0.0.0", porta + 2), HandlerCA)]
        except OSError as e:
            for s in extras:
                s.server_close()
            principal.server_close()
            print(f"Não consegui abrir as portas {porta + 1} (HTTPS) e {porta + 2} (certificado): {e}")
            return None, []
    return principal, extras


def main():
    args = sys.argv[1:]
    porta = cfg()["porta"]
    if "--porta" in args:
        try:
            porta = int(args[args.index("--porta") + 1])
        except (IndexError, ValueError):
            print("uso: servidor.py [--rede-local] [--sem-https] [--porta N] [--sem-navegador]")
            return
    navegador = "--sem-navegador" not in args
    em_rede, https, tailscale = opcoes_rede(args)
    servidor, extras = abrir_servidores(args, porta, em_rede, https, tailscale)
    endereco = f"http://{HOST}:{porta}/"
    if servidor is None:
        print(f"Porta {porta} ocupada: provavelmente o escritório já está rodando. Abrindo o navegador.")
        if navegador:
            webbrowser.open(endereco)
        return
    print(f"{TITULO()} rodando em {endereco}  (Ctrl+C para encerrar)")
    if em_rede and extras:
        print(f"ACESSO PELO CELULAR LIGADO (HTTPS): HTTPS em 0.0.0.0:{porta + 1}, certificado da CA em http://<ip>:{porta + 2}/ . "
              "Só IPs privados com sessão pareada entram; use o botão 'Celular' da página no PC.")
    elif em_rede:
        print("ACESSO PELO CELULAR LIGADO (sem HTTPS): escutando em 0.0.0.0 (rede local). Só IPs privados com sessão pareada "
              "entram; use o botão 'Celular' da página no PC.")
    for s in extras:
        threading.Thread(target=s.serve_forever, daemon=True).start()
    alertas_obj = criar_alertas(Handler.rede)
    parar_alertas = alertas_obj.iniciar()
    push_ok, push_motivo = alertas_obj.push.disponivel()
    print("Alertas: " + ("desligados (alertas.ativo no config.json)" if not alertas_obj.opcoes["ativo"] else
                         "ligados (notificação com a página aberta" + (", Web Push disponível)" if push_ok else
                                                                         "; Web Push INDISPONÍVEL: " + push_motivo + ")")))
    if not configuracao.caminho_config().exists():
        print("Aviso: config.json não encontrado — usando a configuração padrão. Rode 'python instalar.py'.")
    if navegador:
        threading.Timer(0.8, lambda: webbrowser.open(endereco)).start()
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrando.")
    finally:
        parar_alertas.set()
        servidor.server_close()
        for s in extras:
            s.shutdown()
            s.server_close()


if __name__ == "__main__":
    main()
