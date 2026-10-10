"""Processo real isolado e correlação sintética; sem inferência cloud."""
import contextlib
import io
import json
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from skills_execucao import EvidenciaClaude,conferir_worktree
from console_provider import executar
from providers_console import PROVIDERS


def fluxo():
    return [dict(type='system',subtype='init',tools=['Skill']),
            dict(type='assistant',message={'content':[{'type':'tool_use','id':'t1','name':'Skill','input':{'skill':'teste'}}]}),
            dict(type='user',message={'content':[{'type':'tool_result','tool_use_id':'t1','content':'instruções'}]}),
            dict(type='result',subtype='success',is_error=False)]


class SkillsExecucao(unittest.TestCase):
    def avaliar(self,registros):
        e=EvidenciaClaude(['teste'],'s')
        for r in registros: e.consumir({'session_id':'s',**r})
        return e.resumo()

    def test_correlacao_sem_copiar_conteudo(self):
        r=self.avaliar(fluxo());self.assertTrue(r['valida'])
        self.assertEqual(r['confirmadas'],['teste'])
        self.assertNotIn('instruções',json.dumps(r))

    def test_filho_outra_sessao_erro_nome_errado_resultado_sem_chamada(self):
        for modo in ('filho','sessao','erro','nome','sem-chamada','sem-fim','sem-tools'):
            f=fluxo()
            if modo=='filho':
                for r in f[1:3]:r['parent_tool_use_id']='pai'
            elif modo=='sessao':
                for r in f[1:3]:r['session_id']='outra'
            elif modo=='erro':f[2]['message']['content'][0]['is_error']=True
            elif modo=='nome':f[1]['message']['content'][0]['input']['skill']='outra'
            elif modo=='sem-chamada':f.pop(1)
            elif modo=='sem-fim':f.pop()
            elif modo=='sem-tools':f[0]['tools']=[]
            with self.subTest(modo=modo):self.assertFalse(self.avaliar(f)['valida'])

    def test_conflito_e_erro_de_turno_nao_viram_evidencia(self):
        f=fluxo();f.insert(3,dict(type='user',message={'content':[{'type':'tool_result','tool_use_id':'t1','is_error':True}]}))
        self.assertFalse(self.avaliar(f)['valida'])
        f=fluxo();f[-1]['is_error']=True;self.assertFalse(self.avaliar(f)['valida'])

    def test_processos_com_e_sem_chamada_retornam_evidencia(self):
        for chamada in (True,False):
            with self.subTest(chamada=chamada),tempfile.TemporaryDirectory() as tmp:
                raiz=Path(tmp);fake=raiz/'fake.py'
                registros=fluxo() if chamada else [fluxo()[0],fluxo()[-1]]
                fake.write_text('import sys,json,os\nsys.stdin.read()\nregistros='+repr(registros)+
                    '\nfor r in registros:\n r["session_id"]=os.environ["OFFICE_CLAUDE_STREAM_SESSION"]\n print(json.dumps(r),flush=True)\n',encoding='utf-8')
                recebidas=[]
                with patch('providers_console.comando_nativo',return_value=[sys.executable,str(fake)]),contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
                    codigo=executar(PROVIDERS['claude'],'claude',raiz,'Dev',prompt='teste',banco=raiz/'office.db',
                                    skills_nativas=['teste'],ao_skills=recebidas.append)
                self.assertEqual(codigo,0 if chamada else 1)
                self.assertEqual(recebidas[0]['valida'],chamada)

    def test_outro_provider_recusado_antes_de_iniciar(self):
        with tempfile.TemporaryDirectory() as tmp,patch('console_provider.subprocess.Popen') as popen:
            with self.assertRaisesRegex(ValueError,'Claude cloud'):
                executar(PROVIDERS['codex'],'codex',Path(tmp),'Dev',prompt='teste',skills_nativas=['teste'])
            popen.assert_not_called()

    def test_worktree_exige_mesma_fonte_nativa(self):
        with tempfile.TemporaryDirectory() as tmp:
            raiz=Path(tmp);arq=raiz/'.claude/skills/teste/SKILL.md'
            ref={'nome':'teste','ativacao_nativa':'Skill','sha256':hashlib.sha256(b'original').hexdigest()}
            with self.assertRaisesRegex(ValueError,'ausente'):conferir_worktree(raiz,[ref])
            arq.parent.mkdir(parents=True);arq.write_bytes(b'original')
            conferir_worktree(raiz,[ref])
            arq.write_bytes(b'mudou')
            with self.assertRaisesRegex(ValueError,'diverge'):conferir_worktree(raiz,[ref])
            conferir_worktree(raiz,[{'nome':'instrucao'}])


if __name__=='__main__':unittest.main()
