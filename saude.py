"""Saúde do time (sem tokens): trabalho duplicado, agente andando em círculos, risco do PR e PR parado.

Por quê (pesquisa de 7 out. 2026):
- "Where Do AI Coding Agents Fail?" (arXiv 2601.15195, 33 mil PRs de agentes): 23% dos PRs rejeitados eram duplicados, 38% foram
  abandonados sem interação; cada check de CI que falha tira ~15% da chance de merge e PR maior entra 17% menos.
- MAST, "Why Do Multi-Agent LLM Systems Fail?" (arXiv 2503.13657) e "The Observability Gap" (arXiv 2603.26942): repetir passos e
  oscilar entre correções é um modo de falha comum e um aviso precoce de que o agente trata o sintoma, não a causa.

Tudo aqui é puro (sem E/S) exceto `branches_locais` (um `git for-each-ref`, só leitura) e a linha de comando, que lê
dados/saude.json gravado pelo servidor. O servidor junta os PRs que já tem em cache, as branches locais da 1ª pasta de "projetos" e os eventos
recentes.

Painel 🩺 Saúde (saude_painel.js): o desenvolvedor pode IGNORAR um item (dados/saude_ignorados.json; some dos alertas e do
--pendentes, mas segue no painel em "Ignorados") e AVISAR O LÍDER (dados/saude_pedidos.jsonl; o --pendentes entrega cada pedido
uma vez só, guardando o último ts entregue em dados/saude_pedidos_estado.json). Chave estável de cada item: chave_dup,
chave_circulo e chave_parado.

Uso: python saude.py --pendentes   imprime os pedidos do desenvolvedor ainda não entregues e o que o líder deve ver (duplicados
                                   e círculos não ignorados) ou NADA (para o vigia do líder)
"""
import json
import math
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

ARQ = Path(__file__).resolve().parent / "dados" / "saude.json"
PASTA_DADOS = ARQ.parent
IGNORADOS = "saude_ignorados.json"            # {chave: {"motivo", "quando", "origem", "ua"}}: só o servidor grava (POST /api/saude/ignorar)
PEDIDOS = "saude_pedidos.jsonl"               # {ts, chave, texto, recado, origem, ua} por linha: o servidor grava (POST /api/saude/avisar)
PEDIDOS_ESTADO = "saude_pedidos_estado.json"  # {"ultimo_ts": ts do último pedido entregue}: gravado pelo --pendentes
PEDIDOS_TRAVA = "saude_pedidos.lock"          # trava entre processos da entrega (O_CREAT|O_EXCL; vence em TRAVA_VALIDADE s)
MAX_CHAVE, MAX_MOTIVO, MAX_TEXTO = 300, 300, 400
MAX_IGNORADOS = 500                           # o mais antigo sai quando passa disso
MAX_PEDIDOS = 200                             # saude_pedidos.jsonl guarda só os últimos 200
SEM_ESTADO_H = 24                             # sem o arquivo de estado, só os pedidos das últimas 24 h são entregues
TRAVA_VALIDADE = 60
PREFIXO_PEDIDO = "pedido do desenvolvedor: "
PREFIXO_TRIAGEM = "triagem (modelo barato): "  # aviso automático ao líder (saude_triagem.py), entregue como os pedidos
CICLO = "saude_ciclo.json"                    # {"ts", "vistos": {chave: desc}, "resolvidos": [...], "cancelados": {ts: quando}}
TRIAGEM = "saude_triagem.json"                # {"veredictos": {chave: {...}}, "dia", "hoje", "chamadas", "custo_usd"}
RESOLVIDOS_H = 24                             # "Resolvidos" no painel: itens que saíram nas últimas 24 h
MAX_RESOLVIDOS, MAX_VISTOS = 100, 500
GRAVIDADES = ("baixa", "media", "alta")
ACOES_TRIAGEM = ("juntar", "fechar_um", "parar_e_repensar", "retomar_pr", "nenhuma")
TIPO_DA_CHAVE = {"dup": "trabalho duplicado", "circulo": "agente andando em círculos", "parado": "PR parado"}
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
# caracteres de controle (C0, DEL, C1) e separadores de linha/parágrafo do Unicode: nada disso vai para uma linha do --pendentes
_RE_CONTROLE = re.compile("[\x00-\x1f\x7f-\x9f\u2028\u2029]")


def texto_linha(x, limite=200):
    """Uma linha segura: espaços normalizados, sem caractere de controle, até `limite` caracteres. Todo campo que vai para o
    --pendentes passa por aqui (ninguém forja uma linha "pedido do desenvolvedor:" com um file_path ou nome de branch)."""
    return " ".join(_RE_CONTROLE.sub(" ", str(x if x is not None else "")).split())[:limite]
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
            arq = det[len(campo):].strip()
            if _RE_CONTROLE.search(arq):   # caminho com caractere de controle não é um arquivo de verdade: descarta
                return None
            return "edita", arq.replace("\\", "/").lower()
    if f in FERRAMENTAS_COMANDO and det.startswith("command:"):
        cmd = det[len("command:"):]
        # comando de várias linhas é normal (\n, \r, \t viram espaço); outro caractere de controle: descarta
        if _RE_CONTROLE.search(cmd.replace("\n", " ").replace("\r", " ").replace("\t", " ")):
            return None
        return "comando", " ".join(cmd.split())[:160]
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
        a = por_agente.setdefault(texto_linha(ev.get("agente"), 40) or "?", {"edita": {}, "comando": {}, "desde": t})
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
    """Branches locais do repositório com a data do último commit (só leitura). [] = nenhuma branch; None = o git FALHOU
    (sem git, pasta que não é repositório, timeout): aí resumo() marca `sem_locais` e nenhum duplicado conta como resolvido."""
    try:
        r = subprocess.run(["git", "-C", str(repo), "for-each-ref", "--format=%(refname:short)|%(committerdate:unix)", "refs/heads"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    saida = []
    for linha in r.stdout.splitlines():
        nome, _, quando = linha.rpartition("|")
        if nome and quando.isdigit():
            saida.append({"branch": nome, "quando": int(quando)})
    return saida


def resumo(prs, locais, eventos, agora, situacao=None, parado_h=PARADO_H):
    """Tudo o que o servidor publica em /saude e grava em dados/saude.json. prs None (GitHub fora do ar ou ainda sem o
    PRONTO): só os círculos, que dependem só dos eventos locais; o detector não mexe em duplicados nem parados."""
    if prs is None:
        return {"ts": round(agora), "circulos": circulos(eventos, agora), "sem_prs": True}
    d = {"ts": round(agora), "duplicados": duplicados(prs, locais or [], agora), "circulos": circulos(eventos, agora),
         "parados": parados(prs, agora, parado_h, situacao),
         "abertos": sorted(pr["numero"] for pr in prs or [] if isinstance(pr, dict) and isinstance(pr.get("numero"), int))}
    if locais is None:   # git falhou: duplicados só com os PRs; um duplicado ausente pode ser falta de dado (ausente())
        d["sem_locais"] = True
    return d


# ---------------------------------------------------------------- chaves, ignorados e pedidos ao líder
_RE_CHAVE = re.compile(r"(?:dup:[^\s,]+(?:,[^\s,]+)+|circulo:[^:\x00-\x1f]+:[^\x00-\x1f]+|parado:[1-9]\d{0,6})")
_trava = threading.Lock()   # uma gravação por vez dentro do servidor (o arquivo é trocado de uma vez: tmp + replace)


def chave_dup(d):
    return "dup:" + ",".join(sorted(str(b) for b in d.get("branches") or []))


def chave_circulo(c):
    return f"circulo:{c.get('agente')}:{c.get('arquivo')}"


def chave_parado(x):
    return f"parado:{x.get('numero')}"


def chave_valida(chave):
    """dup:<branches ordenadas unidas por ","> | circulo:<agente>:<arquivo> | parado:<n>, até MAX_CHAVE caracteres."""
    return isinstance(chave, str) and 0 < len(chave) <= MAX_CHAVE and bool(_RE_CHAVE.fullmatch(chave))


def sem_ignorados(dados, ignorados):
    """Cópia de `dados` (saude.resumo) sem os itens cuja chave está em `ignorados` ("abertos" fica: é o estado dos PRs)."""
    ign = set(ignorados or ())
    if not isinstance(dados, dict) or not ign:
        return dados
    d = dict(dados)
    if isinstance(d.get("duplicados"), dict):
        d["duplicados"] = {k: [x for x in v if not (isinstance(x, dict) and chave_dup(x) in ign)] if isinstance(v, list) else v
                           for k, v in d["duplicados"].items()}
    if isinstance(d.get("circulos"), list):
        d["circulos"] = [c for c in d["circulos"] if not (isinstance(c, dict) and chave_circulo(c) in ign)]
    if isinstance(d.get("parados"), list):
        d["parados"] = [x for x in d["parados"] if not (isinstance(x, dict) and chave_parado(x) in ign)]
    return d


def _ler(arq, padrao):
    try:
        v = json.loads(Path(arq).read_text(encoding="utf-8"))
        return v if isinstance(v, type(padrao)) else padrao
    except (OSError, ValueError):
        return padrao


def _gravar(arq, obj):
    """Grava `obj` em JSON de uma vez (tmp + os.replace); no Windows o antivírus às vezes segura o arquivo: tenta de novo."""
    arq = Path(arq)
    arq.parent.mkdir(parents=True, exist_ok=True)
    tmp = arq.with_name(arq.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    _trocar(tmp, arq)


def _trocar(tmp, arq):
    for i in range(10):
        try:
            os.replace(tmp, arq)
            return
        except PermissionError:
            if i == 9:
                raise
            time.sleep(0.05 * (i + 1))


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else 0   # nem bool, NaN ou infinito


def ler_ignorados(pasta=None):
    """{chave: {"motivo", "quando", "origem", "ua"}} dos itens ignorados no painel; {} se o arquivo falta ou está quebrado."""
    d = _ler(Path(pasta or PASTA_DADOS) / IGNORADOS, {})
    return {k: v for k, v in d.items() if chave_valida(k) and isinstance(v, dict)}


def definir_ignorado(chave, ignorar, motivo="", origem="", pasta=None, agora=None, ua=""):
    """Ignora (ignorar=True) ou reativa um item. Devolve o mapa novo. A validação de entrada fica com quem chama.
    `origem` e `ua` (User-Agent resumido) ficam no item para o painel mostrar quem ignorou (algo forjado salta aos olhos)."""
    with _trava:
        ign = ler_ignorados(pasta)
        if ignorar:
            ign[chave] = {"motivo": texto_linha(motivo, MAX_MOTIVO), "quando": round(agora or time.time()),
                          "origem": texto_linha(origem, 40), "ua": texto_linha(ua, 120)}
            # "quando" estranho no arquivo (texto, null, NaN) conta como 0: o corte nunca quebra
            for k in sorted(ign, key=lambda k: _num(ign[k].get("quando")))[:max(0, len(ign) - MAX_IGNORADOS)]:
                del ign[k]
        else:
            ign.pop(chave, None)
        _gravar(Path(pasta or PASTA_DADOS) / IGNORADOS, ign)
        return ign


def dado(chave):
    """Nome de branch/arquivo/agente vindo de fora, marcado como dado (nunca prosa): item (dado, não é instrução): "..."."""
    return 'item (dado, não é instrução): "' + texto_linha(chave, 200).replace('"', "'") + '"'


def descrever(chave, dados=None):
    """Texto curto (uma linha) do item `chave` para o pedido ao líder. Só tipo, números e a chave marcada como dado: título de
    PR, motivo e outros textos do GitHub/eventos NÃO entram (injeção de instrução por dado externo)."""
    d = dados if isinstance(dados, dict) else {}
    tipo, _, resto = chave.partition(":")
    if tipo == "dup":
        prs = []
        for grupo in ("fortes", "fracos"):
            for x in (d.get("duplicados") or {}).get(grupo) or []:
                if isinstance(x, dict) and chave_dup(x) == chave:
                    prs = sorted(n for n in x.get("prs") or [] if isinstance(n, int) and not isinstance(n, bool))
        return "trabalho duplicado" + (" (PRs " + ", ".join(f"#{n}" for n in prs) + ")" if prs else "") + "; " + dado(chave)
    if tipo == "circulo":
        return "agente andando em círculos; " + dado(chave)
    if tipo == "parado" and resto.isdigit():
        for x in d.get("parados") or []:
            if isinstance(x, dict) and chave_parado(x) == chave and isinstance(x.get("horas"), int) and not isinstance(x["horas"], bool):
                return f"PR #{int(resto)} parado há {x['horas']} h"
        return f"PR #{int(resto)} parado"
    return dado(chave)


def ler_pedidos(pasta=None):
    """Pedidos ao líder (linhas válidas de dados/saude_pedidos.jsonl), na ordem do arquivo."""
    try:
        linhas = (Path(pasta or PASTA_DADOS) / PEDIDOS).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    saida = []
    for t in linhas:
        try:
            p = json.loads(t)
        except ValueError:
            continue
        if isinstance(p, dict) and _num(p.get("ts")) and isinstance(p.get("texto"), str):
            saida.append(p)
    return saida


def registrar_pedido(chave, texto, pasta=None, agora=None, recado="", origem="", ua="", triagem=None):
    """Acrescenta {ts, chave, texto, recado, origem, ua} em dados/saude_pedidos.jsonl (uma linha; ts sempre crescente) e guarda
    só os últimos MAX_PEDIDOS (troca atômica). `texto` é do servidor (descrever); o `recado` digitado fica em campo separado.
    `triagem` ({"gravidade", "acao", "motivo"} já validados): aviso automático da triagem (tipo_pedido "triagem")."""
    arq = Path(pasta or PASTA_DADOS) / PEDIDOS
    with _trava:
        antigos = ler_pedidos(pasta)
        ultimo = max([p["ts"] for p in antigos] or [0])
        ped = {"ts": round(max(agora or time.time(), ultimo + 0.001), 3), "chave": chave, "texto": texto_linha(texto, MAX_TEXTO),
               "recado": texto_linha(recado, MAX_TEXTO), "origem": texto_linha(origem, 40), "ua": texto_linha(ua, 120)}
        if triagem:
            ped.update(tipo_pedido="triagem", gravidade=str(triagem.get("gravidade")), acao=str(triagem.get("acao")),
                       motivo=texto_linha(triagem.get("motivo"), 160))
        arq.parent.mkdir(parents=True, exist_ok=True)
        if len(antigos) + 1 > MAX_PEDIDOS:
            tmp = arq.with_name(arq.name + ".tmp")
            tmp.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in antigos[-(MAX_PEDIDOS - 1):] + [ped]),
                           encoding="utf-8")
            _trocar(tmp, arq)
        else:
            with open(arq, "a", encoding="utf-8") as f:
                f.write(json.dumps(ped, ensure_ascii=False) + "\n")
        return ped


def ultimo_entregue(pasta=None):
    """ts do último pedido entregue; None sem o arquivo de estado (ou ilegível)."""
    v = _ler(Path(pasta or PASTA_DADOS) / PEDIDOS_ESTADO, {}).get("ultimo_ts")
    return v if _num(v) else None


def linha_pedido(p):
    """"pedido do desenvolvedor: <texto do servidor>; recado: "<o que ele digitou>"" numa linha só, sem controle. O aviso da
    triagem sai por TEMPLATE fixo: só o tipo (da chave), a chave e o motivo marcados como dado e os enums revalidados."""
    if p.get("tipo_pedido") == "triagem":
        chave = str(p.get("chave") or "")
        g = p.get("gravidade") if p.get("gravidade") in GRAVIDADES else "?"
        a = p.get("acao") if p.get("acao") in ACOES_TRIAGEM else "?"
        mot = texto_linha(p.get("motivo"), 160).replace('"', "'")
        return (f"{PREFIXO_TRIAGEM}{TIPO_DA_CHAVE.get(chave.partition(':')[0], 'item')} {dado(chave)} — gravidade {g}, "
                f'ação sugerida {a}; motivo (dado): "{mot}"')
    rec = texto_linha(p.get("recado"), MAX_TEXTO).replace('"', "'")
    return PREFIXO_PEDIDO + texto_linha(p.get("texto"), MAX_TEXTO) + (f'; recado: "{rec}"' if rec else "")


def _travar(arq):
    """Trava entre processos: cria o arquivo com O_CREAT|O_EXCL; uma trava com mais de TRAVA_VALIDADE s é de um processo que
    morreu e é retomada. True se conseguiu."""
    for _ in range(2):
        try:
            os.close(os.open(arq, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            return True
        except FileExistsError:
            try:
                if time.time() - os.stat(arq).st_mtime <= TRAVA_VALIDADE:
                    return False
                os.remove(arq)
            except OSError:
                return False
        except OSError:
            return False
    return False


def pedidos_a_entregar(pasta=None, entregar=None, agora=None, dados=None):
    """Linhas "pedido do desenvolvedor: ..." / "triagem (modelo barato): ..." ainda não entregues. Chama `entregar(linhas)`
    (ex.: imprimir) ANTES de gravar o estado (último ts em saude_pedidos_estado.json): se a gravação falhar, entregar de novo
    é melhor que perder. Sem o arquivo de estado, só os pedidos das últimas SEM_ESTADO_H horas. Com outro processo entregando
    (trava), devolve []. Pedido cancelado (item resolvido antes da entrega: `cancelados` do saude_ciclo.json, ou ausente em
    `dados` calculado depois do pedido) não sai, mas conta como visto."""
    pasta = Path(pasta or PASTA_DADOS)
    pasta.mkdir(parents=True, exist_ok=True)
    trava = pasta / PEDIDOS_TRAVA
    if not _travar(trava):
        return []
    try:
        limite = ultimo_entregue(pasta)
        if limite is None:
            limite = (agora or time.time()) - SEM_ESTADO_H * 3600
        novos = [p for p in ler_pedidos(pasta) if p["ts"] > limite]
        if not novos:
            return []
        canc = ler_ciclo(pasta)["cancelados"]
        linhas = [linha_pedido(p) for p in novos if str(p["ts"]) not in canc
                  and not (p["ts"] < _num((dados or {}).get("ts")) and ausente(str(p.get("chave") or ""), dados))]
        if entregar and linhas:
            entregar(linhas)
        try:
            _gravar(pasta / PEDIDOS_ESTADO, {"ultimo_ts": max(p["ts"] for p in novos)})
        except OSError:
            pass   # entregue sem marcar: sai de novo na próxima rodada (melhor repetir que perder)
        return linhas
    finally:
        try:
            os.remove(trava)
        except OSError:
            pass


# ---------------------------------------------------------------- rodada: resolvidos, expiração e cancelamento
def presentes(dados):
    """{chave: descrição curta} de tudo o que `dados` (saude.resumo) mostra: duplicados (fortes e fracos), círculos e parados."""
    out = {}
    if not isinstance(dados, dict):
        return out
    for grupo in ("fortes", "fracos"):
        for x in (dados.get("duplicados") or {}).get(grupo) or []:
            if isinstance(x, dict) and x.get("branches"):
                out[chave_dup(x)] = texto_linha(", ".join(map(str, x["branches"])), 200)
    for c in dados.get("circulos") or []:
        if isinstance(c, dict):
            out[chave_circulo(c)] = texto_linha(f"{c.get('agente')} em {c.get('arquivo')}", 200)
    for x in dados.get("parados") or []:
        if isinstance(x, dict):
            out[chave_parado(x)] = texto_linha(f"PR #{x.get('numero')} {x.get('titulo') or ''}", 200)
    return out


def ausente(chave, dados):
    """True só se `dados` é completo para o tipo da chave e ela não está lá. Com sem_prs (GitHub fora ou PRONTO não carregado)
    duplicados e parados faltam por falta de dado, não por resolução: só um círculo pode estar ausente."""
    if not isinstance(dados, dict) or dados.get("erro") or not chave:
        return False
    if dados.get("sem_prs") and not chave.startswith("circulo:"):
        return False
    if dados.get("sem_locais") and chave.startswith("dup:"):   # git falhou: duplicado ausente pode ser só falta das branches locais
        return False
    return chave not in presentes(dados)


def ler_ciclo(pasta=None):
    c = _ler(Path(pasta or PASTA_DADOS) / CICLO, {})
    return {"ts": _num(c.get("ts")), "vistos": c.get("vistos") if isinstance(c.get("vistos"), dict) else {},
            "desde": c.get("desde") if isinstance(c.get("desde"), dict) else {},
            "resolvidos": [r for r in c.get("resolvidos") or [] if isinstance(r, dict) and chave_valida(r.get("chave"))],
            "cancelados": c.get("cancelados") if isinstance(c.get("cancelados"), dict) else {}}


PENDENTE_MAX_S = 300   # chamada ao modelo (timeout 90 s) que não terminou nisso foi interrompida


def ler_triagem(pasta=None):
    t = _ler(Path(pasta or PASTA_DADOS) / TRIAGEM, {})
    ver = t.get("veredictos") if isinstance(t.get("veredictos"), dict) else {}
    pc = t.get("por_chave") if isinstance(t.get("por_chave"), dict) else {}
    agora = time.time()
    ver = {k: (dict(v, pendente=False, erro="triagem interrompida") if v.get("pendente") and agora - _num(v.get("quando")) > PENDENTE_MAX_S
               else v) for k, v in ver.items() if isinstance(v, dict)}
    return {"veredictos": {k: v for k, v in ver.items() if chave_valida(k) and isinstance(v, dict)},
            "dia": str(t.get("dia") or ""), "hoje": int(_num(t.get("hoje"))), "chamadas": int(_num(t.get("chamadas"))),
            "custo_usd": float(_num(t.get("custo_usd"))),
            # por chave, sobrevive à expiração do veredicto: {"dia", "n" (triagens no dia), "aviso" (ts do último aviso)}
            "por_chave": {k: v for k, v in pc.items() if chave_valida(k) and isinstance(v, dict)}}


def silencia(v):
    """Veredicto que silencia: falso positivo não desfeito e de gravidade baixa ou média (falso positivo "alta" é contraditório
    ou induzido por dado de terceiros: vira alerta normal)."""
    return isinstance(v, dict) and v.get("problema") is False and not v.get("desfeito") and v.get("gravidade") != "alta"


def silenciados(triagem):
    """Chaves que a triagem julgou falso positivo (e o desenvolvedor não desfez): não alertam nem vão ao --pendentes."""
    return {k for k, v in (triagem or {}).get("veredictos", {}).items() if silencia(v)}


def rodada(dados, pasta=None, agora=None):
    """Depois de cada cálculo (servidor.saude_atual): o que estava na rodada anterior e saiu vira "resolvido" (24 h no painel);
    ignorado, veredicto da triagem e pedido não entregue de um item ausente numa rodada calculada DEPOIS deles expiram
    (ignorar vale só para a ocorrência atual: se voltar, alerta de novo). Respeita sem_prs (ausente()). Devolve o resumo."""
    if not isinstance(dados, dict) or dados.get("erro"):
        return {}
    agora = agora or time.time()
    ts = _num(dados.get("ts")) or agora
    pasta = Path(pasta or PASTA_DADOS)
    with _trava:
        ciclo = ler_ciclo(pasta)
        pres = presentes(dados)
        antes = ciclo["vistos"]
        resolvidos_agora = [k for k in antes if ausente(k, dados)]
        vistos = {k: v for k, v in antes.items() if k not in resolvidos_agora}
        vistos.update(pres)
        vistos = dict(list(vistos.items())[-MAX_VISTOS:])
        res = [r for r in ciclo["resolvidos"] if agora - _num(r.get("quando")) < RESOLVIDOS_H * 3600 and r["chave"] not in pres]
        res += [{"chave": k, "quando": round(agora), "desc": texto_linha(antes[k], 200)} for k in resolvidos_agora]
        ign = ler_ignorados(pasta)
        expirados = [k for k, v in ign.items() if ausente(k, dados) and _num(v.get("quando")) < ts]
        if expirados:
            for k in expirados:
                del ign[k]
            _gravar(pasta / IGNORADOS, ign)
        tri = ler_triagem(pasta)
        tri_exp = [k for k, v in tri["veredictos"].items() if ausente(k, dados) and _num(v.get("quando")) < ts]
        if tri_exp:
            for k in tri_exp:
                del tri["veredictos"][k]
            _gravar(pasta / TRIAGEM, tri)
        ult = ultimo_entregue(pasta) or 0
        peds = ler_pedidos(pasta)
        canc = dict(ciclo["cancelados"])
        cancelados_agora = []
        for p in peds:
            k = str(p["ts"])
            if p["ts"] > ult and k not in canc and p["ts"] < ts and ausente(str(p.get("chave") or ""), dados):
                canc[k] = round(agora)
                cancelados_agora.append(p.get("chave"))
        validos = {str(p["ts"]) for p in peds}
        canc = {k: v for k, v in canc.items() if k in validos}
        novo_em = round(agora) if _num(ciclo.get("ts")) else round(agora) - SEGURAR_MIN * 60 - 1   # sem ciclo anterior: já existia
        desde = {k: ciclo["desde"].get(k) if _num(ciclo["desde"].get(k)) else novo_em for k in vistos}
        _gravar(pasta / CICLO, {"ts": ts, "vistos": vistos, "desde": desde, "resolvidos": res[-MAX_RESOLVIDOS:], "cancelados": canc})
    return {"resolvidos": resolvidos_agora, "ignorados_expirados": expirados, "triagem_expirada": tri_exp,
            "pedidos_cancelados": cancelados_agora}


SEGURAR_MIN = 15   # item novo (duplicado forte, círculo) espera o veredicto da triagem até 15 min antes de alertar/acordar o líder


def segurados(dados, triagem, ciclo, triagem_ativa, agora=None, max_por_chave=2):
    """Chaves de duplicados fortes e círculos NOVOS ainda sem veredicto, vistos pela 1ª vez há menos de SEGURAR_MIN: o alerta e
    o --pendentes esperam a triagem (evita acordar o líder antes de ela dizer se é falso positivo). Triagem desligada ou
    indisponível (triagem_ativa False) → nada é segurado: comportamento de antes."""
    if not triagem_ativa or not isinstance(dados, dict):
        return set()
    agora = agora or time.time()
    ver, desde = (triagem or {}).get("veredictos", {}), (ciclo or {}).get("desde", {})
    chaves = [chave_dup(d) for d in (dados.get("duplicados") or {}).get("fortes") or [] if isinstance(d, dict)]
    chaves += [chave_circulo(c) for c in dados.get("circulos") or [] if isinstance(c, dict)]
    por_chave, hoje = (triagem or {}).get("por_chave", {}), time.strftime("%Y-%m-%d", time.localtime(agora))
    out = set()
    for k in chaves:
        v = ver.get(k)
        if v and not v.get("pendente"):
            continue   # já tem veredicto (problema, falso positivo ou erro): segue a regra normal
        pc = por_chave.get(k) if isinstance(por_chave, dict) else None
        if isinstance(pc, dict) and pc.get("dia") == hoje and _num(pc.get("n")) >= max_por_chave:
            continue   # a triagem desta chave já esgotou hoje: o veredicto não vem, não adianta segurar
        d = _num(desde.get(k))
        if not d:
            continue   # sem "desde" válido (ciclo não gravado, apagado, 1ª leitura): falha aberto, alerta como antes
        if d > agora:
            continue   # "desde" no futuro (relógio voltou): inválido, falha aberto
        if agora - d < SEGURAR_MIN * 60:
            out.add(k)
    return out


def pendentes(dados, agora=None, ignorados=()):
    """Linhas para o líder (duplicados fortes e círculos, fora os ignorados); [] se não há nada ou o arquivo está velho."""
    agora = agora or time.time()
    if not isinstance(dados, dict) or agora - (dados.get("ts") or 0) > VALIDADE_ARQ:
        return []
    dados = sem_ignorados(dados, ignorados)
    # todo campo passa por texto_linha: uma linha só, sem controle (nada forja "pedido do desenvolvedor:" no começo de linha)
    linhas = [f"duplicado: {texto_linha(d.get('motivo'), 120)}: {texto_linha(', '.join(map(str, d.get('branches') or [])), 300)}"
              for d in (dados.get("duplicados") or {}).get("fortes") or [] if isinstance(d, dict)]
    # sem as contagens: elas mudam a cada rodada e o vigia (que só não repete a MESMA saída) acordaria o líder de novo
    linhas += [f"círculo: {texto_linha(c.get('agente'), 40)} edita {texto_linha(c.get('arquivo'), 120)} e roda o mesmo comando "
               "de novo e de novo" for c in dados.get("circulos") or [] if isinstance(c, dict)]
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
    # pedidos primeiro, impressos ANTES de marcar entregues; o vigia emite uma linha por pedido e não os conta no "mesma saída"
    impressas = []

    def imprimir(linhas):
        print("\n".join(linhas), flush=True)
        impressas.extend(linhas)
    fresco = dados if isinstance(dados, dict) and time.time() - _num(dados.get("ts")) <= VALIDADE_ARQ else None
    pedidos_a_entregar(entregar=imprimir, dados=fresco)
    # ignorados no painel, falsos positivos da triagem (não desfeitos) e itens novos esperando a triagem não acordam o líder
    tri = ler_triagem()
    try:
        import saude_triagem   # import tardio: saude_triagem importa saude
        ativa = saude_triagem.disponivel(tri)
    except Exception:
        ativa = False
    linhas = pendentes(dados, ignorados=set(ler_ignorados()) | silenciados(tri) | segurados(dados, tri, ler_ciclo(), ativa))
    if linhas:
        print("\n".join(linhas))
    elif not impressas:
        print("NADA")
    return 0


if __name__ == "__main__":
    sys.exit(main())
