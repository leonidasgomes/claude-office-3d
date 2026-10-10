"""Pré-requisitos simulados e bind local real, sem instalar/abrir consoles."""
from contextlib import redirect_stdout,redirect_stderr
from pathlib import Path
import io,json,socket,sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import diagnostico_instalacao as d
import iniciar_projeto as inicio


class Diagnostico(unittest.TestCase):
    def politica(self):
        return {'ativo':True,'fontes':{'regras':'.office/REGRAS.md'},
          'kanban':{'repo':'owner/app','owner':'owner','numero':1},
          'ceo':{'console':'codex'},'diretor':{'console':'gemini'},
          'equipes':[{'nome':'Dev','especialidade':'Código','executor':{'console':'opencode','modelo':'opencode/big-pickle','cloud':'opencode'}}]}
    def verificar(self,cfg,presentes):
        with patch.object(d.shutil,'which',side_effect=lambda n:'/teste/'+n if n in presentes else None), \
             patch.object(d,'comando_nativo',side_effect=lambda caminho,nome:[caminho]),patch.object(d,'porta_disponivel',return_value=True):
            return d.verificar(cfg)
    def test_claude_opcional_se_apenas_outros_consoles_usados(self):
        r=self.verificar(self.politica(),{'git','gh','codex','gemini','opencode'})
        self.assertTrue(r['requisitos_locais_disponiveis'])
        self.assertFalse(next(i for i in r['itens'] if i['nome']=='claude')['obrigatorio'])
        self.assertNotIn('/teste',json.dumps(r));self.assertEqual(r['autenticacao'],'não verificada')
    def test_revisores_tambem_exigem_seus_consoles(self):
        cfg=self.politica();cfg['revisao']={'ativo':True,'revisores':[
          {'nome':'R1','executor':{'console':'claude','cloud':'anthropic'}},
          {'nome':'R2','executor':{'console':'gemini','cloud':'google'}}]}
        r=self.verificar(cfg,{'git','gh','codex','gemini','opencode'})
        self.assertEqual(r['faltam'],['claude'])
    def test_revisor_suspenso_nao_obriga_instalar_seu_console(self):
        cfg=self.politica();cfg['diretor']={'console':'codex'}
        cfg['revisao']={'ativo':True,'revisores':[
            {'nome':'QA Claude','executor':{'console':'claude'},'ativo':False},
            {'nome':'QA Gemini','executor':{'console':'gemini'},'ativo':False}]}
        r=self.verificar(cfg,{'git','gh','codex','opencode'})
        self.assertTrue(r['requisitos_locais_disponiveis'])
        for nome in ('claude','gemini'):
            self.assertFalse(next(i for i in r['itens'] if i['nome']==nome)['obrigatorio'])
    def test_local_so_exige_ollama_quando_rota_local_escolhida(self):
        cfg=self.politica();cfg['local']={'ativo':True}
        cfg['rotas']={'simples':{'console':'codex','execucao':'local','modelo':'pequeno'}}
        self.assertIn('ollama',self.verificar(cfg,{'git','gh','codex','gemini','opencode'})['faltam'])
        del cfg['rotas']
        self.assertNotIn('ollama',self.verificar(cfg,{'git','gh','codex','gemini','opencode'})['faltam'])
    def test_shim_incompativel_nao_vira_instalado(self):
        with patch.object(d.shutil,'which',return_value='/teste/shim.cmd'),patch.object(d,'porta_disponivel',return_value=True), \
             patch.object(d,'comando_nativo',side_effect=ValueError('DETALHE PRIVADO')):
            r=d.verificar(self.politica())
        self.assertIn('codex',r['faltam']);self.assertNotIn('PRIVADO',json.dumps(r))
    def test_porta_ocupada_detectada_sem_servidor(self):
        with socket.socket() as s:
            s.bind(('127.0.0.1',0));s.listen()
            self.assertFalse(d.porta_disponivel(s.getsockname()[1]))
    def test_modo_estrito_nao_aplica_com_requisitos_ausentes(self):
        with tempfile.TemporaryDirectory() as tmp:
            raiz=Path(tmp);projeto=raiz/'projeto';projeto.mkdir();app=raiz/'app'
            arq=raiz/'politica.json';arq.write_text(json.dumps(self.politica()),encoding='utf-8')
            with patch.object(d,'verificar',return_value={'requisitos_locais_disponiveis':False,'faltam':['codex']}), \
                 patch.object(inicio,'aplicar',side_effect=AssertionError('aplicação indevida')),redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
                codigo=inicio.main(['--projeto',str(projeto),'--destino',str(app),'--politica',str(arq),'--aplicar','--exigir-requisitos'])
            self.assertEqual(codigo,3);self.assertFalse(app.exists());self.assertFalse((projeto/'.office').exists())
    def test_dashboard_inativo_dispensa_consoles_e_git(self):
        r=self.verificar({'ativo':False},set())
        self.assertTrue(r['requisitos_locais_disponiveis'])
        self.assertTrue(all(not i['obrigatorio'] for i in r['itens'] if i['nome'] in ('git','gh','claude','codex','gemini','opencode')))


if __name__=='__main__':unittest.main()
