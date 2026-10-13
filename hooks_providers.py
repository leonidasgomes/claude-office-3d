"""Project-scoped hook receiver. No discovery, installation or global configuration.

The launcher supplies an explicit binding file and an explicit Office database.
JSON adapters may call ingest with the SAME operation ID to deduplicate native hooks.
Payload bodies, commands and tool results are deliberately not persisted.
"""
import argparse
from contextlib import closing
import copy
import hashlib
import json
import os
import re
from pathlib import Path
import sqlite3
import shlex
import sys
import uuid

PHASES = {'SessionStart': 'start', 'PreToolUse': 'tool_start',
          'PostToolUse': 'tool_end', 'PostToolUseFailure': 'tool_end',
          'Stop': 'stop', 'SessionEnd': 'end', 'failure': 'error'}
PROVIDERS = ('claude', 'codex', 'opencode')


def receiver_command(python, receiver, binding_file, database, shell='bash'):
    """Quote explicit paths for the provider's verified hook shell.

    Claude on Windows can invoke Git Bash: cmd.exe quoting with backslashes
    loses path separators there. Never infer the hook shell from the host OS.
    """
    paths=[Path(p) for p in (python,receiver,binding_file,database)]
    if any(not p.is_absolute() for p in paths):
        raise ValueError('receiver command requires absolute paths')
    args=[paths[0].as_posix(),paths[1].as_posix(),'--binding',paths[2].as_posix(),'--database',paths[3].as_posix()]
    if shell == 'bash':return shlex.join(args)
    if shell == 'powershell':return '& '+' '.join("'"+arg.replace("'","''")+"'" for arg in args)
    if shell == 'cmd':
        if any(any(c in arg for c in '%!\r\n"') for arg in args):
            raise ValueError('cmd receiver path has unsupported expansion characters')
        return ' '.join('"'+arg+'"' for arg in args)
    raise ValueError('hook shell must be explicitly bash, powershell or cmd')


def binding(value):
    """Fail closed: one opted-in origin/project/session/provider/version."""
    b = dict(value)
    for key in ('provider', 'version', 'project', 'project_id', 'origin', 'agent'):
        if not isinstance(b.get(key), str) or not b[key].strip() or len(b[key]) > 4096 or '\x00' in b[key]:
            raise ValueError('binding missing ' + key)
    if b.get('enabled') is not True or b['provider'] not in PROVIDERS:
        raise ValueError('explicit opt-in/provider required')
    if not re.fullmatch(r'\d+\.\d+\.\d+(?:[-+][a-zA-Z0-9.-]+)?', b['version']):
        raise ValueError('exact semantic version required')
    for key in ('origin', 'agent'):
        if len(b[key]) > 128:
            raise ValueError('binding too long: ' + key)
    from funcionarios import id_projeto
    project = Path(b['project'])
    if not project.is_absolute() or not project.is_dir():
        raise ValueError('project must be an existing absolute directory')
    b['project'] = str(project.resolve())
    if b['project_id'] != id_projeto(b['project']):
        raise ValueError('mismatched project_id')
    session = b.get('session_id')
    if session is None and b.get('allow_new_session') is True:
        return b
    if not isinstance(session, str) or not session or len(session) > 128 or '\x00' in session:
        raise ValueError('exact session or explicit new-session opt-in required')
    return b


def merge_hooks(existing, additions):
    """Pure idempotent merge, retaining every existing user hook and setting."""
    result = copy.deepcopy(existing)
    hooks = result.setdefault('hooks', {})
    for event, entries in additions.items():
        target = hooks.setdefault(event, [])
        for entry in entries:
            if entry not in target:
                target.append(copy.deepcopy(entry))
    return result


def plan(b, command, capability, existing=None):
    """Capability must be verified for this exact version; otherwise JSON fallback.

    For Claude/Codex produces a merge preview only. OpenCode requires its native
    plugin adapter, not fictitious hooks.json settings.
    """
    b = binding(b)
    verified = (capability.get('version_verified') is True and capability.get('version') == b['version']
                and capability.get('provider', b['provider']) == b['provider'])
    events = capability.get('events', []) if verified else []
    mechanism = capability.get('mechanism', 'json') if verified else 'json'
    if mechanism == 'plugin':
        return {'mechanism': 'plugin', 'apply': False, 'events': list(events),
                'reason': 'project plugin required; no Claude hook schema for OpenCode'}
    supported = [e for e in PHASES if e in events]
    if mechanism != 'hooks' or not supported:
        return {'mechanism': 'json', 'apply': False, 'reason': 'native capability/version unverified'}
    additions = {e: [{'hooks': [{'type': 'command', 'command': command}]}] for e in supported}
    return {'mechanism': 'hooks', 'apply': False, 'events': supported,
            'trust_required': b['provider'] == 'codex',
            'path': '.codex/hooks.json' if b['provider'] == 'codex' else '.claude/settings.local.json',
            'config': merge_hooks(existing or {}, additions)}


def prefer_hooks(b, capability, event):
    """True only for verified native coverage; launcher may suppress JSON phase.

    Explicit hooks_active acknowledges project-local installation; a plan alone
    must never suppress telemetry. Hook absence must surface as missing telemetry.
    """
    b = binding(b)
    if b.get('hooks_active') is not True:
        return False
    if b['provider'] == 'codex' and b.get('hooks_trusted') is not True:
        return False
    if (capability.get('version_verified') is not True or capability.get('version') != b['version']
            or capability.get('provider', b['provider']) != b['provider']
            or capability.get('mechanism') not in ('hooks', 'plugin')):
        return False
    phase = event.get('hook_fase') or event.get('fase') if isinstance(event, dict) else event
    native = {'start': 'SessionStart', 'tool_start': 'PreToolUse', 'tool_end': 'PostToolUse',
              'stop': 'Stop', 'end': 'SessionEnd', 'error': 'failure'}.get(phase, phase)
    return native in capability.get('events', [])


def normalize(b, payload, source='hook'):
    b = binding(b)
    if b.get('session_id') is None:
        raise ValueError('new session must be pinned by ingest before normalization')
    if source not in ('hook', 'json', 'plugin') or not isinstance(payload, dict):
        raise ValueError('invalid source/payload')
    for key, expected in (('provider', b['provider']), ('origin', b['origin']),
                          ('project_id', b['project_id']), ('version', b['version'])):
        if key in payload and payload[key] != expected:
            raise ValueError('mismatched ' + key)
    if payload.get('session_id') != b['session_id']:
        raise ValueError('mismatched session')
    cwd = payload.get('cwd')
    if not isinstance(cwd, str) or os.path.normcase(str(Path(cwd).resolve())) != os.path.normcase(b['project']):
        raise ValueError('mismatched cwd')
    event = payload.get('hook_event_name') or payload.get('event')
    if event not in PHASES:
        raise ValueError('unsupported event')
    phase = PHASES[event]
    operation = payload.get('tool_use_id') or payload.get('operation_id')
    if phase.startswith('tool_') and not operation:
        raise ValueError('tool operation ID required')
    operation = str(operation or payload.get('turn_id') or payload.get('event_id') or
                    (event if phase in ('start', 'end') else ''))
    out = {'agente': b['agent'], 'fonte': b['provider'], 'sessao': b['session_id'],
           'projeto_id': b['project_id'], 'operacao_id': operation,
           'tipo': 'trabalho' if phase.startswith('tool_') else 'ocioso',
           'ferramenta': str(payload.get('tool_name') or '')[:64], 'resumo': event,
           'hook_fase': phase, 'hook_origem': b['origin'], 'hook_fonte': source,
           'provider_version': b['version']}
    if phase == 'start':
        out.update(tipo='trabalho', ferramenta='Console', inicio=True, operacao_estado='executando')
    if phase == 'tool_start':
        out.update(inicio=True, operacao_estado='executando')
    response = payload.get('tool_response')
    code = payload.get('exit_code')
    failed = event in ('PostToolUseFailure', 'failure')
    if isinstance(response, dict):
        code = response.get('exit_code', response.get('code', code))
        failed = failed or response.get('is_error') is True or response.get('status') in ('error', 'failed')
    elif isinstance(response, str):
        # Some native Codex Bash results serialize the status in a text response.
        match = re.search(r'(?im)^\s*(?:Exit code|Process exited with code)\s*:?\s*(-?\d+)\s*$', response)
        if match:
            code = int(match.group(1))
    if payload.get('ok') is False:
        failed = True
    if code is not None:
        if isinstance(code, bool) or not isinstance(code, int):
            raise ValueError('invalid exit_code')
        out['codigo'] = code
        failed = failed or code != 0
    if phase in ('tool_end', 'error'):
        out['operacao_estado'] = 'concluido'
        # Completion without explicit outcome is unknown, never invented success.
        if failed:
            out['ok'] = False
            out['erro'] = str(payload.get('error') or 'provider reported failure')[:120]
        elif code == 0 or payload.get('ok') is True:
            out['ok'] = True
    # Native Stop can lack turn_id. Preserve each stop instead of collapsing turns
    # or inventing a native turn identity. Prefer-hooks routing prevents double feeds.
    dedup_operation = operation
    if not dedup_operation:
        out['hook_dedup'] = 'unavailable_without_native_id'
        dedup_operation = 'delivery:' + uuid.uuid4().hex
    key = json.dumps([b['provider'], b['project_id'], b['session_id'], dedup_operation, phase], separators=(',', ':'))
    return hashlib.sha256(key.encode()).hexdigest(), out


def ingest(database, b, payload, source='hook'):
    """Atomic event+dedup ledger in the explicit Office database; survives restart.

    A later failure can upgrade a previously unknown/success completion in-place.
    It never downgrades failure. SQLite serializes concurrent receivers.
    """
    import banco
    from datetime import datetime, timezone
    b = binding(b)
    database = Path(database)
    database.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(str(database), timeout=5)) as conn, conn:
        conn.executescript(banco.ESQUEMA)
        banco._migrar_eventos(conn)
        conn.execute('CREATE TABLE IF NOT EXISTS hooks_recebidos (chave TEXT PRIMARY KEY, evento_id INTEGER NOT NULL)')
        conn.execute('CREATE TABLE IF NOT EXISTS hooks_bindings (chave TEXT PRIMARY KEY, sessao TEXT NOT NULL)')
        conn.execute('BEGIN IMMEDIATE')
        if b.get('session_id') is None:
            pin = json.dumps([b['provider'], b['version'], b['project_id'], b['origin']], separators=(',', ':'))
            row = conn.execute('SELECT sessao FROM hooks_bindings WHERE chave=?', (pin,)).fetchone()
            if row:
                b['session_id'] = row[0]
            else:
                if payload.get('hook_event_name', payload.get('event')) != 'SessionStart':
                    raise ValueError('SessionStart required to pin new session')
                b['session_id'] = payload.get('session_id')
                binding(b)
                # Validate provenance before committing any pin.
                normalize(b, payload, source)
                conn.execute('INSERT INTO hooks_bindings VALUES (?,?)', (pin, b['session_id']))
        key, event = normalize(b, payload, source)
        event['ts'] = datetime.now(timezone.utc).isoformat()
        row = conn.execute('SELECT evento_id FROM hooks_recebidos WHERE chave=?', (key,)).fetchone()
        if row:
            previous = json.loads(conn.execute('SELECT dados FROM evento WHERE id=?', row).fetchone()[0])
            if event.get('ok') is False and previous.get('ok') is not False:
                previous.update({k: event[k] for k in ('ok', 'erro', 'codigo') if k in event})
                previous['ts'] = event['ts']
                previous['hook_correction'] = True
                cur = conn.execute('INSERT INTO evento(ts,agente,ferramenta,dados) VALUES(?,?,?,?)',
                                   (previous['ts'], previous['agente'], previous['ferramenta'], json.dumps(previous)))
                conn.execute('UPDATE hooks_recebidos SET evento_id=? WHERE chave=?', (cur.lastrowid, key))
                return 'failure_updated'
            return 'duplicate'
        cur = conn.execute('INSERT INTO evento(ts,agente,ferramenta,dados) VALUES(?,?,?,?)',
                           (event['ts'], event['agente'], event['ferramenta'], json.dumps(event)))
        conn.execute('INSERT INTO hooks_recebidos VALUES (?,?)', (key, cur.lastrowid))
    return 'inserted'


def ingest_normalized(database, b, event, source='json'):
    """Bridge from Eventos Office envelope using exact session and operation IDs.

    No heuristic correlation. Non-lifecycle events without a canonical phase
    are rejected rather than silently creating an unrelated identity.
    """
    phase = event.get('hook_fase') or event.get('fase')
    reverse = {'start': 'SessionStart', 'tool_start': 'PreToolUse', 'tool_end': 'PostToolUse',
               'stop': 'Stop', 'end': 'SessionEnd', 'error': 'failure'}
    if phase not in reverse:
        if event.get('ferramenta') == 'Console' and event.get('inicio') is True:
            phase = 'start'
        elif event.get('operacao_id') and event.get('inicio') is True:
            phase = 'tool_start'
        elif event.get('operacao_id') and event.get('operacao_estado') == 'concluido':
            phase = 'tool_end'
        else:
            raise ValueError('normalized event needs canonical phase')
    payload = {'session_id': event.get('sessao'), 'cwd': b['project'],
               'event': reverse[phase], 'operation_id': event.get('operacao_id'),
               'tool_name': event.get('ferramenta', ''),
               'provider': event.get('fonte', b['provider']),
               'project_id': event.get('projeto_id', b['project_id'])}
    for incoming, outgoing in (('codigo', 'exit_code'), ('erro', 'error'), ('ok', 'ok')):
        if incoming in event:
            payload[outgoing] = event[incoming]
    return ingest(database, b, payload, source)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binding', required=True)
    parser.add_argument('--database')
    parser.add_argument('--source', choices=('hook', 'json', 'plugin'), default='hook')
    parser.add_argument('--plan', action='store_true')
    parser.add_argument('--capability')
    parser.add_argument('--command')
    args = parser.parse_args()
    try:
        with open(args.binding, encoding='utf-8') as file:
            b = json.load(file)
        if args.plan:
            if not args.capability or not args.command:
                raise ValueError('--plan requires --capability and --command')
            with open(args.capability, encoding='utf-8') as file:
                capability = json.load(file)
            print(json.dumps(plan(b, args.command, capability), ensure_ascii=False))
            return 0
        if not args.database:
            raise ValueError('receiver requires --database')
        raw = sys.stdin.read(262145)
        if len(raw) > 262144:
            raise ValueError('payload exceeds 256 KiB')
        payload = json.loads(raw)
        ingest(args.database, b, payload, args.source)
    except (ValueError, OSError, sqlite3.Error) as exc:
        print('Office hook rejected: ' + str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
