"""Qualificação de laboratório: Windows/NTFS descartável do GitHub, dados fictícios.

Não exercita nem habilita o atualizador de produção. Oráculo próprio compara
bytes, IDs, owner/group, DACL/SACL (incluindo herança/proteção), streams e EAs.
A suíte recusa execução fora do runner hospedado; ausência de capacidade é falha,
nunca SKIP/sucesso nativo simulado. Alterações de segurança só em fixtures privadas.
"""
from contextlib import contextmanager
import ctypes
from ctypes import wintypes as w
import hashlib
import os
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import backup_windows_nativo as b


class LUID(ctypes.Structure):
    _fields_ = [('LowPart', w.DWORD), ('HighPart', w.LONG)]


class Privilegio(ctypes.Structure):
    _fields_ = [('Luid', LUID), ('Attributes', w.DWORD)]


class Streams(ctypes.Structure):
    _fields_ = [('StreamSize', ctypes.c_longlong), ('cStreamName', w.WCHAR * 296)]


class IOStatus(ctypes.Structure):
    _fields_ = [('Status', ctypes.c_void_p), ('Information', ctypes.c_size_t)]


class Oraculo:
    """APIs independentes do helper: não usa BackupRead nem seu snapshot."""

    def __init__(self):
        self.k = ctypes.WinDLL('kernel32', use_last_error=True)
        self.a = ctypes.WinDLL('advapi32', use_last_error=True)
        self.n = ctypes.WinDLL('ntdll', use_last_error=True)
        pp = ctypes.POINTER(w.LPVOID)
        specs = (
            (self.k, 'GetCurrentProcess', [], w.HANDLE),
            (self.k, 'CloseHandle', [w.HANDLE], w.BOOL),
            (self.k, 'LocalFree', [w.LPVOID], w.LPVOID),
            (self.k, 'CreateFileW', [w.LPCWSTR, w.DWORD, w.DWORD, w.LPVOID,
             w.DWORD, w.DWORD, w.HANDLE], w.HANDLE),
            (self.k, 'FindFirstStreamW', [w.LPCWSTR, ctypes.c_int,
             ctypes.POINTER(Streams), w.DWORD], w.HANDLE),
            (self.k, 'FindNextStreamW', [w.HANDLE, ctypes.POINTER(Streams)], w.BOOL),
            (self.k, 'FindClose', [w.HANDLE], w.BOOL),
            (self.a, 'OpenProcessToken', [w.HANDLE, w.DWORD,
             ctypes.POINTER(w.HANDLE)], w.BOOL),
            (self.a, 'GetTokenInformation', [w.HANDLE, ctypes.c_int, w.LPVOID,
             w.DWORD, ctypes.POINTER(w.DWORD)], w.BOOL),
            (self.a, 'LookupPrivilegeNameW', [w.LPCWSTR, ctypes.POINTER(LUID),
             w.LPWSTR, ctypes.POINTER(w.DWORD)], w.BOOL),
            (self.a, 'ConvertSidToStringSidW', [w.LPVOID,
             ctypes.POINTER(w.LPWSTR)], w.BOOL),
            (self.a, 'GetNamedSecurityInfoW', [w.LPWSTR, ctypes.c_int, w.DWORD,
             pp, pp, pp, pp, pp], w.DWORD),
            (self.a, 'GetLengthSid', [w.LPVOID], w.DWORD),
            (self.a, 'GetSecurityDescriptorControl', [w.LPVOID,
             ctypes.POINTER(w.WORD), ctypes.POINTER(w.DWORD)], w.BOOL),
            (self.a, 'ConvertSecurityDescriptorToStringSecurityDescriptorW',
             [w.LPVOID, w.DWORD, w.DWORD, ctypes.POINTER(w.LPWSTR),
              ctypes.POINTER(w.DWORD)], w.BOOL),
            (self.n, 'NtSetEaFile', [w.HANDLE, ctypes.POINTER(IOStatus),
             w.LPVOID, w.ULONG], w.LONG),
            (self.n, 'NtQueryEaFile', [w.HANDLE, ctypes.POINTER(IOStatus),
             w.LPVOID, w.ULONG, ctypes.c_ubyte, w.LPVOID, w.ULONG,
             ctypes.POINTER(w.ULONG), ctypes.c_ubyte], w.LONG),
        )
        for dll, name, args, result in specs:
            f = getattr(dll, name)
            f.argtypes, f.restype = args, result

    @staticmethod
    def conferir(ok):
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())

    @contextmanager
    def token(self):
        token = w.HANDLE()
        self.conferir(self.a.OpenProcessToken(self.k.GetCurrentProcess(), 8,
                                             ctypes.byref(token)))
        try:
            yield token
        finally:
            self.conferir(self.k.CloseHandle(token))

    def informacao_token(self, token, classe):
        size = w.DWORD()
        self.a.GetTokenInformation(token, classe, None, 0, ctypes.byref(size))
        if not size.value:
            raise ctypes.WinError(ctypes.get_last_error())
        buf = ctypes.create_string_buffer(size.value)
        self.conferir(self.a.GetTokenInformation(token, classe, buf, size.value,
                                                ctypes.byref(size)))
        return buf

    def privilegios(self):
        with self.token() as token:
            buf = self.informacao_token(token, 3)  # TokenPrivileges
            count = ctypes.cast(buf, ctypes.POINTER(w.DWORD))[0]
            entries = ctypes.cast(ctypes.addressof(buf) + 4,
                                  ctypes.POINTER(Privilegio))
            result = {}
            for i in range(count):
                size = w.DWORD(256)
                name = ctypes.create_unicode_buffer(size.value)
                self.conferir(self.a.LookupPrivilegeNameW(
                    None, ctypes.byref(entries[i].Luid), name, ctypes.byref(size)))
                result[name.value] = entries[i].Attributes
            return result

    def sid_usuario(self):
        with self.token() as token:
            buf = self.informacao_token(token, 1)  # TOKEN_USER começa por PSID.
            sid = ctypes.cast(buf, ctypes.POINTER(w.LPVOID))[0]
            text = w.LPWSTR()
            self.conferir(self.a.ConvertSidToStringSidW(sid, ctypes.byref(text)))
            try:
                return text.value
            finally:
                self.k.LocalFree(ctypes.cast(text, w.LPVOID))

    def seguranca(self, path):
        owner, group, dacl, sacl, sd = (w.LPVOID() for _ in range(5))
        # BACKUP_SECURITY_INFORMATION: inclui auditoria, integridade e demais ACEs.
        flags = 0x10000
        error = self.a.GetNamedSecurityInfoW(str(path), 1, flags,
            ctypes.byref(owner), ctypes.byref(group), ctypes.byref(dacl),
            ctypes.byref(sacl), ctypes.byref(sd))
        if error:
            raise ctypes.WinError(error)
        text = w.LPWSTR()
        try:
            control, revision = w.WORD(), w.DWORD()
            self.conferir(self.a.GetSecurityDescriptorControl(
                sd, ctypes.byref(control), ctypes.byref(revision)))
            self.conferir(self.a.ConvertSecurityDescriptorToStringSecurityDescriptorW(
                sd, 1, 0x0F, ctypes.byref(text), None))
            def sid_bytes(ptr):
                return ctypes.string_at(ptr, self.a.GetLengthSid(ptr)) if ptr else None
            def acl_bytes(ptr):
                # ACL header: revision, reserved, AclSize, AceCount, reserved.
                size = int.from_bytes(ctypes.string_at(ptr, 4)[2:4], 'little') if ptr else 0
                return ctypes.string_at(ptr, size) if ptr else None
            return {'owner': sid_bytes(owner), 'group': sid_bytes(group),
                    'dacl': acl_bytes(dacl), 'sacl': acl_bytes(sacl),
                    'control': control.value, 'sddl': text.value}
        finally:
            if text:
                self.k.LocalFree(ctypes.cast(text, w.LPVOID))
            self.k.LocalFree(sd)

    @contextmanager
    def handle(self, path, access=0x88, share=7):
        h = self.k.CreateFileW(str(path), access, share, None, 3, 0x02200000, None)
        if h == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            yield h
        finally:
            self.conferir(self.k.CloseHandle(h))

    def streams(self, path):
        result, data = {}, Streams()
        h = self.k.FindFirstStreamW(str(path), 0, ctypes.byref(data), 0)
        if h == ctypes.c_void_p(-1).value:
            if ctypes.get_last_error() == 38:
                return result
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            while True:
                name = data.cStreamName
                with open(str(path) + name, 'rb') as stream:
                    result[name] = hashlib.sha256(stream.read()).hexdigest()
                if not self.k.FindNextStreamW(h, ctypes.byref(data)):
                    if ctypes.get_last_error() != 38:
                        raise ctypes.WinError(ctypes.get_last_error())
                    break
        finally:
            self.conferir(self.k.FindClose(h))
        return result

    def gravar_ea(self, path):
        # FILE_FULL_EA_INFORMATION. Nenhuma alteração fora da fixture.
        name, value = b'OFFICE_TEST', b'EA-SINTETICO\x00\xff'
        raw = struct.pack('<IBBH', 0, 0, len(name), len(value)) + name + b'\0' + value
        buf, iosb = ctypes.create_string_buffer(raw), IOStatus()
        with self.handle(path, access=0x10) as h:  # FILE_WRITE_EA
            status = self.n.NtSetEaFile(h, ctypes.byref(iosb), buf, len(raw))
        if status != 0:
            raise OSError('NtSetEaFile fixture falhou: 0x%08x' % (status & 0xFFFFFFFF))
        return {name: (0, value)}

    def eas(self, path):
        buf, iosb = ctypes.create_string_buffer(65536), IOStatus()
        with self.handle(path, access=8) as h:
            status = self.n.NtQueryEaFile(h, ctypes.byref(iosb), buf, len(buf),
                                         False, None, 0, None, True)
        if status & 0xFFFFFFFF == 0xC0000052:  # STATUS_NO_EAS_ON_FILE
            return {}
        if status != 0:
            raise OSError('NtQueryEaFile falhou: 0x%08x' % (status & 0xFFFFFFFF))
        raw, pos, result = buf.raw[:iosb.Information], 0, {}
        while raw:
            if pos + 8 > len(raw):
                raise ValueError('Resposta EA truncada')
            nxt, flags, nlen, vlen = struct.unpack_from('<IBBH', raw, pos)
            end = pos + 8 + nlen + 1 + vlen
            if end > len(raw) or raw[pos + 8 + nlen] != 0:
                raise ValueError('Resposta EA inválida')
            name = raw[pos + 8:pos + 8 + nlen]
            result[name] = (flags, raw[pos + 9 + nlen:end])
            if not nxt:
                return result
            if nxt < end - pos or pos + nxt >= len(raw):
                raise ValueError('Offset EA inválido')
            pos += nxt
        return result

    def arvore(self, root):
        root = Path(root)
        if not root.exists():
            return None
        result = {}
        for path in [root, *sorted(root.rglob('*'))]:
            st = path.stat()
            rel = '.' if path == root else path.relative_to(root).as_posix()
            result[rel] = {'pasta': path.is_dir(), 'attrs': st.st_file_attributes,
                'mtime_ns': st.st_mtime_ns, 'creation_ns': st.st_birthtime_ns,
                'seguranca': self.seguranca(path), 'streams': self.streams(path),
                'eas': self.eas(path)}
        return result


class FalhaSintetica(RuntimeError):
    pass


class TrocaSintetica:
    """Harness de falhas, NÃO é implementação da transação do atualizador.

    Mantém as árvores antigas/novas e recupera com uma terceira cópia nativa.
    Comprova o material de backup em cada fronteira; não qualifica produção.
    """
    def __init__(self, espaco):
        self.e = espaco
        self.antes = espaco.copiar('app', 'backup')
        espaco.copiar('app', 'nova')
        espaco.caminho('nova/versao.txt').write_bytes(b'versao nova sintetica')
        self.depois = espaco.snapshot('nova')

    def _renomear(self, src, dst, name, interrupt=None, locked=None):
        if interrupt == name + ':antes':
            raise FalhaSintetica(interrupt)
        source, target = self.e.caminho(src), self.e.caminho(dst)
        if locked is not None and locked[0] == name:
            # A chamada real encontra um handle sem FILE_SHARE_DELETE.
            with locked[1].handle(source, access=0, share=3):
                os.rename(source, target)
        else:
            os.rename(source, target)
        if interrupt == name + ':depois':
            raise FalhaSintetica(interrupt)

    def trocar(self, interrupt=None, locked=None):
        self._renomear('app', 'retida', 'reter', interrupt, locked)
        self._renomear('nova', 'app', 'publicar', interrupt, locked)

    def recuperar(self, interrupt=None):
        e = self.e
        if e.snapshot('backup') != self.antes:
            raise ValueError('Backup mudou; recuperação recusada')
        # Dados posteriores são preservados e exigem decisão humana.
        if e.caminho('retida').exists() and e.snapshot('retida') != self.antes:
            raise ValueError('Dados posteriores na árvore retida')
        current = e.snapshot('app') if e.caminho('app').exists() else None
        if current not in (None, self.antes, self.depois):
            raise ValueError('Dados posteriores no aplicativo')
        if current == self.antes:
            return
        if not e.caminho('restauracao').exists():
            e.copiar('backup', 'restauracao')
        elif e.snapshot('restauracao') != self.antes:
            raise ValueError('Cópia de recuperação mudou')
        if current is not None:
            self._renomear('app', 'quarentena', 'quarentena', interrupt)
        self._renomear('restauracao', 'app', 'restaurar', interrupt)


class BackupNativo(unittest.TestCase):
    def setUp(self):
        self.oracle = Oraculo()
        antes = self.oracle.privilegios()
        self.addCleanup(lambda: self.assertEqual(self.oracle.privilegios(), antes,
            'O token do processo deve voltar exatamente ao estado inicial'))

    @contextmanager
    def laboratorio(self):
        with b.Privilegios() as priv:
            with b.Espaco(priv) as espaco:
                yield priv, espaco

    def fixture(self, espaco, name='origem'):
        sid = self.oracle.sid_usuario()
        # Owner e grupo diferentes; ACLs protegidas e herdáveis; auditoria e
        # integridade média reais. Não habilita política global de auditoria.
        sddl = ('O:SYG:BAD:P(A;OICI;FA;;;' + sid + ')(A;OICI;FA;;;SY)'
                'S:P(AU;OICISAFA;FW;;;WD)(ML;OICI;NW;;;ME)')
        espaco.criar_pasta(name, sddl=sddl)
        # Criação padrão do Windows herda realmente as ACEs da raiz auditada.
        espaco.caminho(name + '/dados').mkdir()
        espaco.caminho(name + '/dados/vazia').mkdir()
        espaco.caminho(name + '/versao.txt').write_bytes(b'versao antiga\r\n')
        espaco.caminho(name + '/dados/arte ç.bin').write_bytes(bytes(range(256)) * 8192)
        espaco.caminho(name + '/dados/vazio').write_bytes(b'')
        # Segundo descritor protegido, sem herdar; comparação cobre ambos.
        espaco.criar_arquivo(name + '/privado.txt', b'PRIVADO-FICTICIO\x00\xff',
            sddl='O:SYG:BAD:P(A;;FA;;;' + sid + ')S:P(AU;SAFA;FR;;;WD)(ML;;NW;;;ME)')
        return espaco.caminho(name)

    def test_000_diagnosticar_mascaras_de_seguranca_sem_reduzir_exigencia(self):
        # Diagnóstico somente leitura do mesmo objeto/handle sintético. Não aceita
        # máscaras reduzidas como substituição do descritor completo obrigatório.
        masks = (0x7, 0x8, 0x10, 0x20, 0x40, 0x80, 0x100, 0x1FF, 0x10000, 0x1007F, 0x101FF)
        with self.laboratorio() as (priv, e):
            path = self.fixture(e)
            enabled = self.oracle.privilegios()
            print('DIAG_PRIVILEGIOS ' + ' '.join(
                name + '=' + str(bool(enabled.get(name, 0) & 2))
                for name in b.PRIVILEGIOS), flush=True)
            results = {}
            with priv.api.handle(path) as handle:
                for mask in masks:
                    by_handle, by_name = w.LPVOID(), w.LPVOID()
                    try:
                        handle_error = priv.api.a.GetSecurityInfo(
                            handle, 1, mask, None, None, None, None,
                            ctypes.byref(by_handle))
                        name_error = self.oracle.a.GetNamedSecurityInfoW(
                            str(path), 1, mask, None, None, None, None,
                            ctypes.byref(by_name))
                        results[mask] = (handle_error, name_error)
                        print('DIAG_SD mask=0x%05X handle_error=%d name_error=%d'
                              % (mask, handle_error, name_error), flush=True)
                    finally:
                        if by_handle:
                            priv.api.k.LocalFree(by_handle)
                        if by_name:
                            self.oracle.k.LocalFree(by_name)
            self.assertEqual(results[0x10000], (0, 0),
                             'A consulta original completa continua obrigatória')

    def test_privilegios_temporarios_restaurados_em_sucesso_e_erro(self):
        before = self.oracle.privilegios()
        for fail in (False, True):
            with self.subTest(falha=fail):
                try:
                    with b.Privilegios():
                        during = self.oracle.privilegios()
                        for name in ('SeBackupPrivilege', 'SeRestorePrivilege', 'SeSecurityPrivilege'):
                            self.assertTrue(during[name] & 2, name)
                        if fail:
                            raise FalhaSintetica('erro depois de habilitar')
                except FalhaSintetica:
                    self.assertTrue(fail)
                self.assertEqual(self.oracle.privilegios(), before)

    def test_gate_recusa_sinais_ausentes_e_runner_autogerenciado(self):
        for env in ({'GITHUB_ACTIONS': '', 'RUNNER_ENVIRONMENT': 'github-hosted'},
                    {'GITHUB_ACTIONS': 'true', 'RUNNER_ENVIRONMENT': 'self-hosted'},
                    {'GITHUB_ACTIONS': 'true', 'RUNNER_ENVIRONMENT': ''},
                    {'OFFICE_NATIVE_BACKUP_PROTOTYPE': ''}):
            with self.subTest(env=env), patch.dict(os.environ, env):
                with self.assertRaisesRegex(ValueError, 'descartável|GitHub'):
                    b.Privilegios()

    def test_habilitacao_parcial_injetada_restaura_token_nativo(self):
        before = self.oracle.privilegios()
        priv = b.Privilegios()
        real, calls = priv._ajustar, []
        def parcial(values):
            calls.append(list(values))
            if len(calls) == 1:
                # Habilita realmente apenas o primeiro privilégio do token.
                # Injeção representa ERROR_NOT_ALL_ASSIGNED após sucesso parcial.
                real(values[:1])
                raise ctypes.WinError(1300)
            return real(values)
        with patch.object(priv, '_ajustar', side_effect=parcial), \
             patch.object(b.tempfile, 'TemporaryDirectory',
                          side_effect=AssertionError('não criar fixture sem privilégios')):
            with self.assertRaises(OSError) as error:
                with priv:
                    self.fail('habilitação parcial não pode autorizar fixture')
        self.assertEqual(error.exception.winerror, 1300)
        self.assertGreaterEqual(len(calls), 2, 'restauração precisa ser tentada')
        self.assertEqual(self.oracle.privilegios(), before)
        self.assertFalse(priv.ativo)

    def test_privilegio_ausente_injetado_bloqueia_sem_mutacao(self):
        # Não remove privilégios reais. Uma leitura injetada omite SeSecurity;
        # a comparação com o token real continua independente e não é simulada.
        before = self.oracle.privilegios()
        priv = b.Privilegios()
        luid = b.LUID()
        priv.api.ok(priv.api.a.LookupPrivilegeValueW(None, 'SeSecurityPrivilege',
                                                   ctypes.byref(luid)))
        key, calls, real = (luid.LowPart, luid.HighPart), [], priv.api.estado_token
        def ausente(token):
            state = real(token)
            calls.append(True)
            if len(calls) == 1:
                state.pop(key)
            return state
        with patch.object(priv.api, 'estado_token', side_effect=ausente), \
             patch.object(b.tempfile, 'TemporaryDirectory',
                          side_effect=AssertionError('não criar fixture sem privilégios')):
            with self.assertRaises((PermissionError, RuntimeError)):
                with priv:
                    self.fail('privilégio ausente não pode autorizar fixture')
        self.assertEqual(self.oracle.privilegios(), before)
        self.assertFalse(priv.ativo)

    def test_backup_independente_bytes_sd_heranca_e_restauracao(self):
        with self.laboratorio() as (_, e):
            source = self.fixture(e)
            before = self.oracle.arvore(source)
            self.assertEqual(before['.']['seguranca']['control'] & 0x3000, 0x3000)
            self.assertIn('O:SYG:BA', before['.']['seguranca']['sddl'])
            for component in ('owner', 'group', 'dacl', 'sacl'):
                self.assertIsNotNone(before['.']['seguranca'][component], component)
            self.assertFalse(before['dados/arte ç.bin']['seguranca']['control'] & 0x1000)
            self.assertIn('(AU;', before['.']['seguranca']['sddl'])
            self.assertIn('(ML;', before['.']['seguranca']['sddl'])
            self.assertIn('ID', before['dados/arte ç.bin']['seguranca']['sddl'])
            e.copiar('origem', 'backup')
            backup = e.caminho('backup')
            self.assertEqual(self.oracle.arvore(backup), before)
            self.assertEqual(self.oracle.arvore(source), before)
            for rel in ('versao.txt', 'dados/arte ç.bin', 'privado.txt'):
                self.assertNotEqual((source / rel).stat().st_ino, (backup / rel).stat().st_ino)
            (source / 'versao.txt').write_bytes(b'nova versao')
            self.assertEqual(self.oracle.arvore(backup), before)
            e.copiar('backup', 'restaurado')
            self.assertEqual(self.oracle.arvore(e.caminho('restaurado')), before)

    def test_staging_privado_antes_de_qualquer_byte(self):
        with self.laboratorio() as (_, e):
            self.fixture(e)
            observed = []
            def observar(event, path):
                if event != 'before_write':
                    return
                path = Path(path)
                sd = self.oracle.seguranca(path)
                self.assertTrue(sd['control'] & 0x1000, 'DACL deve ser protegida')
                for broad in (';;;WD)', ';;;BU)', ';;;AU)'):
                    # Só examina DACL; SACL de auditoria pode mencionar Everyone.
                    self.assertNotIn(broad, sd['sddl'].split('D:', 1)[1].split('S:', 1)[0])
                self.assertEqual(path.stat().st_size, 0)
                observed.append(path)
            e.copiar('origem', 'backup', observer=observar)
            self.assertTrue(observed, 'A observação precisa alcançar a escrita nativa')

    def test_ads_nativos_preservados_em_arquivo_pasta_e_raiz(self):
        with self.laboratorio() as (_, e):
            source = self.fixture(e)
            for path in (source, source / 'dados', source / 'privado.txt'):
                with open(str(path) + ':sentinela', 'wb') as stream:
                    stream.write(b'ADS-FICTICIO\x00\xff')
            before = self.oracle.arvore(source)
            e.copiar('origem', 'backup')
            self.assertEqual(self.oracle.arvore(e.caminho('backup')), before)
            self.assertEqual(self.oracle.arvore(source), before)

    def test_eas_reais_recusadas_sem_mutacao(self):
        for relative in ('origem', 'origem/dados', 'origem/privado.txt'):
            with self.subTest(alvo=relative), self.laboratorio() as (_, e):
                source = self.fixture(e)
                target = e.caminho(relative)
                expected = self.oracle.gravar_ea(target)
                self.assertEqual(self.oracle.eas(target), expected)
                before = self.oracle.arvore(source)
                with self.assertRaisesRegex((ValueError, OSError), 'EA|estendido'):
                    e.copiar('origem', 'backup')
                self.assertFalse(e.caminho('backup').exists())
                self.assertEqual(self.oracle.arvore(source), before)

    def test_falha_real_de_acesso_nao_publica_copia(self):
        # Handle sem compartilhamento produz falha real de CreateFile/BackupRead.
        with self.laboratorio() as (_, e):
            source = self.fixture(e)
            before = self.oracle.arvore(source)
            with self.oracle.handle(source / 'privado.txt', access=0x80000000, share=0):
                with self.assertRaises(OSError):
                    e.copiar('origem', 'backup')
            self.assertFalse(e.caminho('backup').exists())
            self.assertEqual(self.oracle.arvore(source), before)

    def test_falha_injetada_de_stream_aborta_e_permite_repetir(self):
        for api_name in ('BackupRead', 'BackupWrite'):
            with self.subTest(api=api_name), self.laboratorio() as (priv, e):
                source = self.fixture(e)
                before = self.oracle.arvore(source)
                real = getattr(priv.api.k, api_name)
                hits, aborts = [], []
                other = 'BackupWrite' if api_name == 'BackupRead' else 'BackupRead'
                other_real = getattr(priv.api.k, other)
                def falhar(*args):
                    # Abort=true deve chegar à API real para liberar contexto.
                    if args[4]:
                        aborts.append(api_name)
                        return real(*args)
                    hits.append(True)
                    ctypes.set_last_error(5)
                    return False
                with patch.object(priv.api.k, api_name, side_effect=falhar), \
                     patch.object(priv.api.k, other, wraps=other_real) as other_calls:
                    with self.assertRaises(OSError):
                        e.copiar('origem', 'backup')
                self.assertTrue(hits)
                self.assertTrue(aborts, 'abort do contexto que falhou precisa ser tentado')
                self.assertTrue(any(call.args[4] for call in other_calls.call_args_list),
                                'abort do segundo contexto precisa ser tentado')
                self.assertFalse(e.caminho('backup').exists())
                self.assertEqual(self.oracle.arvore(source), before)
                e.copiar('origem', 'backup')
                self.assertEqual(self.oracle.arvore(e.caminho('backup')), before)

    def test_escrita_curta_injetada_recusa_resultado_nativo(self):
        with self.laboratorio() as (priv, e):
            source = self.fixture(e)
            before = self.oracle.arvore(source)
            real, seen, aborts = priv.api.k.BackupWrite, [], []
            def encurtar(*args):
                if args[4]:
                    aborts.append(True)
                ok = real(*args)
                if not args[4] and ok:
                    amount = ctypes.cast(args[3], ctypes.POINTER(w.DWORD))
                    if amount[0]:
                        amount[0] -= 1
                        seen.append(True)
                return ok
            with patch.object(priv.api.k, 'BackupWrite', side_effect=encurtar):
                with self.assertRaisesRegex(OSError, 'incompleto|curta'):
                    e.copiar('origem', 'backup')
            self.assertTrue(seen)
            self.assertTrue(aborts, 'abort após escrita curta precisa ser tentado')
            self.assertFalse(e.caminho('backup').exists())
            self.assertEqual(self.oracle.arvore(source), before)

    def test_falha_de_leitura_de_sd_nao_cria_destino(self):
        with self.laboratorio() as (priv, e):
            source = self.fixture(e)
            before = self.oracle.arvore(source)
            with patch.object(priv.api.a, 'GetSecurityInfo', return_value=5) as denied:
                with self.assertRaises(OSError) as error:
                    e.copiar('origem', 'backup')
            self.assertEqual(error.exception.winerror, 5)
            self.assertTrue(denied.call_args_list)
            self.assertTrue(all(call.args[2] == 0x10000 for call in denied.call_args_list))
            self.assertFalse(e.caminho('backup').exists())
            self.assertEqual(self.oracle.arvore(source), before)

    def test_hardlink_real_recusado_sem_mutacao(self):
        with self.laboratorio() as (_, e):
            source = self.fixture(e)
            os.link(source / 'versao.txt', e.caminho('origem/outro.txt'))
            self.assertEqual((source / 'versao.txt').stat().st_nlink, 2)
            before = self.oracle.arvore(source)
            with self.assertRaisesRegex(ValueError, 'hardlink|Hardlink'):
                e.copiar('origem', 'backup')
            self.assertFalse(e.caminho('backup').exists())
            self.assertEqual(self.oracle.arvore(source), before)

    def test_falhas_observador_antes_commit_e_recopia(self):
        for event in ('before_write', 'after_copy', 'before_commit'):
            with self.subTest(evento=event), self.laboratorio() as (_, e):
                source = self.fixture(e)
                before = self.oracle.arvore(source)
                reached = []
                def observar(actual, path):
                    if actual == event:
                        reached.append(actual)
                        raise FalhaSintetica(actual)
                with self.assertRaises(FalhaSintetica):
                    e.copiar('origem', 'backup', observer=observar)
                self.assertTrue(reached)
                self.assertFalse(e.caminho('backup').exists())
                self.assertEqual(self.oracle.arvore(source), before)
                e.copiar('origem', 'backup')
                self.assertEqual(self.oracle.arvore(e.caminho('backup')), before)

    def test_fonte_ou_backup_mudado_antes_commit_nao_e_aprovado(self):
        for which in ('origem', 'backup'):
            with self.subTest(alvo=which), self.laboratorio() as (_, e):
                source = self.fixture(e)
                before = self.oracle.arvore(source)
                changed = []
                def observar(event, path):
                    if event == 'before_commit':
                        e.caminho(which + '/versao.txt').write_bytes(b'mudou durante copia')
                        changed.append(True)
                with self.assertRaisesRegex(ValueError, 'mudou|conferem|cópia'):
                    e.copiar('origem', 'backup', observer=observar)
                self.assertTrue(changed)
                self.assertFalse(e.caminho('backup').exists())
                if which == 'backup':
                    self.assertEqual(self.oracle.arvore(source), before)
                else:
                    self.assertEqual((source / 'versao.txt').read_bytes(), b'mudou durante copia')

    def test_recuperacao_sintetica_em_cada_fronteira_de_rename(self):
        for point in ('reter:antes', 'reter:depois', 'publicar:antes', 'publicar:depois'):
            with self.subTest(fronteira=point), self.laboratorio() as (_, e):
                source = self.fixture(e, 'app')
                before = self.oracle.arvore(source)
                transaction = TrocaSintetica(e)
                with self.assertRaises(FalhaSintetica):
                    transaction.trocar(interrupt=point)
                self.assertEqual(self.oracle.arvore(e.caminho('backup')), before)
                transaction.recuperar()
                self.assertEqual(self.oracle.arvore(e.caminho('app')), before)
                self.assertEqual(self.oracle.arvore(e.caminho('backup')), before)

    def test_recuperacao_sintetica_interrompida_pode_repetir(self):
        for point in ('quarentena:antes', 'quarentena:depois',
                      'restaurar:antes', 'restaurar:depois'):
            with self.subTest(fronteira=point), self.laboratorio() as (_, e):
                source = self.fixture(e, 'app')
                before = self.oracle.arvore(source)
                transaction = TrocaSintetica(e)
                transaction.trocar()
                with self.assertRaises(FalhaSintetica):
                    transaction.recuperar(interrupt=point)
                transaction.recuperar()
                self.assertEqual(self.oracle.arvore(e.caminho('app')), before)
                self.assertEqual(self.oracle.arvore(e.caminho('backup')), before)

    def test_falha_windows_real_em_cada_rename_permite_recuperar(self):
        for point in ('reter', 'publicar'):
            with self.subTest(fronteira=point), self.laboratorio() as (_, e):
                source = self.fixture(e, 'app')
                before = self.oracle.arvore(source)
                transaction = TrocaSintetica(e)
                with self.assertRaises(OSError) as error:
                    transaction.trocar(locked=(point, self.oracle))
                self.assertIn(error.exception.winerror, (5, 32))
                transaction.recuperar()
                self.assertEqual(self.oracle.arvore(e.caminho('app')), before)
                self.assertEqual(self.oracle.arvore(e.caminho('backup')), before)

    def test_recuperacao_sintetica_recusa_backup_ou_dados_posteriores(self):
        for changed in ('backup/privado.txt', 'app/dados/novo.txt', 'retida/dados/novo.txt'):
            with self.subTest(alvo=changed), self.laboratorio() as (_, e):
                self.fixture(e, 'app')
                transaction = TrocaSintetica(e)
                transaction.trocar()
                e.caminho(changed).write_bytes(b'nao perder trabalho posterior')
                before = self.oracle.arvore(e.root)
                with self.assertRaisesRegex(ValueError, 'Backup mudou|Dados posteriores'):
                    transaction.recuperar()
                self.assertEqual(self.oracle.arvore(e.root), before)

    def test_destino_existente_nao_sobrescrito_e_escopo_confinado(self):
        with self.laboratorio() as (_, e):
            source = self.fixture(e)
            e.criar_pasta('destino')
            e.criar_arquivo('destino/novo.txt', b'trabalho posterior ficticio')
            before, target_before = self.oracle.arvore(source), self.oracle.arvore(e.caminho('destino'))
            with self.assertRaises((ValueError, FileExistsError)):
                e.copiar('origem', 'destino')
            self.assertEqual(self.oracle.arvore(source), before)
            self.assertEqual(self.oracle.arvore(e.caminho('destino')), target_before)
            for rel in ('../fora', '/absoluto', r'C:\\fora', r'\\servidor\pasta'):
                with self.subTest(caminho=rel), self.assertRaises(ValueError):
                    e.caminho(rel)


def exigir_runner_descartavel():
    if (os.name != 'nt' or os.environ.get('GITHUB_ACTIONS') != 'true'
            or os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted'
            or os.environ.get('OFFICE_NATIVE_BACKUP_PROTOTYPE') != '1'):
        raise SystemExit('RECUSADO: suíte apenas no Windows descartável github-hosted, '
                         'com GITHUB_ACTIONS=true e opt-in do protótipo. Nenhum teste nativo executado.')


if __name__ == '__main__':
    exigir_runner_descartavel()
    unittest.main(verbosity=2)
