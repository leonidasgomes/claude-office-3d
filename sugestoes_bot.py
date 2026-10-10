"""Coletor das sugestões do bot de revisão (somente biblioteca padrão; sem tokens, exceto a triagem opcional).

Bots de revisão (Codex, CodeRabbit, Copilot...) deixam comentários em linha de código e revisões nos PRs. Este script junta
tudo numa caixa local para o líder do time decidir o que corrigir, ignorar ou levar a você, sem ninguém abrir o GitHub à mão.
Custo de API mínimo (REST pelo `gh`, com ETag: resposta 304 não conta no limite):
  - 1 chamada a /pulls/comments?since=<último> (traz os comentários de TODOS os PRs; ETag guardado);
  - 1 chamada a /pulls?state=open (quais PRs estão abertos, branch, autor, rótulos; ETag guardado);
  - reviews (/pulls/{n}/reviews) de CADA PR aberto, a cada coleta (desde a 1.4.0; sem ETag; até 100 PRs abertos).
Triagem barata e opcional: se há itens novos, UMA chamada de `claude -p` com um modelo pequeno (padrão Haiku), sem
ferramentas, sugere para cada item corrigir | ignorar | discutir. Falhou? Os itens ficam "nova" e o líder tria.

Configuração (config.json): github.repo, github.bots_revisao (lista de logins; vazia = desligado), github.times e
sugestoes.{triagem_modelo, intervalo_min, janela_dias}. Veja a seção "Sugestões do bot de revisão" do INSTALACAO.md.

Uso:  python sugestoes_bot.py [--coletar]          coleta (padrão) e imprime um resumo de uma linha
      python sugestoes_bot.py --pendentes          NADA, ou resumo compacto para o líder (máx. ~25 linhas)
      python sugestoes_bot.py --tratar <id> --acao encaminhada|ignorada|discutir|resolvida|reabrir [--nota "..."]
      python sugestoes_bot.py --listar [--todas]   itens abertos (ou todos)
      python sugestoes_bot.py --pendentes --pr <n> só as do PR n (o dono trata as do próprio PR antes de avisar o líder;
                                                   vale também com --listar)
      python sugestoes_bot.py --sem-triagem        (com --coletar) não chama o modelo nesta rodada
      python sugestoes_bot.py --recoletar          (com --coletar) relê a janela inteira (janela_dias), uma vez; sem duplicar
      python sugestoes_bot.py --pronto <n>         OK (+ avisos), ou o que ainda segura o merge do PR n (sugestões, bots atrasados)

Estado em dados/sugestoes/estado.json e caixa em dados/sugestoes/caixa.jsonl (fora do git).
Situação de cada item: nova -> triada -> encaminhada | ignorada | discutir -> resolvida (arquivada = PR já fechado).
"""
import json
import hashlib
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent

# ---- Configuração: vem do config.json (github.repo, github.bots_revisao, github.times e o bloco "sugestoes") ----------
import configuracao as _pacote  # noqa: E402  (configuracao.py, da mesma pasta)

PASTA = RAIZ / "dados" / "sugestoes"
GLOSSARIO = RAIZ / "glossario_triagem.md"   # contexto do projeto para a triagem (editável)


def config_base(projeto=None):
    """Dict da configuração: repo, bots (logins do bot de revisão; lista vazia = desligado), modelo da triagem ("" desliga),
    intervalo_min, janela_dias, times (rótulo do PR -> agente), agentes, publicar_status, gh e pasta. Tudo do config.json do pacote."""
    c = _pacote.carregar()
    g, s = c["github"], c["sugestoes"]
    cfg={"repo": g["repo"], "bots": list(g["bots_revisao"]), "modelo": s["triagem_modelo"],
            "revisor": bool((c.get("revisor") or {}).get("ativo")),
            "publicar_status": g["publicar_status"],   # status `revisor-ia`/`sugestoes` no commit (merge automático)
            "intervalo_min": s["intervalo_min"], "janela_dias": s["janela_dias"], "times": dict(g["times"]),
            "agentes": [a["nome"] for a in c["agentes"]], "gh": _pacote.localizar_gh() or "gh", "pasta": PASTA}
    if projeto is not None:
        from politica_painel import snapshot
        from gestao_cli import pasta_dados,RAIZ as app
        from funcionarios import id_projeto
        raiz=Path(projeto).resolve();politica,versao,_=snapshot(raiz)
        if not politica['ativo'] or not politica['kanban']['repo']:raise ValueError('Projeto sem gestão/repositório')
        repo=politica['kanban']['repo'];base=pasta_dados(raiz)
        pasta=base/'sugestoes'/hashlib.sha256(repo.casefold().encode()).hexdigest()[:20]
        if (not base.resolve().is_relative_to(app.resolve()) or not pasta.resolve().is_relative_to(base.resolve())
            or pasta.is_symlink() or any((pasta/n).is_symlink() for n in ('estado.json','caixa.jsonl'))):raise ValueError('Pasta de sugestões inválida')
        cfg.update(repo=repo,bots=list(politica['sugestoes']['bots']) if politica['sugestoes']['ativo'] else [],
                   ativo=politica['sugestoes']['ativo'],modelo='',revisor=False,publicar_status=False,
                   times={e['nome']:e['nome'] for e in politica['equipes']},agentes=[e['nome'] for e in politica['equipes']],
                   pasta=pasta,projeto=raiz,projeto_id=id_projeto(raiz),politica_versao=versao)
        if politica['sugestoes']['triagem']:
            from gestao_projeto import executor
            cfg['triagem_provider']=executor(politica,papel='diretor')
    return cfg
# ---- fim da configuração -------------------------------------------------------------------------------------------------

SITUACOES = ("nova", "triada", "encaminhada", "ignorada", "discutir", "resolvida", "arquivada")
ABERTAS = ("nova", "triada", "discutir")      # aparecem no painel do escritório
PENDENTES = ("nova", "triada")                # o que o líder ainda precisa decidir
SEGURAM_MERGE = ("nova", "triada", "encaminhada")   # sem decisão ou mandada ao colega e ainda não corrigida
ESPERA_BOTS_MIN = 15                          # PR novo sem revisão de bot: espera esse tempo antes do "pronto"
PRAZO_BOT_MIN = 30                            # bot "por push" sem revisar o commit atual depois disso vira aviso, não trava
ACOES_TRATAR = {"encaminhada": "encaminhada", "ignorada": "ignorada", "discutir": "discutir", "resolvida": "resolvida"}
PRIORIDADES = ("P0", "P1", "P2", "P3", "?")
MAX_TEXTO = 1200
MAX_PAGINAS = 10          # teto de páginas de comentários por coleta (a próxima continua de onde parou)
MAX_TRIAGEM = 30
TIMEOUT_TRIAGEM = 120
GUARDAR_ARQUIVADAS_DIAS = 30

RE_BADGE = re.compile(r"!\[(P[0-3])\s*Badge\]\([^)]*\)", re.I)
RE_IMG = re.compile(r"!\[[^\]]*\]\([^)]*\)")
RE_TAGS = re.compile(r"</?sub>", re.I)
RE_RODAPE = re.compile(r"\n+\s*Useful\?\s*React with.*\Z", re.S | re.I)
RE_DETALHES = re.compile(r"<details>.*?</details>", re.S | re.I)
RE_LIMITE = re.compile(r"rate limit", re.I)
# Revisão geral do Copilot ("Copilot review overview"): só um índice dos achados em linha, com a gravidade de cada um.
RE_COPILOT_INDICE = re.compile(r"<!--\s*ccr-overview", re.I)
RE_COPILOT_GRAVIDADE = re.compile(r'alt="(critical|high|medium|low) severity"[^\n]*?\(#discussion_r(\d+)\)', re.I)
PRIO_GRAVIDADE = {"critical": "P0", "high": "P1", "medium": "P2", "low": "P3"}
# Um bot, dois logins: o Copilot assina a revisão como copilot-pull-request-reviewer[bot] e o comentário em linha como "Copilot".
APELIDOS_BOT = {"copilot-pull-request-reviewer": ("copilot",)}


class ErroApi(Exception):
    def __init__(self, status, mensagem, reset=0):
        super().__init__(f"HTTP {status}: {mensagem}")
        self.status, self.mensagem, self.reset = status, mensagem, reset

    @property
    def limite(self):
        return self.status in (403, 429) and bool(RE_LIMITE.search(self.mensagem))


def configuracao(projeto=None):
    cfg = config_base(projeto) if projeto is not None else config_base()
    cfg["pasta"] = Path(cfg["pasta"])
    return cfg

def conferir_projeto(cfg):
    if cfg.get('projeto') is not None:
        from politica_painel import snapshot
        if snapshot(cfg['projeto'])[1]!=cfg['politica_versao']:raise ValueError('Política mudou; recarregue o projeto')


# ---------------------------------------------------------------- arquivos (estado, caixa, trava)
def _agora():
    return datetime.now(timezone.utc)


def _ler_iso(texto):
    """datetime de um ISO do GitHub ("2026-10-06T01:51:53Z"), ou None."""
    try:
        return datetime.fromisoformat(str(texto).replace("Z", "+00:00")) if texto else None
    except ValueError:
        return None


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class trava:
    """Trava entre processos (servidor e linha de comando) por arquivo; só envolve leitura-e-gravação, nunca rede."""

    def __init__(self, pasta, espera=30, expirar=True):
        self.arq, self.espera = Path(pasta) / ".trava", espera
        self.expirar=expirar

    def __enter__(self):
        self.arq.parent.mkdir(parents=True, exist_ok=True)
        fim = time.time() + self.espera
        while True:
            try:
                os.close(os.open(str(self.arq), os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                return self
            except FileExistsError:
                try:
                    if self.expirar and time.time() - self.arq.stat().st_mtime > 120:   # protocolo legado
                        self.arq.unlink()
                        continue
                except OSError:
                    pass
                if time.time() > fim:
                    raise TimeoutError("caixa de sugestões ocupada")
                time.sleep(0.1)

    def __exit__(self, *a):
        try:
            self.arq.unlink()
        except OSError:
            pass


def _gravar(arq, texto):
    tmp = Path(str(arq) + ".tmp")
    tmp.write_text(texto, encoding="utf-8")
    os.replace(tmp, arq)

def trava_caixa(cfg,espera=30):
    return trava(cfg['pasta'],espera=espera,expirar=cfg.get('projeto') is None)


def ler_estado(cfg):
    try:
        e = json.loads((cfg["pasta"] / "estado.json").read_text(encoding="utf-8"))
        if cfg.get('projeto') and not isinstance(e,dict):raise ValueError('Estado de sugestões inválido')
        return e if isinstance(e, dict) else {}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        if cfg.get('projeto'):raise
        return {}


def gravar_estado(cfg, est):
    conferir_projeto(cfg)
    cfg["pasta"].mkdir(parents=True, exist_ok=True)
    _gravar(cfg["pasta"] / "estado.json", json.dumps(est, ensure_ascii=False, indent=1))


def ler_caixa(cfg):
    itens = []
    try:
        linhas = (cfg["pasta"] / "caixa.jsonl").read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return itens
    except OSError:
        if cfg.get('projeto'):raise
        return itens
    for t in linhas:
        try:
            x = json.loads(t)
        except ValueError:
            if cfg.get('projeto') and t.strip():raise ValueError('Caixa de sugestões inválida')
            continue
        if cfg.get('projeto') and (not isinstance(x,dict) or x.get('id') is None):raise ValueError('Item de sugestões inválido')
        if isinstance(x, dict) and x.get("id") is not None:
            itens.append(x)
    return itens


def gravar_caixa(cfg, itens):
    conferir_projeto(cfg)
    cfg["pasta"].mkdir(parents=True, exist_ok=True)
    _gravar(cfg["pasta"] / "caixa.jsonl", "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in itens))


# ---------------------------------------------------------------- GitHub (REST pelo gh, com ETag)
def gh_api(cfg, caminho, etag=None, timeout=90):
    """(status, corpo JSON ou None, cabeçalhos em minúsculas). 304 volta com corpo None (não conta no limite).
    Erros viram ErroApi (com .limite True quando é o limite da API)."""
    args = [cfg["gh"], "api", "-i", caminho]
    if etag:
        args += ["-H", f"If-None-Match: {etag}"]
    try:
        r = subprocess.run(args, capture_output=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as e:
        raise ErroApi(0, f"gh indisponível ({str(e)[:100]})")
    saida = r.stdout.decode("utf-8", errors="replace")
    erro = r.stderr.decode("utf-8", errors="replace").strip()
    m = re.match(r"HTTP/[\d.]+\s+(\d+)", saida)
    if not m:
        raise ErroApi(0, (erro or saida or "gh falhou").strip()[:300])
    status = int(m.group(1))
    partes = re.split(r"\r?\n\r?\n", saida, maxsplit=1)
    cab_txt, corpo = partes[0], (partes[1] if len(partes) > 1 else "")
    cab = {}
    for linha in cab_txt.splitlines()[1:]:
        k, _, v = linha.partition(":")
        cab[k.strip().lower()] = v.strip()
    if status == 304:
        return 304, None, cab
    try:
        dados = json.loads(corpo) if corpo.strip() else None
    except ValueError:
        dados = None
    if status >= 400:
        msg = (dados.get("message") if isinstance(dados, dict) else "") or erro or f"HTTP {status}"
        try:
            reset = int(cab.get("x-ratelimit-reset", "0"))
        except ValueError:
            reset = 0
        raise ErroApi(status, str(msg)[:300], reset)
    return status, dados, cab


def eh_bot(login, bots):
    """O login é de um dos bots configurados? Compara sem diferenciar maiúsculas e sem o sufixo "[bot]"."""
    n = lambda t: str(t or "").strip().lower().removesuffix("[bot]")
    nomes = {n(b) for b in bots}
    for b in list(nomes):
        nomes.update(APELIDOS_BOT.get(b, ()))
    return n(login) in nomes


def _links_proxima(cab):
    return 'rel="next"' in cab.get("link", "")


# ---------------------------------------------------------------- extração
def limpar_texto(corpo):
    t = RE_DETALHES.sub("", corpo or "")
    t = RE_RODAPE.sub("", t).strip()
    return t


def extrair(corpo):
    """(prioridade, título, texto) de um comentário do bot. Sem badge = prioridade '?'."""
    b = limpar_texto(corpo)
    m = RE_BADGE.search(b[:400])
    prio = m.group(1).upper() if m else "?"
    m2 = RE_PRIO_REVISOR.match(b)              # revisor_ia.py: "**P2 — Título**"
    if m2:
        prio, b = m2.group(1), "**" + b[m2.end():]
    b = re.sub(r"\n*<sub>\[revisor-ia\].*?</sub>\s*$", "", b, flags=re.S)
    primeira, _, resto = b.partition("\n")
    titulo, texto = "", b
    if primeira.lstrip().startswith("**"):
        titulo = RE_TAGS.sub("", RE_IMG.sub("", primeira)).replace("**", "").strip()
        texto = resto.strip()
    if not titulo:
        sem = RE_TAGS.sub("", RE_IMG.sub("", texto)).strip()
        titulo = re.split(r"(?<=[.!?])\s|\n", sem, maxsplit=1)[0][:100] if sem else "(sem título)"
    texto = RE_TAGS.sub("", RE_IMG.sub("", texto)).strip()
    if len(texto) > MAX_TEXTO:
        texto = texto[:MAX_TEXTO - 1].rstrip() + "…"
    return prio, titulo[:160], texto


def _eh_resumo_vazio(corpo):
    """Revisão só com a casca do bot (sem achado próprio): não vira item."""
    if MARCA_REVISOR + " Revisão automática" in (corpo or "") and "\n- **" not in (corpo or ""):
        return True   # resumo do revisor_ia.py sem achado no corpo
    t = RE_TAGS.sub("", RE_IMG.sub("", limpar_texto(corpo)))
    t = re.sub(r"[#*_`>\-\s]+", " ", t).strip().lower()
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    casca = ("codex review", "here are some automated review suggestions", "reviewed commit",
             "didn t find any major issues", "didn t find any", "about codex in github", "automated review suggestions for this pull request")
    resto = t
    for c in casca:
        resto = resto.replace(c, " ")
    resto = re.sub(r"[0-9a-f]{7,40}", " ", resto)
    resto = re.sub(r"\b(for|this|pull|request|here|are|some|the|and|a|of)\b", " ", resto)
    return len(resto.split()) < 4


def _time_do_pr(cfg, rotulos):
    mapa = {k.lower(): v for k, v in cfg["times"].items()}
    for r in rotulos or []:
        n = r.get("name", "") if isinstance(r, dict) else str(r)
        if n.lower() in mapa:
            return mapa[n.lower()]
    return ""


def _numero_pr(url):
    try:
        return int(str(url).rstrip("/").rsplit("/", 1)[1])
    except (IndexError, ValueError):
        return 0


def _item(cfg, c, prs, tipo="linha", prefixo=""):
    prio, titulo, texto = extrair(c.get("body") or "")
    n = _numero_pr(c.get("pull_request_url") or c.get("pull_request_url", ""))
    pr = prs.get(str(n))
    return {"id": f"{prefixo}{c['id']}", "tipo": tipo, "pr": n, "arquivo": c.get("path") or "",
            "linha": c.get("line") or c.get("original_line"), "prioridade": prio, "titulo": titulo, "texto": texto,
            "link": c.get("html_url") or "", "criado": c.get("created_at") or c.get("submitted_at") or "",
            "autor": (c.get("user") or {}).get("login", ""),
            "situacao": "nova" if pr else "arquivada",
            "branch": (pr or {}).get("branch", ""), "pr_autor": (pr or {}).get("autor", ""),
            "time_pr": (pr or {}).get("time", ""), "pr_titulo": (pr or {}).get("titulo", ""),
            "acao_sugerida": "", "motivo": "", "time_sugerido": "", "nota": "", "tratada_em": "", "coletada_em": _iso(_agora())}


# ---------------------------------------------------------------- coleta
def _baixar_prs_abertos(cfg, est):
    """Atualiza est['prs'] ({numero: {branch, autor, titulo, time, atualizado}}). Devolve o número de chamadas contadas."""
    if cfg.get('projeto') is not None:
        todos=[]
        for pagina in range(1,MAX_PAGINAS+1):
            status,lote,_=gh_api(cfg,f"repos/{cfg['repo']}/pulls?state=open&per_page=100&page={pagina}")
            if status!=200 or not isinstance(lote,list):raise ValueError('Lista de PRs do projeto incompleta')
            todos.extend(lote)
            if len(lote)<100:break
        else:raise ValueError('Limite da lista de PRs do projeto; não arquivar sugestões')
        est['prs']={str(p['number']):{'branch':(p.get('head') or {}).get('ref',''),'autor':(p.get('user') or {}).get('login',''),
            'titulo':p.get('title',''),'time':_time_do_pr(cfg,p.get('labels')),'url':p.get('html_url',''),'atualizado':p.get('updated_at','')} for p in todos}
        est.pop('etag_prs',None);return pagina
    status, dados, cab = gh_api(cfg, f"repos/{cfg['repo']}/pulls?state=open&per_page=100", est.get("etag_prs"))
    if status == 304 or not isinstance(dados, list):
        return 0
    est["prs"] = {str(p["number"]): {"branch": (p.get("head") or {}).get("ref", ""), "autor": (p.get("user") or {}).get("login", ""),
                                     "titulo": p.get("title", ""), "time": _time_do_pr(cfg, p.get("labels")),
                                     "url": p.get("html_url", ""), "atualizado": p.get("updated_at", "")} for p in dados}
    est["etag_prs"] = cab.get("etag", "")
    return 1


def _baixar_comentarios(cfg, est):
    """Comentários novos (de todos os PRs) desde o cursor. Devolve (lista, chamadas contadas)."""
    desde = est.get("since") or _iso(_agora() - timedelta(days=cfg["janela_dias"]))
    base = f"repos/{cfg['repo']}/pulls/comments?since={desde}&sort=created&direction=asc&per_page=100"
    etag = est.get("etag_comentarios") if est.get("etag_url") == base else None
    todos, chamadas = [], 0
    for pagina in range(1, MAX_PAGINAS + 1):
        url = base if pagina == 1 else f"{base}&page={pagina}"
        status, dados, cab = gh_api(cfg, url, etag if pagina == 1 else None)
        if status == 304:
            return [], 0
        chamadas += 1
        if pagina == 1:
            est["etag_url"], est["etag_comentarios"] = base, cab.get("etag", "")
        todos += dados if isinstance(dados, list) else []
        if not isinstance(dados, list) or len(dados) < 100 or not _links_proxima(cab):
            break
    else:
        est["etag_url"] = ""   # parou no teto: a próxima rodada continua do cursor novo
    if todos:
        est["since"] = max(c.get("created_at", "") for c in todos) or desde
    return todos, chamadas


MARCA_REVISOR = "[revisor-ia]"   # revisor de código próprio (revisor_ia.py): comenta pela conta do usuário com esta marca
RE_PRIO_REVISOR = re.compile(r"^\*\*(P[0-3])\s*—\s*")
RE_SEM_COTA = re.compile(r"unable to review this pull request because .{0,80}quota", re.I | re.S)
RE_ACHADO_INDICE = re.compile(r"<details>\s*<summary>(.*?)</summary>\s*`([^`]+)`\s*(.*?)</details>", re.S)
RE_ALT_GRAVIDADE = re.compile(r'alt="(critical|high|medium|low) severity"', re.I)


def _achados_do_indice(corpo):
    """[(arquivo:linha, título, texto, prioridade)] da seção "Previously missed" do índice do Copilot (achados sem
    comentário em linha). Formato: <details><summary><picture alt="Low severity"> Título</summary> `arq:linha` texto."""
    corpo = (corpo or "").replace("\u200b", "")
    i = corpo.find("Previously missed")
    if i < 0:
        return []
    saida = []
    for resumo, local, texto in RE_ACHADO_INDICE.findall(corpo[i:]):
        g = RE_ALT_GRAVIDADE.search(resumo)
        titulo = re.sub(r"<[^>]+>", "", re.sub(r"<picture>.*?</picture>", "", resumo, flags=re.S)).strip()
        if texto.strip():
            saida.append((local.strip(), titulo, re.sub(r"\s+", " ", texto).strip(),
                          PRIO_GRAVIDADE[g.group(1).lower()] if g else "P3"))
    return saida


def _revisoes(cfg, n, prs, existentes):
    """(itens, gravidades) do PR n: itens de revisão (COMMENTED, com texto próprio) dos bots e, do índice do Copilot,
    {id do comentário em linha: prioridade} pela gravidade (Critical/High/Medium/Low -> P0..P3)."""
    status, dados, _ = gh_api(cfg, f"repos/{cfg['repo']}/pulls/{n}/reviews?per_page=100")
    saida, gravidades = [], {}
    for r in dados if isinstance(dados, list) else []:
        if not (eh_bot((r.get("user") or {}).get("login"), cfg["bots"]) or MARCA_REVISOR in (r.get("body") or "")) \
                or r.get("state") != "COMMENTED":
            continue
        if RE_SEM_COTA.search(r.get("body") or ""):         # aviso do GitHub (cota do bot esgotada): não é sugestão
            continue
        if RE_COPILOT_INDICE.search(r.get("body") or ""):   # índice: dá a gravidade dos comentários em linha...
            for g, cid in RE_COPILOT_GRAVIDADE.findall(r["body"]):
                gravidades[cid] = PRIO_GRAVIDADE[g.lower()]
            # ...e traz os achados "Previously missed", que só existem aqui (sem comentário em linha); ignorar o índice
            # deixava esses achados passarem pelo --pronto.
            for k, (local, titulo, texto, prio) in enumerate(_achados_do_indice(r["body"])):
                iid = f"r{r['id']}m{k}"
                if iid in existentes:
                    continue
                arq, _, lin = local.partition(":")
                c = {"id": f"{r['id']}m{k}", "body": f"**{titulo}**\n{texto}", "path": arq,
                     "line": int(lin) if lin.isdigit() else None, "pull_request_url": f"x/{n}",
                     "html_url": r.get("html_url") or "", "submitted_at": r.get("submitted_at"), "user": r.get("user")}
                item = _item(cfg, c, prs, "revisao", "r")
                item["prioridade"] = prio
                saida.append(item)
            continue
        if not (r.get("body") or "").strip() or f"r{r['id']}" in existentes or _eh_resumo_vazio(r["body"]):
            continue
        r = dict(r, pull_request_url=f"x/{n}", path="", line=None)
        saida.append(_item(cfg, r, prs, "revisao", "r"))
    return saida, gravidades


def coletar(cfg=None, triagem=True, log=None, recoletar=False):
    """Uma coleta completa. Nunca levanta exceção: devolve {'novas', 'chamadas', 'erro', 'limite', 'triadas'}.
    recoletar: ignora o cursor e o ETag e relê a janela inteira (ex.: depois de acrescentar um bot); a caixa não duplica."""
    cfg = cfg or configuracao()
    log = log or (lambda m: None)
    res = {"novas": 0, "chamadas": 0, "erro": "", "limite": 0, "triadas": 0}
    if cfg.get('ativo') is False:
        res['erro']='desligado na política do projeto';return res
    if not cfg["bots"] and not cfg.get("revisor"):
        res["erro"] = "desligado (nenhum bot de revisão configurado)"
        return res
    if not cfg["repo"]:
        res["erro"] = "repositório não configurado"
        return res
    try:
        conferir_projeto(cfg)
        with trava_caixa(cfg):
            est = ler_estado(cfg)
        if recoletar:
            for k in ("since", "etag_url", "etag_comentarios"):
                est.pop(k, None)
        res["chamadas"] += _baixar_prs_abertos(cfg, est)
        comentarios, ch = _baixar_comentarios(cfg, est)
        res["chamadas"] += ch
        prs = est.get("prs", {})
        do_bot = [c for c in comentarios if (eh_bot((c.get("user") or {}).get("login"), cfg["bots"])
                                             or MARCA_REVISOR in (c.get("body") or ""))
                  and (cfg.get('projeto') is None or re.fullmatch('https://api.github.com/repos/'+re.escape(cfg['repo'])+'/pulls/[1-9][0-9]*',str(c.get('pull_request_url') or ''),re.I))
                  and not c.get("in_reply_to_id") and (c.get("body") or "").strip()]
        with trava_caixa(cfg):
            caixa = ler_caixa(cfg)
            ids = {str(x["id"]) for x in caixa}
            novos = []
            for c in do_bot:
                if str(c["id"]) not in ids:
                    novos.append(_item(cfg, c, prs))
                    ids.add(str(c["id"]))
        # Revisões de TODO PR aberto (1 chamada REST por PR): achado só no índice do Copilot ("Previously missed") não
        # gera comentário em linha, então olhar só os PRs com comentário novo deixava esses achados de fora.
        abertos_com_novo = sorted({int(k) for k in prs} | {x["pr"] for x in novos if x["situacao"] == "nova"})
        for n in abertos_com_novo:
            try:
                extra, gravidades = _revisoes(cfg, n, prs, ids)
                res["chamadas"] += 1
                for x in novos:   # Copilot não põe selo no comentário em linha: a prioridade vem do índice da revisão
                    if x["prioridade"] == "?" and str(x["id"]) in gravidades:
                        x["prioridade"] = gravidades[str(x["id"])]
                novos += extra
                ids |= {x["id"] for x in extra}
            except ErroApi as e:
                if e.limite:
                    raise
                log(f"reviews do PR #{n}: {e}")
        with trava_caixa(cfg):
            caixa = ler_caixa(cfg)
            ja = {str(x["id"]) for x in caixa}
            caixa += [x for x in novos if str(x["id"]) not in ja]
            res["novas"] = sum(1 for x in novos if str(x["id"]) not in ja and x["situacao"] == "nova")
            _arquivar(cfg, caixa, prs)
            gravar_caixa(cfg, caixa)
            est["ultima_coleta"] = _iso(_agora())
            est["erro"] = ""
            est.pop("limite_ate", None)
            gravar_estado(cfg, est)
    except ErroApi as e:
        res["erro"] = str(e)
        if e.limite:
            res["limite"] = e.reset or 1
        _anotar_erro(cfg, res)
        return res
    except Exception as e:   # nunca derruba quem chamou (servidor, líder)
        res["erro"] = f"{type(e).__name__}: {str(e)[:200]}"
        _anotar_erro(cfg, res)
        return res
    # tria o que estiver "nova" na caixa, não só as desta coleta: a thread `pronto` do servidor coleta sem triagem a cada
    # 3 min e pegava as novas primeiro, então a coleta com triagem achava 0 novas e a triagem nunca rodava (7 out. 2026)
    if triagem and (cfg["modelo"] or cfg.get('triagem_provider')) and (res["novas"] or _ha_para_triar(cfg)):
        try:
            res["triadas"] = triar(cfg, log)
        except Exception as e:
            log(f"triagem falhou: {str(e)[:200]}")
    return res


def _anotar_erro(cfg, res):
    try:
        with trava_caixa(cfg,espera=5):
            est = ler_estado(cfg)
            est["erro"] = res["erro"]
            if res["limite"]:
                est["limite_ate"] = res["limite"]
            est["ultima_tentativa"] = _iso(_agora())
            gravar_estado(cfg, est)
    except Exception:
        pass


def _arquivar(cfg, caixa, prs):
    """PR que fechou: itens abertos viram 'arquivada'; arquivadas antigas saem da caixa."""
    corte = _iso(_agora() - timedelta(days=GUARDAR_ARQUIVADAS_DIAS))
    for x in caixa:
        # "encaminhada" também: sem isso, a sugestão encaminhada de PR fechado ficava para sempre segurando o merge
        if x.get("situacao") in ABERTAS + ("encaminhada",) and str(x.get("pr")) not in prs:
            x["situacao"], x["tratada_em"] = "arquivada", _iso(_agora())
    caixa[:] = [x for x in caixa if x.get("situacao") != "arquivada" or (x.get("criado") or "") >= corte]


# ---------------------------------------------------------------- triagem barata (Haiku, sem ferramentas)
PROMPT_TRIAGEM = (
    "Você é um triador de sugestões de revisão de código deixadas por um bot em pull requests. Não use ferramentas e não "
    "peça mais informações. Receberá uma lista JSON de itens (id, pr, branch, prioridade, titulo, arquivo, linha, "
    "texto, time_do_pr). Para CADA item decida: acao = \"corrigir\" (problema real e específico: bug, regressão, teste "
    "faltando, contrato quebrado, segurança), \"ignorar\" (nitpick, estilo, falso positivo, já tratado, fora do escopo do "
    "PR) ou \"discutir\" (decisão de produto, arquitetura ou prioridade que cabe ao desenvolvedor). Prioridades P0 e P1 "
    "quase sempre são \"corrigir\", a menos que o texto esteja claramente errado. Responda SOMENTE com um array JSON, "
    "sem markdown e sem comentário, um objeto por item, no formato "
    "{\"id\": \"<id do item>\", \"acao\": \"corrigir|ignorar|discutir\", \"motivo\": \"<até 120 caracteres, em português, sem repetir a prioridade>\", "
    "\"time_sugerido\": \"<um dos times permitidos; use o time_do_pr quando houver>\"}.")


MAX_APRENDIDAS = 20


def contexto_triagem(cfg):
    """Glossário do projeto + as últimas sugestões ignoradas COM motivo: o que o líder já decidiu ensina a próxima
    triagem (caso real: "regera" -> "regenera" foi triado como corrigir, e "regerar" era o termo do projeto)."""
    partes = []
    try:
        g = GLOSSARIO.read_text(encoding="utf-8").strip() if cfg.get('projeto') is None else ''
        if g:
            partes.append("Contexto do projeto (use para separar falso positivo de problema real):\n" + g[:2500])
    except OSError:
        pass
    ignoradas = [x for x in ler_caixa(cfg) if x.get("situacao") == "ignorada" and (x.get("nota") or "").strip()]
    ignoradas.sort(key=lambda x: x.get("tratada_em") or x.get("criado") or "")
    if ignoradas:
        linhas = [f"- {x['titulo'][:90]} — motivo: {x['nota'][:120]}" for x in ignoradas[-MAX_APRENDIDAS:]]
        partes.append("Sugestões que o líder já IGNOROU, com o motivo (trate as parecidas do mesmo jeito):\n" + "\n".join(linhas))
    return "\n\n".join(partes)


def _resumo_para_triagem(x):
    return {"id": x["id"], "pr": x["pr"], "branch": x.get("branch", ""), "prioridade": x["prioridade"], "titulo": x["titulo"],
            "arquivo": f"{x['arquivo']}:{x['linha']}" if x.get("arquivo") else "", "texto": x["texto"][:700],
            "time_do_pr": x.get("time_pr", "")}


def _achar_claude():
    return shutil.which("claude") or shutil.which("claude.cmd") or shutil.which("claude.exe")


def _json_da_resposta(texto):
    t = (texto or "").strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    i, j = t.find("["), t.rfind("]")
    if i < 0 or j <= i:
        raise ValueError("resposta sem array JSON")
    return json.loads(t[i:j + 1])


MAX_TENTATIVAS_TRIAGEM = 2   # item que o modelo não classificou em 2 chamadas fica "nova" (o líder trata) sem novo custo


def _para_triar(caixa):
    return [x for x in caixa if x.get("situacao") == "nova" and int(x.get("tentativas_triagem") or 0) < MAX_TENTATIVAS_TRIAGEM]


def _ha_para_triar(cfg):
    try:
        with trava_caixa(cfg):
            return bool(_para_triar(ler_caixa(cfg)))
    except Exception:
        return False


def triar(cfg, log=None, itens_max=MAX_TRIAGEM):
    """Triagem de até 30 itens 'nova' em UMA chamada de `claude -p` (Haiku, sem ferramentas). Devolve quantos foram triados."""
    if cfg.get('projeto'):
        from triagem_providers import triar as comum
        return comum(cfg,itens_max=itens_max)
    log = log or (lambda m: None)
    exe = _achar_claude()
    if not exe or not cfg["modelo"]:
        return 0
    with trava_caixa(cfg):
        alvo = _para_triar(ler_caixa(cfg))[:itens_max]
        if alvo:   # conta a tentativa ANTES de chamar: resposta inválida ou falha não vira chamada sem fim
            ids = {str(x["id"]) for x in alvo}
            caixa = ler_caixa(cfg)
            for x in caixa:
                if str(x["id"]) in ids:
                    x["tentativas_triagem"] = int(x.get("tentativas_triagem") or 0) + 1
            gravar_caixa(cfg, caixa)
    if not alvo:
        return 0
    times = ", ".join(cfg["agentes"])
    ctx = contexto_triagem(cfg)
    entrada = f"Times permitidos: {times}.\n" + (ctx + "\n\n" if ctx else "") + "Itens:\n" + json.dumps([_resumo_para_triagem(x) for x in alvo], ensure_ascii=False)
    cmd = [exe, "-p", "--model", cfg["modelo"], "--tools", "", "--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence",
           "--output-format", "json", "--system-prompt", PROMPT_TRIAGEM]
    t0 = time.time()
    r = subprocess.run(cmd, input=entrada.encode("utf-8"), capture_output=True, timeout=TIMEOUT_TRIAGEM,
                       cwd=str(RAIZ), env=dict(os.environ, PYTHONUTF8="1"))
    saida = r.stdout.decode("utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError((r.stderr.decode("utf-8", errors="replace") or saida).strip()[-300:] or "claude falhou")
    env = json.loads(saida)
    if env.get("is_error"):
        raise RuntimeError(str(env.get("result"))[:300])
    respostas = _json_da_resposta(env.get("result"))
    validos = {str(x["id"]) for x in alvo}
    aplicadas = {}
    for o in respostas if isinstance(respostas, list) else []:
        if not isinstance(o, dict) or str(o.get("id")) not in validos:
            continue
        acao = str(o.get("acao") or "").strip().lower()
        if acao not in ("corrigir", "ignorar", "discutir"):
            continue
        aplicadas[str(o["id"])] = {"acao_sugerida": acao, "motivo": str(o.get("motivo") or "")[:120],
                                   "time_sugerido": str(o.get("time_sugerido") or "")[:40]}
    with trava_caixa(cfg):
        caixa = ler_caixa(cfg)
        for x in caixa:
            a = aplicadas.get(str(x["id"]))
            if a and x.get("situacao") == "nova":   # o líder pode ter tratado no meio do caminho
                x.update(a, situacao="triada")
                x["time_sugerido"] = x["time_sugerido"] or x.get("time_pr", "")
        gravar_caixa(cfg, caixa)
        est = ler_estado(cfg)
        uso = env.get("usage") or {}
        t = est.setdefault("triagem", {"chamadas": 0, "custo_usd": 0.0, "tokens_entrada": 0, "tokens_saida": 0})
        t["chamadas"] += 1
        t["custo_usd"] = round(t["custo_usd"] + float(env.get("total_cost_usd") or 0), 6)
        t["tokens_entrada"] += int(uso.get("input_tokens") or 0) + int(uso.get("cache_creation_input_tokens") or 0) + int(uso.get("cache_read_input_tokens") or 0)
        t["tokens_saida"] += int(uso.get("output_tokens") or 0)
        t["ultima"] = {"quando": _iso(_agora()), "itens": len(alvo), "triados": len(aplicadas), "segundos": round(time.time() - t0, 1),
                       "custo_usd": env.get("total_cost_usd"), "modelo": cfg["modelo"]}
        gravar_estado(cfg, est)
    log(f"triagem: {len(aplicadas)}/{len(alvo)} itens, custo {env.get('total_cost_usd')} USD")
    return len(aplicadas)


# ---------------------------------------------------------------- tratar, listar, pendentes, resumo
def tratar(cfg, id_, acao, nota=""):
    """(ok, mensagem). `reabrir` volta o item para triada/nova (desfaz um tratar)."""
    acao = (acao or "").strip().lower()
    if acao != "reabrir" and acao not in ACOES_TRATAR:
        return False, "acao deve ser encaminhada, ignorada, discutir, resolvida ou reabrir"
    with trava_caixa(cfg):
        caixa = ler_caixa(cfg)
        x = next((i for i in caixa if str(i["id"]) == str(id_).strip()), None)
        if x is None:
            return False, f"sugestão {id_} não encontrada"
        if acao == "reabrir":
            x["situacao"] = "triada" if x.get("acao_sugerida") else "nova"
            x["tratada_em"] = ""
            x["tentativas_triagem"] = 0   # reaberto sem triagem: volta a ser triado na próxima coleta
        else:
            x["situacao"], x["tratada_em"] = ACOES_TRATAR[acao], _iso(_agora())
        if nota:
            x["nota"] = str(nota)[:300]
        gravar_caixa(cfg, caixa)
    return True, f"sugestão {x['id']} (PR #{x['pr']}, {x['prioridade']}): {x['situacao']}"


def _ordem(x):
    return (int(x.get("pr") or 0), PRIORIDADES.index(x["prioridade"]) if x.get("prioridade") in PRIORIDADES else 4, x.get("criado", ""))


def _local(x):
    if not x.get("arquivo"):
        return "(revisão geral)" if x.get("tipo") == "revisao" else ""
    return f"{x['arquivo']}:{x['linha']}" if x.get("linha") else x["arquivo"]


def texto_pendentes(cfg, maximo=25, pr=None):
    itens = sorted([x for x in ler_caixa(cfg) if x.get("situacao") in PENDENTES
                    and (pr is None or str(x.get("pr")) == str(pr))], key=_ordem)
    if not itens:
        return "NADA"
    por_pr = {}
    for x in itens:
        por_pr.setdefault(x["pr"], []).append(x)
    linhas = [f"Sugestões do bot pendentes: {len(itens)} em {len(por_pr)} PR(s). Trate cada uma com "
              "`sugestoes_bot.py --tratar <id> --acao encaminhada|ignorada|discutir|resolvida`."]
    corte = False
    for pr, lista in por_pr.items():
        dono = lista[0].get("time_pr") or lista[0].get("time_sugerido")   # rótulo do PR; sem rótulo, o palpite da triagem
        cab = f"PR #{pr}" + (f" [{dono}]" if dono else "") + (f" {lista[0]['branch']}" if lista[0].get("branch") else "")
        if len(linhas) + 1 + len(lista) > maximo - 1 and len(linhas) > 1:
            corte = True
            break
        linhas.append(cab)
        for x in lista:
            if len(linhas) >= maximo - 1:
                corte = True
                break
            sug = (x.get("acao_sugerida") or "sem triagem") + (f" ({x['motivo']})" if x.get("motivo") else "")
            linhas.append(f"  {x['id']} {x['prioridade']} {x['titulo'][:90]} | {_local(x)} | sugere: {sug} | {x['link']}")
        if corte:
            break
    if corte:
        linhas.append("… há mais itens; rode --listar para ver todos.")
    return "\n".join(linhas[:maximo])


def texto_listar(cfg, todas=False, pr=None):
    itens = sorted([x for x in ler_caixa(cfg) if (todas or x.get("situacao") in ABERTAS)
                    and (pr is None or str(x.get("pr")) == str(pr))], key=_ordem)
    if not itens:
        return "Nenhuma sugestão" + ("" if todas else " aberta") + "."
    return "\n".join(f"#{x['pr']} {x['prioridade']} [{x['situacao']}{'/' + x['acao_sugerida'] if x.get('acao_sugerida') and x['situacao'] in ('nova', 'triada') else ''}] "
                     f"{x['id']} {x['titulo'][:80]} | {_local(x)} | {x['link']}" for x in itens)


def resumo(cfg=None):
    """Para o servidor: contagem por PR e prioridade das sugestões abertas + os itens, e o estado da coleta."""
    cfg = cfg or configuracao()
    est = ler_estado(cfg)
    abertas = sorted([x for x in ler_caixa(cfg) if x.get("situacao") in ABERTAS], key=_ordem)
    por_pr = {}
    for x in abertas:
        c = por_pr.setdefault(str(x["pr"]), {"total": 0, "P0": 0, "P1": 0, "P2": 0, "P3": 0, "?": 0})
        c["total"] += 1
        c[x["prioridade"] if x["prioridade"] in c else "?"] += 1
    campos = ("id", "tipo", "pr", "arquivo", "linha", "prioridade", "titulo", "texto", "link", "criado", "situacao",
              "acao_sugerida", "motivo", "time_sugerido", "nota", "autor")
    seguram = {}
    for x in ler_caixa(cfg):
        if x.get("situacao") in SEGURAM_MERGE:
            seguram[str(x["pr"])] = seguram.get(str(x["pr"]), 0) + 1
    return {"ativo": bool(cfg["bots"] or cfg.get("revisor")), "por_pr": por_pr, "itens": [{k: x.get(k) for k in campos} for x in abertas],
            "seguram_merge": seguram,
            "ultima_coleta": est.get("ultima_coleta", ""), "erro": est.get("erro", ""), "limite_ate": est.get("limite_ate", 0),
            "triagem": (est.get("triagem") or {}).get("ultima"), "intervalo_min": cfg["intervalo_min"]}


def pronto(cfg, n, coletar_antes=True, info=None):
    """(ok, motivos) para dizer que o PR n está pronto para o merge, do ponto de vista dos bots: nenhuma sugestão sem
    decisão ou encaminhada e ainda não corrigida, cada bot "por push" que já revisou o PR revisou também o commit atual,
    e PR novo não passa antes de algum bot revisar (ESPERA_BOTS_MIN). Avisos (bot de abertura, bot atrasado além de
    PRAZO_BOT_MIN, cota esgotada) não travam: voltam no fim de motivos com o prefixo "(aviso)".
    Coleta antes, para não decidir com a caixa velha (`coletar_antes=False` quando quem chama acabou de coletar).
    `info`, se dado, recebe {"sha": commit conferido}."""
    if coletar_antes:
        coletar(cfg, triagem=False)
    motivos, avisos = [], []
    pend = [x for x in ler_caixa(cfg) if x.get("pr") == n and x.get("situacao") in SEGURAM_MERGE]
    for x in sorted(pend, key=_ordem):
        o_que = "encaminhada, ainda não corrigida" if x["situacao"] == "encaminhada" else "sem decisão"
        motivos.append(f"sugestão {x['prioridade']} {x['id']} ({o_que}): {x['titulo'][:80]}")
    _, pr, _ = gh_api(cfg, f"repos/{cfg['repo']}/pulls/{n}")
    _, revs, _ = gh_api(cfg, f"repos/{cfg['repo']}/pulls/{n}/reviews?per_page=100")
    cabeca = (pr or {}).get("head", {}).get("sha", "")
    if info is not None:
        info["sha"] = cabeca
    por_bot = {}
    sem_cota = set()
    for r in revs if isinstance(revs, list) else []:
        login = (r.get("user") or {}).get("login", "")
        if MARCA_REVISOR in (r.get("body") or ""):
            login = "revisor-ia"                 # o revisor próprio revisa cada commit (revisor_ia.py): conta como bot por push
            por_bot.setdefault(login, set()).update({r.get("commit_id"), "push"})
            continue
        if eh_bot(login, cfg["bots"]):
            if RE_SEM_COTA.search(r.get("body") or ""):
                sem_cota.add(login)      # o GitHub avisou que a cota do bot acabou: ele não vai revisar o push novo
                continue
            por_bot.setdefault(login, set()).add(r.get("commit_id"))
    for login in sorted(sem_cota):
        avisos.append(f"{login}: cota de revisão esgotada (aviso do GitHub); não vai revisar os pushes novos até renovar — confira à mão")
        por_bot.pop(login, None)
    # Há bots que revisam cada push (o Copilot, alguns minutos depois) e bots que só revisam na abertura do PR (o Codex,
    # ou quando alguém comenta "@codex review"). Bot que, neste PR, revisou um commit só é "de abertura" e não segura o
    # merge nos pushes seguintes; bot que revisou 2+ commits é "por push" e segura, até PRAZO_BOT_MIN depois do push.
    data_cabeca = None
    if cabeca:
        try:
            _, c, _ = gh_api(cfg, f"repos/{cfg['repo']}/commits/{cabeca}")
            data_cabeca = _ler_iso(((c or {}).get("commit") or {}).get("committer", {}).get("date", ""))
        except ErroApi:
            data_cabeca = None
    for login, commits in sorted(por_bot.items()):
        if not cabeca or cabeca in commits:
            continue
        if len(commits) < 2:
            avisos.append(f"{login} revisa só na abertura do PR e não viu o commit atual; comente no PR o comando de nova "
                          f"revisão do bot (ex.: \"@codex review\") se quiser outra rodada")
        elif data_cabeca and (_agora() - data_cabeca).total_seconds() > PRAZO_BOT_MIN * 60:
            avisos.append(f"{login} não revisou o commit atual ({cabeca[:8]}) em {PRAZO_BOT_MIN} min (fila ou cota do bot); confira à mão")
        else:
            motivos.append(f"{login} ainda não revisou o commit atual ({cabeca[:8]}); espere alguns minutos e rode de novo")
    criado = _ler_iso((pr or {}).get("created_at", ""))
    if not por_bot and criado and (_agora() - criado).total_seconds() < ESPERA_BOTS_MIN * 60:
        motivos.append(f"nenhum bot revisou ainda (PR aberto há menos de {ESPERA_BOTS_MIN} min); espere e rode de novo")
    return not motivos, motivos + [f"(aviso) {a}" for a in avisos]


# ---------------------------------------------------------------- linha de comando
def _saida():
    for f in (sys.stdout, sys.stderr):
        try:
            f.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _arg(args, nome, padrao=""):
    if nome in args:
        i = args.index(nome)
        return args[i + 1] if i + 1 < len(args) else padrao
    return padrao


def main(argv=None):
    _saida()
    args = list(sys.argv[1:] if argv is None else argv)
    if '--projeto' in args:
        raiz=Path(_arg(args,'--projeto')).resolve()
        if raiz not in [Path(p).resolve() for p in _pacote.carregar()['projetos']]:
            print('Projeto não cadastrado no escritório');return 2
        cfg=configuracao(raiz)
    else:
        from kanban_painel import habilitado
        if habilitado(_pacote.carregar()['projetos']):
            print('Gestão por projeto exige --projeto PASTA');return 2
        cfg=configuracao()
    pr = _arg(args, "--pr") if "--pr" in args else None
    if pr is not None and not str(pr).isdigit():
        print("uso: --pr <número do PR>")
        return 2
    if "--pendentes" in args:
        print(texto_pendentes(cfg, pr=pr))
        return 0
    if "--pronto" in args:
        try:
            n = int(_arg(args, "--pronto"))
        except ValueError:
            print("uso: sugestoes_bot.py --pronto <número do PR>")
            return 2
        ok, motivos = pronto(cfg, n)
        rotulo='OK (somente sugestões; não autoriza merge)' if cfg.get('projeto') is not None else 'OK'
        print((rotulo + "".join(f"\n  {m}" for m in motivos)) if ok
              else f"PR #{n} ainda não está pronto para o merge:\n  " + "\n  ".join(motivos))
        return 0 if ok else 1
    if "--listar" in args:
        print(texto_listar(cfg, "--todas" in args, pr=pr))
        return 0
    if "--tratar" in args:
        ok, msg = tratar(cfg, _arg(args, "--tratar"), _arg(args, "--acao"), _arg(args, "--nota"))
        print(msg)
        return 0 if ok else 1
    res = coletar(cfg, triagem="--sem-triagem" not in args, log=lambda m: print(m, file=sys.stderr),
                  recoletar="--recoletar" in args)
    if res["erro"].startswith("desligado"):
        print(res["erro"])
        return 0
    if res["erro"]:
        print(f"ERRO na coleta: {res['erro']}" + (" (limite da API do GitHub)" if res["limite"] else ""))
        return 1
    est = ler_estado(cfg)
    print(f"coleta ok: {res['novas']} nova(s), {res['triadas']} triada(s), {res['chamadas']} chamada(s) à API; "
          f"{sum(1 for x in ler_caixa(cfg) if x.get('situacao') in PENDENTES)} pendente(s) para o líder")
    return 0


if __name__ == "__main__":
    sys.exit(main())
