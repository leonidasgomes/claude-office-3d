"""Payload confiável de teste, executado somente pelo sandbox oficial."""
import errno
import http.client
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request


def deny_write(path):
    try:
        fd = os.open(path, os.O_WRONLY)  # Nunca cria, trunca ou modifica o sentinela.
    except OSError as e:
        if e.errno not in (errno.EACCES, errno.EPERM, errno.EROFS, errno.ENOENT):
            raise
        return e.errno
    else:
        os.close(fd)
        raise AssertionError('Escrita indevidamente permitida: ' + str(path))


def main():
    spec = json.loads(sys.argv[1])
    ns = {name: os.readlink('/proc/self/ns/' + name) for name in ('pid', 'net', 'user')}
    assert all(ns[k] != spec['host_namespaces'][k] for k in ns), 'Namespace não isolado'
    assert 'NoNewPrivs:\t1' in Path('/proc/self/status').read_text(), 'no_new_privs ausente'
    assert 'Seccomp:\t2' in Path('/proc/self/status').read_text(), 'seccomp ausente'
    result = {'namespaces': ns, 'no_new_privs': True, 'seccomp': True}
    for directory in spec['writable']:
        marker = Path(directory) / 'write-probe'
        marker.write_text('synthetic')
        assert marker.read_text() == 'synthetic'
        marker.unlink()
    result['denied_write'] = [deny_write(p) for p in spec['denied_write']]
    try:
        Path(spec['secret_sentinel']).read_bytes()
    except OSError as e:
        assert e.errno in (errno.EACCES, errno.EPERM, errno.ENOENT)
        result['secret_read_denied'] = True
    else:
        raise AssertionError('Leitura fora do perfil indevidamente permitida')
    # Git can read immutable metadata and create objects only in isolated storage.
    git = subprocess.run(['/usr/bin/git', '-C', spec['worktree'], 'rev-parse', 'HEAD'],
                         capture_output=True, text=True, check=True, timeout=5)
    assert git.stdout.strip() == spec['head'], 'HEAD divergente'
    obj = subprocess.run(['/usr/bin/git', '-C', spec['worktree'], 'hash-object', '-w', '--stdin'],
                         input=b'synthetic-object', capture_output=True, check=True, timeout=5)
    oid = obj.stdout.decode().strip()
    assert (Path(spec['objects']) / oid[:2] / oid[2:]).is_file()
    result['head'] = git.stdout.strip()
    proxy = os.environ.get('HTTPS_PROXY') or os.environ.get('https_proxy')
    assert proxy, 'Proxy ativo não informado'
    parsed = urllib.parse.urlsplit(proxy)
    assert parsed.scheme == 'http' and parsed.hostname and parsed.port, 'Proxy inesperado'
    assert not parsed.username and not parsed.password, 'Proxy com credenciais inesperadas'
    connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
    try:
        connection.request('CONNECT', 'example.com:443', headers={'Host': 'example.com:443'})
        denied = connection.getresponse()
        assert denied.status == 403, 'Bloqueio HTTP não comprovado'
        assert denied.getheader('x-proxy-error') == 'blocked-by-allowlist', 'Sem prova do filtro de domínio'
        assert b'Domain not in allowlist' in denied.read(4096), 'Resposta de bloqueio divergente'
    finally:
        connection.close()
    result['proxy_denied'] = 'blocked-by-allowlist'
    for host in ('api.github.com', 'github.com'):
        with urllib.request.urlopen('https://' + host + '/', timeout=15) as response:
            assert response.status == 200, 'Destino permitido indisponível'
    result['allowed_https'] = ['api.github.com', 'github.com']
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(3)
    try:
        sock.connect((spec['direct_ip'], 443))
    except OSError as e:
        assert e.errno in (errno.EPERM, errno.EACCES, errno.ENETUNREACH, errno.EHOSTUNREACH), 'Negação direta inconclusiva'
        result['direct_denied_errno'] = e.errno
    else:
        raise AssertionError('Conexão direta escapou do proxy')
    finally:
        sock.close()
    print('OFFICE_NATIVE_PROBE ' + json.dumps(result, sort_keys=True), flush=True)
    if spec.get('detached'):
        child = "import pathlib,time; p=pathlib.Path(" + repr(spec['heartbeat']) + ");\nwhile True:\n p.write_text(str(time.monotonic_ns())); time.sleep(.1)"
        subprocess.Popen([sys.executable, '-I', '-c', child], start_new_session=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print('OFFICE_DETACHED_STARTED', flush=True)
        time.sleep(60)


if __name__ == '__main__':
    main()
