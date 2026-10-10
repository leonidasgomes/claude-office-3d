"""Instalação integrada isolada, sem contas, hooks ou processos cloud."""
import json
import os
import io
from contextlib import redirect_stdout
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import iniciar_projeto as inicio
import instalar


class Iniciar(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.raiz = Path(self.tmp.name)
        self.projeto = self.raiz/'jogo'; self.projeto.mkdir()
        self.app = self.raiz/'escritorio'
        self.politica = {'ativo':True,'fontes':{'regras':'.office/REGRAS.md'},
                        'kanban':{'repo':'owner/repo','owner':'owner','numero':4},
                        'equipes':[{'nome':'Dev','especialidade':'Código','executor':{'console':'codex'}}],
                        'merge':{'modo':'automatico','checks':['revisor-ia','sugestoes']}}

    def test_cadastro_explicitamente_preserva_projetos_config_privado_e_backup(self):
        inicio.aplicar(inicio.preparar(self.projeto,self.app,self.politica))
        cfg_arq=self.app/'config.json';cfg=json.loads(cfg_arq.read_text(encoding='utf-8'))
        cfg['campo_privado_usuario']={'sentinela':'SEGREDO-SINTETICO'};cfg['titulo']='Escritório próprio'
        cfg_arq.write_text(json.dumps(cfg),encoding='utf-8');antes=cfg_arq.read_bytes()
        outro=self.raiz/'outro';outro.mkdir()
        with self.assertRaises(ValueError):inicio.preparar(outro,self.app,self.politica)
        plano=inicio.preparar(outro,self.app,self.politica,cadastrar_projeto=True)
        self.assertTrue(plano['cadastro_novo']);self.assertEqual(cfg_arq.read_bytes(),antes)
        retorno=inicio.aplicar(plano);novo=json.loads(cfg_arq.read_text(encoding='utf-8'))
        self.assertTrue(retorno['projeto_cadastrado']);self.assertFalse(retorno['instalacao_criada'])
        self.assertEqual(novo['projetos'],cfg['projetos']+[str(outro.resolve())])
        for chave in set(cfg)-{'projetos'}:self.assertEqual(novo[chave],cfg[chave])
        self.assertEqual((self.app/'dados/historico-config'/f"{plano['config_versao']}.json").read_bytes(),antes)
        repetido=inicio.preparar(outro,self.app,self.politica,cadastrar_projeto=True)
        self.assertFalse(repetido['cadastro_novo']);ultimo=cfg_arq.read_bytes()
        self.assertFalse(inicio.aplicar(repetido)['projeto_cadastrado']);self.assertEqual(cfg_arq.read_bytes(),ultimo)
        self.assertEqual(json.loads((outro/'.office/projeto.json').read_text(encoding='utf-8'))['merge']['modo'],'automatico')

    def test_instalador_repetido_completa_entradas_do_projeto(self):
        inicio.aplicar(inicio.preparar(self.projeto,self.app,self.politica))
        politica=self.projeto/'.office/projeto.json';config=self.app/'config.json'
        antes=(politica.read_bytes(),config.read_bytes())
        (self.projeto/'AGENTS.md').unlink();(self.projeto/'GEMINI.md').unlink()
        arq=self.raiz/'politica.json';arq.write_text(json.dumps(self.politica),encoding='utf-8')
        cmd=[sys.executable,str(self.app/'iniciar_projeto.py'),'--projeto',str(self.projeto),
             '--destino',str(self.app),'--politica',str(arq)]
        previa=subprocess.run(cmd,capture_output=True,text=True,timeout=15)
        self.assertEqual(previa.returncode,0,previa.stderr)
        self.assertFalse((self.projeto/'AGENTS.md').exists())
        r=subprocess.run(cmd+['--aplicar'],capture_output=True,text=True,timeout=15)
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertTrue((self.projeto/'AGENTS.md').is_file());self.assertTrue((self.projeto/'GEMINI.md').is_file())
        self.assertEqual((politica.read_bytes(),config.read_bytes()),antes)

    def test_cadastro_rejeita_config_alterado_e_lock_sem_sobrescrever(self):
        inicio.aplicar(inicio.preparar(self.projeto,self.app,self.politica))
        outro=self.raiz/'outro';outro.mkdir();arq=self.app/'config.json'
        plano=inicio.preparar(outro,self.app,self.politica,cadastrar_projeto=True)
        original=arq.read_bytes();arq.write_bytes(original+b'\n')
        with self.assertRaises(ValueError):inicio.aplicar(plano)
        self.assertFalse((outro/'.office').exists());self.assertEqual(arq.read_bytes(),original+b'\n')
        arq.write_bytes(original);lock=self.app/'cadastro.edicao.lock';lock.write_text('externo')
        with self.assertRaises(ValueError):inicio.aplicar(plano)
        self.assertEqual(arq.read_bytes(),original);self.assertEqual(lock.read_text(),'externo')
        # Projeto preparado antes da falha de cadastro pode ser reutilizado sem sobrescrever.
        lock.unlink();novo=inicio.preparar(outro,self.app,self.politica,cadastrar_projeto=True)
        self.assertTrue(inicio.aplicar(novo)['projeto_cadastrado'])

    def test_cadastro_cli_previa_nao_publica_config_privado(self):
        inicio.aplicar(inicio.preparar(self.projeto,self.app,self.politica))
        arq=self.app/'config.json';cfg=json.loads(arq.read_text(encoding='utf-8'));cfg['privado']='SEGREDO-SINTETICO'
        arq.write_text(json.dumps(cfg),encoding='utf-8');antes=arq.read_bytes()
        outro=self.raiz/'outro';outro.mkdir();politica=self.raiz/'politica.json';politica.write_text(json.dumps(self.politica))
        saida=io.StringIO()
        with redirect_stdout(saida):codigo=inicio.main(['--projeto',str(outro),'--destino',str(self.app),'--politica',str(politica),'--cadastrar-projeto'])
        self.assertEqual(codigo,0);self.assertNotIn('SEGREDO-SINTETICO',saida.getvalue())
        self.assertIn('"cadastro_novo": true',saida.getvalue());self.assertEqual(arq.read_bytes(),antes)
        self.assertFalse((outro/'.office').exists())

    def test_editor_externo_durante_gravacao_preservado_e_temporarios_recolhidos(self):
        inicio.aplicar(inicio.preparar(self.projeto,self.app,self.politica))
        outro=self.raiz/'outro';outro.mkdir();arq=self.app/'config.json'
        plano=inicio.preparar(outro,self.app,self.politica,cadastrar_projeto=True)
        original=arq.read_bytes();externo=original+b'\n';sincronizar=inicio.os.fsync
        def editar(fd):
            sincronizar(fd);arq.write_bytes(externo)
        with patch.object(inicio.os,'fsync',side_effect=editar):
            with self.assertRaises(ValueError):inicio.aplicar(plano)
        self.assertEqual(arq.read_bytes(),externo)
        self.assertFalse((self.app/'cadastro.edicao.lock').exists())
        self.assertEqual(list(self.app.glob('cadastro-*.tmp')),[])
        self.assertEqual((self.app/'dados/historico-config'/f"{plano['config_versao']}.json").read_bytes(),original)

    def test_previa_instala_repete_sem_alterar_contas_dados_ou_politica(self):
        settings = self.projeto/'.claude/settings.json'; settings.parent.mkdir()
        settings.write_text('{"hook_do_usuario":true}',encoding='utf-8')
        plano = inicio.preparar(self.projeto,self.app,self.politica,8766)
        self.assertFalse(self.app.exists()); self.assertFalse((self.projeto/'.office').exists())
        with patch.object(instalar,'preparar_venv',side_effect=AssertionError('venv')), \
             patch.object(instalar,'instalar_hook',side_effect=AssertionError('hook')), \
             patch.object(instalar,'instalar_statusline',side_effect=AssertionError('statusline')), \
             patch.object(instalar,'abrir_escritorio',side_effect=AssertionError('processo')):
            retorno = inicio.aplicar(plano)
            self.assertTrue(retorno['instalacao_criada'])
            cfg = self.app/'config.json'; politica = self.projeto/'.office/projeto.json'
            self.assertEqual(json.loads(cfg.read_text(encoding='utf-8'))['projetos'],[str(self.projeto.resolve())])
            self.assertEqual(json.loads(politica.read_text(encoding='utf-8'))['merge']['modo'],'automatico')
            privado = self.app/'dados/privado.txt'; privado.write_text('preservar')
            antes = [p.read_bytes() for p in (cfg,politica,settings,privado)]
            repetido=inicio.preparar(self.projeto,self.app,self.politica,8766)
            self.assertEqual(inicio.aplicar(repetido)['arquivos_projeto'],[])
            self.assertEqual(antes,[p.read_bytes() for p in (cfg,politica,settings,privado)])

    def test_legado_bloqueado_antes_de_copiar_configurar_ou_hooks(self):
        self.app.mkdir(); antigo=self.app/'VERSION'; antigo.write_text('1.19.1')
        (self.app/'config.json').write_text('{"legado":true}')
        antes={p.name:p.read_bytes() for p in self.app.iterdir()}
        with self.assertRaises(ValueError): inicio.preparar(self.projeto,self.app,self.politica)
        with self.assertRaises(ValueError): instalar.copiar_pacote(self.app)
        with patch.object(instalar,'preparar_venv',side_effect=AssertionError('venv')):
            with self.assertRaises(ValueError): instalar.aplicar({'destino':str(self.app)},None)
        self.assertEqual(antes,{p.name:p.read_bytes() for p in self.app.iterdir()})
        self.assertFalse((self.projeto/'.office').exists())
        settings=self.raiz/'settings-teste.json'; settings.write_text('{"custom":true}')
        for flags in (['--desinstalar'],['--revisao',str(self.projeto)]):
            r=subprocess.run([sys.executable,str(Path(instalar.__file__)),*flags,
                              '--destino',str(self.app),'--sem-perguntas','--settings-usuario',str(settings)],
                             capture_output=True,text=True,encoding='utf-8',timeout=20)
            self.assertNotEqual(r.returncode,0)
            self.assertIn('pasta separada',r.stdout)
        self.assertEqual(settings.read_text(),'{"custom":true}')
        self.assertEqual(antes,{p.name:p.read_bytes() for p in self.app.iterdir()})

    def test_previa_existente_nao_publica_campos_privados_do_config(self):
        inicio.aplicar(inicio.preparar(self.projeto,self.app,self.politica))
        arq=self.app/'config.json'; cfg=json.loads(arq.read_text(encoding='utf-8'))
        cfg['campo_privado_usuario']='SEGREDO-SINTETICO'
        arq.write_text(json.dumps(cfg),encoding='utf-8'); antes=arq.read_bytes()
        politica=self.raiz/'politica.json'; politica.write_text(json.dumps(self.politica),encoding='utf-8')
        saida=io.StringIO()
        with redirect_stdout(saida):
            codigo=inicio.main(['--projeto',str(self.projeto),'--destino',str(self.app),'--politica',str(politica)])
        self.assertEqual(codigo,0)
        self.assertNotIn('SEGREDO-SINTETICO',saida.getvalue())
        self.assertNotIn('campo_privado_usuario',saida.getvalue())
        self.assertEqual(arq.read_bytes(),antes)
        (self.app/'servidor.py').unlink()
        with self.assertRaises(ValueError): inicio.preparar(self.projeto,self.app,self.politica)

    def test_marcador_invalido_versao_legada_e_pasta_pessoal(self):
        self.app.mkdir(); marcador=self.app/'EDICAO.json'
        for texto in ('[]','{}','{"edicao":"office-multi-provider","formato":true}'):
            marcador.write_text(texto)
            with self.assertRaises(ValueError): instalar.validar_edicao(self.app)
        marcador.write_text('{"edicao":"office-multi-provider","formato":1}')
        (self.app/'VERSION').write_text('1.19.1')
        with self.assertRaises(ValueError): instalar.validar_edicao(self.app)
        (self.app/'VERSION').unlink(); marcador.unlink()
        (self.app/'minhas-notas.txt').write_text('pessoal')
        with self.assertRaises(ValueError): inicio.preparar(self.projeto,self.app,self.politica)

    def test_previa_obsoleta_pasta_sobreposta_e_politica_invalida(self):
        with self.assertRaises(ValueError): inicio.preparar(self.projeto,self.projeto/'office',self.politica)
        with self.assertRaises(ValueError): inicio.preparar(self.projeto,self.app,self.politica,80)
        with self.assertRaises(ValueError): inicio.preparar(self.projeto,self.app,{'ativo':True})
        plano = inicio.preparar(self.projeto,self.app,self.politica)
        (self.projeto/'CLAUDE.md').write_text('novo contrato')
        with self.assertRaises(ValueError): inicio.aplicar(plano)
        self.assertFalse(self.app.exists())

    def test_cli_real_em_pasta_nova_marcador_e_atalhos(self):
        arq=self.raiz/'politica.json'; arq.write_text(json.dumps(self.politica),encoding='utf-8')
        comando=[sys.executable,str(Path(inicio.__file__)), '--projeto',str(self.projeto),
                 '--destino',str(self.app),'--politica',str(arq),'--porta','8766']
        for flags in ([],['--aplicar']):
            r=subprocess.run(comando+flags,capture_output=True,text=True,encoding='utf-8',timeout=30)
            self.assertEqual(r.returncode,0,r.stderr)
            self.assertEqual(self.app.exists(),bool(flags))
        self.assertTrue((self.app/'EDICAO.json').is_file())
        self.assertTrue((self.app/('abrir_escritorio.bat' if instalar.WINDOWS else 'abrir_escritorio.sh')).is_file())
        self.assertFalse((self.projeto/'.claude').exists())
        self.assertFalse((self.app/'.venv').exists())
        outro=self.raiz/'outro';outro.mkdir();politica_outro={**self.politica,'merge':{'modo':'manual','checks':[]}}
        arq.write_text(json.dumps(politica_outro),encoding='utf-8')
        comando_outro=[sys.executable,str(self.app/'iniciar_projeto.py'),'--projeto',str(outro),
                       '--destino',str(self.app),'--politica',str(arq),'--porta','8766','--cadastrar-projeto','--aplicar']
        r=subprocess.run(comando_outro,capture_output=True,text=True,encoding='utf-8',timeout=30)
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(len(json.loads((self.app/'config.json').read_text(encoding='utf-8'))['projetos']),2)
        script = r'''
import sys, json, threading, http.client
from pathlib import Path
from functools import partial
from http.server import ThreadingHTTPServer
app=Path(sys.argv[1]); sys.path.insert(0,str(app))
import servidor, rede, configuracao
assert Path(servidor.__file__).resolve().is_relative_to(app.resolve())
assert servidor.cfg()['titulo']=='Office Multi-provider'
assert servidor.cfg()['porta']==8766
servidor.Handler.rede=rede.Rede(app,False,False)
srv=ThreadingHTTPServer(('127.0.0.1',0),partial(servidor.Handler,directory=str(app)))
t=threading.Thread(target=srv.serve_forever,daemon=True); t.start()
con=http.client.HTTPConnection('127.0.0.1',srv.server_address[1],timeout=10)
try:
    con.request('GET','/api/gestao'); resposta=con.getresponse(); dados=json.loads(resposta.read())
    assert resposta.status==200
    assert len(dados['projetos'])==2
    projeto=dados['projetos'][0]
    assert projeto['ativo'] is True
    assert projeto['equipes'][0]['executor']['console']=='codex'
    assert projeto['merge']=='automatico'
    assert dados['projetos'][1]['merge']=='manual'
    con.request('GET','/'); resposta=con.getresponse(); assert resposta.status==200 and resposta.read()
finally:
    con.close(); srv.shutdown(); srv.server_close(); t.join()
'''
        env={k:v for k,v in os.environ.items() if not k.startswith('OFFICE_') and k!='PYTHONPATH'}
        r=subprocess.run([sys.executable,'-I','-c',script,str(self.app)],cwd=self.app,env=env,
                         capture_output=True,text=True,encoding='utf-8',timeout=30)
        self.assertEqual(r.returncode,0,r.stderr)


if __name__=='__main__': unittest.main()
