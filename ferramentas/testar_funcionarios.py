"""Cadastro por projeto, fonte compartilhada e seleção do launcher; sem modelos."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import funcionarios as f
import console_provider as launcher
from gestao_projeto import validar

class Cadastro(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.raiz=Path(self.temp.name)
        self.cfg=validar({'ativo':True,'equipes':[{'nome':'Dev','especialidade':'implementação','executor':{'console':'claude'}}]})
        (self.raiz/'.office').mkdir(); self.salvar()
        skill=self.raiz/'.claude/skills/historia/SKILL.md'; skill.parent.mkdir(parents=True)
        skill.write_text('---\nname: historia\ndescription: História\n---\nInstruções',encoding='utf-8')
        self.dados={'nome':'Historiadora','funcao':'Revisar coerência histórica','equipe':'Dev','executor':{'console':'codex','modelo':'exemplo'},'skills':['historia']}
    def salvar(self):
        (self.raiz/'.office/projeto.json').write_text(json.dumps(self.cfg),encoding='utf-8')
    def test_persistencia_sem_alterar_skills_ou_agentes(self):
        skill=self.raiz/'.claude/skills/historia/SKILL.md'; antes=skill.read_bytes()
        self.assertEqual(f.listar(self.raiz),[]); self.assertFalse(f.arquivo(self.raiz).exists())
        item=f.cadastrar(self.raiz,self.dados)
        self.assertEqual(f.obter(self.raiz,item['id']),item)
        self.assertIn('historia',f.contexto(self.raiz,item)); self.assertEqual(skill.read_bytes(),antes)
        self.assertFalse((self.raiz/'.claude/agents').exists())
        with self.assertRaises(ValueError): f.cadastrar(self.raiz,{**self.dados,'nome':'HISTORIADORA'})
    def test_invalido_sem_criar_banco(self):
        for troca in ({'equipe':'Outro'},{'skills':['../segredo']},{'executor':{'console':'opencode','cloud':''}},{'executor':{'console':'codex','execucao':'local'}},{'permissoes':'tudo'}):
            with self.subTest(troca=troca),self.assertRaises(ValueError): f.cadastrar(self.raiz,{**self.dados,**troca})
        self.assertFalse(f.arquivo(self.raiz).exists())
    def test_opencode_zen_sem_fornecedor_cadastra_e_seleciona_skill_compartilhada(self):
        dados={**self.dados,'executor':{'console':'opencode','modelo':'opencode/space-bunny-free','execucao':'cloud'}}
        item=f.cadastrar(self.raiz,dados)
        self.assertNotIn('cloud',item['executor']); self.assertEqual(f.obter(self.raiz,item['id']),item)
        with patch.object(launcher,'selecionar',return_value=(type('Provider',(),{'nome':'opencode'})(),'native')),patch.object(launcher,'executar',return_value=0) as executar:
            self.assertEqual(launcher.main(['--projeto',str(self.raiz),'--funcionario',item['id'],'--prompt','Pesquisa']),0)
            self.assertEqual(executar.call_args.args[5],'opencode/space-bunny-free')
            self.assertIn('historia',executar.call_args.args[4])
    def test_api_pc_e_projeto_registrado(self):
        dados={'projeto_id':f.id_projeto(self.raiz),'funcionario':self.dados}
        self.assertEqual(f.api_cadastrar([self.raiz],dados,{'permissao':'ver'})[0],403)
        self.assertEqual(f.api_cadastrar([self.raiz],{**dados,'projeto_id':'../fora'},{'permissao':'pc'})[0],400)
        self.assertEqual(f.api_cadastrar([self.raiz],dados,{'permissao':'pc'})[0],201)
    def test_remocao_skill_bloqueia_execucao(self):
        item=f.cadastrar(self.raiz,self.dados)
        (self.raiz/'.claude/skills/historia/SKILL.md').unlink()
        with self.assertRaises(ValueError): f.obter(self.raiz,item['id'])
    def test_launcher_seleciona_executor_e_contexto(self):
        item=f.cadastrar(self.raiz,self.dados)
        with patch.object(launcher,'selecionar',return_value=(type('Provider',(),{'nome':'codex'})(),'codex')),patch.object(launcher,'executar',return_value=0) as executar:
            self.assertEqual(launcher.main(['--projeto',str(self.raiz),'--funcionario',item['id'],'--prompt','Revisar']),0)
            args=executar.call_args.args
            self.assertEqual(args[3],f.nome_eventos(item)); self.assertIn('coerência histórica',args[4]); self.assertEqual(args[5],'exemplo')
    def test_local_desativado_depois_do_cadastro(self):
        self.cfg['local']['ativo']=True; self.salvar()
        item=f.cadastrar(self.raiz,{**self.dados,'executor':{'console':'codex','modelo':'qwen','execucao':'local'}})
        self.cfg['local']['ativo']=False; self.salvar()
        with self.assertRaises(ValueError): f.obter(self.raiz,item['id'])
    def test_equipe_escopo_local_e_rota_do_membro(self):
        item=f.cadastrar(self.raiz,self.dados)
        self.assertEqual(f.executor(self.raiz,item['id'],'Dev','implementacao')[1]['console'],'codex')
        with self.assertRaises(ValueError): f.executor(self.raiz,item['id'],'QA','implementacao')
        self.cfg['local']['ativo']=True; self.salvar()
        local=f.cadastrar(self.raiz,{**self.dados,'nome':'Auxiliar','executor':{'console':'codex','modelo':'qwen','execucao':'local'}})
        with self.assertRaises(ValueError): f.executor(self.raiz,local['id'],'Dev','implementacao')
        self.assertEqual(f.executor(self.raiz,local['id'],'Dev','simples')[1]['execucao'],'local')
    def test_nome_publico_consume_identidade_estavel_sem_caminho(self):
        item=f.cadastrar(self.raiz,self.dados)
        consumo=f.rotular_consumo([self.raiz],{'grupos':[{'agente':f.nome_eventos(item)}]})
        self.assertIn('Historiadora',consumo['grupos'][0]['agente_nome'])
        self.assertNotIn(str(self.raiz),json.dumps(consumo))
        self.assertEqual(consumo['grupos'][0]['agente'],f.nome_eventos(item))
    def test_claude_tui_funcionario_inicio_fim_sem_alterar_hook_ou_nome_legado(self):
        from providers_console import PROVIDERS
        from types import SimpleNamespace
        processo=SimpleNamespace(wait=lambda:0,stdout=None,stdin=None)
        eventos=[]
        with patch('console_provider.subprocess.Popen',return_value=processo),patch('emit_evento.gravar',side_effect=lambda ev,*a:eventos.append(ev)):
            launcher.executar(PROVIDERS['claude'],'claude.exe',self.raiz,'Office_'+'a'*32,banco=self.raiz/'teste.db')
            self.assertEqual([ev['agente'] for ev in eventos],['Office_'+'a'*32]*2)
            eventos.clear()
            launcher.executar(PROVIDERS['claude'],'claude.exe',self.raiz,'Dev',banco=self.raiz/'teste.db')
            self.assertEqual(eventos,[]) # ciclo legado continua entregue pelo hook existente

if __name__=='__main__': unittest.main()
