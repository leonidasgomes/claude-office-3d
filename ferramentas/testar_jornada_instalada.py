"""Jornada instalada: Git/SQLite/processos/controladores reais, serviços sintéticos.

Linux only: the real Linux gate must remain unavailable. This is never live
provider/GitHub acceptance. No application functions are mocked. Reviewer output
is injected at its documented model boundary; capture failure is a SQLite trigger.
Run: python ferramentas/testar_jornada_instalada.py [--evidence DIRECTORY]
"""
import argparse
from contextlib import closing, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest

SOURCE = Path(__file__).resolve().parent.parent


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def run(args, **kwargs):
    return subprocess.run([str(x) for x in args], check=True, capture_output=True,
                          text=True, encoding='utf-8', timeout=120, **kwargs)


def owned_group_alive(record):
    try:
        status = (Path('/proc') / str(record['pid']) / 'stat').read_text().split(') ')[1].split()
        return (status[0] not in ('Z', 'X') and status[19] == record['start']
                and (record['pid'] == record['pgid'] or record.get('leader') == record['pgid'])
                and record['pgid'] == os.getpgid(record['pid']))
    except (FileNotFoundError, ProcessLookupError):
        return False


def cleanup_owned_groups(root):
    # Version/export/launcher use independent sessions. Only kill groups whose
    # recorded leader is still the same process, never an unrelated reused PID.
    records = []
    for log in root.rglob('owned-processes.jsonl'):
        for line in log.read_text(encoding='utf-8').splitlines():
            try: record = json.loads(line)
            except json.JSONDecodeError: continue
            if owned_group_alive(record): records.append(record)
    for record in records:
        try: os.killpg(record['pgid'], signal.SIGTERM)
        except ProcessLookupError: pass
    deadline = time.monotonic() + 2
    while any(owned_group_alive(record) for record in records) and time.monotonic() < deadline:
        time.sleep(.01)
    for record in records:
        if owned_group_alive(record):
            try: os.killpg(record['pgid'], signal.SIGKILL)
            except ProcessLookupError: pass


def install_and_test(evidence):
    if sys.platform != 'linux':
        print('SKIP: this installed journey asserts the real Linux gate limitation.')
        return 0
    with tempfile.TemporaryDirectory(prefix='office-journey-') as temporary:
        root = Path(temporary).resolve()
        home = root / 'home'; home.mkdir()
        binaries = root / 'bin'; binaries.mkdir()
        fake = SOURCE / 'ferramentas' / 'fixtures' / 'jornada_cli.py'
        for name in ('opencode', 'gh', 'codex', 'claude'):
            target = binaries / name
            target.write_text('#!' + sys.executable + '\n' + fake.read_text(encoding='utf-8'), encoding='utf-8')
            target.chmod(0o700)
        for name in ('git', 'python', 'python3'):
            target = shutil.which('git') if name == 'git' else sys.executable
            if not target:
                raise RuntimeError('Git/Python unavailable')
            (binaries / name).symlink_to(Path(target).resolve())
        write_json(root / 'boundary.json', {'status': 'Backlog'})
        guard = root / 'python-guard'; guard.mkdir()
        (guard / 'sitecustomize.py').write_text(
            "import sys\ndef deny_network(event, args):\n"
            "    if event in ('socket.connect', 'socket.connect_ex', 'socket.getaddrinfo'):\n"
            "        raise RuntimeError('Installed acceptance forbids network access')\n"
            "sys.addaudithook(deny_network)\n", encoding='utf-8')
        # Deliberately do not inherit credentials, proxy settings, provider config,
        # Git config, hooks, SSH, user settings or shell startup environment.
        env = {'PATH': str(binaries), 'HOME': str(home), 'XDG_CONFIG_HOME': str(home / '.config'),
               'XDG_DATA_HOME': str(home / '.local/share'), 'XDG_CACHE_HOME': str(home / '.cache'),
               'PYTHONUTF8': '1', 'PYTHONDONTWRITEBYTECODE': '1', 'LANG': 'C.UTF-8',
               'PYTHONPATH': str(guard), 'PYTHONWARNINGS': 'error',
               'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null',
               'GIT_ALLOW_PROTOCOL': 'file', 'GIT_TERMINAL_PROMPT': '0',
               'OFFICE_E2E_ROOT': str(root), 'TMPDIR': str(root),
               'OFFICE_E2E_BIN': str(binaries)}
        config = json.loads((SOURCE / 'config.exemplo.json').read_text(encoding='utf-8'))
        project = root / 'install-project'; project.mkdir()
        config.update(projetos=[str(project)], instalacao={'atalho_desktop': False},
                      praticas={'corrigir': False, 'instalar_deps': False})
        write_json(root / 'config.json', config)
        settings = root / 'settings.json'
        settings.write_text('{"sentinel": "unchanged"}\n', encoding='utf-8')
        old_settings = settings.read_bytes()
        app = root / 'app'
        command = [sys.executable, SOURCE / 'instalar.py', '--sem-perguntas', '--config', root / 'config.json',
                   '--destino', app, '--settings-usuario', settings, '--hook', 'nenhum',
                   '--sem-abrir', '--sem-revisao']
        first = run(command, cwd=SOURCE, env=env)
        second = run(command, cwd=SOURCE, env=env)
        assert settings.read_bytes() == old_settings, 'Installation changed unrelated settings'
        assert (app / '.venv/pyvenv.cfg').is_file(), 'Installation did not create its venv'
        assert '.venv do escritório reaproveitado' in second.stdout, second.stdout
        assert not list(app.glob('config.json.bak-*')), 'Repeated installation changed config'
        package_data = json.loads(run([sys.executable, '-c',
            'import instalar,json; print(json.dumps({"package": instalar.PACOTE, "shortcuts": instalar.ATALHOS}))'],
            cwd=SOURCE, env=env).stdout)
        package = package_data['package']
        production = {}
        source_hashes = {}
        for name in package:
            original = SOURCE / name
            copied = app / name
            expected = original.read_bytes()
            source_hashes[name] = hashlib.sha256(expected).hexdigest()
            if name in package_data['shortcuts']:
                text = package_data['shortcuts'][name]
                expected = text.replace('\n', '\r\n').encode('utf-8') if name.endswith('.bat') else text.encode('utf-8')
            assert copied.is_file() and expected == copied.read_bytes(), name
            production[name] = hashlib.sha256(copied.read_bytes()).hexdigest()
        manifest = {'installed_package_sha256': production, 'source_package_sha256': source_hashes,
                    'generated_shortcuts': sorted(package_data['shortcuts']),
                    'harness_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    'fake_cli_sha256': hashlib.sha256(fake.read_bytes()).hexdigest(),
                    'docs_sha256': hashlib.sha256((SOURCE / 'ferramentas/JORNADA_INSTALADA.md').read_bytes()).hexdigest(),
                    'identity_note': 'Content hashes are authoritative; copied checkout Git metadata is not used.'}
        write_json(root / 'source-manifest.json', manifest)
        # No test helpers are copied into production. The runner imports all application
        # modules from this installed directory in a fresh interpreter.
        env['OFFICE_E2E_INSTALL'] = str(app)
        child = subprocess.Popen([str(app / '.venv/bin/python'), str(Path(__file__).resolve()),
                                  '--installed', str(app), '--root', str(root)], cwd=root, env=env,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                 encoding='utf-8', start_new_session=True)
        try:
            stdout, stderr = child.communicate(timeout=180)
        except BaseException:
            # The launcher session does not contain providers' private groups.
            # Close those first, then the owned runner and any Git/gh descendants.
            cleanup_owned_groups(root)
            try: os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError: pass
            try: child.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.communicate(timeout=3)
            raise
        finally:
            cleanup_owned_groups(root)
            if child.stdout: child.stdout.close()
            if child.stderr: child.stderr.close()
        print(stdout, end=''); print(stderr, end='', file=sys.stderr)
        if evidence:
            evidence.mkdir(parents=True, exist_ok=True)
            (evidence / 'install.log').write_text(first.stdout + second.stdout, encoding='utf-8')
            (evidence / 'tests.log').write_text(stdout + stderr, encoding='utf-8')
            for scenario in root.glob('test_*'):
                if scenario.is_dir() and (scenario / 'boundary.jsonl').is_file():
                    shutil.copyfile(scenario / 'boundary.jsonl', evidence / (scenario.name + '.jsonl'))
                    for diagnostic in scenario.glob('*.stdout.log'):
                        shutil.copyfile(diagnostic, evidence / (scenario.name + '-' + diagnostic.name))
            for name in ('acceptance.json', 'source-manifest.json'):
                if (root / name).exists(): shutil.copyfile(root / name, evidence / name)
        return child.returncode


class InstalledJourney(unittest.TestCase):
    """Each method gets a fresh project and state; one genuinely installed app."""
    app = None
    workspace = None
    outcomes = []

    def setUp(self):
        self.root = self.workspace / self._testMethodName
        self.root.mkdir()
        self.addCleanup(cleanup_owned_groups, self.root)
        os.environ['OFFICE_E2E_ROOT'] = str(self.root)
        self.project = self.root / 'synthetic-project'; self.project.mkdir()
        self.remote = self.root / 'origin.git'
        self.state_path = self.root / 'boundary.json'
        write_json(self.state_path, {'status': 'Backlog', 'mode': 'success'})
        import configurar_gestao
        self.cfg = {
            'ativo': True, 'fontes': {'regras': '.office/REGRAS.md'},
            'kanban': {'repo': 'fixture/office-e2e', 'owner': 'fixture', 'numero': 4},
            'equipes': [{'nome': 'Dev', 'especialidade': 'Synthetic acceptance',
                         'executor': {'console': 'opencode', 'modelo': 'opencode/e2e-free', 'cloud': 'synthetic-author'}}],
            'ciclo': {'ativo': True, 'base': 'origin/main'},
            'merge': {'modo': 'manual', 'checks': ['architecture-guardian']},
            'revisao': {'ativo': True, 'clouds_distintas': 2, 'separar_autor': True,
                       'revisores': [{'nome': 'Synthetic Claude reviewer', 'executor': {'console': 'claude'}},
                                     {'nome': 'Synthetic Codex reviewer', 'executor': {'console': 'codex'}}]}}
        plan = configurar_gestao.preparar(self.project, self.cfg)
        configurar_gestao.aplicar(self.project, plan)
        self.cfg = plan['politica']
        gate = self.project / '.claude/skills/architecture/scripts/review_pr.py'
        gate.parent.mkdir(parents=True)
        gate.write_text("raise AssertionError('Linux gate must never execute')\n", encoding='utf-8')
        with (self.project / '.office/REGRAS.md').open('a', encoding='utf-8') as f:
            f.write('\nGate autorizado: python .claude/skills/architecture/scripts/review_pr.py --pr <numero> --publish\n')
        (self.project / '.gitignore').write_text('__pycache__/\n', encoding='utf-8')
        self.git(self.project, 'init', '-b', 'main')
        self.git(self.project, 'config', 'user.name', 'Synthetic Acceptance')
        self.git(self.project, 'config', 'user.email', 'synthetic@example.com')
        self.git(self.project, 'add', '.')
        self.git(self.project, 'commit', '-m', 'Synthetic base')
        self.git(self.project, 'init', '--bare', self.remote)
        self.git(self.project, 'remote', 'add', 'origin', self.remote)
        self.git(self.project, 'push', 'origin', 'main')
        self.base = self.git(self.project, 'rev-parse', 'HEAD')
        self.change(base=self.base)
        import controlador_local
        created = controlador_local.criar_worktrees(self.project, {'base': 'origin/main', 'cartoes': [42]})
        self.assertEqual(created['estado'], 'criado')
        self.work = Path(created['criados'][0]['worktree'])
        self.branch = created['criados'][0]['branch']
        self.change(branch=self.branch)
        import gestao_cli
        self.data = gestao_cli.pasta_dados(self.project)
        self.db = self.data / 'tarefas.db'
        self.feed = self.root / 'feed.db'
        self.publication = None
        self.review_calls = []
        self.capture_fault = False
        self.attempts_seen = []
        self.addCleanup(self.assert_boundary_safety)
        from modelos_opencode import consultar
        catalog = consultar()  # Real parser and subprocess, explicitly fake catalog.
        self.assertEqual([x['id'] for x in catalog], ['opencode/e2e-free'])
        self.assertTrue(catalog[0]['custo_declarado_zero'])

    def assert_boundary_safety(self):
        for call in self.calls():
            if call['executable'] in ('codex', 'claude'):
                self.assertEqual(call['args'], ['--version'], 'Real reviewer execution must never be attempted')
            if call['executable'] == 'gh' and call['args'][:1] == ['api']:
                method = call['args'][call['args'].index('--method') + 1]
                self.assertIn(method, ('GET', 'PATCH'))
                if method == 'PATCH':
                    self.assertEqual(call['args'][1], 'users/fixture/projectsV2/4/items/42')
        self.assertEqual(self.git(self.project, 'remote', 'get-url', 'origin'), str(self.remote))
        self.assertEqual(self.git(self.project, 'branch', '--show-current'), 'main')
        self.assertEqual(self.git(self.project, 'rev-parse', 'HEAD'), self.base)

    def git(self, folder, *args):
        return run(['git', '-C', folder, *args]).stdout.strip()

    def state(self):
        return json.loads(self.state_path.read_text(encoding='utf-8'))

    def change(self, **kwargs):
        state = self.state(); state.update(kwargs); write_json(self.state_path, state)

    def rows(self, query, parameters=()):
        with closing(sqlite3.connect(self.db)) as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute(query, parameters)]

    def calls(self):
        return [json.loads(line) for line in (self.root / 'boundary.jsonl').read_text().splitlines()]

    def observed(self, token, attempt):
        self.attempts_seen.append((token, attempt))

    def reviewer(self, *args, **kwargs):
        import revisao_execucao
        def fake_model(executor, prompt):
            self.review_calls.append(executor['console'])
            return {'veredito': 'aprovado', 'achados': []}
        return revisao_execucao.executar(*args, **kwargs, chamar=fake_model)

    def launch(self, *args, **kwargs):
        import console_provider
        import publicacao_host
        stopping = threading.Event()
        problem = []
        def interrupt_when_ready():
            ready = self.root / 'cancel-ready.json'
            deadline = time.monotonic() + 15
            while not stopping.wait(.01):
                if ready.is_file():
                    os.kill(os.getpid(), signal.SIGINT)
                    return
                if time.monotonic() > deadline:
                    problem.append('synthetic child never reached cancellation checkpoint')
                    os.kill(os.getpid(), signal.SIGINT)
                    return
        thread = None
        if self.state()['mode'] == 'cancel':
            thread = threading.Thread(target=interrupt_when_ready)
            thread.start()
        try:
            code = console_provider.executar(*args, **kwargs, banco=self.feed)
        finally:
            stopping.set()
            if thread: thread.join(timeout=2)
        self.assertFalse(problem, problem)
        if code == 0:
            request = {'cartao': 42, 'worktree': str(self.work), 'titulo': 'Synthetic phase 2',
                       'corpo': 'Parte de #42\nSynthetic fixture only. Do not merge.',
                       'arquivos_entrega': ['docs/e2e/phase2-proof.md']}
            if self.capture_fault:
                # Real storage fault; do not replace the catalog controller with a mock.
                import galeria_entregas
                with closing(sqlite3.connect(self.db)) as db, db:
                    galeria_entregas._migrar(db)
                    db.execute("CREATE TRIGGER e2e_capture_failure BEFORE INSERT ON galeria_manifesto "
                               "BEGIN SELECT RAISE(ABORT, 'synthetic capture failure'); END")
            import controlador_local
            from funcionarios import id_projeto
            source_request = self.root / 'publication-request.json'
            write_json(source_request, request)
            stray_request = self.work / 'pedido-operacional.json'
            shutil.copyfile(source_request, stray_request)
            try:
                self.publication = controlador_local.executar_pedido(
                    {'projeto_id': id_projeto(self.project), 'acao': 'publicar',
                     'dados': json.loads(source_request.read_text(encoding='utf-8'))}, [self.project])
                self.assertEqual(self.publication['arquivos_pedido_excluidos'], ['pedido-operacional.json'])
                self.assertNotIn('pedido-operacional.json', self.git(self.work, 'ls-tree', '-r', '--name-only', 'HEAD'))
            finally:
                stray_request.unlink(missing_ok=True)
        return code

    def dispatch(self):
        import gestao_cli
        output = io.StringIO()
        try:
            with redirect_stdout(output):
                return gestao_cli.despachar(self.project, 42, 'Dev', 'implementacao', self.work,
                                           rodar=self.launch, revisar=self.reviewer, ao_execucao=self.observed)
        finally:
            (self.root / 'dispatch.stdout.log').write_text(output.getvalue(), encoding='utf-8')

    def resume(self, confirmation=None):
        import gestao_cli
        preview = gestao_cli.preparar_retomada(self.project, 42, self.work)[0]
        with redirect_stdout(io.StringIO()):
            return gestao_cli.retomar(self.project, 42, self.work, confirmation or preview['confirmacao'],
                                     agentes_conciliados=True, rodar=self.launch, revisar=self.reviewer,
                                     ao_execucao=self.observed)

    def assert_no_publication(self):
        self.assertIsNone(self.publication)
        self.assertFalse(self.state().get('pr'))
        self.assertFalse(list((self.data / 'publicacoes').glob('*.json')))
        self.assertEqual(self.review_calls, [])

    def assert_linux_gate_closed(self):
        import gates_projeto
        import kanban_gestao
        self.assertEqual(sys.platform, 'linux')  # Never monkeypatch platform or eligibility.
        before = self.db.read_bytes()
        issues = []
        k = kanban_gestao.Kanban(self.cfg, self.data / 'kanban.json')
        pr = self.state()['pr']
        self.assertEqual(gates_projeto.candidatos(self.project, self.cfg, [pr], self.data, k,
                                                 pendencias=issues), [])
        self.assertEqual(len(issues), 1)
        self.assertIn('Gate Linux indisponível', issues[0]['motivo'])
        self.assertEqual(self.db.read_bytes(), before)
        self.assertFalse((self.data / 'gates_projeto').exists())
        self.assertFalse(any(c['executable'] == 'codex' and c['args'] != ['--version'] for c in self.calls()))
        self.assertFalse(any(c['executable'] == 'gh' and c['args'][:2] in (['pr', 'merge'], ['pr', 'review'])
                             for c in self.calls()))

    def test_cancel_resume_publish_gallery_review_linux_block(self):
        self.change(mode='cancel')
        first = self.dispatch()
        self.assertEqual((first['codigo'], first['estado']), (130, 'bloqueado'))
        first_rows = self.rows('SELECT * FROM execucao_tarefa')
        self.assertEqual(len(first_rows), 1)
        self.assert_no_publication()
        pids = json.loads((self.root / 'cancel-ready.json').read_text())
        for pid in pids.values():
            status = Path('/proc') / str(pid) / 'stat'
            self.assertTrue(not status.exists() or status.read_text().split(') ')[1].split()[0] in ('Z', 'X'))
        self.assertIn('fase 1', (self.work / 'docs/e2e/phase2-proof.md').read_text())
        self.assertEqual(self.git(self.work, 'status', '--porcelain'), '')
        self.change(mode='success')
        import gestao_cli
        preview = gestao_cli.preparar_retomada(self.project, 42, self.work)[0]
        second = self.resume(preview['confirmacao'])
        before_retry = self.calls()
        with self.assertRaises(ValueError): self.resume(preview['confirmacao'])
        self.assertEqual(self.calls(), before_retry)
        self.assertEqual((second['codigo'], second['estado'], second['token']), (0, 'revisao', first['token']))
        attempts = self.rows('SELECT * FROM execucao_tarefa ORDER BY inicio,id')
        self.assertEqual(len(attempts), 2)
        self.assertEqual(attempts[0], first_rows[0])
        self.assertNotEqual(attempts[0]['id'], attempts[1]['id'])
        self.assertEqual(self.rows('SELECT sessao FROM reserva')[0]['sessao'], 'ses_e2e')
        self.assertEqual(self.rows('SELECT tipo FROM execucao_resultado ORDER BY atualizado'),
                         [{'tipo': 'despacho'}, {'tipo': 'retomada'}])
        self.assertEqual(self.publication['tentativa'], attempts[1]['id'])
        self.assertEqual(self.publication['token'], first['token'])
        self.assertEqual(self.publication['galeria']['estado'], 'registrado')
        self.assertEqual(self.git(self.project, 'ls-remote', 'origin', 'refs/heads/' + self.branch).split()[0],
                         self.publication['sha'])
        self.assertEqual(self.review_calls, ['claude', 'codex'])
        report = json.loads((self.data / 'revisoes' / (self.publication['sha'] + '.json')).read_text())
        self.assertTrue(report['aprovado'])
        self.assertEqual(report['sha'], self.publication['sha'])
        delivery = self.rows('SELECT * FROM entrega WHERE token=?', (first['token'],))[0]
        self.assertEqual((delivery['sha'], delivery['pr'], delivery['aprovado']),
                         (self.publication['sha'], 142, 1))
        self.assertEqual(json.loads(delivery['relatorio']), report)
        self.assertEqual(self.rows('SELECT estado FROM reserva WHERE token=?', (first['token'],)),
                         [{'estado': 'revisao'}])
        self.assert_linux_gate_closed()
        self.assert_gallery_snapshot()
        self.assert_accounting_dedup(attempts[1]['id'])
        self.outcomes.append({'scenario': self._testMethodName, 'deterministic': 'passed',
                              'native_linux_gate': 'blocked_as_expected', 'attempts': 2})

    def assert_gallery_snapshot(self):
        import galeria_entregas
        item = galeria_entregas.listar(self.project)['itens'][0]
        file = item['arquivos'][0]
        contents = galeria_entregas.arquivo(self.project, file['id'])['conteudo']
        self.assertEqual(file['sha256'], hashlib.sha256(contents.encode()).hexdigest())
        self.assertIn('fase 2', contents)
        self.assertEqual(item['aceite_usuario'], 'nao_registrado')
        self.assertEqual(item['aprovacao_visual'], 'nao_registrada')
        self.assertEqual(item['merge']['estado'], 'nao_comprovado')
        (self.work / 'docs/e2e/phase2-proof.md').write_text('later unrelated edits', encoding='utf-8')
        self.assertEqual(galeria_entregas.arquivo(self.project, file['id'])['conteudo'], contents)
        self.git(self.work, 'restore', '--', 'docs/e2e/phase2-proof.md')

    def assert_accounting_dedup(self, attempt):
        from consumo_providers import Coletor
        from opencode_v2 import validar_export
        from retorno_console import Retorno
        path = self.root / 'consumo_providers.db'
        def accounting():
            with closing(sqlite3.connect(path)) as db:
                return db.execute('SELECT COUNT(*), SUM(total) FROM consumo').fetchone()
        before = accounting()
        self.assertEqual(before, (3, 20))  # Interrupted tool=7, resumed tool=7, final=6.
        events = json.loads((self.root / 'stream.json').read_text())
        turn = json.loads((self.root / 'turn.json').read_text())
        ret = Retorno('opencode')
        for event in events: ret.consumir(event)
        proof = validar_export(json.loads((self.root / 'export.json').read_text()), ret, self.work,
                               turn['start'], turn['prompt'], 'opencode/e2e-free', events)
        self.assertIsNotNone(proof)
        collector = Coletor(path, 'opencode', self.project, 'Dev', 'opencode/e2e-free', tentativa=attempt)
        for _ in range(2):
            for event in events: collector.consumir(event)
            collector.consumir(proof)
        self.assertEqual(accounting(), before)
        with closing(sqlite3.connect(path)) as db:
            counts = db.execute('SELECT tentativa,COUNT(*) FROM consumo_tentativa GROUP BY tentativa').fetchall()
        self.assertEqual(sorted(count for _, count in counts), [1, 2])

    def test_cleanup_only_terminates_owned_group(self):
        owned = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], start_new_session=True)
        outsider = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], start_new_session=True)
        def identity(pid):
            return {'pid': pid, 'pgid': os.getpgid(pid),
                    'start': (Path('/proc') / str(pid) / 'stat').read_text().split(') ')[1].split()[19]}
        try:
            with (self.root / 'owned-processes.jsonl').open('a', encoding='utf-8') as log:
                log.write(json.dumps(identity(owned.pid)) + '\n')
                stale = identity(outsider.pid); stale['start'] = 'not-the-recorded-process'
                log.write(json.dumps(stale) + '\n')
            cleanup_owned_groups(self.root)
            self.assertEqual(owned.wait(timeout=3), -signal.SIGTERM)
            self.assertIsNone(outsider.poll())
        finally:
            for process in (owned, outsider):
                if process.poll() is None: process.terminate()
                process.wait(timeout=3)

    def test_capture_failure_reconciles_without_republishing(self):
        self.capture_fault = True
        result = self.dispatch()
        self.assertEqual(result['estado'], 'revisao')
        self.assertEqual(self.publication['estado'], 'publicado')
        self.assertEqual(self.publication['galeria']['estado'], 'nao_registrada')
        receipt = (self.data / 'publicacoes/42.json').read_bytes()
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('DROP TRIGGER e2e_capture_failure')
        import galeria_entregas
        request = {'cartao': 42, 'tentativa': self.publication['tentativa'], 'pr': 142,
                   'sha': self.publication['sha'], 'arquivos': ['docs/e2e/phase2-proof.md']}
        before = self.calls()
        self.assertEqual(galeria_entregas.registrar(self.project, request)['estado'], 'registrado')
        self.assertEqual(galeria_entregas.registrar(self.project, request)['estado'], 'ja_registrado')
        self.assertEqual(self.calls(), before)
        self.assertEqual((self.data / 'publicacoes/42.json').read_bytes(), receipt)
        self.assertEqual(sum(c['args'][:2] == ['pr', 'create'] for c in self.calls()), 1)
        self.assert_gallery_snapshot()

    def test_publish_failure_preserves_uncertain_receipt_and_stops_retry(self):
        self.change(publication_error=True)
        with self.assertRaisesRegex(ValueError, 'Publicação falhou'):
            self.dispatch()
        receipt = json.loads((self.data / 'publicacoes/42.json').read_text())
        self.assertEqual(receipt['estado'], 'publicando')
        self.assertIn('tentativa', receipt)
        self.assertFalse(self.state().get('pr'))
        import publicacao_host
        import galeria_entregas
        before = self.calls()
        with self.assertRaises(ValueError):
            publicacao_host.publicar(self.project, {'cartao': 42, 'worktree': str(self.work),
                'titulo': 'Synthetic', 'corpo': 'Parte de #42', 'arquivos_entrega': ['docs/e2e/phase2-proof.md']})
        self.assertEqual(self.calls(), before)
        self.assertEqual(galeria_entregas.listar(self.project)['itens'], [])
        self.assertEqual(sum(c['args'][:2] == ['pr', 'create'] for c in self.calls()), 1)

    def test_stale_export_never_publishes(self):
        self.change(mode='stale')
        result = self.dispatch()
        self.assertEqual((result['codigo'], result['estado']), (1, 'bloqueado'))
        self.assert_no_publication()
        self.assertIn('fase 2', (self.work / 'docs/e2e/phase2-proof.md').read_text())

    def test_missing_native_terminal_never_publishes(self):
        self.change(mode='missing_terminal')
        result = self.dispatch()
        self.assertEqual((result['codigo'], result['estado']), (1, 'bloqueado'))
        self.assert_no_publication()

    def test_provider_401_no_fallback(self):
        self.change(mode='401')
        result = self.dispatch()
        self.assertEqual((result['codigo'], result['estado']), (1, 'bloqueado'))
        self.assert_no_publication()
        self.assertEqual(sum(c['executable'] == 'opencode' and c['args'][:1] == ['run'] for c in self.calls()), 1)

        self.assertIn('HTTP 401 synthetic', (self.root / 'dispatch.stdout.log').read_text())
        self.assertEqual(self.rows('SELECT codigo FROM execucao_tarefa'), [{'codigo': 1}])

    def test_provider_429_no_fallback(self):
        self.change(mode='429')
        result = self.dispatch()
        self.assertEqual((result['codigo'], result['estado']), (1, 'bloqueado'))
        self.assert_no_publication()
        self.assertEqual(sum(c['executable'] == 'opencode' and c['args'][:1] == ['run'] for c in self.calls()), 1)

        self.assertIn('HTTP 429 synthetic', (self.root / 'dispatch.stdout.log').read_text())
        self.assertEqual(self.rows('SELECT codigo FROM execucao_tarefa'), [{'codigo': 1}])

    def test_github_401_before_dispatch_never_starts_provider(self):
        self.change(api_error=401)
        with self.assertRaisesRegex(ValueError, 'GitHub indisponível'):
            self.dispatch()
        self.assertFalse(self.db.exists())
        self.assert_no_publication()
        self.assertFalse(any(c['executable'] == 'opencode' and c['args'][:1] == ['run'] for c in self.calls()))

    def test_github_429_before_dispatch_never_starts_provider(self):
        self.change(api_error=429)
        with self.assertRaisesRegex(ValueError, 'GitHub indisponível'):
            self.dispatch()
        self.assertFalse(self.db.exists())
        self.assert_no_publication()
        self.assertFalse(any(c['executable'] == 'opencode' and c['args'][:1] == ['run'] for c in self.calls()))

    def test_missing_attempt_terminal_blocks_resume(self):
        import gestao_cli
        self.change(mode='cancel')
        self.dispatch()
        # Emulate an interrupted durable write; never synthesize a successful result.
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('UPDATE execucao_tarefa SET fim=NULL,codigo=NULL')
        before = self.calls()
        with self.assertRaisesRegex(ValueError, 'sem retorno'):
            gestao_cli.preparar_retomada(self.project, 42, self.work)
        self.assertEqual(self.calls(), before)
        self.assert_no_publication()

    def test_changed_head_invalidates_resume_preview(self):
        import gestao_cli
        self.change(mode='cancel')
        self.dispatch()
        preview = gestao_cli.preparar_retomada(self.project, 42, self.work)[0]
        self.git(self.work, 'commit', '--allow-empty', '-m', 'Synthetic concurrent head change')
        self.change(mode='success')
        with self.assertRaisesRegex(ValueError, 'Prévia mudou'):
            self.resume(preview['confirmacao'])
        self.assertEqual(len(self.rows('SELECT * FROM execucao_tarefa')), 1)
        self.assert_no_publication()


def installed_main(app, root):
    sys.path.insert(0, str(app))
    # Loaded modules must all come from the installed build, never the source tree.
    import gestao_cli, console_provider, publicacao_host, galeria_entregas, gates_projeto
    import controlador_local, configurar_gestao, revisao_execucao, opencode_v2
    modules = [gestao_cli, console_provider, publicacao_host, galeria_entregas, gates_projeto,
               controlador_local, configurar_gestao, revisao_execucao, opencode_v2]
    imported = {}
    for module in modules:
        path = Path(module.__file__).resolve()
        assert path.parent == app, path
        imported[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    def verify_imports():
        loaded = {}
        for name, module in list(sys.modules.items()):
            file = getattr(module, '__file__', None)
            if not file: continue
            path = Path(file).resolve()
            if path.is_relative_to(SOURCE) and path != Path(__file__).resolve():
                raise AssertionError('Source-tree import leaked into installed journey: ' + name)
            if path.is_relative_to(app) and '.venv' not in path.relative_to(app).parts:
                loaded[str(path.relative_to(app))] = hashlib.sha256(path.read_bytes()).hexdigest()
        return loaded
    verify_imports()
    InstalledJourney.app = app
    InstalledJourney.workspace = root
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(InstalledJourney))
    manifest = json.loads((root / 'source-manifest.json').read_text(encoding='utf-8'))
    manifest['loaded_after_suite_sha256'] = verify_imports()
    for name, digest in manifest['loaded_after_suite_sha256'].items():
        assert manifest['installed_package_sha256'][name] == digest, name
    write_json(root / 'source-manifest.json', manifest)
    report = {'deterministic_installed_journey': 'passed' if result.wasSuccessful() else 'failed',
              'tests': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors),
              'real_provider': 'not_run_no_inference_authorized',
              'real_github_publication': 'not_run_exact_external_authorization_pending',
              'native_linux_gate': 'blocked_as_expected' if InstalledJourney.outcomes else 'not_established',
              'scenarios': InstalledJourney.outcomes,
              'boundaries': {'provider': 'synthetic subprocess', 'github': 'synthetic gh subprocess',
                             'reviewer': 'synthetic model response; real review controller',
                             'git': 'real local repository and local bare remote', 'sqlite': 'real',
                             'ui_browser': 'not_run', 'production_functions_mocked': False}}
    write_json(root / 'acceptance.json', report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--installed', type=Path)
    parser.add_argument('--root', type=Path)
    parser.add_argument('--evidence', type=Path)
    args = parser.parse_args()
    if args.installed:
        if not args.root: parser.error('--installed requires --root')
        raise SystemExit(installed_main(args.installed.resolve(), args.root.resolve()))
    raise SystemExit(install_and_test(args.evidence.resolve() if args.evidence else None))
