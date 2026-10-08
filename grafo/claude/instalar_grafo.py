#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Instala (ou remove) os hooks do grafo no .claude/settings.json DO PROJETO alvo (nunca no do usuário).

Uso:
  python instalar_grafo.py [--projeto P]                 mostra o que faria (nada é gravado)
  python instalar_grafo.py [--projeto P] --aplicar       grava em P/.claude/settings.json
  python instalar_grafo.py [--projeto P] --desinstalar [--aplicar]   remove só as entradas do grafo
Opções:
  --copiar      copia grafo.py e grafo_hook.py para P/.claude/grafo/ (o time recebe pelo git) e usa
                "$CLAUDE_PROJECT_DIR/.claude/grafo/grafo_hook.py"; sem ela, o comando aponta para esta pasta (absoluto)
  --skill       copia a SKILL.md para P/.claude/skills/grafo/SKILL.md
  --bloquear    o verificador de fim bloqueia com erro (padrão: só avisa)
  --fim E1,E2   eventos do verificador (padrão: Stop,TaskCompleted; vazio desliga)
  --python CMD  interpretador nos comandos (padrão: o Python que roda o instalador, caminho absoluto — no macOS/Linux
                pode não haver "python" no PATH; com --copiar o padrão é `python`, porque o settings.json vai para o git)
Recusa (código 2) quando a raiz é a pasta do usuário ou o alvo seria o ~/.claude/settings.json do usuário.

Não duplica: as entradas cujo comando contém "grafo_hook.py" são trocadas pelas novas; o resto do arquivo fica igual.
"""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
HOOK = AQUI / "hooks" / "grafo_hook.py"
GRAFO = AQUI.parent / "grafo.py"
SKILL = AQUI / "SKILL.md"
MARCA = "grafo_hook.py"


def raiz_projeto(p):
    p = Path(p or ".").resolve()
    try:
        out = subprocess.run(["git", "-C", str(p), "rev-parse", "--show-toplevel"], capture_output=True, text=True,
                             timeout=15)
        if out.returncode == 0 and out.stdout.strip():
            return Path(out.stdout.strip()).resolve()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return p


def eh_do_usuario(raiz, arq):
    """True se a raiz resolvida é a pasta do usuário (cwd ~, --projeto ~, repositório de dotfiles na home) ou se o alvo é o
    ~/.claude/settings.json do usuário: esse arquivo vale para todas as sessões e nunca é tocado aqui."""
    try:
        casa = Path.home().resolve()
    except (RuntimeError, OSError):
        return False
    try:
        alvo = Path(arq).resolve()
    except OSError:
        alvo = Path(arq)
    return Path(raiz).resolve() == casa or alvo == (casa / ".claude" / "settings.json").resolve()


def comandos(args):
    if args.copiar:
        alvo = '"$CLAUDE_PROJECT_DIR/.claude/grafo/grafo_hook.py"'
    else:
        alvo = '"' + HOOK.as_posix() + '"'
    # com --copiar o settings.json vai para o git do time: nada de caminho absoluto do Python desta máquina
    py = args.python or ("python" if args.copiar else '"' + Path(sys.executable).as_posix() + '"')

    def cmd(sub):
        if args.copiar:  # a cópia pode faltar num clone antigo: sem ela o hook sai 0 (código 2 no PreToolUse bloquearia Edit/Write)
            return f'f={alvo}; if [ -f "$f" ]; then {py} "$f" {sub}; else exit 0; fi'
        return f"{py} {alvo} {sub}"

    fim = cmd("fim" + (" --bloquear" if args.bloquear else ""))
    entradas = {
        "PreToolUse": {"matcher": "Edit|Write|MultiEdit", "hooks": [
            {"type": "command", "command": cmd("pre"), "timeout": 15, "statusMessage": "Grafo: contexto do sistema"}]},
        "PostToolUse": {"matcher": "Write", "hooks": [
            {"type": "command", "command": cmd("post"), "timeout": 30, "statusMessage": "Grafo: dono do arquivo novo"}]},
    }
    for ev in [e.strip() for e in args.fim.split(",") if e.strip()]:
        entradas[ev] = {"hooks": [{"type": "command", "command": fim, "timeout": 120,
                                   "statusMessage": "Grafo: validando o que mudou"}]}
    return entradas


def sem_grafo(grupos):
    """Lista de grupos sem os hooks do grafo (grupos vazios somem)."""
    out = []
    for g in grupos or []:
        if not isinstance(g, dict):
            out.append(g)
            continue
        hooks = [h for h in g.get("hooks", []) if MARCA not in str((h or {}).get("command", ""))]
        if hooks:
            out.append({**g, "hooks": hooks})
        elif not g.get("hooks"):
            out.append(g)
    return out


def forma_invalida(s):
    """Descrição do problema se 'hooks' não tem a forma esperada ({evento: [{matcher?, hooks: [{...}]}]})."""
    if "hooks" not in s:
        return None
    hooks = s["hooks"]
    if not isinstance(hooks, dict):
        return "'hooks' deveria ser um objeto"
    for ev, grupos in hooks.items():
        if not isinstance(grupos, list):
            return f"'hooks.{ev}' deveria ser uma lista"
        for i, g in enumerate(grupos):
            if not isinstance(g, dict):
                return f"'hooks.{ev}[{i}]' deveria ser um objeto"
            if "hooks" in g and (not isinstance(g["hooks"], list) or not all(isinstance(h, dict) for h in g["hooks"])):
                return f"'hooks.{ev}[{i}].hooks' deveria ser uma lista de objetos"
    return None


def novo_settings(atual, entradas, desinstalar):
    s = json.loads(json.dumps(atual))
    hooks = s.get("hooks") if isinstance(s.get("hooks"), dict) else {}
    for ev in list(hooks):
        hooks[ev] = sem_grafo(hooks[ev])
        if not hooks[ev]:
            del hooks[ev]
    if not desinstalar:
        for ev, grupo in entradas.items():
            hooks.setdefault(ev, []).append(grupo)
    if hooks:
        s["hooks"] = hooks
    else:
        s.pop("hooks", None)
    return s


def main(argv=None):
    for st in (sys.stdout, sys.stderr):
        if hasattr(st, "reconfigure"):
            st.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--projeto", help="raiz do projeto alvo (padrão: topo do git da pasta atual)")
    ap.add_argument("--aplicar", action="store_true", help="grava (sem isso, só mostra)")
    ap.add_argument("--desinstalar", action="store_true", help="remove as entradas do grafo")
    ap.add_argument("--copiar", action="store_true", help="copia grafo.py e o hook para .claude/grafo/ do projeto")
    ap.add_argument("--skill", action="store_true", help="copia a SKILL.md para .claude/skills/grafo/")
    ap.add_argument("--bloquear", action="store_true", help="verificador de fim bloqueia com erro")
    ap.add_argument("--fim", default="Stop,TaskCompleted", help="eventos do verificador (padrão Stop,TaskCompleted)")
    ap.add_argument("--python", default=None,
                    help="interpretador nos comandos (padrão: o que roda este instalador, entre aspas)")
    args = ap.parse_args(argv)

    raiz = raiz_projeto(args.projeto)
    arq = raiz / ".claude" / "settings.json"
    if eh_do_usuario(raiz, arq):
        print(f"ERRO: {raiz.as_posix()} é a pasta do usuário: o alvo seria o settings.json do USUÁRIO "
              f"({arq.as_posix()}). Rode dentro do repositório do projeto ou use --projeto <raiz do projeto>; nada foi feito.",
              file=sys.stderr)
        return 2
    if args.copiar and not args.python and not args.desinstalar:
        print("aviso: com --copiar o comando gravado usa `python` (vai para o git do time); no macOS/Linux sem `python` no PATH, "
              "use --python python3", file=sys.stderr)
    try:
        atual = json.loads(arq.read_text(encoding="utf-8")) if arq.is_file() else {}
    except ValueError as e:
        print(f"ERRO: {arq} não é JSON válido ({e}); nada foi feito.", file=sys.stderr)
        return 2
    if not isinstance(atual, dict):
        print(f"ERRO: {arq} não é um objeto JSON; nada foi feito.", file=sys.stderr)
        return 2
    forma = forma_invalida(atual)
    if forma:
        print(f"ERRO: {arq}: {forma}; nada foi feito (corrija à mão).", file=sys.stderr)
        return 2
    entradas = comandos(args)
    novo = novo_settings(atual, entradas, args.desinstalar)
    mudou = novo != atual
    print(f"projeto: {raiz.as_posix()}")
    print(f"arquivo: {arq.as_posix()} ({'existe' if arq.is_file() else 'novo'})")
    if args.desinstalar:
        print("remover: entradas com 'grafo_hook.py'" + ("" if mudou else " (nenhuma encontrada)"))
    else:
        print("hooks do grafo:")
        print(json.dumps(entradas, ensure_ascii=False, indent=2))
    copias = []
    if args.copiar and not args.desinstalar:
        copias += [(GRAFO, raiz / ".claude" / "grafo" / "grafo.py"), (HOOK, raiz / ".claude" / "grafo" / "grafo_hook.py")]
    if args.skill and not args.desinstalar:
        copias.append((SKILL, raiz / ".claude" / "skills" / "grafo" / "SKILL.md"))
    for de, para in copias:
        print(f"copiar: {de.as_posix()} -> {para.as_posix()}")
    if not args.aplicar:
        print("(nada gravado; para gravar: --aplicar)" if (mudou or copias) else "(já está assim; nada a fazer)")
        return 0
    if mudou:
        arq.parent.mkdir(parents=True, exist_ok=True)
        arq.write_text(json.dumps(novo, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        print(f"gravado: {arq.as_posix()}")
    else:
        print("settings.json já estava assim")
    for de, para in copias:
        para.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(de, para)
        print(f"copiado: {para.as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
