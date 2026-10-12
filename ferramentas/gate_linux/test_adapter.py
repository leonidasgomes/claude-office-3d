"""Testes unitários de construção e supervisão; NÃO atestam sandbox nativo."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parent))
import adapter


class Adapter(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ('worktree', 'tmp', 'objects', 'git', 'home'):
            (self.root/name).mkdir()
        self.profile = adapter.policy(self.root/'worktree', self.root/'tmp', self.root/'objects',
                                      [self.root/'git', self.root/'worktree'/'.git'], [])

    def test_explicit_profile_does_not_grant_root_home_or_global_tmp(self):
        p = self.profile
        self.assertNotIn('extends', p)
        self.assertEqual(p['filesystem'][':minimal'], 'read')
        self.assertNotIn(':root', p['filesystem'])
        self.assertNotIn('/tmp', p['filesystem'])
        self.assertEqual(p['filesystem'][str(self.root/'git')], 'read')
        self.assertEqual(p['network']['domains'], {'api.github.com':'allow','github.com':'allow'})
        self.assertFalse(p['network']['enable_socks5'])
        self.assertFalse(p['network']['enable_socks5_udp'])
        self.assertFalse(p['network']['allow_upstream_proxy'])

    def test_overlaps_fail_closed(self):
        with self.assertRaises(ValueError):
            adapter.policy(self.root/'worktree', self.root/'tmp', self.root/'objects', [self.root], [])
        with self.assertRaises(ValueError):
            adapter.policy(self.root/'worktree', self.root/'tmp', self.root/'objects', [], [self.root])

    def test_toml_escapes_paths(self):
        import tomllib
        self.assertEqual(tomllib.loads('permissions=' + adapter.inline({'test': self.profile}))['permissions']['test'], self.profile)

    def test_command_managed_proxy_no_shell(self):
        cmd = adapter.command(sys.executable, self.root/'worktree', self.profile, [sys.executable, '-I', '-c', 'pass'])
        self.assertIn('--include-managed-config',cmd)
        self.assertIn('features.network_proxy=true',cmd)
        self.assertNotIn('exec',cmd)
        self.assertNotIn('windows.sandbox', ' '.join(cmd))
        self.assertEqual(cmd[cmd.index('--')+1:], [sys.executable,'-I','-c','pass'])

    def test_env_never_copies_credentials_or_python_injection(self):
        os.environ['SYNTHETIC_TOKEN'] = 'synthetic'
        self.addCleanup(os.environ.pop, 'SYNTHETIC_TOKEN')
        env = adapter.environment(self.root/'home',self.root/'tmp',self.root/'objects',self.root/'git','/usr/bin')
        self.assertNotIn('SYNTHETIC_TOKEN',env)
        self.assertNotIn('PYTHONPATH',env)
        self.assertNotIn('HTTPS_PROXY',env)
        self.assertEqual(env['GIT_TERMINAL_PROMPT'],'0')

    @unittest.skipUnless(os.name == 'posix', 'POSIX supervisor')
    def test_output_exit_and_hashes(self):
        result = adapter.run([sys.executable,'-I','-c','import sys; print("valid report");sys.exit(1)'],self.root,{},timeout=3)
        self.assertEqual(result['exit_code'],1)
        self.assertEqual(result['state'],'exited')
        self.assertEqual(result['stdout'],b'valid report\n')
        self.assertEqual(len(result['stdout_sha256']),64)
        self.assertFalse(result['inference'])

    @unittest.skipUnless(os.name == 'posix', 'POSIX supervisor')
    def test_timeout_never_passes(self):
        with self.assertRaises(adapter.SandboxFailure) as e:
            adapter.run([sys.executable,'-I','-c','import time;time.sleep(60)'],self.root,{},timeout=.1)
        self.assertEqual(e.exception.result['state'],'uncertain')
        self.assertNotEqual(e.exception.result['exit_code'],0)

    @unittest.skipUnless(os.name == 'posix', 'POSIX supervisor')
    def test_output_limit_never_passes(self):
        with self.assertRaises(adapter.SandboxFailure) as e:
            adapter.run([sys.executable,'-I','-c','print("x"*10000)'],self.root,{},output_limit=50)
        self.assertEqual(e.exception.result['state'],'uncertain')
        self.assertLessEqual(len(e.exception.result['stdout']),50)

    @unittest.skipUnless(os.name == 'posix', 'POSIX supervisor')
    def test_callback_error_still_cleans_up(self):
        def bad(_):raise ValueError('synthetic callback failure')
        with self.assertRaises(adapter.SandboxFailure) as e:
            adapter.run([sys.executable,'-I','-c','import time;time.sleep(60)'],self.root,{},callback=bad)
        self.assertEqual(e.exception.result['state'],'uncertain')
        self.assertNotEqual(e.exception.result['exit_code'],0)


if __name__ == '__main__':unittest.main()
