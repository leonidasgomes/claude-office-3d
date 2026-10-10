"""Pedido HTTP real, worker com barreira e nenhuma inferência cloud."""
from contextlib import closing
from functools import partial
from http.server import ThreadingHTTPServer
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import coordenacao_painel as cp
import gestao_cli as gc
from funcionarios import id_projeto
from politica_painel import snapshot


class Pedidos(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.p=Path(self.tmp.name)/'projeto';(self.p/'.office').mkdir(parents=True)
        (self.p/'.office/projeto.json').write_text(json.dumps({'ativo':True,'kanban':{'repo':'owner/repo'},'equipes':[]}),encoding='utf-8')
        p=patch.object(gc,'RAIZ',self.p.parent/'app');p.start();self.addCleanup(p.stop)
        self.d={'projeto_id':id_projeto(self.p),'versao':snapshot(self.p)[1],'solicitacao':'Objetivo aprovado',
                'plano':{'cartoes':[{'cartao':42,'worktree':str(self.p.parent/'worktree')}]}}
        self.pc={'permissao':'pc'}

    def test_pc_schema_versao_e_nao_cria_banco_na_leitura(self):
        self.assertEqual(cp.resumo(self.p,'owner/repo')['itens'],[])
        self.assertEqual(cp.api_consultar([self.p],self.d,{'permissao':'ver'})[0],403)
        self.assertEqual(cp.api_consultar([self.p],{**self.d,'executar':True},self.pc)[0],400)
        self.assertEqual(cp.api_consultar([self.p],{**self.d,'versao':'a'*64},self.pc)[0],409)
        self.assertIsNone(cp.abrir(self.p))

    def test_worker_async_nao_despacha_e_pedido_duplicado_bloqueia(self):
        iniciou=threading.Event();soltar=threading.Event();chamadas=[]
        def consulta(*args,**kwargs):
            chamadas.append(kwargs);iniciou.set();self.assertTrue(soltar.wait(5));return {'recibo_id':'a'*32}
        with patch('coordenacao.coordenar',side_effect=consulta):
            codigo,d=cp.api_consultar([self.p],self.d,self.pc)
            self.assertEqual(codigo,202);self.assertTrue(iniciou.wait(5))
            with cp._lock:t=cp._ativos[d['pedido_id']]
            try:
                self.assertTrue(t.is_alive())
                self.assertEqual(cp.api_consultar([self.p],self.d,self.pc)[0],409)
                self.assertEqual(cp.resumo(self.p,'owner/repo')['itens'][0]['estado'],'consultando')
                self.assertEqual(len(chamadas),1)
                self.assertTrue(chamadas[0]['consultar']);self.assertEqual(chamadas[0]['versao_politica'],self.d['versao'])
                self.assertTrue(callable(chamadas[0]['ao_recibo']))
            finally:soltar.set();t.join(5)
        self.assertFalse(t.is_alive())
        r=cp.resumo(self.p,'owner/repo')['itens'][0];self.assertEqual(r['estado'],'concluida');self.assertEqual(r['recibo_id'],'a'*32)
        self.assertNotIn('Objetivo',json.dumps(r));self.assertNotIn('worktree',json.dumps(r))

    def test_pedido_sem_handle_apos_reinicio_exige_conciliacao(self):
        with closing(cp.abrir(self.p,True)) as db,db:
            db.execute('INSERT INTO pedido VALUES (?,?,?,?,NULL)',('b'*32,'owner/repo','consultando',1))
        self.assertEqual(cp.resumo(self.p,'owner/repo')['itens'][0]['estado'],'incerto')
        with patch('coordenacao.coordenar') as chamada:
            self.assertEqual(cp.api_consultar([self.p],self.d,self.pc)[0],409);chamada.assert_not_called()

    def test_http_csrf_e_consulta_com_controlador_real(self):
        import servidor,rede
        anterior=servidor.Handler.rede;servidor.Handler.rede=rede.Rede(self.p.parent,False,False)
        srv=ThreadingHTTPServer(('127.0.0.1',0),partial(servidor.Handler,directory=str(Path(servidor.__file__).parent)))
        th=threading.Thread(target=srv.serve_forever,daemon=True);th.start()
        con=http.client.HTTPConnection('127.0.0.1',srv.server_address[1],timeout=10)
        iniciou=threading.Event();soltar=threading.Event();worker=None
        def consulta(*a,**kw):iniciou.set();soltar.wait(5);return {'recibo_id':'c'*32}
        try:
            with patch.object(servidor,'cfg',return_value={'projetos':[self.p]}),patch('coordenacao.coordenar',side_effect=consulta):
                host=f'127.0.0.1:{srv.server_address[1]}'
                h={'Host':host,'Content-Type':'application/json','X-Office-Acao':'1','Origin':'https://externa.invalid'}
                con.request('POST','/api/gestao/coordenar',json.dumps(self.d),h);r=con.getresponse();r.read();self.assertEqual(r.status,403)
                h['Origin']='http://'+host
                con.request('POST','/api/gestao/coordenar',json.dumps(self.d),h);r=con.getresponse();d=json.loads(r.read());self.assertEqual(r.status,202)
                self.assertTrue(iniciou.wait(5))
                with cp._lock:worker=cp._ativos[d['pedido_id']]
                soltar.set();worker.join(5)
        finally:
            soltar.set()
            if worker:worker.join(5)
            con.close();srv.shutdown();srv.server_close();th.join(5);servidor.Handler.rede=anterior


if __name__=='__main__':unittest.main()
