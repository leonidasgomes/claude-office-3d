"""Claude novo: processo/SQLite reais, envelopes sintéticos, sem inferência ou rede."""
import contextlib
import io
import json
import os
from pathlib import Path
import sqlite3
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from providers_console import PROVIDERS, Eventos, sessao_nativa
from console_provider import executar


def registro(tipo, **campos):
    return dict(type=tipo, session_id='raiz', **({'subtype':'error_during_execution' if campos.get('is_error') else 'success'} if tipo=='result' else {}), **campos)


class ClaudePadronizado(unittest.TestCase):
    def test_resultado_erro_nao_vira_sucesso_mesmo_com_exit_zero(self):
        for erro,filho,codigo,esperado in [(True,None,0,1),(True,None,7,7),(False,None,0,0),(True,'t-pai',0,0)]:
            with self.subTest(erro=erro,filho=filho,codigo=codigo),tempfile.TemporaryDirectory() as tmp:
                raiz=Path(tmp);fake=raiz/'fake.py'
                result=registro('result',is_error=erro,parent_tool_use_id=filho)
                fluxo=[registro('system',subtype='init'),result]+([registro('result',is_error=False)] if filho else [])
                fake.write_text('import sys,json\nsys.stdin.read()\nfor e in '+repr(fluxo)+':print(json.dumps(e),flush=True)\nsys.exit('+str(codigo)+')',encoding='utf-8')
                with patch('providers_console.comando_nativo',return_value=[sys.executable,str(fake)]),contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(executar(PROVIDERS['claude'],'claude',raiz,'Dev',prompt='teste',banco=raiz/'db'),esperado)

    def test_falha_de_vinculo_encerra_processo_real_e_preserva_excecao(self):
        import console_provider as launcher
        iniciar=subprocess.Popen
        processos=[]
        def capturar(*args,**kwargs):
            p=iniciar(*args,**kwargs);processos.append(p);return p
        with tempfile.TemporaryDirectory() as tmp:
            raiz=Path(tmp);fake=raiz/'fake.py'
            fake.write_text('import sys,json,time\nsys.stdin.read()\nprint(json.dumps('+repr(registro('system',subtype='init'))+'),flush=True)\ntime.sleep(60)',encoding='utf-8')
            def falhar(ident): raise ValueError('vínculo divergente')
            with patch('providers_console.comando_nativo',return_value=[sys.executable,str(fake)]), \
                 patch.object(launcher.subprocess,'Popen',side_effect=capturar),contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(ValueError,'vínculo divergente'):
                    executar(PROVIDERS['claude'],'claude',raiz,'Dev',prompt='teste',banco=raiz/'db',ao_sessao=falhar)
            self.assertEqual(len(processos),1)
            self.assertIsNotNone(processos[0].poll())
            self.assertTrue(processos[0].stdout.closed)

    def test_tui_nao_herda_propriedade_de_stream(self):
        from types import SimpleNamespace
        processo=SimpleNamespace(wait=lambda:0,stdout=None,stdin=None)
        with tempfile.TemporaryDirectory() as tmp, \
             patch.dict(os.environ,{'OFFICE_CLAUDE_STREAM_HOOK':'pai.py','OFFICE_CLAUDE_STREAM_SESSION':'pai'}), \
             patch('console_provider.subprocess.Popen',return_value=processo) as iniciar:
            self.assertEqual(executar(PROVIDERS['claude'],'claude',Path(tmp),'Dev',banco=Path(tmp)/'db'),0)
            env=iniciar.call_args.kwargs['env']
            self.assertNotIn('OFFICE_CLAUDE_STREAM_HOOK',env)
            self.assertNotIn('OFFICE_CLAUDE_STREAM_SESSION',env)
            self.assertEqual(iniciar.call_args.args[0],['claude'])
    def test_filtro_exige_hook_sessao_e_pai_sem_apagar_coordenacao(self):
        import registrar_evento as hook
        ev={'session_id':'sessao','hook_event_name':'PostToolUse','tool_name':'Read'}
        env={'OFFICE_CLAUDE_STREAM_HOOK':str(Path(hook.__file__).resolve()),'OFFICE_CLAUDE_STREAM_SESSION':'sessao'}
        with patch.dict(os.environ,env):
            self.assertTrue(hook.principal_no_stream(ev))
            for campo,valor in [('agent_id','filho'),('teammate_name','Dev'),('agent_name','Revisor'),
                                ('agent_transcript_path','filho.jsonl'),('session_id','outra'),
                                ('hook_event_name','SubagentStop'),('tool_name','Agent'),('tool_name','SendMessage')]:
                self.assertFalse(hook.principal_no_stream({**ev,campo:valor}))
            with patch.dict(os.environ,{'OFFICE_CLAUDE_STREAM_HOOK':str(Path(hook.__file__).parent/'outro.py')}):
                self.assertFalse(hook.principal_no_stream(ev))
        with patch.dict(os.environ,{'OFFICE_CLAUDE_STREAM_HOOK':'','OFFICE_CLAUDE_STREAM_SESSION':''}):
            self.assertFalse(hook.principal_no_stream(ev))

    def test_hook_e_stream_no_mesmo_banco_sem_duplicar_pai_preservando_filho(self):
        import console_provider as launcher
        with tempfile.TemporaryDirectory() as tmp:
            raiz=Path(tmp)
            for nome in ('registrar_evento.py','configuracao.py','banco.py'):
                shutil.copyfile(Path(launcher.__file__).parent/nome,raiz/nome)
            (raiz/'config.json').write_text('{}',encoding='utf-8')
            fake=raiz/'fake.py'
            fake.write_text('''import os,sys,json,subprocess
from pathlib import Path
sys.stdin.read()
s=os.environ['OFFICE_CLAUDE_STREAM_SESSION']
assert sys.argv[sys.argv.index('--session-id')+1]==s
assert '--bare' not in sys.argv and '--dangerously-skip-permissions' not in sys.argv
Path('guardian-executado.txt').write_text('hook independente mantido')
h={'session_id':s,'cwd':str(Path.cwd()),'hook_event_name':'PostToolUse','tool_name':'Read','tool_input':{'file_path':'arquivo'}}
for ev in (h,dict(h,agent_id='filho',agent_type='explore')):
    subprocess.run([sys.executable,os.environ['OFFICE_CLAUDE_STREAM_HOOK']],input=json.dumps(ev),text=True,check=True)
for r in (
    {'type':'system','subtype':'init','session_id':s},
    {'type':'assistant','session_id':s,'message':{'id':'m1','content':[{'type':'tool_use','id':'t1','name':'Read','input':{'file_path':'arquivo'}}]}},
    {'type':'user','session_id':s,'message':{'content':[{'type':'tool_result','tool_use_id':'t1','content':'ok'}]}},
    {'type':'result','subtype':'success','session_id':s,'is_error':False}):
    print(json.dumps(r),flush=True)
''',encoding='utf-8')
            sessoes=[]
            with patch.object(launcher,'RAIZ',raiz),patch('providers_console.comando_nativo',return_value=[sys.executable,str(fake)]), \
                 patch.dict(os.environ,{'OFFICE_CONFIG':str(raiz/'config.json'),'OFFICE_AGENTE':''}),contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(executar(PROVIDERS['claude'],'claude',raiz,'Office_'+'a'*32,prompt='Leia',
                                 banco=raiz/'dados/escritorio.db',ao_sessao=sessoes.append),0)
            self.assertEqual(len(sessoes),1)
            self.assertTrue((raiz/'guardian-executado.txt').exists())
            with contextlib.closing(sqlite3.connect(raiz/'dados/escritorio.db')) as c:
                evs=[json.loads(x[0]) for x in c.execute('select dados from evento')]
            pai=[e for e in evs if e.get('ferramenta')=='Read' and e.get('agente')=='Office_'+'a'*32]
            self.assertEqual(len(pai),2)  # um início e um resultado, sem PostToolUse duplicado
            self.assertTrue(any(e.get('agente')=='Explorador' for e in evs))

    def test_comandos_tui_e_stream_sem_bypass(self):
        p=PROVIDERS['claude']
        self.assertEqual(p.comando('claude',Path('.')),['claude'])
        self.assertEqual(p.comando('claude',Path('.'),sessao='id'),['claude','--resume','id'])
        args=p.comando('claude',Path('.'),prompt='segredo',modelo='sonnet',agente='Marketing',sessao='id')
        self.assertEqual(args,['claude','--resume','id','--agent','Marketing','--model','sonnet','-p','--verbose','--output-format','stream-json'])
        self.assertNotIn('segredo',args)
        self.assertTrue(p.capacidades.team_nativo)
        self.assertTrue(p.capacidades.eventos_json)

    def test_sessao_pai_deduplicacao_ferramenta_e_erro(self):
        e=Eventos('claude','Dev')
        init=registro('system',subtype='init')
        self.assertEqual(e.converter(init),[])
        self.assertEqual(e.sessao,'raiz')
        self.assertIsNone(sessao_nativa('claude',dict(init,parent_tool_use_id='filho')))
        a=registro('assistant',message={'id':'m1','content':[
            {'type':'thinking','thinking':'privado'},
            {'type':'text','text':'Vou verificar'},
            {'type':'tool_use','id':'t1','name':'Read','input':{'file_path':'arquivo'}}]})
        eventos=e.converter(a)
        self.assertEqual([x['tipo'] for x in eventos],['fala','trabalho'])
        self.assertEqual(e.converter(a),[])
        self.assertEqual(e.converter(dict(a,parent_tool_use_id='t-pai')),[])
        self.assertEqual(e.converter(dict(a,session_id='outra')),[])
        resultado=registro('user',message={'content':[{'type':'tool_result','tool_use_id':'t1','is_error':True,'content':'não copiar saída'}]})
        ev=e.converter(resultado)[0]
        self.assertFalse(ev['ok'])
        self.assertNotIn('não copiar',json.dumps(ev))
        self.assertEqual(e.converter(resultado),[])
        self.assertEqual(e.converter(registro('result',is_error=True))[0]['ok'],False)
        self.assertEqual(e.converter(registro('result',is_error=True)),[])

    def test_subprocesso_stdin_sessao_e_sqlite(self):
        with tempfile.TemporaryDirectory() as tmp:
            raiz=Path(tmp)
            (raiz/'CLAUDE.md').write_text('Regra compartilhada',encoding='utf-8')
            registros=[registro('system',subtype='init'),registro('system',subtype='init'),
                registro('assistant',message={'id':'m2','content':[{'type':'text','text':'Pronto'}]}),
                registro('result',is_error=False)]
            fake=raiz/'fake.py'
            fake.write_text('import sys,json\nfrom pathlib import Path\nPath("entrada.txt").write_text(sys.stdin.read(),encoding="utf-8")\nfor r in '+repr(registros)+': print(json.dumps(r),flush=True)\n',encoding='utf-8')
            sessoes=[]
            with patch('providers_console.comando_nativo',return_value=[sys.executable,str(fake)]),contextlib.redirect_stdout(io.StringIO()):
                codigo=executar(PROVIDERS['claude'],'claude',raiz,'Dev',prompt='Tarefa com $() e acentos',
                                 banco=raiz/'office.db',ao_sessao=sessoes.append)
            self.assertEqual(codigo,0)
            self.assertEqual(sessoes,['raiz'])
            entrada=(raiz/'entrada.txt').read_text(encoding='utf-8')
            self.assertIn('Tarefa com $() e acentos',entrada)
            self.assertIn('CLAUDE.md',entrada)
            with contextlib.closing(sqlite3.connect(raiz/'office.db')) as c:
                eventos=[json.loads(x[0]) for x in c.execute('select dados from evento')]
            self.assertTrue(any(x.get('texto')=='Pronto' and x['sessao']=='raiz' for x in eventos))
            self.assertTrue(all(x['fonte']=='claude' for x in eventos))


if __name__=='__main__': unittest.main()
