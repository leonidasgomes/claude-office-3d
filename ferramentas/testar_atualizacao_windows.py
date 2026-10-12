"""Qualificação Windows nativa e conservadora, somente com dados sintéticos.

Não habilita privilégios, não muda ACLs e não simula sucesso de uma atualização
existente. Owner/group/DACL são observados; isso não comprova preservação de
SACL. Aplicação/reversão existentes devem continuar recusadas antes da troca.
Fora do Windows, os cenários nativos são SKIP, nunca evidência de aprovação.
"""
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
import atualizar_instalacao as a
import atualizar_windows as windows
import instalar


class NomesWindows(unittest.TestCase):
    """Validação lexical pura; não finge ser execução nativa em Linux."""

    def test_nomes_ambiguos_e_dispositivos_recusados(self):
        for nome in ('', '.', '..', 'final.', 'final ', 'CON', 'con.txt',
                     'PRN', 'AUX.log', 'NUL', 'CONIN$', 'conout$.txt',
                     'COM1', 'LPT9.txt', 'COM¹',
                     'LPT².bin', 'stream:oculto', 'a/b', 'a\\b', 'a\x01b',
                     'a?b', 'a*b', 'a|b', 'a<b', 'a>b', 'a"b'):
            with self.subTest(nome=repr(nome)):
                with self.assertRaises(ValueError):
                    windows.validar_nome(nome)

    def test_nomes_comuns_permitidos(self):
        for nome in ('config.json', '.office', 'Meu escritório', 'COM10',
                     'arquivo final.txt', 'arte-ç.png'):
            with self.subTest(nome=nome):
                windows.validar_nome(nome)

    def test_caminhos_relativos_unc_e_dispositivos_recusados_sem_acesso(self):
        for caminho in ('relativo', 'C:relativo', r'\\servidor\pasta',
                        r'\\?\C:\pasta', r'\\.\C:\pasta', '//servidor/pasta'):
            with self.subTest(caminho=caminho):
                with self.assertRaises(ValueError):
                    windows.validar_caminho(caminho)


class Win32SomenteLeitura:
    """Oráculo independente do inspetor: ACLs e handles, sem Set*Security*."""

    def __init__(self):
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.advapi = ctypes.WinDLL('advapi32', use_last_error=True)
        specs = (
            (self.kernel, 'CreateFileW', [wintypes.LPCWSTR, wintypes.DWORD,
             wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
             wintypes.HANDLE], wintypes.HANDLE),
            (self.kernel, 'CloseHandle', [wintypes.HANDLE], wintypes.BOOL),
            (self.kernel, 'LocalFree', [wintypes.LPVOID], wintypes.LPVOID),
            (self.advapi, 'GetNamedSecurityInfoW', [wintypes.LPWSTR,
             ctypes.c_int, wintypes.DWORD, wintypes.LPVOID, wintypes.LPVOID,
             wintypes.LPVOID, wintypes.LPVOID,
             ctypes.POINTER(wintypes.LPVOID)], wintypes.DWORD),
            (self.advapi, 'ConvertSecurityDescriptorToStringSecurityDescriptorW',
             [wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
              ctypes.POINTER(wintypes.LPWSTR), wintypes.LPVOID], wintypes.BOOL),
        )
        for dll, nome, argumentos, resultado in specs:
            funcao = getattr(dll, nome)
            funcao.argtypes = argumentos
            funcao.restype = resultado

    def seguranca(self, caminho):
        # SE_FILE_OBJECT; OWNER | GROUP | DACL. Não solicita SACL/privilégios.
        descritor = wintypes.LPVOID()
        erro = self.advapi.GetNamedSecurityInfoW(
            str(caminho), 1, 7, None, None, None, None,
            ctypes.byref(descritor))
        if erro:
            raise ctypes.WinError(erro)
        texto = wintypes.LPWSTR()
        try:
            if not self.advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW(
                    descritor, 1, 7, ctypes.byref(texto), None):
                raise ctypes.WinError(ctypes.get_last_error())
            return texto.value
        finally:
            if texto:
                self.kernel.LocalFree(ctypes.cast(texto, wintypes.LPVOID))
            self.kernel.LocalFree(descritor)

    @contextmanager
    def impedir_renomeacao(self, caminho):
        # Share READ | WRITE, sem FILE_SHARE_DELETE. A falha vem do Windows,
        # não de uma exceção de rename inventada pelo teste.
        atributos = 0x02000000 if caminho.is_dir() else 0x80
        handle = self.kernel.CreateFileW(
            str(caminho), 0x80000000, 3, None, 3, atributos, None)
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            yield
        finally:
            if not self.kernel.CloseHandle(handle):
                raise ctypes.WinError(ctypes.get_last_error())


@unittest.skipUnless(os.name == 'nt', 'Requer Windows real e NTFS local')
class AtualizacaoWindows(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='office Windows sintetico ')
        self.addCleanup(self.temp.cleanup)
        self.raiz = Path(self.temp.name)
        self.nativo = Win32SomenteLeitura()
        # Não pula silenciosamente em Windows sem NTFS: o job não está qualificado.
        windows._API().volume(self.raiz)
        self.origem = self.raiz / 'pacote novo'
        self.origem.mkdir()
        for nome in instalar.PACOTE:
            destino = self.origem / nome
            destino.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(RAIZ / nome, destino)
        (self.origem / 'VERSION').write_text('2.0.0-teste.windows.1\n', encoding='utf-8')
        self.app = self.raiz / 'app com espaços'
        with socket.socket() as s:
            s.bind(('127.0.0.1', 0))
            porta = s.getsockname()[1]
        self.cfg = {'porta': porta, 'projetos': [], 'titulo': 'sintético'}

    def instalar(self):
        return a.aplicar(a.preparar(self.app, self.origem, config=self.cfg))

    def privados(self):
        for nome in ('dados/banco.db', 'dados/entregas/arte.png',
                     'dados/gestao/projeto/galeria-blobs-v1/' + 'a' * 64,
                     '.office/projeto.json', 'skills/minha.md',
                     '.claude/settings.json', '.venv/Scripts/python.exe',
                     'NOTAS.md', 'privado.txt'):
            p = self.app / nome
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b'PRIVADO-SINTETICO\x00\xff\r\n' + nome.encode('utf-8'))
        config = a.json_ler(self.app / 'config.json')
        config['sentinela'] = 'NAO-IMPRIMIR-PRIVADO'
        (self.app / 'config.json').write_text(json.dumps(config), encoding='utf-8')

    def upgrade(self):
        (self.origem / 'VERSION').write_text('2.0.0-teste.windows.2\n', encoding='utf-8')
        return a.preparar(self.app, self.origem)

    def estado(self, raiz=None):
        """Bytes, caminhos, atributos e owner/group/DACL por API independente."""
        raiz = self.app if raiz is None else raiz
        if not raiz.exists():
            return {}
        resultado = {}
        for p in [raiz, *sorted(raiz.rglob('*'))]:
            rel = '.' if p == raiz else p.relative_to(raiz).as_posix()
            tipo = 'pasta' if p.is_dir() else 'arquivo'
            digest = None if p.is_dir() else hashlib.sha256(p.read_bytes()).hexdigest()
            resultado[rel] = (tipo, digest, p.lstat().st_file_attributes,
                              self.nativo.seguranca(p))
        return resultado

    def recibo_sintetico(self):
        """Estado de recuperação feito em fixture, sem desativar o gate Windows."""
        backup = self.raiz / (self.app.name + '.backup-sintetico')
        shutil.copytree(self.app, backup)
        recibo = backup.with_name(backup.name + '.json')
        a.gravar_json(recibo, {'formato': 1, 'destino': str(self.app),
                              'backup': str(backup), 'antes': a.inventario(backup),
                              'depois': a.inventario(self.app), 'stage': None})
        return recibo, backup

    def sem_troca(self, operacao):
        antes = self.estado()
        vizinhos = sorted(p.name for p in self.raiz.iterdir())
        with patch.object(a.shutil, 'copytree', side_effect=AssertionError('não copiar')), \
             patch.object(a.shutil, 'copy2', side_effect=AssertionError('não copiar')), \
             patch.object(a.os, 'rename', side_effect=AssertionError('não renomear')), \
             patch.object(a.tempfile, 'mkdtemp', side_effect=AssertionError('não criar stage')):
            with self.assertRaisesRegex(ValueError, 'Windows|ACL|SACL'):
                operacao()
        self.assertEqual(self.estado(), antes)
        self.assertEqual(sorted(p.name for p in self.raiz.iterdir()), vizinhos)

    def test_instalacao_nova_previa_limpa_e_sucesso_real(self):
        origem_antes = self.estado(self.origem)
        vizinhos = sorted(p.name for p in self.raiz.iterdir())
        plano = a.preparar(self.app, self.origem, config=self.cfg)
        self.assertFalse(self.app.exists())
        self.assertEqual(sorted(p.name for p in self.raiz.iterdir()), vizinhos)
        resultado = a.aplicar(plano)
        self.assertTrue(resultado['alterado'])
        self.assertIsNone(resultado['backup'])
        self.assertEqual(a.json_ler(self.app / 'config.json')['porta'], self.cfg['porta'])
        self.assertEqual(a.pacote(self.app, completo=True), plano['novo'])
        self.assertEqual(windows.inspecionar(self.app)['.']['owner_group_dacl'],
                         self.nativo.seguranca(self.app))
        self.assertEqual(self.estado(self.origem), origem_antes)

    def test_previa_existente_preserva_privados_e_seguranca(self):
        self.instalar()
        self.privados()
        antes = self.estado()
        vizinhos = sorted(p.name for p in self.raiz.iterdir())
        plano = self.upgrade()
        self.assertTrue(plano['existente'])
        self.assertNotEqual(plano['antigo'], plano['novo'])
        self.assertEqual(set(plano['metadados_windows']), set(antes))
        for nome, registro in plano['metadados_windows'].items():
            self.assertEqual(registro['owner_group_dacl'], antes[nome][3], nome)
            self.assertEqual(registro['atributos'], antes[nome][2], nome)
        self.assertEqual(self.estado(), antes)
        self.assertEqual(sorted(p.name for p in self.raiz.iterdir()), vizinhos)

    def test_apply_existente_recusa_antes_de_copia_stage_ou_rename(self):
        self.instalar()
        self.privados()
        plano = self.upgrade()
        self.sem_troca(lambda: a.aplicar(plano))

    def test_baseline_legado_sem_manifesto_tem_previa_mas_nao_troca(self):
        self.instalar()
        self.privados()
        (self.app / a.MANIFESTO).unlink()
        anterior = self.raiz / 'pacote anterior'
        shutil.copytree(self.origem, anterior)
        (self.origem / 'VERSION').write_text('2.0.0-teste.windows.2\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'manifesto|anterior'):
            a.preparar(self.app, self.origem)
        plano = a.preparar(self.app, self.origem, anterior)
        self.assertTrue(plano['existente'])
        self.sem_troca(lambda: a.aplicar(plano))

    def test_reversao_existente_recusada_sem_troca(self):
        self.instalar()
        self.privados()
        recibo, backup = self.recibo_sintetico()
        backup_antes = self.estado(backup)
        self.assertFalse(a.reverter(recibo)['recuperacao_interrompida'])
        self.sem_troca(lambda: a.reverter(recibo, True))
        self.assertEqual(self.estado(backup), backup_antes)

    def test_recuperacao_interrompida_tambem_exige_suporte_nativo(self):
        self.instalar()
        self.privados()
        recibo, backup = self.recibo_sintetico()
        preservado = self.raiz / 'fixture preservada'
        os.rename(self.app, preservado)
        antes = self.estado(backup)
        self.assertTrue(a.reverter(recibo)['recuperacao_interrompida'])
        self.sem_troca(lambda: a.reverter(recibo, True))
        self.assertFalse(self.app.exists())
        self.assertEqual(self.estado(backup), antes)
        self.assertTrue(preservado.is_dir())

    def test_backup_modificado_recusa_reversao(self):
        self.instalar()
        self.privados()
        recibo, backup = self.recibo_sintetico()
        (backup / 'privado.txt').write_bytes(b'backup mudou')
        antes, backup_antes = self.estado(), self.estado(backup)
        with self.assertRaisesRegex(ValueError, 'Backup|backup'):
            a.reverter(recibo, True)
        self.assertEqual(self.estado(), antes)
        self.assertEqual(self.estado(backup), backup_antes)

    def test_trabalho_posterior_recusa_reversao(self):
        self.instalar()
        recibo, backup = self.recibo_sintetico()
        (self.app / 'dados' / 'novo.txt').write_bytes(b'nunca descartar')
        antes, backup_antes = self.estado(), self.estado(backup)
        with self.assertRaisesRegex(ValueError, 'posterior|dados'):
            a.reverter(recibo, True)
        self.assertEqual(self.estado(), antes)
        self.assertEqual(self.estado(backup), backup_antes)

    def test_lock_concorrente_nao_e_removido(self):
        for existente in (False, True):
            with self.subTest(existente=existente):
                if existente:
                    self.instalar()
                    plano = self.upgrade()
                else:
                    plano = a.preparar(self.app, self.origem, config=self.cfg)
                antes = self.estado()
                lock = self.raiz / ('.' + self.app.name + '.atualizacao.lock')
                lock.write_text('outro processo sintético', encoding='utf-8')
                try:
                    with self.assertRaises(FileExistsError):
                        a.aplicar(plano)
                    self.assertEqual(lock.read_text(encoding='utf-8'), 'outro processo sintético')
                    self.assertEqual(self.estado(), antes)
                finally:
                    lock.unlink()

    def test_mudanca_da_fonte_apos_previa_recusa_instalacao_nova(self):
        plano = a.preparar(self.app, self.origem, config=self.cfg)
        (self.origem / 'VERSION').write_text('2.0.0-teste.windows.3\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'mudaram|prévia|plano'):
            a.aplicar(plano)
        self.assertFalse(self.app.exists())
        self.assertFalse(list(self.raiz.glob('.*.preparando-*')))

    def test_mudanca_de_dados_apos_previa_preservada(self):
        self.instalar()
        self.privados()
        plano = self.upgrade()
        (self.app / 'privado.txt').write_bytes(b'novo trabalho apos previa')
        antes = self.estado()
        with self.assertRaises(ValueError):
            a.aplicar(plano)
        self.assertEqual(self.estado(), antes)

    def test_falha_rename_instalacao_nova_preserva_fonte_e_permite_repetir(self):
        plano = a.preparar(self.app, self.origem, config=self.cfg)
        antes = self.estado(self.origem)
        with patch.object(a.os, 'rename', side_effect=OSError('falha sintética de rename')) as rename:
            with self.assertRaises(OSError):
                a.aplicar(plano)
        self.assertEqual(rename.call_count, 1)
        self.assertFalse(self.app.exists())
        self.assertFalse(list(self.raiz.glob('.*.preparando-*')))
        self.assertEqual(self.estado(self.origem), antes)
        self.assertTrue(a.aplicar(a.preparar(self.app, self.origem, config=self.cfg))['alterado'])

    def test_handle_windows_sem_share_delete_bloqueia_rename_do_stage(self):
        plano = a.preparar(self.app, self.origem, config=self.cfg)
        rename = os.rename
        tentativas = []

        def renomear_com_handle(src, dst):
            tentativas.append((Path(src), Path(dst)))
            with self.nativo.impedir_renomeacao(Path(src)):
                return rename(src, dst)

        with patch.object(a.os, 'rename', side_effect=renomear_com_handle):
            with self.assertRaises(OSError) as falha:
                a.aplicar(plano)
        self.assertIn(falha.exception.winerror, (5, 32))
        self.assertEqual(len(tentativas), 1)
        self.assertEqual(tentativas[0][1], self.app)
        self.assertFalse(self.app.exists())
        self.assertFalse(list(self.raiz.glob('.*.preparando-*')))
        self.assertTrue(self.instalar()['alterado'])

    def test_hardlink_real_recusado_sem_tocar_destino(self):
        self.instalar()
        arquivo = self.app / 'dados' / 'original.txt'
        arquivo.write_bytes(b'arquivo sintetico')
        link = self.app / 'dados' / 'outro.txt'
        os.link(arquivo, link)
        self.assertEqual(arquivo.stat().st_nlink, 2)
        with self.assertRaisesRegex(ValueError, 'Hardlink|hardlink'):
            windows.inspecionar(self.app)
        with self.assertRaises(ValueError):
            self.upgrade()
        self.assertEqual(arquivo.read_bytes(), b'arquivo sintetico')
        self.assertEqual(link.read_bytes(), b'arquivo sintetico')

    def test_ads_reais_em_arquivo_pasta_e_raiz_recusados(self):
        self.instalar()
        arquivo = self.app / 'dados' / 'normal.txt'
        arquivo.write_bytes(b'conteudo principal')
        for alvo in (arquivo, self.app / 'dados', self.app):
            with self.subTest(alvo=alvo.name):
                ads = str(alvo) + ':sentinela'
                with open(ads, 'wb') as f:
                    f.write(b'ADS-SINTETICO-NAO-PERDER')
                try:
                    with self.assertRaisesRegex(ValueError, 'ADS|Stream|stream'):
                        windows.inspecionar(self.app)
                    with self.assertRaises(ValueError):
                        self.upgrade()
                    with open(ads, 'rb') as f:
                        self.assertEqual(f.read(), b'ADS-SINTETICO-NAO-PERDER')
                    self.assertEqual(arquivo.read_bytes(), b'conteudo principal')
                finally:
                    os.unlink(ads)

    def test_junction_real_nao_e_seguida(self):
        self.instalar()
        externo = self.raiz / 'fixture externa'
        externo.mkdir()
        (externo / 'sentinela.txt').write_bytes(b'externo nao deve mudar')
        antes = self.estado(externo)
        junction = self.app / 'dados' / 'junction'
        comando = subprocess.run(
            ['cmd.exe', '/d', '/c', 'mklink', '/J', str(junction), str(externo)],
            capture_output=True, timeout=30)
        self.assertEqual(comando.returncode, 0, (comando.stdout, comando.stderr))
        try:
            self.assertTrue(junction.lstat().st_file_attributes & 0x400)
            with self.assertRaises(ValueError):
                windows.inspecionar(self.app)
            with self.assertRaises(ValueError):
                windows.inspecionar(junction)
            with self.assertRaises(ValueError):
                a.preparar(junction / 'novo', self.origem, config=self.cfg)
            self.assertEqual(self.estado(externo), antes)
        finally:
            # Remove apenas a junction temporária, nunca sua árvore de destino.
            os.rmdir(junction)

    def test_falha_leitura_seguranca_recusa_previa(self):
        self.instalar()
        antes = self.estado()
        with patch.object(windows._API, 'seguranca', side_effect=PermissionError('leitura negada')):
            with self.assertRaises(PermissionError):
                self.upgrade()
        self.assertEqual(self.estado(), antes)

    def test_falha_inspecao_streams_recusada(self):
        api = windows._API()

        def falhar(*args):
            ctypes.set_last_error(5)
            return 0

        with patch.object(api.k, 'GetFileInformationByHandleEx', side_effect=falhar):
            with self.assertRaises(OSError):
                api.arquivo(self.origem)

    def test_falha_inspecao_ea_e_ea_injetada_recusadas(self):
        api = windows._API()
        with patch.object(api.n, 'NtQueryInformationFile', return_value=-1):
            with self.assertRaises(OSError):
                api.arquivo(self.origem)

        def ea_presente(handle, iosb, saida, tamanho, classe):
            ctypes.cast(saida, ctypes.POINTER(wintypes.ULONG))[0] = 16
            return 0

        with patch.object(api.n, 'NtQueryInformationFile', side_effect=ea_presente):
            with self.assertRaisesRegex(ValueError, 'estendidos'):
                api.arquivo(self.origem)

    def test_atributos_especiais_injetados_recusados(self):
        # Não cria EFS/sparse, não muda readonly nem permissões do filesystem.
        api = windows._API()
        alvo = self.origem / 'VERSION'
        for bit in (0x1, 0x2, 0x4, 0x200, 0x400, 0x800, 0x1000, 0x4000):
            with self.subTest(atributo=hex(bit)):
                st = SimpleNamespace(st_file_attributes=0x20 | bit)
                with patch.object(Path, 'lstat', return_value=st):
                    with self.assertRaisesRegex(ValueError, 'Atributos'):
                        api.arquivo(alvo)

    def test_colisao_casefold_injetada_recusada_sem_mudar_ntfs(self):
        (self.origem / 'duplo.txt').write_bytes(b'sintetico')
        # NTFS normal é case-insensitive. Não habilita case sensitivity na pasta.
        with patch.object(windows.os, 'walk', return_value=[
                (str(self.origem), [], ['duplo.txt', 'DUPLO.txt'])]):
            with self.assertRaisesRegex(ValueError, 'Colisão'):
                windows.inspecionar(self.origem)

    def test_previa_cli_explica_limite_sem_imprimir_privados(self):
        self.instalar()
        self.privados()
        self.upgrade()
        antes = self.estado()
        resultado = subprocess.run(
            [sys.executable, str(self.origem / 'atualizar_instalacao.py'),
             '--destino', str(self.app)], capture_output=True, timeout=60)
        self.assertEqual(resultado.returncode, 0, resultado.stderr.decode(errors='replace'))
        saida = resultado.stdout.decode('utf-8', errors='replace')
        self.assertIn('"aplicacao_suportada": false', saida)
        self.assertNotIn('Revise e repita com --aplicar', saida)
        self.assertNotIn('NAO-IMPRIMIR-PRIVADO', saida)
        self.assertNotIn('NAO-IMPRIMIR-PRIVADO', resultado.stderr.decode(errors='replace'))
        self.assertEqual(self.estado(), antes)
        aplicado = subprocess.run(
            [sys.executable, str(self.origem / 'atualizar_instalacao.py'),
             '--destino', str(self.app), '--aplicar'], capture_output=True, timeout=60)
        self.assertEqual(aplicado.returncode, 2)
        self.assertIn('Windows', aplicado.stderr.decode(errors='replace'))
        self.assertNotIn(b'NAO-IMPRIMIR-PRIVADO', aplicado.stdout + aplicado.stderr)
        self.assertEqual(self.estado(), antes)
        self.assertFalse(list(self.raiz.glob('.*.preparando-*')))


if __name__ == '__main__':
    unittest.main()
