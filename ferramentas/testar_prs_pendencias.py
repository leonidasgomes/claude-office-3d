"""GraphQL somente query, paginação completa, identidade e mudanças de revisão."""
import copy,json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import prs_pendencias as p


def envelope(cursor=None):
    nodes=([{'id':'t1','isResolved':False,'isOutdated':True,'body':'SEGREDO'},
            {'id':'t2','isResolved':True,'isOutdated':False}] if cursor is None else
           [{'id':'t3','isResolved':False,'isOutdated':False}])
    regra={'id':'BPR_privado','requiredApprovingReviewCount':2,
           **{x:True for x in p.FLAGS},'requiredStatusChecks':[{'context':'CI','app':{'databaseId':10}}]}
    return {'data':{'repository':{'nameWithOwner':'owner/repo','pullRequest':{
        'number':42,'state':'OPEN','headRefOid':'a'*40,'baseRefOid':'b'*40,
        'baseRefName':'release/test','isDraft':False,'reviewDecision':'REVIEW_REQUIRED',
        'baseRef':{'name':'release/test','branchProtectionRule':regra},
        'reviewThreads':{'totalCount':3,'nodes':nodes,
                         'pageInfo':{'hasNextPage':cursor is None,'endCursor':'cursor1' if cursor is None else 'fim'}}}}}}


class Pendencias(unittest.TestCase):
    def ler(self,chamar=None):return p.ler('owner/repo',42,'a'*40,'release/test','b'*40,chamar or (lambda v:envelope(v['cursor'])))

    def test_duas_coletas_completas_contam_outdated_como_pendente_sem_dados_privados(self):
        chamadas=[]
        def chamar(v):chamadas.append(v.copy());return envelope(v['cursor'])
        r=self.ler(chamar)
        self.assertEqual([v['cursor'] for v in chamadas],[None,'cursor1',None,'cursor1'])
        self.assertEqual(r['threads_total'],3);self.assertEqual(r['threads_pendentes'],2)
        self.assertEqual(r['threads_pendentes_desatualizadas'],1)
        self.assertEqual(r['decisao_revisao'],'REVIEW_REQUIRED')
        self.assertEqual(r['protecao_classica']['aprovacoes_exigidas'],2)
        self.assertNotIn('SEGREDO',json.dumps(r));self.assertNotIn('BPR_privado',json.dumps(r))
        self.assertNotIn('elegivel',r);self.assertNotIn('threads',r)

    def test_adapter_transmite_query_constante_e_variaveis_sem_mutacao(self):
        v={'owner':'owner','repo':'repo','numero':42,'cursor':None}
        with patch.object(p,'api',return_value={'data':{}}) as api:p.graphql(v)
        api.assert_called_once_with('graphql',metodo='POST',dados={'query':p.CONSULTA,'variables':v})
        self.assertTrue(p.CONSULTA.startswith('query OfficePendencias'));self.assertNotIn('mutation',p.CONSULTA)
        self.assertNotIn('body',p.CONSULTA);self.assertNotIn('comments',p.CONSULTA)

    def test_erros_graphql_mesmo_com_data_nao_sao_aceitos(self):
        for erro in ({'errors':[{'message':'privado'}],'data':envelope()['data']}, {'data':{'repository':None}}, {}):
            with self.assertRaises(ValueError):self.ler(lambda _:erro)

    def test_identidade_pr_head_base_branch_e_repo(self):
        for alvo,valor in [('number',43),('state','CLOSED'),('headRefOid','c'*40),('baseRefOid','c'*40),('baseRefName','outra')]:
            def chamar(v):
                d=envelope(v['cursor']);d['data']['repository']['pullRequest'][alvo]=valor;return d
            with self.subTest(alvo=alvo),self.assertRaises(LookupError):self.ler(chamar)
        d=envelope();d['data']['repository']['nameWithOwner']='outra/repo'
        with self.assertRaises(LookupError):self.ler(lambda _:d)

    def test_quantidade_muda_no_meio_da_paginacao(self):
        def chamar(v):
            d=envelope(v['cursor'])
            if v['cursor']:d['data']['repository']['pullRequest']['reviewThreads']['totalCount']=4
            return d
        with self.assertRaises(LookupError):self.ler(chamar)

    def test_mesma_quantidade_com_resolucao_alterada_entre_coletas_falha(self):
        chamadas=0
        def chamar(v):
            nonlocal chamadas
            chamadas+=1;d=envelope(v['cursor'])
            if chamadas==3:d['data']['repository']['pullRequest']['reviewThreads']['nodes'][0]['isResolved']=True
            return d
        with self.assertRaises(LookupError):self.ler(chamar)

    def test_decisao_ou_protecao_alterada_no_meio_da_paginacao(self):
        for modo in ('decisao','protecao'):
            def chamar(v):
                d=envelope(v['cursor']);pr=d['data']['repository']['pullRequest']
                if v['cursor']:
                    if modo=='decisao':pr['reviewDecision']='APPROVED'
                    else:pr['baseRef']['branchProtectionRule']['requiresCodeOwnerReviews']=False
                return d
            with self.assertRaises(LookupError):self.ler(chamar)

    def test_pagina_incompleta_duplicata_bool_falsa_ou_cursor_repetido(self):
        for modo in ('incompleta','duplicada','booleano','cursor','mais2000'):
            def chamar(v):
                d=envelope(v['cursor']);c=d['data']['repository']['pullRequest']['reviewThreads']
                if modo=='mais2000':c['totalCount']=2001
                if modo=='booleano':c['nodes'][0]['isResolved']='false'
                if v['cursor']:
                    if modo=='incompleta':c['nodes']=[]
                    if modo=='duplicada':c['nodes'][0]['id']='t1'
                    if modo=='cursor':c['totalCount']=5;c['pageInfo']={'hasNextPage':True,'endCursor':'cursor1'}
                elif modo=='cursor':c['totalCount']=5
                return d
            with self.subTest(modo=modo),self.assertRaises(ValueError):self.ler(chamar)

    def test_limite_de_paginas_e_prazo_nao_produzem_zero_pendencias(self):
        chamadas=0
        def chamar(v):
            nonlocal chamadas
            chamadas+=1;d=envelope();c=d['data']['repository']['pullRequest']['reviewThreads']
            c.update(totalCount=2000,nodes=[{'id':str(chamadas),'isResolved':True,'isOutdated':False}],
                     pageInfo={'hasNextPage':True,'endCursor':str(chamadas)})
            return d
        with self.assertRaises(ValueError):self.ler(chamar)
        self.assertEqual(chamadas,20)
        with patch.object(p.time,'monotonic',side_effect=[0,61]):
            with self.assertRaises(ValueError):self.ler()

    def test_protecao_null_e_decisao_null_sao_estados_distintos(self):
        def chamar(v):
            d=envelope(v['cursor']);pr=d['data']['repository']['pullRequest']
            pr['reviewDecision']=None;pr['baseRef']['branchProtectionRule']=None;return d
        r=self.ler(chamar);self.assertIsNone(r['decisao_revisao'])
        self.assertEqual(r['protecao_classica'],{'estado':'ausente','checks':[]})

    def test_protecao_app_contagem_e_flags_invalidas_nao_viram_aceite(self):
        original=envelope()['data']['repository']['pullRequest']['baseRef']['branchProtectionRule']
        for campo,valor in [('requiredApprovingReviewCount',True),('requiresStatusChecks','false'),('requiredStatusChecks',None)]:
            d=copy.deepcopy(original);d[campo]=valor
            with self.assertRaises(ValueError):p.protecao(d)
        d=copy.deepcopy(original);d['requiredStatusChecks'][0]['app']['databaseId']=True
        with self.assertRaises(ValueError):p.protecao(d)


if __name__=='__main__':unittest.main()
