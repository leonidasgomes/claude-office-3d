"""Local só com modelo instalado, isolamento da configuração e proteção durante execução."""
import json
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from executor_local import validar_modelo, preparar_comando
from providers_console import PROVIDERS
from recursos_local import vigiar, reservar, verificar, percentual_cpu, medir_cpu
from gestao_projeto import validar

OCIOSO={'ollama':{'quantidade':0,'memoria_bytes':0,'vram_bytes':0},
        'gpu':{'estado':'indisponivel','gpus':[]}}


class Local(unittest.TestCase):
    def test_projeto_consumo_encaminhado_sem_mudar_destino_ou_admissao(self):
        from contextlib import nullcontext
        from executor_local import executar
        politica=validar({'local':{'ativo':True}})
        rota={'console':'codex','modelo':'fixture'}
        with patch('executor_local.validar_modelo',return_value='fixture') as modelo,patch('recursos_local.reservar',return_value=nullcontext()) as admitir,patch('console_provider.executar',return_value=0) as console:
            evento=lambda ev:None
            self.assertEqual(executar(rota,politica,PROVIDERS['codex'],'native','worktree','Dev',prompt='Teste',projeto_consumo='principal',ao_evento=evento,tentativa_consumo='a'*32),0)
        modelo.assert_called_once_with(rota);admitir.assert_called_once()
        self.assertEqual(console.call_args.args[2],'worktree')
        self.assertEqual(console.call_args.kwargs['projeto_consumo'],'principal')
        self.assertIs(console.call_args.kwargs['ao_evento'],evento)
        self.assertEqual(console.call_args.kwargs['tentativa_consumo'],'a'*32)
        self.assertEqual(console.call_args.kwargs['politica_local'],politica)
    def test_limite_mais_restrito_entre_projetos_e_ram_finita(self):
        simples=validar({'local':{'ativo':True}})
        team=validar({'local':{'ativo':True,'team':True,'max_paralelo':3}})
        medir=lambda:{'ram_livre_gb':16,'pesados':[],'cpu_uso_pct':10,**OCIOSO}
        with tempfile.TemporaryDirectory() as tmp:
            with reservar(Path(tmp)/'slots.db',simples,medidor=medir):
                with self.assertRaises(ValueError):
                    with reservar(Path(tmp)/'slots.db',team,medidor=medir): pass
        with self.assertRaises(ValueError): verificar(simples,{'ram_livre_gb':float('inf'),'pesados':[]})

    def test_modelo_remoto_invalido_ou_ausente_nao_vira_local(self):
        for modelo,dados in [('qwen:cloud',{'capabilities':['completion']}),
                             ('qwen:4b',{'remote_host':'ollama.com','capabilities':['completion']}),
                             ('qwen:4b',{'remote_model':'qwen','capabilities':['completion']}),
                             ('qwen:4b',{})]:
            with self.subTest(modelo=modelo,dados=dados),self.assertRaises(ValueError):
                validar_modelo({'console':'codex','modelo':modelo},lambda _:dados)
        self.assertEqual(validar_modelo({'console':'codex','modelo':'qwen:4b'},lambda _:{'capabilities':['completion'],'details':{'format':'gguf'}}),'qwen:4b')
        with self.assertRaises(ValueError): validar_modelo({'console':'gemini','modelo':'qwen:4b'})

    def test_adapters_somente_loopback_sem_alterar_config(self):
        for nome in ('claude','codex','opencode'):
            p=PROVIDERS[nome]; args=p.comando('native',Path('.'),'tarefa','qwen:4b'); env={}
            local=preparar_comando(p,args,'qwen:4b',env)
            self.assertEqual(env['OLLAMA_HOST'],'http://127.0.0.1:11434')
            self.assertNotIn('--dangerously-skip-permissions',local)
            if nome=='codex':
                self.assertIn('--oss',local)
                self.assertEqual(local[local.index('exec')+1],'--ignore-user-config')
            elif nome=='claude':
                self.assertIn('--bare',local); self.assertEqual(env['ANTHROPIC_API_KEY'],'')
            else:
                cfg=json.loads(env['OPENCODE_CONFIG_CONTENT']); self.assertEqual(cfg['enabled_providers'],['office_ollama'])
                self.assertEqual(local[local.index('--model')+1],'office_ollama/qwen:4b')

    def test_trabalho_pesado_interrompe_apenas_processo_deste_console(self):
        cfg=validar({'local':{'ativo':True}})
        processo=SimpleNamespace(pid=98765,poll=lambda:None)
        with patch('recursos_local.os.name','nt'),patch('recursos_local.subprocess.run',return_value=SimpleNamespace(returncode=0)) as matar:
            with self.assertRaises(ValueError):
                with vigiar(processo,cfg,medidor=lambda:{'ram_livre_gb':16,'pesados':['blender.exe'],'cpu_uso_pct':10},intervalo=0.01):
                    for _ in range(100):
                        if matar.called: break
                        time.sleep(0.005)
            self.assertEqual(matar.call_args.args[0],['taskkill','/PID','98765','/T','/F'])

    def test_cpu_delta_e_contadores_inconsistentes(self):
        self.assertEqual(percentual_cpu((200,500),(250,700)),75)
        for antes,depois in [((1,2),(1,2)),((2,5),(1,8)),((0,5),(5,8)),((True,2),(2,5))]:
            with self.subTest(antes=antes,depois=depois),self.assertRaises(OSError):percentual_cpu(antes,depois)
        with patch('recursos_local.contadores_cpu',side_effect=[(200,500),(250,700)]),patch('recursos_local.time.sleep') as esperar:
            self.assertEqual(medir_cpu(),75);esperar.assert_called_once_with(0.25)

    def test_cpu_pressao_ou_ausencia_bloqueia_reserva_antes_de_criar_banco(self):
        cfg=validar({'local':{'ativo':True}})
        base={'ram_livre_gb':16,'pesados':[],**OCIOSO}
        verificar(cfg,{**base,'cpu_uso_pct':75})
        for cpu in (None,True,-1,76,101,float('nan'),float('inf'),'10'):
            with self.subTest(cpu=cpu),tempfile.TemporaryDirectory() as tmp:
                arquivo=Path(tmp)/'slots.db'
                with self.assertRaises(ValueError):
                    with reservar(arquivo,cfg,medidor=lambda:{**base,'cpu_uso_pct':cpu}):self.fail('Admitiu CPU inválida')
                self.assertFalse(arquivo.exists())

    def test_cpu_alta_no_watchdog_interrompe_apenas_console_local(self):
        cfg=validar({'local':{'ativo':True}})
        processo=SimpleNamespace(pid=98765,poll=lambda:None)
        with patch('recursos_local.os.name','nt'),patch('recursos_local.subprocess.run',return_value=SimpleNamespace(returncode=0)) as matar:
            with self.assertRaises(ValueError):
                with vigiar(processo,cfg,medidor=lambda:{'ram_livre_gb':16,'pesados':[],'cpu_uso_pct':90},intervalo=0.01):
                    for _ in range(100):
                        if matar.called:break
                        time.sleep(0.005)
            self.assertEqual(matar.call_args.args[0],['taskkill','/PID','98765','/T','/F'])

    def test_cli_roteia_local_sob_guarda(self):
        import console_provider
        with tempfile.TemporaryDirectory() as tmp:
            raiz=Path(tmp); (raiz/'.office').mkdir()
            cfg={'ativo':True,'local':{'ativo':True},'rotas':{'simples':{'console':'codex','modelo':'qwen:4b','execucao':'local'}}}
            (raiz/'.office/projeto.json').write_text(json.dumps(cfg),encoding='utf-8')
            with patch('console_provider.selecionar',return_value=(PROVIDERS['codex'],'native')),patch('executor_local.executar',return_value=0) as rodar:
                self.assertEqual(console_provider.main(['--projeto',tmp,'--escopo','simples','--prompt','Resumir']),0)
                self.assertEqual(rodar.call_args.args[0]['execucao'],'local')


if __name__=='__main__': unittest.main()
