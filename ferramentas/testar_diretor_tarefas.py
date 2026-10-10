"""Diretor planeja a partir do board e das reservas; não despacha, infere ou modifica GitHub."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import gestao_cli
import testar_gestao_kanban as fixtures
from providers_console import PROVIDERS


class Diretor(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.KanbanGestao(); self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.k=self.fixture.kanban(); self.raiz=self.fixture.raiz
        self.patch=patch.object(gestao_cli,'RAIZ',self.raiz/'app'); self.patch.start(); self.addCleanup(self.patch.stop)
        self.cli=patch.object(gestao_cli,'selecionar',return_value=(PROVIDERS['codex'],'codex')); self.cli.start(); self.addCleanup(self.cli.stop)

    def test_diagnostico_e_limite_nao_criam_reserva(self):
        dados=gestao_cli.planejar(self.raiz,kanban=self.k)
        self.assertTrue(dados['apenas_diagnostico']); self.assertTrue(dados['cartoes'][0]['preparavel'])
        self.assertEqual(dados['cartoes'][0]['pacote']['dependencias']['itens'],[])
        self.assertFalse((gestao_cli.pasta_dados(self.raiz)/'tarefas.db').exists())
        self.assertFalse(any(c[1]!='GET' for c in self.fixture.chamadas))

    def test_reserva_bloqueia_e_nao_e_roubada(self):
        banco=gestao_cli.pasta_dados(self.raiz)/'tarefas.db'
        c=gestao_cli.Controle(banco)
        token=c.reservar('owner/jogo','42','Dev','codex',{'objetivo':'x','aceite':'y'},True)
        dados=gestao_cli.planejar(self.raiz,kanban=self.k)
        self.assertFalse(dados['cartoes'][0]['preparavel']); self.assertIn('reserva',dados['cartoes'][0]['bloqueio'])
        self.assertEqual(c.listar('owner/jogo')[0]['token'],token)
        self.assertNotIn(token,str(dados))

    def test_bloqueio_por_dependencia_e_cli_indisponivel(self):
        self.k.bloqueadores=lambda _:(_ for _ in ()).throw(ValueError('Dependências indisponíveis'))
        dados=gestao_cli.planejar(self.raiz,kanban=self.k)
        self.assertFalse(dados['cartoes'][0]['preparavel']); self.assertIn('Dependências',dados['cartoes'][0]['bloqueio'])
        with patch.object(gestao_cli,'selecionar',side_effect=ValueError('CLI ausente')):
            self.assertIn('CLI ausente',gestao_cli.planejar(self.raiz,kanban=self.k)['cartoes'][0]['bloqueio'])

    def prioridades(self):
        cfg=self.fixture.cfg
        cfg['kanban']['prioridades']=['P0','P1','P2']
        (self.raiz/'.office/projeto.json').write_text(json.dumps(cfg),encoding='utf-8')
        original=self.k.chamar
        def api(caminho,*args):
            if caminho.endswith('/issues/43') or caminho.endswith('/issues/44'):
                return original(caminho[:-2]+'42',*args)
            dados=original(caminho,*args)
            if '/fields?' in caminho:
                return dados+[{'id':3,'name':'Prioridade'}]
            if '/items?' in caminho:
                itens=[]
                for numero,prioridade in ((42,'P2'),(43,'P0'),(44,'Desconhecida')):
                    item=copy.deepcopy(dados[0]); item['id']=numero
                    item['content']['html_url']='https://github.com/owner/jogo/issues/'+str(numero)
                    item['fields'].append({'id':3,'value':{'name':{'raw':prioridade}}})
                    itens.append(item)
                return itens
            return dados
        self.k.chamar=api

    def test_ordem_e_bloqueio_vem_da_politica_e_do_board(self):
        self.prioridades()
        dados=gestao_cli.planejar(self.raiz,kanban=self.k)
        self.assertEqual([c['numero'] for c in dados['cartoes']],[43,42,44])
        self.assertEqual([c['prioridade'] for c in dados['cartoes']],['P0','P2','Desconhecida'])
        self.assertTrue(dados['cartoes'][0]['preparavel'])
        self.assertFalse(dados['cartoes'][2]['preparavel'])
        self.assertIn('Prioridade',dados['cartoes'][2]['bloqueio'])
        self.assertEqual(dados['ordem'],{'criterio':'prioridade','prioridades':['P0','P1','P2']})
        self.assertFalse(any(c[1]!='GET' for c in self.fixture.chamadas))
        self.assertFalse((gestao_cli.pasta_dados(self.raiz)/'tarefas.db').exists())

    def test_cursor_de_prioridade_nao_pula_issue_de_numero_menor(self):
        self.prioridades()
        primeira=gestao_cli.planejar(self.raiz,1,kanban=self.k)
        self.assertEqual(primeira['proximo_cartao'],43)
        segunda=gestao_cli.planejar(self.raiz,1,kanban=self.k,apos_cartao=43)
        self.assertEqual(segunda['cartoes'][0]['numero'],42)
        with self.assertRaisesRegex(ValueError,'reinicie'):
            gestao_cli.planejar(self.raiz,1,kanban=self.k,apos_cartao=99)

    def test_limite_explicito_e_restantes(self):
        original=self.k.chamar
        def api(caminho,*args):
            if caminho.endswith('/issues/43'):
                return original(caminho.removesuffix('/43')+'/42',*args)
            itens=original(caminho,*args)
            if '/items?' in caminho:
                segundo=copy.deepcopy(itens[0]); segundo['id']=9
                segundo['content']['html_url']='https://github.com/owner/jogo/issues/43'
                return itens+[segundo]
            return itens
        self.k.chamar=api
        dados=gestao_cli.planejar(self.raiz,1,kanban=self.k)
        self.assertEqual((len(dados['cartoes']),dados['nao_avaliados']),(1,1))
        self.assertEqual(dados['proximo_cartao'],42)
        segundo=gestao_cli.planejar(self.raiz,1,kanban=self.k,apos_cartao=42)
        self.assertEqual(segundo['cartoes'][0]['numero'],43); self.assertIsNone(segundo['proximo_cartao'])
        for limite in (0,21,True):
            with self.assertRaises(ValueError): gestao_cli.planejar(self.raiz,limite,kanban=self.k)


if __name__=='__main__': unittest.main()
