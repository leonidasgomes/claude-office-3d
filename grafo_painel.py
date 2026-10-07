"""Painel 🗺️ Arquitetura: base do projeto (só leitura) + grafo/grafo.py (index, validate, drift) para o GET /grafo.

Configuração (bloco "grafo" do config.json, configuracao.normalizar_grafo): `ativo`, `ref` (padrão origin/main), `arquivo`
(caminho do YAML do grafo no repositório; vazio = procurar: o "grafo" do grafo.json do projeto, senão os nomes padrão do
grafo.py) e `intervalo_min` (padrão 60). O projeto é a 1ª pasta de "projetos". Sem grafo no projeto, o GET /grafo diz como
criar um (`python grafo/grafo.py init`) e nada quebra.

O servidor chama `laco(parar, opcoes)` numa thread: na partida e a cada `intervalo_min`, sem bloquear as requisições,
1. lê a árvore de `ref` do repositório do projeto com `git ls-tree` (nunca escreve no repositório);
2. acha o grafo (o `arquivo` configurado, o do grafo.json ou os nomes padrão) e lê, no YAML do grafo e nos `includes`,
   só as chaves ESTRUTURAIS de caminho (coverage.roots e extensions, paths, path, roots, patterns, docs, includes);
3. monta a base em dados/grafo/base.novo/ com `git cat-file --batch` (sem `git archive`: a lista não cabe na linha de comando
   do Windows): os YAML do grafo, os arquivos de texto da cobertura (roots x extensions) e os arquivos citados um a um (texto
   até MAX_ARQ e MAX_TOTAL; binário ou grande vira arquivo vazio, só para o caminho existir). Pasta citada vira só a pasta
   (mkdir, sem arquivos); padrão com * citado fora da cobertura ganha um arquivo vazio que casa com ele (marcador);
4. roda `grafo.py index`, `validate --json` e `drift --json` sobre base.novo e, só se tudo deu certo, troca base.novo -> base,
   index.json/resumo.txt e estado.json. O índice e o estado ficam em memória (o GET /grafo não lê o disco a cada pedido).
Mesmo commit da última rodada boa: não refaz. Falha DETERMINÍSTICA (YAML inválido, grafo não encontrado, grafo.py saindo com
erro) fica em falha.json e não repete a extração para o mesmo commit e a mesma versão do grafo.py/grafo_painel.py por até
FALHA_VALIDADE (6 h); falha transitória (tempo esgotado, arquivo preso, disco, git) tenta de novo na próxima rodada.
Qualquer falha mantém o último resultado e preenche `erro`.
"""
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

PASTA = Path(__file__).resolve().parent
GRAFO_PY = PASTA / "grafo" / "grafo.py"
SAIDA = PASTA / "dados" / "grafo"
REPO = None                  # 1ª pasta de "projetos" (vem das opções do servidor)
REF = "origin/main"          # padrão de grafo.ref
INTERVALO = 3600
MAX_ARQ = 1_000_000          # bytes por arquivo copiado com conteúdo
MAX_TOTAL = 80_000_000       # bytes copiados com conteúdo por rodada
MAX_ARQUIVOS = 40_000        # arquivos escritos (com conteúdo ou vazios)
MAX_YAML = 30                # YAML do grafo lidos (o grafo e os includes)
MAX_YAML_BYTES = MAX_ARQ * 10   # teto de cada YAML do grafo (acima disso: falha determinística, não lê para a memória)
TIMEOUT_GRAFO = 600
TIMEOUT_BLOBS = 300          # s para o git cat-file --batch inteiro
GRAFOS_PADRAO = ["docs/ARCHITECTURE_GRAPH.yaml", "ARCHITECTURE_GRAPH.yaml", "docs/grafo.yaml", "grafo.yaml", ".grafo.yaml",
                 "docs/architecture.yaml", "architecture.yaml"]   # os mesmos do grafo.py (GRAFOS_PADRAO)
CONFIGS_GRAFO = ["grafo.json", ".grafo.json"]   # configuração do grafo.py no projeto: a chave "grafo" aponta o YAML
COMO_CRIAR = ("sem grafo de arquitetura no projeto: crie um com `python grafo/grafo.py init --raiz <projeto> --saida "
              "docs/ARCHITECTURE_GRAPH.yaml`, revise, faça commit e push para a ref configurada (grafo.ref), ou aponte "
              "grafo.arquivo no config.json")
EXT_TEXTO = {".h", ".hh", ".hpp", ".c", ".cc", ".cpp", ".cxx", ".inl", ".cs", ".py", ".ps1", ".psm1", ".psd1", ".sh", ".bat",
             ".cmd", ".ini", ".md", ".yaml", ".yml", ".json", ".toml", ".txt", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cfg",
             ".uplugin", ".uproject"}
CHAVES_CAMINHO = {"paths", "path", "roots", "patterns", "docs"}   # chaves do formato do grafo que guardam caminhos
_RESERVADOS = {"con", "prn", "aux", "nul", "conin$", "conout$", *(f"com{i}" for i in range(10)), *(f"lpt{i}" for i in range(10))}
_INVALIDOS_WIN = set('<>:"|?*\\')
MAX_ITENS_VALIDACAO = 60
FALHA_VALIDADE = 6 * 3600     # s: falha determinística registrada vale até isso (depois tenta de novo)
_ENV_GIT_FORA = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
                 "GIT_COMMON_DIR", "GIT_NAMESPACE")

_estado = {"dados": None, "erro": "", "atualizando": False, "tentativa": 0.0}
_trava = threading.Lock()
_cache = {}   # str(saida) -> {"estado": dict, "index": dict}: o que o GET /grafo serve (atualizado só depois de uma rodada boa)
_mod_grafo = None


class FalhaDeterministica(RuntimeError):
    """Falha que se repete igual para o mesmo commit e a mesma versão das ferramentas (não adianta tentar de novo já)."""


class SemGrafo(FalhaDeterministica):
    """O projeto não tem grafo na ref (nem no `arquivo` configurado): o painel mostra como criar um."""


def _versao():
    """Assinatura do grafo.py e deste arquivo: mudou a ferramenta, a falha registrada deixa de valer."""
    import hashlib
    h = hashlib.sha1()
    for arq in (GRAFO_PY, Path(__file__)):
        try:
            h.update(arq.read_bytes())
        except OSError:
            h.update(b"?")
    return h.hexdigest()[:16]


def _env_git():
    """Ambiente sem GIT_DIR/GIT_WORK_TREE/GIT_INDEX_FILE herdados (um hook do Claude Code pode tê-los): o -C vale."""
    return {k: v for k, v in os.environ.items() if k not in _ENV_GIT_FORA}


def _git(repo, *args, entrada=None, timeout=120):
    r = subprocess.run(["git", "-C", str(repo), *args], input=entrada, capture_output=True, timeout=timeout, env=_env_git())
    if r.returncode != 0:
        raise RuntimeError(f"git {args[0]} falhou: {r.stderr.decode('utf-8', 'replace').strip()[:200]}")
    return r.stdout


def arvore(repo, ref):
    """[(caminho, sha, tamanho)] dos blobs de `ref` (git ls-tree -r -l -z), só leitura."""
    out = _git(repo, "ls-tree", "-r", "-l", "-z", ref)
    itens = []
    for bruto in out.split(b"\0"):
        if not bruto:
            continue
        meta, _, caminho = bruto.partition(b"\t")
        partes = meta.split()
        if len(partes) < 4 or partes[1] != b"blob":
            continue
        try:
            tam = int(partes[3])
        except ValueError:
            tam = 0
        itens.append((caminho.decode("utf-8", "replace"), partes[2].decode("ascii"), tam))
    return itens


def caminho_seguro(rel):
    """Caminho relativo que dá para criar no Windows: sem '..', absoluto, drive/ADS, <>:"|?*\\, controle, nome reservado,
    ponto ou espaço no fim do nome."""
    if not rel or rel.startswith("/") or any(ord(c) < 32 or c in _INVALIDOS_WIN for c in rel):
        return False
    for p in rel.split("/"):
        if p in ("", ".", "..") or p.split(".")[0].lower() in _RESERVADOS or p.endswith((" ", ".")):
            return False
    return True


def ler_blobs(repo, shas, timeout=TIMEOUT_BLOBS):
    """{sha: bytes} via um único `git cat-file --batch` (pedido e resposta um a um). Um vigia mata o processo se passar do
    tempo (a leitura não fica presa para sempre)."""
    saida = {}
    if not shas:
        return saida
    p = subprocess.Popen(["git", "-C", str(repo), "cat-file", "--batch"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, env=_env_git())
    vigia = threading.Timer(timeout, p.kill)
    vigia.daemon = True
    vigia.start()
    try:
        for sha in shas:
            p.stdin.write(sha.encode("ascii") + b"\n")
            p.stdin.flush()
            linha = p.stdout.readline()
            if not linha:
                raise RuntimeError("git cat-file parou de responder (tempo esgotado ou erro)")
            cab = linha.split()
            if len(cab) < 3 or cab[1] == b"missing":
                continue
            tam = int(cab[2])
            dados = p.stdout.read(tam)
            p.stdout.read(1)   # \n depois do conteúdo
            saida[sha] = dados
    finally:
        vigia.cancel()
        try:
            p.stdin.close()
        except OSError:
            pass
        try:
            p.wait(timeout=30)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait(timeout=10)
        p.stdout.close()
    return saida


def _grafo_mod():
    """grafo/grafo.py como módulo (só para ler YAML do mesmo jeito que ele lê)."""
    global _mod_grafo
    if _mod_grafo is None:
        spec = importlib.util.spec_from_file_location("grafo_ferramenta", GRAFO_PY)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _mod_grafo = mod
    return _mod_grafo


def _lista(v):
    return v if isinstance(v, list) else [v] if v is not None else []


def _caminhos(dados, saida):
    """Textos das chaves estruturais de caminho, em qualquer profundidade (sistemas, testes, fontes de dados, coverage...)."""
    if isinstance(dados, dict):
        for k, v in dados.items():
            if k in CHAVES_CAMINHO:
                saida.update(x for x in _lista(v) if isinstance(x, str))
            else:
                _caminhos(v, saida)
    elif isinstance(dados, list):
        for x in dados:
            _caminhos(x, saida)


def _norm(p):
    p = str(p).strip().replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p.rstrip("/")


def _glob_re(p):
    r = re.escape(p).replace(r"\*\*/", "\0").replace(r"\*\*", "\0").replace(r"\*", "[^/]*").replace(r"\?", "[^/]").replace("\0", ".*")
    return re.compile(r + r"(?:/.*)?\Z")   # casa o arquivo ou algo dentro da pasta que casa


class Escolha(set):
    """YAML lidos (o conjunto) + pastas a criar vazias e arquivos a escrever vazios (marcadores, binários, grandes)."""
    def __init__(self, *a):
        super().__init__(*a)
        self.pastas, self.vazios, self.cobertura = set(), set(), set()


def achar_grafo(por_caminho, repo, arquivo=""):
    """Caminho do YAML do grafo na árvore: o `arquivo` configurado; senão a chave "grafo" do grafo.json/.grafo.json do
    projeto; senão o 1º dos nomes padrão. None se não houver."""
    if arquivo:
        a = _norm(arquivo)
        return a if a in por_caminho else None
    for cj in CONFIGS_GRAFO:
        if cj in por_caminho:
            try:
                cfg = json.loads(ler_blobs(repo, [por_caminho[cj][1]]).get(por_caminho[cj][1], b"").decode("utf-8", "replace"))
            except ValueError:
                cfg = None
            g = _norm(cfg.get("grafo")) if isinstance(cfg, dict) and isinstance(cfg.get("grafo"), str) else ""
            if g and g in por_caminho:
                return g
    return next((g for g in GRAFOS_PADRAO if g in por_caminho), None)


def escolher(itens, repo, ref, arquivo=""):
    """(caminho do grafo, [(caminho, sha, tamanho)] a escrever, Escolha) — só o que as chaves estruturais do grafo citam."""
    por_caminho = {c: (c, s, t) for c, s, t in itens}
    grafo = achar_grafo(por_caminho, repo, arquivo)
    if not grafo:
        onde = arquivo or ", ".join(CONFIGS_GRAFO[:1] + GRAFOS_PADRAO[:2]) + "..."
        raise SemGrafo(f"grafo não encontrado em {ref} ({onde}); {COMO_CRIAR}")
    pastas_arvore = set()
    for c in por_caminho:
        d = c
        while "/" in d:
            d = d.rsplit("/", 1)[0]
            if d in pastas_arvore:
                break
            pastas_arvore.add(d)
    lidos = Escolha()
    citados, sis_paths, yamls, raizes, exts = set(), set(), [grafo], [], set()
    principal = None
    while yamls and len(lidos) < MAX_YAML:
        y = yamls.pop(0)
        if y in lidos or y not in por_caminho:
            continue
        lidos.add(y)
        if por_caminho[y][2] > MAX_YAML_BYTES:
            raise FalhaDeterministica(f"YAML do grafo grande demais: {y} tem {por_caminho[y][2]} bytes (teto {MAX_YAML_BYTES})")
        texto = ler_blobs(repo, [por_caminho[y][1]]).get(por_caminho[y][1], b"").decode("utf-8", "replace")
        try:
            dados = _grafo_mod().ler_yaml_texto(texto, y)
        except Exception as e:   # YAML quebrado: falha com o motivo (o grafo.py diria o mesmo)
            raise FalhaDeterministica(f"grafo.py: YAML inválido em {y}: {str(e)[:200]}") from None
        if not isinstance(dados, dict):
            continue
        if principal is None:
            principal = dados
            cov = dados.get("coverage") if isinstance(dados.get("coverage"), dict) else {}
            raizes = [_norm(r) for r in _lista(cov.get("roots")) if isinstance(r, str) and _norm(r)]
            exts = {str(e).lower() for e in _lista(cov.get("extensions")) if isinstance(e, str)}
        base_y = y.rsplit("/", 1)[0] + "/" if "/" in y else ""
        incl = dados.get("includes")
        for rel in (incl.values() if isinstance(incl, dict) else []):
            if isinstance(rel, str):
                yamls.append(_norm(base_y + rel))
        _caminhos(dados, citados)
        for n in _lista(dados.get("systems")):   # pastas dos sistemas fora da cobertura: o código delas entra (imports reais)
            if isinstance(n, dict):
                sis_paths.update(_norm(x) for x in _lista(n.get("paths")) if isinstance(x, str))
    lidos.cobertura = set()
    if raizes:   # arquivos de texto da cobertura (roots x extensions)
        exatas = [r for r in raizes if not any(ch in r for ch in "*?[")]
        padroes = [_glob_re(r) for r in raizes if any(ch in r for ch in "*?[")]
        for c in por_caminho:
            if exts and os.path.splitext(c)[1].lower() not in exts:
                continue
            if any(c == r or c.startswith(r + "/") for r in exatas) or any(p.match(c) for p in padroes):
                lidos.cobertura.add(c)
    sis_pastas = sorted(d for d in sis_paths if d in pastas_arvore and not any(ch in d for ch in "*?["))
    if sis_pastas and exts:
        for c in por_caminho:
            if os.path.splitext(c)[1].lower() in exts and any(c.startswith(d + "/") for d in sis_pastas):
                lidos.cobertura.add(c)
    escolhidos = set(lidos) | lidos.cobertura
    marcadores = []
    for p in sorted(citados):
        q = _norm(p)
        if not q or len(q) > 400 or q in (".", ".."):
            continue
        if any(ch in q for ch in "*?["):
            marcadores.append(q)
        elif q in por_caminho:
            escolhidos.add(q)
        elif q in pastas_arvore and not any(q == r or q.startswith(r + "/") for r in raizes):
            lidos.pastas.add(q)   # pasta citada (docs/areas, fontes de dados): só a pasta, sem os arquivos
    for q in marcadores:   # padrão com *: um arquivo que case com ele basta para o validate (marcador vazio)
        rx = _glob_re(q)
        if any(rx.match(c) for c in escolhidos):
            continue
        prim = next((c for c in sorted(por_caminho) if rx.match(c) and caminho_seguro(c)), None)
        if prim:
            escolhidos.add(prim)
            lidos.vazios.add(prim)
    ordenados = sorted(escolhidos, key=lambda c: (c not in lidos, c not in lidos.cobertura, c))
    lidos.pastas = {d for d in lidos.pastas if caminho_seguro(d)}
    return grafo, [por_caminho[c] for c in ordenados if caminho_seguro(c)][:MAX_ARQUIVOS], lidos


def extrair(repo, ref, destino, arquivo=""):
    """Escreve a base em `destino` (apagado antes). Devolve estatísticas. Quem chama troca de pasta só se tudo der certo."""
    itens = arvore(repo, ref)
    grafo, selec, lidos = escolher(itens, repo, ref, arquivo)
    destino = Path(destino)
    if destino.exists():
        shutil.rmtree(destino, ignore_errors=True)
    destino.mkdir(parents=True)
    conteudo, total = {}, 0
    for c, sha, tam in selec:
        if c in lidos or (c not in lidos.vazios and os.path.splitext(c)[1].lower() in EXT_TEXTO and tam <= MAX_ARQ
                          and total + tam <= MAX_TOTAL):   # YAML do grafo: sempre
            conteudo[c] = sha
            total += tam if c not in lidos else 0
    blobs = ler_blobs(repo, sorted(set(conteudo.values())))
    copiados = vazios = ignorados = 0
    for c, sha, _ in selec:
        alvo = destino.joinpath(*c.split("/"))
        dados = blobs.get(sha) if c in conteudo else None
        if dados is not None and c not in lidos and b"\0" in dados[:8192]:
            dados = None   # binário com extensão de texto
        try:
            alvo.parent.mkdir(parents=True, exist_ok=True)
            alvo.write_bytes(dados or b"")
        except OSError:
            ignorados += 1   # nome que o sistema de arquivos recusa mesmo assim: pula, não derruba a rodada
            continue
        if dados is None:
            vazios += 1
        else:
            copiados += 1
    for d in sorted(lidos.pastas):
        try:
            destino.joinpath(*d.split("/")).mkdir(parents=True, exist_ok=True)
        except OSError:
            ignorados += 1
    return {"grafo": grafo, "arquivos": copiados, "vazios": vazios, "pastas": len(lidos.pastas), "bytes": total,
            "selecionados": len(selec), "cobertura": len(lidos.cobertura), "na_arvore": len(itens), "ignorados": ignorados,
            "cortado": len(selec) >= MAX_ARQUIVOS}


def _rodar(args, timeout=TIMEOUT_GRAFO):
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    r = subprocess.run([sys.executable, str(GRAFO_PY), *args], capture_output=True, timeout=timeout, env=env)
    return r.returncode, r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")


def _json_saida(nome, rc, out, err, codigos_ok=(0,)):
    if rc not in codigos_ok:
        raise FalhaDeterministica(f"grafo.py {nome} saiu com {rc}: {(err or out).strip()[-300:]}")
    try:
        return json.loads(out)
    except ValueError:
        raise FalhaDeterministica(f"grafo.py {nome}: saída não é JSON: {out.strip()[:200]}") from None


def resumir_validacao(v):
    """Só o que o painel usa: ok, contagens e até MAX_ITENS_VALIDACAO erros/avisos (código, mensagem, de/para/sistemas)."""
    def item(x):
        return {k: x[k] for k in ("codigo", "msg", "de", "para", "sistemas") if k in x}
    erros, avisos = v.get("erros") or [], v.get("avisos") or []
    return {"ok": bool(v.get("ok")), "n_erros": len(erros), "n_avisos": len(avisos),
            "erros": [item(x) for x in erros[:MAX_ITENS_VALIDACAO]], "avisos": [item(x) for x in avisos[:MAX_ITENS_VALIDACAO]]}


def _repetir(fn, tentativas=20):
    """os.replace/rename no Windows falha (WinError 5/32) se alguém está com o arquivo aberto: tenta de novo com espera."""
    for i in range(tentativas):
        try:
            return fn()
        except PermissionError:
            if i == tentativas - 1:
                raise
            time.sleep(min(0.5, 0.05 * (i + 1)))   # antivírus/indexador segurando a pasta nova: até ~7 s no total


def _trocar_pasta(novo, destino):
    velho = destino.with_name(destino.name + ".velho")
    if velho.exists():
        shutil.rmtree(velho, ignore_errors=True)
    if destino.exists():
        _repetir(lambda: destino.rename(velho))
    try:
        _repetir(lambda: novo.rename(destino))
    except BaseException:
        if velho.exists() and not destino.exists():
            velho.rename(destino)
        raise
    shutil.rmtree(velho, ignore_errors=True)


def _cache_de(saida):
    """Estado e índice da pasta de saída: da memória; na 1ª vez, do disco (o servidor reiniciado serve o último)."""
    k = str(Path(saida).resolve())
    c = _cache.get(k)
    if c is None:
        est = ler_estado(saida)
        try:
            idx = json.loads((Path(saida) / "index.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            idx = None
        c = {"estado": est, "index": idx}
        if est or idx:
            _cache[k] = c
    return c


def atualizar(repo=None, ref=None, saida=None, forcar=False, arquivo=""):
    """Uma rodada completa. Devolve o estado novo (e grava estado.json); exceção = falha (o chamador mantém o último)."""
    if not (repo or REPO):
        raise RuntimeError('sem projeto: preencha "projetos" no config.json (a 1ª pasta é o repositório do grafo)')
    repo, ref, saida = Path(repo or REPO), ref or REF, Path(saida or SAIDA)
    if not ref_valida(ref):
        raise RuntimeError(f"grafo.ref inválida: {ref!r}")
    saida.mkdir(parents=True, exist_ok=True)
    commit = _git(repo, "rev-parse", "--verify", ref + "^{commit}").decode().strip()
    anterior = _cache_de(saida)["estado"]
    base, novo, tmp = saida / "base", saida / "base.novo", saida / "novo"
    chave_cfg = f"{repo}|{ref}|{arquivo}"   # mudou o projeto, a ref ou o arquivo no config: refaz
    if not forcar:
        if (anterior and anterior.get("commit") == commit and anterior.get("cfg") == chave_cfg and _cache_de(saida)["index"]
                and base.exists()):
            return anterior
        falha = _ler_json(saida / "falha.json")
        if (falha and falha.get("commit") == commit and falha.get("versao") == _versao() and falha.get("cfg") == chave_cfg
                and time.time() - (falha.get("ts") or 0) < FALHA_VALIDADE):
            raise RuntimeError(f"commit {commit[:7]} já falhou do mesmo jeito (refaz quando o commit ou o grafo.py mudar, ou em "
                               f"{FALHA_VALIDADE // 3600} h): {str(falha.get('erro'))[:240]}")
    try:
        extraido = extrair(repo, ref, novo, arquivo)
        grafo_arq = str(novo / extraido["grafo"])
        shutil.rmtree(tmp, ignore_errors=True)
        rc, out, err = _rodar(["index", "--raiz", str(novo), "--grafo", grafo_arq, "--saida", str(tmp)])
        if rc != 0 or not (tmp / "index.json").exists():
            raise FalhaDeterministica(f"grafo.py index saiu com {rc}: {(err or out).strip()[-300:]}")
        validacao = resumir_validacao(_json_saida("validate", *_rodar(["validate", "--raiz", str(novo), "--grafo", grafo_arq, "--json"]),
                                                  codigos_ok=(0, 1)))
        drift = _json_saida("drift", *_rodar(["drift", "--raiz", str(novo), "--grafo", grafo_arq, "--json"]))
        index = json.loads((tmp / "index.json").read_text(encoding="utf-8"))
    except BaseException as e:
        shutil.rmtree(novo, ignore_errors=True)
        shutil.rmtree(tmp, ignore_errors=True)
        if isinstance(e, FalhaDeterministica):   # transitória (timeout, arquivo preso, disco, git): tenta de novo na próxima rodada
            _gravar(saida / "falha.json", {"commit": commit, "versao": _versao(), "erro": f"{type(e).__name__}: {str(e)[:300]}",
                                           "ts": round(time.time()), "cfg": chave_cfg, "sem_grafo": isinstance(e, SemGrafo)})
        raise
    _trocar_pasta(novo, base)   # só depois de index, validate e drift darem certo
    for nome in ("index.json", "resumo.txt"):
        if (tmp / nome).exists():
            _repetir(lambda n=nome: os.replace(tmp / n, saida / n))
    shutil.rmtree(tmp, ignore_errors=True)
    estado = {"ts": round(time.time()), "repo": str(repo), "ref": ref, "commit": commit, "extraido": extraido,
              "validacao": validacao, "drift": drift, "erro": "", "cfg": chave_cfg}
    _gravar(saida / "estado.json", estado)
    try:
        (saida / "falha.json").unlink()
    except OSError:
        pass
    _cache[str(saida.resolve())] = {"estado": estado, "index": index}
    return estado


def _gravar(arq, obj):
    tmp = arq.with_name(arq.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    _repetir(lambda: os.replace(tmp, arq))


def _ler_json(arq):
    try:
        d = json.loads(Path(arq).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def ler_estado(saida=None):
    return _ler_json(Path(saida or SAIDA) / "estado.json")


def ref_valida(ref):
    """Ref do git aceitável na linha de comando: sem começar com "-", espaço, controle ou caracteres que o git recusa."""
    return (isinstance(ref, str) and 0 < len(ref) <= 200 and not ref.startswith("-") and ".." not in ref
            and not re.search(r"[\s~^:?*\[\\\x00-\x1f\x7f]", ref) and not ref.endswith((".", "/", ".lock")))


def rodada(repo=None, ref=None, saida=None, forcar=False, arquivo=""):
    """atualizar() com o estado em memória: falha guarda `erro` (e `sem_grafo`) e mantém o último resultado."""
    with _trava:
        if _estado["atualizando"]:
            return False
        _estado["atualizando"] = True
        _estado["tentativa"] = time.time()
    try:
        est = atualizar(repo, ref, saida, forcar, arquivo)
        with _trava:
            _estado.update(dados=est, erro="", sem_grafo=False)
        return True
    except Exception as e:
        sem = isinstance(e, SemGrafo) or (isinstance(e, RuntimeError) and "grafo não encontrado" in str(e))
        msg = str(e)[:400] if sem else f"{type(e).__name__}: {str(e)[:300]}"
        print(f"[grafo] {msg}", flush=True)
        with _trava:
            _estado.update(erro=msg, sem_grafo=sem)
        return False
    finally:
        with _trava:
            _estado["atualizando"] = False


def resposta(saida=None, ativo=True, raiz="", ref=None, arquivo=""):
    """Corpo do GET /grafo: index + drift + validação resumida + ts/ref/commit + erro (último resultado se a rodada falhou),
    `sem_grafo` (o projeto ainda não tem grafo: o painel mostra `como_criar`), `ativo` e `raiz` (pasta do projeto, para o
    painel tirar o prefixo dos caminhos dos eventos). Vem da memória (atualizada só depois de uma rodada boa)."""
    if not ativo:
        return {"ativo": False, "index": None, "erro": "", "sem_grafo": False, "como_criar": COMO_CRIAR, "atualizando": False}
    saida = Path(saida or SAIDA)
    with _trava:
        erro, atualizando, sem = _estado["erro"], _estado["atualizando"], bool(_estado.get("sem_grafo"))
    if not erro and not sem:   # servidor reiniciado: a falha "sem grafo" gravada continua valendo
        f = _ler_json(saida / "falha.json")
        if f and f.get("sem_grafo"):
            sem, erro = True, str(f.get("erro") or "")[:400]
    c = _cache_de(saida)
    est, index = c["estado"], c["index"]
    if ref is not None and est and est.get("cfg") != f"{Path(raiz) if raiz else ''}|{ref}|{arquivo or ''}":
        # o index é de outro projeto/ref/arquivo (o config mudou e a rodada nova ainda não terminou ou falhou): não serve
        est, index = None, None
        if not erro and not sem:
            erro = "o grafo está sendo gerado para a configuração nova (projeto, grafo.ref ou grafo.arquivo mudou)"
    corpo = {k: est.get(k) for k in ("ts", "ref", "commit", "extraido", "validacao", "drift")} if est else {}
    corpo.update(ativo=True, index=index, erro=erro or ("" if index else "grafo ainda não gerado"), atualizando=atualizando,
                 sem_grafo=sem, como_criar=COMO_CRIAR, raiz=str(raiz or "").replace("\\", "/").rstrip("/"))
    return corpo


def laco(parar, opcoes):
    """Thread do servidor: uma rodada logo na partida (depois de 5 s) e a cada grafo.intervalo_min. `opcoes()` devolve
    {"ativo", "repo", "ref", "arquivo", "intervalo_min"} relido a cada rodada (mudar o config.json não exige reiniciar)."""
    if parar.wait(5):
        return
    while not parar.is_set():
        try:
            o = opcoes()
        except Exception as e:   # noqa: BLE001
            o = {"ativo": False}
            print(f"[grafo] opções: {str(e)[:160]}", flush=True)
        if o.get("ativo"):
            rodada(o.get("repo"), o.get("ref"), None, False, o.get("arquivo") or "")
        parar.wait(max(5, int(o.get("intervalo_min") or 60)) * 60)
