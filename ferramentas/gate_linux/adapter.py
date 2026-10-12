"""Primitivas experimentais do gate Linux; somente fixtures, sem publicação.

Não são importadas pelo executor de produção. O runtime oficial faz o isolamento;
este módulo constrói uma política explícita e limita processo/saída do teste.
"""
import hashlib
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import time

VERSION = 'codex-cli 0.159.2'
MAX_OUTPUT = 8 * 1024 * 1024


class SandboxFailure(RuntimeError):
    def __init__(self, reason, result):
        super().__init__(reason)
        self.result = result


def inline(value):
    """TOML inline somente com dados conhecidos, sem concatenação de caminhos."""
    if isinstance(value, dict):
        return '{' + ','.join(json.dumps(k) + '=' + inline(v) for k, v in value.items()) + '}'
    if type(value) is bool:
        return 'true' if value else 'false'
    if isinstance(value, str):
        return json.dumps(value)
    raise ValueError('Valor não permitido no perfil')


def policy(worktree, temporary, objects, protected, readable):
    worktree, temporary, objects = (Path(p).resolve(strict=True) for p in (worktree, temporary, objects))
    writes = (worktree, temporary, objects)
    if any(not p.is_dir() or p == Path('/') for p in writes):
        raise ValueError('Raiz gravável inválida')
    if any(a == b or a.is_relative_to(b) or b.is_relative_to(a)
           for i, a in enumerate(writes) for b in writes[i + 1:]):
        raise ValueError('Raízes graváveis devem ser distintas e não sobrepostas')
    fs = {':minimal': 'read', **{str(p): 'write' for p in writes}}
    for p in protected:
        # Preserve the lexical .git marker AND the resolved target when applicable.
        lexical = Path(p).absolute()
        for path in (lexical, lexical.resolve()):
            if any(w == path or w.is_relative_to(path) for w in writes):
                raise ValueError('Área gravável inclui metadados protegidos')
            fs[str(path)] = 'read'
    for p in readable:
        path = Path(p).resolve(strict=True)
        if path == Path('/') or any(w == path or w.is_relative_to(path) for w in writes):
            raise ValueError('Leitura ampla/sobreposta não permitida')
        fs[str(path)] = 'read'
    return {'filesystem': fs, 'network': {
        'enabled': True,
        'domains': {'api.github.com': 'allow', 'github.com': 'allow'},
        'allow_upstream_proxy': False,
        'allow_local_binding': False,
        'enable_socks5': False,
        'enable_socks5_udp': False,
        'dangerously_allow_non_loopback_proxy': False,
        'dangerously_allow_all_unix_sockets': False,
    }}


def environment(home, temporary, objects, common, path):
    """Ambiente da fixture: nunca copia ambiente/credenciais da conta."""
    home, temporary, objects, common = (Path(p).resolve(strict=True) for p in (home, temporary, objects, common))
    return {'HOME': str(home), 'CODEX_HOME': str(home / '.codex'),
            'PATH': path, 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8',
            'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONUTF8': '1',
            'TMP': str(temporary), 'TEMP': str(temporary), 'TMPDIR': str(temporary),
            'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull,
            'GIT_TERMINAL_PROMPT': '0', 'GIT_OPTIONAL_LOCKS': '0',
            'GIT_OBJECT_DIRECTORY': str(objects),
            'GIT_ALTERNATE_OBJECT_DIRECTORIES': str(common / 'objects')}


def command(codex, worktree, profile, payload):
    if not payload or not Path(payload[0]).is_absolute():
        raise ValueError('Executável explícito exigido')
    return [str(Path(codex).resolve(strict=True)), 'sandbox',
            '--permission-profile', 'office-gate-linux-validation', '--include-managed-config',
            '-c', 'permissions=' + inline({'office-gate-linux-validation': profile}),
            '-c', 'features.network_proxy=true',
            '-C', str(Path(worktree).resolve(strict=True)), '--', *map(str, payload)]


def run(args, cwd, env, *, timeout=30, output_limit=MAX_OUTPUT, callback=None):
    """Deadline/saída limitados; killpg + namespace oficial, nunca fallback direto.

    A prova de limpeza dos filhos destacados pertence ao teste nativo; killpg
    isoladamente não garante limpeza. Um erro nunca vira sucesso de gate.
    """
    if os.name != 'posix':
        raise ValueError('Harness nativo exige POSIX')
    start = time.monotonic()
    buffers = [bytearray(), bytearray()]
    result = {'state': 'uncertain', 'inference': False, 'exit_code': None}
    failure = None
    p = subprocess.Popen(args, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         start_new_session=True, close_fds=True)
    result['pid'] = p.pid
    selector = selectors.DefaultSelector()
    try:
        selector.register(p.stdout, selectors.EVENT_READ, 0)
        selector.register(p.stderr, selectors.EVENT_READ, 1)
        if callback:
            callback(p.pid)
        while selector.get_map():
            if time.monotonic() - start >= timeout:
                raise TimeoutError('Tempo limite do sandbox')
            for key, _ in selector.select(min(0.1, max(0, timeout - (time.monotonic() - start)))):
                chunk = os.read(key.fileobj.fileno(), 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                total = sum(map(len, buffers))
                buffers[key.data].extend(chunk[:max(0, output_limit - total)])
                if total + len(chunk) > output_limit:
                    raise ValueError('Saída do sandbox excedeu limite')
        p.wait(timeout=max(0.001, timeout - (time.monotonic() - start)))
        result['state'] = 'exited'
    except BaseException as exc:
        failure = exc
    finally:
        # Always terminate any remaining members, including after a clean leader exit.
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            failure = failure or RuntimeError('Limpeza do sandbox não confirmada')
        selector.close()
        p.stdout.close()
        p.stderr.close()
        result.update(exit_code=p.returncode, duration_seconds=round(time.monotonic() - start, 3))
        for key, data in zip(('stdout', 'stderr'), buffers):
            result[key] = bytes(data)
            result[key + '_sha256'] = hashlib.sha256(data).hexdigest()
    if failure:
        result['state'] = 'uncertain'
        result['reason'] = str(failure)
        if isinstance(failure, (KeyboardInterrupt, SystemExit)):
            raise failure
        raise SandboxFailure(str(failure), result) from failure
    return result
