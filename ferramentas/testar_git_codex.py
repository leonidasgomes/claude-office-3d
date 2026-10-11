import base64,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from providers_console import ambiente_git_codex

class GitCodex(unittest.TestCase):
    def test_padrao_preserva_ambiente(self):
        env={'PATH':'teste'};self.assertIs(ambiente_git_codex(env),env)
    def test_token_apenas_em_memoria_e_escopo_github(self):
        env={'OFFICE_CODEX_GIT_GITHUB':'1','GH_TOKEN':'credencial-ficticia'}
        novo=ambiente_git_codex(env)
        self.assertNotIn('GIT_CONFIG_COUNT',env)
        ajustes=[(novo['GIT_CONFIG_KEY_'+str(i)],novo['GIT_CONFIG_VALUE_'+str(i)]) for i in range(5)]
        self.assertTrue(all('https://github.com' in k for k,v in ajustes))
        self.assertIn(('http.https://github.com/.sslBackend','openssl'),ajustes)
        self.assertIn(('http.https://github.com/.sslVerify','true'),ajustes)
        self.assertEqual(ajustes[-2],('http.https://github.com/.extraHeader',''))
        self.assertEqual(base64.b64decode(ajustes[-1][1].split()[-1]).decode(),'x-access-token:credencial-ficticia')
        self.assertEqual(novo['GIT_TERMINAL_PROMPT'],'0')
    def test_preserva_opcoes_anteriores(self):
        env={'OFFICE_CODEX_GIT_GITHUB':'1','GH_TOKEN':'exemplo','GIT_CONFIG_COUNT':'1',
             'GIT_CONFIG_KEY_0':'core.autocrlf','GIT_CONFIG_VALUE_0':'true'}
        novo=ambiente_git_codex(env)
        self.assertEqual(novo['GIT_CONFIG_COUNT'],'6');self.assertEqual(novo['GIT_CONFIG_KEY_0'],'core.autocrlf')
        self.assertEqual(novo['GIT_CONFIG_VALUE_0'],'true')
    def test_falha_sem_credencial_sem_vazar_valor(self):
        for valor in ('','nao\nvalido'):
            with self.assertRaises(ValueError) as erro:
                ambiente_git_codex({'OFFICE_CODEX_GIT_GITHUB':'1','GH_TOKEN':valor})
            self.assertNotIn('nao\nvalido',str(erro.exception))
    def test_recusa_contagem_invalida(self):
        for n in ('-1','101','erro'):
            with self.assertRaises(ValueError):
                ambiente_git_codex({'OFFICE_CODEX_GIT_GITHUB':'1','GH_TOKEN':'exemplo','GIT_CONFIG_COUNT':n})

if __name__=='__main__':unittest.main()
