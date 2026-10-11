"""Contrato de revisão preliminar sem inferir autoria nem aprovação de gate."""
import sys,unittest,json,tempfile,copy
from unittest.mock import Mock,patch
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import revisao_preliminar as r
from gestao_projeto import validar

class Revisao(unittest.TestCase):
    def test_separacao_sem_autoria_bloqueia(self):
        cfg=validar({'ativo':True,'ciclo':{'ativo':True,'base':'origin/main'},'revisao':{'ativo':True,'separar_autor':True,'clouds_distintas':1,'revisores':[{'nome':'R','executor':{'console':'codex'}},{'nome':'R2','executor':{'console':'claude'}}]}})
        with self.assertRaisesRegex(ValueError,'Autoria'):r.revisores_sem_autoria(cfg)
    def test_contexto_e_achados(self):
        pr={'draft':True,'state':'open','head':{'sha':'a'*40},'changed_files':1,'title':'Mudança','body':'Aceite'}
        arquivos=[{'filename':'a.py','patch':'@@ -1 +1 @@\n-old\n+new','additions':1,'deletions':1}]
        ctx,linhas=r.contexto(pr,arquivos,[],[])
        self.assertFalse(ctx['aprova_gate']);self.assertEqual(linhas,{'a.py':{1}})
        achado={'veredito':'reprovado','achados':[{'prioridade':'P1','arquivo':'a.py','linha':2,'evidencia':'prova'}]}
        with self.assertRaisesRegex(ValueError,'fora'):r.conferir_achados(achado,linhas)
        arquivos[0]['additions']=2
        with self.assertRaisesRegex(ValueError,'truncado'):r.contexto(pr,arquivos,[],[])
    def test_parecer_excessivo_nao_publica_resumo_truncado(self):
        achado={'prioridade':'P1','arquivo':'a.py','linha':1,'evidencia':'x'*20001}
        with self.assertRaisesRegex(ValueError,'excessivo'):
            r.conferir_achados({'veredito':'reprovado','achados':[achado]},{'a.py':{1}})

    def test_pr_pronto_nao_adota_fluxo_preliminar(self):
        with self.assertRaisesRegex(ValueError,'rascunho'):r.contexto({'draft':False,'state':'open'},[],[],[])

class Fluxo(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.p=Path(self.tmp.name)
        self.cfg=validar({'ativo':True,'ciclo':{'ativo':True,'base':'origin/main'},'kanban':{'repo':'o/r'},
            'revisao':{'ativo':True,'separar_autor':False,'clouds_distintas':1,'revisores':[{'nome':'QA','executor':{'console':'codex'}}]}})
        self.pr={'number':7,'state':'open','draft':True,'head':{'sha':'a'*40},'base':{'repo':{'full_name':'o/r'}},
                 'changed_files':1,'title':'Regras','body':'Escopo','labels':[{'name':'merge-manual'}]}
        self.arquivos=[{'filename':'a.py','patch':'@@ -1 +1 @@\n-old\n+new','additions':1,'deletions':1}]
        self.fila={'encaminhamentos':[{'pr':7,'head':'a'*40,'acao':'revisar'}]};self.posts=[];self.k=Mock()
        self.k._paginas.side_effect=lambda url:copy.deepcopy(self.arquivos if url.endswith('/files') else self.posts)
        def api(url,method='GET',dados=None):
            if url=='user':return {'login':'usuario'}
            if method=='POST':
                c={'id':20,'body':dados['body'],'user':{'login':'usuario'}};self.posts.append(c);return c
            return copy.deepcopy(self.pr)
        self.k.chamar.side_effect=api
        self.calls=[];self.ceo='revisar';self.mudar=False;self.falhar=False
        def consulta(ex,prompt,norm,papel,nome=None):
            self.calls.append(papel)
            if papel=='ceo':return norm({'acao':self.ceo,'motivo':'decisão'})
            if self.falhar:raise RuntimeError('console indisponível')
            if self.mudar:self.pr['head']['sha']='b'*40
            return norm({'veredito':'aprovado','achados':[]})
        self.consulta=consulta
        for alvo,valor in [('gestao_projeto.carregar',self.cfg),('ciclo_gdd.documentos',[])]:
            p=patch(alvo,return_value=valor);p.start();self.addCleanup(p.stop)
    def executar(self):return r.encaminhar(self.p,self.cfg,[copy.deepcopy(self.pr)],self.fila,[],self.p,self.k,chamar=self.consulta)
    def test_contexto_explica_politica_sem_inventar_separacao(self):
        pacote,_=r.preparar(self.p,self.cfg,self.pr,[],self.k)
        self.assertEqual(pacote['politica_revisao'],{'ativo':True,'clouds_distintas':1,
            'separar_autor':False,'auditor_ativo':False})
        self.assertEqual(pacote['autoria'],'não comprovada')

    def test_publica_comentario_uma_vez_sem_mudar_rascunho(self):
        self.assertEqual(self.executar()['estado'],'publicado');self.assertIsNone(self.executar())
        self.assertEqual(self.calls,['ceo','revisor_preliminar']);self.assertEqual(len(self.posts),1)
        self.assertTrue(self.pr['draft']);self.assertIn('não aprova gates',self.posts[0]['body'])
        self.assertFalse(any('/statuses' in c.args[0] or '/reviews' in c.args[0] for c in self.k.chamar.call_args_list))
    def test_ceo_aguarda_sem_revisor(self):
        self.ceo='aguardar';self.assertIsNone(self.executar());self.assertIsNone(self.executar())
        self.assertEqual(self.calls,['ceo']);self.assertFalse(self.posts)
    def test_head_mudou_descarta_e_nao_publica(self):
        self.mudar=True
        with self.assertRaisesRegex(ValueError,'Contexto'):self.executar()
        self.assertFalse(self.posts)
    def test_falha_de_modelo_nao_repete_inferencia(self):
        self.falhar=True
        with self.assertRaises(RuntimeError):self.executar()
        self.assertIsNone(self.executar());self.assertEqual(len(self.calls),2);self.assertFalse(self.posts)
    def test_recupera_publicacao_confirmada_sem_repetir(self):
        self.executar();f=next((self.p/'revisoes_preliminares').glob('*.json'));d=json.loads(f.read_text(encoding='utf-8'))
        d['estado']='publicando';d.pop('comentario');f.write_text(json.dumps(d),encoding='utf-8')
        self.assertIsNone(self.executar());self.assertEqual(len(self.posts),1);self.assertEqual(len(self.calls),2)
        self.assertEqual(json.loads(f.read_text(encoding='utf-8'))['estado'],'publicado')

if __name__=='__main__':unittest.main()
