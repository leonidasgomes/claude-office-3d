"""Runtime Claude permanece nativo; outros providers recebem somente controles mapeados."""
from pathlib import Path
import json
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from skills_compartilhados import catalogo,resolver,preparar_compartilhados,contexto,instrucoes_ativacao,nomes_cartao
from compatibilidade_skills import analisar,diagnostico
import funcionarios


class Skills(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.p=Path(self.tmp.name)
        self.dir=self.p/'.claude/skills/teste';self.dir.mkdir(parents=True)
        self.arq=self.dir/'SKILL.md'
    def escrever(self,extra='',corpo='Instruções reutilizáveis.'):
        self.arq.write_text('---\nname: teste\ndescription: Teste\n'+extra+'---\n'+corpo,encoding='utf-8')
        return catalogo(self.p)[0]
    def test_nomes_cartao_aceita_ponto_final_e_resolve_catalogo(self):
        self.escrever()
        nomes=nomes_cartao('teste, teste;\n- teste.')
        self.assertEqual(nomes,['teste'])
        self.assertEqual([s['nome'] for s in resolver(self.p,nomes)],['teste'])
        with self.assertRaisesRegex(ValueError,'indisponível'):
            resolver(self.p,nomes_cartao('outro.'))
    def test_nomes_cartao_rejeita_pontuacao_ambigua_e_entradas_invalidas(self):
        for texto in ('teste..','teste. outro','teste., outro',
                      'teste/path.','../teste.','teste && echo.','qualquer nome.',
                      'teste_.','.','teste.\noutro','teste, .','teste;.',' , .'):
            with self.subTest(texto=texto), self.assertRaises(ValueError):
                nomes_cartao(texto)
    def test_contexto_regras_por_escopo_sem_copia_ou_leitura_do_corpo(self):
        self.escrever()
        regras=self.p/'.claude/rules';regras.mkdir()
        arq=regras/'unreal.md';arq.write_text('---\npaths:\n - "Unreal/**"\n---\nSEGREDO_REGRA',encoding='utf-8')
        antes=arq.read_bytes()
        for provider in ('claude','codex','opencode','gemini'):
            texto=contexto(self.p,provider)
            self.assertIn('.claude/rules/',texto);self.assertIn('frontmatter paths',texto)
            self.assertIn('não aplique regras condicionais a todo o projeto',texto)
            self.assertNotIn('SEGREDO_REGRA',texto)
        self.assertEqual(arq.read_bytes(),antes)
    def test_contexto_recusa_tipo_invalido_de_regras(self):
        self.escrever();(self.p/'.claude/rules').write_text('não é pasta',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'pasta inválida'):contexto(self.p,'codex')
    def test_campos_no_corpo_nao_sao_frontmatter_e_plaintext_compartilhado(self):
        s=self.escrever(corpo='Documente os campos hooks: e allowed-tools: neste manual.')
        self.assertEqual(s['recursos_runtime'],[]);self.assertEqual(s['limites'],[])
        for p in ('claude','codex','opencode','gemini'):
            self.assertEqual(diagnostico(s,p)['estado'],'instrucoes')
            self.assertTrue(resolver(self.p,['teste'],provider=p))
        antes=self.arq.read_bytes()
        r=preparar_compartilhados(self.p,True);self.assertEqual(r[0]['estado'],'compartilhado')
        self.assertEqual(self.arq.read_bytes(),antes)
    def test_native_claude_hooks_e_outros_providers_bloqueados(self):
        s=self.escrever('hooks:\n  Stop: []\nallowed-tools: Read\ncontext: fork\nagent: Explore\n')
        self.assertEqual(diagnostico(s,'claude')['estado'],'nativa-claude')
        refs=resolver(self.p,['teste'],provider='claude')
        self.assertEqual(refs[0]['ativacao_nativa'],'Skill')
        self.assertIn('interrompa a tarefa',instrucoes_ativacao(refs))
        self.assertIn('não equivale à ativação',contexto(self.p,'claude'))
        self.assertEqual(instrucoes_ativacao(resolver(self.p,['teste'])),'')
        for p in ('codex','gemini','opencode'):
            with self.assertRaisesRegex(ValueError,'incompatível'): resolver(self.p,['teste'],provider=p)
        with self.assertRaises(ValueError): resolver(self.p,['teste'],provider='claude',local=True)
        self.assertTrue(preparar_compartilhados(self.p,True)[0]['estado'].startswith('adaptação pendente'))
        self.assertFalse((self.p/'.agents').exists())
        self.assertIn('adaptação pendente para codex',contexto(self.p,'codex'))
    def test_substituicoes_injecao_campos_futuros_e_repetidos(self):
        for corpo in ('Resumo: !`git status`','Use ${CLAUDE_SKILL_DIR}/script.py','$ARGUMENTS'):
            s=self.escrever(corpo=corpo)
            self.assertEqual(diagnostico(s,'codex')['estado'],'adaptacao-pendente')
        s=self.escrever('controle-futuro: true\n')
        self.assertEqual(diagnostico(s,'claude')['estado'],'adaptacao-pendente')
        s=self.escrever('name: repetido\n')
        self.assertTrue(any('campo repetido' in p for p in s['problemas']))
        self.assertTrue(analisar('sem frontmatter')['problemas'])
    def test_fonte_personalizada_nao_finge_registro_claude_nativo(self):
        self.escrever('hooks:\n  Stop: []\n')
        nova=self.p/'procedimentos/teste';nova.mkdir(parents=True)
        self.arq.rename(nova/'SKILL.md')
        cfg={'fontes':{'skills':'procedimentos'}}
        s=catalogo(self.p,cfg)[0];self.assertFalse(s['claude_nativo'])
        with self.assertRaises(ValueError): resolver(self.p,['teste'],cfg,'claude')
    def test_cadastro_checa_compatibilidade_antes_de_gravar(self):
        self.escrever('allowed-tools: Read\n')
        pasta=self.p/'.office';pasta.mkdir()
        (pasta/'projeto.json').write_text(json.dumps({'ativo':True,'equipes':[
            {'nome':'Dev','especialidade':'Código','executor':{'console':'claude'}}]}),encoding='utf-8')
        item={'nome':'Marketing','funcao':'Texto','equipe':'Dev','executor':{'console':'codex'},'skills':['teste']}
        with self.assertRaisesRegex(ValueError,'incompatível'): funcionarios.cadastrar(self.p,item)
        self.assertFalse((pasta/'funcionarios.db').exists())
        item['executor']={'console':'claude'}
        registrado=funcionarios.cadastrar(self.p,item)
        self.assertEqual(funcionarios.obter(self.p,registrado['id'])['nome'],'Marketing')
        self.assertTrue(funcionarios.skills(self.p,{'ativo':True})[0]['compatibilidade']['codex']['pendencias'])


if __name__=='__main__': unittest.main()
