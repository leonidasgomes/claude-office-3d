"""PROTÓTIPO DE TESTE: backup nativo de fixtures descartáveis no GitHub Windows.

Não integra PACOTE nem o atualizador. Sem entrada CLI para caminhos externos.
Habilita somente privilégios já presentes no token e restaura seu estado exato.
"""
from contextlib import contextmanager
import ctypes
from ctypes import wintypes as w
import hashlib
import os
from pathlib import Path
import shutil
import tempfile


PRIVILEGIOS = ('SeBackupPrivilege', 'SeRestorePrivilege', 'SeSecurityPrivilege')
BACKUP_SECURITY_INFORMATION = 0x10000


def exigir_ci():
    if (os.name != 'nt' or os.environ.get('GITHUB_ACTIONS') != 'true'
            or os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted'
            or os.environ.get('OFFICE_NATIVE_BACKUP_PROTOTYPE') != '1'):
        raise ValueError('Protótipo permitido somente no Windows descartável do GitHub')


class LUID(ctypes.Structure):
    _fields_ = [('LowPart', w.DWORD), ('HighPart', w.LONG)]


class LUID_ATTRIBUTES(ctypes.Structure):
    _fields_ = [('Luid', LUID), ('Attributes', w.DWORD)]


class TOKEN_PRIVILEGES(ctypes.Structure):
    _fields_ = [('PrivilegeCount', w.DWORD), ('Privileges', LUID_ATTRIBUTES * 3)]


class SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [('nLength', w.DWORD), ('lpSecurityDescriptor', w.LPVOID),
                ('bInheritHandle', w.BOOL)]


class API:
    def __init__(self):
        exigir_ci()
        self.k = ctypes.WinDLL('kernel32', use_last_error=True)
        self.a = ctypes.WinDLL('advapi32', use_last_error=True)
        self.n = ctypes.WinDLL('ntdll', use_last_error=True)
        specs = [
            (self.k, 'GetCurrentProcess', [], w.HANDLE),
            (self.k, 'CloseHandle', [w.HANDLE], w.BOOL),
            (self.k, 'LocalFree', [w.LPVOID], w.LPVOID),
            (self.k, 'CreateFileW', [w.LPCWSTR,w.DWORD,w.DWORD,w.LPVOID,w.DWORD,w.DWORD,w.HANDLE], w.HANDLE),
            (self.k, 'CreateDirectoryW', [w.LPCWSTR,w.LPVOID], w.BOOL),
            (self.k, 'GetFileTime', [w.HANDLE,w.LPVOID,w.LPVOID,w.LPVOID], w.BOOL),
            (self.k, 'SetFileTime', [w.HANDLE,w.LPVOID,w.LPVOID,w.LPVOID], w.BOOL),
            (self.k, 'SetFileAttributesW', [w.LPCWSTR,w.DWORD], w.BOOL),
            (self.k, 'GetFileInformationByHandleEx', [w.HANDLE,ctypes.c_int,w.LPVOID,w.DWORD], w.BOOL),
            (self.k, 'BackupRead', [w.HANDLE,w.LPVOID,w.DWORD,ctypes.POINTER(w.DWORD),w.BOOL,w.BOOL,ctypes.POINTER(w.LPVOID)], w.BOOL),
            (self.k, 'BackupWrite', [w.HANDLE,w.LPVOID,w.DWORD,ctypes.POINTER(w.DWORD),w.BOOL,w.BOOL,ctypes.POINTER(w.LPVOID)], w.BOOL),
            (self.a, 'OpenProcessToken', [w.HANDLE,w.DWORD,ctypes.POINTER(w.HANDLE)], w.BOOL),
            (self.a, 'GetTokenInformation', [w.HANDLE,ctypes.c_int,w.LPVOID,w.DWORD,ctypes.POINTER(w.DWORD)], w.BOOL),
            (self.a, 'LookupPrivilegeValueW', [w.LPCWSTR,w.LPCWSTR,ctypes.POINTER(LUID)], w.BOOL),
            (self.a, 'AdjustTokenPrivileges', [w.HANDLE,w.BOOL,w.LPVOID,w.DWORD,w.LPVOID,w.LPVOID], w.BOOL),
            (self.a, 'ConvertSidToStringSidW', [w.LPVOID,ctypes.POINTER(w.LPWSTR)], w.BOOL),
            (self.a, 'ConvertStringSecurityDescriptorToSecurityDescriptorW', [w.LPCWSTR,w.DWORD,ctypes.POINTER(w.LPVOID),w.LPVOID], w.BOOL),
            (self.a, 'ConvertSecurityDescriptorToStringSecurityDescriptorW', [w.LPVOID,w.DWORD,w.DWORD,ctypes.POINTER(w.LPWSTR),w.LPVOID], w.BOOL),
            (self.a, 'GetSecurityInfo', [w.HANDLE,ctypes.c_int,w.DWORD,w.LPVOID,w.LPVOID,w.LPVOID,w.LPVOID,ctypes.POINTER(w.LPVOID)], w.DWORD),
            (self.a, 'GetSecurityDescriptorControl', [w.LPVOID,ctypes.POINTER(w.WORD),ctypes.POINTER(w.DWORD)], w.BOOL),
            (self.n, 'NtQueryInformationFile', [w.HANDLE,w.LPVOID,w.LPVOID,w.ULONG,ctypes.c_int], w.LONG),
        ]
        for dll,nome,args,resultado in specs:
            f=getattr(dll,nome);f.argtypes=args;f.restype=resultado

    def ok(self, valor):
        if not valor: raise ctypes.WinError(ctypes.get_last_error())

    def token_info(self, token, classe):
        n=w.DWORD()
        self.a.GetTokenInformation(token,classe,None,0,ctypes.byref(n))
        if ctypes.get_last_error()!=122 or not 0<n.value<1024*1024:
            raise OSError('Token não inspecionável')
        b=ctypes.create_string_buffer(n.value)
        self.ok(self.a.GetTokenInformation(token,classe,b,len(b),ctypes.byref(n)))
        return b

    def estado_token(self, token):
        b=self.token_info(token,3)
        count=int.from_bytes(b.raw[:4],'little')
        if 4+count*ctypes.sizeof(LUID_ATTRIBUTES)>len(b): raise ValueError('Token inválido')
        itens=(LUID_ATTRIBUTES*count).from_buffer_copy(b.raw[4:])
        return {(x.Luid.LowPart,x.Luid.HighPart):x.Attributes for x in itens}

    def usuario(self, token):
        b=self.token_info(token,1)
        sid=ctypes.cast(b,ctypes.POINTER(w.LPVOID))[0]
        texto=w.LPWSTR()
        self.ok(self.a.ConvertSidToStringSidW(sid,ctypes.byref(texto)))
        try: return texto.value
        finally: self.k.LocalFree(ctypes.cast(texto,w.LPVOID))

    @contextmanager
    def descritor(self, sddl):
        sd=w.LPVOID()
        self.ok(self.a.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl,1,ctypes.byref(sd),None))
        try: yield sd
        finally: self.k.LocalFree(sd)

    @contextmanager
    def handle(self, p, escrita=False, criar=False, sd=None):
        acesso=(0x40000000|0xE0000|0x1000000) if escrita else (0x80000000|0x20000|0x1000000)
        sa=SECURITY_ATTRIBUTES(ctypes.sizeof(SECURITY_ATTRIBUTES),sd,False)
        h=self.k.CreateFileW(str(p),acesso,7,ctypes.byref(sa) if sd else None,
                            1 if criar else 3,0x02200000,None)
        if h==ctypes.c_void_p(-1).value: raise ctypes.WinError(ctypes.get_last_error())
        try: yield h
        finally: self.ok(self.k.CloseHandle(h))

    def seguranca(self, h):
        sd=w.LPVOID();texto=w.LPWSTR();control=w.WORD();revision=w.DWORD()
        erro=self.a.GetSecurityInfo(h,1,BACKUP_SECURITY_INFORMATION,None,None,None,None,ctypes.byref(sd))
        if erro: raise ctypes.WinError(erro)
        try:
            self.ok(self.a.GetSecurityDescriptorControl(sd,ctypes.byref(control),ctypes.byref(revision)))
            self.ok(self.a.ConvertSecurityDescriptorToStringSecurityDescriptorW(sd,1,15,ctypes.byref(texto),None))
            return {'sddl':texto.value,'control':control.value,'revision':revision.value}
        finally:
            if texto:self.k.LocalFree(ctypes.cast(texto,w.LPVOID))
            self.k.LocalFree(sd)

    def tempos(self,h):
        c,a,m=w.FILETIME(),w.FILETIME(),w.FILETIME()
        self.ok(self.k.GetFileTime(h,ctypes.byref(c),ctypes.byref(a),ctypes.byref(m)))
        return c,a,m

    def sem_ea(self,h):
        iosb=(ctypes.c_void_p*2)();ea=w.ULONG()
        if self.n.NtQueryInformationFile(h,iosb,ctypes.byref(ea),ctypes.sizeof(ea),7)!=0:
            raise OSError('EA não inspecionável')
        if ea.value:raise ValueError('EA fora do escopo deste protótipo')

    def streams(self,h):
        b=ctypes.create_string_buffer(1024*1024)
        if not self.k.GetFileInformationByHandleEx(h,7,b,len(b)):
            if ctypes.get_last_error()==38:return []
            raise ctypes.WinError(ctypes.get_last_error())
        dados=b.raw;pos=0;nomes=[]
        while True:
            prox=int.from_bytes(dados[pos:pos+4],'little');n=int.from_bytes(dados[pos+4:pos+8],'little')
            if n%2 or pos+24+n>len(dados):raise ValueError('Streams inválidos')
            nome=dados[pos+24:pos+24+n].decode('utf-16-le')
            if not nome.endswith(':$DATA') or not nome.startswith(':'):raise ValueError('Stream desconhecido')
            nomes.append(nome)
            if not prox:return sorted(nomes)
            if prox<24+n or pos+prox+24>len(dados):raise ValueError('Streams inválidos')
            pos+=prox


class Privilegios:
    """Não atribui direitos novos. Um privilégio ausente bloqueia antes da fixture."""
    def __init__(self):
        self.api=API();self.token=w.HANDLE();self.ativo=False

    def _ajustar(self, valores):
        p=TOKEN_PRIVILEGES();p.PrivilegeCount=len(valores)
        for i,(luid,attrs) in enumerate(valores):
            p.Privileges[i].Luid=LUID(*luid);p.Privileges[i].Attributes=attrs
        ctypes.set_last_error(0)
        ok=self.api.a.AdjustTokenPrivileges(self.token,False,ctypes.byref(p),0,None,None)
        erro=ctypes.get_last_error()
        if not ok or erro:raise ctypes.WinError(erro)

    def __enter__(self):
        self.api.ok(self.api.a.OpenProcessToken(self.api.k.GetCurrentProcess(),0x28,ctypes.byref(self.token)))
        self.alvos=[]
        try:
            self.antes=self.api.estado_token(self.token)
            for nome in PRIVILEGIOS:
                luid=LUID();self.api.ok(self.api.a.LookupPrivilegeValueW(None,nome,ctypes.byref(luid)))
                chave=(luid.LowPart,luid.HighPart)
                if chave not in self.antes:raise PermissionError('Privilégio ausente: '+nome)
                self.alvos.append((chave,self.antes[chave]))
            self.usuario=self.api.usuario(self.token)
            self._ajustar([(luid,attrs|2) for luid,attrs in self.alvos])
            estado=self.api.estado_token(self.token)
            if any(not estado[luid]&2 for luid,_ in self.alvos):raise PermissionError('Privilégios não habilitados')
            self.ativo=True
            return self
        except BaseException:
            try:
                if hasattr(self,'antes'):self._restaurar()
            finally:self.api.k.CloseHandle(self.token)
            raise

    def _restaurar(self):
        self.ativo=False
        if self.alvos:self._ajustar(self.alvos)
        if self.api.estado_token(self.token)!=self.antes:
            raise RuntimeError('Estado original do token não foi restaurado')

    def __exit__(self,*exc):
        try:self._restaurar()
        finally:self.api.ok(self.api.k.CloseHandle(self.token))


class Espaco:
    """Único domínio de escrita: uma árvore nova, privada e sintética por contexto."""
    def __init__(self, privilegios):
        if not privilegios.ativo:raise PermissionError('Contexto de privilégios inativo')
        self.privilegios=privilegios;self.api=privilegios.api
        self.sddl_privado='D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;'+privilegios.usuario+')'
        self.sddl_auditado=self.sddl_privado+'S:P(AU;OICISAFA;FA;;;WD)(ML;OICI;NW;;;ME)'

    def __enter__(self):
        self.temp=tempfile.TemporaryDirectory(prefix='office-backup-ci-sintetico-')
        self.root=Path(self.temp.name)/'fixtures'
        try:
            from atualizar_windows import _API
            _API().volume(Path(self.temp.name))
            self._mkdir(self.root,self.sddl_privado)
            return self
        except BaseException:
            self.temp.cleanup();raise

    def __exit__(self,*exc):self.temp.cleanup()

    def caminho(self,rel):
        if not self.privilegios.ativo:raise PermissionError('Contexto de privilégios inativo')
        p=Path(rel)
        if p.is_absolute() or p.drive or not p.parts or any(n in ('.','..') or ':' in n for n in p.parts):
            raise ValueError('Somente caminhos relativos à fixture')
        alvo=self.root/p
        if self.root not in alvo.parents:raise ValueError('Fora da fixture')
        atual=self.root
        from atualizar_windows import validar_nome
        for nome in p.parts:
            validar_nome(nome)
            atual=atual/nome
            try:
                st=atual.lstat()
            except FileNotFoundError:
                continue
            if st.st_file_attributes&0x400 or (atual.is_file() and st.st_nlink!=1):
                raise ValueError('Reparse/hardlink fora do escopo')
        if self.root.lstat().st_file_attributes&0x400:raise ValueError('Raiz alterada')
        return alvo

    def _mkdir(self,p,sddl):
        with self.api.descritor(sddl) as sd:
            sa=SECURITY_ATTRIBUTES(ctypes.sizeof(SECURITY_ATTRIBUTES),sd,False)
            self.api.ok(self.api.k.CreateDirectoryW(str(p),ctypes.byref(sa)))

    def criar_pasta(self,rel,sddl=None):
        p=self.caminho(rel)
        self._mkdir(p,sddl or self.sddl_privado)
        return p

    def criar_arquivo(self,rel,dados,sddl=None):
        p=self.caminho(rel)
        with self.api.descritor(sddl or self.sddl_privado) as sd:
            with self.api.handle(p,escrita=True,criar=True,sd=sd):pass
        p.write_bytes(dados)
        return p

    def _entradas(self,rel):
        raiz=self.caminho(rel)
        if not raiz.is_dir():raise ValueError('Fixture deve ser pasta')
        entradas=[raiz]
        def erro(exc):raise exc
        for pasta,dirs,files in os.walk(raiz,followlinks=False,onerror=erro):
            for nome in sorted(dirs+files):
                p=Path(pasta)/nome
                self.caminho(p.relative_to(self.root))
                entradas.append(p)
        for p in entradas:
            attrs=p.lstat().st_file_attributes
            if attrs&~(0x10|0x20|0x80):raise ValueError('Atributos especiais fora do protótipo')
        return entradas

    def snapshot(self,rel):
        raiz=self.caminho(rel);resultado={}
        for p in self._entradas(rel):
            with self.api.handle(p) as h:
                self.api.sem_ea(h)
                c,a,m=self.api.tempos(h)
                streams={}
                for nome in self.api.streams(h):
                    alvo=p if nome=='::$DATA' else Path(str(p)+nome[:-6])
                    streams[nome]=hashlib.sha256(alvo.read_bytes()).hexdigest()
                resultado[p.relative_to(raiz).as_posix()]={
                    'security':self.api.seguranca(h),'attributes':p.lstat().st_file_attributes,
                    'creation':(c.dwHighDateTime<<32)|c.dwLowDateTime,
                    'modified':(m.dwHighDateTime<<32)|m.dwLowDateTime,'streams':streams}
        return resultado

    def copiar(self,origem,destino,observer=None):
        src=self.caminho(origem);dst=self.caminho(destino)
        if dst.exists() or src==dst or src in dst.parents or dst in src.parents:
            raise ValueError('Cópias devem ser independentes e destino deve ser novo')
        antes=self.snapshot(origem);observer=observer or (lambda evento,path:None)
        criado=False
        try:
            self._mkdir(dst,self.sddl_privado);criado=True
            entradas=self._entradas(origem)
            # Diretórios primeiro; metadados/timestamps restaurados depois dos filhos.
            for p in entradas[1:]:
                alvo=dst/p.relative_to(src)
                if p.is_dir():self._mkdir(alvo,self.sddl_privado)
            for p in sorted(entradas,key=lambda x:len(x.parts),reverse=True):
                alvo=dst/p.relative_to(src)
                with self.api.handle(p) as leitura:
                    self.api.sem_ea(leitura)
                    tempos=self.api.tempos(leitura)
                    with self.api.descritor(self.sddl_privado) as sd:
                        with self.api.handle(alvo,escrita=True,criar=not p.is_dir(),sd=sd) as escrita:
                            observer('before_write',alvo)
                            self._transferir(leitura,escrita)
                            self.api.ok(self.api.k.SetFileTime(escrita,*[ctypes.byref(t) for t in tempos]))
                    self.api.ok(self.api.k.SetFileAttributesW(str(alvo),p.lstat().st_file_attributes))
                    observer('after_copy',alvo)
            observer('before_commit',dst)
            if self.snapshot(origem)!=antes:raise ValueError('Fonte mudou durante o backup')
            if self.snapshot(destino)!=antes:raise ValueError('Metadados ou dados da cópia não conferem')
            return antes
        except BaseException:
            if criado and dst.exists():shutil.rmtree(dst)
            raise

    def _transferir(self,leitura,escrita):
        rctx=w.LPVOID();wctx=w.LPVOID();b=ctypes.create_string_buffer(65536)
        quantidade=w.DWORD();gravado=w.DWORD()
        try:
            while True:
                self.api.ok(self.api.k.BackupRead(leitura,b,len(b),ctypes.byref(quantidade),False,True,ctypes.byref(rctx)))
                if not quantidade.value:break
                self.api.ok(self.api.k.BackupWrite(escrita,b,quantidade.value,ctypes.byref(gravado),False,True,ctypes.byref(wctx)))
                if gravado.value!=quantidade.value:raise OSError('BackupWrite incompleto; cópia recusada')
        finally:
            try:self.api.ok(self.api.k.BackupRead(leitura,None,0,ctypes.byref(quantidade),True,True,ctypes.byref(rctx)))
            finally:self.api.ok(self.api.k.BackupWrite(escrita,None,0,ctypes.byref(gravado),True,True,ctypes.byref(wctx)))
