"""Fonte SQLite real somente leitura, destino separado e cursor transacional."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing,ExitStack
from pathlib import Path
import json,sqlite3,sys,tempfile,time,unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import ponte_eventos as p


class Ponte(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent);self.addCleanup(t.cleanup)
        self.raiz=Path(t.name);self.fonte=self.raiz/'fonte.db';self.destino=self.raiz/'nova';self.destino.mkdir()
        (self.destino/'EDICAO.json').write_text(json.dumps({'edicao':'office-multi-provider','formato':1}),encoding='utf-8')
        with closing(sqlite3.connect(self.fonte)) as c,c:c.execute('CREATE TABLE evento (id INTEGER PRIMARY KEY,dados TEXT)')
    def evento(self,valor=None):
        with closing(sqlite3.connect(self.fonte)) as c,c:
            c.execute('INSERT INTO evento(dados) VALUES (?)',(json.dumps(valor or {'tipo':'trabalho','agente':'Team_Dev','ferramenta':'Bash','resumo':'Teste','ts':'2026-10-10T10:00:00','segredo':'não propagar'}),))
    def sync(self,**kw):return p.sincronizar('claude-legado',self.fonte,self.destino,'claude',**kw)
    def dados(self):
        with closing(sqlite3.connect(self.destino/'dados/escritorio.db')) as c:
            return c.execute('SELECT id,dados FROM evento ORDER BY id').fetchall()
    def test_tail_normalizado_preserva_fonte_e_nao_duplica_reinicio(self):
        for _ in range(5):self.evento()
        antes=self.fonte.read_bytes();r=self.sync(ultimos=2)
        self.assertEqual(r['importados'],2);self.assertEqual(r['cursor'],5)
        self.assertEqual(self.fonte.read_bytes(),antes)
        itens=[json.loads(x[1]) for x in self.dados()]
        self.assertEqual([e['origem_escritorio']['id'] for e in itens],[4,5])
        self.assertEqual({e['fonte'] for e in itens},{'claude'})
        self.assertNotIn('segredo',json.dumps(itens))
        self.assertEqual(self.sync(ultimos=200)['importados'],0)
        self.evento();self.assertEqual(self.sync()['importados'],1)
        self.assertEqual([x[0] for x in self.dados()],[1,2,3])
    def test_inicio_sem_historico_e_lote_limitado(self):
        self.evento();self.assertEqual(self.sync()['importados'],0)
        for _ in range(205):self.evento()
        r=self.sync();self.assertEqual(r['importados'],200);self.assertTrue(r['mais'])
        self.assertEqual(self.sync()['importados'],5);self.assertFalse(self.sync()['mais'])
    def test_concorrencia_mesma_origem_e_erro_nao_avanca_cursor(self):
        self.sync()
        for _ in range(8):self.evento()
        with ThreadPoolExecutor(max_workers=4) as pool:
            resultados=list(pool.map(lambda _:self.sync(),range(4)))
        self.assertEqual(sum(r['importados'] for r in resultados),8);self.assertEqual(len(self.dados()),8)
        self.evento()
        with patch('ponte_eventos.identidade',side_effect=[p.identidade(self.fonte),'arquivo-trocado']):
            with self.assertRaisesRegex(ValueError,'mudou durante'):self.sync()
        self.assertEqual(len(self.dados()),8);self.assertEqual(self.sync()['importados'],1)
    def test_reset_e_mudanca_origem_recusados_sem_apagar_destino(self):
        self.evento();self.sync(ultimos=1);antes=self.dados()
        with self.assertRaises(ValueError):p.sincronizar('claude-legado',self.fonte,self.destino,'codex')
        with closing(sqlite3.connect(self.fonte)) as c,c:c.execute('DELETE FROM evento')
        with self.assertRaisesRegex(ValueError,'reiniciada'):self.sync()
        self.assertEqual(self.dados(),antes)
    def test_evento_invalido_e_fonte_vinculada_uma_vez(self):
        self.evento();self.sync(ultimos=1)
        with closing(sqlite3.connect(self.fonte)) as c,c:
            c.executemany('INSERT INTO evento(dados) VALUES (?)',[('não JSON',),('x'*70000,)])
        self.evento();r=self.sync();self.assertEqual(r['importados'],1);self.assertEqual(r['descartados'],2)
        self.assertEqual(self.sync()['importados'],0)
        with self.assertRaises(sqlite3.IntegrityError):p.sincronizar('outra-origem',self.fonte,self.destino,'claude',1)
        self.assertEqual(len(self.dados()),2)
    def test_marker_fonte_ausente_mesmo_banco_e_cli(self):
        self.assertEqual(p.main(['--origem','claude-legado','--fonte',str(self.fonte),'--destino',str(self.destino),'--provider','claude']),0)
        alvo=self.destino/'dados/escritorio.db'
        with self.assertRaisesRegex(ValueError,'separados'):p.sincronizar('nova',alvo,self.destino,'claude')
        with self.assertRaises(ValueError):p.sincronizar('nova',self.raiz/'ausente.db',self.destino,'claude')
        (self.destino/'EDICAO.json').write_text('{"edicao":"office-multi-provider","formato":true}')
        with self.assertRaises(ValueError):self.sync()
    def test_leitura_wal_inclui_eventos_confirmados_com_writer_aberto(self):
        with closing(sqlite3.connect(self.fonte)) as writer:
            writer.execute('PRAGMA journal_mode=WAL')
            self.evento();self.assertEqual(self.sync(ultimos=1)['importados'],1)
            self.evento();self.assertEqual(self.sync()['importados'],1)
            self.assertEqual(len(self.dados()),2)
    def configurar(self,fontes=None):
        pasta=self.destino/'dados';pasta.mkdir(exist_ok=True)
        dados={'ativo':True,'fontes':fontes or [{'origem':'claude-legado','provider':'claude','fonte':str(self.fonte)}]}
        (pasta/'ponte_eventos.json').write_text(json.dumps(dados),encoding='utf-8')
    def aguardar(self,condicao):
        limite=time.monotonic()+5
        while time.monotonic()<limite:
            if condicao():return
            time.sleep(.02)
        self.fail('Estado esperado não observado')
    def test_autostart_optin_acompanha_evento_futuro_e_para(self):
        desligada=p.Acompanhamento(self.destino).iniciar()
        self.assertIsNone(desligada.thread);self.assertEqual(desligada.estado()['estado'],'desligada')
        self.assertFalse((self.destino/'dados').exists())
        self.configurar();a=p.Acompanhamento(self.destino,.03).iniciar();self.addCleanup(a.parar)
        self.aguardar(lambda:a.estado()['estado']=='acompanhando')
        thread=a.thread;self.assertIs(a.iniciar().thread,thread)
        self.evento();self.aguardar(lambda:a.estado()['fontes'][0]['importados']==1)
        self.assertEqual(len(self.dados()),1)
        self.assertNotIn(str(self.fonte),json.dumps(a.estado()))
        self.assertTrue(a.parar());self.assertEqual(a.estado()['estado'],'encerrada')
    def test_configuracao_alterada_interrompe_sem_adotar_outro_provider(self):
        self.configurar();a=p.Acompanhamento(self.destino,.03).iniciar();self.addCleanup(a.parar)
        self.aguardar(lambda:a.estado()['estado']=='acompanhando')
        self.configurar([{'origem':'claude-legado','provider':'codex','fonte':str(self.fonte)}])
        self.aguardar(lambda:a.estado()['estado']=='configuracao_alterada')
        self.assertEqual(a.estado()['fontes'][0]['estado'],'interrompida')
        self.evento();self.assertEqual(len(self.dados()),0)
    def test_fonte_interrompida_nao_oculta_outro_acompanhamento(self):
        self.configurar([{'origem':'ausente','provider':'claude','fonte':str(self.raiz/'ausente.db')},
          {'origem':'claude-legado','provider':'claude','fonte':str(self.fonte)}])
        a=p.Acompanhamento(self.destino,.03).iniciar();self.addCleanup(a.parar)
        self.aguardar(lambda:a.estado()['estado']=='parcial')
        self.evento();self.aguardar(lambda:a.estado()['fontes'][1]['importados']==1)
        self.assertEqual(a.estado()['fontes'][0]['estado'],'interrompida')
    def test_configuracao_invalida_nao_inicia_thread(self):
        self.configurar([{'origem':'x','fonte':'relativa.db','provider':'claude'}])
        a=p.Acompanhamento(self.destino).iniciar()
        self.assertIsNone(a.thread);self.assertEqual(a.estado()['estado'],'configuracao_invalida')
    def test_ciclo_do_servidor_inicia_ponte_e_para_no_finally(self):
        import servidor,threading,configuracao
        from types import SimpleNamespace
        self.configurar();anterior=p._acompanhamento
        fechado=[]
        def servir():
            self.aguardar(lambda:p.estado()['estado']=='acompanhando')
            self.evento();self.aguardar(lambda:p.estado()['fontes'][0]['importados']==1)
            raise KeyboardInterrupt
        fake=SimpleNamespace(serve_forever=servir,server_close=lambda:fechado.append(True))
        alertas=SimpleNamespace(iniciar=threading.Event,opcoes={'ativo':False},push=SimpleNamespace(disponivel=lambda:(False,'fixture')))
        try:
            with ExitStack() as stack:
                for alvo,valor in [('servidor.PASTA',self.destino),('servidor.cfg',lambda:configuracao.normalizar({'porta':8788})),
                    ('servidor.opcoes_rede',lambda _:(False,False,False)),('servidor.abrir_servidores',lambda *args:(fake,[])),
                    ('servidor.criar_alertas',lambda _:alertas),('servidor.iniciar_sugestoes',threading.Event),
                    ('servidor.VIGIA.iniciar',threading.Event),('servidor.saude_laco',lambda _:None),
                    ('servidor.grafo_painel.laco',lambda *args:None),
                    ('servidor.sugestoes_bot.configuracao',lambda:{'bots':[],'repo':'','revisor':False}),
                    ('kanban_painel.habilitado',lambda _:False),('sys.argv',['servidor.py','--sem-navegador'])]:
                    stack.enter_context(patch(alvo,valor))
                servidor.main()
            self.assertEqual(fechado,[True]);self.assertEqual(p.estado()['estado'],'encerrada')
            self.assertFalse(p._acompanhamento.thread.is_alive());self.assertEqual(len(self.dados()),1)
        finally:
            if p._acompanhamento:p._acompanhamento.parar()
            p._acompanhamento=anterior


if __name__=='__main__':unittest.main()
