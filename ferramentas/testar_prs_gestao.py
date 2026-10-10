"""Projeção por projeto e contrato legado; sem inferência ou escrita GitHub."""
import json
from pathlib import Path
import sys
import tempfile
import http.client
import threading
from functools import partial
from http.server import ThreadingHTTPServer
import unittest
from unittest.mock import patch
RAIZ=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(RAIZ))
OFFICE=RAIZ/'office one' if (RAIZ/'office one').is_dir() else RAIZ
sys.path.insert(0,str(OFFICE))
import prs_gestao
import servidor
from funcionarios import id_projeto


class PRs(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.projetos=[]; self.chamadas=[]
        for nome in ('um','dois'):
            p=Path(self.tmp.name)/nome; (p/'.office').mkdir(parents=True)
            (p/'.office/projeto.json').write_text(json.dumps({'ativo':True,
                'kanban':{'repo':'owner/'+nome}}),encoding='utf-8')
            self.projetos.append(p)

    def api(self,caminho,**kw):
        self.chamadas.append((caminho,kw))
        repo=caminho.split('/pulls')[0].removeprefix('repos/')
        return [{'number':42,'state':'open','title':'<script>PR</script>',
            'html_url':f'https://github.com/{repo}/pull/42','head':{'sha':'a'*40,'ref':'feat/task'},
            'base':{'repo':{'full_name':repo}},'body':'SEGREDO','credentials':'SEGREDO'}]

    def test_selecao_canonica_paginada_sem_dados_privados_ou_aprovacao(self):
        sem=prs_gestao.vista(self.projetos,chamar=self.api)
        self.assertTrue(sem['erro']); self.assertEqual(self.chamadas,[])
        for p in self.projetos:
            r=prs_gestao.vista(self.projetos,id_projeto(p),self.api)
            self.assertFalse(r['erro']); self.assertEqual(r['repo'],'owner/'+p.name)
            self.assertEqual(r['prs'][0]['sha'],'a'*40)
            self.assertEqual(r['prs'][0]['revisao'],'')
            self.assertNotIn('SEGREDO',json.dumps(r)); self.assertNotIn(str(p),json.dumps(r))
        self.assertTrue(all(c[1]=={'paginar':True} for c in self.chamadas))

    def test_id_caminho_politica_invalida_e_falha_nao_caem_no_legado(self):
        for ident in ('../fora',str(self.projetos[0])):
            self.assertTrue(prs_gestao.vista(self.projetos,ident,self.api)['erro'])
        self.assertEqual(self.chamadas,[])
        r=prs_gestao.vista(self.projetos,id_projeto(self.projetos[0]),
                          lambda *a,**k: (_ for _ in ()).throw(ValueError('SEGREDO')))
        self.assertEqual(r['prs'],[]); self.assertNotIn('SEGREDO',json.dumps(r))
        (self.projetos[0]/'.office/projeto.json').write_text('{quebrado',encoding='utf-8')
        self.assertTrue(prs_gestao.vista(self.projetos,chamar=self.api)['erro'])
        self.assertFalse(prs_gestao.vista(self.projetos,id_projeto(self.projetos[1]),self.api)['erro'])

    def test_repositorio_sha_e_politica_divergentes_rejeitam_resposta(self):
        for chave in ('base','head','html_url'):
            def api(*a,**kw):
                prs=self.api(*a,**kw)
                prs[0][chave]={'repo':{'full_name':'outro/repo'}} if chave=='base' else {'sha':'invalido','ref':'x'} if chave=='head' else 'https://github.com/outro/repo/pull/42'
                return prs
            r=prs_gestao.vista([self.projetos[0]],chamar=api)
            self.assertTrue(r['erro']); self.assertEqual(r['prs'],[])
        def mudar(*a,**kw):
            prs=self.api(*a,**kw)
            (self.projetos[0]/'.office/projeto.json').write_text(json.dumps({'ativo':False}),encoding='utf-8')
            return prs
        self.assertTrue(prs_gestao.vista([self.projetos[0]],chamar=mudar)['erro'])

    def test_limite_de_exibicao_e_duplicata_nao_sao_ocultados(self):
        def muitos(*a,**kw):
            pr=self.api(*a,**kw)[0]
            return [{**pr,'number':n,'html_url':'https://github.com/owner/um/pull/'+str(n)} for n in range(1,1002)]
        r=prs_gestao.vista([self.projetos[0]],chamar=muitos)
        self.assertEqual(len(r['prs']),1000); self.assertTrue(r['limitado'])
        def duplicado(*a,**kw):
            pr=self.api(*a,**kw)[0]; return [pr,pr]
        r=prs_gestao.vista([self.projetos[0]],chamar=duplicado)
        self.assertTrue(r['erro']);self.assertEqual(r['prs'],[])

    def test_compatibilidade_sem_gestao_e_isolamento_do_cache_legado(self):
        vazio=Path(self.tmp.name)/'vazio'; vazio.mkdir()
        self.assertIsNone(prs_gestao.vista([vazio],chamar=self.api))
        with patch.object(servidor,'prs',return_value={'legado':True}) as legado, \
             patch.object(prs_gestao,'vista',return_value={'fonte':'gestao','prs':[]}):
            self.assertEqual(servidor.prs_projeto()['fonte'],'gestao'); legado.assert_not_called()
        with patch.object(servidor,'prs',return_value={'legado':True}) as legado, \
             patch.object(prs_gestao,'vista',return_value=None):
            self.assertEqual(servidor.prs_projeto(True),{'legado':True}); legado.assert_called_once_with(True)

    def test_http_seleciona_repo_sem_usar_prs_legados(self):
        import rede
        anterior=servidor.Handler.rede
        servidor.Handler.rede=rede.Rede(Path(self.tmp.name),False,False)
        srv=ThreadingHTTPServer(('127.0.0.1',0),partial(servidor.Handler,directory=str(OFFICE)))
        thread=threading.Thread(target=srv.serve_forever,daemon=True); thread.start()
        try:
            with patch.object(servidor,'cfg',return_value={'projetos':self.projetos},create=True), \
                 patch.object(servidor,'REPO_LOCAL',self.projetos[1],create=True), \
                 patch.object(servidor,'com_cota',side_effect=lambda d:d), \
                 patch.object(prs_gestao,'api',side_effect=self.api), \
                 patch.object(servidor,'prs',side_effect=AssertionError('Legado não deve ser consultado')):
                con=http.client.HTTPConnection('127.0.0.1',srv.server_address[1],timeout=10)
                try:
                    con.request('GET','/prs?forcar=1&projeto='+id_projeto(self.projetos[1]))
                    r=con.getresponse(); self.assertEqual(r.status,200)
                    self.assertEqual(json.loads(r.read())['repo'],'owner/dois')
                    con.request('GET','/prs?projeto=../fora')
                    r=con.getresponse(); self.assertEqual(json.loads(r.read())['prs'],[])
                finally: con.close()
        finally:
            srv.shutdown();srv.server_close();thread.join();servidor.Handler.rede=anterior


if __name__=='__main__': unittest.main()
