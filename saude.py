"""Saúde do time (sem tokens): trabalho duplicado, agente andando em círculos, risco do PR e PR parado.

Por quê (pesquisa de 7 out. 2026):
- "Where Do AI Coding Agents Fail?" (arXiv 2601.15195, 33 mil PRs de agentes): 23% dos PRs rejeitados eram duplicados, 38% foram
  abandonados sem interação; cada check de CI que falha tira ~15% da chance de merge e PR maior entra 17% menos.
- MAST, "Why Do Multi-Agent LLM Systems Fail?" (arXiv 2503.13657) e "The Observability Gap" (arXiv 2603.26942): repetir passos e
  oscilar entre correções é um modo de falha comum e um aviso precoce de que o agente trata o sintoma, não a causa.

Tudo aqui é puro (sem E/S) exceto `branches_locais` (um `git for-each-ref`, só leitura) e a linha de comando, que lê
dados/saude.json gravado pelo servidor. O servidor junta os PRs que já tem em cache, as branches locais da 1ª pasta de "projetos" e os eventos
recentes.

Uso: python saude.py --pendentes   imprime o que o líder deve ver (duplicados e círculos) ou NADA (para o vigia do líder)
"""
import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ARQ = Path(__file__).resolve().parent / "dados" / "saude.json"
VALIDADE_ARQ = 1800        # s: saude.json mais velho que isso é ignorado pela linha de comando (servidor parado)
JANELA_ATIVA_H = 48        # branch local com commit mais novo que isso conta como trabalho em andamento
MIN_SLUG = 8               # nome de branch (sem prefixo e número) mais curto que isso não serve para comparar
JANELA_CIRCULO_MIN = 45
MIN_EDICOES = 6            # o mesmo arquivo editado N vezes ...
MIN_COMANDOS = 4           # ... e o mesmo comando rodado M vezes pelo mesmo agente na janela = andando em círculos
PARADO_H = 24
RISCO = {"medio": (300, 10), "grande": (800, 25)}   # (linhas alteradas, arquivos) a partir dos quais o PR é médio/grande
FERRAMENTAS_EDICAO = ("Edit", "Write", "MultiEdit", "NotebookEdit")
CHECKS_FALHOS = ("FAILURE", "ERROR", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED", "STARTUP_FAILURE")
FERRAMENTAS_COMANDO = ("Bash", "PowerShell")

_RE_DATA = re.compile(r"\d{4}-?\d{2}-?\d{2}")
_RE_VERSAO = re.compile(r"-v\d+$")


def _partes(branch):
    resto = str(branch or "").split("/", 1)[-1]
    return [p for p in re.split(r"[-_/]", _RE_DATA.sub("", resto)) if p]


def numero_da_branch(branch):
    """Número da issue no nome da branch (feat/444-login-form → 444); None se não houver (datas não contam)."""
    for p in _partes(branch):
        if p.isdigit() and len(p) <= 5:
            return int(p)
    return None


def slug_da_branch(branch):
    """Nome da tarefa sem prefixo, número e sufixo -vN (feat/444-login-form-v2 → login-form); "" se curto demais."""
    resto = str(branch or "").split("/", 1)[-1]
    resto = _RE_VERSAO.sub("", _RE_DATA.sub("", resto))
    s = "-".join(p for p in re.split(r"[-_/]", resto) if p and not p.isdigit()).lower()
    return s if len(s) >= MIN_SLUG else ""


def duplicados(prs, locais, agora, janela_h=JANELA_ATIVA_H):
    """Trabalho em andamento repetido. `prs`: lista do /prs (numero, branch, fecha); `locais`: [{"branch", "quando"}].
    Conta só o que está ativo: PR aberto ou branch local com commit nas últimas `janela_h` horas.
    fortes (viram alerta): o mesmo nome de tarefa com números diferentes, ou dois PRs abertos para a mesma issue.
    fracos (só aparecem no resumo): duas branches ativas com o mesmo número de issue (pode ser parte 1 e parte 2)."""
    ativos = {}
    for pr in prs or []:
        if isinstance(pr, dict) and pr.get("branch"):
            issues = {numero_da_branch(pr["branch"])} | {n for n in pr.get("fecha") or [] if isinstance(n, int)}
            ativos[pr["branch"]] = {"branch": pr["branch"], "pr": pr.get("numero"), "issues": {n for n in issues if n}}
    limite = agora - janela_h * 3600
    for b in locais or []:
        nome = b.get("branch")
        if nome and nome not in ativos and (b.get("quando") or 0) >= limite and numero_da_branch(nome):
            ativos[nome] = {"branch": nome, "pr": None, "issues": {numero_da_branch(nome)}}
    fortes, fracos, vistos = [], [], set()

    def junta(lista, grupo, motivo):
        chave = tuple(sorted(x["branch"] for x in grupo))
        if len(chave) > 1 and chave not in vistos:
            vistos.add(chave)
            lista.append({"motivo": motivo, "branches": list(chave), "prs": sorted(x["pr"] for x in grupo if x["pr"])})

    por_slug = {}
    for a in ativos.values():
        s = slug_da_branch(a["branch"])
        if s:
            por_slug.setdefault(s, []).append(a)
    for s, grupo in sorted(por_slug.items()):
        conjuntos = [a["issues"] for a in grupo if a["issues"]]
        if len(conjuntos) > 1 and not set.intersection(*conjuntos):
            junta(fortes, grupo, f"mesma tarefa ({s}) com números diferentes")
    por_issue = {}
    for a in ativos.values():
        for n in a["issues"]:
            por_issue.setdefault(n, []).append(a)
    for n, grupo in sorted(por_issue.items()):
        com_pr = [a for a in grupo if a["pr"]]
        if len(com_pr) > 1:
            junta(fortes, com_pr, f"{len(com_pr)} PRs abertos para a issue #{n}")
        elif len(grupo) > 1:
            junta(fracos, grupo, f"{len(grupo)} branches ativas para a issue #{n}")
    return {"fortes": fortes, "fracos": fracos}


def _epoch(ts):
    try:
        return datetime.fromisoformat(str(ts)).timestamp()
    except ValueError:
        return None


def _alvo(ev):
    """(tipo, alvo) de um evento: ("edita", arquivo) ou ("comando", texto do comando); None para o resto."""
    det, f = str(ev.get("detalhe") or ""), ev.get("ferramenta")
    for campo in ("file_path:", "notebook_path:"):   # NotebookEdit traz notebook_path
        if f in FERRAMENTAS_EDICAO and det.startswith(campo):
            return "edita", det[len(campo):].strip().replace("\\", "/").lower()
    if f in FERRAMENTAS_COMANDO and det.startswith("command:"):
        return "comando", " ".join(det[len("command:"):].split())[:160]
    return None


def circulos(eventos, agora, janela_min=JANELA_CIRCULO_MIN, min_edicoes=MIN_EDICOES, min_comandos=MIN_COMANDOS):
    """Agentes no ciclo editar → rodar → editar: na janela, o mesmo arquivo editado >= min_edicoes vezes E o mesmo comando
    rodado >= min_comandos vezes. Os dois juntos (e não só um) evitam o falso positivo de quem só consulta um status."""
    limite = agora - janela_min * 60
    por_agente = {}
    for ev in eventos or []:
        if not isinstance(ev, dict) or ev.get("inicio") or ev.get("tipo") != "trabalho":
            continue   # o início de comando (PreToolUse) não conta: o mesmo comando teria 2 eventos
        t = _epoch(ev.get("ts"))
        alvo = _alvo(ev)
        if t is None or t < limite or alvo is None:
            continue
        a = por_agente.setdefault(str(ev.get("agente") or "?"), {"edita": {}, "comando": {}, "desde": t})
        a[alvo[0]][alvo[1]] = a[alvo[0]].get(alvo[1], 0) + 1
        a["desde"] = min(a["desde"], t)
    saida = []
    for agente, a in sorted(por_agente.items()):
        arq, ed = max(a["edita"].items(), key=lambda x: x[1], default=("", 0))
        cmd, co = max(a["comando"].items(), key=lambda x: x[1], default=("", 0))
        if ed >= min_edicoes and co >= min_comandos:
            saida.append({"agente": agente, "arquivo": arq.rsplit("/", 1)[-1], "edicoes": ed, "comando": cmd[:80],
                          "comandos": co, "desde": round(a["desde"])})
    return saida


def risco_pr(pr):
    """Selo do painel PRs: tamanho (linhas e arquivos) e checks que falharam. nivel: ok | medio | grande | ? (sem tamanho)."""
    linhas, arquivos = pr.get("linhas"), pr.get("arquivos")
    falhas = sum(1 for v in (pr.get("checks") or {}).values() if str(v).upper() in CHECKS_FALHOS)
    if not isinstance(linhas, int) or not isinstance(arquivos, int):
        return {"nivel": "?", "linhas": None, "arquivos": None, "falhas": falhas, "dica": ""}
    nivel = "ok"
    for n in ("medio", "grande"):
        if linhas >= RISCO[n][0] or arquivos >= RISCO[n][1]:
            nivel = n
    dica = ("dividir em PRs menores" if nivel == "grande" else "") or ("corrigir os checks antes" if falhas else "")
    return {"nivel": nivel, "linhas": linhas, "arquivos": arquivos, "falhas": falhas, "dica": dica}


def parados(prs, agora, horas=PARADO_H, situacao=None):
    """PRs abertos sem atualização há mais de `horas` (fora rascunho e pronto, que já tem o lembrete): [{"numero", "horas", "titulo"}]."""
    saida = []
    for pr in prs or []:
        if not isinstance(pr, dict) or pr.get("rascunho") or not isinstance(pr.get("numero"), int):
            continue
        if situacao and situacao(pr) == "pronto":
            continue
        try:
            t = datetime.fromisoformat(str(pr.get("atualizado") or "").replace("Z", "+00:00")).timestamp()
        except ValueError:
            continue
        if agora - t > horas * 3600:
            saida.append({"numero": pr["numero"], "horas": int((agora - t) // 3600), "titulo": str(pr.get("titulo") or "")[:80],
                          "atualizado": pr.get("atualizado")})
    return saida


def branches_locais(repo):
    """Branches locais do repositório com a data do último commit (só leitura). [] se não for um repositório git."""
    try:
        r = subprocess.run(["git", "-C", str(repo), "for-each-ref", "--format=%(refname:short)|%(committerdate:unix)", "refs/heads"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    except (OSError, subprocess.SubprocessError):
        return []
    saida = []
    for linha in r.stdout.splitlines() if r.returncode == 0 else []:
        nome, _, quando = linha.rpartition("|")
        if nome and quando.isdigit():
            saida.append({"branch": nome, "quando": int(quando)})
    return saida


def resumo(prs, locais, eventos, agora, situacao=None, parado_h=PARADO_H):
    """Tudo o que o servidor publica em /saude e grava em dados/saude.json. prs None (GitHub fora do ar ou ainda sem o
    PRONTO): só os círculos, que dependem só dos eventos locais; o detector não mexe em duplicados nem parados."""
    if prs is None:
        return {"ts": round(agora), "circulos": circulos(eventos, agora), "sem_prs": True}
    return {"ts": round(agora), "duplicados": duplicados(prs, locais, agora), "circulos": circulos(eventos, agora),
            "parados": parados(prs, agora, parado_h, situacao),
            "abertos": sorted(pr["numero"] for pr in prs or [] if isinstance(pr, dict) and isinstance(pr.get("numero"), int))}


def pendentes(dados, agora=None):
    """Linhas para o líder (duplicados fortes e círculos); [] se não há nada ou o arquivo está velho."""
    agora = agora or time.time()
    if not isinstance(dados, dict) or agora - (dados.get("ts") or 0) > VALIDADE_ARQ:
        return []
    linhas = [f"duplicado: {d['motivo']}: {', '.join(d['branches'])}" for d in (dados.get("duplicados") or {}).get("fortes") or []]
    # sem as contagens: elas mudam a cada rodada e o vigia (que só não repete a MESMA saída) acordaria o líder de novo
    linhas += [f"círculo: {c['agente']} edita {c['arquivo']} e roda o mesmo comando de novo e de novo"
               for c in dados.get("circulos") or []]
    return linhas


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    if "--pendentes" not in sys.argv:
        print(__doc__)
        return 0
    try:
        dados = json.loads(ARQ.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        dados = None
    linhas = pendentes(dados)
    print("\n".join(linhas) if linhas else "NADA")
    return 0


if __name__ == "__main__":
    sys.exit(main())
