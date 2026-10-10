"""TUI Codex: sessão exata, eventos parciais, ferramentas, fala, resume e ambiguidades."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from codex_observador import Observador, Transcrito


class TestObservador(unittest.TestCase):
    def escrever(self, caminho, registros, modo="w"):
        caminho.parent.mkdir(parents=True, exist_ok=True)
        with caminho.open(modo, encoding="utf-8") as f:
            for r in registros:
                f.write(json.dumps(r) + "\n")

    def meta(self, projeto, sessao):
        return {"type": "session_meta", "payload": {"id": sessao, "cwd": str(projeto), "source": "cli"}}

    def test_descoberta_filtro_e_eventos(self):
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            p = raiz / "projeto"
            p.mkdir()
            eventos = []
            o = Observador(p, "Dev", eventos.append, home=raiz)
            f = raiz / "sessions/2026/10/09/rollout-atual.jsonl"
            self.escrever(f, [self.meta(p, "s1"),
                {"type": "response_item", "payload": {"type": "function_call", "call_id": "1", "name": "exec_command", "arguments": '{"cmd":"pytest"}'}},
                {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "1", "output": "Process exited with code 1"}},
                {"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Resultado"}]}},
                {"type": "event_msg", "payload": {"type": "task_complete"}}])
            o.tick()
            self.assertEqual(len(eventos), 4)
            self.assertTrue(eventos[0]["inicio"])
            self.assertFalse(eventos[1]["ok"])
            self.assertEqual(eventos[2]["tipo"], "fala")
            self.assertEqual(eventos[3]["tipo"], "ocioso")
            self.assertTrue(all(e["sessao"] == "s1" for e in eventos))
            o.tick()
            self.assertEqual(len(eventos), 4)

    def test_resume_nao_repete_historico_e_linha_parcial(self):
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            f = raiz / "sessions/2026/10/09/rollout-antigo.jsonl"
            self.escrever(f, [self.meta(raiz, "s1"), {"type": "event_msg", "payload": {"type": "task_complete"}}])
            eventos = []
            o = Observador(raiz, "Dev", eventos.append, sessao="s1", home=raiz)
            o.tick()
            self.assertEqual(eventos, [])
            linha = json.dumps({"type": "response_item", "payload": {"type": "custom_tool_call", "name": "apply_patch", "input": "patch", "call_id": "a"}})
            with f.open("a", encoding="utf-8") as arq:
                arq.write(linha[:20])
            o.tick()
            self.assertEqual(eventos, [])
            with f.open("a", encoding="utf-8") as arq:
                arq.write(linha[20:] + "\n")
            o.tick()
            self.assertEqual(eventos[0]["ferramenta"], "apply_patch")

    def test_ambiguidade_nao_escolhe_sessao_arbitraria(self):
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            avisos, eventos = [], []
            o = Observador(raiz, "Dev", eventos.append, home=raiz, avisar=avisos.append)
            for nome in ("a", "b"):
                self.escrever(raiz / f"sessions/2026/10/09/rollout-{nome}.jsonl", [self.meta(raiz, nome)])
            o.tick()
            o.tick()
            self.assertIsNone(o.caminho)
            self.assertEqual(len(avisos), 1)
            self.assertEqual(eventos, [])

    def test_descendentes_ancestralidade_e_identidades(self):
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            eventos = []
            o = Observador(raiz, "Lider", eventos.append, home=raiz)
            pasta = raiz / "sessions/2026/10/09"
            self.escrever(pasta / "rollout-root.jsonl", [self.meta(raiz, "root")])
            for ident, pai in (("neto", "filho"), ("filho", "root"), ("alheio", "outra-raiz")):
                meta = self.meta(raiz / "worktree", ident)
                meta["payload"]["source"] = {"subagent": {"thread_spawn": {
                    "parent_thread_id": pai, "agent_nickname": "QA", "agent_path": "/root/qa"}}}
                self.escrever(pasta / f"rollout-{ident}.jsonl", [meta, {
                    "type": "response_item", "payload": {"type": "function_call", "call_id": "a",
                    "name": "exec_command", "arguments": '{"cmd":"pytest"}'}}])
            o.tick()
            trabalhos = [e for e in eventos if e["tipo"] == "trabalho"]
            self.assertEqual({e["sessao"] for e in trabalhos}, {"filho", "neto"})
            self.assertEqual(len({e["agente"] for e in trabalhos}), 2)
            filho = next(e for e in trabalhos if e["sessao"] == "filho")
            neto = next(e for e in trabalhos if e["sessao"] == "neto")
            self.assertEqual(filho["agente_pai"], "Lider")
            self.assertEqual(neto["agente_pai"], filho["agente"])
            self.assertEqual(neto["sessao_pai"], "filho")
            tamanho = len(eventos)
            o.tick()
            self.assertEqual(len(eventos), tamanho)

    def test_historico_herdado_nao_muda_sessao_nem_repete_trabalho(self):
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            eventos = []
            o = Observador(raiz, "Lider", eventos.append, home=raiz,
                           observar_principal=False)
            pasta = raiz / "sessions/2026/10/09"
            self.escrever(pasta / "rollout-root.jsonl", [self.meta(raiz, "root")])
            child = self.meta(raiz, "child")
            child["payload"].update(subagent_history_start_ordinal=3,
                source={"subagent": {"thread_spawn": {"parent_thread_id": "root"}}})
            call = lambda ident: {"type": "response_item", "payload": {
                "type": "function_call", "name": "exec_command", "call_id": ident}}
            self.escrever(pasta / "rollout-child.jsonl", [child, self.meta(raiz, "root"),
                call("herdado"), call("proprio"), self.meta(raiz, "root"),
                {"type": "event_msg", "payload": {"type": "task_complete"}}])
            o.tick()
            self.assertEqual(eventos, [], "JSON aguarda thread.started")
            o.sessao = "root"
            o.tick()
            trabalhos = [e for e in eventos if e["tipo"] == "trabalho"]
            self.assertEqual(len(trabalhos), 1)
            self.assertEqual(trabalhos[0]["sessao"], "child")
            self.assertEqual(eventos[-1]["sessao"], "child")

    def test_nao_le_outro_projeto(self):
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            f = raiz / "sessions/2026/10/09/rollout-alheio.jsonl"
            self.escrever(f, [self.meta(raiz / "outro", "s1")])
            o = Observador(raiz, "Dev", lambda e: self.fail("evento alheio"), sessao="s1", home=raiz)
            o.tick()
            self.assertIsNone(o.caminho)


if __name__ == "__main__":
    unittest.main()
