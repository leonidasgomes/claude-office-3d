"""Processos Python e SQLite reais; nenhum modelo, console nativo ou conta."""
from contextlib import closing
from pathlib import Path
import json,sqlite3,subprocess,sys,tempfile,time,unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from atividade_execucao import Acompanhamento
from controle_tarefas import Controle
from gestao_painel import saude_tarefas
from providers_console import PROVIDERS
from console_provider import executar
import alertas


class Atividade(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.raiz=Path(self.tmp.name);self.c=Controle(self.raiz/'tarefas.db')
        self.token=self.c.reservar('owner/a','42','Dev','codex',{'objetivo':'teste','aceite':'ok'},True)
        self.c.transicao(self.token,'executando');self.ident=self.c.iniciar_execucao(self.token)
    def ler(self):
        with closing(sqlite3.connect(self.c.banco)) as db:
            return saude_tarefas(db,'owner/a')
    def test_processo_real_sinais_periodicos_e_encerramento(self):
        with Acompanhamento(self.c.banco,self.ident,intervalo=.02) as a:
            p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(.2)'])
            try:
                a.vincular(p);inicial=self.ler()['atividades']['42']['ultimo_sinal']
                limite=time.monotonic()+2
                while self.ler()['atividades']['42']['ultimo_sinal']<=inicial and time.monotonic()<limite:time.sleep(.01)
                item=self.ler()['atividades']['42']
                self.assertGreater(item['ultimo_sinal'],inicial)
                self.assertTrue(item['console_observado']);self.assertIsNone(item['codigo_console'])
                p.wait(timeout=3)
            finally:
                if p.poll() is None:p.kill();p.wait()
        item=self.ler()['atividades']['42']
        self.assertEqual((item['estado'],item['codigo_console']),('encerrado',0))
        self.assertNotIn(self.token,json.dumps(self.ler()))
        self.assertNotIn('pid',json.dumps(self.ler()))
    def test_interrupcao_preserva_reserva_e_medicao(self):
        with self.assertRaisesRegex(ValueError,'teste'):
            with Acompanhamento(self.c.banco,self.ident) as a:raise ValueError('teste')
        self.assertEqual(self.ler()['atividades']['42']['estado'],'interrompido')
        self.assertEqual(self.c.listar('owner/a')[0]['estado'],'executando')
        self.assertIn('sem_retorno',self.ler()['pendencias'][0]['sinais'])
    def test_nao_reocupa_tentativa_nem_acompanha_encerrada(self):
        with Acompanhamento(self.c.banco,self.ident):pass
        with self.assertRaises(sqlite3.IntegrityError):
            with Acompanhamento(self.c.banco,self.ident):pass
        self.c.terminar_execucao(self.ident,0,.1)
        with self.assertRaises(ValueError):
            with Acompanhamento(self.c.banco,self.ident):pass
    def test_falha_persistencia_bloqueia_retorno_normal(self):
        with self.assertRaises(RuntimeError):
            with Acompanhamento(self.c.banco,self.ident) as a:
                with closing(sqlite3.connect(self.c.banco)) as db,db:db.execute('DELETE FROM atividade_execucao')
        self.assertIn('sem_retorno',self.ler()['pendencias'][0]['sinais'])
    def test_alerta_nao_confunde_processo_observado_com_atraso(self):
        est={};alertas._detectar_tarefas(est,{'pendencias':[]},10000,[])
        t={'registro':'a'*32,'cartao':'42','inicio':1,'sinais':['sem_retorno'],
           'atividade':{'estado':'acompanhando','ultimo_sinal':10000,'console_observado':True,'codigo_console':None}}
        novos=[];alertas._detectar_tarefas(est,{'pendencias':[t]},10000,novos);self.assertEqual(novos,[])
        alertas._detectar_tarefas(est,{'pendencias':[t]},10061,novos);self.assertEqual(len(novos),1)
        self.assertNotIn('morto',novos[0]['corpo'])
    def test_callback_recebe_processo_lancado_nos_quatro_adapters(self):
        for nome in ('claude','codex','gemini','opencode'):
            with self.subTest(console=nome):
                recebidos=[]
                def observar(p):
                    recebidos.append(p);self.assertIsNone(p.poll());self.assertGreater(p.pid,0)
                with patch.object(type(PROVIDERS[nome]),'comando',return_value=[sys.executable,'-c',
                        "import time; time.sleep(.15); print('{}')",'placeholder']),patch('console_provider.contexto',return_value='Regras'):
                    codigo=executar(PROVIDERS[nome],'ignorado',self.raiz,'Dev',prompt='teste',
                        banco=self.raiz/'eventos.db',ao_processo=observar)
                self.assertEqual(codigo,1);self.assertEqual(len(recebidos),1)
                self.assertEqual(recebidos[0].returncode,0)

    def test_eventos_por_tentativa_sem_corpos_e_sem_reocupar(self):
        with Acompanhamento(self.c.banco,self.ident) as a:
            a.evento({'tipo':'fala','texto':'SEGREDO','sessao':'privada'})
            a.evento({'tipo':'trabalho','sessao_pai':'pai-privado','detalhe':'COMANDO'})
            a.evento({'tipo':'desconhecido'})
            a.registrar('acompanhando')
            e=self.ler()['atividades']['42']['eventos']
            self.assertEqual((e['total'],e['eventos_filhos'],e['ultimo_tipo']),(2,1,'trabalho'))
            with closing(sqlite3.connect(self.c.banco)) as db:
                texto=json.dumps(db.execute('SELECT * FROM atividade_eventos').fetchall())
            for segredo in ('SEGREDO','privada','pai-privado','COMANDO'):self.assertNotIn(segredo,texto)
        a.evento({'tipo':'fala'})
        self.assertEqual(self.ler()['atividades']['42']['eventos']['total'],2)
        self.assertIsNotNone(a.erro)
        self.c.terminar_execucao(self.ident,0,.1)
        nova=self.c.iniciar_execucao(self.token)
        with Acompanhamento(self.c.banco,nova):
            self.assertNotIn('eventos',self.ler()['atividades']['42'])

    def test_eventos_concorrentes_e_sinais_nao_regridem_contador(self):
        from concurrent.futures import ThreadPoolExecutor
        with Acompanhamento(self.c.banco,self.ident,intervalo=.01) as a:
            def receber(n):
                a.evento({'tipo':'fala',**({'sessao_pai':'privado'} if n%2 else {})})
                if n%10==0:a.registrar('acompanhando')
            with ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(receber,range(200)))
            a.registrar('acompanhando')
            self.assertEqual(self.ler()['atividades']['42']['eventos']['total'],200)
        e=self.ler()['atividades']['42']['eventos']
        self.assertEqual((e['total'],e['eventos_filhos']),(200,100))

    def test_falha_eventos_nao_interrompe_tarefa_mas_impede_entrega_normal(self):
        with self.assertRaises(RuntimeError):
            with Acompanhamento(self.c.banco,self.ident) as a:
                with closing(sqlite3.connect(self.c.banco)) as db,db:db.execute('DROP TABLE atividade_eventos')
                a.evento({'tipo':'fala'})
                self.assertIsNone(a.erro)
        self.assertEqual(self.c.listar('owner/a')[0]['estado'],'executando')

    def test_streams_reais_excluem_eventos_sinteticos_nos_quatro_adapters(self):
        from contextlib import redirect_stdout
        import io
        eventos={
            'codex':[{'type':'thread.started','thread_id':'s'},{'type':'turn.started'},
                {'type':'item.completed','item':{'id':'m','type':'agent_message','text':'SEGREDO'}},
                {'type':'turn.completed'}],
            'gemini':[{'type':'init','session_id':'s','model':'fixture'},
                {'type':'message','role':'assistant','content':'SEGREDO'},
                {'type':'result','status':'success'}],
            'opencode':[{'type':'step_start','sessionID':'s','part':{'type':'step-start','sessionID':'s','messageID':'m'}},
                {'type':'text','sessionID':'s','part':{'type':'text','sessionID':'s','messageID':'m','text':'SEGREDO'}},
                {'type':'step_finish','sessionID':'s','part':{'type':'step-finish','sessionID':'s','messageID':'m','reason':'stop'}}],
            'claude':[{'type':'system','subtype':'init'},
                {'type':'assistant','message':{'id':'m','content':[{'type':'text','text':'SEGREDO'}]}},
                {'type':'result','subtype':'success','is_error':False}]}
        for nome,itens in eventos.items():
            with self.subTest(console=nome):
                ident=self.ident if nome=='codex' else self.c.iniciar_execucao(self.token)
                fake=self.raiz/'native.py'
                fake.write_text('import sys,os,json\nsys.stdin.read()\neventos='+repr(itens)+'\n'+
                    ('for e in eventos:e["session_id"]=os.environ["OFFICE_CLAUDE_STREAM_SESSION"]\n' if nome=='claude' else '')+
                    'for e in eventos:print(json.dumps(e),flush=True)\n',encoding='utf-8')
                with Acompanhamento(self.c.banco,ident) as a,patch('providers_console.comando_nativo',return_value=[sys.executable,str(fake)]),patch('console_provider.contexto',return_value='Regras'),patch('emit_evento.gravar',side_effect=OSError('feed indisponível')),redirect_stdout(io.StringIO()):
                    codigo=executar(PROVIDERS[nome],'native',self.raiz,'Dev',prompt='Teste',banco=self.raiz/'feed.db',ao_processo=a.vincular,ao_evento=a.evento)
                self.assertEqual(codigo,0)
                e=self.ler()['atividades']['42']['eventos']
                self.assertEqual((e['total'],e['eventos_filhos'],e['ultimo_tipo']),(2,0,'ocioso'))
                self.assertNotIn('SEGREDO',json.dumps(self.ler()))
                self.c.terminar_execucao(ident,codigo,.1)

    def test_falha_vinculo_encerra_processo_lancado(self):
        recebidos=[]
        def falhar(p):recebidos.append(p);raise ValueError('persistencia falhou')
        try:
            with patch.object(type(PROVIDERS['claude']),'comando',return_value=[sys.executable,'-c',
                    'import time; time.sleep(30)']),patch('console_provider.contexto',return_value='Regras'):
                with self.assertRaisesRegex(ValueError,'persistencia falhou'):
                    executar(PROVIDERS['claude'],'ignorado',self.raiz,'Dev',prompt='teste',
                        banco=self.raiz/'eventos.db',ao_processo=falhar)
            self.assertEqual(len(recebidos),1);self.assertIsNotNone(recebidos[0].poll())
        finally:
            for p in recebidos:
                if p.poll() is None:p.kill();p.wait()


if __name__=='__main__':unittest.main()
