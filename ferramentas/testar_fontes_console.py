"""Fontes externas explícitas: isolamento, restart, cauda e troca de arquivo."""
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
import io
from contextlib import redirect_stderr
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fontes_console import sincronizar, main
from funcionarios import id_projeto


class Fontes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.raiz = Path(self.tmp.name); self.db = self.raiz / 'eventos.db'
        self.config = {'fontes': []}

    def fonte(self, provider, sessao='s', formato='native', historico=False):
        projeto = self.raiz / (provider + sessao); projeto.mkdir()
        arquivo = self.raiz / (provider + sessao + '.jsonl')
        f = dict(origem=provider + sessao, provider=provider, projeto=str(projeto), sessao=sessao,
                 mesa='Dev-' + sessao, arquivo=str(arquivo), formato=formato, historico=historico)
        header = dict(type='office_session', provider=provider, sessao=sessao, cwd=str(projeto))
        if formato == 'codex_rollout': header = dict(type='session_meta', payload=dict(id=sessao, cwd=str(projeto)))
        if formato == 'hooks': header = self.hook(f, 'h1')
        arquivo.write_text(json.dumps(header) + '\n', encoding='utf-8')
        self.config['fontes'].append(f)
        return f

    def hook(self, f, ident):
        return dict(tipo='trabalho', fonte=f['provider'], sessao=f['sessao'], projeto=f['projeto'],
                    agente='ignored', ferramenta='Read', operacao_id='read', operacao_estado='concluido', evento_id=ident)

    def append(self, f, r):
        with Path(f['arquivo']).open('a', encoding='utf-8') as h: h.write(json.dumps(r) + '\n')

    def eventos(self):
        with closing(sqlite3.connect(self.db)) as d: return [json.loads(r[0]) for r in d.execute('SELECT dados FROM evento')]

    def test_tres_providers_concorrentes_restart(self):
        fontes = [self.fonte(p) for p in ('claude', 'codex', 'opencode')]
        sincronizar(self.config, self.db)
        for f in fontes:
            p = f['provider']; s = f['sessao']
            registro = {'claude': dict(type='result', session_id=s, subtype='success'),
                        'codex': dict(type='turn.completed'),
                        'opencode': dict(type='step_finish', sessionID=s, part=dict(reason='stop'))}[p]
            self.append(f, registro)
        sincronizar(self.config, self.db)
        n = len(self.eventos()); self.assertGreater(n, 3)
        self.assertEqual(sum(x['importados'] for x in sincronizar(self.config, self.db)), 0)
        self.assertEqual(len(self.eventos()), n)
        self.assertEqual({e['fonte'] for e in self.eventos()}, {'claude', 'codex', 'opencode'})

    def test_mismatch_atomico_sessao_provider_projeto(self):
        for campo, valor in [('sessao', 'outra'), ('provider', 'claude'), ('cwd', str(self.raiz))]:
            with self.subTest(campo=campo):
                self.config = {'fontes': []}; f = self.fonte('codex', campo)
                sincronizar(self.config, self.db); antes = len(self.eventos())
                self.append(f, dict(type='office_session', **{campo: valor}))
                with self.assertRaises(ValueError): sincronizar(self.config, self.db)
                self.assertEqual(len(self.eventos()), antes)

    def test_partial_nao_perde_linha(self):
        f = self.fonte('codex'); sincronizar(self.config, self.db)
        with Path(f['arquivo']).open('ab') as h: h.write(b'{"type":"turn.completed"')
        self.assertEqual(sincronizar(self.config, self.db)[0]['importados'], 0)
        with Path(f['arquivo']).open('ab') as h: h.write(b'}\n')
        self.assertEqual(sincronizar(self.config, self.db)[0]['importados'], 1)

    def test_substituicao_e_truncamento_fechados(self):
        f = self.fonte('codex'); sincronizar(self.config, self.db)
        a = Path(f['arquivo']); outro = a.with_suffix('.outro'); outro.write_bytes(a.read_bytes()); outro.replace(a)
        with self.assertRaises(ValueError): sincronizar(self.config, self.db)

    def test_hooks_ids_dedup_e_historico(self):
        f = self.fonte('opencode', formato='hooks', historico=True)
        sincronizar(self.config, self.db); self.append(f, self.hook(f, 'h1'))
        self.assertEqual(sincronizar(self.config, self.db)[0]['importados'], 0)
        self.assertTrue(any(e.get('evento_id') == 'h1' for e in self.eventos()))

    def test_rollout_estado_tool_preservado_restart(self):
        f = self.fonte('codex', formato='codex_rollout'); sincronizar(self.config, self.db)
        self.append(f, dict(type='response_item', payload=dict(type='function_call', call_id='c1', name='exec_command', arguments='{"cmd":"echo"}')))
        sincronizar(self.config, self.db)
        self.append(f, dict(type='response_item', payload=dict(type='function_call_output', call_id='c1', output='Exit code: -1')))
        sincronizar(self.config, self.db)
        self.assertTrue(any(e.get('codigo') == -1 and e.get('ok') is False for e in self.eventos()))

    def test_identidade_inicial_obrigatoria(self):
        f = self.fonte('codex'); Path(f['arquivo']).write_text('{"type":"thread.started","thread_id":"s"}\n')
        with self.assertRaises(ValueError): sincronizar(self.config, self.db)

    def test_concorrencia_mesmo_provider_projetos_distintos(self):
        a = self.fonte('codex', 'a'); b = self.fonte('codex', 'b')
        sincronizar(self.config, self.db)
        for f in (a, b):
            self.append(f, dict(type='item.started', item=dict(type='command_execution', id='igual', command='echo')))
        sincronizar(self.config, self.db)
        ferramentas = [e for e in self.eventos() if e.get('operacao_id') == 'igual']
        self.assertEqual(len(ferramentas), 2)
        self.assertEqual({e['sessao'] for e in ferramentas}, {'a', 'b'})

    def test_linha_invalida_nao_avanca_cursor(self):
        f = self.fonte('codex'); r = sincronizar(self.config, self.db)[0]
        with Path(f['arquivo']).open('ab') as h: h.write(b'{broken}\n')
        with self.assertRaises(ValueError): sincronizar(self.config, self.db)
        with closing(sqlite3.connect(self.db)) as d:
            self.assertEqual(d.execute('SELECT cursor FROM fontes_console').fetchone()[0], r['cursor'])

    def test_alteracao_anterior_cursor_recusada(self):
        f = self.fonte('codex'); self.append(f, dict(type='turn.completed'))
        sincronizar(self.config, self.db)
        a = Path(f['arquivo']); texto = a.read_text(); a.write_text(texto.replace('turn.completed', 'turn.completEd'))
        with self.assertRaises(ValueError): sincronizar(self.config, self.db)

    def test_attach_nao_republica_historico(self):
        f = self.fonte('codex'); self.append(f, dict(type='turn.completed'))
        sincronizar(self.config, self.db)
        self.assertEqual(len(self.eventos()), 1)

    def test_envelope_provider_errado_recusado(self):
        f = self.fonte('codex'); sincronizar(self.config, self.db)
        self.append(f, dict(type='system', subtype='init', session_id='s', cwd=f['projeto']))
        with self.assertRaises(ValueError): sincronizar(self.config, self.db)

    def test_attach_ocioso_project_id_historico(self):
        f = self.fonte('codex', historico=True); self.append(f, dict(type='turn.completed', timestamp='2020-01-01T00:00:00Z'))
        sincronizar(self.config, self.db)
        eventos = self.eventos(); attach = eventos[0]
        self.assertEqual(attach['tipo'], 'ocioso'); self.assertNotIn('inicio', attach)
        self.assertNotIn('operacao_estado', attach)
        self.assertTrue(all(e['projeto_id'] == id_projeto(f['projeto']) for e in eventos))
        self.assertEqual(eventos[-1]['ts'], '2020-01-01T00:00:00Z'); self.assertTrue(eventos[-1]['historico'])

    def test_hook_project_id_divergente(self):
        f = self.fonte('codex', formato='hooks'); sincronizar(self.config, self.db)
        self.append(f, {**self.hook(f, 'h2'), 'projeto_id': 'outro'})
        with self.assertRaises(ValueError): sincronizar(self.config, self.db)

    def test_transportes_exigem_autoridade_hooks_verificada(self):
        f = self.fonte('codex', historico=True)
        h = {**f, 'origem': 'hooks', 'arquivo': str(self.raiz / 'hooks.jsonl'), 'formato': 'hooks'}
        Path(h['arquivo']).write_text(json.dumps(self.hook(h, 'h1')) + '\n', encoding='utf-8')
        self.config['fontes'].append(h)
        with self.assertRaises(ValueError): sincronizar(self.config, self.db)
        b = dict(enabled=True, provider='codex', version='0.162.1', project=f['projeto'], project_id=id_projeto(f['projeto']),
                 session_id='s', origin='source', agent='Dev', hooks_active=True, hooks_trusted=True)
        cap = dict(provider='codex', version='0.162.1', version_verified=True, mechanism='hooks',
                   events=['SessionStart', 'PreToolUse', 'PostToolUse', 'Stop'])
        for fonte in (f, h): fonte.update(autoridade='hooks', binding=b, capability=cap)
        self.append(f, dict(type='item.started', item=dict(type='command_execution', id='different-native-id', command='echo')))
        sincronizar(self.config, self.db)
        self.assertFalse(any(e.get('operacao_id') == 'different-native-id' for e in self.eventos()))
        self.assertTrue(any(e.get('evento_id') == 'h1' for e in self.eventos()))

    def test_cli_negacao_sem_traceback(self):
        config = self.raiz / 'config.json'; config.write_text('{"fontes": []}')
        saida = io.StringIO()
        with patch('pathlib.Path.read_text', side_effect=PermissionError('acesso negado')), redirect_stderr(saida):
            self.assertEqual(main(['--config', str(config), '--banco', str(self.db)]), 2)
        self.assertIn('acesso negado', saida.getvalue()); self.assertNotIn('Traceback', saida.getvalue())

    def test_falha_promove_completion_sem_downgrade_apos_restart(self):
        for inicial in ('unknown', 'completed'):
            f = self.fonte('opencode', inicial); sincronizar(self.config, self.db)
            def registro(status):
                return dict(type='tool_use', sessionID=f['sessao'], part=dict(callID='c1', tool='read',
                            state=dict(status=status, error='erro tardio' if status == 'error' else '')))
            self.append(f, registro(inicial)); sincronizar(self.config, self.db)
            antes = len(self.eventos())
            self.append(f, registro('error'))
            self.assertEqual(sum(x['importados'] for x in sincronizar(self.config, self.db)), 1)
            eventos = self.eventos(); self.assertEqual(len(eventos), antes + 1)
            self.assertFalse(eventos[-1]['ok']); self.assertTrue(eventos[-1]['fonte_correction'])
            self.assertEqual(eventos[-1]['erro'], 'erro tardio')
            self.append(f, registro('completed')); sincronizar(self.config, self.db)
            self.assertEqual(len(self.eventos()), antes + 1); self.assertFalse(self.eventos()[-1]['ok'])

    def test_migracao_ledger_idempotente(self):
        with closing(sqlite3.connect(self.db)) as d, d:
            d.execute('CREATE TABLE fontes_console_dedup(chave TEXT PRIMARY KEY)')
        f = self.fonte('codex'); sincronizar(self.config, self.db); sincronizar(self.config, self.db)
        with closing(sqlite3.connect(self.db)) as d:
            self.assertIn('evento_id', {r[1] for r in d.execute('PRAGMA table_info(fontes_console_dedup)')})


if __name__ == '__main__': unittest.main()
