"""Concilia somente acompanhamento com evidência final, sem inferência/liberação."""
from contextlib import closing
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import testar_coordenacao as fixture
import coordenacao as c
import coordenacao_execucao as e
import coordenacao_painel as cp
from funcionarios import id_projeto
from politica_painel import snapshot

class Conciliacao(unittest.TestCase):
    def setUp(self):
        self.f=fixture.Coordenacao();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.p=self.f.f.raiz;self.id='a'*32;self.pc={'permissao':'pc'}
        self.d={'projeto_id':id_projeto(self.p),'versao':snapshot(self.p)[1],'pedido_id':self.id,'acao':'previa'}
    def gravar(self,recibo,tipo='consulta'):
        with closing(cp.abrir(self.p,True)) as db,db:
            db.execute('INSERT INTO pedido VALUES (?,?,?,?,?)',(self.id,'owner/jogo','incerto',1,recibo))
            if tipo:db.execute('INSERT INTO pedido_contexto VALUES (?,?,NULL)',(self.id,tipo))
    def previa(self):return cp.api_conciliar([self.p],self.d,self.pc)
    def aplicar(self,sha):return cp.api_conciliar([self.p],{**self.d,'acao':'aplicar','evidencia_sha256':sha},self.pc)
    def test_consulta_concluida_previa_nao_muta_aplicacao_nao_reexecuta(self):
        r=self.f.rodar(consultar=True);self.gravar(r['recibo_id'])
        with patch('revisores_console.chamar',side_effect=AssertionError('Inferência indevida')):
            codigo,previa=self.previa();self.assertEqual(codigo,200)
            self.assertEqual(cp.resumo(self.p,'owner/jogo')['itens'][0]['estado'],'incerto')
            self.assertEqual(self.aplicar('0'*64)[0],409)
            with closing(cp.abrir(self.p,True)) as db,db:db.execute('UPDATE pedido SET atualizado=2 WHERE id=?',(self.id,))
            self.assertEqual(self.aplicar(previa['evidencia_sha256'])[0],409)
            _,previa=self.previa()
            self.assertEqual(self.aplicar(previa['evidencia_sha256'])[0],200)
        self.assertEqual(cp.resumo(self.p,'owner/jogo')['itens'][0]['estado'],'conciliada')
        self.assertEqual(e.recibo(self.p,r['recibo_id'])['estado'],'organizado')
        self.assertEqual(self.f.f.modelos,[]);self.assertEqual(self.previa()[0],409)
        self.assertNotIn('worktree',json.dumps(previa));self.assertNotIn('motivo',json.dumps(previa))
    def test_execucao_exige_lote_final_sem_pendencias(self):
        r=self.f.rodar(executar=True);self.gravar(r['recibo_id'],'execucao')
        p=Path(r['lote']['relatorio']);modelo=json.loads(p.read_text(encoding='utf-8'))
        import os
        os.utime(p,(1,1))
        for n in range(11):
            outro={**modelo,'id':f'{n:032x}'}
            (p.parent/(outro['id']+'.json')).write_text(json.dumps(outro),encoding='utf-8')
        codigo,previa=self.previa();self.assertEqual(codigo,200)
        d=json.loads(p.read_text(encoding='utf-8'))
        d['cartao_em_execucao']=43;p.write_text(json.dumps(d),encoding='utf-8')
        self.assertEqual(self.aplicar(previa['evidencia_sha256'])[0],409)
        self.assertEqual(cp.resumo(self.p,'owner/jogo')['itens'][0]['estado'],'incerto')
        self.assertEqual(self.f.f.modelos,[43])
    def test_execucao_organizada_nao_e_final_e_legado_sem_tipo_bloqueia(self):
        r=self.f.rodar(consultar=True);self.gravar(r['recibo_id'],'execucao')
        self.assertEqual(self.previa()[0],409)
        with closing(cp.abrir(self.p,True)) as db,db:db.execute('DELETE FROM pedido_contexto')
        self.assertEqual(self.previa()[0],409)
    def test_worker_vivo_impede_conciliacao(self):
        r=self.f.rodar(consultar=True);self.gravar(r['recibo_id'])
        liberar=threading.Event();t=threading.Thread(target=lambda:liberar.wait(5));t.start()
        with cp._lock:cp._ativos[self.id]=t
        try:self.assertEqual(self.previa()[0],409)
        finally:
            liberar.set();t.join(5)
            with cp._lock:cp._ativos.pop(self.id,None)
    def test_pedido_preserva_vinculo_antes_de_inferencia_que_falha(self):
        self.gravar(None)
        def chamar(*args):
            pedido=cp.resumo(self.p,'owner/jogo')['itens'][0]
            self.assertIsNotNone(pedido['recibo_id'])
            raise ValueError('Quota indisponível')
        original=c.coordenar
        def consultar(projeto,plano,solicitacao,**kw):
            return original(projeto,plano,solicitacao,kanban=self.f.f.k,chamar=chamar,**kw)
        with patch.object(c,'coordenar',side_effect=consultar):
            cp.trabalhar(self.p,self.id,self.d['versao'],self.f.f.plano,'Objetivo')
        pedido=cp.resumo(self.p,'owner/jogo')['itens'][0]
        self.assertEqual(pedido['estado'],'incerto');self.assertIsNotNone(pedido['recibo_id'])
        self.assertEqual(self.previa()[0],409)
    def test_schema_permissao_e_versao(self):
        self.assertEqual(cp.api_conciliar([self.p],self.d,{'permissao':'ver'})[0],403)
        self.assertEqual(cp.api_conciliar([self.p],{**self.d,'liberar_reserva':True},self.pc)[0],400)
        self.assertEqual(cp.api_conciliar([self.p],{**self.d,'versao':'0'*64},self.pc)[0],409)
    def test_http_csrf_nao_autoriza_confirmacao_externa(self):
        import http.client
        from functools import partial
        from http.server import ThreadingHTTPServer
        import servidor,rede
        anterior=servidor.Handler.rede;servidor.Handler.rede=rede.Rede(self.p.parent,False,False)
        srv=ThreadingHTTPServer(('127.0.0.1',0),partial(servidor.Handler,directory=str(Path(servidor.__file__).parent)))
        th=threading.Thread(target=srv.serve_forever,daemon=True);th.start()
        con=http.client.HTTPConnection('127.0.0.1',srv.server_address[1],timeout=10)
        try:
            with patch.object(servidor,'cfg',return_value={'projetos':[self.p]}),patch.object(cp,'api_conciliar',return_value=(200,{'somente_preparacao':True})) as api:
                host=f'127.0.0.1:{srv.server_address[1]}'
                h={'Host':host,'Content-Type':'application/json','X-Office-Acao':'1','Origin':'https://externa.invalid'}
                con.request('POST','/api/gestao/coordenacao/conciliar',json.dumps(self.d),h)
                r=con.getresponse();r.read();self.assertEqual(r.status,403);api.assert_not_called()
                h['Origin']='http://'+host
                con.request('POST','/api/gestao/coordenacao/conciliar',json.dumps(self.d),h)
                r=con.getresponse();r.read();self.assertEqual(r.status,200);api.assert_called_once()
        finally:
            con.close();srv.shutdown();srv.server_close();th.join(5);servidor.Handler.rede=anterior

if __name__=='__main__':unittest.main()
