"""Despacho da seleção persistida, com worktrees Git e Kanban simulado."""
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import testar_coordenacao as fixture
import coordenacao_execucao as e
import coordenacao_painel as painel
from funcionarios import id_projeto
from politica_painel import snapshot

class Execucao(unittest.TestCase):
    def setUp(self):
        self.f=fixture.Coordenacao();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.projeto=self.f.f.raiz
        self.r=self.f.rodar(consultar=True)
        self.id=self.r['recibo_id'];self.soma=e.recibo(self.projeto,self.id)['plano_sha256']
        self.versao=snapshot(self.projeto)[1]
        self.dados={'projeto_id':id_projeto(self.projeto),'versao':self.versao,'recibo_id':self.id,'plano_sha256':self.soma}
    def executar(self):
        return e.executar(self.projeto,self.id,self.soma,self.versao,self.f.f.k,self.f.f.despacho)
    def test_selecao_unica_sem_reconsultar_cloud(self):
        with patch('revisores_console.chamar',side_effect=AssertionError('Nova consulta indevida')):
            r=self.executar()
        self.assertEqual(r['estado'],'processado');self.assertEqual(self.f.f.modelos,[43])
        self.assertEqual(e.recibo(self.projeto,self.id)['lote_id'],r['id'])
        with self.assertRaises(ValueError):self.executar()
        self.assertEqual(self.f.f.modelos,[43])
    def test_aceite_alterado_nao_reserva(self):
        self.f.f.corpos[43]='**Aceite:** Outro escopo'
        with self.assertRaises(ValueError):self.executar()
        self.assertEqual(self.f.f.modelos,[]);self.assertEqual(e.recibo(self.projeto,self.id)['estado'],'organizado')
    def test_hash_e_conteudo_adulterados(self):
        with self.assertRaises(ValueError):e.preparar(self.projeto,self.id,'0'*64,self.versao,self.f.f.k)
        p=e.caminho(self.projeto,self.id);p.write_bytes(p.read_bytes()+b' ')
        with self.assertRaisesRegex(ValueError,'mudou'):self.executar()
        self.assertEqual(self.f.f.modelos,[])
    def test_politica_alterada(self):
        p=self.projeto/'.office/projeto.json';p.write_bytes(p.read_bytes()+b' ')
        with self.assertRaisesRegex(ValueError,'Política'):self.executar()
        self.assertEqual(self.f.f.modelos,[])
    def test_plano_antes_do_bloco_opcional_preserva_semantica(self):
        import hashlib
        from contextlib import closing
        from coordenacao_registro import Registro
        p=e.caminho(self.projeto,self.id);d=json.loads(p.read_text(encoding='utf-8'))
        d['preparado']['politica'].pop('sugestoes')
        bruto=json.dumps(d,ensure_ascii=False,sort_keys=True).encode('utf-8');p.write_bytes(bruto)
        soma=hashlib.sha256(bruto).hexdigest()
        # Simula plano/recibo emitidos pela versão anterior, mantendo hash real.
        with closing(Registro(self.projeto).abrir()) as db,db:
            r=e.recibo(self.projeto,self.id);r['plano_sha256']=soma
            db.execute('UPDATE coordenacao SET dados=? WHERE id=?',(json.dumps(r),self.id))
        self.soma=soma
        self.assertEqual(self.executar()['estado'],'processado');self.assertEqual(self.f.f.modelos,[43])
    def test_plano_nao_sobrescrito_e_id_nao_e_caminho(self):
        with self.assertRaises(FileExistsError):e.salvar(self.projeto,self.id,{}, {})
        with self.assertRaises(ValueError):e.caminho(self.projeto,'../fora')
    def test_api_rejeita_novos_caminhos_e_permissao(self):
        self.assertEqual(painel.api_executar([self.projeto],self.dados,{'permissao':'celular'})[0],403)
        self.assertEqual(painel.api_executar([self.projeto],{**self.dados,'worktree':'D:/outro'},{'permissao':'pc'})[0],400)
        self.assertEqual(painel.api_executar([self.projeto],{**self.dados,'versao':'0'*64},{'permissao':'pc'})[0],409)
    def test_worker_assincrono_impede_duplicata(self):
        entrou=threading.Event();liberar=threading.Event()
        def executar(*args):
            entrou.set();self.assertTrue(liberar.wait(5));return {'estado':'processado'}
        with patch('coordenacao_execucao.executar',side_effect=executar):
            codigo,d=painel.api_executar([self.projeto],self.dados,{'permissao':'pc'})
            self.assertEqual(codigo,202);self.assertTrue(entrou.wait(5))
            with painel._lock:t=painel._ativos[d['pedido_id']]
            try:self.assertEqual(painel.api_executar([self.projeto],self.dados,{'permissao':'pc'})[0],409)
            finally:liberar.set();t.join(5)
        self.assertFalse(t.is_alive());self.assertEqual(painel.resumo(self.projeto,'owner/jogo')['itens'][0]['estado'],'concluida')
    def test_http_execucao_exige_csrf(self):
        import http.client
        from functools import partial
        from http.server import ThreadingHTTPServer
        import servidor,rede
        anterior=servidor.Handler.rede
        servidor.Handler.rede=rede.Rede(self.projeto.parent,False,False)
        srv=ThreadingHTTPServer(('127.0.0.1',0),partial(servidor.Handler,directory=str(Path(servidor.__file__).parent)))
        th=threading.Thread(target=srv.serve_forever,daemon=True);th.start()
        con=http.client.HTTPConnection('127.0.0.1',srv.server_address[1],timeout=10)
        try:
            with patch.object(servidor,'cfg',return_value={'projetos':[self.projeto]}),patch.object(painel,'api_executar',return_value=(202,{'pedido_id':'a'*32})) as api:
                host=f'127.0.0.1:{srv.server_address[1]}'
                h={'Host':host,'Content-Type':'application/json','X-Office-Acao':'1','Origin':'https://externa.invalid'}
                con.request('POST','/api/gestao/coordenacao/executar',json.dumps(self.dados),h)
                r=con.getresponse();r.read();self.assertEqual(r.status,403);api.assert_not_called()
                h['Origin']='http://'+host
                con.request('POST','/api/gestao/coordenacao/executar',json.dumps(self.dados),h)
                r=con.getresponse();r.read();self.assertEqual(r.status,202);api.assert_called_once()
                self.assertEqual(api.call_args.args[1],self.dados)
        finally:
            con.close();srv.shutdown();srv.server_close();th.join(5);servidor.Handler.rede=anterior

if __name__=='__main__':unittest.main()
