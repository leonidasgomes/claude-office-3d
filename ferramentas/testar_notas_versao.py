"""Notas indicam o asset da versão exata e mantêm histórico do legado."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from notas_versao import notas


class Notas(unittest.TestCase):
    def test_previa_download_exato(self):
        texto = '# Changelog\n## Próxima versão\n- futuro\n## 2.0.0-dev.3\n- atual\n## 2.0.0-dev.2\n- antigo\n'
        saida = notas('2.0.0-dev.3', texto)
        self.assertIn('/v2.0.0-dev.3/office-multi-provider-v2.0.0-dev.3.zip', saida)
        self.assertIn('Latest', saida)
        self.assertIn('pasta separada', saida)
        self.assertIn('- atual', saida)
        self.assertNotIn('- futuro', saida)
        self.assertNotIn('- antigo', saida)

    def test_legado_preservado(self):
        self.assertEqual(notas('1.19.1', '## 1.19.1\n- correção\n'), '- correção')


if __name__ == '__main__':
    unittest.main()
