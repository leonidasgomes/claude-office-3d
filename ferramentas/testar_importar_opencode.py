# -*- coding: utf-8 -*-
"""Testes do importar_opencode.py num projeto falso em pasta temporária.

Uso: python -W error ferramentas/testar_importar_opencode.py
"""
import io
import json
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
import importar_opencode as io_  # noqa: E402

FALHAS = []


def checar(nome, condicao, detalhe=""):
    print(f"  {'ok' if condicao else 'FALHOU'}: {nome}")
    if not condicao:
        FALHAS.append(f"{nome} {detalhe}")


def montar(tmp):
    proj = Path(tmp) / "proj"
    ag = proj / ".claude" / "agents"
    ag.mkdir(parents=True)
    (ag / "dev.md").write_text("---\nname: dev\ndescription: Faz código\ntools: Read, Bash, Monitor\n"
                               "model: sonnet\nmaxTurns: 40\neffort: high\n---\nVocê é o dev.\n", encoding="utf-8")
    (ag / "sem-desc.md").write_text("---\nname: sem-desc\n---\nNada.\n", encoding="utf-8")
    sk = proj / ".claude" / "skills" / "boa"
    sk.mkdir(parents=True)
    (sk / "SKILL.md").write_text("---\nname: boa\ndescription: Uma skill boa.\n---\nCorpo.\n", encoding="utf-8")
    (proj / ".claude" / "skills" / "ruim").mkdir(parents=True)
    (proj / "CLAUDE.md").write_text("# Regras\n", encoding="utf-8")
    (proj / "AGENTS.md").write_text("Ver CLAUDE.md\n", encoding="utf-8")
    return proj


def sair(fn, *args):
    buf = io.StringIO()
    with redirect_stdout(buf):
        codigo = fn(*args)
    return codigo, buf.getvalue()


def main():
    tmp = tempfile.mkdtemp(prefix="importar-teste-")
    proj = montar(tmp)

    codigo, plano = sair(io_.main, ["--projeto", str(proj)])
    checar("plano sai 0 sem escrever", codigo == 0 and not (proj / ".opencode").exists()
           and not (proj / "opencode.json").exists(), plano)
    checar("plano lista agente, plugin e mudanças", "dev -> .opencode/agents/dev.md" in plano
           and "plugin office.js -> .opencode/plugins/office.js" in plano
           and "instructions += CLAUDE.md" in plano, plano)
    checar("plano avisa só model (Monitor vira task, effort vira linha)", "sonnet" in plano and "Monitor" not in plano
           and "effort sem equivalente" not in plano, plano)
    checar("plano mostra ERRO do sem description", "ERRO" in plano and "sem-desc" in plano, plano)
    checar("plano lista skill ruim", "ruim: sem SKILL.md" in plano, plano)

    codigo, _ = sair(io_.main, ["--projeto", str(proj), "--aplicar", "--sonnet", "prov/sonnet-1"])
    gerado = proj / ".opencode" / "agents" / "dev.md"
    texto = gerado.read_text(encoding="utf-8")
    checar("aplicar sai 0 e gera agente", codigo == 0 and gerado.is_file(), texto[:200])
    checar("frontmatter convertido", "mode: subagent" in texto and "model: prov/sonnet-1" in texto
           and "read: allow" in texto and "bash: allow" in texto and "steps: 40" in texto, texto[:400])
    checar("Monitor vira task e effort vira linha no prompt", "task: allow" in texto
           and "Nível de esforço: high" in texto, texto[:600])
    checar("sem-desc não gera arquivo", not (proj / ".opencode" / "agents" / "sem-desc.md").exists())
    cfg = json.loads((proj / "opencode.json").read_text(encoding="utf-8"))
    checar("opencode.json com instructions (sem array plugin)", "CLAUDE.md" in cfg["instructions"]
           and "plugin" not in cfg, cfg)
    plug = proj / ".opencode" / "plugins" / "office.js"
    checar("plugin copiado igual ao original",
           plug.is_file() and plug.read_bytes() == (RAIZ / "opencode" / "office.js").read_bytes())

    codigo, segunda = sair(io_.main, ["--projeto", str(proj), "--aplicar"])
    checar("segunda aplicação mantém (sem --forcar)", "mantido: dev" in segunda
           and len(list((proj / ".opencode" / "agents").glob("*.md"))) == 1, segunda)
    checar("sem mudanças não reescreve nem backupa",
           segunda.count("backup:") == 0 and (proj / "opencode.json").read_text(encoding="utf-8").count("CLAUDE.md") == 1, segunda)

    buf = io.StringIO()
    with redirect_stdout(buf):
        codigo = io_.main(["--projeto", str(Path(tmp) / "inexistente")])
    checar("projeto sem .claude sai 2", codigo == 2, codigo)

    r = subprocess.run([sys.executable, '-X', 'utf8', str(RAIZ / "importar_opencode.py"), "--projeto", str(proj)],
                       capture_output=True, text=True, encoding='utf-8', timeout=60)
    checar("CLI plano via subprocess", r.returncode == 0 and "plano" in r.stdout, (r.returncode, r.stderr))

    print("OK" if not FALHAS else f"{len(FALHAS)} FALHA(S): {FALHAS}")
    return 1 if FALHAS else 0


if __name__ == "__main__":
    sys.exit(main())
