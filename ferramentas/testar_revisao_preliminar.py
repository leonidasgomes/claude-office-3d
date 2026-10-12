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

    def legado(self,estado='publicando',**mudancas):
        from correcoes_prs import assinatura
        identidade={'repo':'o/r','pr':7,'sha':'a'*40,'politica':assinatura(self.cfg),'fontes':[]}
        identidade.update(mudancas)
        ident=assinatura(identidade)
        recibo={'identidade':identidade,'estado':estado,'corpo':'<!-- office-revisao-preliminar:'+ident+' -->\nParecer antigo',
                'publicador':'usuario','ceo':{'acao':'aguardar','motivo':'política antiga'}}
        if estado=='publicado':recibo['comentario']=19
        pasta=self.p/'revisoes_preliminares';pasta.mkdir(exist_ok=True)
        f=pasta/(ident+'.json');f.write_text(json.dumps(recibo),encoding='utf-8')
        return f,recibo

    def test_migracao_reconcilia_publicado_sem_repetir_apos_reinicio(self):
        f,antigo=self.legado()
        self.posts.append({'id':19,'body':antigo['corpo'],'user':{'login':'usuario'}})
        for _ in range(3):self.assertIsNone(self.executar())
        salvo=json.loads(f.read_text(encoding='utf-8'))
        self.assertEqual(salvo,{**antigo,'estado':'publicado','comentario':19})
        self.assertEqual(self.calls,[]);self.assertEqual(len(self.posts),1)
        self.assertEqual(list(f.parent.glob('*.json')),[f])
        self.assertFalse(any(len(c.args)>1 and c.args[1]=='POST' for c in self.k.chamar.call_args_list))

    def test_migracao_publicacao_nao_encontrada_nao_autoriza_repeticao(self):
        f,_=self.legado();antes=f.read_bytes()
        for _ in range(2):self.assertIsNone(self.executar())
        self.assertEqual(f.read_bytes(),antes);self.assertEqual(self.calls,[]);self.assertEqual(self.posts,[])
        self.assertEqual(list(f.parent.glob('*.json')),[f])

    def test_migracao_falha_de_consulta_preserva_incerteza(self):
        f,_=self.legado();antes=f.read_bytes()
        def paginas(url):
            if url.endswith('/comments'):raise RuntimeError('consulta indisponível')
            return copy.deepcopy(self.arquivos)
        self.k._paginas.side_effect=paginas
        with self.assertRaisesRegex(RuntimeError,'consulta indisponível'):self.executar()
        self.assertEqual(f.read_bytes(),antes);self.assertEqual(self.calls,[]);self.assertEqual(self.posts,[])
        self.assertEqual(list(f.parent.glob('*.json')),[f])

    def test_migracao_comentarios_ambiguos_ou_invalidos_nao_confirmam(self):
        f,antigo=self.legado();antes=f.read_bytes()
        comentario={'id':19,'body':antigo['corpo'],'user':{'login':'usuario'}}
        casos=[[comentario,{**comentario,'id':20}], [{**comentario,'id':True}],
               [{**comentario,'id':0}], [{**comentario,'body':'outro corpo'}],
               [{**comentario,'user':{'login':'outro'}}]]
        for comentarios in casos:
            with self.subTest(comentarios=comentarios):
                self.posts[:]=comentarios
                self.assertIsNone(self.executar())
                self.assertEqual(f.read_bytes(),antes);self.assertEqual(self.calls,[])
                self.assertEqual(self.posts,comentarios);self.assertEqual(list(f.parent.glob('*.json')),[f])

    def test_migracao_publicado_antigo_nao_repete(self):
        f,_=self.legado('publicado');antes=f.read_bytes()
        self.assertIsNone(self.executar());self.assertIsNone(self.executar())
        self.assertEqual(f.read_bytes(),antes);self.assertEqual(self.calls,[]);self.assertEqual(self.posts,[])

    def test_migracao_espera_antiga_exige_nova_decisao_sem_aprovar(self):
        f,_=self.legado('aguardando');antes=f.read_bytes();self.ceo='aguardar'
        self.assertIsNone(self.executar());self.assertIsNone(self.executar())
        self.assertEqual(self.calls,['ceo']);self.assertEqual(self.posts,[]);self.assertEqual(f.read_bytes(),antes)
        novos=[x for x in f.parent.glob('*.json') if x!=f];self.assertEqual(len(novos),1)
        novo=json.loads(novos[0].read_text(encoding='utf-8'))
        self.assertEqual(novo['identidade']['contrato'],2);self.assertEqual(novo['estado'],'aguardando')

    def test_migracao_espera_antiga_permite_nova_revisao_apenas_uma_vez(self):
        f,_=self.legado('aguardando');antes=f.read_bytes()
        self.assertEqual(self.executar()['estado'],'publicado');self.assertIsNone(self.executar())
        self.assertEqual(self.calls,['ceo','revisor_preliminar']);self.assertEqual(len(self.posts),1)
        self.assertEqual(f.read_bytes(),antes)

    def test_migracao_nao_confunde_repo_pr_sha_politica_ou_fontes(self):
        for mudanca in ({'repo':'outra/repo'},{'pr':8},{'sha':'b'*40},{'politica':'c'*64},
                         {'fontes':[{'caminho':'GDD.md','sha256':'d'*64}]}):self.legado(**mudanca)
        self.assertEqual(self.executar()['estado'],'publicado');self.assertIsNone(self.executar())
        self.assertEqual(self.calls,['ceo','revisor_preliminar']);self.assertEqual(len(self.posts),1)

    def test_migracao_identidade_adulterada_bloqueia(self):
        f,antigo=self.legado();antigo['identidade']['pr']=8
        f.write_text(json.dumps(antigo),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'Identidade'):self.executar()
        self.assertEqual(self.calls,[]);self.assertEqual(self.posts,[])

    def test_migracao_reconcilia_legado_mesmo_com_recibo_v2_existente(self):
        self.ceo='aguardar';self.executar();self.calls.clear()
        f,antigo=self.legado()
        self.posts.append({'id':19,'body':antigo['corpo'],'user':{'login':'usuario'}})
        self.assertIsNone(self.executar());self.assertEqual(self.calls,[]);self.assertEqual(len(self.posts),1)
        self.assertEqual(json.loads(f.read_text(encoding='utf-8'))['estado'],'publicado')

if __name__=='__main__':unittest.main()
