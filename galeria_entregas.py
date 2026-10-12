"""Catálogo local de arquivos declarados, capturados do commit publicado.

Snapshots limitados vivem no mesmo SQLite dos recibos. Consultar nunca abre
paths do navegador, executa conteúdo, chama providers ou concede aceite.
"""
from contextlib import closing
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sqlite3
import subprocess
import threading
import time

MAX_ARQUIVOS = 20
MAX_ARQUIVO = 1024 * 1024
MAX_TOTAL = 5 * MAX_ARQUIVO
MAX_MANIFESTOS = 500
FORMATOS = {'.txt': ('text/plain', 'texto'), '.md': ('text/plain', 'texto'),
            '.csv': ('text/plain', 'texto'), '.png': ('image/png', 'imagem'),
            '.jpg': ('image/jpeg', 'imagem'), '.jpeg': ('image/jpeg', 'imagem'),
            '.webp': ('image/webp', 'imagem'), '.pdf': ('application/pdf', 'download'),
            '.glb': ('application/octet-stream', 'download')}
SEGREDOS = re.compile(rb'-----BEGIN [A-Z ]*PRIVATE KEY-----|(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,}', re.I)


def caminhos(arquivos):
    if not isinstance(arquivos, list) or not 1 <= len(arquivos) <= MAX_ARQUIVOS:
        raise ValueError('Declare de 1 a 20 arquivos de entrega')
    vistos = set()
    for nome in arquivos:
        if (not isinstance(nome, str) or not 1 <= len(nome) <= 240 or
            any(ord(c) < 32 or ord(c) == 127 for c in nome) or '\\' in nome or ':' in nome):
            raise ValueError('Caminho de entrega inválido')
        p = PurePosixPath(nome)
        partes = nome.split('/')
        if (p.is_absolute() or any(not v or v in ('.', '..') or v.startswith('.') or
            v != v.rstrip(' .') or re.search(r'(?:secret|credential|password|token|senha|segredo|chave|private[_-]?key)', v, re.I)
            or v.lower() in ('dados', 'node_modules', 'id_rsa', 'id_ed25519') for v in partes)
            or p.suffix.lower() not in FORMATOS or nome.casefold() in vistos):
            raise ValueError('Arquivo fora dos formatos/caminhos permitidos para entrega')
        vistos.add(nome.casefold())
    return sorted(arquivos)


def _canonico(caminho):
    p = Path(caminho)
    if not p.is_absolute() or p != p.resolve(strict=True):
        raise ValueError('Raiz não canônica')
    if any(a.is_symlink() for a in (p, *p.parents)):
        raise ValueError('Raiz com link simbólico')
    return p


def _git(raiz, *args, limite=4096):
    """Leitura limitada; sem filtros, hooks, replace objects ou busca de objetos."""
    env = {**os.environ, 'GIT_NO_REPLACE_OBJECTS': '1', 'GIT_NO_LAZY_FETCH': '1',
           'GIT_TERMINAL_PROMPT': '0', 'GIT_OPTIONAL_LOCKS': '0'}
    with subprocess.Popen(['git', '-C', str(raiz), *args], stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, env=env) as proc:
        timer = threading.Timer(10, proc.kill)
        timer.start()
        try:
            saida = proc.stdout.read(limite + 1)
            if len(saida) > limite:
                proc.kill()
                raise ValueError('Objeto Git excede o limite da galeria')
            if proc.wait(timeout=10):
                raise ValueError('Objeto Git local indisponível')
            return saida
        finally:
            timer.cancel()


def _raiz_git(projeto, trabalho):
    projeto, trabalho = _canonico(projeto), _canonico(trabalho)
    antes = trabalho.stat()
    if Path(_git(trabalho, 'rev-parse', '--show-toplevel').decode().strip()).resolve() != trabalho:
        raise ValueError('Worktree inválido')
    def comum(p):
        valor = _git(p, 'rev-parse', '--git-common-dir').decode().strip()
        return _canonico((p / valor).resolve())
    if comum(projeto) != comum(trabalho):
        raise ValueError('Worktree pertence a outro projeto')
    return trabalho, (antes.st_dev, antes.st_ino)


def _objeto(trabalho, oid, tipo):
    tamanho = _git(trabalho, 'cat-file', '-s', oid).strip()
    if not tamanho.isdigit() or int(tamanho) > MAX_ARQUIVO:
        raise ValueError('Objeto excede 1 MiB')
    dados = _git(trabalho, 'cat-file', tipo, oid, limite=MAX_ARQUIVO)
    cabecalho = tipo.encode() + b' ' + str(len(dados)).encode() + b'\0'
    if len(dados) != int(tamanho) or hashlib.sha1(cabecalho + dados).hexdigest() != oid:
        raise ValueError('Integridade do objeto Git não confirmada')
    return dados


def _blob(trabalho, sha, nome):
    # Confere toda a cadeia commit/tree/blob. Mesmo se o worktree mudar enquanto
    # lemos, bytes de outro objeto nunca são atribuídos ao SHA registrado.
    commit = _objeto(trabalho, sha, 'commit')
    primeira = commit.split(b'\n', 1)[0]
    if not re.fullmatch(rb'tree [0-9a-f]{40}', primeira):
        raise ValueError('Commit sem árvore válida')
    arvore = primeira[5:].decode('ascii')
    partes = nome.split('/')
    for i, parte in enumerate(partes):
        dados = _objeto(trabalho, arvore, 'tree'); offset = 0; entrada = None
        while offset < len(dados):
            zero = dados.index(b'\0', offset)
            modo, encontrado = dados[offset:zero].split(b' ', 1)
            bruto = dados[zero + 1:zero + 21]
            if len(bruto) != 20:
                raise ValueError('Árvore Git inválida')
            if encontrado == parte.encode('utf-8'):
                if entrada is not None:
                    raise ValueError('Arquivo Git ambíguo')
                entrada = (modo, bruto.hex())
            offset = zero + 21
        if entrada is None:
            raise ValueError('Arquivo não consta no commit publicado')
        modo, oid = entrada
        if i < len(partes) - 1:
            if modo != b'40000':
                raise ValueError('Diretório simbólico/submódulo não é entrega')
            arvore = oid
        elif modo not in (b'100644', b'100755'):
            raise ValueError('Links simbólicos/submódulos não são entregas')
    return _objeto(trabalho, oid, 'blob')


def _formato(nome, dados):
    mime, preview = FORMATOS[PurePosixPath(nome).suffix.lower()]
    if SEGREDOS.search(dados):
        raise ValueError('Possível credencial no arquivo; não registrar')
    if preview == 'texto':
        texto = dados.decode('utf-8')
        if any(ord(c) < 32 and c not in '\n\r\t' for c in texto):
            raise ValueError('Texto contém controles binários')
    if mime == 'image/png' and not dados.startswith(b'\x89PNG\r\n\x1a\n'):
        raise ValueError('PNG inválido')
    if mime == 'image/jpeg' and not dados.startswith(b'\xff\xd8\xff'):
        raise ValueError('JPEG inválido')
    if mime == 'image/webp' and not (dados.startswith(b'RIFF') and dados[8:12] == b'WEBP'):
        raise ValueError('WebP inválido')
    if mime == 'application/pdf' and not dados.startswith(b'%PDF-'):
        raise ValueError('PDF inválido')
    if nome.lower().endswith('.glb') and not dados.startswith(b'glTF'):
        raise ValueError('GLB inválido')
    return mime, preview


def _banco(projeto, escrever=False):
    from gestao_cli import pasta_dados
    p = pasta_dados(projeto) / 'tarefas.db'
    if p.is_symlink() or not p.is_file() or p != p.resolve():
        raise ValueError('Diário de tarefas indisponível')
    db = sqlite3.connect(p.resolve().as_uri() + ('?mode=rw' if escrever else '?mode=ro'), uri=True, timeout=5)
    db.row_factory = sqlite3.Row
    return db


def _migrar(db):
    db.execute('''CREATE TABLE IF NOT EXISTS galeria_manifesto (
        id TEXT PRIMARY KEY,projeto TEXT NOT NULL,repo TEXT NOT NULL,cartao INTEGER NOT NULL,
        token TEXT NOT NULL,tentativa TEXT NOT NULL,pr INTEGER NOT NULL,sha TEXT NOT NULL,
        criado REAL NOT NULL,arquivada INTEGER NOT NULL DEFAULT 0,
        UNIQUE(projeto,tentativa,pr,sha))''')
    db.execute('''CREATE TABLE IF NOT EXISTS galeria_arquivo (
        id TEXT PRIMARY KEY,manifesto TEXT NOT NULL,nome TEXT NOT NULL,tamanho INTEGER NOT NULL,
        mime TEXT NOT NULL,preview TEXT NOT NULL,sha256 TEXT NOT NULL,conteudo BLOB NOT NULL,
        UNIQUE(manifesto,nome),FOREIGN KEY(manifesto) REFERENCES galeria_manifesto(id))''')


def _contexto(db, repo, recibo):
    token, tentativa = recibo.get('token'), recibo.get('tentativa')
    if not all(isinstance(v, str) and re.fullmatch('[0-9a-f]{32}', v) for v in (token, tentativa)):
        raise ValueError('Publicação sem tentativa comprovada')
    r = db.execute('SELECT * FROM reserva WHERE token=? AND projeto=? AND cartao=?',
                   (token, repo, str(recibo['cartao']))).fetchone()
    e = db.execute('SELECT * FROM execucao_tarefa WHERE id=? AND token=?', (tentativa, token)).fetchone()
    ctx = json.loads(r['pacote']).get('contexto_execucao', {}) if r else {}
    if not r or not e or ctx.get('worktree') != recibo.get('worktree') or ctx.get('branch') != recibo.get('branch'):
        raise ValueError('Publicação diverge da reserva/tentativa')
    return dict(r), dict(e)


def registrar_publicacao(projeto, recibo, arquivos):
    """Chamado apenas após salvar o recibo de publicação; falha não repete push."""
    from funcionarios import id_projeto
    from gestao_projeto import carregar
    arquivos = caminhos(arquivos)
    cfg = carregar(projeto); repo = cfg['kanban']['repo']; projeto_id = id_projeto(projeto)
    if (not cfg['ativo'] or not isinstance(recibo, dict) or recibo.get('estado') != 'publicado' or
        type(recibo.get('cartao')) is not int or recibo['cartao'] < 1 or
        not re.fullmatch('[0-9a-f]{40}', recibo.get('sha') or '')):
        raise ValueError('Publicação/commit inválido')
    pr = re.fullmatch(re.escape('https://github.com/' + repo + '/pull/') + r'([1-9][0-9]{0,9})', recibo.get('pr') or '')
    if not pr:
        raise ValueError('PR pertence a outro projeto')
    with closing(_banco(projeto)) as db:
        contexto = _contexto(db, repo, recibo)
    trabalho, identidade = _raiz_git(projeto, recibo['worktree'])
    capturados = []; total = 0
    for nome in arquivos:
        dados = _blob(trabalho, recibo['sha'], nome)
        mime, preview = _formato(nome, dados); total += len(dados)
        if total > MAX_TOTAL:
            raise ValueError('Manifesto excede 5 MiB')
        capturados.append((nome, len(dados), mime, preview, hashlib.sha256(dados).hexdigest(), dados))
    atual = _canonico(trabalho).stat()
    if identidade != (atual.st_dev, atual.st_ino) or carregar(projeto) != cfg:
        raise ValueError('Projeto/worktree mudou durante captura')
    ident = hashlib.sha256(json.dumps([projeto_id, recibo['tentativa'], int(pr[1]), recibo['sha']]).encode()).hexdigest()
    with closing(_banco(projeto, True)) as db, db:
        db.execute('BEGIN IMMEDIATE'); _migrar(db)
        if _contexto(db, repo, recibo) != contexto:
            raise ValueError('Reserva/tentativa mudou durante captura')
        antigo = db.execute('SELECT id FROM galeria_manifesto WHERE id=?', (ident,)).fetchone()
        if antigo:
            anteriores = [tuple(r) for r in db.execute('SELECT nome,tamanho,mime,preview,sha256,conteudo FROM galeria_arquivo WHERE manifesto=? ORDER BY nome', (ident,))]
            if anteriores != capturados:
                raise ValueError('Manifesto já registrado é imutável; use nova tentativa/commit')
            return {'id': ident, 'arquivos': len(capturados), 'estado': 'ja_registrado'}
        armazenado = db.execute('SELECT COALESCE(SUM(tamanho),0) FROM galeria_arquivo').fetchone()[0]
        if armazenado + total > 100 * MAX_ARQUIVO:
            raise ValueError('Galeria atingiu 100 MiB; histórico foi preservado')
        if db.execute('SELECT COUNT(*) FROM galeria_manifesto').fetchone()[0] >= MAX_MANIFESTOS:
            raise ValueError('Galeria atingiu 500 manifestos; histórico foi preservado')
        db.execute('INSERT INTO galeria_manifesto VALUES (?,?,?,?,?,?,?,?,?,0)',
                   (ident, projeto_id, repo, recibo['cartao'], recibo['token'], recibo['tentativa'], int(pr[1]), recibo['sha'], time.time()))
        for nome, tamanho, mime, preview, sha256, dados in capturados:
            arquivo_id = hashlib.sha256((ident + '\0' + nome).encode()).hexdigest()
            db.execute('INSERT INTO galeria_arquivo VALUES (?,?,?,?,?,?,?,?)',
                       (arquivo_id, ident, nome, tamanho, mime, preview, sha256, dados))
    return {'id': ident, 'arquivos': len(capturados), 'estado': 'registrado'}


def registrar(projeto, dados):
    """Reconciliação explícita sem publicação ou acesso remoto."""
    from gestao_cli import pasta_dados
    from gestao_projeto import carregar
    if (not isinstance(dados, dict) or set(dados) != {'cartao', 'tentativa', 'pr', 'sha', 'arquivos'} or
        type(dados['cartao']) is not int or dados['cartao'] < 1 or type(dados['pr']) is not int or dados['pr'] < 1 or
        not isinstance(dados['tentativa'], str) or not re.fullmatch('[0-9a-f]{32}', dados['tentativa']) or
        not isinstance(dados['sha'], str) or not re.fullmatch('[0-9a-f]{40}', dados['sha'])):
        raise ValueError('Informe cartão, tentativa, PR, SHA e arquivos explícitos')
    caminhos(dados['arquivos']); encontrados = []
    pasta = pasta_dados(projeto) / 'publicacoes'
    if pasta.is_symlink() or pasta != pasta.resolve():
        raise ValueError('Recibos indisponíveis')
    repo = carregar(projeto)['kanban']['repo']
    candidatos = sorted(pasta.glob(str(dados['cartao']) + '*.json'))
    if len(candidatos) > 200:
        raise ValueError('Recibos excedem limite de consulta')
    for p in candidatos:
        if p.is_symlink() or p.stat().st_size > 128000:
            continue
        r = json.loads(p.read_text(encoding='utf-8'))
        if (r.get('estado') == 'publicado' and r.get('cartao') == dados['cartao'] and
            r.get('tentativa') == dados['tentativa'] and r.get('sha') == dados['sha'] and
            r.get('pr') == f'https://github.com/{repo}/pull/{dados["pr"]}'):
            encontrados.append(r)
    if len(encontrados) != 1:
        raise ValueError('Exige recibo único de publicação da tentativa/PR/SHA')
    return registrar_publicacao(projeto, encontrados[0], dados['arquivos'])


def arquivar(projeto, dados):
    from funcionarios import id_projeto
    if (not isinstance(dados, dict) or set(dados) != {'id', 'arquivada'} or
        not isinstance(dados['id'], str) or not re.fullmatch('[0-9a-f]{64}', dados['id']) or
        type(dados['arquivada']) is not bool):
        raise ValueError('Informe manifesto e estado de arquivo')
    with closing(_banco(projeto, True)) as db, db:
        if db.execute('UPDATE galeria_manifesto SET arquivada=? WHERE id=? AND projeto=?',
                      (int(dados['arquivada']), dados['id'], id_projeto(projeto))).rowcount != 1:
            raise ValueError('Manifesto não pertence ao projeto')
    return {'id': dados['id'], 'arquivada': dados['arquivada']}


def _selecionar(projetos, ident):
    from funcionarios import id_projeto
    from gestao_projeto import carregar
    if not isinstance(ident, str) or not re.fullmatch('[0-9a-f]{20}', ident):
        raise ValueError('Projeto inválido')
    candidatos = [p for p in projetos if id_projeto(p) == ident]
    if len(candidatos) != 1 or not carregar(candidatos[0])['ativo']:
        raise ValueError('Projeto indisponível')
    return candidatos[0]


def listar(projeto):
    """Projeção limitada somente de metadados; registro não é aceite/merge."""
    from funcionarios import id_projeto
    from gestao_projeto import carregar
    from gestao_cli import pasta_dados
    resultado = {'ok': True, 'itens': [], 'limitado': False}
    if not (pasta_dados(projeto) / 'tarefas.db').exists():
        return resultado
    with closing(_banco(projeto)) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='galeria_manifesto' AND type='table'").fetchone():
            return resultado
        repo = carregar(projeto)['kanban']['repo']
        rows = db.execute('SELECT * FROM galeria_manifesto WHERE projeto=? AND repo=? ORDER BY criado DESC,id DESC LIMIT 101',
                          (id_projeto(projeto), repo)).fetchall()
        resultado['limitado'] = len(rows) > 100
        for row in rows[:100]:
            item = {k: row[k] for k in ('id', 'cartao', 'tentativa', 'pr', 'sha', 'criado')}
            item.update(arquivada=bool(row['arquivada']), aprovacao_visual='nao_registrada', aceite_usuario='nao_registrado',
                        execucao={'estado': 'nao_informada', 'codigo': None, 'resultado': None},
                        revisao={'estado': 'nao_informada'}, merge={'estado': 'nao_comprovado'})
            e = db.execute('SELECT e.fim,e.codigo,a.resultado FROM execucao_tarefa e LEFT JOIN execucao_resultado a ON a.execucao=e.id WHERE e.id=? AND e.token=?',
                           (row['tentativa'], row['token'])).fetchone()
            if e:
                item['execucao'] = {'estado': 'encerrada' if e['fim'] is not None else 'sem_retorno', 'codigo': e['codigo'], 'resultado': e['resultado']}
            r = db.execute('SELECT aprovado FROM entrega WHERE token=? AND sha=? AND pr=?', (row['token'], row['sha'], row['pr'])).fetchone()
            if r:
                item['revisao'] = {'estado': 'aprovada' if r['aprovado'] == 1 else 'sem_aprovacao'}
            c = db.execute('SELECT evidencia FROM conclusao WHERE token=?', (row['token'],)).fetchone()
            if c:
                ev = json.loads(c['evidencia'])
                if (ev.get('repo') == repo and ev.get('head') == row['sha'] and ev.get('pr') == row['pr'] and
                    ev.get('cartao') == row['cartao'] and re.fullmatch('[0-9a-f]{40}', ev.get('merge_commit') or '') and ev.get('merged_at')):
                    item['merge'] = {'estado': 'registrado', 'sha': ev['merge_commit'], 'data': ev['merged_at']}
            item['arquivos'] = [dict(a) for a in db.execute('SELECT id,nome,tamanho,mime,preview,sha256 FROM galeria_arquivo WHERE manifesto=? ORDER BY nome LIMIT 20', (row['id'],))]
            resultado['itens'].append(item)
    return resultado


def arquivo(projeto, ident):
    from funcionarios import id_projeto
    from gestao_projeto import carregar
    if not isinstance(ident, str) or not re.fullmatch('[0-9a-f]{64}', ident):
        raise ValueError('Identidade de arquivo inválida')
    with closing(_banco(projeto)) as db:
        row = db.execute('SELECT a.* FROM galeria_arquivo a JOIN galeria_manifesto m ON m.id=a.manifesto WHERE a.id=? AND m.projeto=? AND m.repo=? AND length(a.conteudo)<=?',
                         (ident, id_projeto(projeto), carregar(projeto)['kanban']['repo'], MAX_ARQUIVO)).fetchone()
    if not row:
        raise ValueError('Arquivo não pertence ao projeto')
    dados = row['conteudo']
    if len(dados) != row['tamanho'] or hashlib.sha256(dados).hexdigest() != row['sha256'] or _formato(row['nome'], dados) != (row['mime'], row['preview']):
        raise ValueError('Integridade do snapshot não confirmada')
    return {'ok': True, **{k: row[k] for k in ('nome', 'mime', 'sha256', 'tamanho', 'preview')},
            'conteudo': dados.decode('utf-8') if row['preview'] == 'texto' else base64.b64encode(dados).decode('ascii')}


def api(projetos, qs, ident, conteudo=False):
    # A galeria pode conter entregas privadas; pareamento móvel não amplia acesso.
    if ident.get('permissao') != 'pc':
        return 403, {'ok': False, 'erro': 'Galeria disponível somente no PC'}
    if set(qs) != ({'projeto', 'arquivo'} if conteudo else {'projeto'}) or any(len(v) != 1 for v in qs.values()):
        return 400, {'ok': False, 'erro': 'Informe projeto e identidade únicos'}
    try:
        projeto = _selecionar(projetos, qs['projeto'][0])
        return 200, arquivo(projeto, qs['arquivo'][0]) if conteudo else listar(projeto)
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error):
        return 409, {'ok': False, 'erro': 'Entrega indisponível ou integridade não confirmada; confira os recibos no PC'}
