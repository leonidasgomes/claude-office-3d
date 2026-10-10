"""Merge opcional por projeto, concorrência e preservação da política comum."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import politica_painel as p
from gestao_projeto import validar
from funcionarios import id_projeto

class MergePainel(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.raiz=Path(self.tmp.name)/'projeto';(self.raiz/'.office').mkdir(parents=True)
        self.cfg=validar({'ativo':True})
        self.arq=self.raiz/'.office/projeto.json';self.arq.write_text(json.dumps(self.cfg),encoding='utf-8')
        self.bruto=self.arq.read_bytes();self.hash=p.snapshot(self.raiz)[1]
        self.merge={'modo':'automatico','checks':['CI','Revisão'],'rotulos_manuais':['merge-manual']}
    def test_modo_manual_padrao_e_isolamento(self):
        outro=Path(self.tmp.name)/'outro';outro.mkdir()
        self.assertEqual(self.cfg['merge']['modo'],'manual')
        resultado=p.atualizar_merge(self.raiz,self.hash,self.merge)
        cfg,versao,_=p.snapshot(self.raiz)
        self.assertEqual(cfg['merge'],self.merge);self.assertEqual(versao,resultado['versao'])
        for k in set(cfg)-{'merge'}:self.assertEqual(cfg[k],self.cfg[k])
        self.assertEqual(p.snapshot(outro)[0]['merge']['modo'],'manual')
        self.assertEqual((self.raiz/'.office/historico-politica'/f'{self.hash}.json').read_bytes(),self.bruto)
        p.atualizar_merge(self.raiz,versao,{**self.merge,'modo':'manual'})
        self.assertEqual(p.snapshot(self.raiz)[0]['merge']['modo'],'manual')
    def test_rejeita_auto_sem_checks_e_campos_indevidos(self):
        for merge in ({**self.merge,'checks':[]},{**self.merge,'modo':'sempre'},
                      {**self.merge,'checks':['CI','CI']},{**self.merge,'checks':[{}]},
                      {**self.merge,'rotulos_manuais':[' ']},{**self.merge,'revisao':False}):
            with self.subTest(merge=merge),self.assertRaises(ValueError):p.atualizar_merge(self.raiz,self.hash,merge)
            self.assertEqual(self.arq.read_bytes(),self.bruto)
        self.assertFalse((self.raiz/'.office/historico-politica').exists())
    def test_concorrencia_e_noop(self):
        self.assertFalse(p.atualizar_merge(self.raiz,self.hash,self.cfg['merge'])['alterado'])
        p.atualizar_merge(self.raiz,self.hash,self.merge)
        with self.assertRaises(p.Conflito):p.atualizar_merge(self.raiz,self.hash,self.cfg['merge'])
        versao=p.snapshot(self.raiz)[1]
        lock=self.raiz/'.office/politica.edicao.lock';lock.write_text('externo')
        with self.assertRaises(p.Conflito):p.atualizar_merge(self.raiz,versao,self.cfg['merge'])
        self.assertEqual(lock.read_text(),'externo')
    def test_limite_utf8_antes_de_gravar(self):
        nomes=[str(i)+'😀'*195 for i in range(100)]
        with self.assertRaises(ValueError):p.atualizar_merge(self.raiz,self.hash,{**self.merge,'checks':nomes,'rotulos_manuais':nomes})
        self.assertEqual(self.arq.read_bytes(),self.bruto)
        self.assertFalse((self.raiz/'.office/historico-politica').exists())
    def test_api_pc_projeto_e_versao(self):
        dados={'projeto_id':id_projeto(self.raiz),'versao':self.hash,'merge':copy.deepcopy(self.merge)}
        self.assertEqual(p.api_merge([self.raiz],dados,{'permissao':'celular'})[0],403)
        self.assertEqual(p.api_merge([],dados,{'permissao':'pc'})[0],400)
        self.assertEqual(p.api_merge([self.raiz],{**dados,'extra':True},{'permissao':'pc'})[0],400)
        self.assertEqual(p.api_merge([self.raiz],dados,{'permissao':'pc'})[0],200)
        self.assertEqual(p.api_merge([self.raiz],dados,{'permissao':'pc'})[0],409)
    def test_http_guarda_origin_e_header(self):
        self.http_guarda('/api/gestao/merge','api_merge','merge',self.merge)

    def test_http_revisao_guarda_origin_e_header(self):
        self.http_guarda('/api/gestao/revisao','api_revisao','revisao',{'ativo':False,'clouds_distintas':2,'separar_autor':True})

    def http_guarda(self,rota,metodo,chave,valor):
        import http.client
        import threading
        from functools import partial
        from http.server import ThreadingHTTPServer
        from unittest.mock import patch
        import servidor,rede
        anterior=servidor.Handler.rede;servidor.Handler.rede=rede.Rede(self.raiz.parent,False,False)
        srv=ThreadingHTTPServer(('127.0.0.1',0),partial(servidor.Handler,directory=str(Path(servidor.__file__).parent)))
        th=threading.Thread(target=srv.serve_forever,daemon=True);th.start()
        con=http.client.HTTPConnection('127.0.0.1',srv.server_address[1],timeout=10)
        dados={'projeto_id':id_projeto(self.raiz),'versao':self.hash,chave:valor}
        try:
            with patch.object(servidor,'cfg',return_value={'projetos':[self.raiz]}),patch.object(p,metodo,return_value=(200,{'alterado':False})) as api:
                host=f'127.0.0.1:{srv.server_address[1]}'
                h={'Host':host,'Content-Type':'application/json','X-Office-Acao':'1','Origin':'https://externa.invalid','Connection':'close'}
                con.request('POST',rota,json.dumps(dados),h);r=con.getresponse();r.read();self.assertEqual(r.status,403);api.assert_not_called()
                h['Origin']='http://'+host;del h['X-Office-Acao']
                con.request('POST',rota,json.dumps(dados),h);r=con.getresponse();r.read();self.assertEqual(r.status,403);api.assert_not_called()
                h['X-Office-Acao']='1'
                con.request('POST',rota,json.dumps(dados),h);r=con.getresponse();r.read();self.assertEqual(r.status,200);api.assert_called_once()
                self.assertEqual(api.call_args.args[1],dados);self.assertEqual(api.call_args.args[2]['permissao'],'pc')
        finally:con.close();srv.shutdown();srv.server_close();th.join(5);servidor.Handler.rede=anterior

if __name__=='__main__':unittest.main()
