"""Regressões Linux dos launchers, sem contas, consoles ou dependências externas."""
import http.client
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
import instalar


@unittest.skipUnless(sys.platform.startswith("linux"), "Requer /proc do Linux")
class Lancadores(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="office com espaços ")
        self.addCleanup(self.tmp.cleanup)
        self.app = Path(self.tmp.name) / "aplicativo com espaços"
        self.app.mkdir()
        for nome in ("abrir_escritorio.sh", "reiniciar_escritorio.sh", "instalar.sh", "reiniciar_posix.py"):
            shutil.copy2(RAIZ / nome, self.app / nome)
        (self.app / "configuracao.py").write_text(
            "import json, os\nfrom pathlib import Path\n"
            "def carregar(): return json.loads(Path(os.environ['OFFICE_CONFIG']).read_text())\n")
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.porta = s.getsockname()[1]
        self.cfg = self.app / "config isolada.json"
        self.cfg.write_text(json.dumps({"porta": self.porta}))
        self.env = dict(os.environ, OFFICE_CONFIG=str(self.cfg), PYTHONWARNINGS="error")
        self.env.pop("PYTHONPATH", None)
        self.pids = []
        self.addCleanup(self.limpar_processos)
        (self.app / "servidor.py").write_text('''
import os, sys, json
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import configuracao
args = sys.argv[1:]
porta = int(args[args.index('--porta') + 1]) if '--porta' in args else configuracao.carregar()['porta']
Path('argumentos.json').write_text(json.dumps(args))
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b'office teste')
    def log_message(self, *args): pass
ThreadingHTTPServer(('127.0.0.1', porta), Handler).serve_forever()
''')

    def limpar_processos(self):
        for pid in self.pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        prazo = time.monotonic() + 3
        while time.monotonic() < prazo:
            try:
                with socket.create_connection(("127.0.0.1", self.porta), timeout=0.1):
                    time.sleep(0.05)
            except OSError:
                return

    def executar(self, nome="reiniciar_escritorio.sh", *args, env=None):
        r = subprocess.run(["sh", str(self.app / nome), *args], cwd="/tmp", env=env or self.env,
                           capture_output=True, text=True, timeout=30)
        self.pids.extend(int(pid) for pid in re.findall(r"PID (\d+)", r.stdout))
        return r

    def test_modelos_instalados_iguais(self):
        for nome, texto in instalar.ATALHOS.items():
            if nome.endswith(".sh"):
                self.assertEqual((RAIZ / nome).read_text(), texto)
        self.assertIn("reiniciar_posix.py", instalar.PACOTE)

    def test_iniciar_reiniciar_e_argumentos_com_espacos(self):
        for _ in range(2):
            r = self.executar("reiniciar_escritorio.sh", "celular", "--sem-https", "--porta", str(self.porta), "valor com espaços")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(r.stderr, "")
            self.assertIn("Pronto:", r.stdout)
            args = json.loads((self.app / "argumentos.json").read_text())
            self.assertEqual(args, ["--sem-navegador", "--rede-local", "--sem-https", "--porta", str(self.porta), "valor com espaços"])
        self.assertEqual(len(set(self.pids)), 2)

    def test_porta_explicita_prevalece_config(self):
        self.cfg.write_text('{"porta": 1}')
        r = self.executar("reiniciar_escritorio.sh", "--porta", str(self.porta))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(str(self.porta), r.stdout)

    def test_nao_encerra_processo_alheio(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", self.porta)); s.listen()
            r = self.executar()
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("outro processo", r.stderr)
            self.assertNotIn("Pronto:", r.stdout)
            self.assertGreater(s.fileno(), -1)

    def test_falha_de_partida_e_log(self):
        (self.app / "servidor.py").write_text("raise RuntimeError('falha simulada')\n")
        r = self.executar()
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("Pronto:", r.stdout)
        self.assertIn("falha simulada", (self.app / "dados/reinicio.log").read_text())

    def test_porta_invalida(self):
        for args in (("--porta",), ("--porta", "invalida"), ("--porta", "0"), ("--porta", "65536")):
            r = self.executar("reiniciar_escritorio.sh", *args)
            self.assertNotEqual(r.returncode, 0, args)
            self.assertFalse((self.app / "dados").exists())

    def test_python_ausente_erro_claro(self):
        binario = self.app / "bin"; binario.mkdir()
        (binario / "dirname").symlink_to(shutil.which("dirname"))
        env = dict(self.env, PATH=str(binario))
        for nome in ("abrir_escritorio.sh", "reiniciar_escritorio.sh", "instalar.sh"):
            r = subprocess.run(["/bin/sh", str(self.app / nome)], env=env, capture_output=True, text=True)
            self.assertEqual(r.returncode, 1)
            self.assertIn("Python 3.9+ não encontrado", r.stderr)

    def test_venv_preferido_e_argumentos_preservados(self):
        binario = self.app / ".venv/bin"; binario.mkdir(parents=True)
        (binario / "python").symlink_to(sys.executable)
        for nome, alvo in (("abrir_escritorio.sh", "servidor.py"), ("instalar.sh", "instalar.py")):
            (self.app / alvo).write_text("import sys, json; print(json.dumps(sys.argv[1:]))\n")
            r = self.executar(nome, "um argumento", "outro")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(json.loads(r.stdout), ["um argumento", "outro"])


if __name__ == "__main__":
    unittest.main()
