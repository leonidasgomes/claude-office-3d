import sys,unittest,json,tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from iniciar_equipe import tarefa,main
from console_provider import executar
from providers_console import PROVIDERS
class Inicio(unittest.TestCase):
    def test_ciclo_abre_monitor_e_conversa_sem_despachar_lote(self):
        cfg={'ativo':True,'ceo':{'console':'codex','modelo':'teste','execucao':'cloud'},
             'ciclo':{'ativo':True,'base':'origin/main'}}
        with tempfile.TemporaryDirectory() as tmp, \
             patch('iniciar_equipe.__file__',str(Path(tmp)/'iniciar_equipe.py')), \
             patch('iniciar_equipe.carregar',return_value=cfg), \
             patch('iniciar_equipe.selecionar',return_value=(PROVIDERS['codex'],'codex')), \
             patch('subprocess.run') as host,patch('acompanhamento_ciclo.abrir') as monitor, \
             patch('iniciar_equipe.executar',return_value=0) as ceo:
            host.return_value.returncode=0
            self.assertEqual(main(['--projeto',tmp,'--base','origin/main']),0)
            monitor.assert_called_once_with(Path(tmp).resolve())
            self.assertIn('publicacoes/*.json',ceo.call_args.kwargs['prompt_inicial'])
            self.assertIn('ciclo',host.call_args.args[0])
            self.assertNotIn('lote',host.call_args.args[0])
    def test_tarefa_limitada_delega_sem_raiz(self):
        s=tarefa(Path('projeto'),Path('office'),'origin/main',2)
        self.assertIn('--acao lote --arquivo plano_utf8 --executar',s)
        self.assertIn('--acao diretor --arquivo',s)
        self.assertIn('--acao worktrees --arquivo',s)
        self.assertIn('"max_cartoes": 2',s)
        self.assertIn('Não retome reserva',s)
        self.assertLess(len(s),6000)
        for base,n in [('-x',1),('main x',1),('main',0),('main',3)]:
            with self.assertRaises(ValueError):tarefa(Path('p'),Path('o'),base,n)
    def test_inicio_envia_prompt_e_mantem_tui(self):
        cfg={'ativo':True,'ceo':{'console':'codex','modelo':'teste','execucao':'cloud'}}
        with patch('iniciar_equipe.carregar',return_value=cfg),patch('iniciar_equipe.selecionar',return_value=(PROVIDERS['codex'],'codex')),patch('iniciar_equipe.executar',return_value=0) as rodar:
            self.assertEqual(main(['--projeto','.','--base','origin/main']),0)
            kw=rodar.call_args.kwargs
            self.assertEqual(kw['sandbox'],'workspace-write');self.assertIn('Comece agora',kw['prompt_inicial'])
    def test_processo_recebe_prompt_sem_exec_ou_pipe(self):
        with tempfile.TemporaryDirectory() as tmp:
            raiz=Path(tmp);saida=raiz/'args.json';fake=raiz/'fake.py'
            fake.write_text('import sys,json\nfrom pathlib import Path\nPath('+repr(str(saida))+').write_text(json.dumps(sys.argv[1:]))',encoding='utf-8')
            with patch('providers_console.comando_nativo',return_value=[sys.executable,str(fake)]):
                self.assertEqual(executar(PROVIDERS['codex'],'codex',raiz,'CEO',banco=raiz/'banco.db',sandbox='workspace-write',prompt_inicial='Comece agora',diretorios_escrita=[raiz]),0)
            args=json.loads(saida.read_text())
            self.assertIn('workspace-write',args);self.assertEqual(args[-1],'Comece agora')
            self.assertIn('--add-dir',args);self.assertIn(str(raiz.resolve()),args)
            self.assertNotIn('exec',args);self.assertNotIn('--json',args)
    def test_daemon_isolado_so_codex_sem_alterar_sandbox(self):
        with patch.dict('os.environ',{'OFFICE_CODEX_SEM_DAEMON':'1'}),patch('providers_console.comando_nativo',side_effect=lambda exe,nome:[exe]):
            args=PROVIDERS['codex'].comando('codex',Path('.'),sandbox='workspace-write')
            self.assertEqual(args,['codex','--disable','daemon_auto_start','--sandbox','workspace-write'])
            self.assertNotIn('--disable',PROVIDERS['claude'].comando('claude',Path('.')))
            self.assertNotIn('--disable',PROVIDERS['opencode'].comando('opencode',Path('.')))
    def test_autonomia_explicitamente_autorizada_preserva_sandbox(self):
        with patch.dict('os.environ',{'OFFICE_CODEX_AUTONOMO':'1'}),patch('providers_console.comando_nativo',side_effect=lambda exe,nome:[exe]):
            args=PROVIDERS['codex'].comando('codex',Path('.'),sandbox='workspace-write')
            self.assertIn('never',args);self.assertIn('sandbox_workspace_write.network_access=true',args)
            self.assertIn('workspace-write',args);self.assertNotIn('danger-full-access',args)
            self.assertNotIn('never',PROVIDERS['claude'].comando('claude',Path('.')))
    def test_sandbox_windows_somente_opcao_suportada(self):
        with patch.dict('os.environ',{'OFFICE_CODEX_WINDOWS_SANDBOX':'unelevated'}),patch('providers_console.comando_nativo',side_effect=lambda exe,nome:[exe]):
            args=PROVIDERS['codex'].comando('codex',Path('.'),sandbox='workspace-write')
            self.assertIn('windows.sandbox=unelevated',args);self.assertIn('workspace-write',args)
            self.assertNotIn('windows.sandbox=unelevated',PROVIDERS['claude'].comando('claude',Path('.')))
        with patch.dict('os.environ',{'OFFICE_CODEX_WINDOWS_SANDBOX':'danger-full-access'}):
            with self.assertRaises(ValueError):PROVIDERS['codex'].comando('codex',Path('.'))
    def test_prompt_inicial_rejeita_modo_errado_antes_de_lancar(self):
        with self.assertRaises(ValueError):executar(PROVIDERS['claude'],'claude',Path('.'),'CEO',prompt_inicial='tarefa')
        with self.assertRaises(ValueError):executar(PROVIDERS['codex'],'codex',Path('.'),'CEO',prompt='exec',prompt_inicial='tarefa')
if __name__=='__main__':unittest.main()
