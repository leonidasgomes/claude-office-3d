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
