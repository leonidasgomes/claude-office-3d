# -*- coding: utf-8 -*-
"""Plugins do Claude Code num projeto: quanto cada um pesa no contexto e quais desligar (sem tokens).

Cada skill e cada comando de um plugin ativo põe a sua descrição na lista que entra no contexto de TODA sessão, e essa lista
é relida a cada resposta. Num time real a lista tinha 201 skills (~10 mil tokens), a maior parte de plugins sincronizados
do claude.ai sem relação com o projeto (vendas, finanças, jurídico...). Desligar no projeto não mexe nos outros projetos.

Uso: python plugins_projeto.py                              lista os plugins ativos e o peso de cada um
     python plugins_projeto.py --projeto C:/projetos/app    mostra também o enabledPlugins do .claude/settings.json dele
     python plugins_projeto.py --projeto C:/projetos/app --desligar sales@synced,finance@synced
     python plugins_projeto.py --projeto C:/projetos/app --religar sales@synced
O peso é uma estimativa e um limite superior (caracteres das descrições / 3,5; o Claude Code pode encurtar descrições
longas na lista). A lista vem de `claude plugin list --json`.
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path


def plugins(projeto=None):
    """Lista do `claude plugin list --json` rodado DENTRO da pasta do projeto: o "enabled" é o daquele projeto."""
    exe = shutil.which("claude")
    if not exe:
        sys.exit("não achei o comando `claude` no PATH")
    r = subprocess.run([exe, "plugin", "list", "--json"], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       cwd=projeto or None)
    if r.returncode:
        sys.exit("`claude plugin list --json` falhou: " + (r.stderr.strip() or "sem detalhe")[:200])
    vistos = {}
    for p in json.loads(r.stdout or "[]"):
        vistos.setdefault(p["id"], p)      # o mesmo plugin pode aparecer por projeto; o peso é o mesmo
    return list(vistos.values())


def _descricao(arquivo):
    """Texto de `description` (+ `when_to_use`) do cabeçalho YAML de um SKILL.md ou comando .md."""
    try:
        t = arquivo.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    m = re.match(r"---\s*\n(.*?)\n---", t, re.S)
    if not m:
        return ""
    cab = m.group(1)
    partes = re.findall(r"^(?:description|when_to_use):\s*(.+(?:\n[ \t]+.+)*)", cab, re.M)
    return " ".join(partes)


def peso(p):
    raiz = Path(p.get("installPath") or "")
    skills = list(raiz.glob("skills/*/SKILL.md")) if raiz.is_dir() else []
    comandos = list(raiz.glob("commands/*.md")) if raiz.is_dir() else []
    chars = sum(len(_descricao(f)) + len(f.parent.name if f.name == "SKILL.md" else f.stem) + 4 for f in skills + comandos)
    mcp = 0
    for f in (raiz / ".mcp.json", raiz / ".claude-plugin" / "plugin.json"):
        try:
            mcp += len((json.loads(f.read_text(encoding="utf-8")).get("mcpServers") or {}))
        except (OSError, ValueError, AttributeError):
            pass
    return len(skills), len(comandos), mcp, round(chars / 3.5)


def settings_do(projeto):
    return Path(projeto) / ".claude" / "settings.json"


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    args = sys.argv[1:]
    proj = args[args.index("--projeto") + 1] if "--projeto" in args else None
    desligar = args[args.index("--desligar") + 1].split(",") if "--desligar" in args else []
    religar = args[args.index("--religar") + 1].split(",") if "--religar" in args else []
    if (desligar or religar) and not proj:
        sys.exit("--desligar/--religar precisam de --projeto <pasta do projeto>")
    if proj and (desligar or religar):
        arq = settings_do(proj)
        if not arq.parent.parent.is_dir():
            sys.exit(f"pasta do projeto não existe: {proj}")
        try:
            dados = json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else {}
        except ValueError:
            sys.exit(f"{arq} não é JSON válido; corrija antes")
        ep = dados.setdefault("enabledPlugins", {})
        for n in filter(None, (x.strip() for x in desligar)):
            ep[n] = False
        for n in filter(None, (x.strip() for x in religar)):
            ep.pop(n, None)
        arq.parent.mkdir(exist_ok=True)
        arq.write_text(json.dumps(dados, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"gravado em {arq}: " + ", ".join(f"{k}={v}" for k, v in ep.items()))
        print("Vale na próxima sessão aberta nesse projeto (os outros projetos não mudam).")
        return 0
    ps = plugins(proj)
    proj_ep = {}
    if proj:
        try:
            proj_ep = json.loads(settings_do(proj).read_text(encoding="utf-8")).get("enabledPlugins") or {}
        except (OSError, ValueError):
            proj_ep = {}
    linhas = []
    for p in ps:
        s, c, m, tok = peso(p)
        ativo = proj_ep.get(p["id"], p.get("enabled", True))   # o settings do projeto manda; senão, o que o claude disse ali
        linhas.append((tok, p["id"], p.get("scope", ""), ativo, s, c, m))
    total = sum(l[0] for l in linhas if l[3])
    print(f"Plugins (peso = tokens das descrições que entram em toda sessão; ativos somam ~{total})"
          + (f" — visão do projeto {proj}" if proj else ""))
    for tok, pid, escopo, ativo, s, c, m in sorted(linhas, reverse=True):
        print(f"  {'ATIVO' if ativo else 'desl.'}  ~{tok:>5} tokens  {s:>3} skills  {c:>3} comandos  {m} MCP  {pid}  ({escopo})")
    print("Para desligar num projeto: python plugins_projeto.py --projeto <pasta> --desligar <id>,<id>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
