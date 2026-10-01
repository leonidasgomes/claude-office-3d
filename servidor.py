"""Servidor local do Claude Office 3D (somente biblioteca padrão).

Serve esta pasta e expõe:
  GET /config                         -> configuração pública (título, tema, agentes, GitHub) para a página
  GET /eventos?desde=<n>[&ultimos=<k>] -> {"total": N, "eventos": [...]} a partir de dados/eventos.jsonl
  GET /kanban                         -> cartões do GitHub Projects (via gh, em cache)
  GET /prs[?forcar=1]                 -> pull requests abertos do repositório configurado (via gh, em cache)
Só escuta em 127.0.0.1, na porta do config.json (padrão 8765).

Opções: --porta N (ignora a do config)  --sem-navegador (não abre o navegador)
"""
import json
import mimetypes
import re
import subprocess
import sys
import threading
import time
import webbrowser
from collections import deque
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import configuracao  # noqa: E402

HOST = "127.0.0.1"
PASTA = Path(__file__).resolve().parent
EVENTOS = PASTA / "dados" / "eventos.jsonl"
VENDOR = PASTA / "vendor" / "three"
MAX_POR_RESPOSTA = 500  # evita respostas gigantes se o cliente ficar muito para trás
KANBAN_VALIDADE = 120   # s; o gh leva alguns segundos, então o quadro é lido no máximo a cada 2 min
PRS_VALIDADE = 60       # s
CDN_THREE = f"https://cdn.jsdelivr.net/npm/three@{configuracao.VERSAO_THREE}/"

mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/javascript", ".mjs")
mimetypes.add_type("text/css", ".css")

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


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, formato, *args):
        pass  # silencioso

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def responder(self, corpo, tipo="application/json; charset=utf-8"):
        if not isinstance(corpo, bytes):
            corpo = json.dumps(corpo, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def do_GET(self):
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
        if url.path in ("/", "/index.html"):
            return self.responder(index_html().encode("utf-8"), "text/html; charset=utf-8")
        # não expõe dados brutos, configuração com caminhos locais nem scripts
        p = url.path.lower()
        if p.startswith(("/dados", "/.")) or p.endswith((".py", ".bat", ".sh", ".json", ".md")):
            self.send_error(404)
            return
        super().do_GET()


def main():
    args = sys.argv[1:]
    porta = cfg()["porta"]
    if "--porta" in args:
        try:
            porta = int(args[args.index("--porta") + 1])
        except (IndexError, ValueError):
            print("uso: servidor.py [--porta N] [--sem-navegador]")
            return
    navegador = "--sem-navegador" not in args
    endereco = f"http://{HOST}:{porta}/"
    try:
        servidor = ThreadingHTTPServer((HOST, porta), partial(Handler, directory=str(PASTA)))
    except OSError:
        print(f"Porta {porta} ocupada: provavelmente o escritório já está rodando. Abrindo o navegador em {endereco}")
        if navegador:
            webbrowser.open(endereco)
        return
    print(f"{cfg()['titulo']} rodando em {endereco}  (Ctrl+C para encerrar)")
    if not configuracao.caminho_config().exists():
        print("Aviso: config.json não encontrado — usando a configuração padrão. Rode 'python instalar.py'.")
    if navegador:
        threading.Timer(0.8, lambda: webbrowser.open(endereco)).start()
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrando.")
    finally:
        servidor.server_close()


if __name__ == "__main__":
    main()
