"""Revisão opcional por projeto: isolamento, validação e gates preservados."""
import copy,json,sys,tempfile,unittest
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import politica_painel as p
from gestao_projeto import validar,revisores,decidir_merge
from funcionarios import id_projeto

class RevisaoPainel(unittest.TestCase):
    def test_continuo_exige_metas_e_preserva_demais_opcoes(self):
        with self.assertRaises(ValueError):p.atualizar_ciclo(self.raiz,self.hash,{'duracao_min':120,'continuo':True})
        self.assertEqual(self.arq.read_bytes(),self.bruto)
        cfg=copy.deepcopy(self.cfg);cfg['metas']['ativo']=True;cfg['ciclo'].update(ativo=True,base='origin/main')
        self.arq.write_text(json.dumps(cfg),encoding='utf-8');versao=p.snapshot(self.raiz)[1]
        p.atualizar_ciclo(self.raiz,versao,{'duracao_min':120,'continuo':True})
        novo=p.snapshot(self.raiz)[0];self.assertTrue(novo['ciclo']['continuo'])
        for k in set(cfg)-{'ciclo'}:self.assertEqual(novo[k],cfg[k])
        self.assertEqual(novo['ciclo']['max_cartoes'],2)

    def test_api_pausa_exige_pc_versao_e_sessao_exata(self):
        dados=self.raiz/'dados';dados.mkdir();sessao='a'*32
        (dados/'ciclo.json').write_text(json.dumps({'id':sessao,'estado':'aguardando','pausa_configuravel':True}))
        pedido={'projeto_id':id_projeto(self.raiz),'versao':self.hash,'acao':'pausar','sessao':sessao}
        with patch('gestao_cli.pasta_dados',return_value=dados),patch('ciclo_gdd.pasta_dados',return_value=dados):
            self.assertEqual(p.api_ciclo([self.raiz],pedido,{'permissao':'ver'})[0],403)
            self.assertEqual(p.api_ciclo([] ,pedido,{'permissao':'pc'})[0],400)
            self.assertEqual(p.api_ciclo([self.raiz],{**pedido,'versao':'0'*64},{'permissao':'pc'})[0],409)
            self.assertEqual(p.api_ciclo([self.raiz],{**pedido,'sessao':'b'*32},{'permissao':'pc'})[0],400)
            self.assertFalse((dados/'ciclo.pausa.json').exists())
            codigo,r=p.api_ciclo([self.raiz],pedido,{'permissao':'pc'})
            self.assertEqual(codigo,200);self.assertEqual(r['estado'],'pausa_solicitada')
            self.assertEqual(json.loads((dados/'ciclo.pausa.json').read_text())['id'],sessao)
        self.assertEqual(self.arq.read_bytes(),self.bruto)
    def test_ciclo_antigo_protegido_e_novo_preserva_prazo(self):
        dados=self.raiz/'dados';dados.mkdir();arq=dados/'ciclo.json'
        r={'estado':'implementando','limite':123};arq.write_text(json.dumps(r))
        with patch('gestao_cli.pasta_dados',return_value=dados):
            with self.assertRaisesRegex(p.Conflito,'controlador anterior'):
                p.atualizar_ciclo(self.raiz,self.hash,{'duracao_min':60})
            self.assertEqual(self.arq.read_bytes(),self.bruto)
            r['duracao_futura_configuravel']=True;arq.write_text(json.dumps(r));antes=arq.read_bytes()
            p.atualizar_ciclo(self.raiz,self.hash,{'duracao_min':60})
            self.assertEqual(arq.read_bytes(),antes)
    def test_revisores_suspensos_nao_contam_e_api_explica(self):
        cfg=copy.deepcopy(self.cfg);cfg['revisao']['ativo']=False
        cfg['revisao']['revisores'][1]['ativo']=False
        self.arq.write_text(json.dumps(cfg),encoding='utf-8');antes=self.arq.read_bytes()
        dados={'projeto_id':id_projeto(self.raiz),'versao':p.snapshot(self.raiz)[1],
               'revisao':{'ativo':True,'clouds_distintas':2,'separar_autor':False}}
        codigo,r=p.api_revisao([self.raiz],dados,{'permissao':'pc'})
        self.assertEqual(codigo,400);self.assertIn('1 habilitado',r['erro'])
        self.assertEqual(antes,self.arq.read_bytes())
        dados['revisao']['clouds_distintas']=1
        self.assertEqual(p.api_revisao([self.raiz],dados,{'permissao':'pc'})[0],200)
    def test_correcoes_configuraveis_exigem_ciclo_pausado(self):
        dados=self.raiz/'dados';dados.mkdir();estado=dados/'ciclo.json'
        estado.write_text(json.dumps({'estado':'implementando'}))
        with patch('gestao_cli.pasta_dados',return_value=dados):
            with self.assertRaisesRegex(p.Conflito,'Pause'):
                p.atualizar_ciclo(self.raiz,self.hash,{'max_correcoes_revisao':1})
            self.assertEqual(self.arq.read_bytes(),self.bruto)
            estado.write_text(json.dumps({'estado':'pausado'}))
            resultado=p.atualizar_ciclo(self.raiz,self.hash,{'max_correcoes_revisao':1})
            cfg,sha,_=p.snapshot(self.raiz);self.assertEqual(cfg['ciclo']['max_correcoes_revisao'],1)
            for n in (-1,3,True,1.5):
                with self.assertRaises(ValueError):p.atualizar_ciclo(self.raiz,sha,{'max_correcoes_revisao':n})

    def test_duracao_preserva_politica_e_sessao(self):
        ciclo=self.raiz/'ciclo.json';ciclo.write_text('{"limite":123}')
        resultado=p.atualizar_ciclo(self.raiz,self.hash,{'duracao_min':60})
        cfg,sha,_=p.snapshot(self.raiz)
        self.assertEqual(cfg['ciclo']['duracao_min'],60)
        self.assertEqual(ciclo.read_text(),'{"limite":123}')
        for k in set(cfg)-{'ciclo'}:self.assertEqual(cfg[k],self.cfg[k])
        self.assertEqual(sha,resultado['versao'])
        for n in (0,241,True,1.5):
            with self.assertRaises(ValueError):p.atualizar_ciclo(self.raiz,sha,{'duracao_min':n})
        with self.assertRaises(p.Conflito):p.atualizar_ciclo(self.raiz,self.hash,{'duracao_min':90})
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.raiz=Path(self.tmp.name);(self.raiz/'.office').mkdir()
        self.cfg=validar({'ativo':True,'merge':{'modo':'automatico','checks':['CI']},
            'revisao':{'ativo':True,'revisores':[{'nome':'A','executor':{'console':'claude'}},
              {'nome':'B','executor':{'console':'gemini'}}]}})
        self.arq=self.raiz/'.office/projeto.json';self.arq.write_text(json.dumps(self.cfg),encoding='utf-8')
        self.bruto=self.arq.read_bytes();self.hash=p.snapshot(self.raiz)[1]
        self.opcoes={k:self.cfg['revisao'][k] for k in ('ativo','clouds_distintas','separar_autor')}
    def test_desativa_preserva_revisores_checks_backup_e_reativa(self):
        resultado=p.atualizar_revisao(self.raiz,self.hash,{**self.opcoes,'ativo':False})
        cfg,sha,_=p.snapshot(self.raiz)
        for k in set(cfg)-{'revisao'}:self.assertEqual(cfg[k],self.cfg[k])
        self.assertEqual(cfg['revisao']['revisores'],self.cfg['revisao']['revisores'])
        self.assertEqual(revisores(cfg,{'console':'codex'}),[])
        self.assertFalse(decidir_merge(cfg,{'CI':'failure'}))
        self.assertTrue(decidir_merge(cfg,{'CI':'success'}))
        self.assertEqual((self.raiz/'.office/historico-politica'/f'{self.hash}.json').read_bytes(),self.bruto)
        self.assertEqual(sha,resultado['versao'])
        p.atualizar_revisao(self.raiz,sha,self.opcoes)
        self.assertEqual(p.snapshot(self.raiz)[0],self.cfg)
        self.assertFalse(decidir_merge(self.cfg,{'CI':'success'}))
    def test_configura_um_fornecedor_e_autor_sem_tocar_outro_projeto(self):
        outro=Path(self.tmp.name)/'outro';outro.mkdir()
        p.atualizar_revisao(self.raiz,self.hash,{'ativo':True,'clouds_distintas':1,'separar_autor':False})
        self.assertEqual(len(revisores(p.snapshot(self.raiz)[0],{'console':'claude'})),1)
        self.assertFalse(p.snapshot(outro)[0]['revisao']['ativo'])
    def test_invalido_conflito_noop_sem_mutacao(self):
        self.assertFalse(p.atualizar_revisao(self.raiz,self.hash,self.opcoes)['alterado'])
        for mudanca in ({'ativo':'false'},{'clouds_distintas':0},{'clouds_distintas':True},
                       {'clouds_distintas':3},{'revisores':[]},{'separar_autor':1}):
            with self.subTest(mudanca=mudanca),self.assertRaises(ValueError):
                p.atualizar_revisao(self.raiz,self.hash,{**self.opcoes,**mudanca})
            self.assertEqual(self.arq.read_bytes(),self.bruto)
        with self.assertRaises(p.Conflito):p.atualizar_revisao(self.raiz,'a'*64,self.opcoes)
    def test_auditor_ativo_nao_desligado_silenciosamente(self):
        cfg=copy.deepcopy(self.cfg);cfg['auditor']['ativo']=True
        self.arq.write_text(json.dumps(cfg),encoding='utf-8');antes=self.arq.read_bytes()
        with self.assertRaisesRegex(ValueError,'Auditor'):
            p.atualizar_revisao(self.raiz,p.snapshot(self.raiz)[1],{**self.opcoes,'ativo':False})
        self.assertEqual(self.arq.read_bytes(),antes)
    def test_api_pc_projeto_versao_campos(self):
        dados={'projeto_id':id_projeto(self.raiz),'versao':self.hash,'revisao':{**self.opcoes,'ativo':False}}
        self.assertEqual(p.api_revisao([self.raiz],dados,{'permissao':'celular'})[0],403)
        self.assertEqual(p.api_revisao([],dados,{'permissao':'pc'})[0],400)
        self.assertEqual(p.api_revisao([self.raiz],{**dados,'merge':{}},{'permissao':'pc'})[0],400)
        self.assertEqual(p.api_revisao([self.raiz],dados,{'permissao':'pc'})[0],200)
        self.assertEqual(p.api_revisao([self.raiz],dados,{'permissao':'pc'})[0],409)

if __name__=='__main__':unittest.main()
