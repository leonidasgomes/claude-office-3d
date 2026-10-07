# -*- coding: utf-8 -*-
"""Testes do grafo.py, dos hooks e do instalador (só biblioteca padrão; rode com `python -W error`).

    python -W error grafo/testes/testar_grafo.py          (código 0 = tudo passou)

Monta um repositório git temporário com Python, C++ e TypeScript falsos e um grafo com problemas conhecidos (aresta
real não declarada, ciclo real, camada violada no código, arquivo órfão, caminho inexistente). O teste de fumaça contra
um projeto de verdade só roda com GRAFO_BASE_EXEMPLO=<raiz do projeto> (sem a variável, é pulado).
"""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

AQUI = Path(__file__).resolve().parent
RAIZ_FERRAMENTA = AQUI.parent
sys.path.insert(0, str(RAIZ_FERRAMENTA))
import grafo  # noqa: E402

HOOK = RAIZ_FERRAMENTA / "claude" / "hooks" / "grafo_hook.py"
INSTALADOR = RAIZ_FERRAMENTA / "claude" / "instalar_grafo.py"
BASE_EXEMPLO = Path(os.environ["GRAFO_BASE_EXEMPLO"]) if os.environ.get("GRAFO_BASE_EXEMPLO") else None

GRAFO_YAML = """\
# grafo de teste (formato de arquivo único)
schema_version: 1
project: Teste
updated: 2026-10-01
layers:
  dominio: {description: Núcleo, may_depend_on: []}
  servico:
    description: Serviços
    may_depend_on: [dominio]
  ferramenta: {description: Ferramentas, may_depend_on: [servico, dominio]}
coverage:
  roots: [app, tools, engine, ui, web, tests]
  extensions: [.py, .h, .cpp, .ts]
  ignore: [app/__init__.py]
systems:
  - id: sys.core
    name: Núcleo de modelo
    layer: dominio
    status: active
    summary: Modelo de dados e utilidades.
    description: >
      O modelo de dados do projeto e as utilidades
      compartilhadas. Histórico: veio do protótipo.
    paths: [app/core]
    invariants: [modelo sem efeitos colaterais]
    depends_on: []
    decisions: [adr.001_modelo]
  - id: sys.especial
    name: Arquivo especial dentro do núcleo
    layer: dominio
    status: active
    description: Um arquivo da pasta do núcleo com outro dono (caminho exato vence a pasta).
    paths: [app/core/especial.py]
    depends_on: []
  - id: sys.api
    name: API de rotas
    layer: servico
    status: active
    description: Rotas HTTP.
    paths: [app/api]
    depends_on: [sys.core]
  - id: sys.tools
    name: Ferramentas de relatório
    layer: ferramenta
    status: active
    description: Relatórios.
    paths: [tools]
    depends_on: [sys.api, sys.core]
    test_cmd: python -m pytest tools
  - id: sys.engine
    name: Motor do jogo
    layer: servico
    status: active
    description: Laço do jogo em C++.
    paths: [engine/Game.h, engine/Game.cpp]
    classes: [Game]
    depends_on: []
  - id: sys.ui
    name: Interface (HUD)
    layer: servico
    status: active
    description: Desenha o HUD.
    paths: [ui]
    classes: [Hud]
    depends_on: []
  - id: sys.web
    name: Front-end web
    layer: servico
    status: active
    description: Página em TypeScript.
    paths: [web, web/inexistente.ts]
    depends_on: []
  - id: sys.testes
    name: Testes automatizados
    layer: ferramenta
    status: active
    description: Testes.
    paths: [tests]
    depends_on: [sys.core]
events:
  - id: evt.redraw
    name: Redesenhar o HUD
    kind: call
    symbol: Hud::Redraw
    producer: sys.engine
    consumers: [sys.ui]
    description: O motor pede ao HUD para redesenhar.
tests:
  - id: test.modelo
    name: Testes do modelo
    kind: python
    paths: [tests/test_modelo.py]
    covers: [sys.core]
    command: python -m pytest tests
decisions:
  - id: adr.001_modelo
    title: Modelo imutável
    status: accepted
    date: 2026-09-01
    decision: O modelo não muda depois de criado.
    affects: [sys.core]
"""

ARQUIVOS = {
    "app/__init__.py": "",
    "app/core/__init__.py": "",
    "app/core/modelo.py": "from . import util\n\nclass Modelo:\n    def salvar(self):\n        return util.agora()\n",
    "app/core/util.py": "import os\n\ndef agora():\n    return os.getpid()\n",
    "app/core/especial.py": "def especial():\n    return 1\n",
    "app/api/__init__.py": "",
    "app/api/rotas.py": ("from app.core import modelo\nfrom app.core.util import agora\nimport tools.relatorio\n\n"
                         "def rota_principal():\n    return modelo.Modelo()\n"),
    "tools/__init__.py": "",
    "tools/relatorio.py": "from app.api import rotas\n\ndef gerar_relatorio():\n    return rotas.rota_principal()\n",
    "engine/Game.h": "#pragma once\n#include \"../ui/Hud.h\"\nclass Game {\npublic:\n  void Update();\n};\n",
    "engine/Game.cpp": "#include \"Game.h\"\n#include <vector>\nvoid Game::Update() {\n  Hud h;\n  h.Redraw();\n}\n",
    "ui/Hud.h": "#pragma once\nclass Hud {\npublic:\n  void Redraw();\n};\n",
    "ui/Hud.cpp": "#include \"Hud.h\"\n#include \"engine/Game.h\"\nvoid Hud::Redraw() {}\n",
    "web/util.ts": "export function formatar(x: number): string { return String(x); }\n",
    "web/index.ts": "import { formatar } from './util';\nexport const pagina = formatar(1);\n",
    "tests/test_modelo.py": "from app.core.modelo import Modelo\n\ndef test_modelo():\n    assert Modelo()\n",
    "app/novo/solto.py": "from app.core.util import agora\n\ndef solto():\n    return agora()\n",
    "docs/grafo.yaml": GRAFO_YAML,
    "README.md": "projeto de teste\n",
}


def git(raiz, *args):
    p = subprocess.run(["git", "-C", str(raiz), "-c", "user.name=t", "-c", "user.email=t@t", "-c", "core.autocrlf=false",
                        *args], capture_output=True, text=True, encoding="utf-8")
    if p.returncode != 0:
        raise RuntimeError(f"git {args}: {p.stderr}")
    return p.stdout


def montar_repo(destino: Path, arquivos=ARQUIVOS, commit=True):
    destino.mkdir(parents=True, exist_ok=True)
    for rel, texto in arquivos.items():
        p = destino / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(texto, encoding="utf-8", newline="\n")
    git(destino, "init", "-q")
    if commit:
        git(destino, "add", "-A")
        git(destino, "commit", "-q", "-m", "inicial")
    return destino


def cli(*args):
    """Roda grafo.main no processo; devolve (código, saída)."""
    buf, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
        codigo = grafo.main([str(a) for a in args])
    return codigo, buf.getvalue() + err.getvalue()


def rodar_hook(modo, entrada, *extra, env_extra=None):
    env = {**os.environ, "PYTHONUTF8": "1", **(env_extra or {})}
    dados = entrada if isinstance(entrada, (bytes, str)) else json.dumps(entrada)
    if isinstance(dados, str):
        dados = dados.encode("utf-8")
    p = subprocess.run([sys.executable, "-W", "error", str(HOOK), modo, *extra], input=dados, capture_output=True,
                       env=env, timeout=120)
    return p.returncode, p.stdout.decode("ascii"), p.stderr.decode("utf-8", "replace")


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix="grafo-teste-")
        cls.tmp = Path(cls._tmp.name).resolve()
        cls.raiz = montar_repo(cls.tmp / "repo")
        cls.estado = cls.tmp / "estado"

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def g(self, *args):
        return cli(*args[:1], "--raiz", self.raiz, *args[1:])


# ============================================================================================================ YAML
class TesteYaml(unittest.TestCase):
    TEXTO = """\
# comentário
a: 1
b: texto simples # comentário no fim
c: "aspas: com # dentro"
d: 'simples ''escapada'''
e: [x, y, "z, w",
    k]
f: {um: 1, dois: [2, 3]}
g: >
  linha um
  linha dois

  parágrafo
h: |-
  literal
    indentado
i:
- item1
- chave: v
  outra: [1, 2]
-   - aninhado
j: ~
k: true
l: 2026-10-01
m: 1.5
n: ""
o: multi
  linha plana
"""

    def esperado(self):
        return {"a": 1, "b": "texto simples", "c": "aspas: com # dentro", "d": "simples 'escapada'",
                "e": ["x", "y", "z, w", "k"], "f": {"um": 1, "dois": [2, 3]},
                "g": "linha um linha dois\nparágrafo\n", "h": "literal\n  indentado",
                "i": ["item1", {"chave": "v", "outra": [1, 2]}, ["aninhado"]], "j": None, "k": True,
                "l": "2026-10-01", "m": 1.5, "n": "", "o": "multi linha plana"}

    def test_mini_leitor(self):
        self.assertEqual(grafo._MiniYaml(self.TEXTO, "t").documento(), self.esperado())

    def test_pyyaml_igual_quando_instalado(self):
        if grafo._YAML is None:
            self.skipTest("PyYAML ausente")
        self.assertEqual(grafo.ler_yaml_texto(self.TEXTO), self.esperado())

    def test_chave_duplicada(self):
        with self.assertRaises(grafo.ErroYaml):
            grafo._MiniYaml("a: 1\na: 2\n", "t").documento()
        if grafo._YAML is not None:
            with self.assertRaises(grafo.ErroYaml):
                grafo.ler_yaml_texto("a: 1\na: 2\n")

    def test_grafo_de_teste_igual_nos_dois_leitores(self):
        mini = grafo._MiniYaml(GRAFO_YAML, "t").documento()
        if grafo._YAML is not None:
            self.assertEqual(grafo.ler_yaml_texto(GRAFO_YAML), mini)
        self.assertEqual(mini["systems"][0]["description"],
                         "O modelo de dados do projeto e as utilidades compartilhadas. Histórico: veio do protótipo.\n")

    def test_gravar_e_reler(self):
        dados = {"x": "a: b", "y": ["1", "dois", "três, quatro"], "z": [{"id": "sys.a", "paths": ["p/q"], "n": None}],
                 "w": {}, "v": [], "u": "2026-10-01", "t": "yes", "s": True, "r": 3}
        texto = grafo.gravar_yaml(dados)
        self.assertEqual(grafo._MiniYaml(texto, "t").documento(), dados)
        if grafo._YAML is not None:
            self.assertEqual(grafo.ler_yaml_texto(texto), dados)


# ============================================================================================================ donos
class TesteDonos(unittest.TestCase):
    def test_precedencia(self):
        d = grafo.Donos([
            {"id": "sys.pasta", "paths": ["src"]},
            {"id": "sys.sub", "paths": ["src/sub/"]},
            {"id": "sys.exato", "paths": ["src/sub/a.py"]},
            {"id": "sys.glob1", "paths": ["lib/*.py"]},
            {"id": "sys.glob2", "paths": ["lib/*.py"]},
        ])
        self.assertEqual(d.dono("src/x.py")[0], "sys.pasta")
        self.assertEqual(d.dono("src/sub/b.py")[0], "sys.sub")
        self.assertEqual(d.dono("src/sub/a.py")[0], "sys.exato")
        self.assertEqual(d.dono("SRC/SUB/A.PY")[0], "sys.exato")
        self.assertEqual(d.dono("lib/m.py")[0], "sys.glob2")   # empate: o último vence (CODEOWNERS)
        self.assertIsNone(d.dono("lib/x/m.py"))                # * não atravessa pasta
        self.assertIsNone(d.dono("outro/m.py"))
        self.assertIn(("lib/*.py", ["sys.glob1", "sys.glob2"]), d.conflitos())


# ============================================================================================================ CLI no repo
class TesteValidate(Base):
    def validar_json(self, *extra):
        codigo, saida = self.g("validate", "--json", *extra)
        return codigo, json.loads(saida)

    def test_achados(self):
        codigo, r = self.validar_json()
        self.assertEqual(codigo, 1)
        erros = {e["codigo"]: e for e in r["erros"]}
        msgs = [e["msg"] for e in r["erros"]]
        avisos = [a["msg"] for a in r["avisos"]]
        # arestas reais não declaradas
        self.assertTrue(any("sys.api -> sys.tools" in a for a in avisos if "não declarada" in a), avisos)
        self.assertTrue(any("sys.ui -> sys.engine" in a for a in avisos if "não declarada" in a), avisos)
        # engine -> ui é explicada pelo evento call (Hud::Redraw é do sistema ui)
        self.assertFalse(any("sys.engine -> sys.ui" in a for a in avisos), avisos)
        # ciclo real api <-> tools e camada violada (servico -> ferramenta)
        self.assertIn("ciclo_real", erros)
        self.assertTrue(any("sys.api" in m and "sys.tools" in m for m in msgs if "ciclo real" in m))
        self.assertTrue(any("camada violada no código: sys.api (servico) -> sys.tools (ferramenta)" in m for m in msgs))
        # cobertura e caminhos
        self.assertTrue(any("app/novo/solto.py" in m and "sys.core" in m for m in msgs if "ÓRFÃO" in m), msgs)
        self.assertTrue(any("web/inexistente.ts" in m for m in msgs))
        # dependência declarada sem uso: tools -> core
        self.assertTrue(any("sys.tools -> sys.core" in a for a in avisos if "sem uso" in a), avisos)
        # aninhado: arquivo exato dentro da pasta de outro sistema
        self.assertTrue(any(a["codigo"] == "aninhado" for a in r["avisos"]))

    def test_muitos_orfaos_rapido(self):
        import time
        arqs = dict(ARQUIVOS)
        for i in range(2950):
            arqs[f"app/massa/d{i % 60}/m{i}.py"] = "from app.core import util\n"
        repo = montar_repo(self.tmp / "repo_massa", arqs)
        t0 = time.time()
        codigo, saida = cli("validate", "--raiz", repo, "--json")
        self.assertEqual(codigo, 1)
        self.assertGreaterEqual(sum(e["codigo"] == "orfao" for e in json.loads(saida)["erros"]), 2950)
        self.assertLess(time.time() - t0, 20)

    def test_correcoes_menores(self):
        # script: chamada real conta; comentário, bloco <# #> e echo não
        refs = grafo.extrair_refs("a/run.ps1", "<#\n x.ps1\n#>\n. (Join-Path $PSScriptRoot 'b.ps1')  # c.ps1\n"
                                                "Write-Host 'rode d.py'\n& python tools/e.py\nREM f.bat\n")
        self.assertEqual([r[1].rsplit("/", 1)[-1].strip("'") for r in refs], ["b.ps1", "e.py"])
        # padrão de pasta é dono do conteúdo; padrão inválido vira erro, não traceback
        d = grafo.Donos([{"id": "sys.f", "paths": ["src/Foo*"]}])
        self.assertEqual(d.dono("src/FooBar/x/y.py")[0], "sys.f")
        repo = montar_repo(self.tmp / "repo_glob")
        y = repo / "docs" / "grafo.yaml"
        y.write_text(y.read_text(encoding="utf-8").replace("paths: [tools]", "paths: [tools, \"x/[z-a].py\"]"),
                     encoding="utf-8")
        codigo, saida = cli("validate", "--raiz", repo, "--json")
        self.assertEqual(codigo, 1)
        self.assertTrue(any(e["codigo"] == "padrao_invalido" for e in json.loads(saida)["erros"]))
        # escape inválido no YAML: erro com linha
        with self.assertRaises(grafo.ErroYaml) as ctx:
            grafo._MiniYaml('a: 1\nb: "\\xZZ"\n', "t.yaml").documento()
        self.assertIn("t.yaml:2", str(ctx.exception))
        # saida/regras da configuração fora da raiz: recusado; pela CLI é livre
        (repo / "grafo.json").write_text('{"saida": "../fora", "regras": "../fora2"}', encoding="utf-8")
        self.assertEqual(cli("index", "--raiz", repo)[0], 2)
        self.assertEqual(cli("sync-rules", "--raiz", repo, "--escrever")[0], 2)
        self.assertFalse((repo.parent / "fora").exists() or (repo.parent / "fora2").exists())
        self.assertEqual(cli("index", "--raiz", repo, "--saida", self.tmp / "livre")[0], 0)
        # ref que começa com '-' é recusada antes de chegar ao git
        with self.assertRaises(ValueError):
            grafo.resolver_ref(repo, "--output=x")

    def test_sys_path_herdado_e_determinismo(self):
        extra = {
            "tools/caminhos.py": ("import sys\nfrom pathlib import Path\nLIB = Path(__file__).resolve().parents[1] / 'libx'\n"
                                  "sys.path.insert(0, str(LIB))  # também põe libx no sys.path de quem importa\n"),
            "tools/usa.py": "import caminhos\nimport extra\n",          # herda o sys.path de caminhos (1 nível)
            "tools/neto.py": "import usa\nimport extra\n",              # 2 níveis
            "tools/sozinho.py": "import extra\n",                       # nada põe libx no sys.path: externo
            "libx/extra.py": "x = 1\n",
            # módulo do repo com o nome de um pacote instalado (PyYAML): a regra do repo vence, igual em toda máquina
            "app/core/cfg.py": "import sys\nsys.path.insert(0, str(ROOT / 'tools'))\nimport yaml\n",
            "tools/yaml.py": "x = 1\n",
        }
        repo = montar_repo(self.tmp / "repo_herdado", {**ARQUIVOS, **extra})
        proj = grafo.Projeto(repo)
        arestas = {(o, d) for o, d, _, _ in grafo.Analise(proj, proj.grafo()).arestas_arquivo}
        self.assertIn(("tools/usa.py", "libx/extra.py"), arestas)
        self.assertIn(("tools/neto.py", "libx/extra.py"), arestas)
        self.assertNotIn(("tools/sozinho.py", "libx/extra.py"), arestas)
        self.assertIn(("app/core/cfg.py", "tools/yaml.py"), arestas)

    def test_base_atalho_sem_mudanca_coberta(self):
        repo = montar_repo(self.tmp / "repo_atalho")
        (repo / "README.md").write_text("mudou\n", encoding="utf-8")
        codigo, saida = cli("validate", "--raiz", repo, "--base", "HEAD", "--json")
        r = json.loads(saida)
        self.assertEqual(codigo, 0)
        self.assertEqual(r["info"].get("atalho"), "nada coberto mudou")
        (repo / "web" / "util.ts").write_text("export const y = 2;\n", encoding="utf-8")
        _, saida = cli("validate", "--raiz", repo, "--base", "HEAD", "--json")
        self.assertNotIn("atalho", json.loads(saida)["info"])

    def test_instalador_forma_inesperada(self):
        with tempfile.TemporaryDirectory(prefix="grafo-inst3-") as t:
            proj = Path(t).resolve() / "p"
            (proj / ".claude").mkdir(parents=True)
            git(proj, "init", "-q")
            for ruim in ('{"hooks": []}', '{"hooks": {"Stop": {}}}', '{"hooks": {"Stop": [1]}}',
                         '{"hooks": {"Stop": [{"hooks": "x"}]}}'):
                (proj / ".claude" / "settings.json").write_text(ruim, encoding="utf-8")
                p = subprocess.run([sys.executable, "-W", "error", str(INSTALADOR), "--projeto", str(proj), "--aplicar"],
                                   capture_output=True, text=True, encoding="utf-8", timeout=60)
                self.assertEqual(p.returncode, 2, ruim)
                self.assertEqual((proj / ".claude" / "settings.json").read_text(encoding="utf-8"), ruim)

    def test_sem_pyyaml_mesmo_resultado(self):
        env = {**os.environ, "GRAFO_SEM_PYYAML": "1", "PYTHONUTF8": "1"}
        args = [sys.executable, "-W", "error", str(RAIZ_FERRAMENTA / "grafo.py"), "validate", "--raiz", str(self.raiz), "--json"]
        p1 = subprocess.run(args, capture_output=True, env=env, timeout=120)
        p2 = subprocess.run(args, capture_output=True, env={**os.environ, "PYTHONUTF8": "1"}, timeout=120)
        self.assertEqual(p1.returncode, 1, p1.stderr)
        self.assertEqual(json.loads(p1.stdout), json.loads(p2.stdout))

    def test_base_so_mudados(self):
        repo = montar_repo(self.tmp / "repo_base")
        (repo / "app" / "extra").mkdir()
        (repo / "app" / "extra" / "novo.py").write_text("from app.core import util\n", encoding="utf-8")
        codigo, saida = cli("validate", "--raiz", repo, "--base", "HEAD", "--json")
        r = json.loads(saida)
        msgs = [e["msg"] for e in r["erros"]]
        self.assertEqual(codigo, 1)
        self.assertTrue(any("app/extra/novo.py" in m for m in msgs), msgs)
        self.assertFalse(any("app/novo/solto.py" in m for m in msgs), msgs)    # órfão antigo, fora do diff
        self.assertFalse(any("ciclo real" in m for m in msgs), msgs)          # ciclo antigo, fora do diff
        # mudança que toca o ciclo volta a acusá-lo
        (repo / "tools" / "relatorio.py").write_text(ARQUIVOS["tools/relatorio.py"] + "# mexi\n", encoding="utf-8")
        _, saida = cli("validate", "--raiz", repo, "--base", "HEAD", "--json")
        self.assertTrue(any("ciclo real" in e["msg"] for e in json.loads(saida)["erros"]))
        codigo, _ = cli("validate", "--raiz", repo, "--base", "ref-que-nao-existe")
        self.assertEqual(codigo, 2)


class TesteConsultas(Base):
    def test_owner_normaliza(self):
        abs_win = str(self.raiz / "app" / "core" / "modelo.py").replace("/", "\\")
        for entrada in (abs_win, "app/core/modelo.py", "APP\\CORE\\MODELO.PY", "./app/core/modelo.py",
                        str(self.raiz / ".claude" / "worktrees" / "colega-1" / "app" / "core" / "modelo.py"),
                        "Z:\\outro\\clone\\app\\core\\modelo.py"):
            codigo, saida = self.g("owner", entrada, "--json")
            self.assertEqual(codigo, 0, entrada)
            r = json.loads(saida)
            self.assertEqual(r["arquivo"], "app/core/modelo.py", entrada)
            self.assertEqual(r["dono"], "sys.core", entrada)
        codigo, saida = self.g("owner", "app/core/especial.py", "--json")
        self.assertEqual(json.loads(saida)["dono"], "sys.especial")
        codigo, saida = self.g("owner", "app/novo/solto.py", "--json")
        self.assertEqual(codigo, 1)
        self.assertEqual(json.loads(saida)["sugestoes"][0]["sistema"], "sys.core")

    def test_suggest(self):
        codigo, saida = self.g("suggest", "app/novo/solto.py", "--json")
        self.assertEqual(codigo, 0)
        r = json.loads(saida)
        self.assertIsNone(r["dono_atual"])
        self.assertEqual(r["sugestoes"][0]["sistema"], "sys.core")
        self.assertTrue(any("import" in m for m in r["sugestoes"][0]["motivos"]))
        # arquivo ainda inexistente: só a pasta conta
        codigo, saida = self.g("suggest", "tools/futuro.py", "--json")
        self.assertEqual(json.loads(saida)["sugestoes"][0]["sistema"], "sys.tools")

    def test_slice_orcamento(self):
        codigo, saida = self.g("slice", "core", "--json")
        r = json.loads(saida)
        self.assertEqual(r["sistema"], "sys.core")
        self.assertIn("Modelo de dados e utilidades.", r["texto"])
        self.assertIn("usado por:", r["texto"])
        self.assertIn("test.modelo", r["texto"])
        self.assertIn("adr.001_modelo", r["texto"])
        self.assertIn("invariantes:", r["texto"])
        self.assertNotIn("Histórico", r["texto"])   # o summary substitui a descrição longa
        for orc in (20, 40, 80):
            _, saida = self.g("slice", "sys.core", "--budget", orc, "--json")
            r = json.loads(saida)
            self.assertLessEqual(len(r["texto"]), orc * grafo.CARACTERES_POR_TOKEN, r["texto"])
            self.assertTrue(r["cortado"])
        codigo, saida = self.g("slice", "app/api/rotas.py", "--reais")
        self.assertEqual(codigo, 0)
        self.assertIn("importa sem declarar: sys.tools", saida)
        codigo, _ = self.g("slice", "nao_existe")
        self.assertEqual(codigo, 2)

    def test_impact_diff(self):
        repo = montar_repo(self.tmp / "repo_impact")
        (repo / "app" / "core" / "util.py").write_text(ARQUIVOS["app/core/util.py"] + "# mudou\n", encoding="utf-8")
        codigo, saida = cli("impact", "--raiz", repo, "--diff", "HEAD", "--json")
        self.assertEqual(codigo, 0)
        r = json.loads(saida)
        self.assertEqual(r["arquivos"], ["app/core/util.py"])
        self.assertEqual(list(r["tocados"]), ["sys.core"])
        for s in ("sys.api", "sys.tools", "sys.testes"):
            self.assertIn(s, r["impactados"])
        self.assertEqual(r["impactados"]["sys.api"], 1)
        self.assertNotIn("sys.web", r["impactados"])
        ids = {t["id"]: t["prioridade"] for t in r["testes"]}
        self.assertEqual(ids.get("test.modelo"), 1)
        self.assertIn("adr.001_modelo", r["adrs"])
        self.assertIn("app/api/rotas.py", r["arquivos_provaveis"])
        self.assertIn("app/core/modelo.py", r["arquivos_provaveis"])
        codigo, saida = cli("impact", "--raiz", repo, "tools/relatorio.py")
        self.assertIn("tocado    sys.tools", saida)
        self.assertIn("* sys.tools.test_cmd: python -m pytest tools", saida)

    def test_find(self):
        codigo, saida = self.g("find", "Redraw", "--json")
        r = json.loads(saida)
        self.assertEqual(r["sistemas"][0]["sistema"], "sys.ui")
        arquivos = [a["arquivo"] for a in r["sistemas"][0]["arquivos"]]
        self.assertIn("ui/Hud.cpp", arquivos)
        self.assertIn("ui/Hud.h", arquivos)
        self.assertTrue(any(o["id"] == "evt.redraw" for o in r["outros"]))
        _, saida = self.g("find", "gerar_relatorio", "--json")
        r = json.loads(saida)
        self.assertEqual(r["sistemas"][0]["sistema"], "sys.tools")
        self.assertEqual(r["sistemas"][0]["arquivos"][0]["arquivo"], "tools/relatorio.py")
        _, saida = self.g("find", "rotas.py", "--json")
        self.assertEqual(json.loads(saida)["sistemas"][0]["sistema"], "sys.api")
        _, saida = self.g("find", "sys.web", "--json")
        self.assertEqual(json.loads(saida)["sistemas"][0]["sistema"], "sys.web")
        codigo, saida = self.g("find", "palavraquenaoexiste")
        self.assertEqual(codigo, 1)
        codigo, saida = self.g("find", "modelo")
        self.assertEqual(codigo, 0)
        self.assertIn("app/core/modelo.py", saida)

    def test_drift(self):
        codigo, saida = self.g("drift", "--json")
        m = json.loads(saida)
        self.assertEqual(m["orfaos"], 1)
        self.assertLess(m["pct_com_dono"], 100)
        self.assertIn("sys.api->sys.tools", m["nao_declaradas"])
        self.assertIn("sys.tools->sys.core", m["sem_uso"])
        self.assertEqual(m["ciclos_reais"], 1)
        self.assertEqual(m["camadas_violadas_reais"], 1)
        self.assertEqual(m["paths_quebrados"], 1)
        self.assertIsInstance(m["dias_desde_updated"], int)
        codigo, saida = self.g("drift")
        self.assertIn("arquivos com dono:", saida)

    def test_index_deterministico(self):
        saida1 = self.tmp / "idx1"
        saida2 = self.tmp / "idx2"
        self.g("index", "--saida", saida1)
        self.g("index", "--saida", saida2)
        for nome in ("index.json", "resumo.txt"):
            self.assertEqual((saida1 / nome).read_bytes(), (saida2 / nome).read_bytes(), nome)
        idx = json.loads((saida1 / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(idx["arquivos"]["app/core/modelo.py"], "sys.core")
        self.assertIsNone(idx["arquivos"]["app/novo/solto.py"])
        self.assertEqual(idx["sistemas"]["sys.core"]["camada"], "dominio")
        self.assertTrue(idx["sistemas"]["sys.core"]["cor"].startswith("#"))
        self.assertEqual(idx["camadas"]["dominio"]["cor"], idx["sistemas"]["sys.core"]["cor"])
        tipos = {(a["de"], a["para"]): a["tipo"] for a in idx["arestas"]["reais"]}
        self.assertEqual(tipos[("sys.api", "sys.core")], "declarada")
        self.assertEqual(tipos[("sys.engine", "sys.ui")], "evento")
        self.assertEqual(tipos[("sys.api", "sys.tools")], "nao_declarada")
        self.assertIn(["sys.api", "sys.core"], idx["arestas"]["declaradas"])
        resumo = (saida1 / "resumo.txt").read_text(encoding="utf-8")
        self.assertEqual(len([l for l in resumo.splitlines() if not l.startswith("#")]), 8)
        self.assertLess(grafo.tokens_aprox(resumo), 2000)
        # padrão: .grafo/ na raiz
        codigo, _ = self.g("index")
        self.assertTrue((self.raiz / ".grafo" / "index.json").is_file())

    def test_sync_rules(self):
        pasta = self.tmp / "regras"
        codigo, saida = self.g("sync-rules", "--saida", pasta)
        self.assertEqual(codigo, 0)
        self.assertFalse(pasta.exists())
        self.assertIn("nada gravado", saida)
        self.g("sync-rules", "--saida", pasta, "--escrever")
        regra = (pasta / "arq-core.md").read_text(encoding="utf-8")
        self.assertTrue(regra.startswith('---\npaths:\n  - "app/core/**"\n---\n'))
        self.assertIn("Invariantes: modelo sem efeitos colaterais.", regra)
        self.assertIn("test.modelo", regra)
        linhas_corpo = regra.split("---\n", 2)[2].strip().splitlines()
        self.assertLessEqual(len([l for l in linhas_corpo if l.startswith("- ")]), 10)
        self.assertIn('  - "engine/Game.h"', (pasta / "arq-engine.md").read_text(encoding="utf-8"))
        antes = {p.name: p.read_bytes() for p in pasta.iterdir()}
        _, saida = self.g("sync-rules", "--saida", pasta, "--escrever")
        self.assertNotIn("alterado", saida)
        self.assertEqual(antes, {p.name: p.read_bytes() for p in pasta.iterdir()})
        # regra de sistema que sumiu é removida (só as geradas)
        (pasta / "arq-velho.md").write_text("x\n" + grafo.MARCA_REGRA + "\n", encoding="utf-8")
        (pasta / "arq-manual.md").write_text("regra escrita à mão\n", encoding="utf-8")
        self.g("sync-rules", "--saida", pasta, "--escrever")
        self.assertFalse((pasta / "arq-velho.md").exists())
        self.assertTrue((pasta / "arq-manual.md").exists())


class TesteInit(unittest.TestCase):
    def test_init(self):
        with tempfile.TemporaryDirectory(prefix="grafo-init-") as t:
            arquivos = {k: v for k, v in ARQUIVOS.items() if not k.startswith("docs/")}
            raiz = montar_repo(Path(t).resolve() / "novo", arquivos)
            codigo, saida = cli("init", "--raiz", raiz, "--max-arquivos", "3")
            self.assertEqual(codigo, 0)
            dados = grafo.ler_yaml_texto(saida)
            ids = {s["id"]: s for s in dados["systems"]}
            self.assertTrue(all(s["status"] == "proposto" and s["layer"] == "" for s in ids.values()))
            api = next(s for s in ids.values() if s["paths"] == ["app/api"])
            core = next(s for s in ids.values() if s["paths"] == ["app/core"])
            tools = next(s for s in ids.values() if s["paths"] == ["tools"])
            self.assertIn(core["id"], api["depends_on"])
            self.assertIn(tools["id"], api["depends_on"])
            self.assertTrue(any(t["paths"] == ["tests"] and core["id"] in t["covers"] for t in dados["tests"]))
            destino = raiz / "docs" / "grafo.yaml"
            codigo, _ = cli("init", "--raiz", raiz, "--saida", destino, "--max-arquivos", "3")
            self.assertEqual(codigo, 0)
            antes = destino.read_bytes()
            codigo, _ = cli("init", "--raiz", raiz, "--saida", destino)
            self.assertEqual(codigo, 2)                      # não sobrescreve
            self.assertEqual(destino.read_bytes(), antes)
            codigo, saida = cli("validate", "--raiz", raiz, "--json")
            r = json.loads(saida)
            self.assertFalse([e for e in r["erros"] if e["codigo"] in ("orfao", "esquema", "ref", "id")], r["erros"])
            # repositório pequeno (cabe num sistema só): o sistema da raiz cobre as pastas de verdade
            saida = cli("init", "--raiz", raiz)[1]
            dados = grafo.ler_yaml_texto("\n".join(l for l in saida.splitlines() if not l.startswith("(já existe")))
            self.assertEqual(len(dados["systems"]), 1)
            self.assertIn("app", dados["systems"][0]["paths"])
            self.assertTrue(any(a["codigo"] == "proposto" for a in r["avisos"]))
            codigo, saida = cli("init", "--raiz", raiz, "--llm", "--max-arquivos", "3")
            self.assertIn("Sistemas propostos", saida)
            self.assertIn(core["id"], saida)
            self.assertIn("Modelo", saida)                   # símbolo extraído vai para o prompt


# ============================================================================================================ hooks
class TesteHooks(Base):
    def env(self):
        return {"GRAFO_ESTADO": str(self.estado)}

    def ent(self, arquivo, sessao="s1", evento="PreToolUse", **extra):
        return {"session_id": sessao, "cwd": str(self.raiz), "hook_event_name": evento, "tool_name": "Edit",
                "tool_input": {"file_path": arquivo}, **extra}

    def test_pre_uma_vez_por_sistema(self):
        alvo = str(self.raiz / "app" / "core" / "util.py").replace("/", "\\")
        codigo, out, err = rodar_hook("pre", self.ent(alvo), env_extra=self.env())
        self.assertEqual(codigo, 0, err)
        r = json.loads(out)
        ctx = r["hookSpecificOutput"]["additionalContext"]
        self.assertEqual(r["hookSpecificOutput"]["hookEventName"], "PreToolUse")
        self.assertIn("sys.core", ctx)
        self.assertIn("test.modelo (python -m pytest tests)", ctx)
        self.assertLessEqual(len(ctx), 10000)
        codigo, out, _ = rodar_hook("pre", self.ent(str(self.raiz / "app/core/modelo.py")), env_extra=self.env())
        self.assertEqual((codigo, out), (0, ""))           # mesmo sistema, mesma sessão: silêncio
        codigo, out, _ = rodar_hook("pre", self.ent(str(self.raiz / "app/core/modelo.py"), sessao="s2"),
                                    env_extra=self.env())
        self.assertIn("sys.core", json.loads(out)["hookSpecificOutput"]["additionalContext"])
        codigo, out, _ = rodar_hook("pre", self.ent("README.md"), env_extra=self.env())
        self.assertEqual((codigo, out), (0, ""))

    def test_post_arquivo_sem_dono(self):
        novo = self.raiz / "app" / "outro" / "novo_hook.py"
        novo.parent.mkdir(exist_ok=True)
        novo.write_text("from app.api import rotas\n", encoding="utf-8")
        try:
            codigo, out, err = rodar_hook("post", self.ent(str(novo), evento="PostToolUse"), env_extra=self.env())
            self.assertEqual(codigo, 0, err)
            ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
            self.assertIn("app/outro/novo_hook.py", ctx)
            self.assertIn("sys.api", ctx)                      # sugestão pela maioria dos imports
            codigo, out, _ = rodar_hook("post", self.ent(str(novo), evento="PostToolUse"), env_extra=self.env())
            self.assertEqual(out, "")                          # uma vez por arquivo por sessão
        finally:
            shutil.rmtree(novo.parent)
        codigo, out, _ = rodar_hook("post", self.ent(str(self.raiz / "app/core/util.py"), evento="PostToolUse"),
                                    env_extra=self.env())
        self.assertEqual(out, "")                              # já tem dono

    def test_fim(self):
        repo = montar_repo(self.tmp / "repo_fim")
        (repo / "app" / "extra").mkdir()
        (repo / "app" / "extra" / "x.py").write_text("x = 1\n", encoding="utf-8")
        ent = {"session_id": "f1", "cwd": str(repo), "hook_event_name": "TaskCompleted"}
        codigo, out, err = rodar_hook("fim", ent, "--base", "HEAD", env_extra=self.env())
        self.assertEqual(codigo, 0, err)
        self.assertIn("app/extra/x.py", json.loads(out)["systemMessage"])
        codigo, out, err = rodar_hook("fim", ent, "--base", "HEAD", env_extra=self.env())
        self.assertEqual(out, "")                              # mesmo achado: não repete
        codigo, out, err = rodar_hook("fim", ent, "--bloquear", "--base", "HEAD", env_extra=self.env())
        self.assertEqual(codigo, 2)
        self.assertIn("app/extra/x.py", err)
        stop = {**ent, "hook_event_name": "Stop", "session_id": "f2"}
        codigo, out, _ = rodar_hook("fim", stop, "--bloquear", "--base", "HEAD", env_extra=self.env())
        self.assertEqual(json.loads(out)["decision"], "block")
        codigo, out, _ = rodar_hook("fim", {**stop, "stop_hook_active": True, "session_id": "f3"}, "--bloquear",
                                    "--base", "HEAD", env_extra=self.env())
        self.assertIn("systemMessage", json.loads(out))
        limpo = montar_repo(self.tmp / "repo_fim_limpo", {k: v for k, v in ARQUIVOS.items()})
        codigo, out, _ = rodar_hook("fim", {**ent, "cwd": str(limpo)}, "--bloquear", "--base", "HEAD",
                                    env_extra=self.env())
        self.assertEqual((codigo, out), (0, ""))               # nada mudou: silêncio

    def test_nunca_levanta(self):
        for modo, entrada in (("pre", b"isto nao e json"), ("post", b""), ("fim", b"[1,2]"), ("xyz", b"{}"),
                              ("pre", json.dumps({"cwd": "Z:/nao/existe", "tool_input": {"file_path": "a.py"}})),
                              ("pre", json.dumps({"cwd": str(self.tmp), "tool_input": {"file_path": "a.py"}})),
                              ("fim", json.dumps({"cwd": str(self.raiz), "hook_event_name": "Stop"}))):
            codigo, out, _ = rodar_hook(modo, entrada, "--base", "ref-inexistente", env_extra=self.env())
            self.assertEqual(codigo, 0, (modo, entrada))
            if out:
                json.loads(out)


class TesteInstalador(unittest.TestCase):
    def test_instalar_sem_duplicar_e_desinstalar(self):
        with tempfile.TemporaryDirectory(prefix="grafo-inst-") as t:
            proj = Path(t).resolve() / "p"
            (proj / ".claude").mkdir(parents=True)
            git(proj, "init", "-q")
            original = {"env": {"X": "1"}, "hooks": {"PreToolUse": [
                {"matcher": "Bash", "hooks": [{"type": "command", "command": "python outro.py"}]}]}}
            arq = proj / ".claude" / "settings.json"
            arq.write_text(json.dumps(original), encoding="utf-8")

            def inst(*a):
                p = subprocess.run([sys.executable, "-W", "error", str(INSTALADOR), "--projeto", str(proj), *a],
                                   capture_output=True, text=True, encoding="utf-8", timeout=60)
                self.assertEqual(p.returncode, 0, p.stderr)
                return p.stdout

            saida = inst()
            self.assertIn("nada gravado", saida)
            self.assertEqual(json.loads(arq.read_text(encoding="utf-8")), original)
            inst("--aplicar")
            inst("--aplicar", "--bloquear")
            s = json.loads(arq.read_text(encoding="utf-8"))
            cmds = [h["command"] for grupos in s["hooks"].values() for g in grupos for h in g["hooks"]]
            self.assertEqual(sum("grafo_hook.py" in c and c.endswith(" pre") for c in cmds), 1)
            self.assertEqual(sum("fim --bloquear" in c for c in cmds), 2)     # Stop e TaskCompleted
            self.assertIn("python outro.py", cmds)
            self.assertEqual(s["env"], {"X": "1"})
            inst("--aplicar", "--copiar", "--skill")
            self.assertTrue((proj / ".claude" / "grafo" / "grafo.py").is_file())
            self.assertTrue((proj / ".claude" / "grafo" / "grafo_hook.py").is_file())
            self.assertTrue((proj / ".claude" / "skills" / "grafo" / "SKILL.md").is_file())
            s = json.loads(arq.read_text(encoding="utf-8"))
            self.assertTrue(all("$CLAUDE_PROJECT_DIR/.claude/grafo/grafo_hook.py" in h["command"]
                                for grupos in s["hooks"].values() for g in grupos for h in g["hooks"]
                                if "grafo_hook" in h["command"]))
            inst("--desinstalar", "--aplicar")
            self.assertEqual(json.loads(arq.read_text(encoding="utf-8")), original)
            # cópia dentro do projeto: o hook acha o grafo.py vizinho
            (proj / "docs").mkdir()
            (proj / "docs" / "grafo.yaml").write_text(GRAFO_YAML, encoding="utf-8")
            (proj / "app" / "core").mkdir(parents=True)
            (proj / "app" / "core" / "a.py").write_text("", encoding="utf-8")
            p = subprocess.run([sys.executable, "-W", "error", str(proj / ".claude" / "grafo" / "grafo_hook.py"), "pre"],
                               input=json.dumps({"session_id": "i1", "cwd": str(proj),
                                                 "tool_input": {"file_path": str(proj / "app/core/a.py")}}).encode(),
                               capture_output=True, timeout=60, env={**os.environ, "GRAFO_ESTADO": str(Path(t) / "e")})
            self.assertIn("sys.core", json.loads(p.stdout)["hookSpecificOutput"]["additionalContext"])


# ============================================================================================================ verificador
class TesteVerificador(Base):
    """Casos do verificador independente: robustez dos hooks, limites, instalador e bugs conhecidos (expectedFailure:
    quando o bug for corrigido o teste passa, o unittest acusa 'unexpected success' e o marcador deve sair)."""

    def env(self):
        return {"GRAFO_ESTADO": str(self.estado)}

    def test_hook_entradas_estranhas(self):
        alvo = str(self.raiz / "app" / "core" / "util.py")
        casos = [
            {"cwd": str(self.raiz), "tool_input": "texto"},
            {"cwd": str(self.raiz), "tool_input": {"file_path": [1, 2]}},
            {"cwd": 123, "tool_input": {"file_path": alvo}},
            {"cwd": str(self.raiz), "session_id": {"x": 1}, "tool_input": {"file_path": alvo}},
            {"cwd": str(self.raiz), "session_id": "v1", "tool_input": {"file_path": "../../../../etc/passwd"}},
            {"cwd": str(self.raiz), "session_id": "v2", "tool_input": {"file_path": alvo + "\u0000"}},
            {"cwd": str(self.raiz), "session_id": "v3", "tool_input": {"file_path": alvo, "content": "x" * 3_000_000}},
        ]
        for modo in ("pre", "post", "fim"):
            for i, ent in enumerate(casos):
                codigo, out, _ = rodar_hook(modo, ent, env_extra=self.env())
                self.assertEqual(codigo, 0, (modo, i))
                if out:
                    json.loads(out)
        codigo, out, _ = rodar_hook("pre", b"\xff\xfe\x00lixo", env_extra=self.env())
        self.assertEqual((codigo, out), (0, ""))

    def test_fim_mensagem_dentro_do_limite(self):
        repo = montar_repo(self.tmp / "repo_muitos")
        pasta = repo / "app" / ("orfaos_" + "x" * 60)
        pasta.mkdir()
        for i in range(300):
            (pasta / f"arquivo_com_nome_comprido_{i:04d}_{'y' * 40}.py").write_text("x = 1\n", encoding="utf-8")
        ent = {"session_id": "lim", "cwd": str(repo), "hook_event_name": "Stop"}
        codigo, out, _ = rodar_hook("fim", ent, "--bloquear", "--base", "HEAD", env_extra=self.env())
        self.assertEqual(codigo, 0)
        r = json.loads(out)
        self.assertEqual(r["decision"], "block")
        self.assertLessEqual(len(r["reason"]), 10000)
        ent = {**ent, "session_id": "lim2", "hook_event_name": "TaskCompleted"}
        codigo, out, err = rodar_hook("fim", ent, "--bloquear", "--base", "HEAD", env_extra=self.env())
        self.assertEqual((codigo, out), (2, ""))
        self.assertLessEqual(len(err), 10000)

    def test_pre_contexto_curto_com_grafo_gigante(self):
        sis = {"nome": "N" * 5000, "camada": "c", "resumo": "r" * 5000, "deps": [f"sys.d{i}" for i in range(500)],
               "usado_por": [f"sys.u{i}" for i in range(500)], "invariantes": ["i" * 4000] * 10,
               "testes": ["t" * 3000] * 10, "adrs": ["a"] * 50}
        self.assertLessEqual(len(grafo.contexto_curto(sis, "sys.x", "a/b.py")), 700)

    def test_dono_empates_e_precedencia(self):
        d = grafo.Donos([{"id": "sys.a", "paths": ["src"]}, {"id": "sys.b", "paths": ["SRC/"]},
                         {"id": "sys.c", "paths": ["src/x/y.py"]}, {"id": "sys.d", "paths": ["src/x"]}])
        self.assertEqual(d.dono("src/z.py")[0], "sys.b")       # mesma pasta (maiúsculas à parte): o último vence
        self.assertEqual(d.dono("src/x/y.py")[0], "sys.c")     # exato vence a pasta mais longa declarada depois
        self.assertEqual(d.dono("src/x/w.py")[0], "sys.d")     # pasta mais longa vence
        self.assertIsNone(d.dono("srcx/a.py"))                 # prefixo de nome não é pasta

    def test_instalador_so_mostra_e_nao_toca_usuario(self):
        with tempfile.TemporaryDirectory(prefix="grafo-inst2-") as t:
            proj = Path(t).resolve() / "p"
            casa = Path(t).resolve() / "casa"
            proj.mkdir()
            casa.mkdir()
            git(proj, "init", "-q")
            env = {**os.environ, "HOME": str(casa), "USERPROFILE": str(casa)}

            def inst(*a):
                return subprocess.run([sys.executable, "-W", "error", str(INSTALADOR), "--projeto", str(proj), *a],
                                      capture_output=True, text=True, encoding="utf-8", timeout=60, env=env)

            p = inst()
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertFalse((proj / ".claude").exists())      # sem --aplicar nada é criado
            self.assertEqual(inst("--aplicar").returncode, 0)
            self.assertTrue((proj / ".claude" / "settings.json").is_file())
            self.assertFalse((casa / ".claude").exists())      # nunca no settings do usuário
            self.assertIn("já estava assim", inst("--aplicar").stdout)
            (proj / ".claude" / "settings.json").write_text("{quebrado", encoding="utf-8")
            self.assertEqual(inst("--aplicar").returncode, 2)
            self.assertEqual((proj / ".claude" / "settings.json").read_text(encoding="utf-8"), "{quebrado")

    def test_instalador_recusa_a_pasta_do_usuario(self):
        """Fora de repositório (cwd ~, --projeto ~, dotfiles na home) o alvo seria o settings.json do USUÁRIO: código 2."""
        with tempfile.TemporaryDirectory(prefix="grafo-inst3-") as t:
            casa = Path(t).resolve() / "casa"
            (casa / ".claude").mkdir(parents=True)
            usuario = casa / ".claude" / "settings.json"
            usuario.write_text('{"env": {"U": "1"}}', encoding="utf-8")
            env = {**os.environ, "HOME": str(casa), "USERPROFILE": str(casa)}

            def inst(*a, cwd=None):
                return subprocess.run([sys.executable, "-W", "error", str(INSTALADOR), *a], capture_output=True, text=True,
                                      encoding="utf-8", timeout=60, env=env, cwd=cwd)
            for args, cwd in ((["--projeto", str(casa), "--aplicar"], None), (["--aplicar"], str(casa)),
                              (["--projeto", str(casa)], None)):
                p = inst(*args, cwd=cwd)
                self.assertEqual(p.returncode, 2, (args, p.stdout, p.stderr))
                self.assertIn("pasta do usuário", p.stderr)
            git(casa, "init", "-q")   # repositório de dotfiles na home: a raiz resolvida continua sendo a home
            sub = casa / "sub"
            sub.mkdir()
            self.assertEqual(inst("--projeto", str(sub), "--aplicar").returncode, 2)
            self.assertEqual(usuario.read_text(encoding="utf-8"), '{"env": {"U": "1"}}')

    def test_instalador_copiar_usa_python_do_path(self):
        with tempfile.TemporaryDirectory(prefix="grafo-inst4-") as t:
            proj = Path(t).resolve() / "p"
            proj.mkdir()
            git(proj, "init", "-q")
            p = subprocess.run([sys.executable, "-W", "error", str(INSTALADOR), "--projeto", str(proj), "--aplicar", "--copiar"],
                               capture_output=True, text=True, encoding="utf-8", timeout=60)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertIn("--python python3", p.stderr)   # aviso
            s = json.loads((proj / ".claude" / "settings.json").read_text(encoding="utf-8"))
            cmds = [h["command"] for grupos in s["hooks"].values() for g in grupos for h in g["hooks"]]
            self.assertTrue(cmds and all(c.startswith('python "$CLAUDE_PROJECT_DIR/') for c in cmds), cmds)
            self.assertFalse(any(Path(sys.executable).as_posix() in c for c in cmds))

    def test_nome_e_status_nao_texto_no_index(self):
        repo = montar_repo(self.tmp / "repo_escalar")
        y = repo / "docs" / "grafo.yaml"
        texto = y.read_text(encoding="utf-8")
        i = texto.index("id: sys.core")
        j = texto.index("\n", texto.index("name:", i))
        k = texto.index("status:", i)
        k2 = texto.index("\n", k)
        texto = texto[:texto.index("name:", i)] + "name: 2024" + texto[j:k] + "status: true" + texto[k2:]
        y.write_text(texto, encoding="utf-8")
        saida = self.tmp / "idx_escalar"
        codigo, _ = cli("index", "--raiz", repo, "--saida", saida)
        self.assertEqual(codigo, 0)
        idx = json.loads((saida / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(idx["sistemas"]["sys.core"]["nome"], "2024")
        self.assertIsInstance(idx["sistemas"]["sys.core"]["status"], str)
        codigo, saida_v = cli("validate", "--raiz", repo, "--json")
        self.assertIn(codigo, (0, 1))
        json.loads(saida_v)

    def test_include_fora_da_raiz_nao_e_lido(self):
        repo = montar_repo(self.tmp / "repo_incl")
        fora = self.tmp / "fora_SYSTEMS.yaml"
        fora.write_text("systems:\n  - id: sys.intruso\n    name: X\n", encoding="utf-8")
        y = repo / "docs" / "grafo.yaml"
        rel = os.path.relpath(fora, y.parent).replace("\\", "/")
        y.write_text(y.read_text(encoding="utf-8") + f"includes:\n  systems: {rel}\n", encoding="utf-8")
        g = grafo.Projeto(repo).grafo()
        self.assertNotIn("sys.intruso", g.sistemas)
        self.assertTrue(any("fora do projeto" in p for p in g.problemas), g.problemas)

    def test_index_igual_com_e_sem_pyyaml(self):
        saidas = []
        for extra in ({}, {"GRAFO_SEM_PYYAML": "1"}):
            d = self.tmp / f"idx_py_{len(saidas)}"
            subprocess.run([sys.executable, "-W", "error", str(RAIZ_FERRAMENTA / "grafo.py"), "index", "--raiz",
                            str(self.raiz), "--saida", str(d)], capture_output=True, timeout=120,
                           env={**os.environ, "PYTHONUTF8": "1", **extra})
            saidas.append(((d / "index.json").read_bytes(), (d / "resumo.txt").read_bytes()))
        self.assertEqual(saidas[0], saidas[1])

    # ---------------- bugs conhecidos (relatório do verificador)
    def test_bug_base_com_hifen_vira_opcao_do_git(self):
        alvo = self.tmp / "injetado.txt"
        cli("validate", "--raiz", self.raiz, f"--base=--output={alvo}")
        self.assertFalse(alvo.exists(), "git diff recebeu --output como ref e gravou um arquivo")

    def test_bug_modulo_de_terceiros_homonimo(self):
        repo = montar_repo(self.tmp / "repo_homonimo",
                           {**ARQUIVOS, "tools/yaml.py": "x = 1\n", "app/core/cfg.py": "import yaml\n"})
        proj = grafo.Projeto(repo)
        an = grafo.Analise(proj, proj.grafo())
        self.assertNotIn(("app/core/cfg.py", "tools/yaml.py"), [(o, d) for o, d, _, _ in an.arestas_arquivo])

    def test_bug_referencia_em_comentario_de_script(self):
        refs = grafo.extrair_refs("tools/run.ps1", "# quem chama e o Validate-WP.ps1\nthrow 'rode build.py'\n")
        self.assertEqual(refs, [])

    def test_bug_base_nao_ve_caminho_apagado(self):
        repo = montar_repo(self.tmp / "repo_apagado")
        (repo / "app" / "core" / "especial.py").unlink()
        _, saida = cli("validate", "--raiz", repo, "--base", "HEAD", "--json")
        self.assertTrue(any("especial.py" in e["msg"] for e in json.loads(saida)["erros"]))

    def test_bug_cache_do_hook_ignora_configuracao(self):
        repo = montar_repo(self.tmp / "repo_cache")
        novo = repo / "app" / "gerado" / "a.py"
        novo.parent.mkdir()
        novo.write_text("x = 1\n", encoding="utf-8")
        ent = {"session_id": "c1", "cwd": str(repo), "tool_input": {"file_path": str(novo)}}
        rodar_hook("post", ent, env_extra=self.env())                      # aquece o cache do modelo
        (repo / "grafo.json").write_text('{"ignorar": ["app/gerado"]}', encoding="utf-8")
        _, out, _ = rodar_hook("post", {**ent, "session_id": "c2"}, env_extra=self.env())
        self.assertEqual(out, "", "arquivo ignorado pela configuração continua avisado (cache velho)")

    def test_bug_enum_lista_derruba_validate(self):
        repo = montar_repo(self.tmp / "repo_enum")
        y = repo / "docs" / "grafo.yaml"
        y.write_text(y.read_text(encoding="utf-8").replace("layer: dominio\n    status: active\n    summary",
                                                           "layer: [dominio]\n    status: [active]\n    summary", 1),
                     encoding="utf-8")
        codigo, _ = cli("validate", "--raiz", repo)
        self.assertEqual(codigo, 1)


# ============================================================================================================ fumaça
@unittest.skipUnless(BASE_EXEMPLO and (BASE_EXEMPLO / "docs" / "ARCHITECTURE_GRAPH.yaml").is_file(),
                     "sem GRAFO_BASE_EXEMPLO (raiz de um projeto seu com docs/ARCHITECTURE_GRAPH.yaml)")
class TesteFumacaProjeto(unittest.TestCase):
    """Fumaça opcional contra um projeto de verdade: o validate roda até o fim, sem erro de leitura/esquema, e o resumo é pequeno."""

    def test_validate_roda(self):
        codigo, saida = cli("validate", "--raiz", BASE_EXEMPLO, "--json")
        r = json.loads(saida)
        self.assertIn(codigo, (0, 1))
        self.assertFalse([e for e in r["erros"] if e["codigo"] in ("leitura", "esquema")])

    def test_resumo_pequeno(self):
        g = grafo.Projeto(BASE_EXEMPLO).grafo()
        self.assertLess(grafo.tokens_aprox(grafo.montar_resumo(g)), 4000)


if __name__ == "__main__":
    unittest.main(verbosity=2)
