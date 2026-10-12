"""Fronteiras sintéticas fechadas da jornada: nunca chama um serviço externo."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(os.environ['OFFICE_E2E_ROOT']).resolve()
STATE = ROOT / 'boundary.json'
LOG = ROOT / 'boundary.jsonl'
NAME = Path(sys.argv[0]).name
ARGS = sys.argv[1:]


def save(data):
    tmp = STATE.with_suffix('.tmp')
    tmp.write_text(json.dumps(data), encoding='utf-8')
    tmp.replace(STATE)


def emit(value):
    print(json.dumps(value), flush=True)


def git(*args):
    return subprocess.run(['git', '-C', str(Path.cwd()), *args], check=True,
                          capture_output=True, text=True, timeout=10).stdout.strip()


def fail(message):
    print('SYNTHETIC BOUNDARY: ' + message, file=sys.stderr)
    sys.exit(90)


ownership = {'pid': os.getpid(), 'pgid': os.getpgrp(),
             'start': Path('/proc/self/stat').read_text().split(') ')[1].split()[19]}
with (ROOT / 'owned-processes.jsonl').open('a', encoding='utf-8') as owned:
    owned.write(json.dumps(ownership) + '\n')
with LOG.open('a', encoding='utf-8') as log:
    log.write(json.dumps({'executable': NAME, 'args': ARGS, 'cwd': str(Path.cwd())}) + '\n')
if ARGS == ['--version']:
    print('2.0.27' if NAME == 'opencode' else 'synthetic-cli 1.0')
    sys.exit(0)
if NAME == 'gh' and ARGS == ['auth', 'status']:
    sys.exit(1)  # No real account or credentials.
state = json.loads(STATE.read_text(encoding='utf-8'))
if NAME == 'gh':
    if ARGS[:2] == ['pr', 'create']:
        expected = {'--repo': 'fixture/office-e2e', '--base': 'main', '--head': state['branch']}
        for flag, value in expected.items():
            if flag not in ARGS or ARGS[ARGS.index(flag) + 1] != value:
                fail('unexpected PR target')
        if state.get('publication_error'):
            print('synthetic PR creation timeout after local push', file=sys.stderr)
            sys.exit(1)
        if state.get('pr'):
            fail('duplicate PR creation')
        sha = git('rev-parse', 'HEAD')
        state['pr'] = {'number': 142, 'state': 'open', 'draft': False, 'merged': False, 'labels': [],
            'title': ARGS[ARGS.index('--title') + 1],
            'body': Path(ARGS[ARGS.index('--body-file') + 1]).read_text(encoding='utf-8'),
            'html_url': 'https://github.com/fixture/office-e2e/pull/142',
            'head': {'ref': state['branch'], 'sha': sha, 'repo': {'full_name': 'fixture/office-e2e'}},
            'base': {'ref': 'main', 'sha': state['base'], 'repo': {'full_name': 'fixture/office-e2e'}}}
        save(state)
        print(state['pr']['html_url'])
        sys.exit(0)
    if ARGS[:1] != ['api'] or '--method' not in ARGS:
        fail('unexpected GitHub operation')
    path = ARGS[1]
    method = ARGS[ARGS.index('--method') + 1]
    body = json.load(sys.stdin) if '--input' in ARGS else None
    prefix = 'users/fixture/projectsV2/4/'
    repo = 'repos/fixture/office-e2e/'
    if state.get('api_error'):
        print('HTTP ' + str(state['api_error']) + ' synthetic', file=sys.stderr)
        sys.exit(1)
    if method == 'GET' and path.startswith(prefix + 'fields?'):
        data = [{'id': 1, 'name': 'Status', 'options': [
            {'id': 9, 'name': 'Em andamento'}, {'id': 10, 'name': 'Em revisão'}]},
            {'id': 2, 'name': 'Time'}]
    elif method == 'GET' and path.startswith(prefix + 'items?'):
        data = [{'id': 42, 'content': {'html_url': 'https://github.com/fixture/office-e2e/issues/42'},
                 'fields': [{'id': 1, 'value': {'name': state['status']}}, {'id': 2, 'value': 'Dev'}]}]
    elif method == 'PATCH' and path == prefix + 'items/42':
        if body not in ({'fields': [{'id': 1, 'value': 9}]}, {'fields': [{'id': 1, 'value': 10}]}):
            fail('unexpected card mutation')
        state['status'] = {9: 'Em andamento', 10: 'Em revisão'}[body['fields'][0]['value']]
        save(state)
        data = {}
    elif method == 'GET' and path == repo + 'issues/42':
        data = {'state': 'open', 'title': 'Synthetic delivery',
                'body': '**Objetivo:** Produzir prova sintética\n\n**Aceite:** Arquivo contém fase 2.'}
    elif method == 'GET' and path.startswith(repo + 'issues/42/dependencies/blocked_by?'):
        data = []
    elif method == 'GET' and path.startswith(repo + 'pulls?'):
        data = [state['pr']] if state.get('pr') else []
    elif method == 'GET' and path == repo + 'pulls/142':
        data = state['pr']
    elif method == 'GET' and path == repo + 'git/ref/heads/main':
        data = {'object': {'sha': state['base']}}
    elif method == 'GET' and path.startswith(repo + 'commits/') and '/check-runs?' in path:
        data = {'total_count': 0, 'check_runs': []}
    elif method == 'GET' and path.startswith(repo + 'commits/') and '/statuses?' in path:
        data = []
    else:
        fail('unlisted GitHub route: ' + method + ' ' + path)
    emit([data] if '--slurp' in ARGS else data)
    sys.exit(0)

if NAME != 'opencode':
    fail('unexpected provider inference')
if ARGS == ['models', 'opencode', '--verbose', '--pure']:
    print('opencode/e2e-free')
    emit({'id': 'e2e-free', 'providerID': 'opencode', 'name': 'SYNTHETIC zero-price model',
          'api': {'url': 'https://opencode.ai/zen/v1'}, 'status': 'active',
          'cost': {'input': 0, 'output': 0, 'cache': {'read': 0, 'write': 0}},
          'capabilities': {'toolcall': True}})
    sys.exit(0)
if ARGS[:3] == ['session', 'export', '--standalone'] and ARGS[3:] == ['ses_e2e']:
    sys.stdout.write((ROOT / 'export.json').read_text(encoding='utf-8'))
    sys.exit(0)
if not ARGS or ARGS[0] != 'run' or '--standalone' not in ARGS:
    fail('only standalone V2 run is allowed')
if '--model' not in ARGS or ARGS[ARGS.index('--model') + 1] != 'opencode/e2e-free':
    fail('model fallback or unexpected model')
mode = state.get('mode', 'success')
if mode in ('401', '429'):
    emit({'type': 'error', 'error': {'message': 'HTTP ' + mode + ' synthetic'}})
    sys.exit(1)
prompt = sys.stdin.read()
resumed = '--session' in ARGS or '-s' in ARGS
if resumed:
    flag = '--session' if '--session' in ARGS else '-s'
    if ARGS[ARGS.index(flag) + 1] != 'ses_e2e':
        fail('resume changed native session')
turn = 'resume' if resumed else 'initial'
base = time.time_ns() // 1_000_000
sid = 'ses_e2e'
mid = 'msg_' + turn
content = 'fase 1: checkpoint\n' if mode == 'cancel' else 'fase 2: entrega sintética\n'
entry = {'path': 'docs/e2e/phase2-proof.md', 'content': content}
result = [{'type': 'text', 'text': 'File operation succeeded'}]
record = []

def event(kind, message, part):
    value = {'type': kind, 'sessionID': sid,
             'part': dict(sessionID=sid, messageID=message, **part)}
    record.append(value)
    emit(value)

path = Path.cwd() / entry['path']
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(content, encoding='utf-8')
event('step_start', mid + '_tool', {'type': 'step-start'})
event('tool_use', mid + '_tool', {'type': 'tool', 'id': 'call_' + turn, 'tool': 'write',
    'state': {'status': 'completed', 'input': entry, 'output': 'File operation succeeded',
              'metadata': {'content': result, 'metadata': {}, 'providerCall': {'executed': False},
                           'providerResult': {'executed': False}},
              'time': {'start': base + 2, 'end': base + 4}}})
event('step_finish', mid + '_tool', {'id': 'finish_' + turn, 'type': 'step-finish',
      'reason': 'tool-calls', 'cost': 0, 'tokens': {'input': 5, 'output': 2, 'reasoning': 0, 'cache': {'read': 0, 'write': 0}}})
if mode == 'cancel':
    # A committed checkpoint is required by the existing clean-worktree resume contract.
    # This is a real local Git operation, scripted by the synthetic provider, not model inference.
    git('add', '--', entry['path'])
    git('commit', '-m', 'Synthetic pre-interruption checkpoint')
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
    with (ROOT / 'owned-processes.jsonl').open('a', encoding='utf-8') as owned:
        owned.write(json.dumps({'pid': child.pid, 'pgid': os.getpgrp(), 'leader': os.getpid(),
            'start': (Path('/proc') / str(child.pid) / 'stat').read_text().split(') ')[1].split()[19]}) + '\n')
    (ROOT / 'cancel-ready.json').write_text(json.dumps({'pid': os.getpid(), 'child': child.pid}))
    time.sleep(60)
    fail('cancellation was not delivered')
event('step_start', mid, {'type': 'step-start'})
event('text', mid, {'type': 'text', 'text': 'feito'})
export = {'info': {'id': sid, 'outcome': 'succeeded', 'location': {'directory': str(Path.cwd())}},
    'messages': [
        {'type': 'user', 'id': 'user_' + turn, 'text': 'synthetic input\n' + prompt, 'time': {'created': base}},
        {'type': 'assistant', 'id': mid + '_tool', 'finish': 'tool-calls',
         'model': {'providerID': 'opencode', 'id': 'e2e-free'},
         'time': {'created': base + 1, 'completed': base + 6}, 'cost': 0,
         'tokens': {'input': 5, 'output': 2, 'reasoning': 0, 'cache': {'read': 0, 'write': 0}}, 'content': [
            {'type': 'tool', 'id': 'call_' + turn, 'name': 'write', 'executed': False,
             'state': {'status': 'completed', 'input': entry, 'content': result, 'metadata': {}},
             'time': {'created': base + 2, 'ran': base + 3, 'completed': base + 4}}]},
        {'type': 'assistant', 'id': mid, 'finish': 'stop',
         'model': {'providerID': 'opencode', 'id': 'e2e-free'},
         'time': {'created': base + 7, 'completed': base + 8}, 'cost': 0,
         'tokens': {'input': 5, 'output': 1, 'reasoning': 0, 'cache': {'read': 0, 'write': 0}}, 'content': [{'type': 'text', 'text': 'feito'}]},
        {'type': 'idle', 'outcome': 'succeeded', 'time': {'created': base + 9}}]}
if mode == 'stale':
    export['messages'][0]['time']['created'] = 1
if mode == 'missing_terminal':
    export['messages'][1]['content'][0]['state']['status'] = 'running'
(ROOT / 'export.json').write_text(json.dumps(export), encoding='utf-8')
(ROOT / 'stream.json').write_text(json.dumps(record), encoding='utf-8')
(ROOT / 'turn.json').write_text(json.dumps({'prompt': prompt, 'start': base}), encoding='utf-8')
