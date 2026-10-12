"""Gates de release com API/publicação simuladas; nunca cria uma release real."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qualificar_release as q
import build

SHA = 'a' * 40
TAG = 'v2.0.0-dev.6'


class Qualificacao(unittest.TestCase):
    def identidade(self, **trocas):
        args = dict(tag=TAG, sha=SHA, head=SHA, ci_resultado='success', ci_sha=SHA,
                    versao=TAG[1:], edicao=q.EDICAO)
        args.update(trocas)
        q.identidade(**args)

    def test_identidade_exata(self):
        self.identidade()

    def test_ci_ausente_falho_pendente_ignorado_ou_desconhecido(self):
        for estado in (None, '', 'failure', 'cancelled', 'skipped', 'pending', 'neutral', 'unknown'):
            with self.subTest(estado=estado), self.assertRaises(ValueError):
                self.identidade(ci_resultado=estado)

    def test_commit_tag_edicao_e_canal(self):
        for args in ({'ci_sha':None}, {'ci_sha':'b'*40}, {'head':'b'*40}, {'sha':''},
                     {'tag':'v2.0.0-dev.7'}, {'edicao':{}}, {'versao':'2.0.0'},
                     {'versao':'1.19.1'}, {'versao':'2.0.0-../../x'}):
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.identidade(**args)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.raiz = Path(self.tmp.name)
        (self.raiz/'VERSION').write_text(TAG[1:]+'\n')
        (self.raiz/'EDICAO.json').write_text(json.dumps(q.EDICAO))
        self.arquivos = ['VERSION','EDICAO.json']
        self.zip, _ = build.gerar(self.raiz, self.arquivos, self.raiz/'dist', 'office-multi-provider-'+TAG)
        self.checksum = self.zip.with_suffix('.zip.sha256')
        self.manifesto = patch.object(build, 'arquivos_pacote', return_value=self.arquivos)
        self.manifesto.start(); self.addCleanup(self.manifesto.stop)

    def test_pacote_exato(self):
        self.assertEqual(q.pacote(self.raiz,TAG), (self.zip,self.checksum))

    def test_checksum_incorreto(self):
        self.checksum.write_text('0'*64+'  '+self.zip.name+'\n')
        with self.assertRaises(ValueError): q.pacote(self.raiz,TAG)

    def reescrever(self, entradas):
        with zipfile.ZipFile(self.zip,'w') as z:
            for nome, valor in entradas: z.writestr(nome,valor)
        self.checksum.write_text(hashlib.sha256(self.zip.read_bytes()).hexdigest()+'  '+self.zip.name+'\n')

    def test_versao_errada_e_conteudo_adulterado(self):
        raiz=self.zip.stem+'/'
        self.reescrever([(raiz+'VERSION','2.0.0-dev.99'), (raiz+'EDICAO.json',json.dumps(q.EDICAO))])
        with self.assertRaises(ValueError): q.pacote(self.raiz,TAG)

    def test_raiz_errada_caminho_extra_e_duplicado(self):
        raiz=self.zip.stem+'/'
        originais=[(raiz+f,(self.raiz/f).read_bytes()) for f in self.arquivos]
        for extras in ([('../escape','x')], [('outra-raiz/VERSION',TAG)], [(raiz+'config.json','privado')]):
            with self.subTest(extras=extras):
                self.reescrever(originais+extras)
                with self.assertRaises(ValueError): q.pacote(self.raiz,TAG)
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter('ignore',UserWarning)
            self.reescrever(originais+[originais[0]])
        with self.assertRaises(ValueError): q.pacote(self.raiz,TAG)

    def test_link_simbolico_bloqueado(self):
        raiz=self.zip.stem+'/'
        info=zipfile.ZipInfo(raiz+'VERSION'); info.create_system=3; info.external_attr=0o120777<<16
        self.reescrever([(info,(self.raiz/'VERSION').read_bytes()),
                         (raiz+'EDICAO.json',(self.raiz/'EDICAO.json').read_bytes())])
        with self.assertRaises(ValueError): q.pacote(self.raiz,TAG)

    def simular(self, existente=None, ref=None, erro=None):
        chamadas=[]
        if ref is None: ref={'ref':'refs/tags/'+TAG,'object':{'type':'commit','sha':SHA}}
        def executar(args):
            chamadas.append(args)
            if args[:2]==['gh','api']:
                if '/releases/tags/' in args[-1]:
                    if erro: raise erro
                    if existente is None:
                        raise subprocess.CalledProcessError(1,args,output='HTTP/2.0 404 Not Found\n\n{}')
                    return 'HTTP/2.0 200 OK\r\n\r\n'+json.dumps(existente)
                return 'HTTP/2.0 200 OK\n\n'+json.dumps(ref)
            return ''
        with patch.dict(os.environ,{'GITHUB_REPOSITORY':'leonidasgomes/claude-office-3d'}):
            q.publicar(self.raiz,TAG,SHA,self.zip,self.checksum,executar)
        return chamadas

    def test_criacao_exata_sem_latest_ou_wildcards(self):
        chamadas=self.simular(); cmd=chamadas[-1]
        self.assertEqual(cmd[:4],['gh','release','create',TAG])
        for flag in ('--prerelease','--latest=false','--verify-tag',str(self.zip),str(self.checksum)):
            self.assertIn(flag,cmd)
        self.assertFalse(any('*' in p for p in cmd))

    def test_completa_somente_previa_vazia(self):
        existente={'tag_name':TAG,'draft':False,'prerelease':True,'assets':[]}
        cmds=self.simular(existente)
        self.assertEqual([c[2] for c in cmds if c[:2]==['gh','release']],['upload','edit'])
        self.assertNotIn('--clobber',str(cmds))
        self.assertIn('--latest=false',cmds[-1])
        for alteracao in ({'tag_name':'v2.0.0-dev.5'},{'draft':True},{'prerelease':False},{'assets':[{}]}):
            with self.subTest(alteracao=alteracao),self.assertRaises(ValueError):
                self.simular(dict(existente,**alteracao))

    def test_tag_remota_errada_ausente_ou_anotada(self):
        for ref in ({}, {'ref':'refs/tags/'+TAG,'object':{'type':'commit','sha':'b'*40}},
                    {'ref':'refs/tags/'+TAG,'object':{'type':'tag','sha':SHA}}):
            with self.subTest(ref=ref), self.assertRaises(ValueError): self.simular(ref=ref)

    def test_erro_api_nao_e_release_ausente(self):
        for resposta in ('', 'HTTP/2.0 403 Forbidden\n\n{}', 'HTTP/2.0 500 Error\n\n{}'):
            erro=subprocess.CalledProcessError(1,['gh'],output=resposta)
            with self.subTest(resposta=resposta),self.assertRaises(subprocess.CalledProcessError):
                self.simular(erro=erro)

    def test_api_malformada_bloqueia(self):
        for resposta in ('{}','HTTP/2.0 200 OK\n\nnull','HTTP/2.0 202 OK\n\n{}'):
            with self.assertRaises(ValueError): q.api('x',lambda args:resposta)

    def test_agregador_exige_todos_os_jobs_sem_estado_ambiguo(self):
        import textwrap
        ci=(q.RAIZ/'.github/workflows/ci.yml').read_text()
        codigo=textwrap.dedent(ci.rsplit("python - <<'PY'\n",1)[1].rsplit('          PY',1)[0])
        bons={nome:{'result':'success'} for nome in ('verificar','preparar-windows','compatibilidade_python')}
        casos=[(bons,True), ({},False)]
        for nome in bons:
            for estado in ('failure','cancelled','skipped','unknown',None):
                casos.append((dict(bons,**{nome:{'result':estado}}),False))
        for resultados, sucesso in casos:
            with self.subTest(resultados=resultados):
                saida=self.raiz/'output'
                saida.unlink(missing_ok=True)
                env=dict(os.environ,RESULTADOS=json.dumps(resultados),SHA=SHA,GITHUB_OUTPUT=str(saida))
                r=subprocess.run([sys.executable,'-c',codigo],env=env,capture_output=True,text=True)
                self.assertEqual(r.returncode==0,sucesso,r.stderr)
                self.assertEqual(saida.exists(),sucesso)
                if sucesso: self.assertEqual(saida.read_text(),'sha='+SHA+'\n')

    def test_smoke_falho_bloqueia_e_nao_herda_credenciais(self):
        with patch.dict(os.environ,{'GH_TOKEN':'teste','GITHUB_TOKEN':'teste','OFFICE_TESTE':'teste','PYTHONOPTIMIZE':'1'}):
            with patch.object(q.subprocess,'run',side_effect=subprocess.CalledProcessError(1,['python'])) as run:
                with self.assertRaises(subprocess.CalledProcessError): q.smoke(self.zip)
                self.assertIn('-I',run.call_args.args[0])
                env=run.call_args.kwargs['env']
                for nome in ('GH_TOKEN','GITHUB_TOKEN','OFFICE_TESTE','PYTHONOPTIMIZE'): self.assertNotIn(nome,env)
                self.assertNotIn('assert ',q.SMOKE)

    def test_smoke_timeout_bloqueia(self):
        with patch.object(q.subprocess,'run',side_effect=subprocess.TimeoutExpired(['python'],40)):
            with self.assertRaises(subprocess.TimeoutExpired): q.smoke(self.zip)

    def test_workflow_reutiliza_e_nao_contorna_ci(self):
        raiz=Path(__file__).resolve().parent.parent
        ci=(raiz/'.github/workflows/ci.yml').read_text()
        release=(raiz/'.github/workflows/release.yml').read_text()
        self.assertIn('workflow_call:',ci)
        self.assertIn("v.get('result') != 'success'",ci)
        self.assertIn('needs: [verificar, preparar-windows, compatibilidade_python]',ci)
        self.assertIn('uses: ./.github/workflows/ci.yml',release)
        self.assertIn('needs: qualificar',release)
        self.assertIn("needs.qualificar.result == 'success'",release)
        self.assertIn('needs.qualificar.outputs.tested_sha == github.sha',release)
        self.assertNotIn('continue-on-error',release)
        self.assertNotIn('workflow_dispatch',release)
        self.assertNotIn('upload-artifact',release)
        self.assertIn('ref: ${{ github.sha }}',release)


if __name__=='__main__': unittest.main()
