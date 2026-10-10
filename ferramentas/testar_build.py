"""Pacote por manifesto explícito, sem alterar o índice Git ou incluir dados pessoais."""
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import subprocess
import unittest
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parent))
import build

class Pacote(unittest.TestCase):
    def test_modulo_nao_rastreado_entra_dados_ficam_fora(self):
        with tempfile.TemporaryDirectory() as tmp:
            raiz=Path(tmp)
            (raiz/'novo.py').write_text('valor = 1\n'); (raiz/'config.json').write_text('PRIVADO')
            (raiz/'dados').mkdir(); (raiz/'dados/eventos.jsonl').write_text('PRIVADO')
            arquivos=build.arquivos_pacote(raiz,['novo.py'],versionados=[])
            z,soma=build.gerar(raiz,arquivos,raiz/'dist','teste')
            with zipfile.ZipFile(z) as pacote:
                self.assertEqual(pacote.namelist(),['teste/novo.py']); self.assertEqual(pacote.read('teste/novo.py'),(raiz/'novo.py').read_bytes())
            self.assertEqual(soma,hashlib.sha256(z.read_bytes()).hexdigest())
    def test_privado_escape_ausente_e_duplicado_bloqueiam(self):
        with tempfile.TemporaryDirectory() as tmp:
            raiz=Path(tmp); (raiz/'bom.py').write_text('pass')
            for itens in (['config.json'],['dados/eventos.jsonl'],['../fora.py'],['.env'],['ausente.py'],['bom.py','bom.py']):
                with self.subTest(itens=itens),self.assertRaises(ValueError): build.arquivos_pacote(raiz,itens,[])
    def test_versionado_sem_classificacao_bloqueia(self):
        with tempfile.TemporaryDirectory() as tmp:
            raiz=Path(tmp); (raiz/'bom.py').write_text('pass')
            with self.assertRaises(ValueError): build.arquivos_pacote(raiz,['bom.py'],['bom.py','arquivo-novo.txt'])
            self.assertEqual(build.arquivos_pacote(raiz,['bom.py'],['bom.py','.github/workflows/ci.yml','.gitattributes']),['bom.py'])
    def test_instalador_recusa_fonte_incompleta_antes_de_copiar(self):
        import instalar
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            raiz=Path(tmp); (raiz/'bom.py').write_text('pass'); destino=raiz/'app'
            with patch.object(instalar,'PASTA',raiz),patch.object(instalar,'PACOTE',['bom.py','ausente.py']):
                with self.assertRaises(ValueError): instalar.copiar_pacote(destino)
            self.assertFalse(destino.exists())
    def test_manifesto_real_contem_todos_os_adapters(self):
        lista=build.arquivos_pacote()
        for nome in ('gestao_cli.py','configurar_gestao.py','funcionarios_cena.mjs','consumo_providers.py','revisao_execucao.py','providers_console.py','kanban_painel.py','kanban_projetos.mjs','dependencias_tarefas.py'):
            self.assertIn(nome,lista)
    def test_zip_extraido_importa_e_serve_a_gestao(self):
        with tempfile.TemporaryDirectory() as tmp:
            raiz=Path(tmp); arquivos=build.arquivos_pacote()
            z,_=build.gerar(build.RAIZ,arquivos,raiz/'dist','pacote')
            with zipfile.ZipFile(z) as pacote: pacote.extractall(raiz/'extraido')
            app=raiz/'extraido/pacote'
            script=r'''
import sys,json,threading,http.client
from pathlib import Path
from functools import partial
from http.server import ThreadingHTTPServer
app=Path(sys.argv[1]); sys.path.insert(0,str(app))
import servidor,gestao_cli,configurar_gestao,funcionarios,executor_local,consumo_providers,revisao_execucao,configuracao,rede,banco,kanban_painel,dependencias_tarefas
for modulo in (servidor,gestao_cli,configurar_gestao,funcionarios,executor_local,consumo_providers,revisao_execucao,kanban_painel,dependencias_tarefas):
    assert Path(modulo.__file__).resolve().is_relative_to(app.resolve())
projeto=app.parent/'projeto'; (projeto/'.office').mkdir(parents=True)
cfg={'ativo':True,'equipes':[{'nome':'Dev','especialidade':'Teste','executor':{'console':'codex'}}]}
(projeto/'.office/projeto.json').write_text(json.dumps(cfg),encoding='utf-8')
funcionarios.cadastrar(projeto,{'nome':'Especialista do pacote','funcao':'Testar instalação','equipe':'Dev','executor':{'console':'codex'},'skills':[]})
publico=configuracao.normalizar({'projetos':[str(projeto)]})
servidor.cfg=lambda:publico; banco.ARQ=projeto/'eventos.db'
servidor.Handler.rede=rede.Rede(projeto,False,False)
srv=ThreadingHTTPServer(('127.0.0.1',0),partial(servidor.Handler,directory=str(app)))
t=threading.Thread(target=srv.serve_forever,daemon=True); t.start()
con=http.client.HTTPConnection('127.0.0.1',srv.server_address[1],timeout=10)
try:
    con.request('GET','/api/gestao'); resposta=con.getresponse(); dados=json.loads(resposta.read())
    assert resposta.status==200 and dados['projetos'][0]['funcionarios'][0]['nome']=='Especialista do pacote'
    for arquivo in ('funcionarios_cena.mjs','gestao_painel.js','funcionarios_form.js','indicadores_providers.mjs','kanban_projetos.mjs'):
        con.request('GET','/'+arquivo); resposta=con.getresponse(); corpo=resposta.read()
        assert resposta.status==200 and corpo, arquivo
finally:
    con.close(); srv.shutdown(); srv.server_close(); t.join()
'''
            env={k:v for k,v in os.environ.items() if not k.startswith('OFFICE_') and k!='PYTHONPATH'}
            r=subprocess.run([sys.executable,'-I','-c',script,str(app)],cwd=app,env=env,capture_output=True,text=True,timeout=30)
            self.assertEqual(r.returncode,0,r.stderr)

if __name__=='__main__': unittest.main()
