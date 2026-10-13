"""Identidade e lifecycle concorrentes sem contas, modelos ou hooks globais."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from providers_console import Eventos


def inicio(provider, session):
    return {'claude': {'type':'system','subtype':'init','session_id':session},
            'codex': {'type':'thread.started','thread_id':session},
            'opencode': {'type':'step_start','sessionID':session}}[provider]


class Sessoes(unittest.TestCase):
    def test_identidade_nao_muda_com_init_de_outro_fluxo(self):
        for provider in ('claude','codex','opencode'):
            with self.subTest(provider=provider):
                a=Eventos(provider,'Dev',inicio_vinculado=True)
                b=Eventos(provider,'Dev',inicio_vinculado=True)
                self.assertEqual(a.converter(inicio(provider,'sessao-a'))[0]['sessao'],'sessao-a')
                self.assertEqual(b.converter(inicio(provider,'sessao-b'))[0]['sessao'],'sessao-b')
                self.assertEqual(a.converter(inicio(provider,'sessao-b')),[])
                self.assertEqual(a.sessao,'sessao-a')
                self.assertEqual(a.converter(inicio(provider,'sessao-a')),[])

    def test_codex_ferramenta_falha_nao_vira_sucesso_do_turno(self):
        e=Eventos('codex','Dev',inicio_vinculado=True)
        e.converter(inicio('codex','s'))
        item={'id':'cmd1','type':'command_execution','command':'read artificial.txt'}
        self.assertEqual(e.converter({'type':'item.started','item':item})[0]['operacao_estado'],'executando')
        item.update(exit_code=-1,status='failed',aggregated_output='setup refresh had errors')
        result=e.converter({'type':'item.completed','item':item})[0]
        self.assertFalse(result['ok'])
        self.assertEqual(result['codigo'],-1)
        self.assertEqual(result['erro'],'setup refresh had errors')
        self.assertNotIn('ok',e.converter({'type':'turn.completed'})[0])
        fail=e.converter({'type':'turn.failed','error':{'message':'aborted'}})
        self.assertFalse(fail[0]['ok'])
        self.assertEqual(fail[0]['erro'],'aborted')

    def test_claude_ids_inicio_resultado_e_filho_isolado(self):
        e=Eventos('claude','Dev')
        e.converter(inicio('claude','parent'))
        item={'type':'tool_use','id':'read-1','name':'Read','input':{'file_path':'artificial.txt'}}
        start=e.converter({'type':'assistant','session_id':'parent','message':{'id':'m','content':[item]}})[0]
        end=e.converter({'type':'user','session_id':'parent','message':{'id':'r','content':[{'type':'tool_result','tool_use_id':'read-1','is_error':True}]}})[0]
        self.assertEqual(start['operacao_id'],end['operacao_id'])
        self.assertFalse(end['ok'])
        self.assertEqual(e.converter({'type':'system','subtype':'init','session_id':'child','parent_tool_use_id':'read-1'}),[])
        self.assertEqual(e.sessao,'parent')

    def test_opencode_ids_e_session_mismatch(self):
        e=Eventos('opencode','Dev')
        e.converter(inicio('opencode','s'))
        event={'type':'tool_use','sessionID':'s','part':{'id':'p','callID':'call','tool':'read','state':{'status':'running'}}}
        self.assertEqual(e.converter(event)[0]['operacao_id'],'call')
        event['part']['state']={'status':'error','error':'failed'}
        self.assertFalse(e.converter(event)[0]['ok'])
        event['sessionID']='other'
        self.assertEqual(e.converter(event),[])


if __name__=='__main__':unittest.main()
