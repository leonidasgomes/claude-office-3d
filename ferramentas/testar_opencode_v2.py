"""V2: prova textual exata, falhas fechadas e V1 inalterado. Sem chamadas a modelos."""
import copy,json,sys,tempfile,unittest,subprocess
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from retorno_console import Retorno
from opencode_v2 import validar_export, confirmar, versao


class V2(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.raiz=Path(self.tmp.name).resolve();self.prompt='teste';self.model='opencode/free'
        self.reg=[{'type':'step_start','sessionID':'ses_1','part':{'type':'step-start','sessionID':'ses_1','messageID':'msg_1'}},
                  {'type':'text','sessionID':'ses_1','part':{'type':'text','sessionID':'ses_1','messageID':'msg_1','text':'feito'}}]
        self.r=Retorno('opencode')
        for ev in self.reg:self.r.consumir(ev)
        self.data={'info':{'id':'ses_1','outcome':'succeeded','location':{'directory':str(self.raiz)}},'messages':[
            {'type':'user','id':'u1','text':'instruções\nteste','time':{'created':101}},
            {'type':'assistant','id':'msg_1','finish':'stop','model':{'providerID':'opencode','id':'free'},
             'time':{'created':102,'completed':103},'content':[{'type':'text','text':'feito'}],'cost':0,'tokens':{'input':5,'output':1,'reasoning':0,'cache':{'read':0,'write':0}}},
            {'type':'idle','outcome':'succeeded','time':{'created':104}}]}
    def validate(self,d=None):
        return validar_export(self.data if d is None else d,self.r,self.raiz,100,self.prompt,self.model,self.reg)
    def test_success_requires_matching_native_evidence(self):
        self.assertFalse(self.r.sucesso());fim=self.validate();self.assertEqual(fim['source'],'opencode.v2.session.export')
        self.r.consumir(fim);self.assertTrue(self.r.sucesso())
    def test_stale_wrong_cancelled_missing_failed(self):
        mutations=[lambda d:d['info'].update(id='ses_other'),lambda d:d['info'].update(outcome='failed'),
            lambda d:d['info']['location'].update(directory='/another'),lambda d:d['messages'][0]['time'].update(created=99),
            lambda d:d['messages'][0].update(text='outro'),lambda d:d['messages'][1].update(id='old'),
            lambda d:d['messages'][1].update(finish='length'),lambda d:d['messages'][1].update(error='failed'),
            lambda d:d['messages'][1]['time'].update(completed=0),lambda d:d['messages'][1]['time'].pop('completed'),
            lambda d:d['messages'][1]['model'].update(id='paid'),lambda d:d['messages'][1].update(content=[]),
            lambda d:d['messages'][1].update(content=[{'type':'tool','state':'pending'}]),
            lambda d:d['messages'][1].update(content=[{'type':'text','text':'outro'}]),
            lambda d:d['messages'][-1].update(outcome='cancelled'),lambda d:d['messages'].append({'type':'user'}),
            lambda d:d['info'].update(error='err'),lambda d:d.update(messages=[])]
        for mutate in mutations:
            d=copy.deepcopy(self.data);mutate(d)
            with self.subTest(data=d):self.assertIsNone(self.validate(d))
    def test_no_output_error_and_tool_streams_stay_blocked(self):
        for event in ({'type':'error'},{'type':'tool_use'},{'type':'session.error'}):
            self.reg.append(event);self.assertIsNone(self.validate());self.reg.pop()
        self.reg.pop();self.assertIsNone(self.validate())
        self.reg.append({'type':'text','part':{'text':'feito'}});self.r.falhou=True;self.assertIsNone(self.validate())
    def ferramentas(self, nome='write'):
        self.data['messages'][1]['time'] = {'created':108, 'completed':109}
        self.data['messages'][-1]['time']['created'] = 110
        entrada = {'path':'note.txt', 'content':'feito'}
        content = [{'type':'text','text':'File operation succeeded'}]
        tool = {'type':'tool','id':'call1','name':nome,'executed':False,
                'state':{'status':'completed','input':entrada,'content':content,'metadata':{}},
                'time':{'created':103,'ran':104,'completed':105}}
        mensagem = {'type':'assistant','id':'msg_tool','finish':'tool-calls',
                    'model':{'providerID':'opencode','id':'free'},
                    'time':{'created':102,'completed':107},'content':[tool],
                    'cost':0,'tokens':{'input':5,'output':2}}
        self.data['messages'].insert(1,mensagem)
        def evento(tipo,part):
            return {'type':tipo,'sessionID':'ses_1','part':dict(sessionID='ses_1',messageID='msg_tool',**part)}
        self.reg[:0] = [evento('step_start',{'type':'step-start'}),
            evento('tool_use',{'type':'tool','id':'call1','tool':nome,
                'state':{'status':'completed','input':entrada,'output':'File operation succeeded',
                         'metadata':{'content':content,'metadata':{},'providerCall':{'executed':False},'providerResult':{'executed':False}},
                         'time':{'start':103,'end':105}}}),
            evento('step_finish',{'id':'finish_tool','type':'step-finish','reason':'tool-calls','cost':0,'tokens':{'input':5,'output':2}})]
        self.r=Retorno('opencode')
        for ev in self.reg:self.r.consumir(ev)

    def test_file_tools_require_native_terminal_before_final_text(self):
        for nome in ('write','read','edit'):
            with self.subTest(nome=nome):
                self.setUp();self.ferramentas(nome);fim=self.validate()
                self.assertIsNotNone(fim);self.r.consumir(fim);self.assertTrue(self.r.sucesso())

    def test_file_tool_native_failures_and_divergences_stay_blocked(self):
        self.ferramentas()
        mutations=[lambda d:d['messages'][1].update(finish='stop'),
            lambda d:d['messages'][1].update(error='failed'),
            lambda d:d['messages'][1].update(id='other'),
            lambda d:d['messages'][1]['model'].update(id='paid'),
            lambda d:d['messages'][1]['time'].update(created=99),
            lambda d:d['messages'][1]['time'].update(completed=109),
            lambda d:d['messages'][1].update(cost=10),
            lambda d:d['messages'][1].update(content=[]),
            lambda d:d['messages'][1]['content'][0].update(name='shell'),
            lambda d:d['messages'][1]['content'][0].update(id='call2'),
            lambda d:d['messages'][1]['content'][0].update(executed=True),
            lambda d:d['messages'][1]['content'][0]['state'].update(status='running'),
            lambda d:d['messages'][1]['content'][0]['state'].update(status='pending'),
            lambda d:d['messages'][1]['content'][0]['state'].update(status='error'),
            lambda d:d['messages'][1]['content'][0]['state'].update(error={'message':'denied'}),
            lambda d:d['messages'][1]['content'][0]['state'].update(input={'path':'other'}),
            lambda d:d['messages'][1]['content'][0]['state'].update(content=[]),
            lambda d:d['messages'][1]['content'][0]['time'].update(completed=106),
            lambda d:d['messages'][1]['content'][0]['time'].pop('ran'),
            lambda d:d['messages'].insert(-1,copy.deepcopy(d['messages'][1])),
            lambda d:d['messages'].insert(-1,{'type':'user','text':'\nteste','time':{'created':109}}),
            lambda d:d['messages'][-1].update(outcome='cancelled'),
            lambda d:d['messages'][-1].update(error='failed'),
            lambda d:d['messages'][-1]['time'].update(created=108),
            lambda d:d['info'].update(outcome='failed')]
        for mutate in mutations:
            d=copy.deepcopy(self.data);mutate(d)
            with self.subTest(data=d):self.assertIsNone(self.validate(d))

    def test_file_tool_stream_failures_missing_terminals_and_stale_turns(self):
        self.ferramentas();original=copy.deepcopy(self.reg)
        mutations=[lambda r:r.pop(2),lambda r:r[2]['part'].update(reason='stop'),
            lambda r:r[2]['part'].pop('id'),
            lambda r:r[2]['part'].update(id=''),
            lambda r:r[2]['part'].update(id='msg_1_office_verified'),
            lambda r:r[1]['part']['state'].update(status='error'),
            lambda r:r[1]['part']['state'].update(status='pending'),
            lambda r:r[1]['part']['state'].update(input={'path':'different'}),
            lambda r:r[1]['part']['state']['metadata'].update(content=[]),
            lambda r:r[1]['part']['state']['metadata'].pop('providerResult'),
            lambda r:r[1]['part']['state']['time'].update(start=104),
            lambda r:r[1]['part'].update(id='other'),
            lambda r:r[1].update(sessionID='other'),
            lambda r:r[1]['part'].update(messageID='other'),
            lambda r:r.insert(2,copy.deepcopy(r[1])),
            lambda r:r.insert(1,{'type':'error'}),
            lambda r:r.append({'type':'permission'}),
            lambda r:r[-1]['part'].update(text='other')]
        for mutate in mutations:
            self.reg=copy.deepcopy(original);mutate(self.reg)
            with self.subTest(reg=self.reg):self.assertIsNone(self.validate())
        self.reg=original
        for t in (111,float('nan'),float('inf'),True):
            self.assertIsNone(validar_export(self.data,self.r,self.raiz,t,self.prompt,self.model,self.reg))

    def test_generated_terminal_id_must_fit_consumption_contract(self):
        long_id='m'*256
        self.data['messages'][1]['id']=long_id
        for ev in self.reg:ev['part']['messageID']=long_id
        self.r=Retorno('opencode')
        for ev in self.reg:self.r.consumir(ev)
        self.assertIsNone(self.validate())

    def test_duplicate_terminal_ids_across_tool_steps_fail_closed(self):
        self.ferramentas()
        anterior=copy.deepcopy(self.data['messages'][1]);anterior['id']='msg_earlier'
        anterior['time']={'created':101,'completed':102}
        anterior['content'][0]['id']='call0';anterior['content'][0]['time']={'created':101,'ran':101,'completed':102}
        self.data['messages'].insert(1,anterior)
        reg=copy.deepcopy(self.reg[:3])
        for evento in reg:evento['part']['messageID']='msg_earlier'
        reg[1]['part']['id']='call0';reg[1]['part']['state']['time']={'start':101,'end':102}
        self.reg[:0]=reg
        self.assertIsNone(self.validate())
        self.reg[2]['part']['id']='finish_earlier'
        self.assertIsNotNone(self.validate())

    def test_file_tool_and_final_usage_are_distinct_and_idempotent(self):
        import sqlite3
        from consumo_providers import Coletor,tokens_opencode
        self.ferramentas()
        tokens={'input':7,'output':3,'reasoning':2,'cache':{'read':11,'write':13}}
        self.data['messages'][1]['tokens']=tokens;self.reg[2]['part']['tokens']=tokens
        path=self.raiz/'file-usage.db';collector=Coletor(path,'opencode',self.raiz,'Dev',self.model)
        proof=self.validate();self.assertIsNotNone(proof)
        for _ in range(2):
            for event in self.reg+[proof]:collector.consumir(event)
        expected=[tokens_opencode(m['tokens']) for m in self.data['messages'] if m['type']=='assistant']
        with sqlite3.connect(path) as db:
            row=db.execute('select count(*),sum(entrada),sum(cache),sum(saida),sum(total) from consumo').fetchone()
            self.assertEqual(row,(2,*(sum(t[k] for t in expected) for k in ('entrada','cache','saida','total'))))
            self.assertEqual(set(r[0] for r in db.execute('select fonte from consumo')),{'opencode.run/step_finish.v1','opencode.v2.session.export'})

    def test_resume_matches_only_latest_user_and_whole_exact_turn(self):
        self.ferramentas()
        self.data['messages'][:0]=[{'type':'user','text':'\nteste','time':{'created':1}},
                                 {'type':'assistant','id':'old'}, {'type':'idle','outcome':'succeeded'}]
        self.assertIsNotNone(self.validate())
        self.data['messages'][3]['text']='\nnew task'
        self.assertIsNone(self.validate())
        self.data['messages'][3]['text']='\nteste'
        self.data['messages'][3]['time']['created']=99
        self.assertIsNone(self.validate())

    def test_v1_completion_remains_accepted_without_export(self):
        self.r.consumir({'type':'step_finish','sessionID':'ses_1','part':{'type':'step-finish','sessionID':'ses_1','messageID':'msg_1','reason':'stop'}})
        self.assertTrue(self.r.sucesso());self.assertIsNone(self.validate())
    def test_timeout_invalid_version_and_export_fail_closed(self):
        for value in ('opencode v2.0.27', '2.0.27'):
            with patch('opencode_v2.consultar',return_value=value):
                self.assertTrue(versao('opencode',self.raiz,{}))
        for value in ('1.19.0','unknown','2.0.27\nnoise'):
            with patch('opencode_v2.consultar',return_value=value):
                self.assertFalse(versao('opencode',self.raiz,{}))
        with patch('opencode_v2.consultar',side_effect=subprocess.TimeoutExpired('test',15)):
            self.assertFalse(versao('opencode',self.raiz,{}))
        with patch('opencode_v2.consultar',side_effect=subprocess.TimeoutExpired('test',15)):
            self.assertIsNone(confirmar('opencode',self.raiz,{},self.r,100,self.prompt,self.model,self.reg))
    def test_malformed_exports_fail_closed(self):
        for d in (None,{},[],{'info':{},'messages':[]}):self.assertIsNone(validar_export(d,self.r,self.raiz,100,self.prompt,self.model,self.reg))

    @unittest.skipUnless(sys.platform.startswith('linux'),'Inventário /proc do Linux')
    def test_native_probe_timeout_and_interrupt_reap_only_owned_group(self):
        import os,time
        from opencode_v2 import consultar
        def alive(pid):
            try:return Path('/proc',str(pid),'stat').read_text().split(') ')[1].split()[0] not in ('Z','X')
            except FileNotFoundError:return False
        outsider=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],start_new_session=True)
        original_wait=subprocess.Popen.wait
        try:
            for interrupted in (False,True):
                ready=self.raiz/('pid'+str(interrupted))
                script='import subprocess,sys,time,pathlib; p=subprocess.Popen([sys.executable,"-c","import time;time.sleep(60)"]); pathlib.Path(sys.argv[1]).write_text(str(p.pid));time.sleep(60)'
                called=[]
                def wait(proc,*a,**kw):
                    if interrupted and not called:
                        called.append(proc)
                        for _ in range(200):
                            if ready.exists():break
                            time.sleep(.01)
                        raise KeyboardInterrupt()
                    return original_wait(proc,*a,**kw)
                with patch.object(subprocess.Popen,'wait',wait):
                    with self.assertRaises(KeyboardInterrupt if interrupted else subprocess.TimeoutExpired):
                        consultar([sys.executable,'-c',script,str(ready)],self.raiz,os.environ.copy(),.2,1024)
                self.assertTrue(ready.exists());self.assertFalse(alive(int(ready.read_text())))
                self.assertIsNone(outsider.poll())
        finally:
            outsider.terminate();outsider.wait(timeout=5)

    def test_consumption_preserves_verified_export_provenance(self):
        import sqlite3
        from consumo_providers import Coletor
        path=self.raiz/'consumption.db'
        c=Coletor(path,'opencode',self.raiz,'Dev',self.model)
        proof=self.validate();c.consumir(proof);c.consumir(proof)
        with sqlite3.connect(path) as db:
            self.assertEqual(db.execute('select fonte,count(*) from consumo').fetchone(),
                             ('opencode.v2.session.export',1))

    def test_launcher_selects_private_v2_and_never_confirms_failed_process(self):
        import io
        from types import SimpleNamespace
        from console_provider import executar
        from providers_console import PROVIDERS
        for v2, code in ((True,0),(True,1),(False,0)):
            proc=SimpleNamespace(stdout=io.StringIO(''.join(json.dumps(x)+'\n' for x in self.reg)),
                stdin=io.StringIO(),wait=lambda:code)
            fim=self.validate()
            with patch('opencode_v2.versao',return_value=v2), patch('opencode_v2.confirmar',return_value=fim) as proof, \
                 patch('console_provider.subprocess.Popen',return_value=proc) as launch, \
                 patch('console_provider.contexto',return_value='rules'), patch('emit_evento.gravar'), \
                 patch('sys.stdout',new_callable=io.StringIO), patch('sys.stderr',new_callable=io.StringIO):
                result=executar(PROVIDERS['opencode'],'opencode',self.raiz,'Dev',self.prompt,
                               modelo=self.model,banco=self.raiz/'events.db')
            self.assertEqual('--standalone' in launch.call_args.args[0],v2)
            self.assertEqual(launch.call_args.kwargs['start_new_session'],v2)
            self.assertEqual(proof.called,v2 and code==0)
            self.assertEqual(result,0 if v2 and code==0 else 1)

if __name__=='__main__':unittest.main()
