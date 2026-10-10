"""Contagem persistente não duplica cache, totais Gemini, snapshots nem retomadas."""
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import io
import json
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from consumo_providers import Coletor, ColetorRollout, Registro


class Consumo(unittest.TestCase):
    def test_projeto_consumo_inexistente_rejeita_antes_de_iniciar(self):
        from console_provider import executar
        from providers_console import PROVIDERS
        with tempfile.TemporaryDirectory() as tmp,patch('console_provider.subprocess.Popen') as processo:
            with self.assertRaisesRegex(ValueError,'Projeto de consumo'):
                executar(PROVIDERS['codex'],'native',Path(tmp),'Dev',prompt='Teste',projeto_consumo=Path(tmp)/'ausente')
            processo.assert_not_called()
            self.assertEqual(list(Path(tmp).iterdir()),[])
    def test_claude_baselines_isolados_por_projeto_e_modelo(self):
        from consumo_providers import identidade_projeto
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'uso.db';r=Registro(db);a=identidade_projeto(Path(tmp)/'a');b=identidade_projeto(Path(tmp)/'b')
            for projeto,modelo,entrada in ((a,'m1',100),(a,'m2',200),(b,'m1',50)):
                r.cumulativo_claude(projeto,'s',modelo,'Dev',projeto+modelo,[entrada,0,0,10],True)
            r.cumulativo_claude(a,'s','m1','QA','retoma-a',[120,0,0,15])
            r.cumulativo_claude(b,'s','m1','QA','retoma-b',[80,0,0,10])
            dados_a=r.resumo(projeto_hash=a);dados_b=r.resumo(projeto_hash=b)
            self.assertEqual(sum(g['total'] for g in dados_a['grupos']),345)
            self.assertEqual(sum(g['total'] for g in dados_b['grupos']),90)
            self.assertEqual(next(g['total'] for g in dados_a['grupos'] if g['agente']=='QA'),25)
            self.assertEqual(next(g['total'] for g in dados_b['grupos'] if g['agente']=='QA'),30)
            self.assertNotIn(a,json.dumps(dados_a));self.assertNotIn('saldo_claude',json.dumps(dados_a))
    def test_claude_retomada_usa_saldo_persistido_e_papel_atual(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'uso.db'
            def ev(n,cache=40,saida=30):return {'type':'result','session_id':'s','is_error':False,'modelUsage':{
                'modelo':{'inputTokens':n,'cacheReadInputTokens':cache,'cacheCreationInputTokens':20,'outputTokens':saida}}}
            c=Coletor(db,'claude',tmp,'Dev',sessao_claude_nova='s')
            c.consumir({'type':'system','subtype':'init','session_id':'s'});c.consumir(ev(100))
            for agente in ('QA','QA repetido'):
                r=Coletor(db,'claude',tmp,agente,sessao_claude_retomada='s')
                r.consumir({'type':'system','subtype':'init','session_id':'s'});r.consumir(ev(120,45,40));r.consumir(ev(120,45,40))
            gs={g['agente']:g for g in Registro(db).resumo()['grupos']}
            self.assertEqual(set(gs),{'Dev','QA'})
            self.assertEqual(gs['Dev']['total'],190);self.assertEqual(gs['QA']['total'],35)
            self.assertEqual(gs['QA']['entrada'],25);self.assertEqual(gs['QA']['cache'],5)
    def test_claude_baseline_desconhecido_nao_importa_primeiro_agregado(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'uso.db';c=Coletor(db,'claude',tmp,'QA',sessao_claude_retomada='s')
            c.consumir({'type':'system','subtype':'init','session_id':'s'})
            def ev(n):return {'type':'result','session_id':'s','is_error':False,'modelUsage':{
                'modelo':{'inputTokens':n,'cacheReadInputTokens':40,'cacheCreationInputTokens':20,'outputTokens':30}}}
            c.consumir(ev(500));self.assertEqual(Registro(db).resumo()['grupos'],[])
            c.consumir(ev(550));c.consumir(ev(10));c.consumir(ev(550))
            self.assertEqual(Registro(db).resumo()['grupos'][0]['total'],50)
            with self.assertRaises(ValueError):Coletor(db,'claude',tmp,'QA',sessao_claude_nova='s',sessao_claude_retomada='s')
    def test_claude_saldo_atomico_concorrencia_e_janela_de_sete_dias(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'uso.db';r=Registro(db);agora=time.time()
            with patch('consumo_providers.time.time',return_value=agora-8*86400),ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(lambda i:r.cumulativo_claude('p','s','m','Dev',str(i),[100,40,20,30],True),range(8)))
            self.assertEqual(r.resumo(agora)['grupos'],[])
            self.assertEqual(r.resumo(agora-8*86400)['grupos'][0]['total'],190)
            self.assertEqual(r.resumo(agora-8*86400)['grupos'][0]['amostras'],1)
            r.cumulativo_claude('p','s','m','QA','retomada',[120,45,20,40])
            self.assertEqual(r.resumo(agora+1)['grupos'][0]['total'],35)
    def test_launcher_retomado_real_conserva_baseline_da_sessao_nova(self):
        from console_provider import executar
        from providers_console import PROVIDERS
        from contextlib import redirect_stdout
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);fake=p/'fake.py';sessoes=[]
            fake.write_text('import os,sys,json\nsys.stdin.read()\ns=os.environ["OFFICE_CLAUDE_STREAM_SESSION"]\n'+
                'n=20 if "--resume" in sys.argv else 10\n'+
                'eventos=[{"type":"system","subtype":"init","session_id":s},'+
                '{"type":"result","subtype":"success","session_id":s,"is_error":False,"modelUsage":'+
                '{"modelo":{"inputTokens":n,"cacheReadInputTokens":5,"cacheCreationInputTokens":2,"outputTokens":3}}}]\n'+
                'for e in eventos:print(json.dumps(e),flush=True)\n',encoding='utf-8')
            with patch('providers_console.comando_nativo',return_value=[sys.executable,str(fake)]),redirect_stdout(io.StringIO()):
                self.assertEqual(executar(PROVIDERS['claude'],'claude',p,'Dev',prompt='Teste',banco=p/'office.db',ao_sessao=sessoes.append),0)
                self.assertEqual(executar(PROVIDERS['claude'],'claude',p,'QA',prompt='Retomar',sessao=sessoes[0],banco=p/'office.db'),0)
            gs={g['agente']:g for g in Registro(p/'consumo_providers.db').resumo()['grupos']}
            self.assertEqual(gs['Dev']['total'],20);self.assertEqual(gs['QA']['total'],10)
    def test_claude_novo_agregado_por_modelo_sem_duplica_filhos(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'uso.db';c=Coletor(db,'claude',tmp,'Dev',sessao_claude_nova='s')
            c.consumir({'type':'system','subtype':'init','tools':['Read','Agent'],'session_id':'s'})
            ev={'type':'result','session_id':'s','is_error':False,'modelUsage':{'modelo':{
                'inputTokens':100,'cacheReadInputTokens':40,'cacheCreationInputTokens':20,'outputTokens':30}}}
            c.consumir(ev);c.consumir(ev)
            c.consumir({**ev,'parent_tool_use_id':'filho'})
            ev['modelUsage']['modelo']['inputTokens']=120;c.consumir(ev)
            ev['modelUsage']['modelo']['inputTokens']=1;c.consumir(ev)
            g=Registro(db).resumo()['grupos'][0]
            self.assertEqual((g['entrada'],g['saida'],g['total'],g['amostras']),(180,30,210,1))
            self.assertEqual(g['origem_modelo'],'informado');self.assertIsNone(Registro(db).resumo()['cobranca_usd'])
    def test_claude_historico_local_ou_sessao_foreign_nao_entram(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'uso.db'
            ev={'type':'result','session_id':'s','is_error':False,'modelUsage':{'modelo':{
                'inputTokens':100,'cacheReadInputTokens':0,'cacheCreationInputTokens':0,'outputTokens':20}}}
            for c in (Coletor(db,'claude',tmp,'Dev'),Coletor(db,'claude',tmp,'Dev',sessao_claude_nova='esperada')):
                c.consumir({'type':'system','subtype':'init','session_id':'s','tools':['Read']});c.consumir(ev)
            self.assertFalse(db.exists())
            with self.assertRaises(ValueError):Coletor(db,'claude',tmp,'Dev',rotulo='claude_local',sessao_claude_nova='s')
    def test_launcher_claude_novo_conta_mas_resume_nao_importa_historico(self):
        from console_provider import executar
        from providers_console import PROVIDERS
        from contextlib import redirect_stdout
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);fake=p/'fake.py'
            fake.write_text('import os,sys,json\nsys.stdin.read()\ns=os.environ["OFFICE_CLAUDE_STREAM_SESSION"]\n'+
                'eventos=[{"type":"system","subtype":"init","tools":["Read","Agent"],"session_id":s},'+
                '{"type":"result","subtype":"success","session_id":s,"is_error":False,"modelUsage":'+
                '{"modelo-nativo":{"inputTokens":10,"cacheReadInputTokens":5,"cacheCreationInputTokens":2,"outputTokens":3}}}]\n'+
                'for e in eventos:print(json.dumps(e),flush=True)\n',encoding='utf-8')
            for sessao in (None,'s-historico'):
                db=p/('novo.db' if sessao is None else 'resume.db')
                with patch('providers_console.comando_nativo',return_value=[sys.executable,str(fake)]),redirect_stdout(io.StringIO()):
                    self.assertEqual(executar(PROVIDERS['claude'],'claude',p,'Dev',prompt='Teste',sessao=sessao,banco=db),0)
                grupos=Registro(p/'consumo_providers.db').resumo()['grupos']
                self.assertEqual(sum(g['total'] for g in grupos),20)
                self.assertEqual(grupos[0]['amostras'],1)
    def test_saldo_atomico_com_observadores_concorrentes(self):
        with tempfile.TemporaryDirectory() as tmp:
            registro = Registro(Path(tmp)/'uso.db')
            tokens = {'input_tokens':100, 'cached_input_tokens':80, 'output_tokens':20, 'total_tokens':120}
            with ThreadPoolExecutor(max_workers=4) as pool:
                resultados = list(pool.map(lambda _: registro.cumulativo_codex('p', 's', 'Dev', 'modelo', tokens), range(8)))
            self.assertTrue(all(resultados))
            g = registro.resumo()['grupos'][0]
            self.assertEqual((g['amostras'], g['total']), (1, 120))

    def test_rollout_incrementos_reinicio_replay_e_modelo(self):
        with tempfile.TemporaryDirectory() as tmp:
            arq = Path(tmp) / 'uso.db'
            c = ColetorRollout(arq, tmp, 'Dev', 's1', True)
            def uso(entrada, cache, saida):
                return {'type': 'event_msg', 'payload': {'type': 'token_count', 'info': {
                    'total_token_usage': {'input_tokens': entrada, 'cached_input_tokens': cache,
                                         'output_tokens': saida, 'total_tokens': entrada+saida}}}}
            c.consumir({'type': 'turn_context', 'payload': {'model': 'modelo-real'}})
            c.consumir(uso(100, 80, 20)); c.consumir(uso(100, 80, 20))
            c.consumir(uso(150, 100, 30))
            g = Registro(arq).resumo()['grupos'][0]
            self.assertEqual((g['total'], g['cache'], g['amostras']), (180, 100, 2))
            retomada = ColetorRollout(arq, tmp, 'Dev', 's1', False)
            retomada.consumir({'type': 'turn_context', 'payload': {'model': 'modelo-real'}})
            retomada.consumir(uso(150, 100, 30), base=True)
            retomada.consumir(uso(200, 120, 40))
            retomada.consumir(uso(100, 80, 20)) # Contador antigo não rebaixa saldo.
            g = Registro(arq).resumo()['grupos'][0]
            self.assertEqual((g['total'], g['amostras'], g['origem_modelo']), (240, 3, 'informado'))
            desconhecida = ColetorRollout(arq, tmp, 'QA', 's2', False)
            desconhecida.consumir(uso(500, 400, 100)) # Sem baseline, não cobra histórico.
            desconhecida.consumir(uso(550, 420, 110))
            gs = Registro(arq).resumo()['grupos']
            self.assertEqual(next(g['total'] for g in gs if g['agente']=='QA'), 60)

    def test_observador_consumo_resume_e_filhos_sem_duplica_pai_stream(self):
        from codex_observador import Observador
        from consumo_providers import identidade_projeto
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp); arq = raiz / 'uso.db'
            principal=raiz/'principal';principal.mkdir()
            pasta = raiz / 'sessions/2026/10/09'; pasta.mkdir(parents=True)
            meta = lambda ident: {'type': 'session_meta', 'payload': {'id': ident, 'cwd': str(raiz), 'source': 'cli'}}
            def uso(n):
                return {'type': 'event_msg', 'payload': {'type': 'token_count', 'info': {'total_token_usage': {
                    'input_tokens': n, 'cached_input_tokens': 0, 'output_tokens': 0, 'total_tokens': n}}}}
            def escrever(f, itens, modo='w'):
                with f.open(modo, encoding='utf-8') as saida:
                    for item in itens: saida.write(json.dumps(item)+'\n')
            pai = pasta/'rollout-pai.jsonl'
            escrever(pai, [meta('pai'), {'type': 'turn_context', 'payload': {'model': 'modelo'}}, uso(100)])
            factory = lambda agente, sessao, novo: ColetorRollout(arq, principal, agente, sessao, novo)
            o = Observador(raiz, 'Dev', lambda ev: None, sessao='pai', home=raiz, criar_consumo=factory)
            o.tick(); self.assertEqual(Registro(arq).resumo()['grupos'], [])
            escrever(pai, [uso(120)], 'a'); o.tick()
            self.assertEqual(Registro(arq).resumo()['grupos'][0]['total'], 20)
            stream = Observador(raiz, 'Dev', lambda ev: None, home=raiz, observar_principal=False, criar_consumo=factory)
            stream.sessao = 'pai'
            filho = meta('filho'); filho['payload']['source'] = {'subagent': {'thread_spawn': {'parent_thread_id':'pai'}}}
            escrever(pasta/'rollout-filho.jsonl', [filho, uso(10)])
            escrever(pai, [uso(200)], 'a'); stream.tick()
            gs = Registro(arq).resumo()['grupos']
            self.assertEqual(next(g['total'] for g in gs if g['agente']=='Dev'), 20)
            self.assertEqual(sum(g['total'] for g in gs), 30)
            self.assertEqual(Registro(arq).resumo(projeto_hash=identidade_projeto(raiz))['grupos'],[])
            self.assertEqual(sum(g['total'] for g in Registro(arq).resumo(projeto_hash=identidade_projeto(principal))['grupos']),30)

    def test_launcher_grava_consumo_sem_alterar_saida_ou_eventos(self):
        import console_provider
        with tempfile.TemporaryDirectory() as tmp:
            pasta = Path(tmp)
            registro = {'type': 'result', 'status':'success', 'stats': {'models': {'modelo-real': {
                'input_tokens': 50, 'output_tokens': 10, 'total_tokens': 70}}}}
            inicio={'type':'init','session_id':'s','model':'modelo-real'}
            processo = SimpleNamespace(stdout=io.StringIO(json.dumps(inicio)+'\n'+json.dumps(registro) + '\n'),
                                      stdin=io.StringIO(), wait=lambda: 0)
            provider = SimpleNamespace(nome='gemini', capacidades=SimpleNamespace(eventos_json=True),
                                       comando=lambda *args: ['gemini', 'prompt'])
            with patch('console_provider.contexto', return_value='Regras'), \
                 patch('console_provider.subprocess.Popen', return_value=processo), \
                 patch('emit_evento.gravar') as feed, patch('sys.stdout', new_callable=io.StringIO) as saida:
                codigo = console_provider.executar(provider, 'gemini', pasta, 'Pesquisa', 'Tarefa', banco=pasta / 'feed.db')
                self.assertEqual(codigo, 0)
                self.assertIn('modelo-real', saida.getvalue())
                self.assertGreaterEqual(feed.call_count, 2)
            g = Registro(pasta / 'consumo_providers.db').resumo()['grupos'][0]
            self.assertEqual((g['provider'], g['modelo'], g['total']), ('gemini', 'modelo-real', 70))

    def test_codex_persistencia_cache_e_retoma(self):
        with tempfile.TemporaryDirectory() as tmp:
            arq = Path(tmp) / 'consumo.db'
            c = Coletor(arq, 'codex', tmp, 'Dev', 'modelo-configurado')
            c.consumir({'type': 'thread.started', 'thread_id': 's1'})
            ev = {'type': 'turn.completed', 'usage': {'input_tokens': 100, 'cached_input_tokens': 80, 'output_tokens': 20}}
            c.consumir(ev); c.consumir(ev)
            g = Registro(arq).resumo()['grupos'][0]
            self.assertEqual((g['amostras'], g['entrada'], g['cache'], g['total']), (1, 100, 80, 120))
            self.assertEqual(g['origem_modelo'], 'configurado')
            outra = Coletor(arq, 'codex', tmp, 'Dev', 'modelo-configurado')
            outra.consumir({'type': 'thread.started', 'thread_id': 's1'})
            outra.consumir(ev)
            self.assertEqual(Registro(arq).resumo()['grupos'][0]['total'], 240)

    def test_gemini_modelos_sem_duplicar_agregado(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = Coletor(Path(tmp) / 'uso.db', 'gemini', tmp, 'Pesquisa', 'auto')
            c.consumir({'type': 'result', 'stats': {'total_tokens': 999, 'models': {
                'flash': {'input_tokens': 100, 'output_tokens': 20, 'cached': 50, 'total_tokens': 130},
                'pro': {'input_tokens': 200, 'output_tokens': 30, 'cached': 80, 'total_tokens': 250}}}})
            gs = c.registro.resumo()['grupos']
            self.assertEqual(sum(g['total'] for g in gs), 380)
            self.assertEqual({g['modelo'] for g in gs}, {'flash', 'pro'})
            self.assertTrue(all(g['origem_modelo'] == 'informado' for g in gs))

    def test_ausencia_qualidade_janela_e_leitura_sem_escrita(self):
        with tempfile.TemporaryDirectory() as tmp:
            arq = Path(tmp) / 'uso.db'
            self.assertEqual(Registro(arq).resumo()['grupos'], [])
            self.assertFalse(arq.exists())
            c = Coletor(arq, 'codex', tmp, 'Dev')
            c.consumir({'type': 'turn.completed', 'usage': {'input_tokens': True, 'output_tokens': -1}})
            self.assertFalse(arq.exists())
            c.consumir({'type': 'turn.completed', 'usage': {'input_tokens': 10}})
            g = Registro(arq).resumo()['grupos'][0]
            self.assertIsNone(g['total']); self.assertIsNone(g['saida'])
            self.assertEqual(g['com_total'], 0)
            self.assertIsNone(Registro(arq).resumo()['cobranca_usd'])
            self.assertEqual(Registro(arq).resumo(time.time() + 8 * 86400)['grupos'], [])
            self.assertNotIn(tmp, str(Registro(arq).resumo()))
            with self.assertRaises(ValueError):
                c.consumir({'type': 'turn.completed', 'usage': {'input_tokens': 10, 'cached_input_tokens': 20}})


    def test_opencode_etapas_cache_raciocinio_replay_e_namespace(self):
        with tempfile.TemporaryDirectory() as tmp:
            arq=Path(tmp)/'uso.db'
            def evento(ident, total=None):
                uso={'input':10,'output':20,'reasoning':5,'cache':{'read':80,'write':7}}
                if total is not None: uso['total']=total
                return {'type':'step_finish','sessionID':'s1','part':{
                    'type':'step-finish','id':ident,'sessionID':'s1','tokens':uso,'cost':999}}
            c=Coletor(arq,'opencode',tmp,'Dev','openai/modelo')
            c.consumir(evento('p1')); c.consumir(evento('p1'))
            c=Coletor(arq,'opencode',tmp,'Dev','openai/modelo')
            c.consumir(evento('p1')) # Retomada não duplica a parte já observada.
            c.consumir(evento('p2',130)) # Preserva total nativo independente.
            g=c.registro.resumo()['grupos'][0]
            self.assertEqual((g['amostras'],g['entrada'],g['cache'],g['saida'],g['total']),
                             (2,194,160,50,252))
            self.assertEqual((g['provider'],g['provider_modelo'],g['origem_provider_modelo']),
                             ('opencode','openai','configurado'))
            self.assertIsNone(c.registro.resumo()['cobranca_usd'])
            self.assertNotIn('s1',str(c.registro.resumo()))
            self.assertNotIn(tmp,str(c.registro.resumo()))
            local=Coletor(arq,'opencode',tmp,'Local','ollama/modelo',rotulo='opencode_local')
            ev=evento('local'); ev['sessionID']=ev['part']['sessionID']='local'
            local.consumir(ev)
            self.assertEqual({g['provider'] for g in c.registro.resumo()['grupos']},
                             {'opencode','opencode_local'})

    def test_opencode_identidade_estruturada_nao_colide_por_separador(self):
        with tempfile.TemporaryDirectory() as tmp:
            c=Coletor(Path(tmp)/'uso.db','opencode',tmp,'Dev')
            for sessao,ident in [('a|b','c'),('a','b|c')]:
                c.consumir({'type':'step_finish','sessionID':sessao,'part':{
                    'type':'step-finish','sessionID':sessao,'id':ident,'tokens':{'total':10}}})
            g=c.registro.resumo()['grupos'][0]
            self.assertEqual((g['amostras'],g['total']),(2,20))

    def test_opencode_identidade_e_contadores_ausentes_invalidos(self):
        with tempfile.TemporaryDirectory() as tmp:
            arq=Path(tmp)/'uso.db'; c=Coletor(arq,'opencode',tmp,'Dev')
            ev={'type':'step_finish','sessionID':'s','part':{
                'id':'p','type':'step-finish','sessionID':'outra','tokens':{'total':10}}}
            c.consumir(ev); self.assertFalse(arq.exists())
            ev['part']['sessionID']='s'; ev['part'].pop('id'); c.consumir(ev)
            self.assertFalse(arq.exists())
            ev['part']['id']='p'; ev['part']['tokens']={'input':10,'output':20,'reasoning':0}
            c.consumir(ev)
            g=c.registro.resumo()['grupos'][0]
            self.assertIsNone(g['entrada']); self.assertIsNone(g['total'])
            self.assertEqual(g['saida'],20); self.assertIsNone(g['provider_modelo'])
            ev['part']['id']='q'; ev['part']['tokens']={
                'input':True,'output':-1,'reasoning':float('inf'),'cache':{'read':0,'write':0},'total':None}
            c.consumir(ev); self.assertEqual(c.registro.resumo()['grupos'][0]['amostras'],1)
            ev['part']['id']='r'; ev['part']['tokens']={
                'input':2**53-1,'output':0,'reasoning':0,'cache':{'read':1,'write':0}}
            c.consumir(ev); gs=c.registro.resumo()['grupos'][0]
            self.assertIsNone(gs['entrada']); self.assertIsNone(gs['total'])
            self.assertEqual(gs['com_saida'],2)

    def test_launcher_opencode_grava_etapas_preserva_eventos_e_saida(self):
        import console_provider
        with tempfile.TemporaryDirectory() as tmp:
            pasta=Path(tmp)
            ev={'type':'step_finish','sessionID':'s','part':{'type':'step-finish','id':'p',
                'sessionID':'s','messageID':'m','reason':'stop','tokens':{'input':10,'output':2,'reasoning':1,
                'cache':{'read':20,'write':0}}}}
            inicio={'type':'step_start','sessionID':'s','part':{'type':'step-start','id':'inicio',
                'sessionID':'s','messageID':'m'}}
            processo=SimpleNamespace(stdout=io.StringIO(json.dumps(inicio)+'\n'+json.dumps(ev)+'\n'),stdin=io.StringIO(),wait=lambda:0)
            provider=SimpleNamespace(nome='opencode',capacidades=SimpleNamespace(eventos_json=True),
                                     comando=lambda *args:['opencode','run','Tarefa'])
            with patch('console_provider.subprocess.Popen',return_value=processo), \
                 patch('emit_evento.gravar') as feed, patch('sys.stdout',new_callable=io.StringIO) as saida:
                self.assertEqual(console_provider.executar(provider,'opencode',pasta,'Dev','Tarefa',
                    modelo='openai/modelo',banco=pasta/'feed.db'),0)
                self.assertIn('step_finish',saida.getvalue())
                self.assertTrue(any(c.args[0]['tipo']=='ocioso' for c in feed.call_args_list))
            g=Registro(pasta/'consumo_providers.db').resumo()['grupos'][0]
            self.assertEqual((g['entrada'],g['saida'],g['total']),(30,3,33))


    def test_ponte_plugin_limites_origem_informada_e_replay(self):
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            arq=Path(tmp)/'uso.db'
            script=Path(__file__).resolve().parent.parent/'consumo_providers.py'
            payload={'projeto':tmp,'agente':'Dev','modelo':'google/modelo','evento':{
                'type':'step_finish','sessionID':'s','part':{'type':'step-finish','id':'p',
                'sessionID':'s','tokens':{'total':20}}}}
            def rodar(dados):
                return subprocess.run([sys.executable,str(script),'--opencode','--banco',str(arq)],
                    input=dados,capture_output=True)
            for _ in range(2): self.assertEqual(rodar(json.dumps(payload).encode()).returncode,0)
            g=Registro(arq).resumo()['grupos'][0]
            self.assertEqual((g['amostras'],g['total'],g['origem_modelo'],g['provider_modelo']),
                             (1,20,'informado','google'))
            for invalido in [b'{',b' '*131073,json.dumps({**payload,'texto':'SECRETO'}).encode(),
                             json.dumps({**payload,'projeto':'relativo'}).encode()]:
                r=rodar(invalido); self.assertEqual(r.returncode,2)
                self.assertNotIn(b'SECRETO',r.stderr); self.assertEqual(r.stdout,b'')
            self.assertEqual(Registro(arq).resumo()['grupos'][0]['amostras'],1)


if __name__ == '__main__':
    unittest.main()
