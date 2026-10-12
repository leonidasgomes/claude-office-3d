"""Busca local e limitada de referências; nunca fornece instruções ao despacho.

Lê somente três fontes configuradas e conclusões com evidência de merge.
Nenhum índice, descoberta de arquivos, escrita, subprocesso ou provider.
"""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sqlite3
import stat
import threading
import time

MAX_ARQUIVO = 131072
MAX_REGISTRO = 64000
MAX_BYTES = 2 * 1024 * 1024
MAX_BANCO = 32 * 1024 * 1024
MAX_ENTREGAS = 100
MAX_RESULTADOS = 20
EXTENSOES = {'.md', '.txt', '.yaml', '.yml', '.json'}
PROIBIDOS = {'dados', 'node_modules', 'vendor', 'dist', 'build', '__pycache__',
             'credentials', 'secrets', 'private', 'logs', 'sessions', 'transcripts'}
NOME_PRIVADO = re.compile(r'(?:secret|credential|password|token|senha|segredo|private|id_rsa|id_ed25519)', re.I)
SEGREDOS = re.compile(
    r'-----BEGIN [A-Z ]*PRIVATE KEY-----|(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]{20,}'
    r'|sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}'
    r'|(?:password|passwd|senha|api[_-]?key|access[_-]?token|client[_-]?secret|authorization)'
    r'[\s\"\x27]*[:=][^\r\n]+', re.I)
SHA = re.compile(r'[0-9a-f]{40}\Z')
HASH = re.compile(r'[0-9a-f]{64}\Z')
REPO = re.compile(r'[A-Za-z0-9][A-Za-z0-9-]{0,99}/[A-Za-z0-9_.-]{1,100}\Z')
_CONSULTA = threading.BoundedSemaphore(1)


def _assinatura(p):
    s = p.lstat()
    return s.st_dev, s.st_ino, s.st_mode, s.st_size, s.st_mtime_ns


def _link(p, s):
    return (stat.S_ISLNK(s.st_mode) or
            bool(getattr(s, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)) or
            getattr(p, 'is_junction', lambda: False)())


def _cadeia(p):
    """Não segue links, inclusive links para dentro da própria raiz."""
    p = Path(p)
    if not p.is_absolute():
        raise ValueError('Caminho não canônico')
    cadeia = []
    for parte in reversed((p, *p.parents)):
        s = parte.lstat()
        if _link(parte, s):
            raise ValueError('Link não permitido')
        cadeia.append((parte, (s.st_dev, s.st_ino, s.st_mode)))
    if p != p.resolve(strict=True):
        raise ValueError('Caminho não canônico')
    return cadeia


def _conferir(cadeia):
    for p, identidade in cadeia:
        s = p.lstat()
        if (s.st_dev, s.st_ino, s.st_mode) != identidade or _link(p, s):
            raise ValueError('Fonte mudou durante leitura')


def _nome(nome):
    if (not isinstance(nome, str) or not 1 <= len(nome) <= 240 or
        '\\' in nome or ':' in nome or any(ord(c) < 32 or ord(c) == 127 for c in nome)):
        raise ValueError('Fonte excluída pela política de leitura')
    partes = nome.split('/')
    # Exceção estreita para a fonte canônica documentada .office/REGRAS.md.
    office = len(partes) == 2 and partes[0] == '.office' and PurePosixPath(nome).suffix.lower() in {'.md', '.txt', '.yaml', '.yml'}
    for i, parte in enumerate(partes):
        if (not parte or parte in ('.', '..') or parte != parte.rstrip(' .') or
            (parte.startswith('.') and not (office and i == 0)) or
            parte.casefold() in PROIBIDOS or NOME_PRIVADO.search(parte)):
            raise ValueError('Fonte excluída pela política de leitura')
    if (PurePosixPath(nome).suffix.lower() not in EXTENSOES or
        PurePosixPath(nome).stem.casefold() in {'config', 'auth', 'settings', 'credentials'} or
        partes[-1].casefold() == 'projeto.json'):
        raise ValueError('Fonte excluída pela política de leitura')
    return nome


def _texto_seguro(texto):
    return (isinstance(texto, str) and not SEGREDOS.search(texto) and
            not any((ord(c) < 32 and c not in '\n\r\t') or 0xD800 <= ord(c) <= 0xDFFF for c in texto))


def _abrir(raiz, nome):
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
    if os.open not in os.supports_dir_fd:
        return os.open(raiz / nome, flags)
    esperada = _assinatura(raiz)[:3]
    diretorio = os.open(raiz, flags | os.O_DIRECTORY)
    try:
        s = os.fstat(diretorio)
        if (s.st_dev, s.st_ino, s.st_mode) != esperada:
            raise ValueError('Raiz mudou durante leitura')
        partes = nome.split('/')
        for parte in partes[:-1]:
            novo = os.open(parte, flags | os.O_DIRECTORY, dir_fd=diretorio)
            os.close(diretorio)
            diretorio = novo
        return os.open(partes[-1], flags, dir_fd=diretorio)
    finally:
        os.close(diretorio)


def _ler_bytes(raiz, nome, limite=MAX_ARQUIVO):
    p = raiz / nome
    cadeia = _cadeia(p)
    if not p.is_relative_to(raiz):
        raise ValueError('Fonte fora do projeto')
    antes = _assinatura(p)
    if not stat.S_ISREG(antes[2]) or antes[3] > limite:
        raise ValueError('Fonte indisponível ou acima do limite')
    fd = _abrir(raiz, nome)
    with os.fdopen(fd, 'rb') as f:
        s = os.fstat(f.fileno())
        if (s.st_dev, s.st_ino, s.st_mode, s.st_size, s.st_mtime_ns) != antes:
            raise ValueError('Fonte mudou durante leitura')
        bruto = f.read(limite + 1)
        fim = os.fstat(f.fileno())
    _conferir(cadeia)
    if antes != _assinatura(p) or antes != (fim.st_dev, fim.st_ino, fim.st_mode, fim.st_size, fim.st_mtime_ns) or len(bruto) > limite:
        raise ValueError('Fonte mudou durante leitura')
    return bruto, s


def _politica(raiz):
    from gestao_projeto import validar
    bruto, _ = _ler_bytes(raiz, '.office/projeto.json')
    try:
        return validar(json.loads(bruto.decode('utf-8-sig')))
    except (RecursionError, AttributeError, TypeError, KeyError) as exc:
        raise ValueError('Política excede complexidade permitida') from exc


def _documento(raiz, papel, nome):
    nome = _nome(nome)
    bruto, s = _ler_bytes(raiz, nome)
    texto = bruto.decode('utf-8-sig')
    if not _texto_seguro(texto):
        raise ValueError('Fonte excluída por conteúdo não seguro')
    sha = hashlib.sha256(bruto).hexdigest()
    return {'id': 'documento:' + papel, 'tipo': 'documento', 'papel': papel,
            'fonte': nome, 'revisao': sha, 'data': datetime.fromtimestamp(s.st_mtime, timezone.utc).isoformat(),
            'data_tipo': 'modificacao_local', 'origem': 'arquivo_canonico_configurado',
            'snapshot': 'arvore_de_trabalho', 'texto': texto}


def _data(valor):
    if not isinstance(valor, str) or not 10 <= len(valor) <= 50:
        raise ValueError('Data inválida')
    dt = datetime.fromisoformat(valor.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        raise ValueError('Data sem fuso')
    return dt.isoformat()


def _entrega(repo, numero, equipe, pacote, prova):
    """Mesmos requisitos de merge da memória de despacho, sem mudar seu filtro GDD."""
    if (not isinstance(numero, str) or not re.fullmatch('[1-9][0-9]{0,9}', numero) or
        not isinstance(equipe, str) or len(equipe) > 200):
        raise ValueError('Entrega inválida')
    anterior, ev = json.loads(pacote), json.loads(prova)
    if not isinstance(anterior, dict) or not isinstance(ev, dict):
        raise ValueError('Entrega inválida')
    if (ev.get('repo') != repo or type(ev.get('cartao')) is not int or ev['cartao'] != int(numero) or
        type(ev.get('pr')) is not int or not 1 <= ev['pr'] <= 9999999999 or
        not isinstance(ev.get('head'), str) or not SHA.fullmatch(ev['head']) or
        not isinstance(ev.get('merge_commit'), str) or not SHA.fullmatch(ev['merge_commit'])):
        raise ValueError('Merge sem vínculo válido')
    checks = ev.get('checks')
    gates = checks.get('gates') if isinstance(checks, dict) else None
    if not isinstance(gates, list) or not gates or any(not isinstance(g, dict) or g.get('estado') != 'success' for g in gates):
        raise ValueError('Merge sem gates aprovados')
    meta = anterior.get('meta')
    if not isinstance(meta, dict):
        raise ValueError('Entrega sem metadados')
    gdd = meta.get('gdd')
    if (not isinstance(gdd, dict) or not isinstance(gdd.get('sha256'), str) or
        not HASH.fullmatch(gdd['sha256']) or type(gdd.get('numero')) is not int or gdd['numero'] < 1):
        raise ValueError('Entrega sem proveniência GDD')
    objetivo = meta.get('objetivo', '')
    if not isinstance(objetivo, str) or len(objetivo) > 1000 or not _texto_seguro(objetivo + '\n' + equipe):
        raise ValueError('Metadados indisponíveis')
    evidencia = hashlib.sha256(prova.encode()).hexdigest()
    return {'id': 'entrega:' + hashlib.sha256(f'{repo}:{numero}:{ev["pr"]}:{ev["head"]}'.encode()).hexdigest(),
            'tipo': 'entrega', 'fonte': f'Cartão #{numero} · PR #{ev["pr"]}',
            'revisao': ev['merge_commit'], 'head': ev['head'], 'data': _data(ev.get('merged_at')),
            'data_tipo': 'merge_registrado', 'origem': 'conclusao_registrada',
            'cartao': int(numero), 'pr': ev['pr'], 'equipe': equipe,
            'gdd_sha256': gdd['sha256'], 'objetivo_gdd': gdd['numero'],
            'evidencia_sha256': evidencia, 'aceite_usuario': 'nao_inferido',
            'url': f'https://github.com/{repo}/pull/{ev["pr"]}',
            'texto': f'Cartão #{numero} PR #{ev["pr"]}\n{objetivo}\nEquipe: {equipe}'}


def _sidecars(p):
    saida = []
    # SQLite pode consultar sidecars existentes; links nesses nomes são proibidos.
    for sufixo in ('-wal', '-shm', '-journal'):
        extra = Path(str(p) + sufixo)
        if extra.exists() or extra.is_symlink():
            _cadeia(extra)
            s = _assinatura(extra)
            if not stat.S_ISREG(s[2]):
                raise ValueError('Sidecar inválido')
            saida.append((extra.name, s))
            if sufixo in ('-wal', '-journal') and extra.stat().st_size:
                raise ValueError('Diário em transição; tente novamente')
    return saida


def _entregas(raiz, repo):
    from gestao_cli import pasta_dados
    p = pasta_dados(raiz) / 'tarefas.db'
    if not p.exists() and not p.is_symlink():
        return [], False, 0
    cadeia = _cadeia(p)
    assinatura = _assinatura(p)
    if not stat.S_ISREG(p.lstat().st_mode):
        raise ValueError('Diário indisponível')
    sidecars = _sidecars(p)
    bruto, _ = _ler_bytes(p.parent, p.name, MAX_BANCO)
    if (not bruto.startswith(b'SQLite format 3\x00') or len(bruto) < 100 or
        bruto[18:20] != b'\x01\x01' or _sidecars(p) != sidecars):
        raise ValueError('Snapshot SQLite indisponível')
    itens, vistos, gasto, omitidos = [], set(), 0, 0
    # SQLite nunca abre o caminho: a imagem limitada pertence ao fd já conferido.
    # Sem temporários, sidecars, alterações no diário ou leitura por outro inode.
    with closing(sqlite3.connect(':memory:')) as db:
        if not hasattr(db, 'deserialize') or not hasattr(db, 'setlimit'):
            raise ValueError('Leitura isolada de SQLite indisponível')
        db.deserialize(bruto)
        del bruto
        db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 2 * MAX_REGISTRO + 4096)
        db.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, 20000)
        db.execute('PRAGMA temp_store=MEMORY')
        db.execute('PRAGMA query_only=ON')
        db.execute('PRAGMA trusted_schema=OFF')
        def autorizar(acao, a, b, banco, origem):
            if acao == sqlite3.SQLITE_SELECT:
                return sqlite3.SQLITE_OK
            if acao == sqlite3.SQLITE_READ and a in ('sqlite_master', 'reserva', 'conclusao') and banco == 'main':
                return sqlite3.SQLITE_OK
            if acao == sqlite3.SQLITE_FUNCTION and b in ('substr', 'length'):
                return sqlite3.SQLITE_OK
            return sqlite3.SQLITE_DENY
        db.set_authorizer(autorizar)
        inicio = time.monotonic()
        db.set_progress_handler(lambda: int(time.monotonic() - inicio > 0.25), 1000)
        tabelas = {r[0] for r in db.execute("SELECT name,sql FROM sqlite_master WHERE type='table'")
                   if isinstance(r[1], str) and not re.match(r'\s*CREATE\s+VIRTUAL\b', r[1], re.I)}
        if not {'reserva', 'conclusao'} <= tabelas:
            return [], False, 0
        rows = db.execute('SELECT substr(r.cartao,1,11),substr(r.equipe,1,201),substr(r.pacote,1,?),substr(c.evidencia,1,?),length(r.pacote),length(c.evidencia) '
                          "FROM reserva r JOIN conclusao c ON c.token=r.token WHERE r.projeto=? AND r.estado='concluido' "
                          'ORDER BY r.atualizado DESC,r.cartao LIMIT ?',
                          (MAX_REGISTRO + 1, MAX_REGISTRO + 1, repo, MAX_ENTREGAS + 1))
        limitado = False
        for i, row in enumerate(rows):
            if i >= MAX_ENTREGAS:
                limitado = True
                break
            numero, equipe, pacote, prova, lp, le = row
            if not all(isinstance(x, str) for x in (pacote, prova)) or not all(type(n) is int and 0 < n <= MAX_REGISTRO for n in (lp, le)):
                omitidos += 1
                continue
            gasto += len(pacote.encode()) + len(prova.encode())
            if gasto > MAX_BYTES:
                limitado = True
                break
            try:
                item = _entrega(repo, numero, equipe, pacote, prova)
                if item['id'] not in vistos:
                    vistos.add(item['id']); itens.append(item)
            except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
                omitidos += 1
    _conferir(cadeia)
    if _assinatura(p) != assinatura or _sidecars(p) != sidecars:
        raise ValueError('Diário mudou durante leitura')
    return itens, limitado, omitidos


def _buscar(projetos, ident, consulta):
    from funcionarios import id_projeto
    if not isinstance(ident, str) or not re.fullmatch('[0-9a-f]{20}', ident):
        raise ValueError('Informe um projeto registrado')
    if (not isinstance(consulta, str) or len(consulta) > 160 or len(consulta.strip()) < 2 or
        any(ord(c) < 32 or ord(c) == 127 for c in consulta)):
        raise ValueError('Consulta deve ter entre 2 e 160 caracteres')
    termos = list(dict.fromkeys(consulta.casefold().split()))
    if len(termos) > 12:
        raise ValueError('Consulta excede 12 termos')
    selecionados = [Path(p) for p in projetos if id_projeto(p) == ident]
    if len(selecionados) != 1:
        raise ValueError('Projeto indisponível')
    raiz = selecionados[0]
    cadeia = _cadeia(raiz)
    politica = raiz / '.office' / 'projeto.json'
    if politica.exists() or politica.is_symlink():
        cadeia.extend(_cadeia(politica))
    cfg = _politica(raiz)
    repo = cfg['kanban']['repo']
    if (not cfg['ativo'] or (repo and (not REPO.fullmatch(repo) or repo.split('/')[-1] in ('.', '..')))):
        raise ValueError('Projeto indisponível')
    saida = {'ok': True, 'projeto_id': ident, 'resultados': [], 'fontes': [], 'limitado': False,
             'limite': 'Busca literal nas três fontes configuradas e em até 100 conclusões recentes. Histórico exige Python 3.11+ e snapshot SQLite de até 32 MiB sem WAL ativo; arquivos da galeria contam nesse tamanho. Referências históricas não substituem regras atuais.'}
    fontes = []
    for papel in ('regras', 'produto', 'arquitetura'):
        try:
            fonte = _documento(raiz, papel, cfg['fontes'][papel])
            fontes.append(fonte)
            saida['fontes'].append({'tipo': 'documento', 'papel': papel, 'estado': 'disponivel'})
        except (OSError, ValueError, UnicodeError, OverflowError):
            saida['fontes'].append({'tipo': 'documento', 'papel': papel, 'estado': 'indisponivel_ou_excluida'})
            saida['limitado'] = True
    try:
        if not repo:
            raise ValueError('Histórico exige repositório configurado')
        entregas, limitado, omitidos = _entregas(raiz, repo)
        fontes.extend(entregas)
        saida['limitado'] |= limitado or bool(omitidos)
        saida['fontes'].append({'tipo': 'entrega', 'estado': 'disponivel', 'omitidos': omitidos})
    except (OSError, ValueError, sqlite3.Error, TypeError):
        saida['fontes'].append({'tipo': 'entrega', 'estado': 'indisponivel_ou_excluida',
                               'motivo': 'repositorio_nao_configurado' if not repo else 'limite_ou_integridade'})
        saida['limitado'] = True
    if _politica(raiz) != cfg:
        raise ValueError('Política mudou durante consulta')
    _conferir(cadeia)
    encontrados = []
    for fonte in fontes:
        texto = fonte['texto']
        # Matching literal, uma referência por fonte, sem regexp do usuário.
        for numero, linha in enumerate(texto.splitlines(), 1):
            baixa = linha.casefold()
            if all(t in baixa for t in termos):
                # Excertos limitados, sem realce HTML nem URLs extraídas do texto.
                indice = min((baixa.find(t) for t in termos), default=0)
                posicao = 0
                dobrados = 0
                for posicao, caractere in enumerate(linha):
                    if dobrados >= indice:
                        break
                    dobrados += len(caractere.casefold())
                posicao = max(0, posicao - 80)
                encontrados.append({**{k: v for k, v in fonte.items() if k != 'texto'},
                                    'linha': numero, 'trecho': linha[posicao:posicao + 400],
                                    'trecho_truncado': posicao > 0 or len(linha) > posicao + 400})
                break
    saida['limitado'] |= len(encontrados) > MAX_RESULTADOS
    saida['resultados'] = encontrados[:MAX_RESULTADOS]
    return saida


def buscar(projetos, ident, consulta):
    # Uma única imagem SQLite por processo; chamadas concorrentes não acumulam RAM.
    if not _CONSULTA.acquire(blocking=False):
        raise ValueError('Outra consulta em andamento; tente novamente')
    try:
        return _buscar(projetos, ident, consulta)
    finally:
        _CONSULTA.release()


def api(projetos, qs, ident):
    if not isinstance(ident, dict) or ident.get('permissao') != 'pc':
        return 403, {'ok': False, 'erro': 'Contexto disponível somente no PC'}
    if not isinstance(qs, dict) or set(qs) != {'projeto', 'q'} or any(not isinstance(v, list) or len(v) != 1 for v in qs.values()):
        return 400, {'ok': False, 'erro': 'Informe projeto e consulta únicos'}
    try:
        return 200, buscar(projetos, qs['projeto'][0], qs['q'][0])
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error):
        return 409, {'ok': False, 'erro': 'Contexto indisponível; confira projeto e consulta no PC'}
