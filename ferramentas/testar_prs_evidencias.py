"""Evidências de commit exato, sanitização e paginação real do adapter gh."""
import json
import copy
from pathlib import Path
import sys
import tempfile
import unittest
import http.client
import threading
from functools import partial
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import prs_evidencias as e
import kanban_gestao as k
from funcionarios import id_projeto


class Evidencias(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.p=Path(self.tmp.name); (self.p/'.office').mkdir()
        (self.p/'.office/projeto.json').write_text(json.dumps({'ativo':True,
          'kanban':{'repo':'owner/repo'},'merge':{'modo':'automatico','checks':['CI','lint']}}),encoding='utf-8')
        self.sha='a'*40; self.chamadas=[]; self.heads=0
        self.runs=[{'id':1,'name':'CI','status':'completed','conclusion':'success','head_sha':self.sha,'app':{'id':10},'output':{'text':'SEGREDO'}}]
        self.statuses=[{'id':3,'context':'lint','state':'failure','description':'SEGREDO'},
                       {'id':2,'context':'lint','state':'success'}]
        self.reviews=[{'id':1,'state':'APPROVED','commit_id':'b'*40,'user':{'login':'antigo'},'submitted_at':'2026-10-01T10:00:00Z','body':'SEGREDO'},
                      {'id':2,'state':'CHANGES_REQUESTED','commit_id':self.sha,'user':{'login':'atual'},'submitted_at':'2026-10-02T10:00:00Z'}]

    def api(self,caminho,**kw):
        self.chamadas.append((caminho,kw))
        if caminho.endswith('/pulls/42'):
            self.heads+=1
            return {'number':42,'state':'open','html_url':'https://github.com/owner/repo/pull/42',
                    'base':{'repo':{'full_name':'owner/repo'}},'head':{'sha':self.sha},'mergeable':None}
        if 'check-runs?' in caminho: return self.runs
        if '/statuses?' in caminho: return self.statuses
        if '/reviews?' in caminho: return self.reviews
        raise AssertionError(caminho)

    def ler(self,chamar=None): return e.ler([self.p],id_projeto(self.p),42,self.sha,chamar or self.api)

    def test_commit_status_recente_revisao_antiga_e_sanitizacao(self):
        r=self.ler(); self.assertTrue(r['ok']); self.assertEqual(self.heads,2)
        self.assertEqual(r['gates'],[{'nome':'CI','estado':'success'},{'nome':'lint','estado':'failure'}])
        self.assertEqual([v['commit_atual'] for v in r['revisoes']],[False,True])
        self.assertIsNone(r['mergeavel']); self.assertNotIn('SEGREDO',json.dumps(r))
        self.assertNotIn(str(self.p),json.dumps(r)); self.assertNotIn('elegivel',r)
        self.assertEqual(len(self.chamadas),5)
        self.assertEqual(self.chamadas[1][1],{'paginar':True,'campo':'check_runs'})

    def test_colisao_ausencia_e_neutral_nao_viram_sucesso(self):
        self.runs += [{**self.runs[0],'id':2,'app':{'id':11}}]
        self.assertEqual(self.ler()['gates'][0]['estado'],'ambíguo')
        self.runs=[]; self.assertEqual(self.ler()['gates'][0]['estado'],'ausente')
        self.runs=[{'id':1,'name':'CI','status':'completed','conclusion':'neutral','head_sha':self.sha,'app':{'id':10}}]
        self.assertEqual(self.ler()['gates'][0]['estado'],'neutral')

    def test_troca_commit_politica_repo_e_falha_apagam_evidencias(self):
        for modo in ('sha','politica','repo','falha'):
            self.heads=0
            def api(caminho,**kw):
                d=self.api(caminho,**kw)
                if modo=='falha' and '/reviews?' in caminho: raise ValueError('SEGREDO')
                if self.heads==2:
                    if modo=='sha': d['head']['sha']='c'*40
                    if modo=='repo': d['base']['repo']['full_name']='outro/repo'
                    if modo=='politica':
                        (self.p/'.office/projeto.json').write_text('{"ativo":false}',encoding='utf-8')
                return d
            r=self.ler(api)
            self.assertFalse(r['ok']); self.assertEqual(r['checks'],[]); self.assertEqual(r['revisoes'],[])
            self.assertNotIn('SEGREDO',json.dumps(r))
            self.setUp_repor()

    def test_portao_unreal_obrigatorio_nao_confunde_compilacao_pulada_com_success(self):
        nomes=['architecture-guardian','revisor-ia','sugestoes','grafo','unreal-build']
        (self.p/'.office/projeto.json').write_text(json.dumps({'ativo':True,
          'kanban':{'repo':'owner/repo'},'merge':{'modo':'automatico','checks':nomes}}),encoding='utf-8')
        self.statuses=[]
        anteriores=[{'id':i+10,'name':nome,'status':'completed','conclusion':'success',
          'head_sha':self.sha,'app':{'id':10}} for i,nome in enumerate(nomes[:-1])]
        for status,conclusao,esperado in [('completed','success','success'),
            ('completed','skipped','skipped'),('completed','failure','failure'),
            ('completed','cancelled','cancelled'),('in_progress',None,'pending')]:
            with self.subTest(conclusao=conclusao):
                self.heads=0
                self.runs=anteriores+[{'id':20,'name':'unreal-build','status':status,
                  'conclusion':conclusao,'head_sha':self.sha,'app':{'id':10}}]
                r=self.ler();self.assertTrue(r['ok'])
                self.assertEqual(r['gates'],[{'nome':n,'estado':'success'} for n in nomes[:-1]]+
                  [{'nome':'unreal-build','estado':esperado}])
                self.assertNotIn('elegivel',r)

    def setUp_repor(self):
        (self.p/'.office/projeto.json').write_text(json.dumps({'ativo':True,'kanban':{'repo':'owner/repo'},
            'merge':{'modo':'automatico','checks':['CI','lint']}}),encoding='utf-8')

    def test_envelopes_invalidos_e_sha_divergente(self):
        original=self.runs[0]
        for campo,valor in [('head_sha','b'*40),('status','futuro'),('conclusion',None),('id',True)]:
            self.runs=[{**original,campo:valor}]; r=self.ler()
            self.assertFalse(r['ok']); self.assertEqual(r['checks'],[])
        self.runs=[original,original]; self.assertFalse(self.ler()['ok'])
        r=e.ler([self.p],str(self.p),42,self.sha,self.api)
        self.assertFalse(r['ok']); self.assertNotIn(str(self.p),json.dumps(r))
        self.runs=[original]; self.reviews[0]['submitted_at']='inválida'
        self.assertFalse(self.ler()['ok'])

    def test_adapter_gh_envelopes_paginados_e_contrato_antigo(self):
        for payload,kw,esperado in [([[1],[2]],{},[1,2]),
              ([{'total_count':2,'check_runs':[1]},{'total_count':2,'check_runs':[2]}],{'campo':'check_runs'},[1,2]),
              ([{'total_count':0,'check_runs':[]}],{'campo':'check_runs'},[])]:
            with patch.object(k.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=json.dumps(payload))) as run:
                self.assertEqual(k.api('repos/owner/repo/endpoint',paginar=True,**kw),esperado)
                args=run.call_args.args[0]
                self.assertIn('--paginate',args); self.assertIn('--slurp',args)
                self.assertEqual(args[args.index('--method')+1],'GET')
        for payload in ([{'total_count':2,'check_runs':[1]}],
                        [{'total_count':1,'check_runs':[1]},{'total_count':2,'check_runs':[2]}],
                        [{'total_count':True,'check_runs':[]}],[]):
            with patch.object(k.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=json.dumps(payload))):
                with self.assertRaises(ValueError): k.api('x',paginar=True,campo='check_runs')

    def regras(self):
        return [{'type':'required_status_checks','ruleset_id':9,'ruleset_source_type':'Organization',
                 'parameters':{'strict_required_status_checks_policy':True,'required_status_checks':[
                     {'context':'CI','integration_id':10},{'context':'lint'}]},'ruleset_source':'SEGREDO'},
                {'type':'pull_request','ruleset_id':9,'ruleset_source_type':'Organization',
                 'parameters':{'required_approving_review_count':2,'dismiss_stale_reviews_on_push':True,
                    'require_code_owner_review':True,'require_last_push_approval':True,
                    'required_review_thread_resolution':True,'required_reviewers':[{'privado':'SEGREDO'}]}}]

    def api_regras(self,caminho,**kw):
        if '/rules/branches/' in caminho:
            self.chamadas.append((caminho,kw));return copy.deepcopy(self.regras())
        d=self.api(caminho,**kw)
        if caminho.endswith('/pulls/42'):d['base'].update(ref='release/office',sha='c'*40)
        return d

    def test_rulesets_ativos_base_codificada_app_e_sanitizacao(self):
        self.runs.append({**self.runs[0],'id':2,'app':{'id':11},'conclusion':'failure'})
        r=self.ler(self.api_regras);self.assertTrue(r['ok'])
        regras=r['regras_branch'];self.assertEqual(regras['estado'],'consultado')
        self.assertEqual(regras['branch'],'release/office');self.assertEqual(regras['sha_base'],'c'*40)
        self.assertEqual(r['gates'][0]['estado'],'ambíguo')
        self.assertEqual([g['estado'] for g in regras['gates']],['success','failure'])
        self.assertEqual(regras['regras'][1]['aprovacoes_exigidas'],2)
        self.assertTrue(regras['regras'][1]['parametros_adicionais'])
        self.assertNotIn('SEGREDO',json.dumps(r));self.assertNotIn('elegivel',r)
        chamadas=[c for c in self.chamadas if '/rules/branches/' in c[0]]
        self.assertEqual(chamadas,[('repos/owner/repo/rules/branches/release%2Foffice?per_page=100',{'paginar':True})]*2)

    def test_falha_de_acesso_nao_vira_ruleset_vazio(self):
        def chamar(caminho,**kw):
            if '/rules/branches/' in caminho:raise ValueError('SEGREDO')
            return self.api_regras(caminho,**kw)
        r=self.ler(chamar);self.assertTrue(r['ok']);self.assertEqual(r['regras_branch']['estado'],'indisponivel')
        self.assertNotIn('SEGREDO',json.dumps(r))

    def test_mudanca_de_base_ou_ruleset_invalida_toda_evidencia(self):
        for modo in ('branch','base_sha','ruleset'):
            self.heads=0;leituras=0
            def chamar(caminho,**kw):
                nonlocal leituras
                d=self.api_regras(caminho,**kw)
                if '/rules/branches/' in caminho:
                    leituras+=1
                    if modo=='ruleset' and leituras==2:d=[]
                if caminho.endswith('/pulls/42') and self.heads==2:
                    if modo=='branch':d['base']['ref']='outra'
                    if modo=='base_sha':d['base']['sha']='d'*40
                return d
            r=self.ler(chamar);self.assertFalse(r['ok']);self.assertEqual(r['checks'],[])
            self.assertEqual(r['regras_branch']['estado'],'indisponivel')

    def test_regra_invalida_nao_inventa_aprovacao(self):
        for modo in ('app','booleano','aprovacoes','duplicado'):
            def chamar(caminho,**kw):
                d=self.api_regras(caminho,**kw)
                if '/rules/branches/' in caminho:
                    if modo=='app':d[0]['parameters']['required_status_checks'][0]['integration_id']=True
                    if modo=='booleano':d[1]['parameters']['require_code_owner_review']='false'
                    if modo=='aprovacoes':d[1]['parameters']['required_approving_review_count']=True
                    if modo=='duplicado':d.append(d[0])
                return d
            r=self.ler(chamar);self.assertTrue(r['ok']);self.assertEqual(r['regras_branch']['estado'],'indisponivel')

    def test_rulesets_vazios_e_regra_desconhecida_nao_autorizam_merge(self):
        for dados in ([],[{'type':'regra_futura','ruleset_id':3,'ruleset_source_type':'Repository','parameters':{'segredo':'SEGREDO'}}]):
            def chamar(caminho,**kw):
                return copy.deepcopy(dados) if '/rules/branches/' in caminho else self.api_regras(caminho,**kw)
            r=self.ler(chamar);self.assertTrue(r['ok']);self.assertEqual(r['regras_branch']['estado'],'consultado')
            self.assertIn('Proteção clássica',r['regras_branch']['limite']);self.assertNotIn('elegivel',r)
            self.assertNotIn('SEGREDO',json.dumps(r))

    def test_pendencias_graphql_integradas_e_app_da_protecao_classica(self):
        from testar_prs_pendencias import envelope
        def chamar(v):
            d=envelope();pr=d['data']['repository']['pullRequest']
            pr.update(headRefOid=self.sha,baseRefOid='c'*40,baseRefName='release/office')
            pr['baseRef']['name']='release/office'
            pr['reviewThreads'].update(totalCount=2,pageInfo={'hasNextPage':False,'endCursor':'fim'})
            return d
        r=e.ler([self.p],id_projeto(self.p),42,self.sha,self.api_regras,chamar)
        self.assertTrue(r['ok']);self.assertEqual(r['pendencias_revisao']['threads_pendentes'],1)
        self.assertEqual(r['pendencias_revisao']['protecao_classica']['checks'][0]['estado'],'success')
        r=e.ler([self.p],id_projeto(self.p),42,self.sha,self.api_regras,lambda _: {'errors':[{}]})
        self.assertTrue(r['ok']);self.assertEqual(r['pendencias_revisao'],{'estado':'indisponivel'})
        def mudou(v):
            d=chamar(v);d['data']['repository']['pullRequest']['headRefOid']='d'*40;return d
        r=e.ler([self.p],id_projeto(self.p),42,self.sha,self.api_regras,mudou)
        self.assertFalse(r['ok']);self.assertEqual(r['checks'],[])

    def test_http_real_parametros_e_sem_fallback_legado(self):
        import servidor, rede
        anterior=servidor.Handler.rede
        servidor.Handler.rede=rede.Rede(self.p,False,False)
        srv=ThreadingHTTPServer(('127.0.0.1',0),partial(servidor.Handler,directory=str(Path(servidor.__file__).parent)))
        t=threading.Thread(target=srv.serve_forever,daemon=True); t.start()
        con=http.client.HTTPConnection('127.0.0.1',srv.server_address[1],timeout=10)
        try:
            with patch.object(servidor,'cfg',return_value={'projetos':[self.p]}),patch.object(e,'api',side_effect=self.api), \
                 patch.object(servidor,'prs',side_effect=AssertionError('legado')):
                base=f'/api/gestao/pr?projeto={id_projeto(self.p)}&numero=42&sha={self.sha}'
                con.request('GET',base); r=con.getresponse(); d=json.loads(r.read())
                self.assertEqual(r.status,200); self.assertTrue(d['ok'])
                self.assertEqual(d['gates'][1]['estado'],'failure')
                for url in (base+'&numero=43',base+'&ignorar=1',base.replace('numero=42','numero=x')):
                    con.request('GET',url); r=con.getresponse(); r.read(); self.assertEqual(r.status,400)
        finally:
            con.close(); srv.shutdown();srv.server_close();t.join();servidor.Handler.rede=anterior


if __name__=='__main__': unittest.main()
