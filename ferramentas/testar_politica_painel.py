"""Política única: alteração explícita, concorrência, preservação e isolamento."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import politica_painel as p
from gestao_projeto import validar,carregar
from funcionarios import id_projeto


class PoliticaPainel(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.raiz=Path(self.tmp.name);(self.raiz/'.office').mkdir()
        self.cfg=validar({'ativo':True,'merge':{'modo':'automatico','checks':['CI']},
                         'equipes':[{'nome':'Dev','especialidade':'Código','executor':{'console':'claude'}}]})
        self.arq=self.raiz/'.office/projeto.json'
        self.arq.write_text(json.dumps(self.cfg),encoding='utf-8')
        self.original=self.arq.read_bytes();self.hash=p.snapshot(self.raiz)[1]
        self.alt={'ceo':{'console':'codex','modelo':'','execucao':'cloud'},
                  'diretor':{'console':'gemini','modelo':'','execucao':'cloud'},
                  'equipes':[{'nome':'Dev','executor':{'console':'opencode','modelo':'opencode/free','cloud':'nvidia','execucao':'cloud'}}]}

    def test_zen_sem_fornecedor_salva_papeis_sem_inventar_identidade(self):
        import copy
        alt=copy.deepcopy(self.alt)
        zen={'console':'opencode','modelo':'opencode/space-bunny-free','execucao':'cloud'}
        alt['ceo']=zen;alt['diretor']=zen;alt['equipes'][0]['executor']=zen
        p.atualizar(self.raiz,self.hash,alt)
        cfg=p.snapshot(self.raiz)[0]
        for item in (cfg['ceo'],cfg['diretor'],cfg['equipes'][0]['executor']):
            self.assertNotIn('cloud',item)
        self.assertEqual(cfg['merge'],self.cfg['merge'])

    def test_salva_preserva_merge_regras_rotas_e_backup_exato(self):
        resultado=p.atualizar(self.raiz,self.hash,self.alt)
        novo=carregar(self.raiz)
        for k in set(self.cfg)-{'ceo','diretor','equipes'}:self.assertEqual(novo[k],self.cfg[k])
        self.assertEqual(novo['equipes'][0]['especialidade'],'Código')
        self.assertEqual(novo['ceo']['console'],'codex')
        self.assertEqual(novo['ceo']['autonomia'],'limites_aprovados')
        self.assertEqual((self.raiz/'.office/historico-politica'/f'{self.hash}.json').read_bytes(),self.original)
        self.assertEqual(p.snapshot(self.raiz)[1],resultado['versao'])
        self.assertFalse((self.raiz/'.office/politica.edicao.lock').exists())

    def test_hash_antigo_e_lock_rejeitados_sem_gravar(self):
        self.arq.write_bytes(self.original+b'\n')
        with self.assertRaises(p.Conflito):p.atualizar(self.raiz,self.hash,self.alt)
        self.arq.write_bytes(self.original)
        lock=self.raiz/'.office/politica.edicao.lock';lock.write_text('outro')
        with self.assertRaises(p.Conflito):p.atualizar(self.raiz,self.hash,self.alt)
        self.assertEqual(lock.read_text(),'outro');self.assertEqual(self.arq.read_bytes(),self.original)

    def test_dados_invalidos_nao_alteram_politica(self):
        for mudanca in ({**self.alt,'merge':{'modo':'manual'}}, {**self.alt,'ceo':{'console':'local','modelo':''}},
                        {**self.alt,'ceo':{'console':'claude','modelo':'','execucao':'local'}},
                        {**self.alt,'equipes':[]},
                        {**self.alt,'equipes':[{'nome':'Outra','executor':{'console':'claude'}}]},
                        {**self.alt,'diretor':{'console':'opencode','modelo':'opencode/free','cloud':''}},
                        {**self.alt,'equipes':[{'nome':'Dev','executor':{'console':'codex','execucao':'local'}}]}):
            with self.subTest(mudanca=mudanca),self.assertRaises(ValueError):p.atualizar(self.raiz,self.hash,mudanca)
            self.assertEqual(self.arq.read_bytes(),self.original)

    def test_falha_de_replace_preserva_original_e_remove_temporario(self):
        with patch('politica_painel.os.replace',side_effect=OSError('erro')):
            with self.assertRaises(OSError):p.atualizar(self.raiz,self.hash,self.alt)
        self.assertEqual(self.arq.read_bytes(),self.original)
        self.assertFalse(list((self.raiz/'.office').glob('*.tmp')))
        self.assertFalse((self.raiz/'.office/politica.edicao.lock').exists())

    def test_api_pc_projeto_registrado_e_conflito(self):
        d={'projeto_id':id_projeto(self.raiz),'versao':self.hash,'executores':copy.deepcopy(self.alt)}
        self.assertEqual(p.api_atualizar([self.raiz],d,{'permissao':'ver'})[0],403)
        self.assertEqual(p.api_atualizar([] ,d,{'permissao':'pc'})[0],400)
        self.assertEqual(p.api_atualizar([self.raiz],{**d,'projeto_id':str(self.raiz)},{'permissao':'pc'})[0],400)
        self.assertEqual(self.arq.read_bytes(),self.original)
        self.assertEqual(p.api_atualizar([self.raiz],d,{'permissao':'pc'})[0],200)
        self.assertEqual(p.api_atualizar([self.raiz],d,{'permissao':'pc'})[0],409)


if __name__=='__main__':unittest.main()
