"""Revisão opcional por projeto: isolamento, validação e gates preservados."""
import copy,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import politica_painel as p
from gestao_projeto import validar,revisores,decidir_merge
from funcionarios import id_projeto

class RevisaoPainel(unittest.TestCase):
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
