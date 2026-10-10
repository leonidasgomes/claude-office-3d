"""Fechamento antecipado de stdin: processo real e erros de I/O distintos."""
import contextlib,errno,io,json
from pathlib import Path
import subprocess,sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from console_provider import executar,pipe_entrada
from providers_console import PROVIDERS

class PipeConsole(unittest.TestCase):
    def test_pipe_fechado_preserva_saida_nativa_e_conclusao(self):
        for nome in ('codex','claude','opencode'):
            for codigo,completo,esperado in ((0,True,0),(7,True,7),(0,False,1)):
                with self.subTest(console=nome,codigo=codigo,completo=completo),tempfile.TemporaryDirectory() as tmp:
                    raiz=Path(tmp);fake=raiz/'fake.py'
                    eventos=([{'type':'thread.started','thread_id':'sessao'},{'type':'turn.started'}]+([{'type':'turn.completed'}] if completo else [])) if nome=='codex' else [
                        {'type':'system','subtype':'init','session_id':'sessao'},
                        {'type':'result','subtype':'success' if completo else 'error_during_execution','session_id':'sessao','is_error':not completo}]
                    if nome=='opencode':
                        eventos=[{'type':'step_start','sessionID':'sessao','part':{'type':'step-start','sessionID':'sessao','messageID':'m'}}]
                        if completo:eventos.append({'type':'step_finish','sessionID':'sessao','part':{'type':'step-finish','sessionID':'sessao','messageID':'m','reason':'stop'}})
                    fake.write_text('import sys,json\nfor e in '+repr(eventos)+': print(json.dumps(e),flush=True)\nsys.exit('+str(codigo)+')\n',encoding='utf-8')
                    processos=[]
                    def antes_entrada(p):
                        processos.append(p);p.wait(timeout=10) # Força encerramento antes do write/flush.
                    with patch('providers_console.comando_nativo',return_value=[sys.executable,str(fake)]),contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
                        self.assertEqual(executar(PROVIDERS[nome],nome,raiz,'Dev',prompt='tarefa',banco=raiz/'db',ao_processo=antes_entrada),esperado)
                    self.assertEqual(processos[0].returncode,codigo);self.assertTrue(processos[0].stdin.closed);self.assertTrue(processos[0].stdout.closed)
    def test_einval_e_epipe_em_write_close_outros_erros_nao_sao_ocultados(self):
        for codigo in (errno.EINVAL,errno.EPIPE):
            def falhar(*args):raise OSError(codigo,'pipe fechado')
            self.assertIsNone(pipe_entrada(falhar,'entrada'));self.assertIsNone(pipe_entrada(falhar))
        def io_falhou():raise OSError(errno.EIO,'outro erro')
        with self.assertRaises(OSError) as r:pipe_entrada(io_falhou)
        self.assertEqual(r.exception.errno,errno.EIO)

if __name__=='__main__':unittest.main()
