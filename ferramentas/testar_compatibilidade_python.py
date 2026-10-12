"""Regressões das operações disponíveis apenas em versões novas do Python."""
import hashlib
import io
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from compatibilidade_python import is_junction, sha256_arquivo


class CompatibilidadePython(unittest.TestCase):
    def test_usa_metodo_nativo_quando_disponivel(self):
        caminho = SimpleNamespace(is_junction=Mock(return_value=True))
        self.assertTrue(is_junction(caminho))
        caminho.is_junction.assert_called_once_with()

    def test_fallback_reconhece_junction_windows_sem_seguir_link(self):
        for tag, esperado in ((0xA0000003, True), (0xA000000C, False), (0, False)):
            with self.subTest(tag=tag):
                caminho = SimpleNamespace(lstat=Mock(return_value=SimpleNamespace(st_reparse_tag=tag)))
                self.assertEqual(is_junction(caminho), esperado)
                caminho.lstat.assert_called_once_with()

    def test_fallback_posix_e_caminho_ausente(self):
        caminho = SimpleNamespace(lstat=Mock(return_value=SimpleNamespace()))
        self.assertFalse(is_junction(caminho))
        for erro in (FileNotFoundError, NotADirectoryError):
            caminho.lstat.side_effect = erro
            self.assertFalse(is_junction(caminho))

    def test_fallback_nao_oculta_permissao_negada(self):
        caminho = SimpleNamespace(lstat=Mock(side_effect=PermissionError))
        with self.assertRaises(PermissionError):
            is_junction(caminho)

    def test_diretorio_real_sem_api_nova(self):
        with tempfile.TemporaryDirectory() as pasta:
            with patch.object(Path, 'is_junction', None, create=True):
                self.assertFalse(is_junction(Path(pasta)))
                self.assertFalse(is_junction(Path(pasta) / 'ausente'))

    def test_hash_vazio_pequeno_e_multiplos_blocos(self):
        for conteudo in (b'', b'asset local', b'x' * (2 * 1024 * 1024 + 7)):
            with self.subTest(tamanho=len(conteudo)):
                arquivo = io.BytesIO(conteudo)
                self.assertEqual(sha256_arquivo(arquivo), hashlib.sha256(conteudo).hexdigest())
                self.assertFalse(arquivo.closed)


if __name__ == '__main__':
    unittest.main()
