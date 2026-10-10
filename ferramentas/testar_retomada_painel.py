"""API/worker de retomada: Git e subprocessos reais, GitHub e modelos sintéticos."""
from contextlib import closing
from pathlib import Path
import http.client,json,sqlite3,sys,threading,time,unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import retomada_painel as painel
import gestao_cli as gc
import testar_retomada_tarefas as fixtures
from funcionarios import id_projeto
from politica_painel import snapshot

class Painel(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.Retomada();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.projeto=self.f.projeto;self.repo=self.f.cfg['kanban']['repo']
        self.dados={'projeto_id':id_projeto(self.projeto),'versao':snapshot(self.projeto)[1],'cartao':42,'acao':'previa'}
        p=patch.object(gc,'Kanban',return_value=self.f.f.k);p.start();self.addCleanup(p.stop)
        real=gc.retomar
        def rodar(*args,**kwargs):
            kwargs.setdefault('rodar',self.f.rodar)
            return real(*args,**kwargs)
        p=patch.object(gc,'retomar',side_effect=rodar);p.start();self.addCleanup(p.stop)
    def api(self,dados=None,permissao='pc'):return painel.api([self.projeto],dados or self.dados,{'permissao':permissao})
    def preparar(self):
        codigo,d=self.api();self.assertEqual(codigo,200)
        return {**self.dados,'acao':'executar','confirmacao':d['confirmacao'],'agentes_conciliados':True}
    def aguardar(self,ident):
        with painel._lock:t=painel._ativos.get(ident)
        if t:t.join(15);self.assertFalse(t.is_alive())
        return painel.resumo(self.projeto,self.repo)['itens'][0]

    def test_previa_nao_inicia_processo_ou_ledger(self):
        codigo,d=self.api();self.assertEqual(codigo,200);self.assertTrue(d['apenas_previa'])
        self.assertEqual(self.f.calls,[None]);self.assertIsNone(painel.abrir(self.projeto))
        self.assertNotIn('sessao',d);self.assertNotIn('worktree',d)

    def test_celular_campos_extras_e_falsa_conciliacao_rejeitados(self):
        self.assertEqual(self.api(permissao='conferir')[0],403)
        for d in ({**self.dados,'worktree':'D:/privado'},{**self.dados,'sessao':'outra'},
                  {**self.dados,'cartao':True},{**self.dados,'cartao':0},
                  {**self.preparar(),'agentes_conciliados':False}):
            self.assertEqual(self.api(d)[0],400)
        self.assertEqual(self.f.calls,[None])

    def test_hash_ou_politica_alterada_nao_iniciam(self):
        d=self.preparar();d['confirmacao']='a'*64
        self.assertEqual(self.api(d)[0],409)
        self.assertEqual(self.api({**self.dados,'versao':'a'*64})[0],409)
        self.assertIsNone(painel.abrir(self.projeto));self.assertEqual(self.f.calls,[None])

    def test_worker_preserva_sessao_e_historico_e_expoe_resultado_seguro(self):
        d=self.preparar();codigo,r=self.api(d);self.assertEqual(codigo,202)
        final=self.aguardar(r['pedido_id'])
        self.assertEqual((final['estado'],final['resultado'],final['codigo']),('concluida','bloqueado',0))
        self.assertEqual(self.f.calls,[None,'sessao-42'])
        with closing(sqlite3.connect(self.f.db)) as db:self.assertEqual(db.execute('SELECT count(*) FROM execucao_tarefa').fetchone()[0],2)
        publico=json.dumps(final)
        self.assertNotIn('sessao-42',publico);self.assertNotIn(str(self.f.trabalho),publico)
        self.assertEqual(self.api(d)[0],409);self.assertEqual(len(self.f.calls),2)

    def test_pedido_ativo_impede_duplicata(self):
        d=self.preparar();entrou=threading.Event();liberar=threading.Event()
        real=gc.retomar
        def aguardar(*args,**kw):
            entrou.set();self.assertTrue(liberar.wait(5));return real(*args,**kw)
        with patch.object(gc,'retomar',side_effect=aguardar):
            codigo,r=self.api(d);self.assertEqual(codigo,202);self.assertTrue(entrou.wait(5))
            try:self.assertEqual(self.api(d)[0],409)
            finally:liberar.set();self.aguardar(r['pedido_id'])
        self.assertEqual(len(self.f.calls),2)

    def test_excecao_worker_nao_vaza_e_permanece_incerta(self):
        d=self.preparar()
        with patch.object(gc,'retomar',side_effect=RuntimeError('SECRETO D:/privado')):
            codigo,r=self.api(d);self.assertEqual(codigo,202);final=self.aguardar(r['pedido_id'])
        self.assertEqual(final['estado'],'incerto');self.assertNotIn('SECRETO',json.dumps(final))
        self.assertEqual(self.api(d)[0],409);self.assertEqual(len(self.f.calls),1)

    def test_reinicio_sem_handle_nao_presume_fim(self):
        d=self.preparar()
        with closing(painel.abrir(self.projeto,True)) as db,db:
            db.execute('INSERT INTO pedido_retomada VALUES (?,?,?,?,?,NULL,NULL)',('a'*32,self.repo,42,'executando',time.time()))
        self.assertEqual(painel.resumo(self.projeto,self.repo)['itens'][0]['estado'],'incerto')
        self.assertEqual(self.api(d)[0],409)
        with closing(painel.abrir(self.projeto)) as db:self.assertEqual(db.execute('SELECT estado FROM pedido_retomada').fetchone()[0],'executando')

    def test_resumo_filtra_repo_limita_e_recusa_dados_inconsistentes(self):
        with closing(painel.abrir(self.projeto,True)) as db,db:
            for n in range(12):db.execute('INSERT INTO pedido_retomada VALUES (?,?,?,?,?,?,?)',(f'{n:032x}',self.repo,n+1,'concluida',100+n,'bloqueado',1))
            db.execute('INSERT INTO pedido_retomada VALUES (?,?,?,?,?,?,?)',('f'*32,'outro/repo',123,'concluida',1000,'revisao',0))
        r=painel.resumo(self.projeto,self.repo);self.assertTrue(r['limitado']);self.assertEqual(len(r['itens']),10)
        self.assertNotIn(123,[i['cartao'] for i in r['itens']])
        with closing(painel.abrir(self.projeto,True)) as db,db:db.execute("UPDATE pedido_retomada SET resultado='SECRETO' WHERE id=?",('0'*31+'b',))
        r=painel.resumo(self.projeto,self.repo);self.assertEqual(r['problemas'],1);self.assertNotIn('SECRETO',json.dumps(r))

    def test_http_retoma_exige_pc_e_csrf(self):
        from functools import partial
        from http.server import ThreadingHTTPServer
        import servidor,rede
        anterior=servidor.Handler.rede;servidor.Handler.rede=rede.Rede(self.projeto.parent,False,False)
        srv=ThreadingHTTPServer(('127.0.0.1',0),partial(servidor.Handler,directory=str(Path(servidor.__file__).parent)))
        th=threading.Thread(target=srv.serve_forever,daemon=True);th.start()
        con=http.client.HTTPConnection('127.0.0.1',srv.server_address[1],timeout=10)
        try:
            for rota,funcao,dados in [('/api/gestao/retomar','api',self.dados),('/api/gestao/retomada/conciliar','api_conciliar',{'projeto_id':self.dados['projeto_id'],'versao':self.dados['versao'],'pedido_id':'a'*32,'acao':'previa'})]:
                with patch.object(servidor,'cfg',return_value={'projetos':[self.projeto]}),patch.object(painel,funcao,return_value=(200,{'apenas_previa':True})) as api:
                    host=f'127.0.0.1:{srv.server_address[1]}'
                    h={'Host':host,'Content-Type':'application/json','X-Office-Acao':'1','Origin':'https://externa.invalid','Connection':'close'}
                    con.request('POST',rota,json.dumps(dados),h);r=con.getresponse();r.read();self.assertEqual(r.status,403);api.assert_not_called()
                    h['Origin']='http://'+host
                    con.request('POST',rota,json.dumps(dados),h);r=con.getresponse();r.read();self.assertEqual(r.status,200);api.assert_called_once()
                    self.assertEqual(api.call_args.args[1],dados);self.assertEqual(api.call_args.args[2]['permissao'],'pc')
        finally:con.close();srv.shutdown();srv.server_close();th.join(5);servidor.Handler.rede=anterior

if __name__=='__main__':unittest.main()
