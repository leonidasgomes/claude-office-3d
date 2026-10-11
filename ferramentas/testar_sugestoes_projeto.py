"""Coleta/tratamento reais em caixas isoladas; GitHub e modelos simulados."""
import json,os,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import configuracao,gestao_cli,gestao_projeto,sugestoes_bot as sb,servidor
from funcionarios import id_projeto

class Sugestoes(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.raiz=Path(self.tmp.name);self.a=self.raiz/'a';self.b=self.raiz/'b'
        for p,repo in ((self.a,'owner/a'),(self.b,'owner/b')):
            (p/'.office').mkdir(parents=True)
            (p/'.office/projeto.json').write_text(json.dumps({'ativo':True,'kanban':{'repo':repo},
                'sugestoes':{'ativo':True,'bots':['revisor[bot]']},
                'equipes':[{'nome':'Dev','especialidade':'Código','executor':{'console':'codex'}}]}),encoding='utf-8')
        self.base=configuracao.normalizar({'projetos':[str(self.a),str(self.b)],'github':{'repo':'global/outro','bots_revisao':['global[bot]'],'publicar_status':True},
            'sugestoes':{'triagem_modelo':'modelo-legado'},'revisor':{'ativo':True}})
        for alvo,valor in ((gestao_cli,'RAIZ'),):
            p=patch.object(alvo,valor,self.raiz/'app');p.start();self.addCleanup(p.stop)
        for alvo,nome,valor in ((configuracao,'carregar',self.base),(servidor,'cfg',self.base)):
            p=patch.object(alvo,nome,return_value=valor);p.start();self.addCleanup(p.stop)
    def cfg(self,p=None):return sb.configuracao(p or self.a)
    def api(self,cfg,caminho,*args,**kw):
        self.assertTrue(caminho.startswith('repos/'+cfg['repo']+'/'))
        if '/pulls?state=' in caminho:return 200,[{'number':42,'title':'Mudança','head':{'ref':'feat/42'},'labels':[{'name':'Dev'}]}],{}
        if '/pulls/comments?' in caminho:return 200,[{'id':7,'body':'**P1 — Corrigir contrato**\nVerifique a entrada','user':{'login':'revisor[bot]'},
            'pull_request_url':f'https://api.github.com/repos/{cfg["repo"]}/pulls/42','created_at':sb._iso(sb._agora()),'path':'app.py','line':3}],{}
        if '/reviews?' in caminho:return 200,[],{}
        raise AssertionError('Chamada inesperada: '+caminho)
    def coletar(self,cfg):
        with patch.object(sb,'gh_api',side_effect=self.api),patch.object(sb,'triar',side_effect=AssertionError('Triagem global indevida')):
            r=sb.coletar(cfg);self.assertEqual(r['erro'],'');self.assertEqual(r['novas'],1)
    def test_coleta_nao_herda_modelo_bots_revisor_ou_status_globais(self):
        a=self.cfg();self.assertFalse(a['publicar_status']);self.assertFalse(a['revisor']);self.assertEqual(a['modelo'],'')
        self.assertEqual(a['bots'],['revisor[bot]']);self.coletar(a)
        self.assertEqual(sb.resumo(a)['itens'][0]['id'],'7');self.assertEqual(sb.resumo(a)['itens'][0]['pr'],42)
    def test_comentario_com_url_de_outro_repo_nao_entra(self):
        original=self.api
        def chamada(cfg,caminho,*args,**kw):
            codigo,dados,cab=original(cfg,caminho,*args,**kw)
            if '/pulls/comments?' in caminho:
                dados=dados+[{**dados[0],'id':8,'pull_request_url':'https://api.github.com/repos/outro/repo/pulls/42'}]
            return codigo,dados,cab
        a=self.cfg()
        with patch.object(sb,'gh_api',side_effect=chamada):self.assertEqual(sb.coletar(a)['novas'],1)
        self.assertEqual([x['id'] for x in sb.ler_caixa(a)],['7'])
    def test_prs_paginados_e_falha_nao_substitui_lista_completa(self):
        cfg=self.cfg();est={}
        with patch.object(sb,'gh_api',side_effect=[(200,[{'number':n} for n in range(1,101)],{}),(200,[{'number':101}],{})]):
            self.assertEqual(sb._baixar_prs_abertos(cfg,est),2)
        self.assertEqual(len(est['prs']),101)
        with patch.object(sb,'gh_api',side_effect=[(200,[{'number':n} for n in range(1,101)],{}),(500,{}, {})]):
            with self.assertRaisesRegex(ValueError,'incompleta'):sb._baixar_prs_abertos(cfg,est)
        self.assertEqual(len(est['prs']),101)
    def test_mesmo_id_comentario_nao_cruza_caixas(self):
        a=self.cfg();b=self.cfg(self.b);self.coletar(a);self.coletar(b)
        self.assertTrue(sb.tratar(a,'7','ignorada','Falso positivo')[0])
        self.assertEqual(sb.ler_caixa(a)[0]['situacao'],'ignorada');self.assertEqual(sb.ler_caixa(b)[0]['situacao'],'nova')
        arq=self.a/'.office/projeto.json';d=json.loads(arq.read_text());d['kanban']['repo']='owner/novo';arq.write_text(json.dumps(d))
        self.assertEqual(sb.ler_caixa(self.cfg()),[]);self.assertNotEqual(self.cfg()['pasta'],a['pasta'])
    def test_api_selecao_leitura_e_tratamento_por_versao(self):
        a=self.cfg();self.coletar(a)
        r=servidor.sugestoes_get()[1];self.assertEqual(r['itens'],[]);self.assertEqual(len(r['projetos']),2)
        r=servidor.sugestoes_get(a['projeto_id'])[1];self.assertEqual(r['repo'],'owner/a');self.assertEqual(len(r['itens']),1)
        dados={'id':'7','acao':'resolvida','projeto_id':a['projeto_id'],'versao':a['politica_versao']}
        self.assertEqual(servidor.sugestoes_tratar({'id':'7','acao':'resolvida'},{'permissao':'pc'})[0],400)
        self.assertEqual(servidor.sugestoes_tratar({**dados,'versao':'0'*64},{'permissao':'pc'})[0],409)
        self.assertEqual(servidor.sugestoes_tratar(dados,{'permissao':'pc'})[0],200)
        self.assertEqual(sb.ler_caixa(a)[0]['situacao'],'resolvida')
        self.assertFalse(self.cfg(self.b)['pasta'].exists());self.assertNotIn(str(self.a),json.dumps(r))
    def test_politica_alterada_nao_grava_resposta_antiga(self):
        a=self.cfg();self.coletar(a);arq=self.a/'.office/projeto.json';arq.write_bytes(arq.read_bytes()+b' ')
        with self.assertRaisesRegex(ValueError,'Política mudou'):sb.tratar(a,'7','resolvida')
        self.assertEqual(sb.ler_caixa(a)[0]['situacao'],'nova')
    def test_optout_nao_coleta_nem_cria_dados(self):
        arq=self.a/'.office/projeto.json';d=json.loads(arq.read_text());d['sugestoes']['ativo']=False;arq.write_text(json.dumps(d))
        a=self.cfg()
        with patch.object(sb,'gh_api') as api:
            self.assertIn('desligado',sb.coletar(a)['erro']);api.assert_not_called()
        self.assertFalse(a['pasta'].exists());self.assertFalse(servidor.sugestoes_get(a['projeto_id'])[1]['ativo'])
    def test_trava_antiga_do_projeto_nao_e_roubada_por_prazo(self):
        a=self.cfg();a['pasta'].mkdir(parents=True);arq=a['pasta']/'.trava';arq.write_text('Em uso')
        os.utime(arq,(time.time()-500,time.time()-500))
        with self.assertRaises(TimeoutError):
            with sb.trava_caixa(a,espera=0):pass
        self.assertEqual(arq.read_text(),'Em uso')
    def test_laco_coleta_projetos_sem_acionar_revisor_ou_auditor_global(self):
        class Parar:
            terminou=False
            def wait(self,tempo):
                if tempo==25:return False
                self.terminou=True;return True
            def is_set(self):return self.terminou
        chamadas=[]
        def coletar(cfg,**kw):chamadas.append((cfg['repo'],kw));return {'erro':''}
        with patch.object(sb,'coletar',side_effect=coletar),patch.object(servidor,'revisor_rodada') as revisor:
            servidor.sugestoes_laco(Parar());revisor.assert_not_called()
        self.assertEqual({c[0] for c in chamadas},{'owner/a','owner/b'});self.assertTrue(all(c[1]['triagem'] is False for c in chamadas))
        self.assertFalse(servidor.sugestoes_para_alertas()['pronto_carregado'])
    def test_cli_sem_projeto_nao_cai_no_global_e_bots_sao_explicitos(self):
        self.assertEqual(sb.main(['--listar']),2)
        for dados in ({'sugestoes':{'ativo':True,'bots':[]}}, {'sugestoes':{'bots':['x','X']}}):
            with self.assertRaises(ValueError):gestao_projeto.validar(dados)
    def test_http_seleciona_caixa_e_recusa_csrf(self):
        import http.client,threading
        from functools import partial
        from http.server import ThreadingHTTPServer
        import rede
        a=self.cfg();self.coletar(a)
        anterior=servidor.Handler.rede;servidor.Handler.rede=rede.Rede(self.raiz/'app',False,False)
        srv=ThreadingHTTPServer(('127.0.0.1',0),partial(servidor.Handler,directory=str(Path(servidor.__file__).parent)))
        th=threading.Thread(target=srv.serve_forever,daemon=True);th.start()
        con=http.client.HTTPConnection('127.0.0.1',srv.server_address[1],timeout=10)
        try:
            con.request('GET','/api/sugestoes?projeto='+a['projeto_id']);r=con.getresponse();d=json.loads(r.read())
            self.assertEqual(d['repo'],'owner/a');self.assertEqual(len(d['itens']),1)
            host=f'127.0.0.1:{srv.server_address[1]}'
            h={'Host':host,'Content-Type':'application/json','X-Office-Acao':'1','Origin':'https://externa.invalid'}
            with patch.object(servidor,'sugestoes_tratar') as tratar:
                con.request('POST','/api/sugestoes/tratar',json.dumps({'id':'7','acao':'resolvida','projeto_id':a['projeto_id'],'versao':a['politica_versao']}),h)
                r=con.getresponse();r.read();self.assertEqual(r.status,403);tratar.assert_not_called()
        finally:
            con.close();srv.shutdown();srv.server_close();th.join(5);servidor.Handler.rede=anterior

class Gate(unittest.TestCase):
    setUp=Sugestoes.setUp
    cfg=Sugestoes.cfg

    def preparar(self):
        dados=json.loads((self.a/'.office/projeto.json').read_text())
        dados['merge']={'modo':'automatico','checks':['sugestoes']}
        dados['sugestoes']={'ativo':False,'bots':[],'triagem':False}
        (self.a/'.office/projeto.json').write_text(json.dumps(dados))
        self.pr={'number':42,'state':'open','draft':False,'created_at':'2020-01-01T00:00:00Z',
                 'head':{'sha':'a'*40,'ref':'feat/42','repo':{'full_name':'owner/a'}},
                 'base':{'sha':'b'*40,'repo':{'full_name':'owner/a'}}}
        self.comentarios=[];self.revisoes=[{'id':1,'state':'COMMENTED','commit_id':'a'*40,
            'body':'[revisor-ia] Revisão independente do despacho.\n- QA (codex)\nSem P0/P1 no relatório verificado.'}]
        self.calls=[]
        def api(caminho,metodo='GET',dados=None,**kw):
            import copy
            self.calls.append((caminho,metodo,dados,kw))
            if metodo=='POST':return {'context':'sugestoes','state':dados['state']}
            if '/comments?' in caminho:
                self.assertTrue(kw['paginar']);return copy.deepcopy(self.comentarios)
            if '/reviews?' in caminho:
                self.assertTrue(kw['paginar']);return copy.deepcopy(self.revisoes)
            if '/commits/' in caminho:return {'commit':{'committer':{'date':'2020-01-01T00:00:00Z'}}}
            return copy.deepcopy(self.pr)
        return api

    def test_cabecalho_sem_achados_nao_vira_sugestao_e_gate_e_isolado(self):
        api=self.preparar()
        with patch.object(sb,'triar',side_effect=AssertionError('Nenhum modelo')):
            r=sb.publicar_gate_gestao(self.a,42,api)
            self.assertEqual(r['estado'],'success')
            self.assertEqual(sb.publicar_gate_gestao(self.a,42,api),r)
        self.assertEqual(len([x for x in self.calls if x[1]=='POST']),1)
        self.assertEqual(sb.ler_caixa(self.cfg()),[])
        self.assertFalse(self.cfg(self.b)['pasta'].exists())

    def test_achado_antigo_e_coletado_sem_janela_e_fica_pending_ate_decisao(self):
        api=self.preparar()
        self.comentarios=[{'id':7,'body':'**P2 — Verificar teste**\nFalta o teste.\n<sub>[revisor-ia]</sub>',
            'created_at':'2020-01-01T00:00:00Z','path':'app.py','line':3,'user':{'login':'autor'}}]
        self.assertEqual(sb.publicar_gate_gestao(self.a,42,api)['estado'],'pending')
        self.assertEqual(sb.ler_caixa(self.cfg())[0]['situacao'],'nova')
        self.assertTrue(sb.tratar(self.cfg(),'7','resolvida','Teste existente conferido')[0])
        self.assertEqual(sb.publicar_gate_gestao(self.a,42,api)['estado'],'success')
        self.assertEqual(len(sb.ler_caixa(self.cfg())),1)

    def test_falha_de_coleta_ou_head_mudou_nao_publica(self):
        api=self.preparar()
        def falha(caminho,*args,**kw):
            if '/reviews?' in caminho:raise ValueError('API indisponível')
            return api(caminho,*args,**kw)
        with self.assertRaises(ValueError):sb.publicar_gate_gestao(self.a,42,falha)
        def mudou(caminho,*args,**kw):
            r=api(caminho,*args,**kw)
            if '/reviews?' in caminho:self.pr['head']['sha']='c'*40
            return r
        with self.assertRaisesRegex(ValueError,'divergente'):sb.publicar_gate_gestao(self.a,42,mudou)
        self.assertFalse(any(x[1]=='POST' for x in self.calls))

    def test_paginacao_com_mais_de_cem_comentarios_inclui_ultimo_achado(self):
        api=self.preparar()
        self.comentarios=[{'id':n,'body':'Conversa','user':{'login':'humano'}} for n in range(1,101)]
        self.comentarios.append({'id':101,'body':'**P1 — Erro**\nFalha comprovada. [revisor-ia]',
                                 'path':'app.py','line':2,'user':{'login':'autor'}})
        self.assertEqual(sb.publicar_gate_gestao(self.a,42,api)['estado'],'pending')
        self.assertEqual(sb.ler_caixa(self.cfg())[0]['id'],'101')

    def test_politica_mudou_ou_pr_rascunho_nao_publica(self):
        api=self.preparar();self.pr['draft']=True
        with self.assertRaises(ValueError):sb.publicar_gate_gestao(self.a,42,api)
        self.pr['draft']=False
        def mudou(caminho,*args,**kw):
            r=api(caminho,*args,**kw)
            if '/commits/' in caminho:
                arq=self.a/'.office/projeto.json';arq.write_bytes(arq.read_bytes()+b' ')
            return r
        with self.assertRaisesRegex(ValueError,'Política mudou'):sb.publicar_gate_gestao(self.a,42,mudou)
        self.assertFalse(any(x[1]=='POST' for x in self.calls))

    def test_laco_publica_somente_gate_exigido_e_pula_rascunho(self):
        self.preparar();parar=unittest.mock.Mock();parar.wait.side_effect=[False,False];parar.is_set.side_effect=[False,True]
        with patch('kanban_gestao.api',return_value=[{'number':42,'draft':False},{'number':43,'draft':True}]), \
             patch.object(sb,'publicar_gate_gestao',return_value={'estado':'success'}) as gate:
            servidor.pronto_laco(parar)
        gate.assert_called_once_with(self.a,42)


if __name__=='__main__':unittest.main()
