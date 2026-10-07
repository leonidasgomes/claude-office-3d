"""Hook do Claude Code que alimenta o Claude Office 3D.

Ligado em PreToolUse (só Bash/PowerShell) / PostToolUse / PostToolUseFailure (só Bash/PowerShell) / TeammateIdle / Stop /
SubagentStop. Lê o JSON do hook no stdin e acrescenta UMA linha
na tabela evento do banco local (banco.py, dados/escritorio.db, na pasta ao lado deste script). Nunca bloqueia o
agente: qualquer erro sai com código 0 e sem saída; se o banco estiver ocupado ou quebrado, a linha vai para
dados/eventos.falha.jsonl.

Só registra sessões cujo diretório de trabalho (cwd) está dentro de uma das pastas de "projetos" do config.json
(lista vazia = registra todas as sessões).

Formato de cada linha:
{"ts": "2026-10-01T14:30:00", "agente": "Dev", "tipo": "trabalho|fala|reuniao|subagente|ocioso",
 "para": ["Lider"], "ferramenta": "Bash", "resumo": "texto curto (até 90 caracteres)",
 "texto": "mensagem completa (só fala/reunião)", "detalhe": "comando ou arquivo (só trabalho)"}
No fim de um comando Bash/PowerShell o `trabalho` leva "ok": true (o sucesso chega no PostToolUse) ou false com "codigo" e
"erro" (a falha só chega no PostToolUseFailure, "Exit code N"); em segundo plano, nada (`resultado_de`).
No início de um comando Bash/PowerShell em primeiro plano (PreToolUse), o `trabalho` leva também "inicio": true e
"espera_s" (o timeout do comando em s, padrão 120, de 1 a 600).
"""
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import configuracao  # noqa: E402  (módulo ao lado deste script)

PASTA = Path(__file__).resolve().parent / "dados"
FALHA = PASTA / "eventos.falha.jsonl"   # reserva: o banco não aceitou (ocupado > 5 s, disco cheio)
MAX_TEXTO = 2000      # mensagem entre agentes, completa até aqui
MAX_DETALHE = 400     # comando/arquivo do trabalho
# subagente sem nome: apelido pelo tipo (o escritório mostra nome + função)
APELIDOS = {"general-purpose": "Assistente", "explore": "Explorador", "plan": "Planejador",
            "claude-code-guide": "Guia_Claude", "statusline-setup": "Configurador"}

CFG = configuracao.carregar()
LIDER = (configuracao.lider(CFG) or {}).get("nome", "Lider")
PALAVRAS_REUNIAO = tuple(CFG["palavras_reuniao"])
NOMES = {}            # chave (minúsculas, '-'->'_') -> nome canônico do agente
for _ag in CFG["agentes"]:
    NOMES[configuracao.chave(_ag["nome"])] = _ag["nome"]
    for _o in _ag["outros_nomes"]:
        NOMES.setdefault(configuracao.chave(_o), _ag["nome"])
for _o in ("main", "lead", "leader", "team_lead"):
    NOMES.setdefault(_o, LIDER)
CONHECIDOS = {a["nome"] for a in CFG["agentes"]}
SUFIXO_NUMERO = re.compile(r"[_-]\d+[a-z]?$", re.I)   # Dev_235, Dev_66b: um por tarefa (mesma regra do escritorio.js)


def normalizar(nome):
    n = str(nome or "").strip()
    # endereço de outra sessão do Claude (pipe/socket/ponte), não um agente do time
    if n.lower().startswith(("uds:", "bridge:")) or "\\pipe\\" in n.lower():
        return "Outra_Sessao"
    if re.fullmatch(r"a[0-9a-f]{12,}", n.lower()):
        return "Assistente"  # id interno de subagente
    if not n:
        return ""
    if configuracao.chave(n) in NOMES:   # nome do config ou um dos "outros_nomes", exatamente
        return NOMES[configuracao.chave(n)]
    n = SUFIXO_NUMERO.sub("", n)         # subagente numerado (Dev_235, Dev_66b) cai na mesa do agente
    return NOMES.get(configuracao.chave(n), n) if n else ""


def nome_do_meta(d, agente_id):
    """Lê <projeto>/<sessão>/subagents/agent-<id>.meta.json e devolve o nome dado pelo líder.
    "Dev_235" ou "Dev_66b" (um por tarefa) vira "Dev"; sem nome, tenta o começo da descrição."""
    if not agente_id or not d.get("transcript_path") or not d.get("session_id"):
        return ""
    try:
        base = Path(d["transcript_path"]).parent / str(d["session_id"]) / "subagents"
        meta = json.loads((base / f"agent-{agente_id}.meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    for texto in (meta.get("name"), str(meta.get("description") or "").split(" ")[0]):
        n = SUFIXO_NUMERO.sub("", str(texto or "").strip())
        if n and normalizar(n) in CONHECIDOS:
            return normalizar(n)
    n = SUFIXO_NUMERO.sub("", str(meta.get("name") or "").strip())
    return normalizar(n) if n else ""


def quem(d):
    """Descobre qual agente gerou o evento (do mais confiável ao heurístico)."""
    if os.environ.get("OFFICE_AGENTE"):
        return normalizar(os.environ["OFFICE_AGENTE"])
    for k in ("teammate_name", "agent_name"):
        if d.get(k):
            return normalizar(d[k])
    # colega de time: o id vem como "<nome>@<time>" (ex.: "Dev@session-14f95d4d")
    agente_id = str(d.get("agent_id") or "")
    if "@" in agente_id and agente_id.split("@", 1)[0]:
        return normalizar(agente_id.split("@", 1)[0])
    # subagente/colega com id interno: o nome está no .meta.json ao lado do histórico dele
    nome = nome_do_meta(d, agente_id)
    if nome:
        return nome
    tipo = str(d.get("agent_type") or "")
    if tipo and normalizar(tipo) in CONHECIDOS:
        return normalizar(tipo)   # subagente definido em .claude/agents/<nome>.md com o mesmo nome do agente
    if d.get("agent_id"):
        return normalizar(APELIDOS.get(tipo.lower(), "Assistente"))
    return LIDER   # sessão principal


def detalhe_de(entrada):
    """O que exatamente o agente fez (comando, arquivo, busca), para a ficha do agente."""
    partes = []
    for k in ("skill", "args", "command", "file_path", "path", "pattern", "glob", "url", "query", "prompt", "subagent_type", "name"):
        v = (entrada or {}).get(k)
        if v:
            partes.append(f"{k}: {v}")
    return "\n".join(partes)[:MAX_DETALHE]


def resumo_de(ferramenta, entrada):
    entrada = entrada or {}
    if entrada.get("skill"):   # ferramenta Skill: o XP conta quem usa a skill de quem
        return ("usa a skill " + str(entrada["skill"]))[:90]
    for k in ("description", "summary", "file_path", "pattern", "prompt", "command", "url", "query"):
        if entrada.get(k):
            texto = str(entrada[k])
            if k == "file_path":
                verbo = "lê" if ferramenta == "Read" else "edita"
                texto = f"{verbo} {Path(texto).name}"
            return " ".join(texto.split())[:90]
    return ferramenta


def chama_reuniao(entrada):
    """Mensagem que convoca reunião (ex.: 'Reunião: alinhar a próxima etapa'), pelas palavras_reuniao do config."""
    alvo = " ".join(str(x) for x in (entrada.get("summary") or "", str(entrada.get("message") or "")[:200])).lower()
    return any(p in alvo for p in PALAVRAS_REUNIAO)


FERRAMENTAS_LONGAS = ("Bash", "PowerShell")   # PreToolUse só registra o início destas (ver evento())
CAMPOS_SAIDA = ("exit_code", "exitCode", "returncode", "returnCode")


def resultado_de(nome_evento, ferramenta, d):
    """Sucesso ou falha de um comando (Bash/PowerShell): {"ok": bool, "codigo"?: int, "erro"?: str} ou {} se não dá para saber.
    Aceita os formatos possíveis do Claude Code: `tool_response.exit_code` no PostToolUse, o evento PostToolUseFailure
    (campo `error`), `interrupted` e a resposta em texto "Error: Exit code N" (como fica no transcrito)."""
    if ferramenta not in FERRAMENTAS_LONGAS:
        return {}
    if nome_evento == "PostToolUseFailure":   # medido em 7 out. 2026: comando que falha só chega aqui, error "Exit code N"
        m = re.match(r"\s*Exit\s+code\s+(\d+)", str(d.get("error") or ""))
        return {"ok": False, **({"codigo": int(m.group(1))} if m else {}), "erro": _erro_curto(d.get("error"))}
    r = d.get("tool_response")
    if isinstance(r, dict):
        for k in CAMPOS_SAIDA:
            if isinstance(r.get(k), int) and not isinstance(r.get(k), bool):
                return {"ok": r[k] == 0, "codigo": r[k]}
        if r.get("interrupted") is True:
            return {"ok": False, "erro": "interrompido"}
        ti = d.get("tool_input")
        if isinstance(ti, dict) and ti.get("run_in_background"):
            return {}   # em segundo plano o PostToolUse chega no INÍCIO: não dá para saber se vai dar certo
        if nome_evento == "PostToolUse" and ("stdout" in r or "stderr" in r):
            return {"ok": True}   # medido em 7 out. 2026: sucesso chega no PostToolUse sem exit_code (a falha vai ao PostToolUseFailure)
    elif isinstance(r, str):   # só o formato exato do Claude Code ("Error: Exit code N"); saída que começa com "Error" não conta
        m = re.match(r"\s*Error: Exit code (\d+)", r)
        if m:
            return {"ok": False, "codigo": int(m.group(1)), "erro": f"exit code {m.group(1)}"}
    return {}


def _erro_curto(texto):
    """Só a 1ª linha do erro, curta (o banco de eventos é lido pelo celular: nada da saída inteira do comando)."""
    linha = next((l for l in str(texto or "").splitlines() if l.strip()), "falhou")
    return " ".join(linha.split())[:120]


def evento(d):
    nome_evento = d.get("hook_event_name", "")
    agente = quem(d)
    base = {"ts": datetime.now().isoformat(timespec="seconds"), "agente": agente}
    if nome_evento in ("TeammateIdle", "Stop", "SubagentStop"):
        return {**base, "tipo": "ocioso", "para": [], "ferramenta": "", "resumo": "aguardando"}
    ferramenta = d.get("tool_name", "")
    entrada = d.get("tool_input") or {}
    if nome_evento == "PreToolUse":
        # início de comando que pode demorar (Bash/PowerShell em primeiro plano): o PostToolUse só chega no fim, e o
        # painel apagaria o "trabalhando" depois de 60 s. `espera_s` = o timeout do comando (padrão 120 s, até 600 s).
        if ferramenta not in FERRAMENTAS_LONGAS or entrada.get("run_in_background"):
            return None
        try:
            espera = int(float(entrada.get("timeout") or 120000) / 1000)
        except (TypeError, ValueError, OverflowError):
            espera = 120
        return {**base, "tipo": "trabalho", "inicio": True, "espera_s": max(1, min(espera, 600)), "para": [],
                "ferramenta": ferramenta, "resumo": resumo_de(ferramenta, entrada), "detalhe": detalhe_de(entrada)}
    if ferramenta == "SendMessage":
        alvo = entrada.get("to") or entrada.get("recipient") or ""
        alvos = alvo if isinstance(alvo, list) else [alvo]
        alvos = [normalizar(a) if a != "*" else "*" for a in alvos if a]
        tipo = "reuniao" if "*" in alvos or len(alvos) > 1 or chama_reuniao(entrada) else "fala"
        texto = entrada.get("summary") or entrada.get("message") or "mensagem"
        completo = entrada.get("message") or entrada.get("summary") or ""
        if not isinstance(completo, str):
            completo = json.dumps(completo, ensure_ascii=False)
        return {**base, "tipo": tipo, "para": [a for a in alvos if a != "*"], "ferramenta": ferramenta,
                "resumo": " ".join(str(texto).split())[:90], "texto": completo[:MAX_TEXTO]}
    if ferramenta in ("Agent", "Task"):
        tipo_sub = str(entrada.get("subagent_type") or "general-purpose")
        nome = entrada.get("name") or (tipo_sub if configuracao.chave(tipo_sub) in NOMES
                                       else APELIDOS.get(tipo_sub.lower(), tipo_sub))
        return {**base, "tipo": "subagente", "para": [normalizar(nome)], "ferramenta": ferramenta,
                "resumo": resumo_de(ferramenta, entrada), "funcao": tipo_sub, "modelo": entrada.get("model", "")}
    return {**base, "tipo": "trabalho", "para": [], "ferramenta": ferramenta, "resumo": resumo_de(ferramenta, entrada),
            "detalhe": detalhe_de(entrada), **resultado_de(nome_evento, ferramenta, d)}


def main():
    try:
        d = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace") or "{}")
        # o hook pode valer para todas as sessões do usuário: só registra o que é dos projetos monitorados
        if CFG["projetos"] and not configuracao.pasta_dentro(d.get("cwd", ""), CFG["projetos"]):
            sys.exit(0)
        PASTA.mkdir(exist_ok=True)
        ev = evento(d)
        if ev is None:
            sys.exit(0)
        try:
            import banco  # ao lado deste script; importado só depois do filtro de projeto
            banco.gravar_evento(ev)
        except Exception:
            with FALHA.open("a", encoding="utf-8") as f:
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    except Exception:
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
