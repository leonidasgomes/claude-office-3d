"""Servidor local do Claude Office 3D (somente biblioteca padrão).

Serve esta pasta e expõe:
  GET /config                         -> configuração pública (título, tema, agentes, GitHub) para a página
  GET /eventos?desde=<n>[&ultimos=<k>] -> {"total": N, "eventos": [...]} depois do id n (tabela evento do banco local)
  GET /eventos?de=<ISO>[&ate=<ISO>][&apos=<id>] -> eventos de um período (replay do dia; paginado por id, até 5000 por página)
  GET /kanban                         -> cartões do GitHub Projects (REST via gh, em cache; traz também o texto da cota do GitHub)
  GET /prs[?forcar=1]                 -> pull requests abertos do repositório configurado (via gh, em cache)
  GET /xp                             -> placar de XP e níveis (dados/xp/placar.json, gerado por xp.py; opcional)
  GET /api/alertas?desde=<id>         -> fila de alertas (alertas.py); GET /api/push/chave e POST /api/push/inscrever|sair|prefs|teste
                                         (Web Push, push.py: só aparelho pareado com sessão + CSRF, ou o PC)
  GET /saude                          -> duplicados, círculos e PRs parados (saude.py; a cada 5 min, gravado em dados/saude.json),
                                         com os itens ignorados e os últimos pedidos ao líder
  POST /api/saude/ignorar|avisar      -> painel 🩺 Saúde: ignorar/reativar um item ou avisar o líder (só o PC, com CSRF)
  POST /api/saude/triagem             -> desfazer o "falso positivo" da triagem barata (só o PC, com CSRF)
  GET /grafo                          -> painel 🗺️ Arquitetura (grafo_painel.py + grafo/grafo.py): index do grafo do projeto,
                                         drift e validação resumida; a thread `grafo` lê só leitura a `grafo.ref` da 1ª pasta
                                         de "projetos" a cada grafo.intervalo_min (sem grafo: diz como criar um)
  GET /api/sugestoes                  -> sugestões abertas dos bots de revisão, por PR (sugestoes_bot.py; o celular pareado também lê)
  GET /api/praticas                   -> boas práticas dos projetos do config (boas_praticas.validar; recalculado no máximo a
                                         cada 10 min numa thread; o celular lê sem os caminhos absolutos)
  GET /api/versao                     -> {"local": versão instalada} (arquivo VERSION; mostrada no menu ⚙️ do painel)
  POST /api/sugestoes/tratar          -> encaminhar/ignorar/resolver uma sugestão (só o PC, com CSRF)
O GitHub é consultado só por REST com cache (PRs 180 s, com ETag e cache por sha; Kanban 600 s) e uma thread coleta as
sugestões a cada sugestoes.intervalo_min (padrão 15) minutos.
Só escuta em 127.0.0.1, na porta do config.json (padrão 8765) — a não ser que o acesso pelo celular esteja ligado
("rede_local": true no config.json ou --rede-local): aí escuta em 0.0.0.0 e só aceita IPs de rede privada que tenham
o cookie do QR code (rede.py). O celular lê tudo; com a permissão "conferir" ele também marca e desfaz "conferido"
(POST /api/xp/conferido e /api/xp/desfazer); liberar vermelho e tratar sugestões são só do PC (rede.PERMISSAO_ROTA).

Opções: --porta N (ignora a do config)  --sem-navegador (não abre o navegador)  --rede-local (liga o acesso pelo celular)
"""
import json
import mimetypes
import os
import posixpath
import re
import subprocess
import sys
import threading
import time
import webbrowser
from functools import partial
from http.server import ThreadingHTTPServer
ThreadingHTTPServer.request_queue_size = 64   # o padrão (5) recusa conexões quando a página pede vários módulos de uma vez no Windows
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import alertas  # noqa: E402
import banco  # noqa: E402  (banco local SQLite: eventos, decisões do XP, custos)
import cota  # noqa: E402
import configuracao  # noqa: E402
import rede  # noqa: E402
import saude  # noqa: E402  (duplicados, círculos, risco do PR, PR parado: saude.py)
import saude_triagem  # noqa: E402  (triagem barata dos itens novos da saúde: saude_triagem.py)
import sugestoes_bot  # noqa: E402
import boas_praticas  # noqa: E402  (boas práticas dos projetos: painel 🩺 Saúde)
import grafo_painel  # noqa: E402  (painel 🗺️ Arquitetura: base só leitura + grafo/grafo.py)

HOST = "127.0.0.1"
PASTA = Path(__file__).resolve().parent
VENDOR = PASTA / "vendor" / "three"
XP_PLACAR = PASTA / "dados" / "xp" / "placar.json"  # gerado por xp.py
XP_CUSTOS = PASTA / "dados" / "xp" / "custos.json"  # gerado por custo_time.py (custo por agente, cartão e PR; sem tokens)
CUSTOS_VALIDADE = 3600  # s; mais velho que isso, o /xp pede um custo_time.py novo em segundo plano
_custos_rodando = {"desde": 0.0}


def custos():
    """Custo do time (dados/xp/custos.json) ou None; velho ou ausente, roda custo_time.py em segundo plano.
    Só com "projetos" no config (é onde ficam os transcritos que ele lê)."""
    if not cfg().get("projetos"):
        return None
    try:
        idade = time.time() - XP_CUSTOS.stat().st_mtime
    except OSError:
        idade = None
    if (idade is None or idade > CUSTOS_VALIDADE) and time.time() - _custos_rodando["desde"] > 600:
        _custos_rodando["desde"] = time.time()
        try:
            subprocess.Popen([sys.executable, str(PASTA / "custo_time.py")], cwd=str(PASTA),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass
    return _ler_json(XP_CUSTOS, None)


XP_PY = PASTA / "xp.py"
MAX_POR_RESPOSTA = 500  # evita respostas gigantes se o cliente ficar muito para trás
MAX_PERIODO = 5000      # GET /eventos?de=&ate= (replay do dia): por página; o cliente pagina com apos=<proximo>
RE_ISO = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}(T[0-9]{2}:[0-9]{2}(:[0-9]{2})?)?", re.ASCII)
FORMATOS_ISO = {10: "%Y-%m-%d", 16: "%Y-%m-%dT%H:%M", 19: "%Y-%m-%dT%H:%M:%S"}
MAX_ID = 2 ** 63 - 1   # maior inteiro do SQLite
KANBAN_VALIDADE = 600   # s; o quadro é lido no máximo a cada 10 min (REST; o GraphQL do `gh project` só entra como reserva)
PRS_VALIDADE = 180      # s; REST, com ETag na lista (304 não conta no limite) e cache por sha
MERGEAVEL_TTL = 1800    # s; a base pode andar sem o sha do PR mudar, então o "conflito" é conferido de novo a cada 30 min
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
        "grafo": {"ativo": bool(c["grafo"]["ativo"])},
        "gh_disponivel": bool(gh()),
        "three_local": three_local(),
    }


def three_local():
    return (VENDOR / "build" / "three.module.js").is_file() and \
        (VENDOR / "examples" / "jsm" / "controls" / "OrbitControls.js").is_file()


def iso_valido(texto):
    """Data/hora ISO local só com dígitos ASCII e que existe de verdade (mês 13 ou 25:61 não passam)."""
    if not RE_ISO.fullmatch(texto or ""):
        return False
    try:
        datetime.strptime(texto, FORMATOS_ISO[len(texto)])
    except (KeyError, ValueError):
        return False
    return True


def eventos_periodo(qs):
    """GET /eventos?de=<ISO>&ate=<ISO>[&apos=<id>] (replay do dia): (código, dados). Datas no formato do hook, hora local
    ("2026-10-07T14:00" ou "2026-10-07"); `ate` exclusivo e opcional (sem ele, até agora); no máximo MAX_PERIODO por resposta."""
    de, ate = (qs.get("de") or [""])[0].strip(), (qs.get("ate") or [""])[0].strip()
    if not iso_valido(de) or (ate and not iso_valido(ate)):
        return 400, {"erro": "de/ate no formato AAAA-MM-DD ou AAAA-MM-DDTHH:MM[:SS], com data e hora que existem"}
    ate = ate or "9999-12-31"
    if ate <= de:
        return 400, {"erro": "ate precisa ser depois de de"}
    try:
        apos = max(0, int((qs.get("apos") or ["0"])[0] or "0"))
    except ValueError:
        return 400, {"erro": "apos precisa ser um número"}
    if apos > MAX_ID:
        return 400, {"erro": "apos grande demais"}
    try:
        eventos, proximo = banco.eventos_periodo(de, ate, apos, MAX_PERIODO)
    except Exception as e:   # banco ocupado ou quebrado
        print(f"[eventos] ERRO no período: {type(e).__name__}: {str(e)[:150]}", flush=True)
        return 503, {"erro": "banco de eventos indisponível agora"}
    return 200, {"de": de, "ate": ate, "eventos": eventos, "proximo": proximo, "maximo": MAX_PERIODO}


def ler_eventos(desde=0, ultimos=0):
    """Devolve (total, eventos) da tabela evento do banco local (banco.py): consulta pelo id, sem reler o histórico."""
    try:
        return banco.ler_eventos(desde, ultimos, MAX_POR_RESPOSTA)
    except Exception as e:   # banco ocupado ou quebrado: o escritório só fica sem novidades nesta consulta
        print(f"[eventos] ERRO: {type(e).__name__}: {str(e)[:150]}", flush=True)
        return desde, []


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


RE_LIMITE = re.compile(r"rate limit", re.I)
_limite = {"quando": 0.0, "texto": ""}


def aviso_limite(erro, recurso="core"):
    """Se `erro` é o limite da API do GitHub estourado, lê `gh api rate_limit` (essa consulta não conta no limite) e devolve
    "limite da API do GitHub atingido — volta às HH:MM". Só chama o gh quando dá erro de limite; vazio nos outros erros."""
    if not RE_LIMITE.search(erro or ""):
        return ""
    agora = time.time()
    if _limite["texto"] and agora - _limite["quando"] < 60:
        return _limite["texto"]
    texto = "limite da API do GitHub atingido — tente de novo em alguns minutos"
    try:
        r = subprocess.run([gh() or "gh", "api", "rate_limit"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)
        recursos = json.loads(r.stdout)["resources"]
        esgotados = [v for k, v in recursos.items() if k in recurso.split("|") and v.get("remaining", 1) <= 0]
        if esgotados:
            texto = "limite da API do GitHub atingido — volta às " + time.strftime("%H:%M", time.localtime(esgotados[0]["reset"]))
    except Exception:
        pass
    _limite.update(quando=agora, texto=texto)
    return texto


class Cache:
    """Resultado do gh em cache; renova em segundo plano quando vence (a primeira leitura espera)."""

    def __init__(self, validade, ler, vazio, recurso="core"):
        self.validade, self.ler, self.vazio, self.recurso = validade, ler, vazio, recurso
        self.quando, self.dados, self.lendo, self.chave = 0.0, None, False, None
        self.trava = threading.Lock()

    def _atualizar(self, chave):
        try:
            dados = self.ler()
        except Exception as e:  # sem gh, sem rede ou sem permissão: mantém o último resultado e avisa
            dados = dict(self.dados or self.vazio(), erro=str(e)[:300], limite=aviso_limite(str(e), self.recurso))
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


_url_projeto = {}
_base_rest = {}   # (dono, número) -> "users/<dono>/projectsV2/<n>" ou "orgs/<dono>/projectsV2/<n>"


def _paginas_rest(caminho):
    """GET REST paginado pelo gh (`--paginate --slurp`): lista única com os itens de todas as páginas."""
    paginas = json.loads(rodar_gh(["api", caminho, "--paginate", "--slurp"]) or "[]")
    return [x for p in paginas for x in (p if isinstance(p, list) else [p])]


def _valor_rest(campo):
    """Texto do valor de um campo de um item do Projects (REST): nome da opção, texto ou título."""
    v = (campo or {}).get("value")
    if isinstance(v, dict):
        v = v.get("name") or v.get("raw") or v.get("title") or ""
        v = v.get("raw", "") if isinstance(v, dict) else v
    return str(v or "")


def _ler_kanban_rest(g):
    """Cartões pela API REST do Projects v2 (`/users|orgs/<dono>/projectsV2/<n>/fields|items`, 100 por página): não gasta a cota
    do GraphQL (um `gh project item-list` de 180 cartões custa ~200 dos 5000 pontos/h). Levanta RuntimeError se falhar."""
    owner, numero = g["projeto_owner"], g["projeto_numero"]
    chave = (owner, numero)
    ultimo = RuntimeError("projeto não encontrado")
    for base in ([_base_rest[chave]] if chave in _base_rest else [f"users/{owner}/projectsV2/{numero}", f"orgs/{owner}/projectsV2/{numero}"]):
        try:
            campos = _paginas_rest(f"{base}/fields")
            _base_rest[chave] = base
            break
        except RuntimeError as e:
            if RE_LIMITE.search(str(e)):
                raise
            ultimo = e
    else:
        raise ultimo
    por_nome = {c["name"].lower(): c["id"] for c in campos if isinstance(c, dict) and "id" in c and "name" in c}
    nomes = {"status": "status", "time": g["campo_time"], "prioridade": g["campo_prioridade"]}
    ids = {k: por_nome.get(str(n).lower()) for k, n in nomes.items() if n}
    brutos = _paginas_rest(f"{base}/items?per_page=100&fields=" + ",".join(str(i) for i in ids.values() if i))
    url = f"https://github.com/{base.split('/')[0]}/{owner}/projects/{numero}"
    cartoes = []
    for i in brutos:
        c = i.get("content") or {}
        por_id = {f.get("id"): f for f in i.get("fields") or []}
        valor = {k: _valor_rest(por_id.get(ids.get(k))) for k in nomes}
        tipo = i.get("content_type") or ""
        # rascunho (DraftIssue) não tem número nem html_url: o link abre o item no próprio projeto (id numérico do item)
        link = c.get("html_url") or (f"{url}?pane=issue&itemId={i['id']}" if tipo == "DraftIssue" and isinstance(i.get("id"), int) else "")
        cartoes.append({"numero": c.get("number"), "titulo": c.get("title") or "", "url": link,
                        "tipo": tipo, "status": valor["status"] or "Sem status",
                        "time": valor["time"], "prioridade": valor["prioridade"], "item_id": str(i.get("node_id") or "")})
    return {"configurado": True, "projeto": url, "cartoes": cartoes, "atualizado": time.strftime("%H:%M:%S"), "erro": "", "limite": ""}


def _ler_kanban():
    g = cfg()["github"]
    try:
        return _ler_kanban_rest(g)
    except Exception as e:   # REST do Projects indisponível (gh antigo, escopo, projeto): cai no GraphQL do `gh project`
        if RE_LIMITE.search(str(e)):
            raise
    return _ler_kanban_graphql(g)


def _ler_kanban_graphql(g):
    saida = rodar_gh(["project", "item-list", str(g["projeto_numero"]), "--owner", g["projeto_owner"],
                      "--format", "json", "--limit", "500"])
    cartoes = []
    for i in json.loads(saida or "{}").get("items", []):
        c = i.get("content") or {}
        cartoes.append({"numero": c.get("number"), "titulo": i.get("title") or c.get("title") or "",
                        "url": c.get("url") or "", "tipo": c.get("type") or "",
                        "status": i.get("status") or "Sem status",
                        "time": str(_campo(i, g["campo_time"]) or ""),
                        "prioridade": str(_campo(i, g["campo_prioridade"]) or ""), "item_id": str(i.get("id") or "")})
    owner = g["projeto_owner"]
    url = _url_projeto.get((owner, g["projeto_numero"]))
    if not url:   # a URL não muda: o `project view` (uma chamada GraphQL a mais) só roda na primeira leitura
        url = f"https://github.com/users/{owner}/projects/{g['projeto_numero']}"
        try:  # organização usa /orgs/; o gh informa a URL certa
            info = json.loads(rodar_gh(["project", "view", str(g["projeto_numero"]), "--owner", owner, "--format", "json"]))
            url = info.get("url") or url
            _url_projeto[(owner, g["projeto_numero"])] = url
        except Exception:
            pass
    return {"configurado": True, "projeto": url, "cartoes": cartoes, "atualizado": time.strftime("%H:%M:%S"), "erro": "", "limite": ""}


_rest = {"repo": "", "etag": None, "lista": None, "status": {}, "merge": {}, "review": {}}   # caches por sha do commit
RE_FECHA = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?\s+(?:[\w.-]+/[\w.-]+)?#(\d+)", re.I)
FINAIS = ("SUCCESS", "FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "NEUTRAL", "SKIPPED", "ACTION_REQUIRED", "STALE")


def _rest_get(caminho, etag=None):
    """GET REST pelo gh (sugestoes_bot.gh_api): (status, json, cabeçalhos). Erros viram sugestoes_bot.ErroApi."""
    exe = gh()
    if not exe:
        raise RuntimeError("GitHub CLI (gh) não encontrado — instale em https://cli.github.com e rode 'gh auth login'")
    return sugestoes_bot.gh_api({"gh": exe}, caminho, etag)


def _checks_do_sha(repo, sha, check, agora):
    """Status do commit (REST /commits/{sha}/status; e, se o check de revisão for um check-run do Actions, /check-runs).
    Só fica em cache por sha quando o veredito do check de revisão já saiu; enquanto não saiu, é consultado de novo."""
    c = _rest["status"].get(sha)
    # Veredito final fica em cache só por 10 min: a revisão pode ser republicada no MESMO commit (reprovado → corrige o
    # ambiente → aprovado) e o cache eterno deixava o painel preso no veredito velho.
    if c and c["final"] and agora - c.get("quando", 0) < 600:
        return c["checks"]
    _, dados, _ = _rest_get(f"repos/{repo}/commits/{sha}/status")
    checks = {s["context"]: str(s.get("state") or "pending").upper() for s in (dados or {}).get("statuses") or []}
    if check and check not in checks:
        _, runs, _ = _rest_get(f"repos/{repo}/commits/{sha}/check-runs?per_page=100")
        for r in (runs or {}).get("check_runs") or []:
            checks[r["name"]] = str(r.get("conclusion") or "pending").upper() if r.get("status") == "completed" else "PENDING"
    _rest["status"][sha] = {"checks": checks, "final": bool(check) and checks.get(check, "") in FINAIS, "quando": agora}
    return checks


def _decisao_review(repo, n, sha, atualizado):
    """Sem check configurado: decisão das reviews (REST /pulls/{n}/reviews), em cache enquanto o PR não mudar."""
    c = _rest["review"].get(n)
    if c and c["chave"] == (sha, atualizado):
        return c["decisao"]
    _, lista, _ = _rest_get(f"repos/{repo}/pulls/{n}/reviews?per_page=100")
    ultimo = {}
    for r in lista if isinstance(lista, list) else []:
        if r.get("state") in ("APPROVED", "CHANGES_REQUESTED", "DISMISSED"):
            ultimo[(r.get("user") or {}).get("login")] = r["state"]
    estados = set(ultimo.values())
    decisao = "FAILURE" if "CHANGES_REQUESTED" in estados else ("SUCCESS" if "APPROVED" in estados else "")
    _rest["review"][n] = {"chave": (sha, atualizado), "decisao": decisao}
    return decisao


def _conflito_do_pr(repo, n, sha, agora):
    """mergeable do PR (REST /pulls/{n}): só quando o sha mudou (ou a cada MERGEAVEL_TTL, ou se o GitHub ainda calculava)."""
    c = _rest["merge"].get(sha)
    if c and c["conflito"] is not None and agora - c["quando"] < MERGEAVEL_TTL:
        return c["conflito"]
    _, dados, _ = _rest_get(f"repos/{repo}/pulls/{n}")
    dados = dados or {}
    mergeavel = dados.get("mergeable")
    conflito = None if mergeavel is None else (mergeavel is False or dados.get("mergeable_state") == "dirty")
    linhas = (dados.get("additions") or 0) + (dados.get("deletions") or 0) if "additions" in dados else None
    _rest["merge"][sha] = {"conflito": conflito, "quando": agora, "linhas": linhas, "arquivos": dados.get("changed_files")}
    return bool(conflito)


def _ler_prs():
    """PRs abertos do repositório configurado. Só REST: lista (ETag) + status por sha + mergeable por sha. O que o GraphQL dava
    e o REST não dá: "fecha" vem do texto do PR (Closes/Fixes/Resolves #n)."""
    g = cfg()["github"]
    repo, check = g["repo"], g["check_revisao"]
    if (_rest["repo"], _rest.get("check")) != (repo, check):
        _rest.update(repo=repo, check=check, etag=None, lista=None, status={}, merge={}, review={})
    estado, lista, cab = _rest_get(f"repos/{repo}/pulls?state=open&per_page=50", _rest["etag"] if _rest["lista"] is not None else None)
    if estado == 304:
        lista = _rest["lista"]
    else:
        lista = lista if isinstance(lista, list) else []
        _rest.update(etag=cab.get("etag"), lista=lista)
    agora = time.time()
    prs = []
    for pr in lista:
        sha, n = pr["head"]["sha"], pr["number"]
        checks = _checks_do_sha(repo, sha, check, agora) if check else {}
        if check:
            revisao = checks.get(check, "")
        else:  # sem check configurado: usa a decisão de review do GitHub
            revisao = _decisao_review(repo, n, sha, pr.get("updated_at", ""))
        prs.append({"numero": n, "titulo": pr["title"], "url": pr["html_url"], "branch": pr["head"]["ref"],
                    "rascunho": bool(pr.get("draft")), "conflito": False if pr.get("draft") else _conflito_do_pr(repo, n, sha, agora),
                    "sha": sha, "revisao": revisao, "checks": checks,
                    "rotulos": [lb["name"] for lb in pr.get("labels") or []],
                    "fecha": sorted({int(x) for x in RE_FECHA.findall(pr.get("body") or "")}),
                    "autor": (pr.get("user") or {}).get("login", ""), "atualizado": pr.get("updated_at", "")})
        tam = _rest["merge"].get(sha) or {}   # o mesmo GET /pulls/{n} do conflito traz o tamanho (sem chamada a mais)
        prs[-1].update(linhas=tam.get("linhas"), arquivos=tam.get("arquivos"))
        prs[-1]["risco"] = saude.risco_pr(prs[-1])
    vivos = {pr["head"]["sha"] for pr in lista}
    for k in ("status", "merge"):
        _rest[k] = {sha: v for sha, v in _rest[k].items() if sha in vivos}
    _rest["review"] = {n: v for n, v in _rest["review"].items() if n in {pr["number"] for pr in lista}}
    return {"configurado": True, "repo": repo, "check": check, "prs": prs,
            "atualizado": time.strftime("%H:%M:%S"), "erro": "", "limite": ""}


_kanban = Cache(KANBAN_VALIDADE, _ler_kanban, lambda: {"configurado": True, "projeto": "", "cartoes": [], "atualizado": ""}, "graphql|core")
_prs = Cache(PRS_VALIDADE, _ler_prs, lambda: {"configurado": True, "repo": "", "prs": [], "atualizado": ""}, "core")


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
               "--desfazer": banco.decisoes("conferido") | banco.decisoes("liberado")}
    if pr not in abertos[flag]:
        return 404, {"ok": False, "erro": f"PR #{pr} não está na lista desta ação"}
    if flag == "--desfazer" and ident.get("permissao") != "pc":   # celular só desfaz o que foi "conferido" (amarelo)
        if pr in banco.decisoes("liberado") or pr not in banco.decisoes("conferido"):
            return 403, {"ok": False, "erro": "o celular só desfaz PRs marcados como conferidos; liberar/desfazer liberação é só no PC"}
    if not XP_PY.is_file():
        return 500, {"ok": False, "erro": "xp.py não encontrado"}
    if not _xp_trava.acquire(blocking=False):
        return 409, {"ok": False, "erro": "outra ação de XP está em andamento"}
    try:
        r = subprocess.run([sys.executable, str(XP_PY), flag, str(pr), "--so-placar", "--origem",
                            f"escritório ({ident.get('permissao') or 'pc'})"], capture_output=True, text=True,
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
VIGIA = cota.Vigia(PASTA / "dados", "gh", leitor=lambda: cota.ler(gh()) if gh() else None)   # cota do GitHub: leitura barata a cada 5 min -> dados/github_cota.jsonl


def com_cota(dados):
    """Acrescenta ao JSON do Kanban/PRs o texto do rodapé ("GraphQL: 3.200/5.000 (volta 11:25)") e se a cota está baixa."""
    c = VIGIA.resumo() if gh() else None
    return dict(dados, cota=c["texto"] if c else "", cota_baixa=bool(c and c["baixa"]))


# ---- Sugestões dos bots de revisão (sugestoes_bot.py): coleta em segundo plano, leitura e tratamento ---------------------
ACOES_SUGESTAO = ("encaminhada", "ignorada", "discutir", "resolvida", "reabrir")
_sug_trava = threading.Lock()   # uma coleta por vez
# "Pronto para o merge" de cada PR aberto (sugestoes_bot.pronto, o mesmo do --pronto), por commit: o painel só acende
# verde com a revisão aprovada E isto OK para o commit atual (antes ficava verde antes de os bots revisarem).
PRONTO = {}
PRONTO_A_CADA_S = 180
# Liga quando o PRONTO foi calculado pela 1ª vez (ou não há o que calcular). Antes disso o detector de alertas não lê os
# PRs: com o PRONTO vazio todo PR aprovado viraria "espera" e, ao encher, dispararia pr_pronto de novo a cada reinício.
PRONTO_CARREGADO = threading.Event()
# Último estado (ok) publicado como status `sugestoes` por (pr, sha), com github.publicar_status: check obrigatório do
# merge automático. Por (pr, sha) e não por (pr, sha, ok): sugestão nova no mesmo commit depois do OK tem de voltar o
# status a pending.
STATUS_SUGESTOES = {}


def publicar_status_sugestoes(c, n, sha, ok, motivos):
    """Status `sugestoes` no commit do PR (só quando muda): success quando o --pronto está OK, pending sem. Falha ao
    publicar não derruba o laço; tenta de novo na próxima rodada."""
    if not sha or STATUS_SUGESTOES.get((n, sha)) == ok:
        return
    desc = "Sugestões dos bots decididas" if ok else (motivos[0] if motivos else "Sugestões pendentes")
    try:
        r = subprocess.run([c["gh"], "api", "-X", "POST", f"repos/{c['repo']}/statuses/{sha}", "-f",
                            f"state={'success' if ok else 'pending'}", "-f", "context=sugestoes", "-f",
                            f"description={desc[:140]}"], capture_output=True, timeout=60)
        if r.returncode == 0:
            STATUS_SUGESTOES[(n, sha)] = ok
    except (OSError, subprocess.SubprocessError):
        pass


def atualizar_pronto(c):
    """Coleta (sem a triagem paga) e calcula o --pronto de cada PR aberto. Coletar antes é obrigatório: revisão de bot
    que acabou de chegar precisa estar na caixa, senão o PR pareceria pronto cedo demais."""
    with _sug_trava:
        sugestoes_bot.coletar(c, triagem=False, log=lambda m: None)
        _, abertos, _ = sugestoes_bot.gh_api(c, f"repos/{c['repo']}/pulls?state=open&per_page=100")
        novo = {}
        for pr in abertos if isinstance(abertos, list) else []:
            info = {}
            ok, motivos = sugestoes_bot.pronto(c, pr["number"], coletar_antes=False, info=info)
            novo[str(pr["number"])] = {"ok": ok, "sha": info.get("sha", ""), "quando": time.time(),
                                       "motivos": [m for m in motivos if not m.startswith("(aviso)")][:3],
                                       "avisos": [m[9:] for m in motivos if m.startswith("(aviso)")][:3]}
            if c.get("publicar_status"):
                publicar_status_sugestoes(c, pr["number"], info.get("sha", ""), ok,
                                          [m for m in motivos if not m.startswith("(aviso)")])
        for k in [k for k in STATUS_SUGESTOES if str(k[0]) not in novo or novo[str(k[0])]["sha"] != k[1]]:
            STATUS_SUGESTOES.pop(k, None)   # PR fechado ou commit antigo: não cresce sem limite
        PRONTO.update(novo)   # troca sem esvaziar: entre clear() e update() o detector leria tudo como "espera"
        for k in [k for k in PRONTO if k not in novo]:
            PRONTO.pop(k, None)
        PRONTO_CARREGADO.set()


def pronto_laco(parar):
    """Thread: recalcula o pronto de cada PR aberto a cada 3 min (só REST; sem tokens). Custo por rodada: a coleta sem
    triagem (comentários e lista de PRs com ETag + 1 chamada de reviews por PR aberto), 1 lista de PRs abertos sem ETag
    (até 100) e, por PR aberto, até 3 chamadas REST sem ETag no `sugestoes_bot.pronto` (o PR, as reviews e, às vezes, o
    commit da cabeça); com github.publicar_status, 1 POST de status por PR só quando o resultado muda."""
    if parar.wait(40):
        return
    while not parar.is_set():
        try:
            c = sugestoes_bot.configuracao()
            if (c["bots"] or c["revisor"]) and c["repo"]:
                atualizar_pronto(c)
            else:
                PRONTO_CARREGADO.set()   # sem bots/revisor o painel não usa o PRONTO
        except Exception as e:   # nunca derruba o servidor; o painel cai no "aguardando"
            print(f"[pronto] ERRO: {type(e).__name__}: {str(e)[:150]}", flush=True)
        parar.wait(PRONTO_A_CADA_S)


def revisor_rodada():
    """Revisor de código próprio (revisor_ia.py, revisor.ativo no config.json): revisa os PRs abertos cujo commit atual
    ainda não foi revisado, antes da coleta, para os achados entrarem na mesma rodada. Nunca derruba o laço."""
    try:
        import revisor_ia
        for linha in revisor_ia.pendentes(log=lambda m: print(f"[revisor] {m}", flush=True)):
            print(f"[revisor] {linha}", flush=True)
    except Exception as e:   # sem `claude`, sem rede, etc.: as sugestões seguem sem o revisor
        print(f"[revisor] ERRO {type(e).__name__}: {str(e)[:200]}", flush=True)


def sugestoes_laco(parar):
    """Thread: coleta as sugestões dos bots a cada sugestoes.intervalo_min (padrão 15). Sem github.bots_revisao, não faz nada."""
    if parar.wait(25):
        return
    while not parar.is_set():
        c = sugestoes_bot.configuracao()
        if c["revisor"] and c["repo"]:
            revisor_rodada()
        if (c["bots"] or c["revisor"]) and c["repo"]:
            with _sug_trava:
                res = sugestoes_bot.coletar(c, log=lambda m: print(f"[sugestoes] {m}", flush=True))
            if res["erro"] or res["novas"]:
                print(f"[sugestoes] {res['novas']} nova(s), {res['triadas']} triada(s), {res['chamadas']} chamada(s)"
                      + (f"; ERRO: {res['erro'][:120]}" if res["erro"] else ""), flush=True)
        try:   # auditor dos amarelos do Placar (modelo barato; o segundo só no suspeito): só com auditor.ativo e xp.ativo
            import auditor_xp
            ca = auditor_xp.configuracao_auditor()
            if auditor_xp.ativo(ca):
                for n, veredito, issue in auditor_xp.auditar(log=lambda m: print(f"[auditor] {m}", flush=True), cfg=ca):
                    print(f"[auditor] #{n}: {veredito}" + (f" → issue #{issue}" if issue else ""), flush=True)
        except Exception as e:  # o auditor nunca derruba a coleta
            print(f"[auditor] ERRO: {type(e).__name__}: {str(e)[:150]}", flush=True)
        parar.wait(c["intervalo_min"] * 60)


def iniciar_sugestoes():
    parar = threading.Event()
    threading.Thread(target=sugestoes_laco, args=(parar,), daemon=True, name="sugestoes").start()
    threading.Thread(target=pronto_laco, args=(parar,), daemon=True, name="pronto").start()
    return parar


def sugestoes_get():
    """GET /api/sugestoes: contagem por PR e prioridade, itens abertos e o estado da última coleta (leitura de arquivo local)."""
    try:
        r = sugestoes_bot.resumo()
    except Exception as e:
        return 200, {"ok": True, "ativo": False, "por_pr": {}, "itens": [], "erro": str(e)[:200]}
    aviso = aviso_limite("rate limit") if r.get("limite_ate") and r["limite_ate"] > time.time() else ""
    return 200, dict(r, ok=True, limite=aviso, pronto=PRONTO)


def sugestoes_tratar(dados, ident):
    """POST /api/sugestoes/tratar {"id", "acao": encaminhada|ignorada|discutir|resolvida|reabrir, "nota"}: só o PC (rede.py)."""
    id_, acao, nota = dados.get("id"), dados.get("acao"), dados.get("nota") or ""
    if not isinstance(id_, (str, int)) or isinstance(id_, bool) or not str(id_).strip():
        return 400, {"ok": False, "erro": "id inválido"}
    if acao not in ACOES_SUGESTAO or not isinstance(nota, str):
        return 400, {"ok": False, "erro": "acao deve ser " + ", ".join(ACOES_SUGESTAO)}
    c = sugestoes_bot.configuracao()
    try:
        ok, msg = sugestoes_bot.tratar(c, id_, acao, nota)
    except TimeoutError:
        return 409, {"ok": False, "erro": "caixa de sugestões ocupada; tente de novo"}
    if not ok:
        return 404, {"ok": False, "erro": msg}
    item = next((x for x in sugestoes_bot.ler_caixa(c) if str(x["id"]) == str(id_).strip()), None)
    dados["pr"] = item.get("pr") if item else None   # vai para o histórico de ações (dados/acoes.jsonl)
    print(f"[sugestoes] {msg}", flush=True)
    return 200, {"ok": True, "mensagem": msg, "sugestoes": sugestoes_get()[1]}


SAUDE_VALIDADE = 300   # s entre cálculos (branches locais + últimos eventos + PRs em cache)
_saude = {"quando": 0.0, "dados": None}
_saude_trava = threading.Lock()


def sugestoes_para_alertas():
    """Fonte "sugestoes" do detector (e regra de "pronto" da saúde): o resumo da caixa + o PRONTO da thread de validações."""
    try:
        return dict(sugestoes_bot.resumo(), pronto=dict(PRONTO), pronto_carregado=PRONTO_CARREGADO.is_set())
    except Exception as e:
        # caixa ilegível com bots/revisor ligados: o detector pula os PRs nesta rodada em vez de cair no "só a
        # revisão" (alerta pr_pronto falso); sem `itens`, também não mexe nas sugestões
        try:
            c = sugestoes_bot.configuracao()
            configurado = bool(c["bots"] or c["revisor"])
        except Exception:
            configurado = True   # nem a configuração leu: na dúvida, pula os PRs (sem alerta falso)
        if configurado:
            return {"ativo": True, "pronto_carregado": False, "erro": str(e)[:200]}
        raise


def saude_pasta():
    """dados/ do escritório: saude.json, saude_ignorados.json e saude_pedidos.jsonl (saude.py)."""
    return PASTA / "dados"


def saude_atual():
    """Duplicados, círculos, PRs parados, cartões rascunho e comandos repetidos (saude.resumo), recalculado no máximo a cada SAUDE_VALIDADE e gravado em
    dados/saude.json (lido por `saude.py --pendentes`, no vigia do líder). As branches locais vêm da 1ª pasta de "projetos"."""
    with _saude_trava:
        if _saude["dados"] is not None and time.time() - _saude["quando"] < SAUDE_VALIDADE:
            return _saude["dados"]
        lista, sg = [], None
        if cfg()["github"]["repo"]:
            try:
                d = prs()
            except Exception:
                d = None
            try:
                sg = sugestoes_para_alertas()
            except Exception:
                sg = None
            lista = d.get("prs") if isinstance(d, dict) and not d.get("erro") and isinstance(d.get("prs"), list) else None
            if not isinstance(sg, dict) or sg.get("pronto_carregado") is False:
                lista = None   # sem a regra de "pronto" do painel (PRONTO não carregado, caixa ilegível): sem parado falso
        # lista None (GitHub fora, ou sem a regra do painel): só os círculos, que dependem só dos eventos locais
        try:
            eventos = banco.ler_eventos(0, 3000)[1]
        except Exception:
            eventos = []
        projetos = cfg()["projetos"]
        locais = saude.branches_locais(projetos[0]) if projetos and lista is not None else []
        cartoes = None   # Kanban não configurado ou com erro: sem "rascunhos" (nenhum rascunho conta como resolvido)
        try:
            k = kanban()
            if k.get("configurado") and not k.get("erro") and isinstance(k.get("cartoes"), list):
                cartoes = k["cartoes"]
        except Exception:
            pass
        dados = saude.resumo(lista, locais, eventos, time.time(), lambda pr: alertas.situacao_pr(pr, sg),
                             cfg()["alertas"]["parado_horas"], cartoes, cfg()["github"]["repo"])
        # só os círculos (GitHub fora ou PRONTO ainda não carregado, como logo depois de subir): tenta de novo em 60 s
        _saude.update(quando=time.time() - (SAUDE_VALIDADE - 60 if dados.get("sem_prs") else 0), dados=dados)
        try:   # resolvidos, ignorado/veredicto que expira e pedido cancelado (saude.rodada respeita sem_prs/sem_locais);
            # antes do saude.json: o --pendentes (outro processo) já acha o "desde" das chaves novas no ciclo
            r = saude.rodada(dados, saude_pasta())
            if any(r.values()):
                print(f"[saude] rodada: {json.dumps(r, ensure_ascii=False)[:200]}", flush=True)
        except Exception as e:
            print(f"[saude] rodada: {str(e)[:160]}", flush=True)
        try:
            arq = saude_pasta() / "saude.json"
            arq.parent.mkdir(parents=True, exist_ok=True)
            tmp = arq.with_suffix(".tmp")
            tmp.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
            tmp.replace(arq)
        except OSError:
            pass
        return dados


def silenciados_saude(dados=None):
    """Chaves que não alertam (agora): ignoradas no painel + falsos positivos da triagem não desfeitos + duplicados/círculos
    NOVOS esperando a triagem (até saude.SEGURAR_MIN; só com a triagem disponível). Não chama o modelo."""
    pasta = saude_pasta()
    tri = saude.ler_triagem(pasta)
    out = set(saude.ler_ignorados(pasta)) | saude.silenciados(tri)
    if dados is not None:
        try:
            out |= saude.segurados(dados, tri, saude.ler_ciclo(pasta), saude_triagem.disponivel(tri),
                                   max_por_chave=saude_triagem.MAX_POR_CHAVE_DIA)
        except Exception:
            pass
    return out


def _saude_para_alertas():
    d = saude_atual()
    return dict(d, ignorados=sorted(silenciados_saude(d)))


def triagem_saude(dados):
    """Triagem barata dos itens novos (saude_triagem.rodada): só na thread `saude`, depois de um cálculo que deu certo; usa
    os títulos dos PRs que já estão no cache do servidor (sem GitHub). Falha nunca derruba a thread."""
    try:
        d = _prs.dados   # só o que já está em cache (o saude_atual acabou de pedir os PRs): nenhuma chamada ao GitHub
        lista = d.get("prs") if isinstance(d, dict) and isinstance(d.get("prs"), list) else []
        for chave, v in saude_triagem.rodada(dados, lista, saude_pasta()):
            print(f"[saude] triagem {chave}: " + (v.get("erro") or ("problema → líder avisado" if v.get("problema") else
                                                                     "falso positivo (silenciado)")), flush=True)
    except Exception as e:
        print(f"[saude] triagem: {str(e)[:160]}", flush=True)


def saude_get():
    """GET /saude: saude_atual() + "ignorados" ({chave: {motivo, quando, origem}}), os últimos 20 "pedidos" ao líder (cada um
    com "entregue" e "cancelado"), os "resolvidos" das últimas 24 h e a "triagem" (modelo, veredictos, chamadas de hoje e
    teto). Os itens ignorados seguem na lista (o painel separa)."""
    pasta = saude_pasta()
    dados = dict(saude_atual(), ignorados=saude.ler_ignorados(pasta))
    limite = saude.ultimo_entregue(pasta) or 0
    ciclo = saude.ler_ciclo(pasta)
    canc = ciclo["cancelados"]
    dados["pedidos"] = [dict(p, entregue=p["ts"] <= limite and str(p["ts"]) not in canc, cancelado=str(p["ts"]) in canc)
                        for p in saude.ler_pedidos(pasta)[-20:]]
    agora = time.time()
    dados["resolvidos"] = [r for r in ciclo["resolvidos"] if agora - saude._num(r.get("quando")) < saude.RESOLVIDOS_H * 3600]
    tri = saude.ler_triagem(pasta)
    dados["triagem"] = {"modelo": saude_triagem.modelo_configurado(), "veredictos": tri["veredictos"],
                        "hoje": tri["hoje"] if tri["dia"] == time.strftime("%Y-%m-%d") else 0, "teto": saude_triagem.TETO_DIA}
    return dados


PRATICAS_VALIDADE = 600   # s entre validações das boas práticas (git curto e leitura de arquivos, mas por projeto)
_praticas = {"quando": 0.0, "dados": None, "thread": None}
_praticas_trava = threading.Lock()


def praticas_calcular():
    """boas_praticas.validar de cada pasta de "projetos" (o settings do usuário só é lido)."""
    projetos = None
    try:
        c = cfg()
        projetos = []
        for p in c["projetos"]:
            item = {"projeto": str(p), "nome": Path(p).name or str(p), "stacks": [], "testes": "", "itens": [], "erro": ""}
            try:
                if not Path(p).is_dir():
                    raise OSError("pasta não encontrada")
                escopo = boas_praticas.detectar_escopo(p)
                item.update(stacks=sorted(escopo["stacks"]), testes=escopo["testes"], itens=boas_praticas.validar(p, c))
            except Exception as e:
                item["erro"] = str(e)[:200]
            projetos.append(item)
    except Exception as e:
        print(f"[praticas] {str(e)[:160]}", flush=True)
    finally:
        with _praticas_trava:
            _praticas["thread"] = None
            if projetos is not None:
                _praticas.update(quando=time.time(), dados=projetos)


def versao_get():
    """GET /api/versao: a versão instalada, lida do VERSION do pacote ("" se faltar). Não consulta o GitHub."""
    try:
        local = (PASTA / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        local = ""
    return 200, {"local": local}


# caminho absoluto num texto: C:\... ou C:/..., \\servidor\..., /a/b... (pelo menos duas partes; "e/ou" e ".venv/" não)
sem_caminhos = saude.sem_caminhos   # texto sem caminhos absolutos (para o celular): cada um vira "…/<última parte>"


def _praticas_celular(p):
    """Projeto do /api/praticas para quem não é o PC: sem o campo projeto e sem caminhos absolutos nos textos."""
    out = {k: sem_caminhos(v) for k, v in p.items() if k != "projeto"}
    out["itens"] = [{k: sem_caminhos(v) for k, v in i.items()} for i in p.get("itens") or []]
    return out


def praticas_get(ident):
    """GET /api/praticas: resultado em cache; velho (ou ausente) dispara a validação numa thread e espera no máximo 3 s.
    Para quem não é o PC (celular), sem o caminho absoluto dos projetos (só o nome da pasta) nem caminhos nos textos."""
    with _praticas_trava:
        velho = _praticas["dados"] is None or time.time() - _praticas["quando"] >= PRATICAS_VALIDADE
        t = _praticas["thread"]
        if velho and t is None:
            t = _praticas["thread"] = threading.Thread(target=praticas_calcular, name="praticas", daemon=True)
            t.start()
    if t is not None and _praticas["dados"] is None:
        t.join(3)
    with _praticas_trava:
        dados, quando = _praticas["dados"], _praticas["quando"]
    pc = ident.get("permissao") == "pc"
    projetos = [dict(p) if pc else _praticas_celular(p) for p in dados or []]
    return 200, {"ok": True, "calculando": dados is None, "quando": quando, "validade": PRATICAS_VALIDADE,
                 "projetos": projetos}


def _validar_saude(dados, campo_texto, limite):
    """(chave, texto) válidos do corpo do POST, ou (None, erro)."""
    chave, texto = dados.get("chave"), dados.get(campo_texto, "")
    if not saude.chave_valida(chave):
        return None, ("chave inválida (dup:<branches>, circulo:<agente>:<arquivo>, parado:<n>, rascunho:<id do item> ou "
                      "repetido:<agente>:<assinatura>, até 300 caracteres)")
    if texto is None:
        texto = ""
    if not isinstance(texto, str) or len(texto) > limite:
        return None, f"{campo_texto} deve ser texto de até {limite} caracteres"
    try:   # JSON com surrogate solto ("\ud800") vira str que não codifica: recusa aqui, antes de gravar
        chave.encode("utf-8"), texto.encode("utf-8")
    except UnicodeError:
        return None, "texto com caractere inválido (não é UTF-8)"
    return chave, texto


def saude_ignorar(dados, ident):
    """POST /api/saude/ignorar {"chave", "ignorar": true|false, "motivo"}: some (ou volta) dos alertas e do --pendentes."""
    chave, motivo = _validar_saude(dados, "motivo", saude.MAX_MOTIVO)
    if chave is None:
        return 400, {"ok": False, "erro": motivo}
    if not isinstance(dados.get("ignorar"), bool):
        return 400, {"ok": False, "erro": "ignorar deve ser true ou false"}
    try:
        ign = saude.definir_ignorado(chave, dados["ignorar"], motivo, ident.get("nome") or "PC", saude_pasta(),
                                     ua=dados.get("_ua") or "")
    except OSError as e:
        return 500, {"ok": False, "erro": "não consegui gravar: " + str(e)[:150]}
    except (ValueError, TypeError) as e:
        return 400, {"ok": False, "erro": "entrada inválida: " + str(e)[:150]}
    dados["_detalhe"] = ("ignorar " if dados["ignorar"] else "reativar ") + chave   # histórico de ações (dados/acoes.jsonl)
    dados["pr"] = int(chave.split(":", 1)[1]) if chave.startswith("parado:") else None
    print(f"[saude] {'ignorado' if dados['ignorar'] else 'reativado'}: {chave}", flush=True)
    return 200, {"ok": True, "ignorados": ign}


def saude_avisar(dados, ident):
    """POST /api/saude/avisar {"chave", "texto"}: grava um pedido em dados/saude_pedidos.jsonl; o vigia do líder o entrega
    (`saude.py --pendentes` → "[vigia saude] ... pedido do desenvolvedor: ..."). Não manda nada a sessão nenhuma."""
    chave, nota = _validar_saude(dados, "texto", saude.MAX_TEXTO)
    if chave is None:
        return 400, {"ok": False, "erro": nota}
    # só tipo, números e a chave marcada como dado (nada de título de PR); o recado digitado vai em campo separado
    texto = saude.descrever(chave, _saude["dados"])   # o cache basta (não recalcula a saúde só para descrever)
    try:
        ped = saude.registrar_pedido(chave, texto, saude_pasta(), recado=nota, origem=ident.get("nome") or "PC",
                                     ua=dados.get("_ua") or "")
    except OSError as e:
        return 500, {"ok": False, "erro": "não consegui gravar: " + str(e)[:150]}
    except (ValueError, TypeError) as e:
        return 400, {"ok": False, "erro": "entrada inválida: " + str(e)[:150]}
    dados["_detalhe"] = "avisar " + chave
    dados["pr"] = int(chave.split(":", 1)[1]) if chave.startswith("parado:") else None
    print(f"[saude] pedido ao líder: {chave}", flush=True)
    return 200, {"ok": True, "pedido": dict(ped, entregue=False)}


def saude_triagem_post(dados, ident):
    """POST /api/saude/triagem {"chave", "acao": "desfazer"}: desfaz o "falso positivo" da triagem (o item volta a alertar)."""
    chave, _ = _validar_saude(dados, "_nada", 0)
    if chave is None:
        return 400, {"ok": False, "erro": "chave inválida"}
    if dados.get("acao") != "desfazer":
        return 400, {"ok": False, "erro": "acao deve ser 'desfazer'"}
    try:
        ok = saude_triagem.desfazer(chave, ident.get("nome") or "PC", dados.get("_ua") or "", saude_pasta())
    except OSError as e:
        return 500, {"ok": False, "erro": "não consegui gravar: " + str(e)[:150]}
    if not ok:
        return 404, {"ok": False, "erro": "este item não está marcado como falso positivo pela triagem"}
    dados["_detalhe"] = "desfazer falso positivo " + chave
    dados["pr"] = int(chave.split(":", 1)[1]) if chave.startswith("parado:") else None
    print(f"[saude] falso positivo desfeito: {chave}", flush=True)
    return 200, {"ok": True, "triagem": saude.ler_triagem(saude_pasta())["veredictos"]}


ACOES_SAUDE = {"/api/saude/ignorar": saude_ignorar, "/api/saude/avisar": saude_avisar, "/api/saude/triagem": saude_triagem_post}


def saude_laco(parar):
    """Grava dados/saude.json a cada SAUDE_VALIDADE mesmo com os alertas desligados (o vigia do líder lê o arquivo)."""
    if parar.wait(30):
        return
    while not parar.is_set():
        try:
            dados = saude_atual()
        except Exception as e:
            dados = None
            print(f"[saude] {str(e)[:160]}", flush=True)
        if isinstance(dados, dict) and not dados.get("erro"):
            triagem_saude(dados)   # fora do caminho das requisições; no máximo MAX_POR_RODADA chamadas por rodada
        parar.wait(SAUDE_VALIDADE)


def criar_alertas(obj_rede):
    """Liga o detector aos dados que o servidor já tem (PRs em cache, placar de XP, eventos, escalonamentos opcionais)."""
    global ALERTAS

    def placar():
        return _ler_json(XP_PLACAR, None) if cfg()["xp"]["ativo"] else None

    def escalonamentos():   # opcional: alertas.escalonamentos = caminho de um JSON {"semana": [{cartao, motivo, aberto, fechado, resultado}]}
        caminho = cfg()["alertas"].get("escalonamentos") or ""
        return _ler_json(caminho, None) if caminho and Path(caminho).is_file() else None
    fontes = {"prs": prs, "placar": placar, "eventos": lambda desde: ler_eventos(desde), "escalonamentos": escalonamentos,
              "sugestoes": sugestoes_para_alertas, "cota": VIGIA.resumo,
              # itens ignorados no painel Saúde, falsos positivos da triagem e itens novos esperando a triagem não alertam
              "saude": _saude_para_alertas}
    # "sugestoes" leva o PRONTO da thread de validações: o alerta pr_pronto usa a mesma regra do painel PRs (prs.js);
    # antes da 1ª rodada do PRONTO (pronto_carregado False) o detector não mexe no estado dos PRs
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
        return 200, {"ok": True, "ativo": A.opcoes["ativo"], "alertas": lista, "ultimo": ultimo, "titulo": TITULO(), "hoje": A.hoje(),
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



SUF_BLOQUEADOS = (".py", ".bat", ".sh", ".json", ".md", ".txt")   # nunca servidos como estáticos (servidor.caminho_bloqueado)
class Handler(rede.HandlerSeguro):
    def api_post(self, rota, dados, ident):
        dados.pop("_detalhe", None)   # só o servidor preenche (vai para o histórico de ações)
        if rota in ACOES_SAUDE:
            return ACOES_SAUDE[rota](dados, ident)
        if rota.startswith("/api/push/"):
            return alertas_post(rota, dados, ident)
        if rota == "/api/sugestoes/tratar":
            return sugestoes_tratar(dados, ident)
        return acao_xp(rota, dados, ident) if rota in ACOES_XP else None

    def api_get(self, rota, qs, ident):
        if rota == "/api/sugestoes":
            return sugestoes_get()
        if rota == "/api/praticas":
            return praticas_get(ident)
        if rota == "/api/versao":
            return versao_get()
        return alertas_get(rota, qs, ident)

    def caminho_bloqueado(self):
        # não expõe dados brutos, configuração com caminhos locais nem scripts.
        # Confere o caminho DECODIFICADO e normalizado, como o SimpleHTTPRequestHandler o resolve: antes, /%64ados/...,
        # /x/../dados/..., %2epy, "dados." e "dados::$DATA" (Windows) passavam e serviam dados/ (sessões, tokens CSRF).
        try:
            bruto = unquote(urlparse(self.path).path, errors="strict").replace("\\", "/")
        except (UnicodeDecodeError, ValueError):
            return True
        if ":" in bruto or "\x00" in bruto:
            return True   # fluxo alternativo do NTFS (dados::$DATA) e byte nulo
        partes = [x.rstrip(". ").lower() for x in posixpath.normpath("/" + bruto).split("/") if x]
        if partes and (partes[0] == "dados" or any(x.startswith(".") or x == "" for x in partes)):
            return True
        if partes and partes[-1].endswith(SUF_BLOQUEADOS):   # nome normalizado ("/servidor.py/." conta)
            return True
        try:   # o arquivo que seria servido precisa ficar dentro da pasta do escritório e fora de dados/
            alvo = Path(self.translate_path(self.path)).resolve()
            base = Path(getattr(self, "directory", None) or PASTA).resolve()
            rel = alvo.relative_to(base)
        except (ValueError, OSError):
            return True
        if alvo.name.rstrip(". ").lower().endswith(SUF_BLOQUEADOS):   # nome real (cobre o nome curto 8.3 do Windows)
            return True
        return bool(rel.parts) and rel.parts[0].rstrip(". ").lower() == "dados"

    def rotas_get(self):
        url = urlparse(self.path)
        qs = parse_qs(url.query)
        if url.path == "/config":
            return self.responder(config_publica())
        if url.path == "/eventos":
            qs_rep = parse_qs(url.query, keep_blank_values=True)   # "de=" vazio é erro do replay, não o modo antigo
            if "de" in qs_rep or "ate" in qs_rep:   # replay do dia: filtro por tempo, paginado por id
                codigo, dados = eventos_periodo(qs_rep)
                return self.responder(dados, codigo=codigo)
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
            return self.responder(com_cota(kanban()))
        if url.path == "/prs":
            return self.responder(com_cota(prs("forcar" in qs)))
        if url.path == "/xp":
            if not cfg()["xp"]["ativo"]:
                return self.responder({"ativo": False, "agentes": {}})
            try:
                corpo = json.loads(XP_PLACAR.read_bytes())
                corpo["custos"] = custos()
                try:   # limites do plano (5 h e semana) gravados pela statusline_uso.py
                    corpo["uso"] = banco.uso_resumo()
                except Exception:
                    corpo["uso"] = None
            except (OSError, ValueError) as e:
                corpo = {"agentes": {}, "erro": f"placar de XP indisponível (rode 'python xp.py'): {str(e)[:120]}"}
            return self.responder(corpo)
        if url.path == "/saude":
            try:
                return self.responder(saude_get())
            except Exception as e:
                return self.responder({"erro": str(e)[:200]})
        if url.path == "/grafo":   # painel 🗺️ Arquitetura: index + drift + validação resumida (thread grafo)
            o = opcoes_grafo()
            return self.responder(grafo_painel.resposta(ativo=o["ativo"], raiz=o["repo"] or "", ref=o["ref"],
                                                        arquivo=o["arquivo"]))
        if url.path == "/manifest.webmanifest":
            return self.responder(json.dumps(manifesto(), ensure_ascii=False).encode("utf-8"), "application/manifest+json; charset=utf-8")
        if url.path in ("/", "/index.html"):
            texto = index_html()
            self.csp_html = texto  # o hash do importmap inline entra na Content-Security-Policy
            return self.responder(texto.encode("utf-8"), "text/html; charset=utf-8")
        self.servir_estatico()


def opcoes_grafo():
    """Opções da thread e da rota do grafo: bloco "grafo" do config.json e o projeto (1ª pasta de "projetos")."""
    c = cfg()
    g, projetos = c["grafo"], c["projetos"]
    return {"ativo": bool(g["ativo"]), "repo": str(projetos[0]) if projetos else "", "ref": g["ref"], "arquivo": g["arquivo"],
            "intervalo_min": g["intervalo_min"]}


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
    obj = Handler.rede = rede.Rede(PASTA, em_rede, tailscale)
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
    parar_sugestoes = iniciar_sugestoes()
    parar_cota = VIGIA.iniciar()
    threading.Thread(target=saude_laco, args=(parar_cota,), daemon=True, name="saude").start()
    parar_grafo = threading.Event()   # painel 🗺️ Arquitetura: na partida (5 s) e a cada grafo.intervalo_min; só lê o projeto
    threading.Thread(target=grafo_painel.laco, args=(parar_grafo, opcoes_grafo), daemon=True, name="grafo").start()
    print(f"Cota do GitHub: vigia a cada {cota.INTERVALO // 60} min (dados/github_cota.jsonl)")
    cfg_sug = sugestoes_bot.configuracao()
    print("Sugestões dos bots de revisão: " + (f"coleta a cada {cfg_sug['intervalo_min']} min ({', '.join(cfg_sug['bots'])}; "
          + ("triagem " + cfg_sug["modelo"] if cfg_sug["modelo"] else "sem triagem") + ")" if cfg_sug["bots"] and cfg_sug["repo"]
          else "desligadas (github.bots_revisao vazio no config.json)"))
    if cfg_sug["revisor"]:
        print("Revisor de código próprio (revisor_ia.py): ligado — revisa cada commit novo de PR antes da coleta"
              + ("" if cfg_sug["repo"] else " (SEM github.repo: não vai rodar)"))
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
        parar_sugestoes.set()
        parar_cota.set()
        parar_grafo.set()
        servidor.server_close()
        for s in extras:
            s.shutdown()
            s.server_close()


if __name__ == "__main__":
    main()
