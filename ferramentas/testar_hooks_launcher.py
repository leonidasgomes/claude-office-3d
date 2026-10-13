"""Subprocesso real com envelopes sintéticos; nenhum CLI cloud ou hook global."""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
RAIZ=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(RAIZ))
from console_provider import executar
from providers_console import PROVIDERS
from funcionarios import id_projeto


class LauncherHooks(unittest.TestCase):
    def run_fake(self, native):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);db=root/'eventos.db'
            b=dict(enabled=True,provider='codex',version='0.162.1',project=str(root),project_id=id_projeto(root),
                   session_id='s',origin='fixture',agent='Dev',hooks_active=True,hooks_trusted=True)
            cap=dict(version_verified=True,version='0.162.1',mechanism='hooks',
                     events=['SessionStart','SessionEnd','PreToolUse','PostToolUse'])
            script=root/'fixture.py'
            records=[{'type':'thread.started','thread_id':'s'},{'type':'turn.started'},
                     {'type':'item.started','item':{'type':'command_execution','id':'item_0','command':'read artificial.txt'}},
                     {'type':'item.completed','item':{'type':'command_execution','id':'item_0','command':'read artificial.txt','exit_code':0}},
                     {'type':'turn.completed'}]
            text='import sys,json\nsys.stdin.read()\nsys.path.insert(0,'+repr(str(RAIZ))+')\n'
            if native:
                text+='from hooks_providers import ingest\nb='+repr(b)+'\n'
                # Hook call ID is deliberately different from exec item_0.
                for phase in ('SessionStart','PreToolUse','PostToolUse','SessionEnd'):
                    payload=dict(session_id='s',cwd=str(root),hook_event_name=phase,tool_use_id='native_call',
                                 tool_name='Bash',tool_response={'exit_code':0})
                    text+='ingest('+repr(str(db))+',b,'+repr(payload)+')\n'
            text+='for r in '+repr(records)+': print(json.dumps(r),flush=True)\n'
            script.write_text(text,encoding='utf-8')
            with patch.dict(os.environ,{'CODEX_HOME':str(root/'codex-home')}), patch.object(type(PROVIDERS['codex']),'comando',return_value=[sys.executable,str(script),'-']):
                code=executar(PROVIDERS['codex'],sys.executable,root,'Dev',prompt='artificial',banco=db,
                              hook_binding=b,hook_capability=cap)
            with closing(sqlite3.connect(db)) as c:
                events=[json.loads(x[0]) for x in c.execute('SELECT dados FROM evento')]
            return code,events

    def test_native_hooks_authority_with_different_exec_ids(self):
        code,events=self.run_fake(True)
        self.assertEqual(code,0)
        tools=[e for e in events if e.get('hook_fase') in ('tool_start','tool_end')]
        self.assertEqual(len(tools),2)
        self.assertTrue(all(e['operacao_id']=='native_call' for e in tools))
        self.assertFalse(any(e.get('operacao_id')=='item_0' for e in events))

    def test_missing_native_events_never_claims_coverage(self):
        code,events=self.run_fake(False)
        self.assertEqual(code,1)
        self.assertTrue(any(e.get('ok') is False and 'native_coverage' in e.get('erro','') for e in events))


if __name__=='__main__':unittest.main()
