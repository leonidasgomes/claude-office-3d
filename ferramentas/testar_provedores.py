"""Validação, isolamento de ambiente, eventos JSON e execução literal sem usar APIs pagas."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE.parent))
import provedores
import rede
import servidor


class TestProvedores(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        self.addCleanup(patch.stopall)
        patch.object(provedores, 'RAIZ', self.dir).start()
        if hasattr(provedores, 'configurados'):
            patch.object(provedores, 'configurados', return_value=(self.dir, ('Team_Dev',))).start()
        else:
            patch.object(provedores, 'PROJETO', self.dir).start()
        patch.object(provedores, 'achar', return_value=sys.executable).start()
        patch.object(provedores, 'evento').start()
        with provedores.TRAVA:
            provedores.TAREFAS.clear()
            provedores.PROCESSOS.clear()

    def dados(self, **kwargs):
        return dict(provedor='ollama', mesa='Team_Dev', modelo='qwen3.5:9b', prompt='Leia o projeto.', **kwargs)

    def test_modelos_invalidos_nao_executam(self):
        for valor in ('--help', 'x & calc', 'x\nfoo', '$env:KEY', ['x']):
            d = self.dados(); d['modelo'] = valor
            with self.assertRaises(ValueError):
                provedores.preparar(d)
        for key, value in [('provedor', 'shell'), ('provedor', {}), ('mesa', 'intruso'), ('mesa', []), ('prompt', ''), ('prompt', []), ('prompt', 'x' * 12001)]:
            d = self.dados(); d[key] = value
            with self.assertRaises(ValueError):
                provedores.preparar(d)

    def test_ambiente_local_nao_vaza_para_nuvem(self):
        with patch.dict(os.environ, {'ANTHROPIC_AUTH_TOKEN': 'credencial-teste', 'CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS': '1'}):
            _, _, _, local, env = provedores.preparar(self.dados())
            self.assertEqual(env['ANTHROPIC_BASE_URL'], 'http://127.0.0.1:11434')
            self.assertEqual(env['ANTHROPIC_DEFAULT_OPUS_MODEL'], 'qwen3.5:9b')
            self.assertEqual(env['CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS'], '0')
            self.assertEqual(os.environ['ANTHROPIC_AUTH_TOKEN'], 'credencial-teste')
            d = self.dados(); d['provedor'] = 'claude'; d['modelo'] = ''
            _, _, _, cloud, cloud_env = provedores.preparar(d)
            self.assertEqual(cloud_env['ANTHROPIC_AUTH_TOKEN'], 'credencial-teste')
            self.assertNotIn('--model', cloud)
            self.assertNotIn('--dangerously-skip-permissions', local)

    def test_comandos_das_quatro_clis(self):
        for prov, flag in [('claude', '-p'), ('codex', 'exec'), ('gemini', '-p'), ('opencode', 'run')]:
            d = self.dados(); d.update(provedor=prov, modelo='')
            _, _, _, cmd, _ = provedores.preparar(d)
            self.assertIn(flag, cmd)
            self.assertFalse(any('yolo' in a or 'skip-permissions' in a for a in cmd))

    def test_eventos_dos_provedores(self):
        envelopes = [({'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': 'Olá'}]}}, 'fala', 'Olá'),
                     ({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'Feito'}}, 'fala', 'Feito'),
                     ({'type': 'message', 'role': 'assistant', 'content': 'Resposta Gemini'}, 'fala', 'Resposta Gemini'),
                     ({'type': 'text', 'part': {'type': 'text', 'text': 'Resposta OpenCode'}}, 'fala', 'Resposta OpenCode'),
                     ({'type': 'tool_use', 'tool_name': 'read_file'}, 'trabalho', 'read_file')]
        for d, tipo, texto in envelopes:
            self.assertEqual(provedores.interpretar(d), (tipo, texto))
        self.assertEqual(provedores.interpretar([]), ('', ''))

    def test_trava_ollama_e_mesa(self):
        with patch.object(provedores.threading, 'Thread') as thread:
            self.assertEqual(provedores.iniciar(self.dados())[0], 200)
            self.assertEqual(provedores.iniciar(self.dados())[0], 409)
            thread.assert_called_once()

    def test_permissoes_api(self):
        for rota in ('/api/provedores/iniciar', '/api/provedores/cancelar'):
            self.assertEqual(rede.PERMISSAO_ROTA[rota], {'pc'})
            self.assertTrue(rota.startswith(rede.ROTAS_NAVEGADOR))
        handler = object.__new__(servidor.Handler)
        for rota in ('/api/provedores', '/api/provedores/tarefas'):
            self.assertEqual(handler.api_get(rota, {}, {'permissao': 'ver'})[0], 403)
            self.assertEqual(handler.api_get(rota, {}, {'permissao': 'pc'})[0], 200)

    def test_cancelamento_pendente(self):
        with patch.object(provedores.threading, 'Thread'):
            code, d = provedores.iniciar(self.dados())
            self.assertEqual(code, 200)
            self.assertEqual(provedores.cancelar({'id': d['id']})[0], 200)
            self.assertEqual(provedores.estado()['tarefas'][0]['estado'], 'cancelando')
            self.assertEqual(provedores.iniciar(self.dados())[0], 409)
            self.assertEqual(provedores.cancelar({'id': []})[0], 400)

    def test_prompt_longo_literal_no_windows(self):
        script = self.dir / 'eco.py'
        script.write_text('import json,sys; print(json.dumps(sys.argv[1:]))', encoding='utf-8')
        prompt = 'Olá "aspas" & | ; $(Get-Date) `cmd` %PATH% \' fim\n' + 'x' * 12000
        cmd, arq = provedores.comando_arquivo([sys.executable, str(script), prompt], self.dir)
        try:
            r = subprocess.run(cmd, capture_output=True, encoding='utf-8', errors='replace', timeout=30,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(json.loads(r.stdout), [prompt])
        finally:
            if arq:
                arq.unlink(missing_ok=True)

    def test_execucao_sem_api_paga(self):
        script = self.dir / 'fixture.py'
        script.write_text('import json; print(json.dumps({"type":"item.completed","item":{"text":"fixture OK"}}))', encoding='utf-8')
        env = dict(os.environ, TEMP=str(self.dir), OFFICE_TASK_PROJECT=str(self.dir))
        for id_, cmd, expected in [('ok', [sys.executable, str(script)], 'concluida'),
                                   ('erro', [sys.executable, '-c', 'import sys; sys.exit(2)'], 'erro')]:
            provedores.TAREFAS[id_] = dict(id=id_, mesa='Team_Dev', provedor='codex', modelo='', estado='executando', resultado='', erro='')
            provedores.executar(id_, cmd, env)
            self.assertEqual(provedores.TAREFAS[id_]['estado'], expected)
            self.assertNotIn(id_, provedores.PROCESSOS)
        self.assertIn('fixture OK', provedores.TAREFAS['ok']['resultado'])

    @unittest.skipUnless(os.name == 'nt', 'Launcher npm específico do Windows')
    def test_wrapper_npm_resolvido_sem_shell(self):
        target = self.dir / 'node_modules' / 'cli' / 'main.js'
        target.parent.mkdir(parents=True)
        target.write_text('', encoding='utf-8')
        wrapper = self.dir / 'cli.cmd'
        wrapper.write_text('"%_prog%" "%dp0%\\node_modules\\cli\\main.js" %*', encoding='utf-8')
        with patch.object(provedores.shutil, 'which', return_value='node.exe'):
            cmd, _ = provedores.comando_arquivo([str(wrapper), '$(calc) & "literal"'], self.dir)
        self.assertEqual(cmd, ['node.exe', str(target.resolve()), '$(calc) & "literal"'])


if __name__ == '__main__':
    unittest.main()
