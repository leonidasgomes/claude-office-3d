"""Inspeção Windows somente leitura. NÃO habilita atualização/reversão.

Owner/group/DACL observáveis não comprovam a ausência de SACL. Este módulo não
ajusta privilégios, permissões ou políticas e não copia descritores de segurança.
"""
import ctypes
from ctypes import wintypes as w
import os
from pathlib import Path
import re


def validar_nome(nome):
    if (not nome or nome[-1:] in (' ', '.') or any(ord(c) < 32 or c in '<>:"/\\|?*' for c in nome)
            or re.fullmatch(r'(CON|CONIN\$|CONOUT\$|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\..*)?', nome, re.I)):
        raise ValueError('Nome não suportado no Windows: ' + nome)


def validar_caminho(raiz):
    texto = os.fspath(raiz)
    if texto.startswith(('\\\\', '//')) or not re.match(r'^[A-Za-z]:[\\/]', texto):
        raise ValueError('Windows exige caminho local absoluto, sem UNC/dispositivo')
    for parte in Path(texto).parts[1:]:
        validar_nome(parte)


class _API:
    def __init__(self):
        if os.name != 'nt':
            raise ValueError('Inspeção nativa disponível somente no Windows')
        self.k = ctypes.WinDLL('kernel32', use_last_error=True)
        self.a = ctypes.WinDLL('advapi32', use_last_error=True)
        self.n = ctypes.WinDLL('ntdll', use_last_error=True)
        specs = [
            (self.k, 'GetVolumePathNameW', [w.LPCWSTR, w.LPWSTR, w.DWORD], w.BOOL),
            (self.k, 'GetDriveTypeW', [w.LPCWSTR], w.UINT),
            (self.k, 'GetVolumeInformationW', [w.LPCWSTR, w.LPWSTR, w.DWORD, ctypes.POINTER(w.DWORD), ctypes.POINTER(w.DWORD), ctypes.POINTER(w.DWORD), w.LPWSTR, w.DWORD], w.BOOL),
            (self.k, 'CreateFileW', [w.LPCWSTR, w.DWORD, w.DWORD, w.LPVOID, w.DWORD, w.DWORD, w.HANDLE], w.HANDLE),
            (self.k, 'CloseHandle', [w.HANDLE], w.BOOL),
            (self.k, 'GetFileInformationByHandleEx', [w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD], w.BOOL),
            (self.k, 'LocalFree', [w.LPVOID], w.LPVOID),
            (self.a, 'GetSecurityInfo', [w.HANDLE, ctypes.c_int, w.DWORD, w.LPVOID, w.LPVOID, w.LPVOID, w.LPVOID, ctypes.POINTER(w.LPVOID)], w.DWORD),
            (self.a, 'ConvertSecurityDescriptorToStringSecurityDescriptorW', [w.LPVOID, w.DWORD, w.DWORD, ctypes.POINTER(w.LPWSTR), ctypes.POINTER(w.DWORD)], w.BOOL),
            (self.n, 'NtQueryInformationFile', [w.HANDLE, w.LPVOID, w.LPVOID, w.ULONG, ctypes.c_int], w.LONG),
        ]
        for dll, nome, args, resultado in specs:
            f = getattr(dll, nome); f.argtypes = args; f.restype = resultado

    def conferir(self, ok):
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())

    def volume(self, raiz):
        pasta = ctypes.create_unicode_buffer(32768)
        self.conferir(self.k.GetVolumePathNameW(str(raiz), pasta, len(pasta)))
        if self.k.GetDriveTypeW(pasta.value) != 3:
            raise ValueError('Somente volume local fixo NTFS pode ser inspecionado')
        formato = ctypes.create_unicode_buffer(64)
        self.conferir(self.k.GetVolumeInformationW(pasta.value, None, 0, None, None, None, formato, len(formato)))
        if formato.value != 'NTFS':
            raise ValueError('Volume não NTFS; inspeção recusada')

    def seguranca(self, handle):
        # Somente owner/group/DACL. Não pedir SACL nem habilitar privilégios.
        # GetFileSecurity legado pode omitir INHERITED_ACE. Lê pelo handle com
        # GetSecurityInfo e mantém os flags, sem normalizá-los para passar o teste.
        sd = w.LPVOID()
        erro = self.a.GetSecurityInfo(handle, 1, 7, None, None, None, None, ctypes.byref(sd))
        if erro:
            raise ctypes.WinError(erro)
        texto = w.LPWSTR()
        try:
            self.conferir(self.a.ConvertSecurityDescriptorToStringSecurityDescriptorW(sd, 1, 7, ctypes.byref(texto), None))
            return texto.value
        finally:
            if texto:
                self.k.LocalFree(ctypes.cast(texto, w.LPVOID))
            self.k.LocalFree(sd)

    def arquivo(self, p):
        st = p.lstat()
        # Archive/normal/directory são os únicos atributos aceitos nesta inspeção.
        # Recusa inclusive readonly, EFS, sparse, compressed, offline e reparse.
        atributos = st.st_file_attributes
        if atributos & ~(0x10 | 0x20 | 0x80):
            raise ValueError('Atributos especiais Windows não suportados: ' + str(p))
        if not p.is_dir() and st.st_nlink != 1:
            raise ValueError('Hardlink não suportado: ' + str(p))
        # READ_CONTROL | FILE_READ_EA | FILE_READ_ATTRIBUTES. Não concede escrita.
        h = self.k.CreateFileW(str(p), 0x20088, 7, None, 3, 0x02200000, None)
        if h == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            # FILE_STREAM_INFO. Buffer limitado; overflow recusa em vez de omitir.
            b = ctypes.create_string_buffer(1024 * 1024)
            ok = self.k.GetFileInformationByHandleEx(h, 7, b, len(b))
            if not ok and ctypes.get_last_error() != 38:
                raise ctypes.WinError(ctypes.get_last_error())
            if ok:
                dados = b.raw; pos = 0
                while True:
                    proximo = int.from_bytes(dados[pos:pos + 4], 'little')
                    tamanho = int.from_bytes(dados[pos + 4:pos + 8], 'little')
                    if tamanho % 2 or pos + 24 + tamanho > len(dados):
                        raise ValueError('Resposta de streams inválida')
                    nome = dados[pos + 24:pos + 24 + tamanho].decode('utf-16-le')
                    if nome != '::$DATA':
                        raise ValueError('Stream alternativo (ADS) não suportado: ' + str(p))
                    if not proximo:
                        break
                    if proximo < 24 + tamanho or pos + proximo + 24 > len(dados):
                        raise ValueError('Resposta de streams inválida')
                    pos += proximo
            # FileEaInformation é distinto dos streams $DATA, inclusive em pastas.
            iosb = (ctypes.c_void_p * 2)()
            ea = w.ULONG()
            status = self.n.NtQueryInformationFile(h, iosb, ctypes.byref(ea), ctypes.sizeof(ea), 7)
            if status != 0:
                raise OSError('Inspeção de atributos estendidos NTFS falhou')
            if ea.value:
                raise ValueError('Atributos estendidos NTFS não suportados: ' + str(p))
            return {'atributos': atributos, 'owner_group_dacl': self.seguranca(h)}
        finally:
            self.k.CloseHandle(h)


def inspecionar(raiz):
    """Diagnóstico parcial: nunca prova preservação completa nem autoriza troca."""
    raiz = Path(raiz)
    validar_caminho(raiz)
    api = _API()
    api.volume(raiz)
    for p in [raiz, *raiz.parents]:
        if p.lstat().st_file_attributes & 0x400:
            raise ValueError('Junção/reparse point no caminho: ' + str(p))
    resultado = {'.': api.arquivo(raiz)}
    def erro(exc):
        raise exc
    for pasta, dirs, arquivos in os.walk(raiz, followlinks=False, onerror=erro):
        vistos = set()
        for nome in sorted(dirs + arquivos):
            validar_nome(nome)
            if nome.casefold() in vistos:
                raise ValueError('Colisão de nomes no Windows: ' + nome)
            vistos.add(nome.casefold())
            p = Path(pasta) / nome
            resultado[p.relative_to(raiz).as_posix()] = api.arquivo(p)
    return resultado
