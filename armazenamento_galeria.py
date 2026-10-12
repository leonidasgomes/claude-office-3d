"""Bytes imutáveis da galeria; não migra, compacta nem remove histórico.

Somente novas mutações Linux qualificadas. A trava global é a mesma do
atualizador; não substitui parar os demais processos do escritório.
"""
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import re
import stat
import sys
import uuid

MAX_ARQUIVO = 1024 * 1024
MAX_FISICO = 110 * MAX_ARQUIVO
MAX_ENTRADAS = 10020
HASH = re.compile(r'[0-9a-f]{64}\Z')
TEMP = re.compile(r'\.captura-[0-9a-f]{32}\Z')
PASTA = 'galeria-blobs-v1'
APP = Path(__file__).absolute().parent


def _id(s):
    return s.st_dev, s.st_ino, s.st_mode


# Registrado ao carregar o código, não depois de esperar pelo atualizador.
APP_ID = _id(APP.lstat())
DIR_FD = all(f in os.supports_dir_fd for f in (os.open, os.link, os.unlink))


def _plataforma():
    if (not sys.platform.startswith('linux') or not hasattr(os, 'O_NOFOLLOW') or
        not hasattr(os, 'O_DIRECTORY') or not DIR_FD):
        raise ValueError('Novos snapshots externos exigem Linux com operações de arquivo qualificadas')


def _regular(s, privado=False):
    if not stat.S_ISREG(s.st_mode) or s.st_nlink != 1:
        raise ValueError('Snapshot/trava não é arquivo regular exclusivo')
    if privado and (s.st_uid != os.geteuid() or stat.S_IMODE(s.st_mode) & 0o077):
        raise ValueError('Armazenamento da galeria sem privacidade local')


class Pasta:
    """Mantém cada componente aberto e confere os nomes antes de devolver dados."""
    def __init__(self, caminho):
        self.caminho = Path(caminho)
        self.fds = []; self.cadeia = []
        if not self.caminho.is_absolute() or '..' in self.caminho.parts:
            raise ValueError('Pasta não canônica')
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        try:
            fd = os.open('/', flags); self.fds.append(fd)
            for nome in self.caminho.parts[1:]:
                pai = fd
                fd = os.open(nome, flags, dir_fd=pai); self.fds.append(fd)
                s = os.fstat(fd)
                self.cadeia.append((pai, nome, fd, _id(s)))
            self.fd = fd
            self.conferir()
        except BaseException:
            self.close(); raise

    def conferir(self):
        for pai, nome, fd, identidade in self.cadeia:
            if (_id(os.fstat(fd)) != identidade or
                _id(os.stat(nome, dir_fd=pai, follow_symlinks=False)) != identidade):
                raise ValueError('Pasta mudou durante operação')

    def close(self):
        for fd in reversed(self.fds):
            os.close(fd)
        self.fds = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        try:
            if exc[0] is None:
                self.conferir()
        finally:
            self.close()


def _app():
    if _id(APP.lstat()) != APP_ID or not stat.S_ISDIR(APP_ID[2]):
        raise ValueError('Instalação substituída; reinicie este processo antes de registrar')


def _ler(pasta, nome, limite=MAX_ARQUIVO):
    pasta.conferir()
    antes = os.stat(nome, dir_fd=pasta.fd, follow_symlinks=False)
    _regular(antes, privado=True)
    if antes.st_size > limite:
        raise ValueError('Snapshot excede limite')
    fd = os.open(nome, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=pasta.fd)
    with os.fdopen(fd, 'rb') as f:
        s = os.fstat(f.fileno()); _regular(s, privado=True)
        assinatura = lambda v: (_id(v), v.st_nlink, v.st_size, v.st_mtime_ns, v.st_ctime_ns)
        if assinatura(s) != assinatura(antes):
            raise ValueError('Snapshot mudou durante leitura')
        bruto = f.read(limite + 1)
        fim = os.fstat(f.fileno())
    pasta.conferir()
    depois = os.stat(nome, dir_fd=pasta.fd, follow_symlinks=False)
    if len(bruto) > limite or assinatura(antes) != assinatura(fim) or assinatura(antes) != assinatura(depois):
        raise ValueError('Snapshot mudou durante leitura')
    return bruto


def _pasta_privada(pasta):
    s = os.fstat(pasta.fd)
    if s.st_uid != os.geteuid() or stat.S_IMODE(s.st_mode) != 0o700:
        raise ValueError('Pasta de snapshots sem privacidade local')
    if hasattr(os, 'listxattr') and any('acl' in n.lower() for n in os.listxattr(pasta.fd)):
        raise ValueError('ACL de snapshots ainda não qualificada')


def ler(projeto, sha):
    """Leitura de corpo sem escrita; SQL de metadados mantém seu contrato anterior."""
    _plataforma(); _app()
    if not isinstance(sha, str) or not HASH.fullmatch(sha):
        raise ValueError('Hash de snapshot inválido')
    from gestao_cli import pasta_dados
    dados = pasta_dados(projeto)
    if not dados.is_relative_to(APP):
        raise ValueError('Dados fora desta instalação')
    with Pasta(APP), Pasta(dados / PASTA) as pasta:
        _pasta_privada(pasta)
        bruto = _ler(pasta, sha)
        if hashlib.sha256(bruto).hexdigest() != sha:
            raise ValueError('Integridade do snapshot não confirmada')
        _app()
        return bruto


class Escrita:
    def __init__(self, dados):
        self.dados = dados

    @contextmanager
    def _pasta(self):
        with Pasta(self.dados) as pai:
            try:
                os.mkdir(PASTA, 0o700, dir_fd=pai.fd)
                os.fsync(pai.fd)
            except FileExistsError:
                pass
            with Pasta(self.dados / PASTA) as pasta:
                _pasta_privada(pasta)
                yield pasta

    def _inventario(self, pasta):
        total = quantidade = 0
        # Não materializa diretórios arbitrariamente grandes em uma lista.
        with os.scandir(pasta.fd) as entradas:
            for entrada in entradas:
                if not HASH.fullmatch(entrada.name) and not TEMP.fullmatch(entrada.name):
                    raise ValueError('Entrada desconhecida na galeria; concilie no PC')
                s = entrada.stat(follow_symlinks=False); _regular(s, privado=True)
                if s.st_size > MAX_ARQUIVO:
                    raise ValueError('Snapshot órfão excede limite')
                quantidade += 1; total += s.st_size
                if quantidade > MAX_ENTRADAS or total > MAX_FISICO:
                    raise ValueError('Armazenamento físico da galeria atingiu limite; histórico preservado')
        pasta.conferir()
        return total, quantidade

    def gravar(self, capturados):
        """Reserva orçamento de toda a captura antes do primeiro corpo novo."""
        unicos = {}
        for _, tamanho, _, _, sha, corpo in capturados:
            if (type(tamanho) is not int or not isinstance(corpo, bytes) or
                tamanho != len(corpo) or tamanho > MAX_ARQUIVO or
                not isinstance(sha, str) or not HASH.fullmatch(sha) or
                hashlib.sha256(corpo).hexdigest() != sha):
                raise ValueError('Captura inválida')
            if sha in unicos and unicos[sha] != corpo:
                raise ValueError('Hash de captura conflitante')
            unicos[sha] = corpo
        with self._pasta() as pasta:
            total, quantidade = self._inventario(pasta)
            novos = {}
            for sha, corpo in unicos.items():
                try:
                    anterior = _ler(pasta, sha)
                except FileNotFoundError:
                    novos[sha] = corpo
                else:
                    if anterior != corpo:
                        raise ValueError('Snapshot existente diverge; histórico preservado')
            # Reserva também a duplicação transitória do nome durante link+unlink.
            extra = sum(len(b) for b in novos.values())
            margem = max((len(b) for b in novos.values()), default=0)
            if total + extra + margem > MAX_FISICO or quantidade + len(novos) + bool(novos) > MAX_ENTRADAS:
                raise ValueError('Armazenamento físico da galeria atingiu limite; histórico preservado')
            for sha, corpo in novos.items():
                nome = '.captura-' + uuid.uuid4().hex
                fd = os.open(nome, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=pasta.fd)
                # Interrupções preservam corpos parciais/órfãos; nunca os sobrescrevem.
                with os.fdopen(fd, 'wb') as f:
                    criado = os.fstat(f.fileno()); _regular(criado, privado=True)
                    f.write(corpo); f.flush(); os.fsync(f.fileno())
                if _ler(pasta, nome) != corpo:
                    raise ValueError('Captura persistida diverge')
                pasta.conferir()
                os.link(nome, sha, src_dir_fd=pasta.fd, dst_dir_fd=pasta.fd, follow_symlinks=False)
                temporario = os.stat(nome, dir_fd=pasta.fd, follow_symlinks=False)
                final = os.stat(sha, dir_fd=pasta.fd, follow_symlinks=False)
                if (_id(temporario) != _id(criado) or _id(final) != _id(criado) or
                    temporario.st_nlink != 2 or final.st_nlink != 2):
                    raise ValueError('Publicação do snapshot mudou; concilie no PC')
                os.unlink(nome, dir_fd=pasta.fd)
                os.fsync(pasta.fd)
                if _ler(pasta, sha) != corpo:
                    raise ValueError('Integridade do snapshot não confirmada')
            self._inventario(pasta)


@contextmanager
def mutacao(projeto):
    """Exclusão global O_EXCL do PR99, depois orçamento por projeto via flock."""
    _plataforma(); _app()
    import fcntl
    from gestao_cli import pasta_dados
    # A pasta pai fica pinada antes de qualquer acesso aos dados do projeto.
    with Pasta(APP.parent) as pai:
        nome = '.' + APP.name + '.atualizacao.lock'
        fd = os.open(nome, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=pai.fd)
        identidade = _id(os.fstat(fd))
        try:
            os.write(fd, str(os.getpid()).encode('ascii')); os.fsync(fd); os.fsync(pai.fd)
            _app(); pai.conferir()
            with Pasta(APP):
                dados = pasta_dados(projeto)
                if not dados.is_relative_to(APP):
                    raise ValueError('Dados fora desta instalação')
                with Pasta(dados) as pasta:
                    banco = os.stat('tarefas.db', dir_fd=pasta.fd, follow_symlinks=False)
                    _regular(banco)
                    trava = os.open('.galeria-orcamento.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
                                    0o600, dir_fd=pasta.fd)
                    try:
                        _regular(os.fstat(trava), privado=True)
                        fcntl.flock(trava, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        os.fsync(pasta.fd)
                        yield Escrita(dados)
                        pasta.conferir(); _app()
                        depois = os.stat('tarefas.db', dir_fd=pasta.fd, follow_symlinks=False)
                        _regular(depois)
                        if _id(depois) != _id(banco):
                            raise ValueError('Diário substituído durante registro')
                    finally:
                        os.close(trava)
        finally:
            os.close(fd)
            pai.conferir()
            final = os.stat(nome, dir_fd=pai.fd, follow_symlinks=False)
            _regular(final, privado=True)
            if _id(final) != identidade:
                raise ValueError('Trava foi substituída; concilie no PC')
            os.unlink(nome, dir_fd=pai.fd); os.fsync(pai.fd)
