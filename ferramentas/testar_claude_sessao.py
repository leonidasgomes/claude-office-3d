"""Transcritos temporários; não chama modelos nem altera o Claude da máquina."""
from datetime import datetime,timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from claude_sessao import Observador


class Sessoes(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.raiz=Path(self.tmp.name); self.projeto=self.raiz/'worktree'; self.projeto.mkdir()
        self.config=self.raiz/'claude-config'
        self.observador=Observador(self.projeto,self.config,inicio=1)
        self.pasta=self.observador.pasta; self.pasta.mkdir(parents=True)

    def escrever(self,ident=None,**campos):
        ident=ident or str(uuid.uuid4())
        d={'type':'user','sessionId':ident,'cwd':str(self.projeto),'isSidechain':False,
           'timestamp':datetime.now(timezone.utc).isoformat(),**campos}
        with (self.pasta/(ident+'.jsonl')).open('a',encoding='utf-8') as f: f.write(json.dumps(d)+'\n')
        return ident

    def test_sessao_nova_principal_sem_conteudo_ou_alterar_arquivo(self):
        ident=self.escrever(); arq=self.pasta/(ident+'.jsonl'); antes=arq.read_bytes()
        self.assertEqual(self.observador.consultar(),ident)
        self.assertEqual(self.observador.consultar(),ident); self.assertEqual(arq.read_bytes(),antes)

    def test_historico_anterior_inclusive_novas_linhas_nao_e_nova_sessao(self):
        ident=self.escrever()
        obs=Observador(self.projeto,self.config,inicio=1)
        self.escrever(ident)
        self.assertIsNone(obs.consultar())
        novo=self.escrever(); self.assertEqual(obs.consultar(),novo)

    def test_outro_cwd_subagente_horario_antigo_nao_identificam(self):
        self.escrever(cwd=str(self.raiz/'outro'))
        self.escrever(isSidechain=True)
        self.escrever(agentId='colega')
        self.escrever(timestamp='1970-01-01T00:00:00+00:00')
        self.escrever(timestamp='2026-10-09T00:00:00')
        self.assertIsNone(self.observador.consultar())

    def test_duas_sessoes_novas_sao_ambiguidade(self):
        self.escrever(); self.escrever()
        with self.assertRaisesRegex(ValueError,'Mais de uma sessão'): self.observador.consultar()

    def test_linha_parcial_e_nome_incompativel_nao_inventam_id(self):
        (self.pasta/'incompleto.jsonl').write_text('{"type":"user"',encoding='utf-8')
        ident=self.escrever(); (self.pasta/(ident+'.jsonl')).rename(self.pasta/'nome-errado.jsonl')
        self.assertIsNone(self.observador.consultar())

    def test_resume_observa_so_novas_linhas_do_id_exato(self):
        ident=self.escrever(); obs=Observador(self.projeto,self.config,inicio=1,sessao=ident)
        self.assertIsNone(obs.consultar())
        self.escrever(); self.escrever(ident)
        self.assertEqual(obs.consultar(),ident)

    def test_prompt_do_despacho_confere_a_correlacao_sem_busca_por_trecho(self):
        obs=Observador(self.projeto,self.config,inicio=1,prompt='Tarefa única')
        self.escrever(message={'content':'Outra sessão no mesmo cwd'})
        self.escrever(message={'content':'Eco: Tarefa única'})
        self.escrever(message={'content':'Tarefa única'},isMeta=True)
        self.assertIsNone(obs.consultar())
        ident=self.escrever(message={'content':[{'type':'text','text':'Tarefa única'}]})
        self.assertEqual(obs.consultar(),ident)

    def test_compatibilidade_provider_sem_stream_vincula_transcrito(self):
        from dataclasses import replace
        from console_provider import executar
        from providers_console import PROVIDERS
        from skills_compartilhados import contexto
        fake=self.raiz/'fake.py'; ident=str(uuid.uuid4())
        fake.write_text('from pathlib import Path\nimport json\nfrom datetime import datetime,timezone\n'
            +'p=Path('+repr(str(self.pasta/(ident+'.jsonl')))+')\n'
            +'d='+repr({'type':'user','sessionId':ident,'cwd':str(self.projeto),'isSidechain':False,
                       'message':{'content':contexto(self.projeto)+'\n\nTarefa:\ntarefa'}})+'\n'
            +'d["timestamp"]=datetime.now(timezone.utc).isoformat()\np.write_text(json.dumps(d)+"\\n",encoding="utf-8")\n',encoding='utf-8')
        recebidos=[]
        legado=replace(PROVIDERS['claude'],capacidades=replace(PROVIDERS['claude'].capacidades,eventos_json=False))
        with patch('claude_sessao.os.environ',{'CLAUDE_CONFIG_DIR':str(self.config)}), \
             patch.object(type(PROVIDERS['claude']),'comando',return_value=[sys.executable,str(fake),'prompt']) as comando:
            self.assertEqual(executar(legado,sys.executable,self.projeto,'Dev',prompt='tarefa',
                                     banco=self.raiz/'office.db',ao_sessao=recebidos.append),0)
        self.assertEqual(recebidos,[ident]); self.assertTrue(comando.call_args.args[2].endswith('tarefa'))


if __name__=='__main__': unittest.main()
