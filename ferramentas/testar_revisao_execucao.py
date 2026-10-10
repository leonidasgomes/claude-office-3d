"""Git real temporário, consoles simulados e relatórios por SHA; não publica no GitHub."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import gestao_cli
import revisao_execucao as re
from revisao_cruzada import conferir


class Execucao(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.raiz=Path(self.tmp.name); self.repo=self.raiz/'repo'; self.repo.mkdir()
        def git(*args):
            return subprocess.run(['git','-C',str(self.repo),'-c','user.name=Teste','-c','user.email=teste@example.com',*args],
                                  capture_output=True,text=True,check=True).stdout.strip()
        self.git=git; git('init','-b','feat/revisao')
        (self.repo/'.office').mkdir()
        self.cfg={'ativo':True,'equipes':[{'nome':'Dev','especialidade':'Código','executor':{'console':'gemini'}}],
                  'revisao':{'ativo':True,'clouds_distintas':2,'revisores':[
                      {'nome':'QA Claude','executor':{'console':'claude'}},
                      {'nome':'QA Codex','executor':{'console':'codex'}}]}}
        (self.repo/'.office/projeto.json').write_text(json.dumps(self.cfg),encoding='utf-8')
        (self.repo/'CLAUDE.md').write_text('Preservar o contrato e testar o aceite.',encoding='utf-8')
        (self.repo/'codigo.py').write_text('valor = 1\n',encoding='utf-8')
        git('add','.'); git('commit','-m','Base'); self.base=git('rev-parse','HEAD')
        (self.repo/'codigo.py').write_text('valor = 2\n',encoding='utf-8')
        git('add','.'); git('commit','-m','Mudança')
        self.trabalho=self.raiz/'trabalho'
        git('worktree','add','-b','feat/trabalho',str(self.trabalho))
        def git_trabalho(*args):
            return subprocess.run(['git','-C',str(self.trabalho),'-c','user.name=Teste','-c','user.email=teste@example.com',*args],
                                  capture_output=True,text=True,check=True).stdout.strip()
        self.git=git_trabalho
        self.isolar=patch.object(gestao_cli,'RAIZ',self.raiz/'instalacao'); self.isolar.start(); self.addCleanup(self.isolar.stop)

    def test_relatorio_commit_e_prompts_independentes(self):
        chamadas=[]
        def chamar(executor,prompt):
            chamadas.append((executor,prompt)); return {'veredito':'aprovado','achados':[]}
        r=re.executar(self.repo,self.trabalho,self.base,'Dev','valor deve ser 2',chamar)
        self.assertTrue(conferir(re.gestao_projeto.carregar(self.repo),r,self.git('rev-parse','HEAD')))
        self.assertEqual(chamadas[0][1],chamadas[1][1])
        self.assertNotEqual(chamadas[0][0],chamadas[1][0])
        salvo=gestao_cli.pasta_dados(self.repo)/'revisoes'/(r['sha']+'.json')
        self.assertEqual(json.loads(salvo.read_text(encoding='utf-8')),r)
        self.assertEqual(self.git('status','--porcelain'),'')

    def test_achado_linha_inexistente_bloqueia(self):
        r=re.executar(self.repo,self.trabalho,self.base,'Dev','Aceite',lambda *_: {'veredito':'aprovado','achados':[
            {'prioridade':'P2','arquivo':'codigo.py','linha':999,'evidencia':'inventada'}]})
        self.assertFalse(r['aprovado']); self.assertTrue(all('erro' in x for x in r['revisoes']))

    def test_commit_mudando_descarta_relatorio(self):
        def chamar(*_):
            atual=(self.trabalho/'codigo.py').read_text(encoding='utf-8')
            (self.trabalho/'codigo.py').write_text(atual+'# concorrência\n',encoding='utf-8')
            self.git('add','.'); self.git('commit','-m','Concorrência')
            return {'veredito':'aprovado','achados':[]}
        with self.assertRaises(ValueError): re.executar(self.repo,self.trabalho,self.base,'Dev','Aceite',chamar)
        self.assertFalse((gestao_cli.pasta_dados(self.repo)/'revisoes').exists())

    def test_revisores_separam_cloud_do_funcionario_e_nao_executor_padrao(self):
        import funcionarios
        self.cfg['equipes'][0]['executor']={'console':'claude'}
        (self.repo/'.office/projeto.json').write_text(json.dumps(self.cfg),encoding='utf-8')
        (self.trabalho/'.office/projeto.json').write_text(json.dumps(self.cfg),encoding='utf-8')
        self.git('add','.'); self.git('commit','-m','Equipe padrão Claude')
        (self.repo/'.git/info/exclude').write_text('.office/funcionarios.db*\n',encoding='utf-8')
        membro=funcionarios.cadastrar(self.repo,{'nome':'Autora Gemini','funcao':'Implementar','equipe':'Dev','executor':{'console':'gemini'},'skills':[]})
        chamadas=[]
        r=re.executar(self.repo,self.trabalho,self.base,'Dev','Aceite',lambda e,p: chamadas.append(e['console']) or {'veredito':'aprovado','achados':[]},funcionario=membro['id'])
        self.assertEqual(r['autor'],membro['executor'])
        self.assertEqual(chamadas,['claude','codex']); self.assertTrue(r['aprovado'])
    def test_checkout_principal_e_subpasta_nao_sao_worktrees_de_tarefa(self):
        with self.assertRaises(ValueError): gestao_cli.validar_worktree(self.repo,self.repo)
        sub=self.repo/'pasta'; sub.mkdir()
        with self.assertRaises(ValueError): gestao_cli.validar_worktree(self.repo,sub)
        self.assertEqual(gestao_cli.validar_worktree(self.repo,self.trabalho),self.trabalho.resolve())
    def test_trava_git_compartilhada_e_estado_fora_da_arvore_versionada(self):
        from controle_tarefas import ocupar_worktree
        banco=gestao_cli.banco_worktrees(self.repo)
        self.assertEqual(banco,gestao_cli.banco_worktrees(self.trabalho))
        with ocupar_worktree(banco,self.trabalho):
            with self.assertRaisesRegex(ValueError,'já ocupado'):
                with ocupar_worktree(gestao_cli.banco_worktrees(self.trabalho),self.trabalho): pass
            self.assertEqual(self.git('status','--porcelain'),'')
        with ocupar_worktree(banco,self.trabalho): pass


if __name__=='__main__': unittest.main()
