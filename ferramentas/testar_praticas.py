"""Teste das boas práticas do projeto (boas_praticas.py), do .venv do escritório (instalar.py) e de GET /api/praticas.

Uso: python -W error ferramentas/testar_praticas.py
Cobre: detecção das tecnologias e do comando de teste (com limite de profundidade e pastas pesadas puladas); cada checagem
em pastas temporárias (com e sem git: repositório temporário, .env versionado, regra de pasta-mãe do .gitignore); corrigir
sem --aplicar não muda nada; aplicar é idempotente e não sobrescreve arquivo; backup do settings do projeto ao trocar o
python dos hooks do grafo; .gitignore CRLF continua CRLF; caminho do Python do .venv no Windows e no Linux/macOS; a CLI
(validar/corrigir, --json, --so, códigos de saída); a rota GET /api/praticas (servidor numa thread, porta livre, cache,
celular sem caminhos absolutos no projeto, no detalhe e no erro, "calculando" quando a validação demora); GET /api/versao (conteúdo do VERSION); a revisão de PR (regra revisao-pr, com_revisor,
criar_revisor sem sobrescrever, seção "Fluxo de PR" do líder ou do CLAUDE.md quando não há lider.md, revisor casado por
palavra: "previsao"/"preview" não contam) e o `instalar.py --revisao PROJETO` (diff, backup, idempotente); o ignore global
do usuário não conta no .gitignore; o comando do hook aparece sem perder o "_"; .venv quebrado só é recriado com confirmação;
a regra scripts-do-projeto.md (dica, gravada do modelo, nunca sobrescrita) e a seção "Cartão rascunho" do modelo do líder.
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
import boas_praticas as bp  # noqa: E402
import instalar  # noqa: E402

feitos, falhas = [], []
CONFIG = {"agentes": [{"nome": "Lider", "lider": True, "mesa": "lider"},
                      {"nome": "Dev", "funcao": "Código e testes", "mesa": "dev"},
                      {"nome": "Revisor_PR", "funcao": "Revisa os PRs"}]}
GIT_ID = ["-c", "user.name=Teste", "-c", "user.email=teste@example.com", "-c", "commit.gpgsign=false"]


def checar(nome, cond, info=""):
    if cond:
        feitos.append(nome)
        print("  ok:", nome)
    else:
        falhas.append(nome)
        print("  FALHOU:", nome, str(info)[:600])


def pasta_temp():
    return tempfile.TemporaryDirectory(prefix="c3dbp", ignore_cleanup_errors=True)


def gravar(raiz, rel, texto="", modo="w"):
    arq = Path(raiz) / rel
    arq.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(texto, bytes):
        arq.write_bytes(texto)
    else:
        arq.write_text(texto, encoding="utf-8", newline="\n")
    return arq


def git(raiz, *args):
    r = subprocess.run(["git", *GIT_ID, "-C", str(raiz), *args], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, f"git {args}: {r.stderr}"
    return r.stdout


def arvore(raiz):
    """{caminho relativo: bytes} de tudo fora do .git (para conferir que nada mudou)."""
    raiz = Path(raiz)
    return {p.relative_to(raiz).as_posix(): p.read_bytes() for p in raiz.rglob("*")
            if p.is_file() and ".git" not in p.relative_to(raiz).parts}


def itens(projeto, config=CONFIG, settings_usuario=None, usuario=None):
    """validar() com um settings do usuário temporário (nunca o ~/.claude de quem roda o teste)."""
    if settings_usuario is None:
        settings_usuario = Path(projeto).parent / "usuario-settings.json"
        if usuario is not None:
            settings_usuario.write_text(json.dumps(usuario), encoding="utf-8")
    return {i["id"]: i for i in bp.validar(projeto, config, settings_usuario)}


def venv_falso(raiz):
    """.venv que passa no venv_ok (pyvenv.cfg + executável), sem criar um de verdade."""
    gravar(raiz, ".venv/pyvenv.cfg", "home = x\n")
    gravar(raiz, bp.caminho_python_venv(raiz).relative_to(raiz).as_posix(), b"")


# ---------------------------------------------------------------- detecção do escopo
def testar_deteccao():
    with pasta_temp() as tmp:
        t = Path(tmp)
        vazio = bp.detectar_escopo(t)
        checar("pasta vazia: nenhuma tecnologia, sem testes", vazio == {"stacks": set(), "testes": "", "descricao": ""}, vazio)
        gravar(t, "README.md", "# Meu App\n\n[![ci](https://x/y.svg)](https://x)\n\nUm **app** de [tarefas](http://x) para times.\n"
                               "Segunda linha.\n\nOutro parágrafo.\n")
        gravar(t, "requirements.txt", "requests\n")
        gravar(t, "tests/test_algo.py", "")
        gravar(t, "front/package.json", json.dumps({"scripts": {"test": "jest"}}))
        gravar(t, "jogo/Jogo.uproject", "{}")
        gravar(t, "api/Api.csproj", "<Project/>")
        gravar(t, "sql/consulta.sql", "select 1")
        gravar(t, "web/index.html", "<p>")
        gravar(t, "a/b/c/d/fundo.ipynb", "{}")              # profundidade 4: fora do limite
        gravar(t, "node_modules/pacote/x.sln", "")           # pasta pesada: não é olhada
        e = bp.detectar_escopo(t)
        checar("detecta python, node, unreal, dotnet, dados e web",
               e["stacks"] == {"python", "node", "unreal", "dotnet", "dados", "web"}, e)
        py = ".venv/Scripts/python" if bp.WINDOWS else ".venv/bin/python"
        checar("testes: tests/test_*.py → unittest pelo Python do .venv", e["testes"] == f"{py} -m unittest discover -s tests", e)
        checar("descrição: 1º parágrafo do README sem título, selo nem markdown",
               e["descricao"] == "Um app de tarefas para times. Segunda linha.", e["descricao"])
        checar("escopo interno guarda a pasta do .uproject e do .csproj", bp._escopo(t)["_pastas"] == {"unreal": "jogo",
                                                                                                         "dotnet": "api"})
        gravar(t, "pytest.ini", "[pytest]\n")
        checar("testes: pytest.ini → pytest", bp.detectar_escopo(t)["testes"] == f"{py} -m pytest")
    with pasta_temp() as tmp:
        t = Path(tmp)
        gravar(t, "package.json", json.dumps({"scripts": {"test": "echo \"Error: no test specified\" && exit 1"}}))
        checar("node com o test padrão do npm init: sem comando de teste", bp.detectar_escopo(t)["testes"] == "")
        gravar(t, "package.json", json.dumps({"scripts": {"test": "vitest"}}))
        checar("node com script de teste: npm test", bp.detectar_escopo(t)["testes"] == "npm test")
        gravar(t, "App.sln", "")
        checar("dotnet sem npm test: dotnet test vem depois do node", bp.detectar_escopo(t)["testes"] == "npm test")
    with pasta_temp() as tmp:
        guardar = bp.MAX_ARQUIVOS
        try:
            bp.MAX_ARQUIVOS = 5
            for i in range(20):
                gravar(tmp, f"f{i:02}.txt", "")
            checar("teto de arquivos lidos na detecção", len(bp._varrer(Path(tmp))) == 5)
        finally:
            bp.MAX_ARQUIVOS = guardar


# ---------------------------------------------------------------- checagens
def testar_sem_git():
    with pasta_temp() as tmp:
        proj = Path(tmp) / "proj"
        proj.mkdir()
        i = itens(proj)
        checar("sem git: checagem git = erro", not i["git"]["ok"] and i["git"]["nivel"] == "erro" and not i["git"]["corrigivel"])
        checar("sem .gitignore: aviso corrigível", not i["gitignore"]["ok"] and i["gitignore"]["corrigivel"])
        checar("segredos fora do git: erro corrigível, lista as 3 linhas", not i["segredos-ignorados"]["ok"]
               and i["segredos-ignorados"]["nivel"] == "erro" and "*.pem" in i["segredos-ignorados"]["como_corrigir"], i["segredos-ignorados"])
        checar("agente comum sem definição = erro; líder = aviso", i["agente-dev"]["nivel"] == "erro" and not i["agente-dev"]["ok"]
               and i["agente-lider"]["nivel"] == "aviso" and i["agente-revisor_pr"]["nivel"] == "erro")
        checar("sem CLAUDE.md, testes, grafo, CI: aviso, aviso, dica, dica",
               [(i[k]["ok"], i[k]["nivel"]) for k in ("claude-md", "testes", "grafo", "ci")]
               == [(False, "aviso"), (False, "aviso"), (False, "dica"), (False, "dica")])
        checar("sem python: nenhuma checagem python-*", not any(k.startswith("python-") for k in i))
        checar("env-versionado ok sem git", i["env-versionado"]["ok"])
        checar("validar não devolve o campo interno _correcao", not any(k.startswith("_") for x in i.values() for k in x))
        # fallback sem git: o .gitignore lido à mão
        gravar(proj, ".gitignore", ".env\n*.pem\n/segredos/*.key\n.claude/settings.local.json\n")
        i = itens(proj)
        checar("sem git: .gitignore lido à mão (padrão ancorado não cobre *.key na raiz)", not i["segredos-ignorados"]["ok"]
               and i["segredos-ignorados"]["detalhe"].endswith("*.key") and i["settings-local-ignorado"]["ok"], i["segredos-ignorados"])
        gravar(proj, ".gitignore", ".env\n*.pem\n*.key\n.claude/\n!.claude/settings.json\n")
        checar("sem git: pasta-mãe ignorada cobre o arquivo", itens(proj)["settings-local-ignorado"]["ok"])
        checar("_casa_gitignore: negação e só pasta", bp._casa_gitignore(bp._padroes_gitignore(proj), ".claude/settings.json") is False
               and bp._casa_gitignore([(False, "build", True, False)], "build") is False
               and bp._casa_gitignore([(False, "build", True, False)], "build/") is True)


def testar_com_git():
    with pasta_temp() as tmp:
        proj = Path(tmp) / "proj"
        proj.mkdir()
        git(proj, "init", "-q")
        gravar(proj, ".env", "CHAVE=1\n")
        gravar(proj, "config/.env.producao", "X=1\n")
        gravar(proj, ".env.example", "CHAVE=\n")
        gravar(proj, "app.py", "print(1)\n")
        git(proj, "add", "-A")
        git(proj, "commit", "-q", "-m", "inicio")
        i = itens(proj)
        checar("git: repositório reconhecido", i["git"]["ok"])
        checar("git: .env e .env.producao versionados = erro (o .example não conta)", not i["env-versionado"]["ok"]
               and i["env-versionado"]["detalhe"] == "versionado no git: .env, config/.env.producao", i["env-versionado"])
        checar("env-versionado não é corrigível (git rm --cached é manual)", not i["env-versionado"]["corrigivel"])
        gravar(proj, ".gitignore", "node_modules/\n.env\n*.pem\n*.key\n.claude/settings.local.json\n.venv/\n")
        i = itens(proj)
        checar("git check-ignore: segredos, settings.local e .venv cobertos", i["segredos-ignorados"]["ok"]
               and i["settings-local-ignorado"]["ok"] and i["python-venv-ignorado"]["ok"])
        checar("git check-ignore em caminhos que não existem e regra de pasta-mãe",
               bp.ignorados(proj, ["node_modules/x/y.js", ".venv/", "outro/"], True) == {"node_modules/x/y.js", ".venv/"})
        # o ignore global do usuário (core.excludesFile) não vale para quem clona o projeto: não conta
        gravar(proj, ".gitignore", "node_modules/\n.env\n*.pem\n*.key\n.venv/\n")
        glob_ign = gravar(tmp, "ignore-global", ".claude/settings.local.json\n")
        glob_cfg = gravar(tmp, "gitconfig-global", f"[core]\n\texcludesFile = {glob_ign.as_posix()}\n")
        antes_env = os.environ.get("GIT_CONFIG_GLOBAL")
        os.environ["GIT_CONFIG_GLOBAL"] = str(glob_cfg)
        try:
            global_vale = subprocess.run(["git", "-C", str(proj), "check-ignore", "--no-index", ".claude/settings.local.json"],
                                         capture_output=True, timeout=30).returncode == 0
            i = itens(proj)
            checar("settings.local só no ignore global do usuário: settings-local-ignorado avisa", global_vale
                   and not i["settings-local-ignorado"]["ok"] and ".claude/settings.local.json" in i["settings-local-ignorado"]["detalhe"],
                   (global_vale, i["settings-local-ignorado"]))
            gravar(proj, ".git/info/exclude", ".claude/settings.local.json\n")
            checar(".git/info/exclude do projeto conta", itens(proj)["settings-local-ignorado"]["ok"])
        finally:
            if antes_env is None:
                os.environ.pop("GIT_CONFIG_GLOBAL", None)
            else:
                os.environ["GIT_CONFIG_GLOBAL"] = antes_env
        git(proj, "rm", "-q", "--cached", ".env", "config/.env.producao")
        git(proj, "commit", "-q", "-m", "tira o env")
        checar("git: depois do git rm --cached, env-versionado ok", itens(proj)["env-versionado"]["ok"])


def testar_python():
    with pasta_temp() as tmp:
        proj = Path(tmp) / "proj"
        gravar(proj, "app.py", "")
        i = itens(proj)
        checar("python sem .venv: aviso corrigível (criar)", not i["python-venv"]["ok"] and i["python-venv"]["corrigivel"])
        checar("python sem requirements: aviso manual", not i["python-dependencias"]["ok"] and not i["python-dependencias"]["corrigivel"])
        checar("python sem regra: aviso corrigível", not i["python-regra-venv"]["ok"] and i["python-regra-venv"]["corrigivel"])
        checar("python sem hooks e sem agentes: ok", i["python-hooks-venv"]["ok"] and i["python-agentes-venv"]["ok"])
        gravar(proj, ".venv/lixo.txt", "x")
        i = itens(proj)
        checar(".venv incompleto: aviso NÃO corrigível (não mexe na pasta)", not i["python-venv"]["ok"]
               and not i["python-venv"]["corrigivel"] and "incompleto" in i["python-venv"]["detalhe"])
        (proj / ".venv" / "lixo.txt").unlink()
        (proj / ".venv").rmdir()
        venv_falso(proj)
        gravar(proj, "requirements-dev.txt", "pytest\n")
        gravar(proj, bp.REGRA_VENV.as_posix(), "regra\n")
        i = itens(proj)
        checar(".venv, requirements-dev.txt e regra: ok", i["python-venv"]["ok"] and i["python-dependencias"]["ok"]
               and i["python-regra-venv"]["ok"], i["python-dependencias"])
        hooks = {"hooks": {"PreToolUse": [{"hooks": [{"type": "command", "command": "python grafo/claude/grafo_hook.py pre"}]}],
                           "PostToolUse": [{"hooks": [{"type": "command", "command": "py -3 scripts/outro.py"},
                                                      {"type": "command", "command": "python D:/office/registrar_evento.py"}]}]}}
        gravar(proj, ".claude/settings.json", json.dumps(hooks))
        i = itens(proj)
        checar("hooks com python solto: aviso; o do escritório não conta", not i["python-hooks-venv"]["ok"]
               and "outro.py" in i["python-hooks-venv"]["detalhe"] and "registrar_evento" not in i["python-hooks-venv"]["detalhe"])
        checar("hook do grafo com python solto: corrigível", i["python-hooks-venv"]["corrigivel"])
        checar("detalhe do hook mostra o comando como está (grafo_hook.py, não grafohook.py)",
               "grafo/claude/grafo_hook.py pre" in i["python-hooks-venv"]["detalhe"], i["python-hooks-venv"]["detalhe"])
        hooks["hooks"].pop("PreToolUse")
        gravar(proj, ".claude/settings.json", json.dumps(hooks))
        checar("só hook alheio com python solto: manual", not itens(proj)["python-hooks-venv"]["corrigivel"])
        gravar(proj, ".claude/settings.local.json", "{quebrado")
        i = itens(proj)
        checar("settings do projeto inválido: aparece no detalhe", not i["python-hooks-venv"]["ok"]
               and "settings.local.json inválido" in i["python-hooks-venv"]["detalhe"])
        gravar(proj, ".claude/agents/a.md", "Rode `python -m pytest` antes.\n")
        gravar(proj, ".claude/agents/b.md", "Rode `.venv/bin/python -m pytest`.\n")
        gravar(proj, ".claude/agents/c.md", "Sem comandos.\n")
        i = itens(proj)
        checar("agente que roda python sem citar o .venv: aviso só para ele", not i["python-agentes-venv"]["ok"]
               and i["python-agentes-venv"]["detalhe"] == "rodam python sem citar o .venv: a.md", i["python-agentes-venv"])


def testar_outras_stacks():
    with pasta_temp() as tmp:
        proj = Path(tmp) / "proj"
        gravar(proj, "package.json", "{}")
        gravar(proj, "jogo/Jogo.uproject", "{}")
        gravar(proj, "src/Api/Api.csproj", "<Project/>")
        gravar(proj, ".gitignore", "jogo/Binaries/\nIntermediate/\nSaved/\n")
        i = itens(proj)
        checar("node sem node_modules no .gitignore e sem lockfile: avisos", not i["node-modules-ignorado"]["ok"]
               and not i["node-lockfile"]["ok"] and i["node-modules-ignorado"]["nivel"] == "aviso")
        checar("unreal: pastas relativas ao .uproject, só a que falta", not i["unreal-ignorados"]["ok"]
               and i["unreal-ignorados"]["detalhe"] == "o .gitignore não cobre: DerivedDataCache/", i["unreal-ignorados"])
        checar("dotnet: bin/ e obj/ faltando", i["dotnet-ignorados"]["detalhe"] == "o .gitignore não cobre: bin/, obj/")
        gravar(proj, "package-lock.json", "{}")
        gravar(proj, ".github/workflows/ci.yml", "on: push\n")
        gravar(proj, "docs/ARCHITECTURE_GRAPH.yaml", "nos: []\n")
        gravar(proj, ".claude/CLAUDE.md", "# x\n")
        i = itens(proj)
        checar("lockfile, CI, grafo e .claude/CLAUDE.md: ok", all(i[k]["ok"] for k in ("node-lockfile", "ci", "grafo", "claude-md")))
        # hook do escritório: no settings do projeto ou no do usuário (só lido)
        checar("sem o hook do escritório: aviso", not i["hook-escritorio"]["ok"])
        usuario = {"hooks": {"PostToolUse": [{"hooks": [{"type": "command", "command": '"C:/o/.venv/Scripts/python.exe" "C:/o/registrar_evento.py"'}]}]}}
        antes = json.dumps(usuario)
        arq_usuario = Path(tmp) / "usuario-settings.json"
        i = itens(proj, usuario=usuario)
        checar("hook do escritório no settings do usuário: ok, e o arquivo não muda", i["hook-escritorio"]["ok"]
               and arq_usuario.read_text(encoding="utf-8") == antes)
        arq_usuario.unlink()
        gravar(proj, ".claude/settings.local.json", json.dumps(usuario))
        checar("hook do escritório no settings.local do projeto: ok", itens(proj)["hook-escritorio"]["ok"])
        # definição do agente achada pelo campo name, com outro nome de arquivo
        gravar(proj, ".claude/agents/qualquer.md", "---\nname: revisor-pr\n---\n")
        checar("definição achada pelo campo name do frontmatter", itens(proj)["agente-revisor_pr"]["ok"])


# ---------------------------------------------------------------- correção
def testar_corrigir():
    with pasta_temp() as tmp:
        proj = Path(tmp) / "proj"
        gravar(proj, "app.py", "")
        gravar(proj, "README.md", "Ferramenta de teste.\n")
        gravar(proj, ".claude/agents/dev.md", "MEU dev, não sobrescrever\n")
        venv_falso(proj)
        gravar(proj, ".claude/settings.json", json.dumps({"hooks": {"PreToolUse": [{"hooks": [
            {"type": "command", "command": "python grafo/claude/grafo_hook.py pre"},
            {"type": "command", "command": "python3 outro.py"}]}]}}, indent=1))
        usuario = Path(tmp) / "usuario-settings.json"
        antes = arvore(proj)
        plano = bp.corrigir(proj, config=CONFIG, settings_usuario=usuario)
        checar("plano (sem aplicar): nada muda na pasta", arvore(proj) == antes and not usuario.exists())
        checar("plano: nenhuma ação marcada como aplicada", plano and not any(a["aplicada"] for a in plano), plano)
        ids = [a["id"] for a in plano]
        checar("plano: .gitignore numa ação só, regras, agentes que faltam, hooks; sem venv (já existe)",
               ids == ["gitignore,segredos-ignorados,settings-local-ignorado,python-venv-ignorado", "python-regra-venv",
                       "scripts-regra", "agente-lider", "agente-revisor_pr", "python-hooks-venv"], ids)
        feito = bp.corrigir(proj, aplicar=True, config=CONFIG, settings_usuario=usuario)
        checar("aplicar: todas as ações sem erro", all(a["aplicada"] and not a["erro"] for a in feito), feito)
        checar("aplicar: .gitignore criado com as linhas", (proj / ".gitignore").read_text(encoding="utf-8").splitlines()
               == ["# boas práticas (Claude Office 3D)", ".env", "*.pem", "*.key", ".claude/settings.local.json", ".venv/"])
        checar("aplicar: definição existente não foi sobrescrita",
               (proj / ".claude/agents/dev.md").read_text(encoding="utf-8") == "MEU dev, não sobrescrever\n")
        rev = (proj / ".claude/agents/revisor_pr.md").read_text(encoding="utf-8")
        checar("aplicar: agente criado do modelo do revisor, com nome, descrição, projeto e testes", rev.startswith(
            '---\nname: revisor_pr\ndescription: "Revisa os PRs"\n---\n') and "**proj**" in rev and "Ferramenta de teste." in rev
            and "{{" not in rev and ".venv" in rev, rev[:400])
        lider = (proj / ".claude/agents/lider.md").read_text(encoding="utf-8")
        checar("aplicar: líder do modelo lider.md, sem 'leia o CLAUDE.md' nem model:", "**líder**" in lider
               and "leia o CLAUDE.md" not in lider and "\nmodel:" not in lider)
        regra = (proj / bp.REGRA_VENV).read_text(encoding="utf-8")
        checar("aplicar: regra python-venv.md copiada do modelo",
               regra == (RAIZ / "modelos" / "praticas" / "python-venv.md").read_text(encoding="utf-8"))
        checar("aplicar: regra scripts-do-projeto.md copiada do modelo",
               (proj / bp.REGRA_SCRIPTS).read_text(encoding="utf-8")
               == (RAIZ / "modelos" / "praticas" / "scripts-do-projeto.md").read_text(encoding="utf-8"))
        lider_md = (RAIZ / "modelos" / "time" / "lider.md").read_text(encoding="utf-8")
        checar("modelo lider.md: seção Cartão rascunho (converter antes, nunca despachar rascunho)",
               "## Cartão rascunho" in lider_md and "Nunca despache um rascunho" in lider_md and "## Cartão rascunho" in lider)
        settings = json.loads((proj / ".claude/settings.json").read_text(encoding="utf-8"))
        cmds = [h["command"] for h in settings["hooks"]["PreToolUse"][0]["hooks"]]
        checar("aplicar: python do hook do grafo trocado pelo do .venv; o alheio fica",
               cmds == [bp.python_venv_hook() + " grafo/claude/grafo_hook.py pre", "python3 outro.py"], cmds)
        baks = list((proj / ".claude").glob("settings.json.bak-*"))
        checar("aplicar: backup do settings do projeto com o conteúdo antigo", len(baks) == 1
               and baks[0].read_bytes() == antes[".claude/settings.json"], baks)
        depois = arvore(proj)
        de_novo = bp.corrigir(proj, aplicar=True, config=CONFIG, settings_usuario=usuario)
        checar("aplicar de novo: nada a fazer e nada muda (idempotente)", de_novo == [] and arvore(proj) == depois, de_novo)
        erros = [i["id"] for i in bp.validar(proj, CONFIG, usuario) if i["nivel"] == "erro" and not i["ok"]]
        checar("depois de aplicar: o único erro que resta é o manual (git init)", erros == ["git"], erros)
        checar("o settings do usuário nunca foi criado", not usuario.exists())
    with pasta_temp() as tmp:   # hooks sem .venv: não troca (o hook quebraria)
        proj = Path(tmp) / "proj"
        gravar(proj, "app.py", "")
        gravar(proj, ".venv/lixo", "x")   # .venv que não é venv: nem cria, nem troca hooks
        cfg = gravar(proj, ".claude/settings.json", json.dumps({"hooks": {"Stop": [{"hooks": [
            {"type": "command", "command": "python grafo/claude/grafo_hook.py stop"}]}]}}))
        antes = cfg.read_bytes()
        r = bp.corrigir(proj, ids={"python-hooks-venv", "python-venv"}, aplicar=True, config=CONFIG,
                        settings_usuario=Path(tmp) / "u.json")
        checar("sem .venv válido: hooks não trocados, erro explicado, settings intacto, sem backup",
               len(r) == 1 and "não existe" in r[0]["erro"] and cfg.read_bytes() == antes
               and not list(cfg.parent.glob("*.bak-*")), r)
        checar("--so: só as checagens pedidas", [a["id"] for a in bp.corrigir(proj, ids={"python-regra-venv"}, config=CONFIG,
                                                                              settings_usuario=Path(tmp) / "u.json")]
               == ["python-regra-venv"])


def testar_venv_real():
    with pasta_temp() as tmp:
        proj = Path(tmp) / "proj"
        gravar(proj, "app.py", "")
        r = bp.corrigir(proj, ids={"python-venv"}, aplicar=True, config=CONFIG, settings_usuario=Path(tmp) / "u.json")
        checar("aplicar python-venv: cria o .venv de verdade", r and r[0]["aplicada"] and bp.venv_ok(proj), r)
        cod = subprocess.run([str(bp.caminho_python_venv(proj)), "-c", "import sys; print(sys.prefix != sys.base_prefix)"],
                             capture_output=True, text=True, timeout=60)
        checar("o python do .venv roda e está num venv", cod.returncode == 0 and cod.stdout.strip() == "True", cod.stdout)


def testar_venv_quebrado():
    with pasta_temp() as tmp:
        app = Path(tmp) / "app"
        venv_falso(app)   # pyvenv.cfg + executável vazio: existe, mas o Python não roda
        exe = instalar.python_venv(app)
        perguntas = []
        sit, det = instalar.preparar_venv(app)
        checar("silencioso: .venv quebrado não é recriado (falhou com o aviso, nada apagado)", sit == "falhou"
               and "não recriei" in det and exe.is_file() and exe.read_bytes() == b"", (sit, det))
        sit, det = instalar.preparar_venv(app, lambda motivo: perguntas.append(motivo) or False)
        checar("interativo respondendo não: pergunta uma vez e não recria", sit == "falhou" and len(perguntas) == 1
               and "não roda" in perguntas[0] and exe.read_bytes() == b"", (sit, perguntas))


def testar_scripts_regra():
    with pasta_temp() as tmp:
        proj = Path(tmp) / "proj"
        gravar(proj, "README.md", "x\n")
        item = {i["id"]: i for i in bp.validar(proj, CONFIG, Path(tmp) / "u.json")}.get("scripts-regra")
        checar("scripts-regra: dica corrigível quando falta a regra", item and item["nivel"] == "dica" and not item["ok"]
               and item["corrigivel"], item)
        meu = gravar(proj, ".claude/rules/scripts-do-projeto.md", "MINHA regra\n")
        r = bp.corrigir(proj, ids={"scripts-regra"}, aplicar=True, config=CONFIG, settings_usuario=Path(tmp) / "u.json")
        item = {i["id"]: i for i in bp.validar(proj, CONFIG, Path(tmp) / "u.json")}["scripts-regra"]
        checar("scripts-regra: regra existente conta como ok e nunca é sobrescrita", r == [] and item["ok"]
               and meu.read_text(encoding="utf-8") == "MINHA regra\n", r)
        checar("scripts-regra: o modelo vai no pacote do instalador", "modelos/praticas/scripts-do-projeto.md" in instalar.PACOTE)


def testar_gitignore():
    with pasta_temp() as tmp:
        t = Path(tmp)
        original = b"# meu\r\nbuild/\r\n*.log"   # CRLF e sem quebra no fim
        gravar(t, ".gitignore", original)
        novas = bp.acrescentar_gitignore(t, [".env", "build/", ".env", "*.pem"])
        bruto = (t / ".gitignore").read_bytes()
        checar("CRLF: conteúdo antigo intacto no começo", bruto.startswith(original))
        checar("CRLF: só CRLF no arquivo (nenhum LF solto)", bruto.count(b"\n") == bruto.count(b"\r\n"), bruto)
        checar("acrescenta só o que falta, sem repetir", novas == [".env", "*.pem"] and bruto.endswith(b".env\r\n*.pem\r\n"), bruto)
        checar("idempotente", bp.acrescentar_gitignore(t, [".env", "*.pem"]) == [] and (t / ".gitignore").read_bytes() == bruto)
        gravar(t, "lf/.gitignore", "a\n")
        bp.acrescentar_gitignore(t / "lf", ["b"])
        checar("LF continua LF", (t / "lf/.gitignore").read_bytes() == b"a\n\n# boas pr\xc3\xa1ticas (Claude Office 3D)\nb\n")
        (t / "novo").mkdir()
        bp.acrescentar_gitignore(t / "novo", ["x"])
        checar("sem .gitignore: cria", (t / "novo/.gitignore").read_text(encoding="utf-8") == "# boas práticas (Claude Office 3D)\nx\n")


# ---------------------------------------------------------------- caminhos do .venv (Windows e Linux/macOS)
def testar_caminhos_venv():
    p = Path("proj")
    checar("caminho_python_venv: Windows e POSIX", bp.caminho_python_venv(p, True).as_posix() == "proj/.venv/Scripts/python.exe"
           and bp.caminho_python_venv(p, False).as_posix() == "proj/.venv/bin/python")
    checar("python_venv_hook: entre aspas, relativo a $CLAUDE_PROJECT_DIR",
           bp.python_venv_hook(True) == '"$CLAUDE_PROJECT_DIR/.venv/Scripts/python.exe"'
           and bp.python_venv_hook(False) == '"$CLAUDE_PROJECT_DIR/.venv/bin/python"')
    d = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "py -3 grafo_hook.py"}]}]}}
    novo, n = bp.trocar_python_hooks_grafo(d, windows=False)
    checar("trocar_python_hooks_grafo no Linux: bin/python; o original não muda", n == 1
           and novo["hooks"]["Stop"][0]["hooks"][0]["command"] == '"$CLAUDE_PROJECT_DIR/.venv/bin/python" grafo_hook.py'
           and d["hooks"]["Stop"][0]["hooks"][0]["command"] == "py -3 grafo_hook.py")
    guardar = instalar.WINDOWS
    with pasta_temp() as tmp:
        try:
            for win, rel in ((True, ".venv/Scripts/python.exe"), (False, ".venv/bin/python")):
                instalar.WINDOWS = win
                exe = instalar.python_venv(tmp)
                checar(f"instalar.python_venv ({'Windows' if win else 'POSIX'}): {rel}", exe.as_posix().endswith(rel)
                       and exe.is_absolute())
                checar("sem .venv: python do PATH, sem aspas", instalar.python_do_escritorio(tmp) == instalar.PYTHON_CMD
                       and instalar.chamada_python(tmp) == instalar.PYTHON_CMD)
                gravar(tmp, rel, b"")
                checar("com .venv: caminho absoluto entre aspas no comando", instalar.chamada_python(tmp)
                       == f'"{Path(tmp).absolute().as_posix()}/{rel}"')
                cmd = instalar.comando_hook(Path(tmp))
                checar("comando do hook com o python do .venv", cmd.startswith(f'"{Path(tmp).absolute().as_posix()}/{rel}" ')
                       and "registrar_evento.py" in cmd, cmd)
        finally:
            instalar.WINDOWS = guardar


# ---------------------------------------------------------------- linha de comando
def cli(*args, config=None):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    if config is not None:
        env["OFFICE_CONFIG"] = str(config)
    r = subprocess.run([sys.executable, str(RAIZ / "boas_praticas.py"), *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env, stdin=subprocess.DEVNULL, timeout=120)
    return r.returncode, r.stdout + r.stderr


def testar_cli():
    with pasta_temp() as tmp:
        t = Path(tmp)
        proj = t / "proj"
        gravar(proj, "README.md", "x\n")
        cfg = gravar(t, "config.json", json.dumps(dict(CONFIG, projetos=[str(proj)])))
        cod, out = cli("validar", str(proj), config=cfg)
        checar("CLI validar sem git: sai com 1 e mostra o ERRO", cod == 1 and "[ERRO ] Repositório git" in out, out)
        cod, out = cli("validar", "--json", config=cfg)
        dados = json.loads(out)
        checar("CLI validar --json sem PROJETO: usa os projetos do config", cod == 1 and dados[0]["projeto"] == str(proj)
               and any(i["id"] == "git" and not i["ok"] for i in dados[0]["itens"]), out[:300])
        cod, out = cli("validar", str(t / "nao-existe"), config=cfg)
        checar("CLI validar pasta inexistente: sai com 2", cod == 2 and "não encontrada" in out, out)
        antes = arvore(proj)
        cod, out = cli("corrigir", str(proj), config=cfg)
        checar("CLI corrigir sem --aplicar: plano, sai com 0, nada muda", cod == 0 and "[plano]" in out
               and "--aplicar" in out and arvore(proj) == antes, out)
        cod, out = cli("corrigir", str(proj), "--aplicar", "--so", "agente-dev,agente-revisor_pr", config=cfg)
        checar("CLI corrigir --aplicar --so: só os agentes pedidos", cod == 0 and out.count("[feito]") == 2
               and sorted(p.name for p in (proj / ".claude/agents").iterdir()) == ["dev.md", "revisor_pr.md"], out)
        git(proj, "init", "-q")
        cod, out = cli("corrigir", str(proj), "--aplicar", config=cfg)
        checar("CLI corrigir --aplicar: resto feito", cod == 0 and "[feito]" in out and (proj / ".gitignore").is_file(), out)
        cod, out = cli("validar", str(proj), config=cfg)
        checar("CLI validar depois de corrigir: sai com 0", cod == 0 and "ERRO" not in out, out)
        cod, out = cli("validar", config=gravar(t, "vazio.json", json.dumps(dict(CONFIG, projetos=[]))))
        checar("CLI sem projeto e sem projetos no config: sai com 2", cod == 2, out)
        cod, out = cli("apagar", str(proj), config=cfg)
        checar("CLI comando desconhecido: sai com erro do argparse", cod == 2, out)


# ---------------------------------------------------------------- revisão de PR (líder + revisor)
SEM_REVISOR = {"agentes": [{"nome": "Lider", "lider": True, "mesa": "lider"}, {"nome": "Dev", "mesa": "dev"}]}


def testar_revisao():
    with pasta_temp() as tmp:
        proj = Path(tmp) / "proj"
        gravar(proj, "README.md", "Ferramenta de teste.\n")
        it = itens(proj, SEM_REVISOR)["revisao-pr"]
        checar("revisao-pr: sem revisor, revisor-ia, bots nem check → aviso corrigível", not it["ok"]
               and it["nivel"] == "aviso" and it["corrigivel"] and "--revisao" in it["como_corrigir"], it)
        checar("revisao-pr: agente revisor no config basta", itens(proj, CONFIG)["revisao-pr"]["ok"])
        for nome, extra in (("revisor-ia ativo", {"revisor": {"ativo": True}}),
                            ("bots_revisao", {"github": {"bots_revisao": ["coderabbitai[bot]"]}}),
                            ("check_revisao", {"github": {"check_revisao": "revisao-ia"}})):
            it = itens(proj, dict(SEM_REVISOR, **extra))["revisao-pr"]
            checar(f"revisao-pr: {nome} basta", it["ok"], it)
        antes = arvore(proj)
        plano = bp.corrigir(proj, ids={"revisao-pr"}, config=SEM_REVISOR, settings_usuario=Path(tmp) / "u.json")
        checar("revisao-pr: plano cria revisor.md e nada muda sem aplicar",
               [a["id"] for a in plano] == ["revisao-pr"] and "revisor.md" in plano[0]["acao"] and arvore(proj) == antes, plano)
        feito = bp.corrigir(proj, ids={"revisao-pr"}, aplicar=True, config=SEM_REVISOR, settings_usuario=Path(tmp) / "u.json")
        rev = proj / ".claude/agents/revisor.md"
        texto = rev.read_text(encoding="utf-8") if rev.is_file() else ""
        checar("revisao-pr --aplicar: revisor.md do modelo (publica com gh pr review --comment, [revisor], sem merge)",
               feito and feito[0]["aplicada"] and texto.startswith("---\nname: revisor\n") and "gh pr review" in texto
               and "--comment" in texto and "[revisor]" in texto and "nunca faça merge" in texto and "{{" not in texto,
               (feito, texto[:300]))
        checar("revisao-pr: depois de aplicar, ok (definição no projeto)", itens(proj, SEM_REVISOR)["revisao-pr"]["ok"])
        checar("revisao-pr: aplicar de novo não faz nada", bp.corrigir(proj, ids={"revisao-pr"}, aplicar=True,
               config=SEM_REVISOR, settings_usuario=Path(tmp) / "u.json") == [])
    with pasta_temp() as tmp:   # revisor do usuário (outro nome ou o mesmo): nunca sobrescreve
        proj = Path(tmp) / "proj"
        meu = gravar(proj, ".claude/agents/code-reviewer.md", "---\nname: code-reviewer\n---\nMEU\n")
        checar("revisor com outro nome no projeto: revisao-pr ok e criar_revisor não cria nada",
               itens(proj, SEM_REVISOR)["revisao-pr"]["ok"] and bp.criar_revisor(proj, SEM_REVISOR) is None
               and sorted(p.name for p in meu.parent.iterdir()) == ["code-reviewer.md"])
        proj2 = Path(tmp) / "proj2"
        meu2 = gravar(proj2, ".claude/agents/revisor.md", "MEU revisor\n")
        checar("revisor.md existente: criar_revisor devolve None e não mexe",
               bp.criar_revisor(proj2, SEM_REVISOR) is None and meu2.read_text(encoding="utf-8") == "MEU revisor\n")
    sim = ["Revisor", "Revisor_PR", "revisora", "code-reviewer", "Code Reviewer", "reviewer", "Revisão", "revisao-pr", "QA.review"]
    nao = ["Previsao", "previsão", "Preview", "previewer", "Revisionista", "Dev", "Pesquisa", "superrevisor"]
    checar("eh_revisor casa por palavra (revisor, reviewer, code-reviewer, revisao...)", all(bp.eh_revisor(n) for n in sim),
           [n for n in sim if not bp.eh_revisor(n)])
    checar("eh_revisor: previsao, preview e afins não são revisor", not any(bp.eh_revisor(n) for n in nao),
           [n for n in nao if bp.eh_revisor(n)])
    checar("com_revisor: time com Preview e Previsao ainda ganha o Revisor",
           bp.com_revisor({"agentes": [{"nome": "Lider"}, {"nome": "Preview"}, {"nome": "Previsao"}]})[1] is True)
    with pasta_temp() as tmp:
        proj = Path(tmp) / "proj"
        gravar(proj, ".claude/agents/preview.md", "---\nname: preview\n---\nx\n")
        gravar(proj, ".claude/agents/previsao.md", "---\nname: previsao\n---\nx\n")
        checar("preview.md e previsao.md no projeto não contam como revisor", not itens(proj, SEM_REVISOR)["revisao-pr"]["ok"]
               and bp.caminho_revisor(proj, SEM_REVISOR) == proj / ".claude/agents/revisor.md")
    original = {"porta": 1, "agentes": [{"nome": "Lider", "lider": True}, "Dev"]}
    novo, mudou = bp.com_revisor(original)
    checar("com_revisor: acrescenta o Revisor no fim, sem mexer no original nem nas outras chaves",
           mudou and [a if isinstance(a, str) else a["nome"] for a in novo["agentes"]] == ["Lider", "Dev", "Revisor"]
           and len(original["agentes"]) == 2 and novo["porta"] == 1, novo)
    checar("com_revisor: idempotente", bp.com_revisor(novo) == (novo, False))
    checar("com_revisor: time com revisor de outro nome não ganha outro",
           bp.com_revisor({"agentes": [{"nome": "Lider"}, {"nome": "Code_Reviewer"}]})[1] is False)
    sem = bp.com_revisor({})[0]["agentes"]
    checar("com_revisor sem agentes: time padrão + Revisor (o time não vira só o revisor)",
           [a["nome"] for a in sem] == ["Lider", "Dev", "Designer", "Pesquisa", "Revisor"], sem)
    norm = bp.configuracao.normalizar(novo)
    checar("com_revisor: config normalizado com o Revisor em mesa própria", norm["agentes"][-1]["nome"] == "Revisor"
           and norm["agentes"][-1]["mesa"] == "padrao" and not norm["agentes"][-1]["lider"])
    lider = (RAIZ / "modelos" / "time" / "lider.md").read_text(encoding="utf-8")
    secao = bp.secao_fluxo_pr()
    checar("modelo do líder: seção Fluxo de PR (revisor por PR, gh pr review --comment, P0/P1 ao autor, merge é do dev)",
           "## Fluxo de PR" in lider and secao.startswith("## Fluxo de PR") and "gh pr review <n> --comment" in secao
           and "P0 ou P1" in secao and "nunca faz merge" in secao, secao)
    with pasta_temp() as tmp:
        proj = Path(tmp) / "proj"
        md = gravar(proj, ".claude/agents/lider.md", "---\nname: lider\n---\nlíder antigo\n")
        checar("lider_sem_fluxo_pr: acha o líder sem a seção", bp.lider_sem_fluxo_pr(proj, SEM_REVISOR) == md)
        gravar(proj, ".claude/agents/lider.md", "---\nname: lider\n---\n" + secao)
        checar("lider_sem_fluxo_pr: com a seção, None", bp.lider_sem_fluxo_pr(proj, SEM_REVISOR) is None)
        checar("claude_md_sem_fluxo_pr: com a definição do líder, None", bp.claude_md_sem_fluxo_pr(proj, SEM_REVISOR) is None)
        sem_lider = Path(tmp) / "sem-lider"
        gravar(sem_lider, "README.md", "x\n")
        checar("claude_md_sem_fluxo_pr: sem lider.md e sem CLAUDE.md, aponta <projeto>/CLAUDE.md",
               bp.claude_md_sem_fluxo_pr(sem_lider, SEM_REVISOR) == sem_lider / "CLAUDE.md")
        cm = gravar(sem_lider, ".claude/CLAUDE.md", "# projeto\n")
        checar("claude_md_sem_fluxo_pr: usa o CLAUDE.md que existe", bp.claude_md_sem_fluxo_pr(sem_lider, SEM_REVISOR) == cm)
        gravar(sem_lider, ".claude/CLAUDE.md", "# projeto\n\n" + secao)
        checar("claude_md_sem_fluxo_pr: CLAUDE.md com a seção, None", bp.claude_md_sem_fluxo_pr(sem_lider, SEM_REVISOR) is None)


def instalar_cli(*args):
    r = subprocess.run([sys.executable, str(RAIZ / "instalar.py"), *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL, timeout=120,
                       env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    return r.returncode, r.stdout + r.stderr


def testar_revisao_cli():
    with pasta_temp() as tmp:
        t = Path(tmp)
        app, proj = t / "app", t / "proj"
        gravar(proj, "README.md", "x\n")
        gravar(proj, ".claude/agents/lider.md", "---\nname: lider\n---\nlíder antigo\n")
        cfg = gravar(app, "config.json", json.dumps(dict(SEM_REVISOR, porta=8770, projetos=[str(proj)])))
        antes_cfg = cfg.read_bytes()
        cod, out = instalar_cli("--revisao", str(proj), "--destino", str(app), "--sem-perguntas")
        dados = json.loads(cfg.read_text(encoding="utf-8"))
        baks = list(app.glob("config.json.bak-*"))
        checar("--revisao: sai com 0, mostra o diff e acrescenta o Revisor ao config", cod == 0
               and any(ln.strip().startswith("+") and '"nome": "Revisor"' in ln for ln in out.splitlines()) and [a["nome"] for a in dados["agentes"]] == ["Lider", "Dev", "Revisor"]
               and dados["porta"] == 8770, out[-1500:])
        checar("--revisao: backup do config.json com o conteúdo antigo",
               len(baks) == 1 and baks[0].read_bytes() == antes_cfg, baks)
        checar("--revisao: cria .claude/agents/revisor.md no projeto", (proj / ".claude/agents/revisor.md").is_file())
        checar("--revisao: líder sem a seção é avisado com o texto, sem mexer no arquivo", "## Fluxo de PR" in out
               and (proj / ".claude/agents/lider.md").read_text(encoding="utf-8").endswith("líder antigo\n"), out[-800:])
        depois = cfg.read_bytes()
        cod, out = instalar_cli("--revisao", str(proj), "--destino", str(app), "--sem-perguntas")
        checar("--revisao de novo: nada a fazer, sem backup novo", cod == 0 and "Nada a fazer" in out
               and cfg.read_bytes() == depois and len(list(app.glob("config.json.bak-*"))) == 1, out[-800:])
        proj2 = t / "proj2"
        meu = gravar(proj2, ".claude/agents/revisor.md", "MEU revisor\n")
        cod, out = instalar_cli("--revisao", str(proj2), "--destino", str(app), "--sem-perguntas")
        checar("--revisao com revisor.md do usuário: mantido", cod == 0 and meu.read_text(encoding="utf-8") == "MEU revisor\n"
               and "mantida" in out, out[-800:])
        checar("--revisao sem lider.md: avisa que a sessão principal é o líder e mostra a seção para o CLAUDE.md, sem criá-lo",
               "sessão principal faz o papel de líder" in out and "CLAUDE.md" in out and "## Fluxo de PR" in out
               and not (proj2 / "CLAUDE.md").exists(), out[-1200:])
        ruim = gravar(t / "app2", "config.json", "{ quebrado")
        cod, out = instalar_cli("--revisao", str(proj), "--destino", str(t / "app2"), "--sem-perguntas")
        checar("--revisao com config.json inválido: sai com 2 e não mexe", cod == 2
               and ruim.read_text(encoding="utf-8") == "{ quebrado" and not list(ruim.parent.glob("*.bak-*")), out)
        cod, out = instalar_cli("--revisao", str(t / "nao-existe"), "--destino", str(app), "--sem-perguntas")
        checar("--revisao com projeto inexistente: sai com 2", cod == 2 and "não encontrada" in out, out)


# ---------------------------------------------------------------- GET /api/praticas
def testar_rota():
    import http.client
    import rede
    import servidor
    import configuracao
    from functools import partial
    from http.server import ThreadingHTTPServer
    with pasta_temp() as tmp:
        t = Path(tmp)
        proj = t / "meu-proj"
        gravar(proj, "app.py", "")
        hook = {"hooks": {"PostToolUse": [{"hooks": [{"type": "command", "command": f'python "{proj.as_posix()}/scripts/outro.py"'}]}]}}
        gravar(proj, ".claude/settings.json", json.dumps(hook))
        config = configuracao.normalizar(dict(CONFIG, projetos=[str(proj), str(t / "sumiu")]))
        guardar = servidor.cfg, dict(servidor._praticas), servidor.Handler.rede, servidor.boas_praticas.validar
        srv, liberar = None, threading.Event()
        try:
            servidor.cfg = lambda: config
            servidor._praticas.update(quando=0.0, dados=None, thread=None)
            r = rede.Rede(t, False, False)
            r.arq_acoes = t / "acoes.jsonl"
            servidor.Handler.rede = r
            srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(servidor.Handler, directory=str(t)))
            porta = srv.server_address[1]
            threading.Thread(target=srv.serve_forever, daemon=True).start()

            def get(rota="/api/praticas"):
                con = http.client.HTTPConnection("127.0.0.1", porta, timeout=20)
                try:
                    con.request("GET", rota, headers={"Host": f"127.0.0.1:{porta}"})
                    resp = con.getresponse()
                    return resp.status, json.loads(resp.read() or b"{}")
                finally:
                    con.close()
            cod, d = get("/api/versao")
            versao = (RAIZ / "VERSION").read_text(encoding="utf-8").strip()
            checar("GET /api/versao: 200 com a versão do arquivo VERSION", cod == 200 and d == {"local": versao} and versao,
                   (cod, d))
            cod, d = get()
            checar("GET /api/praticas: 200 com os projetos", cod == 200 and d.get("ok") and not d["calculando"]
                   and d["validade"] == servidor.PRATICAS_VALIDADE and len(d["projetos"]) == 2, d)
            p = d["projetos"][0]
            checar("PC: projeto com caminho, nome, stacks e itens", p["projeto"] == str(proj) and p["nome"] == "meu-proj"
                   and p["stacks"] == ["python"] and any(i["id"] == "git" and not i["ok"] for i in p["itens"])
                   and not any("_correcao" in i for i in p["itens"]), p)
            checar("pasta que sumiu: erro no item, sem derrubar a rota", d["projetos"][1]["erro"] == "pasta não encontrada"
                   and d["projetos"][1]["itens"] == [])
            quando = d["quando"]
            cod, d2 = get()
            checar("cache: a 2ª chamada não recalcula", d2["quando"] == quando)
            hooks_pc = next(i for i in p["itens"] if i["id"] == "python-hooks-venv")["detalhe"]
            checar("PC: detalhe do hook com o caminho absoluto", proj.as_posix() in hooks_pc, hooks_pc)
            cel = servidor.praticas_get({"permissao": "ver", "nome": "celular"})[1]
            texto_cel = json.dumps(cel, ensure_ascii=False)
            hooks_cel = next(i for i in cel["projetos"][0]["itens"] if i["id"] == "python-hooks-venv")["detalhe"]
            checar("celular: sem o caminho absoluto do projeto nem caminhos no detalhe", all("projeto" not in x for x in cel["projetos"])
                   and cel["projetos"][0]["nome"] == "meu-proj" and t.as_posix() not in texto_cel
                   and json.dumps(str(t))[1:-1] not in texto_cel and t.name not in texto_cel and "…/outro.py" in hooks_cel,
                   (hooks_cel, texto_cel[:600]))
            checar("sem_caminhos: Windows, UNC e POSIX viram …/<nome>; URL, relativo e $CLAUDE_PROJECT_DIR ficam",
                   servidor.sem_caminhos(r"falhou em C:\obra\p\x.py e D:/o/grafo_hook.py") == "falhou em …/x.py e …/grafo_hook.py"
                   and servidor.sem_caminhos(r"\\srv\share\a.py; /srv/obra/b.py") == "…/a.py; …/b.py"
                   and servidor.sem_caminhos("https://x.com/a/b e/ou .venv/ $CLAUDE_PROJECT_DIR/.venv/bin/python")
                   == "https://x.com/a/b e/ou .venv/ $CLAUDE_PROJECT_DIR/.venv/bin/python")
            item_erro = {"projeto": "D:/x/p", "nome": "p", "erro": "pasta D:/x/p não encontrada", "itens": []}
            checar("celular: caminho no erro também some", servidor._praticas_celular(item_erro)["erro"] == "pasta …/p não encontrada")
            # validação lenta: não segura a resposta mais que ~3 s e devolve "calculando"
            servidor._praticas.update(quando=0.0, dados=None, thread=None)

            def lento(*a, **k):
                liberar.wait(20)
                return []
            servidor.boas_praticas.validar = lento
            t0 = time.time()
            cod, d = get()
            dt = time.time() - t0
            checar("validação lenta: responde em até ~3 s com calculando", cod == 200 and d["calculando"] and d["projetos"] == []
                   and dt < 6, (dt, d))
            th = servidor._praticas["thread"]
            cod, d = get()
            checar("enquanto calcula, não abre outra thread", servidor._praticas["thread"] is th and d["calculando"])
            liberar.set()
            th.join(20)
            cod, d = get()
            checar("terminada a validação, o resultado aparece", not d["calculando"] and d["projetos"][0]["itens"] == [], d)
        finally:
            liberar.set()
            if srv is not None:
                srv.shutdown()
                srv.server_close()
            servidor.cfg, servidor.Handler.rede, servidor.boas_praticas.validar = guardar[0], guardar[2], guardar[3]
            servidor._praticas.clear()
            servidor._praticas.update(guardar[1])


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    t = time.time()
    testar_deteccao()
    testar_sem_git()
    testar_com_git()
    testar_python()
    testar_outras_stacks()
    testar_corrigir()
    testar_venv_real()
    testar_venv_quebrado()
    testar_scripts_regra()
    testar_gitignore()
    testar_caminhos_venv()
    testar_cli()
    testar_revisao()
    testar_revisao_cli()
    testar_rota()
    if falhas:
        print(f"FALHOU: {len(falhas)} de {len(feitos) + len(falhas)} verificações")
        return 1
    print(f"OK: {len(feitos)} verificações em {time.time() - t:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
