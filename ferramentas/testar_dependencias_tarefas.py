"""Bloqueadores nativos/Markdown: fechamento cancelado, PR sem merge e mudanças não liberam tarefas."""
import copy
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from dependencias_tarefas import declaradas, verificar, conferir


class Dependencias(unittest.TestCase):
    def setUp(self):
        self.nativas = []; self.chamadas = []
        self.issue = {'number':1,'html_url':'https://github.com/owner/repo/issues/1',
                      'state':'closed','state_reason':'completed'}
        self.pr = {'number':1,'merged':True,'merge_commit_sha':'a'*40}
        def api(caminho):
            self.chamadas.append(caminho)
            return copy.deepcopy(self.pr if '/pulls/' in caminho else self.issue)
        self.k = SimpleNamespace(cfg={'repo':'owner/repo'}, bloqueadores=lambda _:copy.deepcopy(self.nativas), chamar=api)

    def test_formatos_e_checkbox_nao_sao_evidencia(self):
        corpo = '**Dependências:**\n- [x] #1\n- [ ] outro/repo#2; https://github.com/owner/repo/pull/3\n\n**Aceite:** Tudo passa'
        self.assertEqual(declaradas(corpo,'owner/repo'), [('owner/repo',1,'issues'),('outro/repo',2,'issues'),('owner/repo',3,'pull')])
        self.issue['state'] = 'open'
        with self.assertRaisesRegex(ValueError,'não concluída'): verificar(self.k,42,'**Dependências:** - [x] #1')

    def test_sem_campo_consulta_bloqueadores_nativos(self):
        self.nativas = [self.issue]
        relatorio = verificar(self.k,42,'**Aceite:** Testado')
        self.assertEqual(relatorio['itens'][0]['origens'],['github']); self.assertTrue(self.chamadas)
        self.assertNotIn('body',str(relatorio))

    def test_corpo_e_nativa_sao_unidas_sem_duplicar(self):
        self.nativas = [self.issue]
        relatorio = verificar(self.k,42,'**Dependências:** #1, owner/repo#1')
        self.assertEqual(len(relatorio['itens']),1); self.assertEqual(len(self.chamadas),1)
        self.assertEqual(relatorio['itens'][0]['origens'],['corpo','github'])

    def test_cancelada_e_motivo_ausente_bloqueiam(self):
        for motivo in ('not_planned',None):
            self.issue['state_reason']=motivo
            with self.subTest(motivo=motivo),self.assertRaises(ValueError): verificar(self.k,42,'**Dependências:** #1')

    def test_pr_fechado_sem_merge_e_sha_invalido_bloqueiam(self):
        self.issue['pull_request'] = {'url':'ignored'}
        for merged, sha in ((False,'a'*40),(None,'a'*40),(True,'curto')):
            self.pr.update(merged=merged,merge_commit_sha=sha)
            with self.subTest(merged=merged,sha=sha),self.assertRaises(ValueError): verificar(self.k,42,'**Dependências:** #1')
        self.pr.update(merged=True,merge_commit_sha='a'*40)
        self.assertEqual(verificar(self.k,42,'**Dependências:** #1')['itens'][0]['merge_sha'],'a'*40)

    def test_falha_de_rede_nao_significa_nenhuma(self):
        def falha(_): raise ValueError('offline')
        self.k.bloqueadores=falha
        with self.assertRaises(ValueError): verificar(self.k,42,'**Dependências:** nenhuma')

    def test_reabertura_ou_lista_mudando_invalidam_preparo(self):
        anterior=verificar(self.k,42,'**Dependências:** #1')
        self.issue['state']='open'
        with self.assertRaises(ValueError): conferir(self.k,42,'**Dependências:** #1',anterior)
        self.issue['state']='closed'
        with self.assertRaisesRegex(ValueError,'mudaram'): conferir(self.k,42,'**Dependências:** nenhuma',anterior)

    def test_identidade_e_autodependencia(self):
        self.issue['number']=2
        with self.assertRaises(ValueError): verificar(self.k,42,'**Dependências:** #1')
        self.issue['number']=1; self.issue['html_url']='https://github.com/outro/repo/issues/1'
        with self.assertRaisesRegex(ValueError,'transferida'): verificar(self.k,42,'**Dependências:** #1')
        with self.assertRaisesRegex(ValueError,'si mesmo'): verificar(self.k,42,'**Dependências:** #42')

    def test_urls_arbitrarias_prosa_e_campo_vazio_rejeitados(self):
        for campo in ('', 'depois da modelagem', 'http://127.0.0.1/issues/1', 'https://github.com/owner/repo/issues/1?x=2', '#1 #2'):
            with self.subTest(campo=campo),self.assertRaises(ValueError): declaradas('**Dependências:** '+campo+'\n**Aceite:** Testado','owner/repo')
        with self.assertRaises(ValueError): declaradas('**Dependências:** #1\n\n**Dependências:** #2','owner/repo')


if __name__=='__main__': unittest.main()
