"""Testa argumentos sem shell interpolation e preservação de atalhos alheios."""
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import atalho_desktop


class Atalho(unittest.TestCase):
    def test_icone(self):
        dados = (Path(atalho_desktop.__file__).parent / 'icone-office.ico').read_bytes()
        self.assertEqual(struct.unpack('<HHH', dados[:6]), (0, 1, 1))
        tamanho, inicio = struct.unpack('<II', dados[14:22])
        self.assertEqual(tamanho, len(dados) - inicio)
        self.assertTrue(dados[inicio:].startswith(b'\x89PNG\r\n\x1a\n'))

    def test_criar_e_falhar_sem_desktop_real(self):
        with tempfile.TemporaryDirectory() as tmp:
            pasta = Path(tmp) / "office $literal ' com espacos"
            pasta.mkdir()
            (pasta / 'abrir_escritorio.bat').write_text('@echo off')
            (pasta / 'icone-office.ico').write_bytes(b'icone')
            with patch.object(atalho_desktop.os, 'name', 'nt'), \
                 patch.object(atalho_desktop.subprocess, 'CREATE_NO_WINDOW', 0, create=True), \
                 patch.object(atalho_desktop.subprocess, 'run') as run:
                run.return_value = SimpleNamespace(returncode=0, stdout=str(pasta / 'teste.lnk'), stderr='')
                self.assertEqual(atalho_desktop.criar(pasta), pasta / 'teste.lnk')
                args, kwargs = run.call_args
                self.assertEqual(args[0][-1], atalho_desktop.SCRIPT)
                dados = json.loads(kwargs['env']['ESCRITORIO_ATALHO_JSON'])
                self.assertEqual(dados['alvo'], str(pasta / 'abrir_escritorio.bat'))
                self.assertNotIn(str(pasta), args[0][-1])
                run.return_value = SimpleNamespace(returncode=1, stdout='', stderr='Atalho alheio preservado')
                with self.assertRaisesRegex(OSError, 'preservado'):
                    atalho_desktop.criar(pasta)
                with self.assertRaises(ValueError):
                    atalho_desktop.criar(pasta, nome='../invalido')


if __name__ == '__main__':
    unittest.main()
