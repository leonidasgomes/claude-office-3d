"""Parser/cache/API com metadados sintéticos; sem inferência ou credenciais."""
from pathlib import Path
import json,sys,unittest
import http.client,tempfile,threading
from functools import partial
from http.server import ThreadingHTTPServer
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import modelos_opencode as m


def bloco(id='free',**alteracoes):
    obj={'id':id,'providerID':'opencode','name':'Modelo <script>',
         'api':{'url':'https://opencode.ai/zen/v1'},'status':'active',
         'cost':{'input':0,'output':0,'cache':{'read':0,'write':0}},
         'capabilities':{'toolcall':True},'headers':{'Authorization':'SEGREDO'},'options':{'apiKey':'SEGREDO'}}
    obj.update(alteracoes)
    return 'opencode/'+id+'\n'+json.dumps(obj)+'\n'


class Modelos(unittest.TestCase):
    def test_zero_todas_dimensoes_sem_segredos_ou_cloud_inventada(self):
        r=m.normalizar(bloco('big-pickle'))
        self.assertEqual(r[0]['id'],'opencode/big-pickle')
        self.assertEqual(r[0]['fornecedor_real'],'não atestado')
        self.assertNotIn('SEGREDO',json.dumps(r));self.assertNotIn('apiKey',json.dumps(r))
    def test_suffix_free_nao_prova_preco(self):
        for custo in ({'input':1,'output':0,'cache':{'read':0,'write':0}},
                      {'input':0,'output':0}, {'input':False,'output':0,'cache':{'read':0,'write':0}},
                      {'input':0,'output':0,'cache':{'read':0,'write':1}},
                      {'input':0,'output':0,'cache':{'read':0,'write':0},'tier':{'input':1}}):
            self.assertEqual(m.normalizar(bloco('parece-free',cost=custo)),[])
    def test_namespace_api_toolcall_status_identidade_estritos(self):
        for extra in ({'api':{'url':'https://local/v1'}},{'capabilities':{'toolcall':False}},{'status':'deprecated'}):
            self.assertEqual(m.normalizar(bloco(**extra)),[])
        with self.assertRaises(ValueError):m.normalizar(bloco(providerID='local'))
        with self.assertRaises(ValueError):m.normalizar(bloco()+bloco())
        with self.assertRaises(ValueError):m.normalizar('LOG SEGREDO\n'+bloco())
        with self.assertRaises(ValueError):m.normalizar('x'*(m.LIMITE+1))
        with self.assertRaises(ValueError):m.normalizar(bloco().replace('"input": 0','"input": 1, "input": 0'))
    def test_cache_sem_inferencia_e_sem_mutacao(self):
        c=m.Catalogo()
        with patch.object(m,'consultar',return_value=m.normalizar(bloco())) as consulta:
            a=c.obter();a['modelos'].clear();b=c.obter()
        self.assertEqual(consulta.call_count,1);self.assertEqual(len(b['modelos']),1)
    def test_falha_nao_serve_catalogo_vencido_como_atual(self):
        c=m.Catalogo()
        with patch.object(m,'consultar',return_value=m.normalizar(bloco())):c.obter()
        c.validade=0
        with patch.object(m,'consultar',side_effect=ValueError('SEGREDO')):r=c.obter()
        self.assertFalse(r['ok']);self.assertEqual(r['modelos'],[]);self.assertNotIn('SEGREDO',json.dumps(r))
    def test_permissao_e_console_sem_invocar_cli(self):
        with patch.object(m.CATALOGO,'obter',side_effect=AssertionError('CLI indevido')):
            self.assertEqual(m.api({'console':'opencode'},{'permissao':'ver'})[0],403)
            for dados in ({'console':'codex'},{'console':'opencode','comando':'arbitrario'}):
                self.assertEqual(m.api(dados,{'permissao':'pc'})[0],400)
    def test_rota_servidor_e_permissao_ambas_presentes(self):
        import servidor,rede
        self.assertEqual(rede.PERMISSAO_ROTA['/api/gestao/modelos'],{'pc'})
        with patch.object(m.CATALOGO,'obter',return_value={'ok':True,'modelos':[],'limite':'teste'}):
            codigo,dados=servidor.Handler.api_post(object(),'/api/gestao/modelos',{'console':'opencode','_ua':'privado'},{'permissao':'pc'})
        self.assertEqual(codigo,200);self.assertEqual(dados['modelos'],[])
    def test_http_real_exige_guarda_de_acao(self):
        import servidor,rede
        antigo=getattr(servidor.Handler,'rede',None)
        with tempfile.TemporaryDirectory() as tmp:
            raiz=Path(tmp);servidor.Handler.rede=rede.Rede(raiz,False,False)
            srv=ThreadingHTTPServer(('127.0.0.1',0),partial(servidor.Handler,directory=str(raiz)))
            thread=threading.Thread(target=srv.serve_forever,daemon=True);thread.start()
            try:
                with patch.object(m.CATALOGO,'obter',return_value={'ok':True,'modelos':[]}) as consulta:
                    for cabecalhos,esperado in (({'Content-Type':'application/json'},403),
                            ({'Content-Type':'application/json','X-Office-Acao':'1','Origin':'https://fora.example'},403),
                            ({'Content-Type':'application/json','X-Office-Acao':'1','Origin':f'http://127.0.0.1:{srv.server_address[1]}'},200)):
                        con=http.client.HTTPConnection('127.0.0.1',srv.server_address[1],timeout=5)
                        try:
                            con.request('POST','/api/gestao/modelos',json.dumps({'console':'opencode'}),cabecalhos)
                            r=con.getresponse();r.read();self.assertEqual(r.status,esperado)
                        finally:con.close()
                    self.assertEqual(consulta.call_count,1)
            finally:
                srv.shutdown();srv.server_close();thread.join()
                servidor.Handler.rede=antigo


if __name__=='__main__':unittest.main()
