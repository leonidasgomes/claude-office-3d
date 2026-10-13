"""Synthetic project-scoped native hook/JSON contract; no model or global config."""
import concurrent.futures
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hooks_providers import ingest, ingest_normalized, normalize, plan, prefer_hooks, receiver_command
from funcionarios import id_projeto


class Hooks(unittest.TestCase):
    def test_comando_cotado_para_shell_verificado(self):
        import shlex
        with tempfile.TemporaryDirectory(prefix='hook command ') as tmp:
            root=Path(tmp)
            paths=[root/'python.exe',root/'receiver.py',root/'binding file.json',root/'events.db']
            command=receiver_command(*paths,shell='bash')
            self.assertNotIn('\\',command)
            parsed=shlex.split(command)
            self.assertEqual(parsed[0],paths[0].as_posix())
            self.assertEqual(parsed[3],paths[2].as_posix())
            self.assertTrue(receiver_command(*paths,shell='powershell').startswith('& '))
            self.assertIn('"',receiver_command(*paths,shell='cmd'))
            with self.assertRaises(ValueError):receiver_command(*paths,shell='auto')
            with self.assertRaises(ValueError):receiver_command('relative.exe',*paths[1:])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db = self.root / 'office.db'
        self.b = dict(enabled=True, provider='codex', version='0.162.1',
                      project=str(self.root), project_id=id_projeto(self.root),
                      session_id='session-a', origin='test', agent='Dev')

    def payload(self, event='PostToolUse', **extra):
        return dict(session_id=self.b['session_id'], cwd=str(self.root),
                    hook_event_name=event, tool_use_id='op-1', tool_name='Read', **extra)

    def events(self):
        with closing(sqlite3.connect(self.db)) as conn:
            return [json.loads(r[0]) for r in conn.execute('SELECT dados FROM evento')]

    def test_three_providers_lifecycle_unknown_and_failure(self):
        for provider in ('claude', 'codex', 'opencode'):
            b = dict(self.b, provider=provider)
            for event in ('SessionStart', 'PreToolUse', 'PostToolUse', 'Stop', 'SessionEnd'):
                self.assertEqual(ingest(self.db, b, self.payload(event)), 'inserted')
            self.assertEqual(ingest(self.db, b, self.payload(tool_response={'exit_code': -1}), 'json'), 'failure_updated')
        events = self.events()
        self.assertEqual(len(events), 18)
        ends = [e for e in events if e.get('hook_correction')]
        self.assertTrue(all(e['ok'] is False and e['codigo'] == -1 for e in ends))

    def test_restart_dedup_and_no_failure_downgrade(self):
        p = self.payload(tool_response={'exit_code': -1})
        ingest(self.db, self.b, p)
        self.assertEqual(ingest(self.db, dict(self.b), p, 'json'), 'duplicate')
        self.assertEqual(ingest(self.db, self.b, self.payload(exit_code=0)), 'duplicate')
        self.assertFalse(self.events()[0]['ok'])

    def test_fail_closed(self):
        for extra in ({'provider': 'claude'}, {'session_id': 'other'}, {'cwd': str(self.root/'child')}, {'origin': 'other'}, {'project_id': 'a'*20}):
            p = self.payload(); p.update(extra)
            with self.assertRaises(ValueError):
                normalize(self.b, p)
        with self.assertRaises(ValueError):
            normalize(dict(self.b, enabled=False), self.payload())
        p = self.payload(); p.pop('tool_use_id')
        with self.assertRaises(ValueError):
            normalize(self.b, p)

    def test_concurrent_sessions_same_operation(self):
        # Initialize schema before exercising concurrent transactional writers.
        ingest(self.db, self.b, self.payload('SessionStart'))
        def write(i):
            b = dict(self.b, session_id='s'+str(i % 4))
            p = self.payload(); p['session_id'] = b['session_id']
            return ingest(self.db, b, p, 'json' if i % 2 else 'hook')
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(write, range(20)))
        self.assertEqual(results.count('inserted'), 4)
        self.assertEqual(len(self.events()), 5)

    def test_merge_preview_preserves_hooks_and_capability(self):
        existing = {'env': {'KEEP': 'yes'}, 'hooks': {'Stop': [{'user': 'existing'}]}}
        capability = dict(version_verified=True, version='0.162.1', mechanism='hooks',
                          events=['SessionStart', 'PreToolUse', 'PostToolUse', 'Stop', 'SessionEnd'])
        result = plan(self.b, 'receiver', capability, existing)
        self.assertNotIn('PostToolUseFailure', result['config']['hooks'])
        self.assertEqual(result['config']['env'], existing['env'])
        self.assertEqual(plan(self.b, 'receiver', capability, result['config'])['config'], result['config'])
        self.assertFalse(result['apply'])
        self.assertEqual(plan(self.b, 'receiver', {})['mechanism'], 'json')
        self.assertEqual(plan(dict(self.b, provider='opencode'), 'receiver',
                              dict(capability, mechanism='plugin'))['mechanism'], 'plugin')
        self.assertFalse(prefer_hooks(self.b, capability, 'tool_end'))
        self.assertFalse(prefer_hooks(dict(self.b, hooks_active=True), capability, 'tool_end'))
        self.assertTrue(prefer_hooks(dict(self.b, hooks_active=True, hooks_trusted=True), capability, 'tool_end'))

    def test_pin_new_session_by_origin_survives_restart(self):
        b = dict(self.b, session_id=None, allow_new_session=True)
        with self.assertRaises(ValueError):
            ingest(self.db, b, self.payload())
        self.assertEqual(ingest(self.db, b, self.payload('SessionStart')), 'inserted')
        self.assertEqual(ingest(self.db, b, self.payload()), 'inserted')
        p = self.payload(); p['session_id'] = 'session-b'
        with self.assertRaises(ValueError):
            ingest(self.db, b, p)
        p['hook_event_name'] = 'SessionStart'
        self.assertEqual(ingest(self.db, dict(b, origin='other'), p), 'inserted')

    def test_json_bridge_dedup_and_codex_text_nonzero(self):
        p = self.payload(tool_response='command output\nProcess exited with code 7')
        ingest(self.db, self.b, p)
        event = dict(sessao=self.b['session_id'], fonte='codex', hook_fase='tool_end',
                     operacao_id='op-1', ferramenta='Read', codigo=7, ok=False)
        self.assertEqual(ingest_normalized(self.db, self.b, event), 'duplicate')
        self.assertFalse(self.events()[0]['ok'])
        self.assertEqual(self.events()[0]['codigo'], 7)

    def test_binding_project_and_version_not_trusted(self):
        for b in (dict(self.b, project_id='a'*20), dict(self.b, version='latest'),
                  dict(self.b, version='0.162.1\nmalformed')):
            with self.assertRaises(ValueError):
                normalize(b, self.payload())
        for project in ('relative', str(self.root / 'absent')):
            with self.assertRaises(ValueError):
                normalize(dict(self.b, project=project), self.payload())

    def test_stop_without_native_identity_not_collapsed(self):
        p = self.payload('Stop'); p.pop('tool_use_id')
        ingest(self.db, self.b, p)
        ingest(self.db, self.b, p)
        self.assertEqual(len(self.events()), 2)
        self.assertTrue(all(e['hook_dedup'] == 'unavailable_without_native_id' for e in self.events()))

    def test_stdin_receiver_persists_and_rejects_oversize(self):
        config = self.root / 'binding.json'
        config.write_text(json.dumps(self.b), encoding='utf-8')
        module = Path(__file__).resolve().parent.parent / 'hooks_providers.py'
        command = [sys.executable, str(module), '--binding', str(config), '--database', str(self.db)]
        result = subprocess.run(command, input=json.dumps(self.payload(exit_code=0)),
                                text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.events()[0]['ok'])
        result = subprocess.run(command, input=' ' * 262145, text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 2)
        self.assertIn('256 KiB', result.stderr)


if __name__ == '__main__':
    unittest.main()
