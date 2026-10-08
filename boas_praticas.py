"""Boas práticas do projeto (somente biblioteca padrão): confere e corrige o básico de que o time de agentes precisa.

    python boas_praticas.py validar [PROJETO] [--json]
    python boas_praticas.py corrigir [PROJETO] [--aplicar] [--so id1,id2] [--instalar-deps]

Sem PROJETO, usa as pastas de "projetos" do config.json do escritório. `validar` sai com código 1 se alguma checagem de
nível "erro" falhar. `corrigir` sem --aplicar só mostra o plano; com --aplicar executa as correções seguras:
- cria o .venv do projeto (`python -m venv`; com --instalar-deps, `pip install -r requirements.txt`);
- acrescenta ao .gitignore as linhas que faltam (o conteúdo e as quebras de linha, inclusive CRLF, ficam como estão);
- grava .claude/rules/python-venv.md (modelo em modelos/praticas/);
- troca o `python` dos hooks do grafo no settings do PROJETO pelo Python do .venv (com backup do settings antes);
- cria .claude/agents/<nome>.md dos agentes do config.json que não têm definição (modelos em modelos/time/);
- sem ninguém revisando os PRs (agente revisor, revisor-ia, bots ou check de revisão), cria .claude/agents/revisor.md.
Nunca sobrescreve arquivo existente (exceto acrescentar ao .gitignore e mesclar o settings do projeto, com backup) e nunca
escreve no settings do usuário (~/.claude), que só é lido. Validar é rápido: sem rede, sem pip; git com tempo curto.

Usado também pelo instalar.py (passo "Projeto: boas práticas") e pelo servidor (GET /api/praticas, painel 🩺 Saúde).
"""
import argparse
import collections
import copy
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PASTA = Path(__file__).resolve().parent
sys.path.insert(0, str(PASTA))
import configuracao  # noqa: E402

WINDOWS = os.name == "nt"
NIVEIS = ("erro", "aviso", "dica")
MAX_PROFUNDIDADE = 3          # pastas abaixo da raiz que a detecção de tecnologias olha
MAX_ARQUIVOS = 4000           # teto de arquivos lidos na detecção (projeto enorme não trava o servidor)
TEMPO_GIT = 5
PASTAS_IGNORADAS = {".git", ".venv", "venv", "env", "node_modules", "Intermediate", "Binaries", "Saved", "DerivedDataCache",
                    "__pycache__", "dist", "build", "bin", "obj", "vendor", "target", "out", "coverage"}
MODELOS = PASTA / "modelos"
REGRA_VENV = Path(".claude") / "rules" / "python-venv.md"
GRAFOS = ["docs/ARCHITECTURE_GRAPH.yaml", "ARCHITECTURE_GRAPH.yaml", "docs/grafo.yaml", "grafo.yaml", ".grafo.yaml",
          "docs/architecture.yaml", "architecture.yaml", "grafo.json", ".grafo.json"]   # os mesmos do grafo_painel.py
# Python "solto" no começo do comando de um hook (python, python3, py -3, com ou sem .exe)
RE_PYTHON_NU = re.compile(r"^\s*(?:python3?|py(?:\s+-3)?)(?:\.exe)?\s+", re.I)
RE_PYTHON_TEXTO = re.compile(r"(?<![\w/.\\-])python3?(?:\.exe)?\s+[-\w\"'$.]", re.I)
HOOKS_ESCRITORIO = ("registrar_evento.py", "statusline_uso.py")
SECOES_STACK = {
    "python": "- Python: use sempre o Python do `.venv` do projeto (`.venv/Scripts/python` no Windows, `.venv/bin/python` no"
              " Linux/macOS), nunca o do sistema; pacote novo vai no `.venv` e no `requirements.txt` ou `pyproject.toml`.",
    "node": "- Node: instale pelo lockfile (`npm ci`, `pnpm install --frozen-lockfile`, `yarn install --frozen-lockfile`);"
            " `node_modules/` fica fora do git.",
    "unreal": "- Unreal: `Binaries/`, `Intermediate/`, `Saved/` e `DerivedDataCache/` ficam fora do git; compilar e abrir o"
              " editor só quando a tarefa pedir (é pesado).",
    "dotnet": "- .NET: `dotnet build` e `dotnet test` antes de entregar; `bin/` e `obj/` ficam fora do git.",
    "dados": "- Dados (SQL, KQL, notebooks): consulta nova roda primeiro com limite (TOP/take); nada de alterar dados de"
             " produção sem o líder confirmar; notebook vai para o commit sem saídas pesadas.",
    "web": "- Web: confira em tela pequena (celular) e grande; texto vindo de fora entra na página como texto, nunca como HTML.",
}
PAPEIS = {"lider": "lider", "dev": "dev", "design": "designer", "designer": "designer", "pesquisa": "pesquisa",
          "revisor": "revisor"}
# palavras (do nome do agente, separadas por - _ espaço ou ponto) que fazem dele um revisor: "previsao" e "preview" não
PALAVRAS_REVISOR = {"revisor", "revisora", "revisores", "revisao", "revisão", "revisoes", "revisões", "review", "reviews",
                    "reviewer", "reviewers", "codereview", "codereviewer"}


# ---------------------------------------------------------------- utilidades
def caminho_python_venv(pasta, windows=WINDOWS):
    """Executável do Python do .venv de uma pasta (Windows: .venv/Scripts/python.exe; senão .venv/bin/python)."""
    return Path(pasta) / ".venv" / ("Scripts/python.exe" if windows else "bin/python")


def python_venv_hook(windows=WINDOWS):
    """Python do .venv do projeto como o hook do Claude Code o chama (entre aspas, relativo a $CLAUDE_PROJECT_DIR)."""
    return '"$CLAUDE_PROJECT_DIR/.venv/' + ("Scripts/python.exe" if windows else "bin/python") + '"'


def venv_ok(pasta):
    venv = Path(pasta) / ".venv"
    return (venv / "pyvenv.cfg").is_file() and caminho_python_venv(pasta).is_file()


def _rodar(cmd, timeout=TEMPO_GIT, cwd=None):
    """(código, saída) de um comando; (None, '') se não existir ou passar do tempo."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, cwd=cwd)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except (OSError, subprocess.SubprocessError):
        return None, ""


def _git(projeto, *args):
    return _rodar(["git", "-C", str(projeto), *args])


def _ler(arq, limite=200_000):
    try:
        with open(arq, encoding="utf-8", errors="replace") as f:
            return f.read(limite)
    except OSError:
        return ""


def _ler_json(arq):
    """(dados, erro). Arquivo ausente = ({}, '')."""
    if not arq.is_file():
        return {}, ""
    try:
        dados = json.loads(arq.read_text(encoding="utf-8-sig") or "{}")
    except (OSError, ValueError) as e:
        return {}, f"{arq.name} inválido: {e}"
    return (dados, "") if isinstance(dados, dict) else ({}, f"{arq.name} não é um objeto JSON")


def _limpar(texto, limite=300, markdown=True):
    """Texto de arquivo do projeto pronto para mostrar: sem markdown comum, sem caracteres de controle, curto.
    markdown=False (comandos, saída de programa): mantém o texto como está ("grafo_hook.py" não vira "grafohook.py")."""
    t = texto
    if markdown:
        t = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", t)
        t = re.sub(r"[*_`]+", "", t)
    t = "".join(c if c.isprintable() else " " for c in t)
    t = re.sub(r"\s+", " ", t).strip()
    return t if len(t) <= limite else t[:limite - 1].rstrip() + "…"


def backup(arq):
    """Cópia <nome>.bak-AAAAMMDD-HHMMSS[-n] ao lado do arquivo (mesmo formato do instalar.py)."""
    arq = Path(arq)
    if not arq.exists():
        return None
    destino = arq.with_name(f"{arq.name}.bak-{datetime.now():%Y%m%d-%H%M%S}")
    n = 1
    while destino.exists():
        destino = arq.with_name(f"{arq.name}.bak-{datetime.now():%Y%m%d-%H%M%S}-{n}")
        n += 1
    shutil.copy2(arq, destino)
    return destino


# ---------------------------------------------------------------- escopo do projeto
def _varrer(projeto):
    """Caminhos relativos dos arquivos até MAX_PROFUNDIDADE (no máximo MAX_ARQUIVOS); pula pastas pesadas e ocultas."""
    achados, fila = [], collections.deque([(projeto, 0)])
    while fila and len(achados) < MAX_ARQUIVOS:
        pasta, nivel = fila.popleft()
        try:
            with os.scandir(pasta) as it:
                entradas = sorted(it, key=lambda e: e.name)
        except OSError:
            continue
        for e in entradas:
            try:
                if e.is_dir(follow_symlinks=False):
                    if nivel < MAX_PROFUNDIDADE and e.name not in PASTAS_IGNORADAS and not e.name.startswith("."):
                        fila.append((Path(e.path), nivel + 1))
                elif e.is_file(follow_symlinks=False):
                    achados.append(Path(e.path).relative_to(projeto).as_posix())
            except (OSError, ValueError):
                continue
            if len(achados) >= MAX_ARQUIVOS:
                break
    return achados


def _comando_testes(projeto, stacks, arquivos):
    nomes = set(arquivos)
    if "python" in stacks:
        py = ".venv/Scripts/python" if WINDOWS else ".venv/bin/python"
        if ({"pytest.ini", "conftest.py", "tests/conftest.py"} & nomes
                or "[tool.pytest" in _ler(projeto / "pyproject.toml")
                or "[tool:pytest]" in _ler(projeto / "setup.cfg") or "[pytest]" in _ler(projeto / "tox.ini")):
            return f"{py} -m pytest"
        for pasta in ("tests", "test"):
            if any(re.fullmatch(rf"{pasta}/test_[^/]*\.py", a) for a in arquivos):
                return f"{py} -m unittest discover -s {pasta}"
        if any(re.fullmatch(r"test_[^/]*\.py", a) for a in arquivos):
            return f"{py} -m unittest discover"
    if "node" in stacks:
        dados, _ = _ler_json(projeto / "package.json")
        teste = str((dados.get("scripts") or {}).get("test") or "") if isinstance(dados.get("scripts"), dict) else ""
        if teste and "no test specified" not in teste:
            return "npm test"
    if "dotnet" in stacks:
        return "dotnet test"
    return ""


def _descricao(projeto):
    """1º parágrafo de texto do README (ou do CLAUDE.md), sem títulos, selos, HTML nem blocos de código."""
    for nome in ("README.md", "README.rst", "README.txt", "README", "CLAUDE.md", ".claude/CLAUDE.md"):
        texto = _ler(projeto / nome, 40_000)
        if not texto:
            continue
        paragrafo, em_codigo, cabecalho = [], False, texto.startswith("---")
        for i, linha in enumerate(texto.splitlines()):
            s = linha.strip()
            if cabecalho:                       # front matter YAML no topo
                cabecalho = not (i > 0 and s == "---")
                continue
            if s.startswith(("```", "~~~")):
                em_codigo = not em_codigo
                if paragrafo:
                    break
                continue
            if em_codigo:
                continue
            if not s or s.startswith(("#", "<", "![", "[![", "|", "---", "===", "***", "..")) or set(s) <= set("=-~^*#"):
                if paragrafo:
                    break
                continue
            paragrafo.append(s)
        if paragrafo:
            return _limpar(" ".join(paragrafo))
    return ""


def _escopo(projeto):
    projeto = Path(projeto)
    arquivos = _varrer(projeto)
    stacks, pastas = set(), {}
    for a in arquivos:
        nome, ext = a.rsplit("/", 1)[-1], Path(a).suffix.lower()
        pasta = a.rsplit("/", 1)[0] if "/" in a else ""
        if (nome in ("pyproject.toml", "setup.py", "setup.cfg", "Pipfile") or ext == ".py"
                or re.fullmatch(r"requirements[\w.-]*\.txt", nome)):
            stacks.add("python")
        elif nome == "package.json":
            stacks.add("node")
        elif ext in (".uproject", ".uplugin"):
            stacks.add("unreal")
            pastas.setdefault("unreal", pasta)
        elif ext in (".csproj", ".fsproj", ".vbproj", ".sln"):
            stacks.add("dotnet")
            pastas.setdefault("dotnet", pasta)
        elif ext in (".sql", ".kql", ".ipynb"):
            stacks.add("dados")
        elif ext in (".html", ".htm", ".css", ".tsx", ".jsx", ".vue", ".svelte"):
            stacks.add("web")
    return {"stacks": stacks, "testes": _comando_testes(projeto, stacks, arquivos), "descricao": _descricao(projeto),
            "_pastas": pastas}


def detectar_escopo(projeto):
    """{"stacks": {"python", "node", "unreal", "dotnet", "dados", "web"}, "testes": comando sugerido ou "",
    "descricao": 1º parágrafo do README/CLAUDE.md}. Barato: só nomes de arquivo, com limite de profundidade e de arquivos."""
    return {k: v for k, v in _escopo(projeto).items() if not k.startswith("_")}


# ---------------------------------------------------------------- .gitignore
def _padroes_gitignore(projeto):
    padroes = []
    for linha in _ler(Path(projeto) / ".gitignore").splitlines():
        s = linha.strip()
        if not s or s.startswith("#"):
            continue
        neg = s.startswith("!")
        s = s[1:] if neg else s
        so_dir = s.endswith("/")
        s = s.rstrip("/")
        ancorado = s.startswith("/") or "/" in s
        padroes.append((neg, s.lstrip("/"), so_dir, ancorado))
    return padroes


def _casa_gitignore(padroes, caminho):
    """Leitura simplificada do .gitignore da raiz (para pasta sem git): o último padrão que casa decide."""
    partes = caminho.rstrip("/").split("/")
    ignorado = False
    for neg, pad, so_dir, ancorado in padroes:
        for i in range(len(partes)):
            eh_pasta = i < len(partes) - 1 or caminho.endswith("/")
            if so_dir and not eh_pasta:
                continue
            alvo = "/".join(partes[:i + 1]) if ancorado else partes[i]
            if fnmatch.fnmatchcase(alvo, pad):
                ignorado = not neg
                break
    return ignorado


def ignorados(projeto, caminhos, eh_repo):
    """Quais destes caminhos (relativos; pasta termina em /) o .gitignore ignora. Usa o git quando há repositório, só com
    as regras do projeto (.gitignore e .git/info/exclude): o ignore global do usuário (core.excludesFile) não conta, já
    que o colega que clona o projeto não o tem."""
    caminhos = list(caminhos)
    if eh_repo:
        cod, out = _git(projeto, "-c", "core.excludesFile=", "check-ignore", "--no-index", "--", *caminhos)
        if cod in (0, 1):
            saida = {linha.strip() for linha in out.splitlines()}
            return {c for c in caminhos if c in saida}
    padroes = _padroes_gitignore(projeto)
    return {c for c in caminhos if _casa_gitignore(padroes, c)}


def acrescentar_gitignore(projeto, linhas):
    """Acrescenta ao .gitignore só as linhas que faltam (idempotente), mantendo o conteúdo e a quebra de linha (CRLF ou LF).
    Cria o arquivo se não existir. Devolve as linhas acrescentadas."""
    arq = Path(projeto) / ".gitignore"
    bruto = arq.read_bytes() if arq.exists() else b""
    texto = bruto.decode("utf-8", errors="replace")
    existentes = {s.strip() for s in texto.splitlines()}
    faltam = []
    for linha in linhas:
        if linha not in existentes and linha not in faltam:
            faltam.append(linha)
    if not faltam:
        return []
    nl = "\r\n" if b"\r\n" in bruto else "\n"
    extra = (nl if bruto and not bruto.endswith(b"\n") else "") + (nl if bruto.strip() else "")
    extra += "# boas práticas (Claude Office 3D)" + nl + nl.join(faltam) + nl
    with open(arq, "ab") as f:
        f.write(extra.encode("utf-8"))
    return faltam


# ---------------------------------------------------------------- agentes
def _nome_arquivo_agente(nome):
    return re.sub(r"[^\w.-]+", "-", str(nome).strip().lower()).strip("-.") or "agente"


def _agentes_existentes(projeto):
    """Chaves (configuracao.chave) dos agentes definidos em .claude/agents/*.md: nome do arquivo e campo name."""
    chaves = set()
    for md in (Path(projeto) / ".claude" / "agents").glob("*.md"):
        chaves.add(configuracao.chave(md.stem))
        m = re.search(r"^name:\s*['\"]?([^'\"\n]+)", _ler(md, 4000), re.M)
        if m:
            chaves.add(configuracao.chave(m.group(1)))
    return chaves


def _nome_de_revisor(nome):
    """O nome (ou a chave) tem uma palavra de revisor (revisor, reviewer, code-reviewer, revisao...)? Casa por palavra."""
    return any(p in PALAVRAS_REVISOR for p in re.split(r"[\W_]+", str(nome or "").lower()))


def _eh_lider(ag):
    return bool(ag.get("lider")) or configuracao.chave(ag.get("nome")) in ("lider", "líder")


def _papel(ag):
    k = configuracao.chave(ag.get("nome"))
    if _eh_lider(ag):
        return "lider"
    if _nome_de_revisor(k):
        return "revisor"
    for chave_papel, papel in PAPEIS.items():
        if papel != "revisor" and chave_papel in k:
            return papel
    return PAPEIS.get(ag.get("mesa") or "", "agente")


def texto_agente(ag, projeto, escopo):
    """Definição .claude/agents/<nome>.md a partir de modelos/time/<papel>.md, com o nome, a descrição e os testes do projeto."""
    modelo = MODELOS / "time" / f"{_papel(ag)}.md"
    if not modelo.is_file():
        modelo = MODELOS / "time" / "agente.md"
    texto = modelo.read_text(encoding="utf-8")
    funcao = _limpar(ag.get("funcao") or ag.get("titulo") or ag.get("nome") or "", 200) or "Colega do time"
    secoes = [SECOES_STACK[s] for s in sorted(escopo["stacks"]) if s in SECOES_STACK]
    trocas = {
        "{{nome}}": _nome_arquivo_agente(ag.get("nome")),
        "{{descricao_agente}}": json.dumps(funcao, ensure_ascii=False),
        "{{funcao}}": funcao,
        "{{projeto}}": Path(projeto).name,
        "{{descricao}}": escopo["descricao"] or "(sem descrição: escreva aqui em 2 ou 3 linhas o que o produto faz e para quem)",
        "{{stacks}}": ", ".join(sorted(escopo["stacks"])) or "nenhuma detectada",
        "{{testes}}": escopo["testes"] or "defina o comando de teste do projeto",
        "{{secoes_stack}}": "\n".join(secoes),
    }
    for k, v in trocas.items():
        texto = texto.replace(k, v)
    return re.sub(r"\n{3,}", "\n\n", texto)


# ---------------------------------------------------------------- revisão de PR (líder + revisor)
AGENTE_REVISOR = {"nome": "Revisor", "titulo": "Revisor", "funcao": "Revisa cada PR antes do merge (P0/P1/P2)",
                  "cor": "#14b8a6", "apelido_br": "Rita", "apelido_cinema": "Sherlock", "mesa": "padrao",
                  "outros_nomes": ["reviewer", "code-reviewer", "revisora"]}


def eh_revisor(ag):
    return _papel(ag if isinstance(ag, dict) else {"nome": str(ag)}) == "revisor"


def _revisor_definido(projeto):
    """Já há uma definição de revisor em .claude/agents/ (nome do arquivo ou campo name com palavra de revisor)?"""
    return any(_nome_de_revisor(k) for k in _agentes_existentes(projeto))


def revisao_configurada(cfg, projeto=None):
    """Quem revisa os PRs (config normalizado): lista de motivos; vazia = ninguém."""
    motivos = []
    if any(eh_revisor(a) for a in cfg.get("agentes") or []) or (projeto and _revisor_definido(projeto)):
        motivos.append("agente revisor")
    if (cfg.get("revisor") or {}).get("ativo"):
        motivos.append("revisor-ia")
    gh = cfg.get("github") or {}
    if gh.get("bots_revisao"):
        motivos.append("bots de revisão")
    if gh.get("check_revisao"):
        motivos.append(f"check {gh['check_revisao']}")
    return motivos


def com_revisor(config):
    """Cópia do config BRUTO (como no arquivo) com o agente revisor no time, se ainda não há um.
    Sem "agentes", parte do time padrão (senão o time viraria só o revisor). Devolve (config, acrescentou)."""
    cfg = copy.deepcopy(config) if isinstance(config, dict) else {}
    agentes = cfg.get("agentes") if isinstance(cfg.get("agentes"), list) and cfg.get("agentes") \
        else copy.deepcopy(configuracao.AGENTES_PADRAO)
    if any(eh_revisor(a) for a in agentes):
        return cfg, False
    nomes = {configuracao.chave(a.get("nome") if isinstance(a, dict) else a) for a in agentes}
    novo = copy.deepcopy(AGENTE_REVISOR)
    if configuracao.chave(novo["nome"]) in nomes:   # improvável (o nome já seria revisor), mas nunca duplica
        novo["nome"] = "Revisor_PR"
    cfg["agentes"] = agentes + [novo]
    return cfg, True


def caminho_revisor(projeto, config=None):
    """.claude/agents/<revisor>.md que criar_revisor gravaria, ou None se o projeto já tem uma definição de revisor."""
    if _revisor_definido(projeto):
        return None
    cfg = _carregar_config(config)
    ag = next((a for a in cfg["agentes"] if eh_revisor(a)), AGENTE_REVISOR)
    destino = Path(projeto) / ".claude" / "agents" / f"{_nome_arquivo_agente(ag['nome'])}.md"
    return None if destino.exists() else destino


def criar_revisor(projeto, config=None):
    """Grava a definição do revisor pelo modelo modelos/time/revisor.md (nunca sobrescreve). Devolve o caminho criado
    ou None (já havia)."""
    destino = caminho_revisor(projeto, config)
    if destino is None:
        return None
    cfg = _carregar_config(config)
    ag = next((a for a in cfg["agentes"] if eh_revisor(a)), AGENTE_REVISOR)
    destino.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(destino, "x", encoding="utf-8", newline="\n") as f:   # "x": nunca sobrescreve
            f.write(texto_agente(ag, projeto, _escopo(Path(projeto))))
    except FileExistsError:
        return None
    return destino


def secao_fluxo_pr():
    """Texto da seção "Fluxo de PR" do modelo do líder (para quem já tem a definição do líder sem ela)."""
    texto = (MODELOS / "time" / "lider.md").read_text(encoding="utf-8")
    m = re.search(r"^## Fluxo de PR\n.*?(?=^## |\Z)", texto, re.M | re.S)
    return m.group(0).rstrip() + "\n" if m else ""


def _definicoes_lider(projeto, cfg):
    """.claude/agents/*.md do líder (nome do arquivo lider/líder ou o nome do líder do config)."""
    lider = configuracao.lider(cfg)
    chaves = {"lider", "líder"} | ({configuracao.chave(lider["nome"])} if lider else set())
    return [md for md in sorted((Path(projeto) / ".claude" / "agents").glob("*.md")) if configuracao.chave(md.stem) in chaves]


def lider_sem_fluxo_pr(projeto, config=None):
    """Definição do líder em .claude/agents/ que ainda não tem a seção "Fluxo de PR" (ou None)."""
    cfg = _carregar_config(config)
    return next((md for md in _definicoes_lider(projeto, cfg) if "Fluxo de PR" not in _ler(md)), None)


def claude_md_sem_fluxo_pr(projeto, config=None):
    """Projeto sem a definição do líder (a sessão principal faz o papel de líder) e cujo CLAUDE.md não tem a seção
    "Fluxo de PR": devolve o CLAUDE.md onde colar a seção (o que existe, ou <projeto>/CLAUDE.md). Senão None."""
    cfg = _carregar_config(config)
    if _definicoes_lider(projeto, cfg):
        return None
    candidatos = [Path(projeto) / "CLAUDE.md", Path(projeto) / ".claude" / "CLAUDE.md"]
    existentes = [c for c in candidatos if c.is_file()]
    if any("Fluxo de PR" in _ler(c) for c in existentes):
        return None
    return existentes[0] if existentes else candidatos[0]


# ---------------------------------------------------------------- hooks do projeto
def _settings_projeto(projeto):
    return [Path(projeto) / ".claude" / "settings.json", Path(projeto) / ".claude" / "settings.local.json"]


def _comandos_hooks(dados):
    """(evento, hook) de cada hook de comando de um settings."""
    hooks = dados.get("hooks") if isinstance(dados, dict) else None
    for ev, grupos in (hooks.items() if isinstance(hooks, dict) else []):
        for g in grupos if isinstance(grupos, list) else []:
            for h in (g.get("hooks") if isinstance(g, dict) else None) or []:
                if isinstance(h, dict) and isinstance(h.get("command"), str):
                    yield ev, h


def _eh_do_escritorio(cmd):
    return any(m in cmd.replace("\\", "/") for m in HOOKS_ESCRITORIO)


def hooks_python_nu(dados):
    """Hooks do projeto (não os do escritório) que chamam o python do sistema."""
    return [h for _, h in _comandos_hooks(dados) if RE_PYTHON_NU.match(h["command"]) and not _eh_do_escritorio(h["command"])]


def trocar_python_hooks_grafo(dados, windows=WINDOWS):
    """Cópia do settings com o python solto dos hooks do grafo trocado pelo Python do .venv. Devolve (dados, n_trocados)."""
    dados = copy.deepcopy(dados)
    n = 0
    for h in hooks_python_nu(dados):
        if "grafo_hook.py" in h["command"]:
            h["command"] = RE_PYTHON_NU.sub(lambda _m: python_venv_hook(windows) + " ", h["command"], count=1)
            n += 1
    return dados, n


# ---------------------------------------------------------------- validação
def _item(id_, titulo, nivel, ok, detalhe="", corrigivel=False, como_corrigir="", correcao=None):
    return {"id": id_, "titulo": titulo, "nivel": nivel, "ok": bool(ok), "detalhe": detalhe,
            "corrigivel": bool(corrigivel and not ok), "como_corrigir": "" if ok else como_corrigir,
            "_correcao": None if ok else correcao}


def _carregar_config(config):
    return configuracao.carregar() if config is None else configuracao.normalizar(config)


def _checagens(projeto, config=None, settings_usuario=None):
    projeto = Path(projeto)
    cfg = _carregar_config(config)
    escopo = _escopo(projeto)
    stacks = escopo["stacks"]
    itens = []
    cod, out = _git(projeto, "rev-parse", "--is-inside-work-tree")
    eh_repo = cod == 0 and out.strip() == "true"
    itens.append(_item("git", "Repositório git", "erro", eh_repo,
                       "" if eh_repo else "a pasta não está num repositório git (sem histórico nem PR)",
                       como_corrigir="git init (e o primeiro commit)"))

    tem_gitignore = (projeto / ".gitignore").is_file()
    itens.append(_item("gitignore", ".gitignore existe", "aviso", tem_gitignore, "" if tem_gitignore else "falta o .gitignore",
                       True, "criar o .gitignore com as linhas das outras checagens", {"gitignore": []}))

    # o que precisa ficar fora do git: (id, título, nível, {caminho de teste: linha do .gitignore})
    fora = [("segredos-ignorados", "Segredos fora do git (.env, *.pem, *.key)", "erro",
             {".env": ".env", "chave.pem": "*.pem", "chave.key": "*.key"}),
            ("settings-local-ignorado", ".claude/settings.local.json fora do git", "aviso",
             {".claude/settings.local.json": ".claude/settings.local.json"})]
    if "python" in stacks:
        fora.append(("python-venv-ignorado", ".venv/ fora do git", "aviso", {".venv/": ".venv/"}))
    if "node" in stacks:
        fora.append(("node-modules-ignorado", "node_modules/ fora do git", "aviso", {"node_modules/": "node_modules/"}))
    if "unreal" in stacks:
        base = escopo["_pastas"].get("unreal", "")
        fora.append(("unreal-ignorados", "Pastas geradas do Unreal fora do git", "aviso",
                     {f"{base}/{p}/".lstrip("/"): f"{p}/" for p in ("Binaries", "Intermediate", "Saved", "DerivedDataCache")}))
    if "dotnet" in stacks:
        base = escopo["_pastas"].get("dotnet", "")
        fora.append(("dotnet-ignorados", "bin/ e obj/ do .NET fora do git", "aviso",
                     {f"{base}/{p}/".lstrip("/"): f"{p}/" for p in ("bin", "obj")}))
    todos = [c for *_, mapa in fora for c in mapa]
    ja = ignorados(projeto, todos, eh_repo)
    for id_, titulo, nivel, mapa in fora:
        faltam = [linha for c, linha in mapa.items() if c not in ja]
        itens.append(_item(id_, titulo, nivel, not faltam, ("o .gitignore não cobre: " + ", ".join(faltam)) if faltam else "",
                           True, "acrescentar ao .gitignore: " + ", ".join(faltam), {"gitignore": faltam}))

    env_versionados = []
    if eh_repo:
        cod, out = _git(projeto, "ls-files", "-z")
        for nome in (out.split("\0") if cod == 0 else []):
            base = nome.rsplit("/", 1)[-1]
            if base == ".env" or (base.startswith(".env.") and not base.endswith((".example", ".sample", ".template"))):
                env_versionados.append(nome)
    itens.append(_item("env-versionado", ".env não versionado", "erro", not env_versionados,
                       ("versionado no git: " + ", ".join(env_versionados[:5])) if env_versionados else "",
                       como_corrigir="git rm --cached <arquivo> (o arquivo fica na pasta) e troque as chaves que estavam nele"))

    tem_claude_md = (projeto / "CLAUDE.md").is_file() or (projeto / ".claude" / "CLAUDE.md").is_file()
    itens.append(_item("claude-md", "CLAUDE.md do projeto", "aviso", tem_claude_md,
                       "" if tem_claude_md else "sem CLAUDE.md, cada sessão começa sem saber do projeto",
                       como_corrigir="rode /init no Claude Code e deixe o arquivo curto (menos de 200 linhas)"))

    existentes = _agentes_existentes(projeto)
    for ag in cfg.get("agentes") or []:
        chaves = {configuracao.chave(ag["nome"])} | {configuracao.chave(o) for o in ag.get("outros_nomes") or []}
        tem = bool(chaves & existentes)
        arq = f".claude/agents/{_nome_arquivo_agente(ag['nome'])}.md"
        lider = _eh_lider(ag)
        itens.append(_item(f"agente-{_nome_arquivo_agente(ag['nome'])}", f"Definição do agente {ag['nome']}",
                           "aviso" if lider else "erro", tem,
                           "" if tem else f"falta {arq}" + (" (opcional para o líder, que é a sessão principal)" if lider else ""),
                           True, f"criar {arq} a partir de modelos/time/{_papel(ag)}.md", {"agente": ag}))

    motivos = revisao_configurada(cfg, projeto)
    itens.append(_item("revisao-pr", "Revisão de PR configurada", "aviso", bool(motivos), ", ".join(motivos) if motivos
                       else "ninguém revisa os PRs (sem agente revisor, revisor-ia, bots ou check de revisão)",
                       True, "criar .claude/agents/revisor.md (modelo modelos/time/revisor.md); para pôr o Revisor no "
                       "time do escritório: python instalar.py --revisao <projeto>", {"revisor": True}))

    achou_hook = False
    for arq in _settings_projeto(projeto) + [Path(settings_usuario) if settings_usuario
                                             else Path.home() / ".claude" / "settings.json"]:
        dados, _ = _ler_json(arq)   # o do usuário só é lido
        if any("registrar_evento.py" in h["command"] for _, h in _comandos_hooks(dados)):
            achou_hook = True
            break
    itens.append(_item("hook-escritorio", "Hook do escritório instalado", "aviso", achou_hook,
                       "" if achou_hook else "sem o hook, o escritório não vê os agentes deste projeto",
                       como_corrigir="python instalar.py (passo do hook) na pasta do escritório"))

    itens.append(_item("testes", "Comando de teste conhecido", "aviso", bool(escopo["testes"]),
                       escopo["testes"] or "não achei pytest, unittest (tests/test_*.py), npm test nem dotnet test",
                       como_corrigir="crie os testes (ex.: tests/test_*.py) e cite o comando no CLAUDE.md"))

    tem_grafo = any((projeto / g).is_file() for g in GRAFOS)
    itens.append(_item("grafo", "Grafo de arquitetura", "dica", tem_grafo,
                       "" if tem_grafo else "os agentes não têm o mapa de dependências do projeto",
                       como_corrigir="python grafo/claude/instalar_grafo.py <projeto> (veja grafo/LEIAME.md)"))

    wf = projeto / ".github" / "workflows"
    tem_ci = (wf.is_dir() and any(wf.glob("*.y*ml"))) or any((projeto / n).is_file()
                                                              for n in (".gitlab-ci.yml", "azure-pipelines.yml"))
    itens.append(_item("ci", "Integração contínua (CI)", "dica", tem_ci, "" if tem_ci else "nada roda os testes a cada PR",
                       como_corrigir="crie .github/workflows/ci.yml que rode o comando de teste"))

    if "python" in stacks:
        ok = venv_ok(projeto)
        itens.append(_item("python-venv", ".venv do projeto", "aviso", ok,
                           "" if ok else ("o .venv está incompleto (sem pyvenv.cfg ou sem o python)" if (projeto / ".venv").exists()
                                          else "sem .venv, os agentes rodam com o Python do sistema"),
                           not (projeto / ".venv").exists(), "python -m venv .venv", {"venv": True}))
        deps = [n for n in ("pyproject.toml", "setup.py", "setup.cfg", "Pipfile") if (projeto / n).is_file()] + \
            sorted(p.name for p in projeto.glob("requirements*.txt"))
        itens.append(_item("python-dependencias", "Dependências declaradas", "aviso", bool(deps), ", ".join(deps)
                           or "sem requirements.txt nem pyproject.toml", como_corrigir="liste os pacotes em requirements.txt"))
        tem_regra = (projeto / REGRA_VENV).is_file()
        itens.append(_item("python-regra-venv", "Regra .claude/rules/python-venv.md", "aviso", tem_regra,
                           "" if tem_regra else "nada diz aos agentes para usar o .venv",
                           True, "gravar .claude/rules/python-venv.md (modelo do escritório)", {"regra": True}))
        nus, grafo_nus, erros = [], 0, []
        for arq in _settings_projeto(projeto):
            dados, erro = _ler_json(arq)
            if erro:
                erros.append(erro)
            for h in hooks_python_nu(dados):
                nus.append(f"{arq.name}: {_limpar(h['command'], 90, markdown=False)}")
                grafo_nus += "grafo_hook.py" in h["command"]
        itens.append(_item("python-hooks-venv", "Hooks do projeto com o Python do .venv", "aviso", not nus and not erros,
                           "; ".join(erros + nus[:3]), grafo_nus > 0,
                           ("trocar o python dos hooks do grafo por " + python_venv_hook() + " (com backup)")
                           if grafo_nus else "use " + python_venv_hook() + " no comando dos hooks do projeto",
                           {"hooks": True} if grafo_nus else None))
        sem_venv = []
        for md in sorted((projeto / ".claude" / "agents").glob("*.md")):
            texto = _ler(md)
            if RE_PYTHON_TEXTO.search(texto) and ".venv" not in texto:
                sem_venv.append(md.name)
        itens.append(_item("python-agentes-venv", "Agentes citam o .venv", "aviso", not sem_venv,
                           ("rodam python sem citar o .venv: " + ", ".join(sem_venv[:5])) if sem_venv else "",
                           como_corrigir="nas definições, troque `python ...` pelo Python do .venv (veja a regra python-venv.md)"))

    if "node" in stacks:
        locks = [n for n in ("package-lock.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb", "bun.lock")
                 if (projeto / n).is_file()]
        itens.append(_item("node-lockfile", "Lockfile do Node versionado", "aviso", bool(locks), ", ".join(locks)
                           or "sem lockfile, cada máquina instala versões diferentes",
                           como_corrigir="npm install (gera o package-lock.json) e versione o arquivo"))
    return itens, escopo


def validar(projeto, config=None, settings_usuario=None):
    """Checagens do projeto: lista de {id, titulo, nivel: erro|aviso|dica, ok, detalhe, corrigivel, como_corrigir}.
    config: config do escritório (agentes); None = config.json. settings_usuario: só lido (padrão ~/.claude/settings.json)."""
    itens, _ = _checagens(projeto, config, settings_usuario)
    return [{k: v for k, v in i.items() if not k.startswith("_")} for i in itens]


def tem_erro(itens):
    return any(i["nivel"] == "erro" and not i["ok"] for i in itens)


# ---------------------------------------------------------------- correção
def corrigir(projeto, ids=None, aplicar=False, instalar_deps=False, config=None, settings_usuario=None):
    """Plano das correções seguras (ids = só estas checagens). Com aplicar=True, executa.
    Devolve [{id, acao, aplicada, erro}]; sem aplicar, aplicada é sempre False."""
    projeto = Path(projeto)
    itens, escopo = _checagens(projeto, config, settings_usuario)
    pendentes = [i for i in itens if i["corrigivel"] and i["_correcao"] is not None and (not ids or i["id"] in ids)]
    acoes = []

    def fazer(id_, acao, funcao):
        r = {"id": id_, "acao": acao, "aplicada": False, "erro": ""}
        if aplicar:
            try:
                erro = funcao()
                r["aplicada"], r["erro"] = not erro, erro or ""
            except (OSError, ValueError, subprocess.SubprocessError) as e:
                r["erro"] = str(e)
        acoes.append(r)
        return r

    vai_venv = any("venv" in i["_correcao"] for i in pendentes)
    if vai_venv:
        def criar_venv():
            cod, out = _rodar([sys.executable, "-m", "venv", str(projeto / ".venv")], timeout=300)
            if cod != 0 or not venv_ok(projeto):
                return "python -m venv falhou: " + _limpar(out, 200, markdown=False)
            req = projeto / "requirements.txt"
            if instalar_deps and req.is_file():
                cod, out = _rodar([str(caminho_python_venv(projeto)), "-m", "pip", "install", "-r", str(req)],
                                  timeout=900, cwd=str(projeto))
                if cod != 0:
                    return ".venv criado, mas o pip install falhou: " + _limpar(out[-400:], 200, markdown=False)
            return ""
        fazer("python-venv", "criar .venv (python -m venv .venv)"
              + (" e instalar requirements.txt" if instalar_deps and (projeto / "requirements.txt").is_file() else ""),
              criar_venv)

    linhas, ids_gi = [], []
    for i in pendentes:
        if "gitignore" in i["_correcao"]:
            ids_gi.append(i["id"])
            linhas += [linha for linha in i["_correcao"]["gitignore"] if linha not in linhas]
    if ids_gi:
        def gi():
            acrescentar_gitignore(projeto, linhas)
        fazer(",".join(ids_gi), (".gitignore: acrescentar " + ", ".join(linhas)) if linhas else "criar o .gitignore", gi)

    if any("regra" in i["_correcao"] for i in pendentes):
        def regra():
            destino = projeto / REGRA_VENV
            if destino.exists():
                return ""
            destino.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(MODELOS / "praticas" / "python-venv.md", destino)
        fazer("python-regra-venv", f"gravar {REGRA_VENV.as_posix()}", regra)

    for i in pendentes:
        if "agente" in i["_correcao"]:
            ag = i["_correcao"]["agente"]
            destino = projeto / ".claude" / "agents" / f"{_nome_arquivo_agente(ag['nome'])}.md"

            def agente(ag=ag, destino=destino):
                if destino.exists():
                    return ""
                destino.parent.mkdir(parents=True, exist_ok=True)
                with open(destino, "x", encoding="utf-8", newline="\n") as f:   # "x": nunca sobrescreve
                    f.write(texto_agente(ag, projeto, escopo))
            fazer(i["id"], f"criar .claude/agents/{destino.name} (modelo {_papel(ag)})", agente)

    if any("revisor" in i["_correcao"] for i in pendentes):
        def revisor():
            criar_revisor(projeto, config)
        alvo = caminho_revisor(projeto, config)
        fazer("revisao-pr", f"criar .claude/agents/{alvo.name if alvo else 'revisor.md'} (modelo revisor)", revisor)

    if any("hooks" in i["_correcao"] for i in pendentes):
        def hooks():
            if not venv_ok(projeto):
                return "o .venv não existe: crie antes (checagem python-venv) para os hooks não quebrarem"
            for arq in _settings_projeto(projeto):
                dados, erro = _ler_json(arq)
                if erro:
                    return erro
                novo, n = trocar_python_hooks_grafo(dados)
                if n:
                    backup(arq)
                    arq.write_text(json.dumps(novo, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return ""
        fazer("python-hooks-venv", "hooks do grafo no settings do projeto: python → " + python_venv_hook() + " (com backup)",
              hooks)
    return acoes


# ---------------------------------------------------------------- relatório e linha de comando
ROTULO = {"erro": "ERRO ", "aviso": "aviso", "dica": "dica "}


def relatorio(projeto, itens, escopo=None, todos=False):
    """Linhas de texto do resultado de validar (para o terminal e o instalador)."""
    linhas = [f"Projeto: {projeto}"]
    if escopo:
        linhas.append(f"  tecnologias: {', '.join(sorted(escopo['stacks'])) or 'nenhuma detectada'}"
                      f"   testes: {escopo['testes'] or '—'}")
    falhas = [i for i in itens if not i["ok"]]
    for nivel in NIVEIS:
        for i in itens:
            if i["nivel"] != nivel or (i["ok"] and not todos):
                continue
            linhas.append(f"  [{'ok   ' if i['ok'] else ROTULO[nivel]}] {i['titulo']}" + (f" — {i['detalhe']}" if i["detalhe"] else ""))
            if not i["ok"]:
                linhas.append(f"          {'automático' if i['corrigivel'] else 'manual'}: {i['como_corrigir']}")
    linhas.append(f"  {len(itens) - len(falhas)} de {len(itens)} ok"
                  + (f"; {sum(1 for i in falhas if i['corrigivel'])} com correção automática" if falhas else ""))
    return linhas


def _projetos_cli(projeto):
    if projeto:
        return [projeto]
    return configuracao.carregar()["projetos"]


def main(argv=None):
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="Boas práticas do projeto: valida e corrige o básico do time de agentes")
    sub = ap.add_subparsers(dest="comando", required=True)
    v = sub.add_parser("validar", help="confere o projeto (sai com 1 se houver erro)")
    v.add_argument("projeto", nargs="?", help="pasta do projeto (padrão: projetos do config.json)")
    v.add_argument("--json", action="store_true", help="saída em JSON")
    c = sub.add_parser("corrigir", help="mostra o plano das correções seguras (com --aplicar, executa)")
    c.add_argument("projeto", nargs="?", help="pasta do projeto (padrão: projetos do config.json)")
    c.add_argument("--aplicar", action="store_true", help="executa o plano")
    c.add_argument("--so", default="", help="só estas checagens (ids separados por vírgula)")
    c.add_argument("--instalar-deps", action="store_true", help="ao criar o .venv, roda pip install -r requirements.txt")
    args = ap.parse_args(argv)
    projetos = _projetos_cli(args.projeto)
    if not projetos:
        print("Nenhum projeto: passe a pasta ou configure \"projetos\" no config.json.")
        return 2
    codigo = 0
    if args.comando == "validar":
        saida = []
        for p in projetos:
            if not Path(p).is_dir():
                print(f"Pasta não encontrada: {p}")
                codigo = 2
                continue
            itens = validar(p)
            escopo = detectar_escopo(p)
            codigo = max(codigo, 1 if tem_erro(itens) else 0)
            if args.json:
                saida.append({"projeto": str(p), "stacks": sorted(escopo["stacks"]), "testes": escopo["testes"],
                              "descricao": escopo["descricao"], "itens": itens})
            else:
                print("\n".join(relatorio(p, itens, escopo)))
        if args.json:
            print(json.dumps(saida, ensure_ascii=False, indent=2))
        return codigo
    ids = {s.strip() for s in args.so.split(",") if s.strip()} or None
    for p in projetos:
        if not Path(p).is_dir():
            print(f"Pasta não encontrada: {p}")
            codigo = 2
            continue
        acoes = corrigir(p, ids, aplicar=args.aplicar, instalar_deps=args.instalar_deps)
        print(f"Projeto: {p}")
        if not acoes:
            print("  nada a corrigir automaticamente" + (" (nas checagens pedidas)" if ids else ""))
        for a in acoes:
            if not args.aplicar:
                print(f"  [plano] {a['acao']}")
            elif a["erro"]:
                print(f"  [FALHOU] {a['acao']}: {a['erro']}")
                codigo = 1
            else:
                print(f"  [feito] {a['acao']}")
        if acoes and not args.aplicar:
            print("  (nada foi alterado; rode de novo com --aplicar para executar)")
    return codigo


if __name__ == "__main__":
    sys.exit(main())
