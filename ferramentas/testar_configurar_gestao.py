"""Instalação de política em projetos temporários, sem autenticação ou inferência."""
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import configurar_gestao as c

class Configurar(unittest.TestCase):
    def test_guiado_recomenda_codex_sem_exigir_claude_e_preserva_escolha(self):
        with tempfile.TemporaryDirectory() as tmp:
            for escolha in ('', 'claude'):
                perguntas=[]
                def entrada(pergunta):
                    perguntas.append(pergunta)
                    if pergunta.startswith('CEO console'):return escolha
                    if pergunta.startswith('Revisão cruzada'):return 'n'
                    if pergunta.startswith('Repositório GitHub'):return 'owner/repo'
                    return ''
                with patch.object(c,'detectar',return_value=[
                    {'console':'claude','instalado':True},{'console':'codex','instalado':True}]):
                    cfg=c.guiado(Path(tmp),entrada)
                self.assertIn('[codex]',next(p for p in perguntas if p.startswith('CEO console')))
                esperado=escolha or 'codex'
                self.assertEqual(cfg['ceo']['console'],esperado)
                self.assertEqual(cfg['diretor']['console'],esperado)
                self.assertTrue(all(e['executor']['console']==esperado for e in cfg['equipes']))
                self.assertFalse(cfg['revisao']['ativo'])
                self.assertFalse((Path(tmp)/'.office').exists())

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup); self.raiz=Path(self.tmp.name)
        self.cfg={'ativo':True,'fontes':{'regras':'.office/REGRAS.md'},'kanban':{'repo':'owner/repo','owner':'owner','numero':4},
                  'equipes':[{'nome':'Dev','especialidade':'Código','executor':{'console':'codex'}}]}
    def test_zen_sem_fornecedor_prepara_ceo_diretor_e_equipes(self):
        executor={'console':'opencode','modelo':'opencode/space-bunny-free','execucao':'cloud'}
        cfg={**self.cfg,'ceo':executor,'diretor':executor,
             'equipes':[{'nome':'Dev','especialidade':'Pesquisa','executor':executor}]}
        plano=c.preparar(self.raiz,cfg)
        for item in (plano['politica']['ceo'],plano['politica']['diretor'],plano['politica']['equipes'][0]['executor']):
            self.assertNotIn('cloud',item);self.assertEqual(item['modelo'],'opencode/space-bunny-free')
        self.assertFalse((self.raiz/'.office').exists())

    def test_guiado_zen_sem_fornecedor_nao_grava_cloud_vazia(self):
        def entrada(pergunta):
            if ' console ' in pergunta:return 'opencode'
            if ' fornecedor real ' in pergunta:return ''
            if ' modelo ' in pergunta:return 'opencode/space-bunny-free'
            if pergunta.startswith('Revisão cruzada'):return 'n'
            if pergunta.startswith('Repositório GitHub'):return 'owner/repo'
            return ''
        with patch.object(c,'detectar',return_value=[{'console':'opencode','instalado':True}]):
            cfg=c.guiado(self.raiz,entrada)
        plano=c.preparar(self.raiz,cfg)
        self.assertNotIn('cloud',plano['politica']['ceo'])
        self.assertNotIn('cloud',plano['politica']['diretor'])
        self.assertFalse(plano['politica']['revisao']['ativo'])

    def test_previa_aplicacao_repeticao_preservam_contratos(self):
        (self.raiz/'CLAUDE.md').write_text('REGRAS EXISTENTES',encoding='utf-8')
        (self.raiz/'.claude').mkdir(); settings=self.raiz/'.claude/settings.json'; settings.write_text('{"custom":true}')
        plano=c.preparar(self.raiz,self.cfg); self.assertFalse((self.raiz/'.office').exists())
        self.assertEqual(plano['politica']['merge']['modo'],'manual'); self.assertFalse(plano['politica']['local']['ativo'])
        c.aplicar(self.raiz,plano)
        self.assertTrue((self.raiz/'.office/REGRAS.md').is_file())
        self.assertIn('perfis-nativos.lock',(self.raiz/'.office/.gitignore').read_text(encoding='utf-8').splitlines())
        self.assertEqual(settings.read_text(),'{"custom":true}'); self.assertEqual((self.raiz/'CLAUDE.md').read_text(),'REGRAS EXISTENTES')
        repetido=c.preparar(self.raiz,self.cfg); self.assertTrue(repetido['existente']); self.assertEqual(c.aplicar(self.raiz,repetido),[])
    def test_preserva_politica_existente_inclusive_auto_merge(self):
        cfg={**self.cfg,'merge':{'modo':'automatico','checks':['revisor-ia','sugestoes']}}
        c.aplicar(self.raiz,c.preparar(self.raiz,cfg))
        antes=(self.raiz/'.office/projeto.json').read_bytes()
        with self.assertRaises(ValueError): c.preparar(self.raiz,self.cfg)
        self.assertEqual((self.raiz/'.office/projeto.json').read_bytes(),antes)
    def test_repara_entradas_ausentes_sem_regravar_politica_e_claude(self):
        c.aplicar(self.raiz,c.preparar(self.raiz,self.cfg))
        politica=self.raiz/'.office/projeto.json'
        politica.write_text(json.dumps(json.loads(politica.read_text(encoding='utf-8')),indent=4)+'\n',encoding='utf-8')
        antes=politica.read_bytes()
        (self.raiz/'CLAUDE.md').write_text('Personalização Claude preservada',encoding='utf-8')
        (self.raiz/'AGENTS.md').unlink();(self.raiz/'GEMINI.md').unlink()
        plano=c.preparar(self.raiz,self.cfg)
        self.assertTrue(plano['existente'])
        self.assertEqual(set(plano['arquivos']),{'AGENTS.md','GEMINI.md'})
        self.assertEqual(c.aplicar(self.raiz,plano),['AGENTS.md','GEMINI.md'])
        self.assertEqual(politica.read_bytes(),antes)
        self.assertEqual((self.raiz/'CLAUDE.md').read_text(encoding='utf-8'),'Personalização Claude preservada')
        self.assertEqual(c.aplicar(self.raiz,c.preparar(self.raiz,self.cfg)),[])
    def test_reparo_recusa_corrida_e_fonte_customizada_ausente(self):
        (self.raiz/'CLAUDE.md').write_text('Fonte original',encoding='utf-8')
        cfg={**self.cfg,'fontes':{'regras':'CLAUDE.md'}}
        c.aplicar(self.raiz,c.preparar(self.raiz,cfg))
        (self.raiz/'AGENTS.md').unlink();(self.raiz/'GEMINI.md').unlink()
        plano=c.preparar(self.raiz,cfg)
        (self.raiz/'AGENTS.md').write_text('Criado por outro editor',encoding='utf-8')
        with self.assertRaises(ValueError):c.aplicar(self.raiz,plano)
        self.assertFalse((self.raiz/'GEMINI.md').exists())
        self.assertEqual((self.raiz/'AGENTS.md').read_text(encoding='utf-8'),'Criado por outro editor')
        (self.raiz/'CLAUDE.md').unlink()
        with self.assertRaises(ValueError):c.preparar(self.raiz,cfg)
    def test_reparo_nao_substitui_fonte_comum_perdida_por_regras_iniciais(self):
        c.aplicar(self.raiz,c.preparar(self.raiz,self.cfg))
        politica=(self.raiz/'.office/projeto.json').read_bytes()
        (self.raiz/'.office/REGRAS.md').unlink();(self.raiz/'AGENTS.md').unlink()
        with self.assertRaisesRegex(ValueError,'Fonte de regras ausente'):c.preparar(self.raiz,self.cfg)
        self.assertFalse((self.raiz/'.office/REGRAS.md').exists())
        self.assertFalse((self.raiz/'AGENTS.md').exists())
        self.assertEqual((self.raiz/'.office/projeto.json').read_bytes(),politica)
    def test_regras_existentes_sem_copia(self):
        (self.raiz/'CLAUDE.md').write_text('Contrato',encoding='utf-8')
        plano=c.preparar(self.raiz,{**self.cfg,'fontes':{'regras':'CLAUDE.md'}})
        self.assertEqual(set(plano['arquivos']),{'.office/projeto.json','.office/.gitignore','AGENTS.md','GEMINI.md'})
        self.assertIn('CLAUDE.md',plano['arquivos']['AGENTS.md'])
        self.assertIn('@./CLAUDE.md',plano['arquivos']['GEMINI.md'])
        self.assertNotIn('@./',plano['arquivos']['AGENTS.md'])
    def test_gemini_importa_fonte_nova_e_preserva_entrada_existente(self):
        plano=c.preparar(self.raiz,self.cfg)
        self.assertIn('@./.office/REGRAS.md',plano['arquivos']['GEMINI.md'])
        (self.raiz/'GEMINI.md').write_text('Contexto personalizado',encoding='utf-8')
        plano=c.preparar(self.raiz,self.cfg)
        self.assertNotIn('GEMINI.md',plano['arquivos'])
        c.aplicar(self.raiz,plano)
        self.assertEqual((self.raiz/'GEMINI.md').read_text(encoding='utf-8'),'Contexto personalizado')
    def test_claude_novo_importa_fonte_unica_e_entradas_referem_escopos(self):
        plano=c.preparar(self.raiz,self.cfg)
        self.assertIn('@./.office/REGRAS.md',plano['arquivos']['CLAUDE.md'])
        for nome in ('CLAUDE.md','AGENTS.md','GEMINI.md'):
            self.assertIn('.claude/rules/',plano['arquivos'][nome])
            self.assertIn('frontmatter paths',plano['arquivos'][nome])
        c.aplicar(self.raiz,plano)
        self.assertEqual(c.aplicar(self.raiz,c.preparar(self.raiz,self.cfg)),[])
    def test_nao_importa_fonte_com_espacos_e_nao_cria_auto_importacao(self):
        (self.raiz/'Regras comuns.md').write_text('Fonte original',encoding='utf-8')
        plano=c.preparar(self.raiz,{**self.cfg,'fontes':{'regras':'Regras comuns.md'}})
        self.assertNotIn('@./',plano['arquivos']['CLAUDE.md'])
        self.assertIn('Regras comuns.md',plano['arquivos']['CLAUDE.md'])
        (self.raiz/'CLAUDE.md').write_text('Autoridade Claude',encoding='utf-8')
        plano=c.preparar(self.raiz,{**self.cfg,'fontes':{'regras':'CLAUDE.md'}})
        self.assertNotIn('CLAUDE.md',plano['arquivos'])
    def test_erro_e_corrida_sem_sobrescrita(self):
        with self.assertRaises(ValueError): c.preparar(self.raiz,{**self.cfg,'kanban':{'repo':'inválido'}})
        plano=c.preparar(self.raiz,self.cfg)
        (self.raiz/'.office').mkdir(); (self.raiz/'.office/projeto.json').write_text('{}')
        with self.assertRaises(ValueError): c.aplicar(self.raiz,plano)
        self.assertEqual((self.raiz/'.office/projeto.json').read_text(),'{}')
        self.assertFalse((self.raiz/'.office/REGRAS.md').exists())
    def test_deteccao_nao_executa_clis(self):
        with patch('configurar_gestao.shutil.which',return_value=None):
            self.assertTrue(all(not x['instalado'] for x in c.detectar()))
        with patch('configurar_gestao.shutil.which',return_value='console.exe'),patch('configurar_gestao.comando_nativo',return_value=['console.exe']):
            self.assertTrue(all(x['autenticacao']=='não verificada' for x in c.detectar()))
    def test_guiado_cloud_revisores_e_fonte_existente(self):
        (self.raiz/'CLAUDE.md').write_text('Regras originais',encoding='utf-8')
        def entrada(pergunta):
            return 'owner/repo' if pergunta.startswith('Repositório GitHub') else ''
        with patch.object(c,'detectar',return_value=[{'console':'codex','instalado':True}]):
            cfg=c.guiado(self.raiz,entrada)
        self.assertEqual(cfg['ceo']['console'],'codex')
        self.assertTrue(cfg['revisao']['ativo']); self.assertEqual(len(cfg['revisao']['revisores']),3)
        self.assertEqual(cfg['fontes']['regras'],'CLAUDE.md')
        self.assertFalse(cfg['local']['ativo']); self.assertEqual(cfg['merge']['modo'],'manual')
    def test_cli_publico_prepara_e_aplica_sem_hooks(self):
        instalar=Path(__file__).resolve().parent.parent/'instalar.py'
        if not instalar.is_file(): self.skipTest('Versão dev usa configurar_gestao.py diretamente')
        arq=self.raiz/'politica.json'; arq.write_text(json.dumps(self.cfg),encoding='utf-8')
        chamada=[sys.executable,str(instalar),'--gestao',str(self.raiz),'--politica',str(arq)]
        for aplicar in (False,True):
            r=subprocess.run(chamada+(['--aplicar'] if aplicar else []),capture_output=True,text=True,timeout=15)
            self.assertEqual(r.returncode,0,r.stderr)
            self.assertEqual((self.raiz/'.office/projeto.json').exists(),aplicar)
        self.assertFalse((self.raiz/'.claude/settings.json').exists())
        self.assertIn('.office/REGRAS.md',(self.raiz/'AGENTS.md').read_text(encoding='utf-8'))

if __name__=='__main__': unittest.main()
