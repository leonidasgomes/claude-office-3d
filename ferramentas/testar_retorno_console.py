"""Fluxos nativos sintéticos e processo real, sem modelos, contas ou GitHub."""
from pathlib import Path
import io,json,sys,tempfile,unittest
from contextlib import redirect_stdout
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from retorno_console import Retorno
from console_provider import executar
from providers_console import PROVIDERS


def parte(tipo,mensagem='m1',**extra):
    return {'type':tipo,'sessionID':'ses1','part':{'sessionID':'ses1','messageID':mensagem,
        'type':{'step_start':'step-start','step_finish':'step-finish','tool_use':'tool'}.get(tipo,tipo),**extra}}


class Retornos(unittest.TestCase):
    def fluxos(self):
        return {'claude':[{'type':'system','subtype':'init','session_id':'s1'},
                          {'type':'assistant','session_id':'s1','message':{'content':[]}},
                          {'type':'result','subtype':'success','session_id':'s1','is_error':False}],
                'codex':[{'type':'thread.started','thread_id':'t1'},{'type':'turn.started'},
                         {'type':'item.completed','item':{'type':'agent_message','text':'feito'}},{'type':'turn.completed'}],
                'gemini':[{'type':'init','session_id':'s1','model':'gemini'},
                          {'type':'message','role':'assistant','content':'feito'}, {'type':'result','status':'success'}],
                'opencode':[parte('step_start'),parte('text',text='feito'),parte('step_finish',reason='stop')]}

    def verificar(self,nome,eventos):
        retorno=Retorno(nome)
        for ev in eventos:retorno.consumir(ev)
        return retorno.sucesso()

    def test_conclusao_nativa_e_cobertura_incompleta(self):
        for nome,fluxo in self.fluxos().items():
            with self.subTest(console=nome):
                self.assertTrue(self.verificar(nome,fluxo))
                self.assertFalse(self.verificar(nome,fluxo[:-1]))
                self.assertFalse(self.verificar(nome,fluxo[1:]))
                self.assertFalse(self.verificar(nome,[]))
                self.assertFalse(self.verificar(nome,[{'type':'unknown'}]))
                self.assertTrue(self.verificar(nome,[None,{'type':'unknown'},*fluxo]))

    def test_erro_antes_e_apos_conclusao_nao_vira_sucesso(self):
        for nome,fluxo in self.fluxos().items():
            for erro in ({'type':'error'},*([{'type':'turn.failed'}] if nome=='codex' else [])):
                with self.subTest(console=nome,erro=erro):
                    self.assertFalse(self.verificar(nome,[erro,*fluxo]))
                    self.assertFalse(self.verificar(nome,[*fluxo,erro]))
                    if nome!='claude':self.assertFalse(self.verificar(nome,[*fluxo,fluxo[-1]]))

    def test_claude_resultado_ou_sessao_incompletos_e_filho_nao_concluem(self):
        inicio,_,fim=self.fluxos()['claude']
        for final in ({**fim,'is_error':True},{**fim,'is_error':0},{k:v for k,v in fim.items() if k!='is_error'},
                      {**fim,'subtype':'error_max_turns'},{**fim,'session_id':'outra'},
                      {**fim,'parent_tool_use_id':'filho'}):
            self.assertFalse(self.verificar('claude',[inicio,final]))
        self.assertFalse(self.verificar('claude',[fim]))
        self.assertFalse(self.verificar('claude',[{**inicio,'session_id':''},fim]))
        filho={**fim,'parent_tool_use_id':'filho','session_id':'outra','is_error':True}
        self.assertTrue(self.verificar('claude',[inicio,filho,fim]))

    def test_claude_turno_background_exige_novo_resultado(self):
        inicio,turno,fim=self.fluxos()['claude']
        self.assertTrue(self.verificar('claude',[inicio,fim,{'type':'system','subtype':'status','session_id':'s1'}]))
        self.assertFalse(self.verificar('claude',[inicio,fim,turno]))
        self.assertTrue(self.verificar('claude',[inicio,fim,turno,fim]))
        self.assertFalse(self.verificar('claude',[inicio,{**fim,'is_error':True},turno,fim]))
        self.assertFalse(self.verificar('claude',[inicio,{**inicio,'session_id':'outra'},fim]))

    def test_opencode_multiplas_etapas_e_falha_de_ferramenta_recuperavel(self):
        fluxo=[parte('step_start'),parte('tool_use',state={'status':'error'}),
               parte('step_finish',reason='tool-calls'),parte('step_start','m2'),
               parte('tool_use','m2',state={'status':'completed'}),parte('text','m2',text='feito'),
               parte('step_finish','m2',reason='stop')]
        self.assertTrue(self.verificar('opencode',fluxo))
        self.assertFalse(self.verificar('opencode',fluxo[:3]))
        self.assertFalse(self.verificar('opencode',[parte('step_start'),parte('step_finish',reason='length')]))
        self.assertFalse(self.verificar('opencode',[parte('step_start'),parte('step_finish','outra',reason='stop')]))
        self.assertFalse(self.verificar('opencode',[parte('step_start'),{**parte('step_finish',reason='stop'),'sessionID':'outra'}]))
        self.assertFalse(self.verificar('opencode',[parte('step_start'),parte('step_start'),parte('step_finish',reason='stop')]))

    def test_gemini_status_erro_e_identidades(self):
        inicio=self.fluxos()['gemini'][0]
        for final in ({'type':'result','status':'error'},{'type':'result','status':'success','error':{}},
                      {'type':'result','status':'success','session_id':'outra'}):
            self.assertFalse(self.verificar('gemini',[inicio,final]))
        self.assertFalse(self.verificar('gemini',[{**inicio,'model':None},{'type':'result','status':'success'}]))

    def test_codex_turno_e_sessao(self):
        inicio=self.fluxos()['codex'][0]
        self.assertFalse(self.verificar('codex',[inicio,{'type':'turn.completed'}]))
        self.assertFalse(self.verificar('codex',[inicio,{'type':'thread.started','thread_id':'outro'},
                                               {'type':'turn.started'},{'type':'turn.completed'}]))

    def test_processo_real_saida_zero_erro_ou_sem_fim_bloqueados(self):
        for nome,fluxo in self.fluxos().items():
            for eventos,codigo_nativo,esperado in ((fluxo,0,0),(fluxo[:-1],0,1),
                                                  ([*fluxo,{'type':'error'}],0,1),(fluxo[:-1],7,7)):
                with self.subTest(console=nome,esperado=esperado),tempfile.TemporaryDirectory() as tmp:
                    raiz=Path(tmp);fake=raiz/'fake.py'
                    fake.write_text('import json\nfor ev in '+repr(eventos)+': print(json.dumps(ev))\n'
                                    +'raise SystemExit('+str(codigo_nativo)+')\n',encoding='utf-8')
                    with patch.object(type(PROVIDERS[nome]),'comando',return_value=[sys.executable,str(fake),'prompt']),redirect_stdout(io.StringIO()):
                        self.assertEqual(executar(PROVIDERS[nome],sys.executable,raiz,'Dev',prompt='teste',
                                                banco=raiz/'office.db'),esperado)


if __name__=='__main__':unittest.main()
