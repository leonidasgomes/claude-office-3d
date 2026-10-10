"""Contrato HTTP do escritório recebe os três providers na mesma tabela, sem migração."""
import http.client
import json
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
OFFICE = RAIZ / "office one" if (RAIZ / "office one").is_dir() else RAIZ
sys.path.insert(0, str(OFFICE))
import banco
import emit_evento
import servidor
import rede
from providers_console import Eventos, hook_claude
from codex_observador import Transcrito


class TestHTTP(unittest.TestCase):
    def test_politica_http_origem_versao_e_merge_preservado(self):
        from politica_painel import snapshot
        from gestao_projeto import validar,carregar
        from funcionarios import id_projeto
        anterior=servidor.Handler.rede
        with tempfile.TemporaryDirectory() as tmp:
            raiz=Path(tmp);(raiz/'.office').mkdir()
            cfg=validar({'ativo':True,'merge':{'modo':'automatico','checks':['CI']},'equipes':[]})
            arquivo=raiz/'.office/projeto.json';arquivo.write_text(json.dumps(cfg),encoding='utf-8')
            original=arquivo.read_bytes();versao=snapshot(raiz)[1]
            servidor.Handler.rede=rede.Rede(raiz,False,False)
            srv=ThreadingHTTPServer(('127.0.0.1',0),partial(servidor.Handler,directory=str(raiz)))
            thread=threading.Thread(target=srv.serve_forever,daemon=True);thread.start()
            host=f'127.0.0.1:{srv.server_address[1]}'
            body=json.dumps({'projeto_id':id_projeto(raiz),'versao':versao,'executores':{
                'ceo':{'console':'codex'},'diretor':{'console':'gemini'},'equipes':[]}})
            try:
                with patch.object(servidor,'cfg',return_value={'projetos':[str(raiz)]}):
                    con=http.client.HTTPConnection('127.0.0.1',srv.server_address[1],timeout=10)
                    try:
                        h={'Host':host,'Content-Type':'application/json','X-Office-Acao':'1','Origin':'https://outra.example'}
                        con.request('POST','/api/gestao/executores',body,h);r=con.getresponse();r.read();self.assertEqual(r.status,403)
                        self.assertEqual(arquivo.read_bytes(),original)
                        h['Origin']='http://'+host
                        con.request('POST','/api/gestao/executores',body,h);r=con.getresponse();r.read();self.assertEqual(r.status,200)
                        self.assertEqual(carregar(raiz)['merge'],cfg['merge'])
                        con.request('POST','/api/gestao/executores',body,h);r=con.getresponse();r.read();self.assertEqual(r.status,409)
                    finally:con.close()
            finally:srv.shutdown();srv.server_close();thread.join();servidor.Handler.rede=anterior

    def test_cadastro_http_origem_e_pc(self):
        from gestao_projeto import validar
        from funcionarios import id_projeto, listar
        anterior=servidor.Handler.rede
        with tempfile.TemporaryDirectory() as tmp:
            raiz=Path(tmp); (raiz/'.office').mkdir()
            cfg=validar({'ativo':True,'equipes':[{'nome':'Dev','especialidade':'código','executor':{'console':'claude'}}]})
            (raiz/'.office/projeto.json').write_text(json.dumps(cfg),encoding='utf-8')
            servidor.Handler.rede=rede.Rede(raiz,False,False)
            srv=ThreadingHTTPServer(('127.0.0.1',0),partial(servidor.Handler,directory=str(raiz)))
            thread=threading.Thread(target=srv.serve_forever,daemon=True); thread.start()
            body=json.dumps({'projeto_id':id_projeto(raiz),'funcionario':{'nome':'QA','funcao':'Testar','equipe':'Dev','executor':{'console':'codex'},'skills':[]}})
            host=f'127.0.0.1:{srv.server_address[1]}'
            try:
                with patch.object(servidor,'cfg',return_value={'projetos':[str(raiz)]},create=True),patch.object(servidor,'REPO_LOCAL',raiz,create=True):
                    con=http.client.HTTPConnection('127.0.0.1',srv.server_address[1],timeout=10)
                    try:
                        headers={'Host':host,'Content-Type':'application/json','X-Office-Acao':'1','Origin':'https://estranho.example'}
                        con.request('POST','/api/gestao/funcionarios',body,headers); r=con.getresponse(); r.read(); self.assertEqual(r.status,403)
                        self.assertEqual(listar(raiz),[])
                        headers['Origin']='http://'+host
                        con.request('POST','/api/gestao/funcionarios',body,headers); r=con.getresponse(); dados=json.loads(r.read()); self.assertEqual(r.status,201)
                        self.assertEqual(dados['funcionario']['nome'],'QA'); self.assertEqual(len(listar(raiz)),1)
                        self.assertEqual(rede.PERMISSAO_ROTA['/api/gestao/funcionarios'],{'pc'})
                    finally: con.close()
            finally:
                srv.shutdown(); srv.server_close(); thread.join(); servidor.Handler.rede=anterior

    def test_consumo_no_painel_sem_expor_sessao_ou_projeto(self):
        from consumo_providers import Coletor
        anterior = banco.ARQ, servidor.Handler.rede
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            banco.ARQ = raiz / 'office.db'
            servidor.Handler.rede = rede.Rede(raiz, False, False)
            c = Coletor(raiz / 'consumo_providers.db', 'codex', raiz, 'Dev', 'modelo')
            c.consumir({'type': 'thread.started', 'thread_id': 'sessao-privada'})
            c.consumir({'type': 'turn.completed', 'usage': {'input_tokens': 100, 'output_tokens': 20}})
            srv = ThreadingHTTPServer(('127.0.0.1', 0), partial(servidor.Handler, directory=str(raiz)))
            thread = threading.Thread(target=srv.serve_forever, daemon=True); thread.start()
            try:
                with patch('uso_providers.limites_codex', return_value={'provider': 'codex', 'disponivel': False}):
                    con = http.client.HTTPConnection('127.0.0.1', srv.server_address[1], timeout=10)
                    try:
                        con.request('GET', '/api/uso/providers', headers={'Host': f'127.0.0.1:{srv.server_address[1]}'})
                        resposta = con.getresponse(); corpo = resposta.read().decode()
                        self.assertEqual(resposta.status, 200)
                        dados = json.loads(corpo)
                        self.assertEqual(dados['consumo']['grupos'][0]['total'], 120)
                        self.assertNotIn('sessao-privada', corpo)
                        self.assertNotIn(tmp, corpo)
                        self.assertIsNone(dados['consumo']['cobranca_usd'])
                    finally:
                        con.close()
            finally:
                srv.shutdown(); srv.server_close(); thread.join()
                banco.ARQ, servidor.Handler.rede = anterior

    def test_tres_providers_e_tui_mesmo_feed(self):
        anteriores = banco.ARQ, banco.EVENTOS_JSONL, servidor.Handler.rede
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            banco.ARQ = raiz / "office.db"
            banco.EVENTOS_JSONL = raiz / "ausente.jsonl"
            servidor.Handler.rede = rede.Rede(raiz, False, False)
            srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(servidor.Handler, directory=str(raiz)))
            thread = threading.Thread(target=srv.serve_forever, daemon=True)
            thread.start()
            try:
                claude = Eventos("claude", "Team_QA", hook_claude(RAIZ))
                original = claude.converter({"hook_event_name": "PostToolUse", "tool_name": "Read",
                    "teammate_name": "Team_QA", "tool_input": {"file_path": "AGENTS.md"}})[0]
                original["fonte"] = "claude"  # apenas fixture; hook original continua sem esta chave
                emit_evento.gravar(emit_evento.normalizar(original), banco.ARQ)
                codex = Eventos("codex", "Team_Dev")
                for ev in codex.converter({"type": "item.completed", "item": {"id": "1", "type": "command_execution", "command": "Get-Content AGENTS.md", "exit_code": 0}}):
                    emit_evento.gravar(emit_evento.normalizar(ev), banco.ARQ)
                opencode = Eventos("opencode", "Team_Boss")
                for ev in opencode.converter({"type": "tool_use", "sessionID": "open1", "part": {"tool": "task", "state": {"status": "completed", "input": {"subagent_type": "qa-unreal"}}}}):
                    emit_evento.gravar(emit_evento.normalizar(ev), banco.ARQ)
                tui = Transcrito("Codex_TUI", lambda ev: emit_evento.gravar(emit_evento.normalizar(ev), banco.ARQ))
                tui.consumir({"type": "session_meta", "payload": {"id": "codex-tui"}})
                tui.consumir({"type": "response_item", "payload": {"type": "function_call", "name": "exec_command", "call_id": "t1", "arguments": '{"cmd":"Get-Location"}'}})
                con = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
                try:
                    con.request("GET", "/eventos?desde=0", headers={"Host": f"127.0.0.1:{srv.server_address[1]}"})
                    response = con.getresponse()
                    dados = json.loads(response.read())
                    self.assertEqual(response.status, 200)
                finally:
                    con.close()
                eventos = dados["eventos"]
                self.assertEqual({e["fonte"] for e in eventos}, {"claude", "codex", "opencode"})
                self.assertEqual(len(eventos), 4)
                self.assertTrue(any(e.get("sessao") == "codex-tui" and e.get("inicio") for e in eventos))
                self.assertTrue(any(e["tipo"] == "subagente" and e["para"] == ["qa-unreal"] for e in eventos))
            finally:
                srv.shutdown()
                srv.server_close()
                thread.join(timeout=5)
                banco.ARQ, banco.EVENTOS_JSONL, servidor.Handler.rede = anteriores


if __name__ == "__main__":
    unittest.main()
