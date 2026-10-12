"""Instala/atualiza a edição 2.x offline. Sem --aplicar, apenas faz a prévia.

Execute a partir do pacote novo extraído, com o escritório parado. Não instala
providers, não executa o pacote anterior e nunca altera os projetos cadastrados.
"""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import stat
import sys
import tempfile
import uuid

# A prévia standalone não cria caches no pacote extraído.
sys.dont_write_bytecode = True

MANIFESTO = '.office-pacote.json'
EDICAO = {'edicao': 'office-multi-provider', 'formato': 1}


def soma(dados):
    return hashlib.sha256(dados).hexdigest()


def caminho(valor):
    p = Path(os.path.abspath(valor))
    if any(a.is_symlink() or (a.exists() and getattr(a.lstat(), 'st_file_attributes', 0) & 0x400)
           for a in [p, *p.parents]):
        raise ValueError('Caminho com link simbólico: ' + str(p))
    return p


def ler(p, limite=16 * 1024 * 1024):
    if p.is_symlink() or not p.is_file() or p.stat().st_nlink != 1:
        raise ValueError('Arquivo ausente ou link simbólico: ' + str(p))
    with p.open('rb') as f:
        b = f.read(limite + 1)
    if len(b) > limite:
        raise ValueError('Arquivo excede o limite: ' + str(p))
    return b


def json_ler(p):
    return json.loads(ler(p, 1024 * 1024).decode('utf-8-sig'))


def pacote(raiz, completo=False):
    edicao = json_ler(raiz / 'EDICAO.json')
    if edicao != EDICAO or type(edicao.get('formato')) is not int:
        raise ValueError('Edição incompatível')
    versao = ler(raiz / 'VERSION', 100).decode().strip()
    if not versao.startswith('2.'):
        raise ValueError('Somente a edição 2.x é suportada')
    # Lê a lista sem importar/executar código do pacote anterior.
    try:
        arvore = ast.parse(ler(raiz / 'instalar.py').decode('utf-8-sig'))
    except SyntaxError as exc:
        raise ValueError('Sintaxe inválida em instalar.py') from exc
    listas = [n.value for n in arvore.body if isinstance(n, ast.Assign)
              and any(isinstance(t, ast.Name) and t.id == 'PACOTE' for t in n.targets)]
    if len(listas) != 1:
        raise ValueError('Lista PACOTE ausente ou ambígua')
    nomes = ast.literal_eval(listas[0])
    if not isinstance(nomes, list) or not nomes:
        raise ValueError('Lista PACOTE inválida')
    import instalar
    permitidos = set(instalar.PACOTE)
    if completo and set(nomes) != permitidos:
        raise ValueError('Pacote novo incompleto: lista de arquivos não corresponde ao atualizador')
    hashes = {}
    for nome in nomes:
        if not isinstance(nome, str) or nome not in permitidos:
            raise ValueError('Arquivo não reconhecido no pacote; revise a compatibilidade')
        p = Path(nome)
        if (not isinstance(nome, str) or p.is_absolute() or '..' in p.parts
                or '\\' in nome or ':' in nome or not p.parts
                or p.parts[0] in ('dados', '.venv', '.office', '.git', 'vendor')
                or p.name in ('config.json', MANIFESTO)):
            raise ValueError('Caminho inválido no pacote')
        if nome.casefold() in {n.casefold() for n in hashes}:
            raise ValueError('Arquivo duplicado no pacote')
        arq = caminho(raiz / nome)
        b = ler(arq)
        if arq.suffix == '.py':
            try:
                compile(b, nome, 'exec')
            except SyntaxError as exc:
                raise ValueError('Sintaxe inválida no arquivo do pacote: ' + nome) from exc
        hashes[nome] = soma(b)
    if not {'VERSION', 'EDICAO.json', 'instalar.py', 'servidor.py'} <= hashes.keys():
        raise ValueError('Pacote incompleto')
    return {'formato': 1, 'versao': versao, 'arquivos': hashes}


def inventario(raiz):
    """Inclui arquivos pessoais e links sem seguir links nem ler destinos externos."""
    resultado = {}
    if not raiz.exists():
        return resultado
    resultado['.'] = ['pasta', stat.S_IMODE(raiz.stat().st_mode)]
    def erro(exc):
        raise exc
    for pasta, dirs, files in os.walk(raiz, followlinks=False, onerror=erro):
        for nome in sorted(dirs + files):
            p = Path(pasta) / nome
            rel = p.relative_to(raiz).as_posix()
            if getattr(p.lstat(), 'st_file_attributes', 0) & 0x400 and not p.is_symlink():
                raise ValueError('Junção/reparse point não suportado: ' + str(p))
            if p.is_mount():
                raise ValueError('Ponto de montagem dentro da instalação: ' + str(p))
            if p.is_symlink():
                resultado[rel] = ['link', os.readlink(p)]
            elif p.is_file():
                if p.stat().st_nlink != 1:
                    raise ValueError('Hardlink não suportado: ' + str(p))
                h = hashlib.sha256()
                with p.open('rb') as f:
                    for bloco in iter(lambda: f.read(1024 * 1024), b''):
                        h.update(bloco)
                resultado[rel] = ['arquivo', h.hexdigest(), stat.S_IMODE(p.stat().st_mode)]
            elif p.is_dir():
                resultado[rel] = ['pasta', stat.S_IMODE(p.stat().st_mode)]
            else:
                raise ValueError('Arquivo especial não suportado: ' + str(p))
    return resultado


def parado(destino):
    # Linux: detecta também servidor iniciado com --porta diferente, antes do bind.
    proc = Path('/proc')
    if proc.is_dir():
        for item in proc.iterdir():
            if not item.name.isdigit():
                continue
            try:
                args = (item / 'cmdline').read_bytes().split(b'\0')
                if any(Path(os.fsdecode(a)).name == 'servidor.py' for a in args if a):
                    cwd = (item / 'cwd').resolve()
                    if any((cwd / os.fsdecode(a)).resolve() == destino / 'servidor.py'
                           for a in args if a and Path(os.fsdecode(a)).name == 'servidor.py'):
                        raise ValueError('Pare o servidor desta instalação antes da atualização')
                elif b'-m' in args and b'servidor' in args and (item / 'cwd').resolve() == destino:
                    raise ValueError('Pare o servidor desta instalação antes da atualização')
            except (OSError, RuntimeError):
                continue
    cfg = json_ler(destino / 'config.json')
    if not isinstance(cfg, dict):
        raise ValueError('Configuração inválida')
    porta = cfg.get('porta', 8765)
    if type(porta) is not int or not 1 <= porta <= 65535:
        raise ValueError('Porta inválida na configuração')
    # Não encerra processos. Recusa porta ocupada, mesmo se pertencer a outro app.
    for familia, host in ((socket.AF_INET, '127.0.0.1'), (socket.AF_INET6, '::1')):
        try:
            with socket.socket(familia, socket.SOCK_STREAM) as s:
                s.settimeout(0.2)
                if s.connect_ex((host, porta)) == 0:
                    raise ValueError('Pare o escritório: porta configurada está em uso')
        except OSError:
            if familia == socket.AF_INET:
                raise
    return cfg


def preparar(destino, origem=None, anterior=None, config=None):
    origem = caminho(origem or Path(__file__).parent)
    destino = caminho(destino)
    if origem == destino or origem in destino.parents or destino in origem.parents:
        raise ValueError('Extraia o pacote em pasta separada da instalação')
    if anterior:
        referencia = caminho(anterior)
        if any(referencia == p or referencia in p.parents or p in referencia.parents for p in (destino, origem)):
            raise ValueError('Pacote anterior deve ficar separado da instalação e do pacote novo')
    novo = pacote(origem, completo=True)
    antes = inventario(destino)
    existente = any(n != '.' for n in antes)
    if existente:
        parado(destino)
        if json_ler(destino / 'EDICAO.json') != EDICAO:
            raise ValueError('Destino de outra edição')
        versao = ler(destino / 'VERSION', 100).decode().strip()
        if not versao.startswith('2.'):
            raise ValueError('Destino incompatível')
        if config is not None:
            raise ValueError('Atualização preserva config.json; não passe --config')
        if (destino / MANIFESTO).exists():
            antigo = json_ler(destino / MANIFESTO)
            if not isinstance(antigo, dict) or type(antigo.get('formato')) is not int or antigo.get('formato') != 1 or antigo.get('versao') != versao:
                raise ValueError('Manifesto instalado inválido')
            # Validar nomes/estrutura também comparando ao pacote instalado.
            instalado = pacote(destino)
            if antigo != instalado:
                raise ValueError('Arquivos do pacote foram personalizados ou estão incompletos')
        elif anterior:
            antigo = pacote(caminho(anterior))
            if antigo['versao'] != versao:
                raise ValueError('Pacote anterior não corresponde à versão instalada')
            for nome, hash_esperado in antigo['arquivos'].items():
                b = ler(caminho(destino / nome))
                if soma(b) != hash_esperado:
                    # O instalador histórico gera seus quatro atalhos a partir de
                    # constantes. Só reconhecemos exatamente as variantes conhecidas.
                    import instalar
                    texto = instalar.ATALHOS.get(nome)
                    variantes = [] if texto is None else [texto.encode(), texto.replace('\n', '\r\n').encode()]
                    if b not in variantes:
                        raise ValueError('Arquivo personalizado; preserve e revise antes de atualizar: ' + nome)
        else:
            raise ValueError('Instalação sem manifesto: informe --pacote-anterior com a versão original extraída')
        for nome in novo['arquivos']:
            alvo = caminho(destino / nome)
            if alvo.exists() and nome not in antigo['arquivos']:
                raise ValueError('Arquivo do usuário ocupa novo caminho do pacote: ' + nome)
    else:
        antigo = None
        if config is None or not isinstance(config, dict):
            raise ValueError('Instalação nova exige configuração explícita')
        import configuracao
        config = configuracao.normalizar(config)
    return {'origem': str(origem), 'destino': str(destino),
            'anterior': str(caminho(anterior)) if anterior else None,
            'config': config, 'novo': novo, 'antigo': antigo, 'antes': antes,
            'existente': existente}



def validar_metadados(raiz):
    if os.name == 'nt':
        raise ValueError('Atualização/reversão de instalação existente no Windows ainda requer cópia com ACL nativa; nenhuma troca realizada')
    if not sys.platform.startswith('linux') or not hasattr(os, 'listxattr'):
        raise ValueError('Esta plataforma não oferece a inspeção de ACL qualificada; atualização existente recusada')
    if any('acl' in n.lower() for n in os.listxattr(raiz.parent, follow_symlinks=False)):
        raise ValueError('Pasta pai com ACL personalizada/herdável; operação recusada')
    if raiz.parent.stat().st_mode & stat.S_ISGID:
        raise ValueError('Pasta pai com herança de grupo especial; operação recusada')
    for p in [raiz, *raiz.rglob('*')]:
        st = p.lstat()
        if st.st_uid != os.geteuid() or st.st_gid != os.getegid():
            raise ValueError('Proprietário/grupo diferente do usuário atual; cópia recusada: ' + str(p))
        if hasattr(os, 'listxattr'):
            atributos = os.listxattr(p, follow_symlinks=False)
            if any('acl' in n.lower() or n.startswith('security.') for n in atributos):
                raise ValueError('ACL personalizada exige cópia nativa; operação recusada: ' + str(p))
        if stat.S_IMODE(st.st_mode) & 0o7000:
            raise ValueError('Permissões especiais exigem revisão: ' + str(p))


def gravar_json(p, dados):
    with os.fdopen(os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w', encoding='utf-8') as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)
        f.write('\n'); f.flush(); os.fsync(f.fileno())


def aplicar(plano):
    destino = Path(plano['destino'])
    destino.parent.mkdir(parents=True, exist_ok=True)
    lock = destino.parent / ('.' + destino.name + '.atualizacao.lock')
    with lock.open('x', encoding='utf-8') as f:
        f.write(str(os.getpid()))
    stage = None
    backup = destino.parent / (destino.name + '.backup-' + uuid.uuid4().hex)
    recibo = backup.with_name(backup.name + '.json')
    movido = False
    try:
        atual = preparar(destino, plano['origem'], plano['anterior'], plano['config'])
        if atual != plano:
            raise ValueError('Arquivos mudaram desde a prévia; refaça o plano')
        if plano['existente']:
            validar_metadados(destino)
        if plano['antigo'] == plano['novo']:
            return {'alterado': False, 'destino': str(destino)}
        necessario = sum(p.stat().st_size for p in destino.rglob('*') if p.is_file() and not p.is_symlink()) if destino.exists() else 0
        necessario += sum((Path(plano['origem']) / n).stat().st_size for n in plano['novo']['arquivos'])
        if shutil.disk_usage(destino.parent).free < necessario + 16 * 1024 * 1024:
            raise ValueError('Espaço livre insuficiente para cópia completa e backup')
        stage = Path(tempfile.mkdtemp(prefix='.' + destino.name + '.preparando-', dir=destino.parent))
        if destino.exists():
            shutil.copytree(destino, stage, dirs_exist_ok=True, symlinks=True)
        # Não remove arquivos antigos: preserva inclusive módulos descontinuados.
        for nome in plano['novo']['arquivos']:
            alvo = stage / nome
            alvo.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(Path(plano['origem']) / nome, alvo)
        if not plano['existente']:
            gravar_json(stage / 'config.json', plano['config'])
            (stage / 'dados').mkdir(exist_ok=True)
        manifesto = stage / MANIFESTO
        if manifesto.exists():
            manifesto.unlink()
        gravar_json(manifesto, plano['novo'])
        if pacote(stage, completo=True) != plano['novo']:
            raise ValueError('Cópia do pacote não confere')
        depois = inventario(stage)
        for nome, registro in plano['antes'].items():
            if nome not in plano['novo']['arquivos'] and nome != MANIFESTO and depois.get(nome) != registro:
                raise ValueError('Cópia de arquivo preservado não confere: ' + nome)
        if plano['existente']:
            parado(destino)
        if inventario(destino) != plano['antes']:
            raise ValueError('Instalação mudou durante a cópia; nenhuma troca realizada')
        registro = {'formato': 1, 'destino': str(destino), 'backup': str(backup),
                    'antes': plano['antes'], 'depois': depois, 'stage': str(stage)}
        if len(json.dumps(registro, ensure_ascii=False, indent=2).encode('utf-8')) > 64 * 1024 * 1024 - 1:
            raise ValueError('Inventário excede o limite seguro de recuperação')
        gravar_json(recibo, registro)
        if destino.exists():
            os.rename(destino, backup); movido = True
        try:
            os.rename(stage, destino); stage = None
        except BaseException:
            if movido:
                os.rename(backup, destino); movido = False
            raise
        return {'alterado': True, 'destino': str(destino),
                'backup': str(backup) if movido else None, 'recibo': str(recibo)}
    finally:
        if stage is not None and stage.exists():
            shutil.rmtree(stage)
        lock.unlink(missing_ok=True)


def reverter(recibo, executar=False):
    recibo = caminho(recibo)
    r = json.loads(ler(recibo, 64 * 1024 * 1024).decode('utf-8'))
    destino, backup = caminho(r['destino']), caminho(r['backup'])
    if (type(r.get('formato')) is not int or r.get('formato') != 1 or backup.parent != destino.parent
            or recibo != backup.with_name(backup.name + '.json')
            or not backup.name.startswith(destino.name + '.backup-')):
        raise ValueError('Recibo inválido')
    if inventario(backup) != r['antes'] or not backup.is_dir():
        raise ValueError('Backup ausente ou alterado; restauração recusada')
    if r['antes'] and any(n != '.' for n in r['antes']):
        if json_ler(backup / 'EDICAO.json') != EDICAO or not ler(backup / 'VERSION', 100).decode().strip().startswith('2.'):
            raise ValueError('Backup não é uma instalação 2.x')
        if not isinstance(json_ler(backup / 'config.json'), dict):
            raise ValueError('Configuração do backup inválida')
    if destino.exists():
        parado(destino)
        if inventario(destino) != r['depois']:
            raise ValueError('Instalação contém trabalho posterior; restauração recusada para não perder dados')
    resultado = {'destino': str(destino), 'backup': str(backup), 'recuperacao_interrompida': not destino.exists()}
    if not executar:
        return resultado
    validar_metadados(backup)
    if destino.exists():
        validar_metadados(destino)
    lock = destino.parent / ('.' + destino.name + '.atualizacao.lock')
    # Lock órfão nunca é removido implicitamente. Confira o processo antes de removê-lo.
    with lock.open('x', encoding='utf-8') as f:
        f.write(str(os.getpid()))
    guardado = destino.parent / (destino.name + '.antes-reversao-' + uuid.uuid4().hex)
    try:
        if destino.exists():
            parado(destino)
        if inventario(backup) != r['antes'] or (destino.exists() and inventario(destino) != r['depois']):
            raise ValueError('Arquivos mudaram; refaça a prévia')
        if destino.exists():
            os.rename(destino, guardado)
        try:
            os.rename(backup, destino)
        except BaseException:
            if guardado.exists():
                os.rename(guardado, destino)
            raise
        resultado['preservado'] = str(guardado) if guardado.exists() else None
        return resultado
    finally:
        lock.unlink(missing_ok=True)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--destino', type=Path)
    p.add_argument('--pacote-anterior', type=Path)
    p.add_argument('--config', type=Path, help='somente instalação nova')
    p.add_argument('--reverter', type=Path, help='recibo JSON da atualização, inclusive recuperação interrompida')
    p.add_argument('--aplicar', action='store_true')
    a = p.parse_args(argv)
    try:
        if a.reverter:
            if a.destino or a.config or a.pacote_anterior:
                raise ValueError('--reverter não aceita opções de instalação')
            resultado = reverter(a.reverter, a.aplicar)
        else:
            if not a.destino:
                raise ValueError('Informe --destino')
            plano = preparar(a.destino, anterior=a.pacote_anterior, config=json_ler(a.config) if a.config else None)
            resultado = aplicar(plano) if a.aplicar else {
                'destino': plano['destino'], 'versao': plano['novo']['versao'],
                'existente': plano['existente'], 'arquivos_pacote': len(plano['novo']['arquivos']),
                'preserva': 'configuração, dados, projetos, skills, hooks e porta'}
        print(json.dumps(resultado, ensure_ascii=False, indent=2))
        if not a.aplicar:
            print('Prévia sem alterações. Revise e repita com --aplicar.')
        return 0
    except (OSError, ValueError, SyntaxError, KeyError, TypeError) as exc:
        print('Operação não concluída: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
