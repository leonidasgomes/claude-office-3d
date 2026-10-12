"""Aceite nativo em runner efêmero sem conta; falha em vez de pular isolamento."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time

import adapter

ROOT = Path(__file__).resolve().parents[2]


def digest_tree(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in Path(root).rglob('*') if p.is_file()}


def clean_config_sources(worktree, home):
    candidates = [Path('/etc/codex/config.toml'), Path('/etc/codex/requirements.toml'),
                  Path('/etc/codex/managed_config.toml'),
                  home/'.codex/config.toml', home/'.codex/requirements.toml']
    candidates += [p/'.codex/config.toml' for p in [worktree, *worktree.parents]]
    if any(p.exists() or p.is_symlink() for p in candidates):
        raise RuntimeError('Runner sintético contém configuração Codex externa; validação recusada')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--codex', required=True)
    parser.add_argument('--runtime-root', required=True)
    args = parser.parse_args()
    if sys.platform != 'linux':
        raise RuntimeError('Validação nativa exige Linux')
    codex = Path(args.codex).resolve(strict=True)
    runtime = Path(args.runtime_root).resolve(strict=True)
    if not codex.is_relative_to(runtime):
        raise RuntimeError('CLI fora do runtime instalado explicitamente')
    evidence = {'state': 'failed', 'production_enabled': False, 'inference': False,
                'commit': subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()}
    with tempfile.TemporaryDirectory(prefix='office-native-gate-') as directory:
        root = Path(directory)
        for name in ('repo', 'tmp', 'objects', 'home'):
            (root/name).mkdir()
        repo, worktree, temporary, objects, home = [root/x for x in ('repo','worktree','tmp','objects','home')]
        (home/'.codex').mkdir()
        host_env = {'PATH': os.environ['PATH'], 'HOME': str(home), 'GIT_CONFIG_NOSYSTEM': '1',
                    'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_TERMINAL_PROMPT': '0', 'LC_ALL':'C.UTF-8'}
        def git(*argv):
            return subprocess.check_output(['/usr/bin/git','-C',str(repo),*argv],env=host_env,stderr=subprocess.PIPE,text=True).strip()
        git('init','-q');git('config','user.name','Synthetic test');git('config','user.email','synthetic@example.com')
        (repo/'fixture.txt').write_text('synthetic\n');git('add','.');git('commit','-qm','fixture')
        head = git('rev-parse','HEAD');git('worktree','add','--detach',str(worktree),head)
        common = repo/'.git'
        gitdir = common/'worktrees'/worktree.name
        for name in ('.agents','.claude','.codex'):
            (worktree/name).mkdir();(worktree/name/'sentinel').write_text('protected')
        outside = root/'outside-sentinel';outside.write_text('outside')
        secret = home/'synthetic-secret';secret.write_text('synthetic, not an account credential')
        clean_config_sources(worktree,home)
        env = adapter.environment(home,temporary,objects,common,os.environ['PATH'])
        version = subprocess.run([str(codex),'--version'],env=env,capture_output=True,text=True,timeout=15,check=True)
        if version.stdout.strip() != adapter.VERSION:
            raise RuntimeError('Versão Codex diferente da revisada')
        evidence['runtime'] = version.stdout.strip()
        evidence['launcher_sha256'] = hashlib.sha256(codex.read_bytes()).hexdigest()
        native = []
        for executable in runtime.rglob('codex'):
            if executable.is_file() and not executable.is_symlink():
                with executable.open('rb') as stream:
                    if stream.read(4) == b'\x7fELF':
                        native.append(executable)
        if len(native) != 1:
            raise RuntimeError('Executável Codex nativo ausente/ambíguo')
        evidence['native_executable_sha256'] = hashlib.sha256(native[0].read_bytes()).hexdigest()
        evidence['native_executable_relative_path'] = str(native[0].relative_to(runtime))
        protected = [worktree/'.git',common,gitdir,*[worktree/x for x in ('.agents','.claude','.codex')]]
        profile = adapter.policy(worktree,temporary,objects,protected,[Path(sys.base_prefix),runtime,Path(__file__).with_name('probe.py')])
        evidence['profile_sha256'] = hashlib.sha256(adapter.inline(profile).encode()).hexdigest()
        spec = {'host_namespaces': {n:os.readlink('/proc/self/ns/'+n) for n in ('pid','net','user')},
                'writable':list(map(str,(worktree,temporary,objects))),
                'denied_write':list(map(str,(outside,worktree/'.git',common/'config',*[worktree/n/'sentinel' for n in ('.agents','.claude','.codex')]))),
                'secret_sentinel':str(secret),'head':head,'worktree':str(worktree),'objects':str(objects),
                'direct_ip':socket.gethostbyname('api.github.com')}
        before = digest_tree(common)
        payload = [sys.executable,'-I',str(Path(__file__).with_name('probe.py')),json.dumps(spec)]
        cmd = adapter.command(codex,worktree,profile,payload)
        result = adapter.run(cmd,worktree,env,timeout=60)
        evidence['exit_code'] = result['exit_code']
        print(result['stderr'].decode('utf-8',errors='replace')[:8000],file=sys.stderr)
        if result['exit_code'] != 0:
            raise RuntimeError('Probe nativo falhou: '+result['stdout'].decode('utf-8',errors='replace')[:4000])
        lines = [line for line in result['stdout'].decode().splitlines() if line.startswith('OFFICE_NATIVE_PROBE ')]
        if len(lines) != 1:
            raise RuntimeError('Evidência nativa ausente/ambígua')
        evidence['probe'] = json.loads(lines[0].split(' ',1)[1])
        assert digest_tree(common) == before, 'Metadados/objetos canônicos foram alterados'
        assert outside.read_text() == 'outside'
        # Native detached descendant must disappear with the sandbox namespace.
        spec.update(detached=True,heartbeat=str(temporary/'heartbeat'))
        cmd = adapter.command(codex,worktree,profile,[*payload[:-1],json.dumps(spec)])
        try:
            adapter.run(cmd,worktree,env,timeout=30)
        except adapter.SandboxFailure as exc:
            output = exc.result['stdout'].decode()
            assert 'OFFICE_DETACHED_STARTED' in output, 'Filho destacado não iniciou; timeout inconclusivo'
            assert exc.result['state'] == 'uncertain'
            evidence['timeout'] = {'state':exc.result['state'],'exit_code':exc.result['exit_code'],
                                   'stdout_sha256':exc.result['stdout_sha256']}
        else:
            raise AssertionError('Timeout não ocorreu')
        heartbeat = temporary/'heartbeat'
        assert heartbeat.is_file(), 'Heartbeat ausente'
        last = heartbeat.read_bytes()
        time.sleep(1.5)
        assert heartbeat.read_bytes() == last, 'Filho destacado sobreviveu ao sandbox'
        evidence['detached_heartbeat_stopped'] = True
        assert digest_tree(common) == before
        evidence['state'] = 'passed'
        print('OFFICE_LINUX_GATE_VALIDATION '+json.dumps(evidence,sort_keys=True))


if __name__ == '__main__':
    main()
