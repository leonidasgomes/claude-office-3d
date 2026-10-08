"""Briefing do Diretor (exemplo genérico), sem gastar tokens de agente: gera dados/diretor/briefing.md, uma página.

Usa o config.json do escritório (github.repo, github.projeto_owner, github.projeto_numero, campo_time, campo_prioridade) e o
GitHub CLI (`gh`). Seções: quadro por status x time x prioridade, cartões parados há mais de N dias (Em andamento ou P0) e
PRs da última semana, branches sem PR parados há mais de 2 dias; se existir dados/xp/placar.json, um resumo do placar. É um ponto de partida: copie e adapte (por
exemplo, acrescentando o documento de visão do seu projeto).

Uso: python modelos/briefing_diretor.py [--config config.json] [--dias-parado 14] [--saida arquivo.md]
"""
import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

RAIZ = Path(__file__).resolve().parent.parent
GH = shutil.which("gh") or "gh"
FEITO = ("Feito", "Done")
ANDAMENTO = ("Em andamento", "In Progress")
PARADO_DIAS = 2   # branch sem PR e sem commit há mais que isso: trabalho largado no meio (o líder cobra o PR ou o descarte)


def gh(*args):
    r = subprocess.run([GH, *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or "gh falhou").strip().splitlines()[-1][:200])
    return json.loads(r.stdout or "null")


def iso(texto):
    return datetime.fromisoformat(str(texto).replace("Z", "+00:00"))


def curto(texto, n):
    texto = " ".join(str(texto or "").split())
    return texto if len(texto) <= n else texto[: n - 1].rstrip() + "…"


def secao_quadro(cartoes):
    abertos = [c for c in cartoes if c["status"] not in FEITO]
    status = sorted({c["status"] for c in abertos})
    linhas = [f"## Quadro — {len(abertos)} abertos, {len(cartoes) - len(abertos)} feitos (células: P0/P1/P2)",
              "| Time | " + " | ".join(status) + " |", "|---|" + "---|" * len(status)]
    for t in sorted({c["time"] for c in abertos}):
        cel = []
        for s in status:
            grupo = [c for c in abertos if c["time"] == t and c["status"] == s]
            cel.append("/".join(str(sum(1 for c in grupo if c["prioridade"] == p)) for p in ("P0", "P1", "P2")) if grupo else "·")
        linhas.append(f"| {t} | " + " | ".join(cel) + " |")
    return linhas


def secao_parados(cartoes, repo, dias):
    agora = datetime.now(timezone.utc)
    issues = {}   # REST (não gasta a cota do GraphQL): 100 por página; os PRs vêm junto e saem pelo campo pull_request
    for pagina in range(1, 11):
        lista = gh("api", f"repos/{repo}/issues?state=open&per_page=100&page={pagina}") or []
        issues.update({i["number"]: i["updated_at"] for i in lista if "pull_request" not in i})
        if len(lista) < 100:
            break
    achados = []
    for c in cartoes:
        quando = issues.get(c["numero"])
        em_foco = c["status"] in ANDAMENTO or (c["prioridade"] == "P0" and c["status"] not in FEITO)
        if quando and em_foco and agora - iso(quando) > timedelta(days=dias):
            achados.append(((agora - iso(quando)).days, c))
    achados.sort(key=lambda x: -x[0])
    linhas = [f"## Parados há mais de {dias} dias"]
    linhas += [f"- #{c['numero']} {curto(c['titulo'], 60)} — {c['time']}, {c['prioridade']}, {c['status']}, {d} d" for d, c in achados[:8]]
    return linhas if achados else linhas + ["Nenhum."]


def secao_prs(repo):
    desde = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    prs = gh("pr", "list", "-R", repo, "--state", "all", "--limit", "300", "--search", f"created:>={desde}",
             "--json", "number,title,state,reviewDecision") or []
    reprov = [p for p in prs if p["state"] == "CLOSED" or p.get("reviewDecision") == "CHANGES_REQUESTED"]
    linhas = [f"## PRs dos últimos 7 dias ({len(prs)}): {sum(p['state'] == 'OPEN' for p in prs)} abertos, "
              f"{sum(p['state'] == 'MERGED' for p in prs)} mergeados, {len(reprov)} reprovados ou fechados sem merge"]
    return linhas + [f"- #{p['number']} {curto(p['title'], 62)}" for p in reprov[:5]]


def _paginas(caminho, limite=20):
    itens = []
    for pagina in range(1, limite + 1):
        lote = gh("api", f"{caminho}{'&' if '?' in caminho else '?'}per_page=100&page={pagina}") or []
        itens += lote
        if len(lote) < 100:
            break
    return itens


def secao_branches_parados(repo, dias=PARADO_DIAS):
    """Branches que nunca tiveram PR, à frente do branch padrão e sem commit há mais de `dias` dias."""
    base = (gh("api", f"repos/{repo}") or {}).get("default_branch", "main")
    com_pr = {(p.get("head") or {}).get("ref") for p in _paginas(f"repos/{repo}/pulls?state=all")}
    agora, parados = datetime.now(timezone.utc), []
    for b in _paginas(f"repos/{repo}/branches"):
        nome = b["name"]
        if nome == base or nome in com_pr:
            continue
        ref = quote(nome, safe="/")
        cmp = gh("api", f"repos/{repo}/compare/{quote(base, safe='/')}...{ref}") or {}
        if not cmp.get("ahead_by"):
            continue
        ponta = gh("api", f"repos/{repo}/commits/{ref}") or {}   # o compare corta em 250 commits: a data vem da ponta
        data = ((ponta.get("commit") or {}).get("committer") or {}).get("date")
        if not data:
            continue
        idade = (agora - iso(data)).days
        if idade > dias:
            parados.append((idade, nome))
    titulo = f"## Branches sem PR parados há mais de {dias} dias ({len(parados)})"
    return [titulo] + ([f"- `{n}` — {d} d sem commit (abrir o PR ou largar o branch)" for d, n in sorted(parados, reverse=True)]
                       or ["Nenhum."])


def secao_placar():
    placar = RAIZ / "dados" / "xp" / "placar.json"
    if not placar.exists():
        return []
    try:
        t = json.loads(placar.read_text(encoding="utf-8")).get("time", {})
    except (OSError, ValueError):
        return []
    return ["", "## Placar", f"- {t.get('prs_pontuados', 0)} PRs pontuados; aprovação de primeira "
            f"{round(100 * t.get('aprovacao_primeira', 0))}%; retrabalho em 14 d {round(100 * t.get('retrabalho_14d', 0))}%; "
            f"auditorias abertas {t.get('auditorias_abertas', 0)}."]


def main():
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=str(RAIZ / "config.json"))
    ap.add_argument("--dias-parado", type=int, default=14)
    ap.add_argument("--saida", default=str(RAIZ / "dados" / "diretor" / "briefing.md"))
    args = ap.parse_args()
    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    g = cfg.get("github") or {}
    repo = g.get("repo") or ""
    campo_time = str(g.get("campo_time") or "time").lower()
    campo_prio = str(g.get("campo_prioridade") or "prioridade").lower()
    saida = [f"# Briefing do Diretor — {datetime.now().strftime('%Y-%m-%d %H:%M')} ({repo or 'sem repositório no config'})", ""]
    cartoes = []
    try:
        dados = gh("project", "item-list", str(g["projeto_numero"]), "--owner", g["projeto_owner"], "--format", "json", "--limit", "500")
        for i in (dados or {}).get("items", []):
            c = i.get("content") or {}
            if c.get("type") == "PullRequest":
                continue
            cartoes.append({"numero": c.get("number"), "titulo": i.get("title") or c.get("title") or "",
                            "status": i.get("status") or "Sem status", "time": i.get(campo_time) or "Sem time",
                            "prioridade": i.get(campo_prio) or "—"})
        saida += secao_quadro(cartoes)
    except (KeyError, RuntimeError, OSError) as e:
        saida += ["## Quadro", f"Indisponível: {curto(e, 160)} (confira github.projeto_owner e projeto_numero no config e o `gh auth status`)."]
    for secao in (lambda: secao_parados(cartoes, repo, args.dias_parado), lambda: secao_prs(repo), lambda: secao_branches_parados(repo)):
        saida.append("")
        try:
            saida += secao()
        except (RuntimeError, OSError) as e:
            saida.append(f"Seção indisponível: {curto(e, 160)}")
    saida += secao_placar()
    destino = Path(args.saida)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text("\n".join(saida) + "\n", encoding="utf-8")
    print(f"Briefing gravado em {destino}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
