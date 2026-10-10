"""XP real com persistência isolada e política/Kanban por projeto."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import configuracao,gestao_cli,xp,xp_projeto as p
from funcionarios import id_projeto

class XPProjeto(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.raiz=Path(self.tmp.name);self.a=self.raiz/'a';self.b=self.raiz/'b'
        for projeto,repo in ((self.a,'owner/a'),(self.b,'owner/b')):
            (projeto/'.office').mkdir(parents=True)
            (projeto/'.office/projeto.json').write_text(json.dumps({'ativo':True,'kanban':{'repo':repo,'owner':'owner','numero':1,'feito':'Aceito'},
                'equipes':[{'nome':'Time A','especialidade':'Implementação','executor':{'console':'codex'}}]}),encoding='utf-8')
        self.base=configuracao.normalizar({'projetos':[str(self.a),str(self.b)],'github':{'repo':'outro/global'},'xp':{'ativo':True}})
        pa=patch.object(gestao_cli,'RAIZ',self.raiz/'app');pa.start();self.addCleanup(pa.stop)
    def contexto(self,a=None):return p.contexto(a or self.a,self.base)
    def placar(self,ctx):
        ctx['pasta'].mkdir(parents=True,exist_ok=True)
        ctx['placar'].write_text(json.dumps({'repo':ctx['politica']['kanban']['repo'],'projeto_id':ctx['id'],'politica_versao':ctx['versao'],
            'agentes':{'Time A':{'conferir':[{'pr':42}],'auditoria':[]}},'time':{}}),encoding='utf-8')
    def test_decisoes_mesmo_pr_nao_cruzam_projeto_ou_repo(self):
        a=self.contexto();b=self.contexto(self.b)
        self.assertEqual(a['decisoes'].decisoes('conferido'),set());self.assertFalse(a['pasta'].exists())
        a['decisoes'].decidir(42,'conferido','PC','Revisado')
        self.assertEqual(a['decisoes'].decisoes('conferido'),{42});self.assertEqual(b['decisoes'].decisoes('conferido'),set())
        arq=self.a/'.office/projeto.json';d=json.loads(arq.read_text());d['kanban']['repo']='owner/novo';arq.write_text(json.dumps(d))
        novo=self.contexto();self.assertNotEqual(novo['pasta'],a['pasta']);self.assertEqual(novo['decisoes'].decisoes('conferido'),set())
        self.assertEqual(a['decisoes'].decisoes('conferido'),{42})
    def test_vista_exige_selecao_e_nao_ler_global(self):
        r=p.vista([self.a,self.b],self.base);self.assertEqual(r['agentes'],{});self.assertEqual(len(r['projetos']),2)
        self.assertFalse((self.raiz/'app').exists())
        ctx=self.contexto();self.placar(ctx)
        r=p.vista([self.a,self.b],self.base,ctx['id']);self.assertEqual(r['repo'],'owner/a');self.assertIsNone(r['custos'])
        self.assertNotIn(str(self.a),json.dumps(r));self.assertEqual(p.vista([self.a,self.b],self.base,'inexistente')['agentes'],{})
    def test_politica_nova_nao_exibe_placar_antigo(self):
        ctx=self.contexto();self.placar(ctx)
        arq=self.a/'.office/projeto.json';arq.write_bytes(arq.read_bytes()+b' ')
        r=p.vista([self.a],self.base,ctx['id']);self.assertEqual(r['agentes'],{});self.assertIn('desatualizado',r['erro'])
    def test_kanban_comum_e_coluna_final_da_politica(self):
        with patch.dict(xp.__dict__,{}),patch('configuracao.carregar',return_value=self.base):
            xp.configurar_projeto(self.a)
            with patch('kanban_gestao.Kanban') as classe:
                classe.return_value.cartoes.return_value=[{'numero':42,'equipe':'Time A','status':'Aceito'}]
                cartoes=xp.ler_kanban();self.assertEqual(cartoes['42']['time'],'Time A')
                self.assertEqual(classe.call_args.args[1],gestao_cli.pasta_dados(self.a)/'kanban.json')
            self.assertTrue(xp.cartao_feito({'status':'Aceito'}));self.assertFalse(xp.cartao_feito({'status':'Feito'}))
            self.assertEqual(xp.pontos_skills(),{});self.assertEqual(xp.AGENTE_PADRAO,'')
    def preparar_cache(self):
        xp.configurar_projeto(self.a)
        assinatura=json.dumps([xp.GITHUB['repo'],xp.GITHUB['check_revisao'],xp.XP['padroes_teste'],xp.XP['padroes_avaliacao']],ensure_ascii=False)
        assinatura+=json.dumps(xp.CONTEXTO_PROJETO['politica']['kanban'],sort_keys=True)
        xp.gravar_json(xp.ESTADO,{'assinatura':assinatura,'lista':[]})
    def test_motor_real_decisao_e_recalculo_sem_github(self):
        with patch.dict(xp.__dict__,{}),patch('configuracao.carregar',return_value=self.base):
            self.preparar_cache()
            with patch.object(sys,'argv',['xp.py','--projeto',str(self.a),'--conferido','42','--so-placar']),patch.object(xp,'gh',side_effect=AssertionError('Rede indevida')):
                self.assertEqual(xp.main(),0)
        ctx=self.contexto();self.assertEqual(ctx['decisoes'].decisoes('conferido'),{42})
        self.assertEqual(p.ler(ctx)['repo'],'owner/a');self.assertFalse(self.contexto(self.b)['pasta'].exists())
    def test_cli_ambiguo_e_hash_antigo_nao_decidem(self):
        with patch.dict(xp.__dict__,{}),patch('configuracao.carregar',return_value=self.base):
            with patch.object(sys,'argv',['xp.py','--conferido','42']):
                with self.assertRaisesRegex(ValueError,'exige --projeto'):xp.main()
            with patch.object(sys,'argv',['xp.py','--projeto',str(self.a),'--versao-politica','0'*64,'--conferido','42']):
                with self.assertRaisesRegex(ValueError,'Política mudou'):xp.main()
        self.assertFalse(self.contexto()['pasta'].exists())
    def test_api_acao_no_projeto_sem_mudar_banco_global(self):
        import servidor,banco
        ctx=self.contexto();self.placar(ctx);original=banco.ARQ
        dados={'pr':42,'projeto_id':ctx['id'],'versao':ctx['versao']}
        def rodar(cmd,**kw):
            self.assertIn('--projeto',cmd);self.assertEqual(cmd[cmd.index('--projeto')+1],str(self.a.resolve()))
            with patch.dict(xp.__dict__,{}),patch.object(sys,'argv',cmd[1:]),patch.object(xp,'gh',side_effect=AssertionError('Rede indevida')):
                self.preparar_cache();codigo=xp.main()
            return subprocess.CompletedProcess(cmd,codigo,'','')
        with patch.object(servidor,'cfg',return_value=self.base),patch('configuracao.carregar',return_value=self.base):
            self.assertEqual(servidor.acao_xp('/api/xp/conferido',{'pr':42},{'permissao':'pc'})[0],400)
            self.assertEqual(servidor.acao_xp('/api/xp/conferido',{**dados,'versao':'0'*64},{'permissao':'pc'})[0],409)
            with patch.object(servidor.subprocess,'run',side_effect=rodar):
                codigo,r=servidor.acao_xp('/api/xp/conferido',dados,{'permissao':'pc'})
                self.assertEqual(codigo,200);self.assertEqual(r['placar']['projeto_id'],ctx['id'])
        self.assertEqual(banco.ARQ,original);self.assertEqual(ctx['decisoes'].decisoes('conferido'),{42})
    def test_http_xp_isola_selecao_e_csrf(self):
        import http.client,threading
        from functools import partial
        from http.server import ThreadingHTTPServer
        import servidor,rede
        a=self.contexto();b=self.contexto(self.b);self.placar(a);self.placar(b)
        anterior=servidor.Handler.rede;servidor.Handler.rede=rede.Rede(self.raiz/'app',False,False)
        srv=ThreadingHTTPServer(('127.0.0.1',0),partial(servidor.Handler,directory=str(Path(servidor.__file__).parent)))
        th=threading.Thread(target=srv.serve_forever,daemon=True);th.start()
        con=http.client.HTTPConnection('127.0.0.1',srv.server_address[1],timeout=10)
        try:
            with patch.object(servidor,'cfg',return_value=self.base):
                con.request('GET','/xp');r=con.getresponse();d=json.loads(r.read());self.assertEqual(d['agentes'],{})
                for ctx in (a,b):
                    con.request('GET','/xp?projeto='+ctx['id']);r=con.getresponse();d=json.loads(r.read())
                    self.assertEqual(d['repo'],ctx['politica']['kanban']['repo']);self.assertEqual(d['projeto_id'],ctx['id'])
                host=f'127.0.0.1:{srv.server_address[1]}'
                h={'Host':host,'Content-Type':'application/json','X-Office-Acao':'1','Origin':'https://externa.invalid'}
                with patch.object(servidor,'acao_xp') as acao:
                    con.request('POST','/api/xp/conferido',json.dumps({'pr':42,'projeto_id':a['id'],'versao':a['versao']}),h)
                    r=con.getresponse();r.read();self.assertEqual(r.status,403);acao.assert_not_called()
        finally:
            con.close();srv.shutdown();srv.server_close();th.join(5);servidor.Handler.rede=anterior

if __name__=='__main__':unittest.main()
