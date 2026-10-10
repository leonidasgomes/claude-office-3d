"""Contratos do verificador: flags reais e rejeição de documentação incompleta."""
from pathlib import Path
import sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
import verificar_docs as v


class Documentacao(unittest.TestCase):
    def test_tabela_auxiliar_da_ponte_sem_executar_modulo(self):
        with tempfile.TemporaryDirectory() as tmp:
            raiz=Path(tmp)
            (raiz/'banco.py').write_text('CREATE TABLE IF NOT EXISTS evento',encoding='utf-8')
            (raiz/'ponte_eventos.py').write_text('raise RuntimeError("Não executar")\n# CREATE TABLE IF NOT EXISTS ponte_eventos',encoding='utf-8')
            with patch.object(v,'RAIZ',raiz):self.assertEqual(v.tabelas(),['evento','ponte_eventos'])
    def test_flags_aspas_aliases_multilinha_sem_importar_cli(self):
        fonte='''
raise RuntimeError("Não executar CLI para inspecionar")
parser.add_argument('--simples', help="exemplo --ignorado")
parser.add_argument("--duplas")
grupo.add_argument(
    '-f', '--primeiro', "--alias", default="--ignorado")
# parser.add_argument('--comentario')
texto="parser.add_argument('--texto')"
'''
        self.assertEqual(v.flags_argparse(fonte),{'--simples','--duplas','--primeiro','--alias'})
    def test_script_sintetico_revela_flag_antes_invisivel(self):
        with tempfile.TemporaryDirectory() as tmp:
            raiz=Path(tmp)
            (raiz/'cli.py').write_text("if __name__ == '__main__':\n p.add_argument('--nova')\n",encoding='utf-8')
            with patch.object(v,'RAIZ',raiz),patch.object(v,'SCRIPTS_EXTRAS',[]):
                self.assertEqual(v.scripts(),{'cli.py':['--nova']})
    def test_sdd_sem_flag_na_linha_certa_e_rejeitado(self):
        with tempfile.TemporaryDirectory() as tmp:
            raiz=Path(tmp);sdd=raiz/'SDD.md'
            sdd.write_text('''### 4.1 Banco
sem tabelas
### 5.1 Rotas
sem rotas
### 5.3 Scripts
| cli.py | sem opções |
| outro.py | --nova |
### 5.4 Configuração
sem config
## fim
''',encoding='utf-8')
            with patch.object(v,'RAIZ',raiz),patch.object(v,'SDD',sdd), \
                patch.object(v,'rotas',return_value=[]),patch.object(v,'tabelas',return_value=[]), \
                patch.object(v,'scripts',return_value={'cli.py':['--nova']}), \
                patch.object(v,'chaves_config',return_value=[]),patch.object(v,'variaveis_ambiente',return_value=[]):
                self.assertEqual(v.faltas(),['flag --nova de cli.py não está na linha dele na seção 5.3'])
                sdd.write_text(sdd.read_text(encoding='utf-8').replace('| cli.py | sem opções |','| cli.py | --nova |'),encoding='utf-8')
                self.assertEqual(v.faltas(),[])
    def test_bootstrap_tem_modo_estrito_no_catalogo_real(self):
        self.assertIn('--exigir-requisitos',v.scripts()['iniciar_projeto.py'])

    def test_links_guias_relocados_rejeitam_pai_errado_e_aceitam_destino_local(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=Path(tmp);(r/'docs').mkdir()
            (r/'INSTALACAO.md').write_text('# Guia',encoding='utf-8')
            p=r/'docs/CLAUDE-COMPATIBILIDADE.md'
            p.write_text('[Guia](../INSTALACAO.md)\n[Web](https://example.org/)\n[Ancora](#topo)',encoding='utf-8')
            with patch.object(v,'RAIZ',r):self.assertEqual(v.links_locais(),[])
            p.write_text('[Guia](../../INSTALACAO.md)',encoding='utf-8')
            with patch.object(v,'RAIZ',r):self.assertEqual(len(v.links_locais()),1)


if __name__=='__main__':unittest.main()
