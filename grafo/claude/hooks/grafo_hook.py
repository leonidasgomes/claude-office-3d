#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Hooks do Claude Code para o grafo de arquitetura (nunca derrubam o agente; saída rápida).

Uso (o instalar_grafo.py grava estes comandos no .claude/settings.json do projeto):
  grafo_hook.py pre                 PreToolUse (Edit|Write|MultiEdit): na 1ª vez por sessão que o agente toca um
                                    sistema, devolve additionalContext curto ("arquivo do sistema X; depende de...").
  grafo_hook.py post                PostToolUse (Write): arquivo de código novo sem dono -> additionalContext com a
                                    sugestão de dono (uma vez por arquivo por sessão).
  grafo_hook.py fim [--bloquear] [--base REF]
                                    Stop / SubagentStop / TaskCompleted: roda `validate --base` (só o que mudou). Por
                                    padrão só avisa (systemMessage, para o humano). Com --bloquear e erro: Stop devolve
                                    decision=block (o agente corrige antes de parar; não repete se stop_hook_active) e
                                    TaskCompleted sai com código 2 (stderr volta para o agente).

Entrada: JSON do Claude Code no stdin (session_id, cwd, hook_event_name, tool_name, tool_input...).
Saída: JSON em ASCII (o Claude Code lê a saída do hook fora de UTF-8 no Windows). Qualquer falha do próprio hook
termina com código 0 e sem saída (só uma linha no stderr). Estado por sessão em <temp>/grafo-claude/sessao-*.json.
Ache o grafo.py por: variável GRAFO_PY (arquivo ou pasta), a mesma pasta deste script ou até duas pastas acima.
"""
import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path

PASTA_ESTADO = Path(os.environ.get("GRAFO_ESTADO") or Path(tempfile.gettempdir()) / "grafo-claude")
DIAS_ESTADO = 3
MAX_MENSAGEM = 9000   # additionalContext/systemMessage: o Claude Code aceita até 10.000 caracteres
BASES_AUTO = ("origin/HEAD", "origin/main", "origin/master", "main", "master")


def importar_grafo():
    cands = []
    env = os.environ.get("GRAFO_PY")
    if env:
        p = Path(env)
        cands.append(p.parent if p.is_file() else p)
    aqui = Path(__file__).resolve().parent
    cands += [aqui, aqui.parent, aqui.parent.parent]
    for c in cands:
        if (c / "grafo.py").is_file():
            sys.path.insert(0, str(c))
            import grafo  # noqa: PLC0415
            return grafo
    raise ImportError("grafo.py não encontrado (defina GRAFO_PY)")


def emitir(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=True))
    sys.stdout.flush()


def arquivo_estado(sessao, raiz):
    chave = hashlib.sha1(f"{sessao}|{str(raiz).lower()}".encode("utf-8")).hexdigest()[:16]
    return PASTA_ESTADO / f"sessao-{chave}.json"


def ler_estado(arq):
    try:
        return json.loads(arq.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"sistemas": [], "avisados": []}


def gravar_estado(arq, estado):
    try:
        PASTA_ESTADO.mkdir(parents=True, exist_ok=True)
        if not arq.exists():   # sessão nova: limpa estados velhos
            limite = time.time() - DIAS_ESTADO * 86400
            for velho in PASTA_ESTADO.glob("sessao-*.json"):
                try:
                    if velho.stat().st_mtime < limite:
                        velho.unlink()
                except OSError:
                    pass
        tmp = arq.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(estado), encoding="utf-8")
        os.replace(tmp, arq)
    except OSError:
        pass


def caminho_do_tool(ent):
    ti = ent.get("tool_input") or {}
    tr = ent.get("tool_response") or {}
    return ti.get("file_path") or ti.get("notebook_path") or ti.get("path") or (tr.get("filePath") if isinstance(tr, dict) else None)


def projeto(grafo, ent):
    cwd = ent.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    proj = grafo.Projeto(grafo.achar_raiz(cwd))
    if proj.grafo_arq is None or not proj.grafo_arq.is_file():
        return None
    return proj


def modo_pre(grafo, ent):
    alvo = caminho_do_tool(ent)
    if not alvo:
        return
    proj = projeto(grafo, ent)
    if proj is None:
        return
    m = grafo.modelo_hook(proj)
    donos = grafo.Donos([{"id": sid, "paths": s["paths"]} for sid, s in m["sistemas"].items()])
    rel = grafo.normalizar_caminho(alvo, proj.raiz, None, donos)
    d = donos.dono(rel)
    if not d:
        return
    sid = d[0]
    arq = arquivo_estado(ent.get("session_id") or "sem-sessao", proj.raiz)
    estado = ler_estado(arq)
    if sid in estado.get("sistemas", []):
        return
    estado.setdefault("sistemas", []).append(sid)
    gravar_estado(arq, estado)
    texto = grafo.contexto_curto(m["sistemas"][sid], sid, rel)
    emitir({"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": texto[:MAX_MENSAGEM]}})


def modo_post(grafo, ent):
    alvo = caminho_do_tool(ent)
    if not alvo:
        return
    proj = projeto(grafo, ent)
    if proj is None:
        return
    m = grafo.modelo_hook(proj)
    donos = grafo.Donos([{"id": sid, "paths": s["paths"]} for sid, s in m["sistemas"].items()])
    rel = grafo.normalizar_caminho(alvo, proj.raiz, None, donos)
    if rel.startswith("..") or donos.dono(rel) or not grafo.coberto_por(m["cobertura"], rel):
        return
    arq = arquivo_estado(ent.get("session_id") or "sem-sessao", proj.raiz)
    estado = ler_estado(arq)
    if rel in estado.get("avisados", []):
        return
    estado.setdefault("avisados", []).append(rel)
    gravar_estado(arq, estado)
    g = proj.grafo()
    an = grafo.Analise(proj, g)
    sug = grafo.sugerir(proj, g, an, rel)
    nome_grafo = g.arquivo_sistemas.name
    if sug:
        s = sug[0]
        texto = (f"[grafo] {rel} é código sem sistema dono. Sugestão: {s['sistema']} ({'; '.join(s['motivos'])}). "
                 f"Registre o caminho em paths: desse sistema (YAML do grafo, {nome_grafo}) ou rode "
                 f"`grafo.py suggest {rel}`; o validate reprova código órfão.")
    else:
        texto = (f"[grafo] {rel} é código sem sistema dono e não há sugestão. Registre-o em paths: de um sistema "
                 f"no YAML do grafo ({nome_grafo}) ou crie um sistema novo.")
    emitir({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": texto[:MAX_MENSAGEM]}})


def base_auto(grafo, proj):
    base = proj.config.get("base")
    if base:
        return str(base)
    for ref in BASES_AUTO:
        rc, out = grafo.git(proj.raiz, "merge-base", "HEAD", ref, timeout=15)
        if rc == 0 and out.strip():
            return out.strip()
    return "HEAD"


def modo_fim(grafo, ent, args):
    proj = projeto(grafo, ent)
    if proj is None or not proj.repo.eh_git:
        return 0
    bloquear = "--bloquear" in args
    base = args[args.index("--base") + 1] if "--base" in args and args.index("--base") + 1 < len(args) else None
    base = base or base_auto(grafo, proj)
    # saída rápida: nada coberto mudou e o YAML do grafo também não
    mudados = proj.repo.mudados(base)
    m = grafo.modelo_hook(proj)
    fontes = set()
    for f in m.get("fontes", []):
        try:
            fontes.add(Path(f).resolve().relative_to(proj.raiz).as_posix().lower())
        except ValueError:
            pass
    if not any(x.lower() in fontes or grafo.coberto_por(m["cobertura"], x) for x in mudados):
        return 0
    rep = grafo.validar(proj, base=base)
    erros = [e["msg"] for e in rep.erros]
    avisos = [a["msg"] for a in rep.avisos]
    if not erros and not avisos:
        return 0
    linhas = [f"[grafo] validate --base {base[:12]}: {len(erros)} erro(s), {len(avisos)} aviso(s) nos arquivos mudados."]
    linhas += [f"ERRO {e}" for e in erros[:12]] + [f"AVISO {a}" for a in avisos[:8]]
    if len(erros) > 12 or len(avisos) > 8:
        linhas.append("(mais: python grafo.py validate --base " + base[:12] + ")")
    texto = "\n".join(linhas)[:MAX_MENSAGEM]
    evento = ent.get("hook_event_name") or ""
    # mesmo resultado da última vez nesta sessão: o aviso não se repete a cada turno
    arq = arquivo_estado(ent.get("session_id") or "sem-sessao", proj.raiz)
    estado = ler_estado(arq)
    marca = hashlib.sha1(texto.encode("utf-8")).hexdigest()[:12]
    repetido = estado.get("ultimo_fim") == marca
    if not repetido:
        estado["ultimo_fim"] = marca
        gravar_estado(arq, estado)
    if bloquear and erros:
        if evento == "TaskCompleted":
            sys.stderr.write(texto + "\nCorrija (registre o arquivo no grafo, declare a dependência ou mude o import) antes de concluir.\n")
            return 2
        if evento in ("Stop", "SubagentStop") and not ent.get("stop_hook_active"):
            emitir({"decision": "block", "reason": texto + "\nCorrija antes de terminar (grafo.py slice/suggest ajudam)."})
            return 0
    if not repetido:
        emitir({"systemMessage": texto})
    return 0


def main(argv):
    try:
        modo = argv[1] if len(argv) > 1 else ""
        bruto = sys.stdin.buffer.read().decode("utf-8", "replace") if not sys.stdin.isatty() else ""
        ent = json.loads(bruto or "{}")
        if not isinstance(ent, dict):
            return 0
        grafo = importar_grafo()
        if modo == "pre":
            modo_pre(grafo, ent)
        elif modo == "post":
            modo_post(grafo, ent)
        elif modo == "fim":
            return modo_fim(grafo, ent, argv[2:])
        return 0
    except BaseException as e:  # noqa: BLE001 — o hook nunca derruba o agente
        try:
            sys.stderr.write(f"grafo_hook: {type(e).__name__}: {e}\n")
        except Exception:  # noqa: BLE001
            pass
        return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
