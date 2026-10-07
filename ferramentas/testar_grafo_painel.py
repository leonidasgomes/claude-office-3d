"""Teste do painel 🗺️ Arquitetura no servidor: grafo_painel.py (cópia só leitura da base + grafo.py) e GET /grafo.

Uso: python -W error ferramentas/testar_grafo_painel.py
Repositório git temporário com um grafo pequeno (camada violada no código de propósito), arquivo binário, arquivo grande,
pasta não citada pelo grafo e uma ref `origin/main`. Saída em pasta temporária; HTTP em porta aleatória.
Não toca no seu projeto nem em dados/. Cobre também o bloco "grafo" do config (configuracao.normalizar_grafo), o
`arquivo` configurado, o grafo.json do projeto, a ref inválida e o painel sem grafo (`sem_grafo` + como criar).
"""
import json
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
import configuracao  # noqa: E402
import grafo_painel as gp  # noqa: E402

feitos, falhas = [], []
REF = "origin/main"


def checar(nome, cond, info=""):
    if cond:
        feitos.append(nome)
        print("  ok:", nome)
    else:
        falhas.append(nome)
        print("  FALHOU:", nome, str(info)[:400])


GRAFO = """\
schema_version: 1
project: Painel
updated: 2026-10-01
layers:
  base: {description: Núcleo, may_depend_on: []}
  app: {description: Aplicação, may_depend_on: [base]}
coverage:
  roots: [src]
  extensions: [.py]
  ignore: []
systems:
  - id: sys.core
    name: Núcleo
    layer: base
    status: active
    summary: Modelo e utilidades.
    description: Modelo e utilidades.
    paths: [src/core]
    depends_on: []
  - id: sys.app
    name: Aplicação
    layer: app
    status: active
    summary: Telas.
    description: Telas.
    paths: [src/app]
    depends_on: [sys.core]
tests:
  - id: test.core
    name: Testes do núcleo
    kind: python
    paths: [tests/test_core.py]
    covers: [sys.core]
    command: python -m pytest tests
"""

ARQUIVOS = {
    "docs/ARCHITECTURE_GRAPH.yaml": GRAFO,
    "src/core/__init__.py": "",
    "src/core/modelo.py": "from src.app import tela\n\ndef salvar():\n    return tela.mostrar()\n",   # base -> app: camada violada
    "src/app/__init__.py": "",
    "src/app/tela.py": "from src.core import modelo\n\ndef mostrar():\n    return 1\n",
    "src/core/grande.py": "# " + "x" * 400 + "\n",
    "tests/test_core.py": "def test_ok():\n    assert True\n",
    "outro/segredo.py": "SENHA = 'nao copiar'\n",
}


def git(repo, *args):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        raise RuntimeError(r.stderr)
    return r.stdout.strip()


def criar_repo(tmp):
    repo = Path(tmp) / "projeto"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "t@t")
    git(repo, "config", "user.name", "t")
    git(repo, "config", "core.autocrlf", "false")
    for rel, texto in ARQUIVOS.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(texto, encoding="utf-8", newline="\n")
    (repo / "src" / "core" / "logo.py").write_bytes(b"\x89PNG\0\0binario")   # extensão de texto, conteúdo binário
    (repo / "src" / "core" / "foto.png").write_bytes(b"\x89PNG\0\0")
    commitar(repo, "inicial")
    return repo


def commitar(repo, msg):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg)
    git(repo, "update-ref", "refs/remotes/" + REF, "HEAD")
    return git(repo, "rev-parse", "HEAD")


def zerar_estado():
    gp._estado.update(dados=None, erro="", atualizando=False, tentativa=0.0, sem_grafo=False)


def main():
    guardar = gp.MAX_ARQ
    with tempfile.TemporaryDirectory() as tmp:
        repo = criar_repo(tmp)
        saida = Path(tmp) / "saida"
        gp.MAX_ARQ = 200
        try:
            print("caminho_seguro")
            checar("aceita caminho normal", gp.caminho_seguro("Projeto/Source/Modulo/A.cpp"))
            for ruim in ["../x", "a/../b", "/abs", "C:/x", "a\\b", "a/CON.txt", "a/nul", "a/b ", "a/b.", "a//b", "a/\x01b", "x:ads"]:
                checar(f"recusa {ruim!r}", not gp.caminho_seguro(ruim))

            print("escolher (o que vai para a base)")
            itens = gp.arvore(repo, REF)
            grafo, selec, yamls = gp.escolher(itens, repo, REF)
            nomes = [c for c, _, _ in selec]
            checar("acha docs/ARCHITECTURE_GRAPH.yaml", grafo == "docs/ARCHITECTURE_GRAPH.yaml")
            checar("leva a cobertura (src) e o caminho do teste", {"src/core/modelo.py", "src/app/tela.py", "tests/test_core.py"} <= set(nomes), nomes)
            checar("não leva pasta que o grafo não cita", "outro/segredo.py" not in nomes, nomes)
            checar("o YAML do grafo vem primeiro", nomes[0] == grafo and grafo in yamls, nomes[:3])

            print("atualizar (base + grafo.py index/validate/drift)")
            commit = git(repo, "rev-parse", "HEAD")
            est = gp.atualizar(repo, REF, saida)
            base = saida / "base"
            checar("estado com commit, ref e sem erro", est["commit"] == commit and est["ref"] == REF and est["erro"] == "", est)
            checar("conteúdo copiado", (base / "src/core/modelo.py").read_text(encoding="utf-8") == ARQUIVOS["src/core/modelo.py"])
            checar("arquivo grande vira vazio (existe para o validate)", (base / "src/core/grande.py").exists()
                   and (base / "src/core/grande.py").stat().st_size == 0)
            checar("binário com extensão da cobertura vira vazio (pelo NUL)", (base / "src/core/logo.py").stat().st_size == 0)
            checar("binário fora das extensões da cobertura e não citado não é escrito", not (base / "src/core/foto.png").exists())
            checar("pasta não citada fica fora da base", not (base / "outro").exists())
            checar("estatísticas da extração", est["extraido"]["vazios"] >= 2 and est["extraido"]["arquivos"] >= 4 and not est["extraido"]["cortado"],
                   est["extraido"])
            idx = json.loads((saida / "index.json").read_text(encoding="utf-8"))
            checar("index.json com os 2 sistemas, camadas e arquivos", set(idx["sistemas"]) == {"sys.core", "sys.app"}
                   and set(idx["camadas"]) == {"base", "app"} and idx["arquivos"].get("src/app/tela.py") == "sys.app", list(idx["sistemas"]))
            checar("resumo.txt gerado", (saida / "resumo.txt").exists())
            erros = {e["codigo"] for e in est["validacao"]["erros"]}
            checar("validate acha a camada violada e o ciclo real", {"camada_real", "ciclo_real"} <= erros and not est["validacao"]["ok"], est["validacao"])
            checar("drift com arestas reais e não declaradas", est["drift"]["arestas_reais"] >= 2 and est["drift"]["arestas_nao_declaradas"] >= 1, est["drift"])
            checar("estado.json gravado", gp.ler_estado(saida)["commit"] == commit)
            checar("sem sobra de base.novo/base.velho/novo", not any((saida / n).exists() for n in ("base.novo", "base.velho", "novo")))

            print("mesmo commit não refaz; forcar refaz; commit novo atualiza")
            (base / "marca.txt").write_text("x", encoding="utf-8")
            est2 = gp.atualizar(repo, REF, saida)
            checar("mesmo commit: devolve o estado anterior sem extrair de novo", est2["ts"] == est["ts"] and (base / "marca.txt").exists())
            gp.atualizar(repo, REF, saida, forcar=True)
            checar("forcar: base substituída por inteiro", not (base / "marca.txt").exists())
            (repo / "src" / "app" / "nova.py").write_text("X = 1\n", encoding="utf-8")
            commit2 = commitar(repo, "nova tela")
            est3 = gp.atualizar(repo, REF, saida)
            idx = json.loads((saida / "index.json").read_text(encoding="utf-8"))
            checar("commit novo: base e index atualizados", est3["commit"] == commit2 and idx["arquivos"].get("src/app/nova.py") == "sys.app")

            print("falhas mantêm o último resultado")
            zerar_estado()
            checar("rodada boa", gp.rodada(repo, REF, saida) is True and gp._estado["erro"] == "")
            checar("ref inexistente: rodada falha", gp.rodada(repo, "origin/nao-existe", saida) is False and "git rev-parse" in gp._estado["erro"],
                   gp._estado["erro"])
            r = gp.resposta(saida)
            checar("resposta mantém o index anterior e mostra o erro", r["index"] and r["commit"] == commit2 and r["erro"], r.get("erro"))
            (repo / "docs" / "ARCHITECTURE_GRAPH.yaml").write_text("schema_version: [1\n", encoding="utf-8")
            commitar(repo, "grafo quebrado")
            checar("grafo quebrado: rodada falha", gp.rodada(repo, REF, saida) is False and "grafo.py" in gp._estado["erro"], gp._estado["erro"])
            idx = json.loads((saida / "index.json").read_text(encoding="utf-8"))
            checar("grafo quebrado: index.json anterior intacto", "src/app/nova.py" in idx["arquivos"])
            checar("grafo quebrado: estado.json anterior intacto", gp.ler_estado(saida)["commit"] == commit2)
            checar("grafo quebrado: base anterior intacta (o grafo roda em base.novo)", (saida / "base" / "src/app/nova.py").exists()
                   and not (saida / "base.novo").exists())
            checar("mesmo commit que falhou: não repete a extração", gp.rodada(repo, REF, saida) is False and "já falhou" in gp._estado["erro"],
                   gp._estado["erro"])
            falha = json.loads((saida / "falha.json").read_text(encoding="utf-8"))
            falha["ts"] -= gp.FALHA_VALIDADE + 1
            (saida / "falha.json").write_text(json.dumps(falha), encoding="utf-8")
            checar("falha registrada expira (6 h): tenta de novo", gp.rodada(repo, REF, saida) is False and "YAML inválido" in gp._estado["erro"],
                   gp._estado["erro"])
            guardar_versao = gp._versao
            gp._versao = lambda: "outra-versao"
            try:
                checar("grafo.py/grafo_painel.py mudou: a falha registrada não vale", gp.rodada(repo, REF, saida) is False
                       and "YAML inválido" in gp._estado["erro"], gp._estado["erro"])
            finally:
                gp._versao = guardar_versao
            testar_transitoria(Path(tmp))
            git(repo, "rm", "-q", "docs/ARCHITECTURE_GRAPH.yaml")
            commitar(repo, "sem grafo")
            checar("sem grafo na ref: rodada falha com mensagem clara", gp.rodada(repo, REF, saida) is False and "grafo não encontrado" in gp._estado["erro"],
                   gp._estado["erro"])
            r = gp.resposta(saida, raiz="C:\\proj\\")
            checar("sem grafo: resposta com sem_grafo, como criar (grafo.py init) e raiz normalizada", r["sem_grafo"] is True
                   and "grafo.py init" in r["como_criar"] and r["raiz"] == "C:/proj" and r["ativo"] is True, r)
            zerar_estado()
            checar("sem grafo: vale também depois de reiniciar (falha.json)", gp.resposta(saida)["sem_grafo"] is True)
            checar("mesmo commit sem grafo: não refaz e continua sem_grafo", gp.rodada(repo, REF, saida) is False
                   and gp._estado.get("sem_grafo") is True, gp._estado)
            r = gp.resposta(saida, ativo=False)
            checar("grafo.ativo false: resposta ativo=False sem index", r["ativo"] is False and r["index"] is None and not r["erro"], r)
            checar("sem projeto configurado: rodada falha com mensagem", gp.rodada("", REF, saida) is False
                   and "projetos" in gp._estado["erro"], gp._estado["erro"])
            for ruim in ["-x", "a b", "a..b", "a:b", "a^", "a/", ""]:
                checar(f"ref inválida {ruim!r}: não chama o git", gp.rodada(repo, ruim or None, saida) is False if ruim else gp.ref_valida(ruim) is False,
                       gp._estado["erro"])
            testar_arquivo_config(Path(tmp))
            testar_cfg_atual(repo, saida)
            testar_yaml_grande(Path(tmp))
            vazio = Path(tmp) / "vazio"
            zerar_estado()
            r = gp.resposta(vazio)
            checar("antes da 1ª rodada: index nulo e erro explicando", r["index"] is None and r["erro"] == "grafo ainda não gerado", r)
            gp._estado["atualizando"] = True
            checar("rodada em andamento não começa outra", gp.rodada(repo, REF, saida) is False)
            gp._estado["atualizando"] = False

            print("nomes perigosos e palavras soltas no grafo")
            testar_nomes(Path(tmp))
            testar_palavra_solta(Path(tmp))

            print("GET /grafo (servidor em porta aleatória)")
            testar_http(saida)
            testar_concorrencia(repo, saida)
        finally:
            gp.MAX_ARQ = guardar
            zerar_estado()
    print(f"\n{len(feitos)} ok, {len(falhas)} falha(s)")
    return 1 if falhas else 0


def arvore_crua(repo, entradas):
    """Árvore montada com hash-object + mktree (sem checkout): permite nomes que o Windows não cria. entradas: {caminho: bytes}."""
    def cru(*args, entrada=None):
        r = subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args], input=entrada,
                           capture_output=True)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.decode("utf-8", "replace"))
        return r.stdout.decode().strip()

    def montar(d):
        linhas = []
        for nome, v in sorted(d.items()):
            if isinstance(v, dict):
                linhas.append(f"040000 tree {montar(v)}{chr(9)}{nome}")
            else:
                linhas.append(f"100644 blob {cru('hash-object', '-w', '--stdin', entrada=v)}{chr(9)}{nome}")
        return cru("mktree", entrada=("".join(x + chr(10) for x in linhas)).encode("utf-8"))

    raiz = {}
    for c, v in entradas.items():
        d = raiz
        partes = c.split("/")
        for p in partes[:-1]:
            d = d.setdefault(p, {})
        d[partes[-1]] = v
    commit = cru("commit-tree", montar(raiz), "-m", "cru")
    cru("update-ref", "refs/remotes/" + REF, commit)
    return commit


def testar_nomes(tmp):
    repo = tmp / "nomes"
    repo.mkdir()
    git(repo, "init", "-q")
    grafo = GRAFO.encode("utf-8")
    base = {"docs/ARCHITECTURE_GRAPH.yaml": grafo, "src/core/modelo.py": b"X = 1\n", "src/app/tela.py": b"Y = 2\n",
            "tests/test_core.py": b"def test_ok():\n    assert True\n"}
    for ruim in ["CON.py", "..", "nul.txt", "a<b.py", "a|b.py", "a?b.py", 'a"b.py', "a*b.py"]:
        try:
            arvore_crua(repo, {**base, "src/core/" + ruim: b"Z = 3\n"})
        except RuntimeError as e:
            print(f"  (git recusou o nome {ruim!r}: {str(e)[:60]})")
            continue
        destino = tmp / "saida_nomes" / "base"
        try:
            st = gp.extrair(repo, REF, destino)
            ok = (destino / "src/core/modelo.py").exists() and st["selecionados"] >= 4
            checar(f"nome perigoso {ruim!r} na árvore: ignorado sem derrubar a extração", ok, st)
        except Exception as e:
            checar(f"nome perigoso {ruim!r} na árvore: ignorado sem derrubar a extração", False, f"{type(e).__name__}: {e}")
        finally:
            shutil.rmtree(tmp / "saida_nomes", ignore_errors=True)


def testar_transitoria(tmp):
    """Falha transitória (timeout do grafo.py, arquivo preso) não grava falha.json: a rodada seguinte tenta e dá certo."""
    repo2 = tmp / "transitoria"
    repo2.mkdir()
    git(repo2, "init", "-q")
    arvore_crua(repo2, {"docs/ARCHITECTURE_GRAPH.yaml": GRAFO.encode("utf-8"), "src/core/modelo.py": b"X = 1\n",
                        "src/app/tela.py": b"Y = 2\n", "tests/test_core.py": b"def test_ok():\n    assert True\n"})
    saida2 = tmp / "saida_transitoria"
    orig, n = gp._rodar, {"c": 0}

    def falso(args, timeout=gp.TIMEOUT_GRAFO):
        n["c"] += 1
        if n["c"] == 1:
            raise subprocess.TimeoutExpired("grafo.py", timeout)
        return orig(args, timeout)
    gp._rodar = falso
    try:
        primeira = gp.rodada(repo2, REF, saida2)
        checar("transitória (timeout): rodada falha sem gravar falha.json", primeira is False and not (saida2 / "falha.json").exists(),
               gp._estado["erro"])
        checar("transitória: a rodada seguinte tenta de novo e dá certo", gp.rodada(repo2, REF, saida2) is True, gp._estado["erro"])
        def preso(*a, **k):
            raise PermissionError(5, "Acesso negado")
        guardar = gp.extrair
        gp.extrair = preso
        try:
            checar("transitória (arquivo preso): não grava falha.json", gp.rodada(repo2, REF, saida2, forcar=True) is False
                   and not (saida2 / "falha.json").exists())
        finally:
            gp.extrair = guardar
    finally:
        gp._rodar = orig


def testar_arquivo_config(tmp):
    """grafo.arquivo do config e a chave "grafo" do grafo.json do projeto escolhem o YAML; arquivo configurado ausente = sem grafo."""
    repo = tmp / "arquivo_cfg"
    repo.mkdir()
    git(repo, "init", "-q")
    base = {"arq/meu_grafo.yaml": GRAFO.encode("utf-8"), "src/core/modelo.py": b"X = 1\n", "src/app/tela.py": b"Y = 2\n",
            "tests/test_core.py": b"def test_ok():\n    assert True\n"}
    arvore_crua(repo, base)
    itens = gp.arvore(repo, REF)
    checar("arquivo configurado: usa o YAML apontado", gp.escolher(itens, repo, REF, "arq/meu_grafo.yaml")[0] == "arq/meu_grafo.yaml")
    try:
        gp.escolher(itens, repo, REF, "docs/nao_tem.yaml")
        ok = False
    except gp.SemGrafo as e:
        ok = "docs/nao_tem.yaml" in str(e)
    checar("arquivo configurado ausente: SemGrafo citando o arquivo", ok)
    try:
        gp.escolher(itens, repo, REF)
        ok = False
    except gp.SemGrafo:
        ok = True
    checar("sem arquivo e sem nome padrão: SemGrafo", ok)
    arvore_crua(repo, {**base, "grafo.json": b'{"grafo": "arq/meu_grafo.yaml"}'})
    checar("grafo.json do projeto aponta o YAML (auto-descoberta)", gp.escolher(gp.arvore(repo, REF), repo, REF)[0] == "arq/meu_grafo.yaml")
    saida = tmp / "saida_arquivo_cfg"
    est = gp.atualizar(repo, REF, saida, arquivo="arq/meu_grafo.yaml")
    checar("atualizar com o arquivo configurado gera o index", est["extraido"]["grafo"] == "arq/meu_grafo.yaml"
           and (saida / "index.json").exists(), est.get("extraido"))
    est2 = gp.atualizar(repo, REF, saida)
    checar("mudar o arquivo no config refaz (mesmo commit)", est2["ts"] >= est["ts"] and est2["cfg"] != est["cfg"])

    print("configuracao.normalizar_grafo")
    n = configuracao.normalizar_grafo
    checar("padrão: ativo, origin/main, procurar, 60 min", n(None) == {"ativo": True, "ref": "origin/main", "arquivo": "", "intervalo_min": 60})
    checar("valores válidos", n({"ativo": False, "ref": "origin/dev", "arquivo": "./docs\\g.yaml", "intervalo_min": 2})
           == {"ativo": False, "ref": "origin/dev", "arquivo": "docs/g.yaml", "intervalo_min": 5})
    checar("ref e arquivo inválidos voltam ao padrão", n({"ref": "-x", "arquivo": "../fora.yaml"}) == n(None)
           and n({"ref": "a b", "arquivo": "C:/x.yaml"}) == n(None) and n({"arquivo": "/abs.yaml", "ativo": "sim"}) == n(None))
    checar("config.exemplo.json tem o bloco grafo", "grafo" in __import__("json").loads((RAIZ / "config.exemplo.json").read_text(encoding="utf-8")))


def testar_cfg_atual(repo, saida):
    """O index só é servido para a configuração com que foi gerado (projeto|ref|arquivo); outra configuração: index null."""
    est = gp.ler_estado(saida)
    zerar_estado()
    r = gp.resposta(saida, raiz=est["repo"], ref=est["ref"], arquivo="")
    checar("config atual = a do index: index servido", r["index"] is not None, r.get("erro"))
    for nome, kw in (("ref", dict(raiz=est["repo"], ref="origin/outra")), ("arquivo", dict(raiz=est["repo"], ref=est["ref"], arquivo="x/g.yaml")),
                     ("projeto", dict(raiz=str(Path(est["repo"]).parent / "outro"), ref=est["ref"]))):
        r = gp.resposta(saida, **kw)
        checar(f"{nome} mudou no config: index null e aviso de geração", r["index"] is None and r["erro"] and not r.get("commit"), r)
    checar("sem ref (chamada antiga): serve o último index", gp.resposta(saida)["index"] is not None)


def testar_yaml_grande(tmp):
    """YAML do grafo acima de MAX_YAML_BYTES: falha determinística, sem ler para a memória."""
    guardar = gp.MAX_YAML_BYTES
    gp.MAX_YAML_BYTES = 1000
    repo = tmp / "yaml_grande"
    repo.mkdir()
    git(repo, "init", "-q")
    arvore_crua(repo, {"docs/ARCHITECTURE_GRAPH.yaml": GRAFO.encode("utf-8") + b"#" * (gp.MAX_YAML_BYTES + 10) + b"\n",
                       "src/core/modelo.py": b"X = 1\n"})
    try:
        gp.escolher(gp.arvore(repo, REF), repo, REF)
        ok = False
    except gp.FalhaDeterministica as e:
        ok = "grande demais" in str(e)
    finally:
        gp.MAX_YAML_BYTES = guardar
    checar("YAML do grafo grande demais: falha determinística", ok)


def testar_palavra_solta(tmp):
    """Palavra comum no texto do grafo (summary: 'outro') que coincide com uma pasta não pode puxar a pasta inteira."""
    repo = tmp / "palavra"
    repo.mkdir()
    git(repo, "init", "-q")
    grafo = GRAFO.replace("summary: Telas.", "summary: Telas de um outro modulo.").encode("utf-8")
    arvore_crua(repo, {"docs/ARCHITECTURE_GRAPH.yaml": grafo, "src/core/modelo.py": b"X = 1\n", "src/app/tela.py": b"Y = 2\n",
                       "tests/test_core.py": b"def test_ok():\n    assert True\n",
                       **{f"outro/arq{i}.uasset": b"\x00bin" for i in range(5)}})
    _, selec, _ = gp.escolher(gp.arvore(repo, REF), repo, REF)
    nomes = [c for c, _, _ in selec]
    checar("palavra solta no summary ('outro') não puxa a pasta inteira", not any(c.startswith("outro/") for c in nomes), nomes)


def testar_concorrencia(repo, saida):
    """GET /grafo (resposta) lido sem parar enquanto uma rodada forçada troca base/index: sempre JSON com index ou erro claro."""
    zerar_estado()
    ruins, fim = [], threading.Event()

    def ler():
        while not fim.is_set():
            try:
                r = gp.resposta(saida)
                json.dumps(r, ensure_ascii=False)
                if not r.get("index") and not r.get("erro"):
                    ruins.append("sem index e sem erro")
            except Exception as e:   # noqa: BLE001
                ruins.append(f"{type(e).__name__}: {e}")
    leitores = [threading.Thread(target=ler, daemon=True) for _ in range(3)]
    for t in leitores:
        t.start()
    try:
        git(repo, "checkout", "-q", "HEAD~2", "--", "docs/ARCHITECTURE_GRAPH.yaml")   # grafo bom de volta (antes de quebrar/apagar)
        commitar(repo, "grafo de volta")
        ok = gp.rodada(repo, REF, saida, forcar=True)
    finally:
        fim.set()
        for t in leitores:
            t.join(10)
    checar("rodada com GET /grafo lendo ao mesmo tempo: rodada ok (sem WinError 5 no os.replace)", ok, gp._estado["erro"])
    checar("leituras concorrentes sempre válidas", not ruins, ruins[:3])
    zerar_estado()


def testar_http(saida):
    import http.client
    from functools import partial
    from http.server import ThreadingHTTPServer
    import rede
    import servidor
    guardar = gp.SAIDA, servidor.Handler.rede, servidor.opcoes_grafo
    srv = None
    with tempfile.TemporaryDirectory() as pasta:
        try:
            gp.SAIDA = saida
            repo_atual = (gp.ler_estado(saida) or {}).get("repo", "")
            servidor.opcoes_grafo = lambda: {"ativo": True, "repo": repo_atual, "ref": REF, "arquivo": "", "intervalo_min": 60}
            zerar_estado()
            r = rede.Rede(Path(pasta), False, False)
            r.arq_acoes = Path(pasta) / "acoes.jsonl"
            servidor.Handler.rede = r
            srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(servidor.Handler, directory=str(pasta)))
            porta = srv.server_address[1]
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            con = http.client.HTTPConnection("127.0.0.1", porta, timeout=20)
            con.request("GET", "/grafo", headers={"Host": f"127.0.0.1:{porta}"})
            resp = con.getresponse()
            corpo = resp.read()
            con.close()
            d = json.loads(corpo) if resp.status == 200 else {}
            checar("HTTP 200 com index, drift, validação e commit", resp.status == 200 and d.get("index") and "drift" in d and "validacao" in d
                   and d.get("commit"), (resp.status, corpo[:300]))
            checar("HTTP: JSON", resp.getheader("Content-Type", "").startswith("application/json"))
            base = Path(pasta) / "dados" / "grafo" / "base" / "src"
            base.mkdir(parents=True)
            (base / "fonte.cpp").write_text("CODIGO DO PROJETO", encoding="utf-8")
            for caminho in ["/dados/grafo/base/src/fonte.cpp", "/%64ados/grafo/base/src/fonte.cpp", "/x/../dados/grafo/base/src/fonte.cpp",
                            "/%2e/dados/grafo/base/src/fonte.cpp"]:
                con = http.client.HTTPConnection("127.0.0.1", porta, timeout=20)
                con.request("GET", caminho, headers={"Host": f"127.0.0.1:{porta}"})
                resp = con.getresponse()
                corpo = resp.read()
                con.close()
                checar(f"HTTP: cópia da base não é servida ({caminho})", resp.status == 404 and b"CODIGO" not in corpo, resp.status)
        finally:
            if srv is not None:
                srv.shutdown()
                srv.server_close()
            gp.SAIDA, servidor.Handler.rede, servidor.opcoes_grafo = guardar


if __name__ == "__main__":
    sys.exit(main())
