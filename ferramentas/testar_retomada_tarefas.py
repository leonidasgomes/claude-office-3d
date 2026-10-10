"""Retomada explícita: Git/SQLite/processo reais, consoles e GitHub sintéticos."""
from pathlib import Path
from contextlib import closing,redirect_stdout
import io,json,sqlite3,sys,unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import gestao_cli as gc
import console_provider
from controle_tarefas import Controle,ocupar_worktree
from providers_console import PROVIDERS
import testar_diretor_lotes as fixtures

class Retomada(unittest.TestCase):
    console="codex"
    def setUp(self):
        self.f=fixtures.Lotes();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.projeto=self.f.raiz;self.trabalho=self.f.work/'42'
        self.cfg=json.loads((self.projeto/'.office/projeto.json').read_text())
        self.cfg['revisao']['ativo']=False
        self.cfg['equipes'][0]['executor']['console']=self.console
        pc=patch.object(gc,'selecionar',return_value=(PROVIDERS[self.console],'native'));pc.start();self.addCleanup(pc.stop)
        (self.projeto/'.office/projeto.json').write_text(json.dumps(self.cfg),encoding='utf-8')
        self.db=gc.pasta_dados(self.projeto)/'tarefas.db'
        self.calls=[];self.cwds=[]
        self.fake=self.f.work/'console.py'
        if self.console=='codex':
            eventos=[{'type':'thread.started','thread_id':'sessao-42'},{'type':'turn.started'},{'type':'turn.completed'}]
        elif self.console=='gemini':
            eventos=[{'type':'init','session_id':'sessao-42','model':'fixture'},{'type':'result','status':'success'}]
        elif self.console=='opencode':
            eventos=[{'type':tipo,'sessionID':'sessao-42','part':{'type':parte,'sessionID':'sessao-42',
                'messageID':'mensagem','id':tipo,**({'reason':'stop'} if tipo=='step_finish' else {})}}
                for tipo,parte in [('step_start','step-start'),('step_finish','step-finish')]]
        else:
            eventos=[{'type':'system','subtype':'init'},{'type':'result','subtype':'success','is_error':False}]
        if self.console=='codex':eventos[-1]['usage']={'input_tokens':10,'output_tokens':2}
        elif self.console=='gemini':eventos[-1]['stats']={'input_tokens':10,'output_tokens':2,'total_tokens':12}
        elif self.console=='opencode':eventos[-1]['part']['tokens']={'input':10,'output':2,'reasoning':0,'cache':{'read':0,'write':0}}
        else:eventos[-1]['modelUsage']={'fixture':{'inputTokens':10,'cacheReadInputTokens':0,'cacheCreationInputTokens':0,'outputTokens':2}}
        script='import json,sys,os\n'
        script+='sys.stdin.read()\n'
        if self.console=='claude':
            script+='s=sys.argv[sys.argv.index("--resume")+1] if "--resume" in sys.argv else os.environ["OFFICE_CLAUDE_STREAM_SESSION"]\n'
            script+='eventos='+repr(eventos)+'\nfor e in eventos:e["session_id"]=s\n'
        else:script+='eventos='+repr(eventos)+'\n'
        script+='for e in eventos:print(json.dumps(e),flush=True)\n'
        self.fake.write_text(script,encoding='utf-8')
        self.native=patch('providers_console.comando_nativo',return_value=[sys.executable,str(self.fake)])
        self.native.start();self.addCleanup(self.native.stop)
        api=self.f.k.chamar
        self.f.k.chamar=lambda caminho,metodo='GET',dados=None: [] if '/pulls?' in caminho else api(caminho,metodo,dados)
        with redirect_stdout(io.StringIO()):
            self.inicial=gc.despachar(self.projeto,42,'Dev','implementacao',self.trabalho,kanban=self.f.k,rodar=self.rodar)
        self.assertEqual(self.inicial['estado'],'bloqueado')

    def rodar(self,*args,**kwargs):
        self.calls.append(kwargs.get('sessao'))
        nativo=console_provider.subprocess.Popen
        def iniciar(*a,**kw):
            self.cwds.append(Path(kw['cwd']).resolve())
            return nativo(*a,**kw)
        with patch.object(console_provider.subprocess,'Popen',side_effect=iniciar):
            return console_provider.executar(*args,**kwargs,banco=self.f.work/'feed.db')

    def previa(self):return gc.preparar_retomada(self.projeto,42,self.trabalho,kanban=self.f.k)[0]
    def test_consumo_despachado_pertence_ao_projeto_e_cwd_ao_worktree(self):
        from consumo_providers import Registro,identidade_projeto
        from gestao_painel import resumo
        banco=self.f.work/'consumo_providers.db'
        dados=resumo([self.projeto],banco_consumo=banco)['projetos'][0]['consumo']
        tarefa=resumo([self.projeto],banco_consumo=banco)['projetos'][0]['tarefas'][0]
        self.assertGreaterEqual(tarefa['atividade']['eventos']['total'],1)
        self.assertEqual(sum(g['total'] for g in tarefa['ultima_execucao']['consumo']['grupos']),12)
        self.assertEqual(sum(g['total'] for g in dados['grupos']),12)
        self.assertEqual(Registro(banco).resumo(projeto_hash=identidade_projeto(self.trabalho))['grupos'],[])
        self.assertEqual(self.cwds,[self.trabalho.resolve()])
        self.assertEqual(self.inicial['estado'],'bloqueado')
        self.retomar()
        depois=resumo([self.projeto],banco_consumo=banco)['projetos'][0]['consumo']
        esperado=24 if self.console in ('codex','gemini') else 12
        self.assertEqual(sum(g['total'] for g in depois['grupos']),esperado)
        p=resumo([self.projeto],banco_consumo=banco)['projetos'][0]
        self.assertEqual(p['desempenho']['grupos'][0]['tentativas_com_consumo'],2 if self.console in ('codex','gemini') else 1)
        g=p['desempenho']['grupos'][0]
        self.assertEqual((g['despachos'],g['retomadas'],g['resultados']['sem_entrega']),(1,1,2))
        with closing(sqlite3.connect(self.db)) as db:
            for (ident,) in db.execute('SELECT id FROM execucao_tarefa'):
                self.assertNotIn(ident,json.dumps(p))
        self.assertEqual(self.cwds,[self.trabalho.resolve()]*2)
        self.assertEqual(Registro(banco).resumo(projeto_hash=identidade_projeto(self.trabalho))['grupos'],[])
    def retomar(self,hash=None):
        with redirect_stdout(io.StringIO()):return gc.retomar(self.projeto,42,self.trabalho,hash or self.previa()['confirmacao'],kanban=self.f.k,rodar=self.rodar,agentes_conciliados=True)

    def test_mesma_reserva_sessao_nova_tentativa_sem_mover_kanban(self):
        antes=len([c for c in self.f.fixture.chamadas if c[1]=='PATCH'])
        preview=self.previa();self.assertTrue(preview['apenas_previa']);self.assertEqual(len(self.calls),1)
        r=self.retomar(preview['confirmacao'])
        self.assertEqual((r['token'],r['estado']),(self.inicial['token'],'bloqueado'))
        self.assertEqual(self.calls,[None,Controle(self.db).listar(self.cfg['kanban']['repo'])[0]['sessao']])
        with closing(sqlite3.connect(gc.banco_worktrees(self.trabalho))) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM worktree_ocupado').fetchone()[0],0)
        self.assertEqual(len([c for c in self.f.fixture.chamadas if c[1]=='PATCH']),antes)
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM execucao_tarefa WHERE token=?',(r['token'],)).fetchone()[0],2)
        with self.assertRaisesRegex(ValueError,'Prévia mudou'):self.retomar(preview['confirmacao'])
        with closing(sqlite3.connect(gc.banco_worktrees(self.trabalho))) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM worktree_ocupado').fetchone()[0],0)

    def test_cli_previa_e_head_alterado_exigem_nova_confirmacao(self):
        saida=io.StringIO()
        with patch.object(gc,'Kanban',return_value=self.f.k),redirect_stdout(saida):
            codigo=gc.main(['--projeto',str(self.projeto),'retomar','--cartao','42','--worktree',str(self.trabalho)])
        self.assertEqual(codigo,0);preview=json.loads(saida.getvalue())
        self.f.git(self.trabalho,'-c','user.name=Fixture','-c','user.email=fixture@example.com','commit','--allow-empty','-m','checkpoint')
        with self.assertRaisesRegex(ValueError,'Prévia mudou'):self.retomar(preview['confirmacao'])
        self.assertEqual(len(self.calls),1)
        self.assertEqual(self.retomar()['estado'],'bloqueado')

    def test_sem_conciliar_filhos_nao_executa(self):
        with self.assertRaisesRegex(ValueError,'agentes-conciliados'):
            gc.retomar(self.projeto,42,self.trabalho,self.previa()['confirmacao'],kanban=self.f.k,rodar=self.rodar)
        self.assertEqual(len(self.calls),1)

    def test_sem_retorno_ou_atividade_encerrada_nao_retoma(self):
        for coluna,valor in [('fim',None),('codigo',None)]:
            with closing(sqlite3.connect(self.db)) as db,db:
                original=db.execute('SELECT '+coluna+' FROM execucao_tarefa').fetchone()[0]
                db.execute('UPDATE execucao_tarefa SET '+coluna+'=?',(valor,))
            with self.assertRaisesRegex(ValueError,'sem retorno'):self.previa()
            with closing(sqlite3.connect(self.db)) as db,db:db.execute('UPDATE execucao_tarefa SET '+coluna+'=?',(original,))
        with closing(sqlite3.connect(self.db)) as db,db:db.execute("UPDATE atividade_execucao SET estado='interrompido'")
        with self.assertRaisesRegex(ValueError,'encerramento'):self.previa()
        self.assertEqual(len(self.calls),1)

    def test_politica_cartao_worktree_sujos_ou_divergentes_rejeitados(self):
        self.f.corpos[42]='**Aceite:** Outro escopo'
        with self.assertRaises(ValueError):self.previa()
        self.f.corpos[42]='**Aceite:** Testes passam'
        (self.trabalho/'alterado.txt').write_text('alteracao')
        with self.assertRaisesRegex(ValueError,'alterações'):self.previa()
        (self.trabalho/'alterado.txt').unlink()
        with self.assertRaisesRegex(ValueError,'diverge'):
            gc.preparar_retomada(self.projeto,42,self.f.work/'43',kanban=self.f.k)
        self.cfg['ceo']['nome']='Mudou'
        (self.projeto/'.office/projeto.json').write_text(json.dumps(self.cfg),encoding='utf-8')
        with self.assertRaises(ValueError):self.previa()

    def test_trava_antiga_nao_roubada(self):
        preview=self.previa()
        with ocupar_worktree(gc.banco_worktrees(self.trabalho),self.trabalho):
            with self.assertRaisesRegex(ValueError,'ocupado'):self.retomar(preview['confirmacao'])
        self.assertEqual(len(self.calls),1)

    def test_claim_com_reserva_alterada_ou_tentativa_aberta_rejeitado(self):
        preview,_,reserva=gc.preparar_retomada(self.projeto,42,self.trabalho,kanban=self.f.k)
        controle=Controle(self.db);controle.transicao(reserva['token'],'executando')
        with self.assertRaisesRegex(ValueError,'Reserva mudou'):controle.retomar(reserva)
        controle.iniciar_execucao(reserva['token']);controle.transicao(reserva['token'],'bloqueado')
        reserva=controle.listar(self.cfg['kanban']['repo'])[0]
        with self.assertRaisesRegex(ValueError,'sem retorno'):controle.retomar(reserva)

class RetomadaClaude(Retomada):
    console='claude'
    def test_resultado_apenas_do_filho_nao_libera_entrega_da_retomada(self):
        self.fake.write_text('import os,sys,json\nsys.stdin.read()\ns=os.environ["OFFICE_CLAUDE_STREAM_SESSION"]\n'
            'for e in [{"type":"system","subtype":"init","session_id":s},'
            '{"type":"result","subtype":"success","is_error":False,"session_id":s,"parent_tool_use_id":"filho"}]: print(json.dumps(e),flush=True)\n',encoding='utf-8')
        with patch.object(self.f.k,'entrega',side_effect=AssertionError('Não consultar entrega sem resultado principal')),redirect_stdout(io.StringIO()):
            r=self.retomar()
        self.assertEqual((r['codigo'],r['estado']),(1,'bloqueado'))
        self.assertEqual(len(self.calls),2)
        with closing(sqlite3.connect(self.db)) as db:
            medicao=db.execute('SELECT id,codigo FROM execucao_tarefa WHERE token=? ORDER BY inicio DESC,id DESC',(r['token'],)).fetchone()
            self.assertEqual(medicao[1],1)
            self.assertEqual(db.execute('SELECT codigo_console FROM atividade_execucao WHERE execucao=?',(medicao[0],)).fetchone()[0],0)
class RetomadaOpenCode(Retomada):console='opencode'
class RetomadaGemini(Retomada):console='gemini'

if __name__=='__main__':unittest.main()
