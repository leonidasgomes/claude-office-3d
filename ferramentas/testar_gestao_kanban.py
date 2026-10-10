"""Despacho e GitHub simulados: nenhum cartão/PR real é alterado."""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import gestao_cli
from gestao_projeto import validar
from kanban_gestao import Kanban, api
from providers_console import PROVIDERS


class KanbanGestao(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.raiz = Path(self.tmp.name)
        self.cfg = validar({"ativo": True, "kanban": {"repo": "owner/jogo", "owner": "owner", "numero": 4},
            "equipes": [{"nome": "Dev", "especialidade": "C++", "executor": {"console": "codex"}}]})
        (self.raiz / ".office").mkdir()
        (self.raiz / ".office" / "projeto.json").write_text(json.dumps(self.cfg), encoding="utf-8")
        self.chamadas = []
        self.status = "Backlog"

    def api(self, caminho, metodo="GET", dados=None):
        self.chamadas.append((caminho, metodo, dados))
        if '/dependencies/blocked_by?' in caminho:
            return []
        if "/fields?" in caminho:
            return [{"id": 1, "name": "Status", "options": [{"id": 9, "name": "Em andamento"}]},
                    {"id": 2, "name": "Time"}]
        if "/items?" in caminho:
            return [{"id": 8, "content": {"html_url": "https://github.com/owner/jogo/issues/42"},
                     "fields": [{"id": 1, "value": {"name": self.status}}, {"id": 2, "value": "Dev"}]}]
        if caminho.endswith("/issues/42"):
            return {"state": "open", "title": "Tarefa", "body": "**Objetivo:** Corrigir\n\n**Aceite:** Testes passam"}
        if "/pulls?" in caminho:
            return []
        if metodo == "PATCH":
            self.status = "Em andamento"
            return {}
        raise AssertionError(caminho)

    def kanban(self):
        return Kanban(self.cfg, self.raiz / "quadro.json", chamar=self.api)

    def test_cache_e_escrita_rest(self):
        k = self.kanban()
        self.assertEqual(k.cartao(42)["equipe"], "Dev")
        n = len(self.chamadas)
        k.quadro()
        self.assertEqual(len(self.chamadas), n)
        k.mover(42, "Em andamento")
        self.assertEqual(self.chamadas[-1][1:], ("PATCH", {"fields": [{"id": 1, "value": 9}]}))
        self.assertFalse(k.cache.exists())

    def test_cursor_gh_e_campos_explicitos(self):
        paginas = [[{'id': i} for i in range(100)], [{'id': 101}]]
        with patch('kanban_gestao.subprocess.run', return_value=SimpleNamespace(returncode=0, stdout=json.dumps(paginas))) as rodar:
            self.assertEqual(len(api('users/owner/projectsV2/4/items?fields=1,2', paginar=True)), 101)
            self.assertIn('--paginate', rodar.call_args.args[0]); self.assertIn('--slurp', rodar.call_args.args[0])
        self.kanban().quadro()
        caminho = next(c[0] for c in self.chamadas if '/items?' in c[0])
        self.assertIn('fields=1,2', caminho); self.assertNotIn('&page=', caminho)

    def test_cache_titulo_antigo_e_campos_alterados_invalidam(self):
        k = self.kanban(); dados = k.quadro(); dados.pop('campos_consultados')
        k.cache.write_text(json.dumps(dados), encoding='utf-8')
        n = len(self.chamadas); k.quadro(); self.assertGreater(len(self.chamadas), n)
        k.cfg['campo_time'] = 'Outra área'
        with self.assertRaises(ValueError): k.quadro()

    def test_rede_falha_nao_usa_cache_no_despacho(self):
        k = self.kanban()
        k.quadro()
        k.chamar = lambda *_: (_ for _ in ()).throw(ValueError("offline"))
        with self.assertRaises(ValueError):
            k.cartao(42, ao_vivo=True)

    def test_cartao_outro_repo_rejeitado(self):
        with self.assertRaises(ValueError):
            self.kanban().cartao(99)

    def test_preparacao_sem_escrita(self):
        with patch("gestao_cli.selecionar", return_value=(PROVIDERS["codex"], "codex")):
            pacote = gestao_cli.preparar(self.raiz, 42, "Dev", kanban=self.kanban())[4]
        self.assertEqual(pacote["aceite"], "Testes passam")
        self.assertFalse(any(c[1] != "GET" for c in self.chamadas))

    def test_exit_zero_sem_pr_fica_bloqueado(self):
        k = self.kanban()
        with patch("gestao_cli.selecionar", return_value=(PROVIDERS["codex"], "codex")), \
                patch("gestao_cli.validar_worktree", return_value=self.raiz), \
                patch("gestao_cli.subprocess.run", return_value=SimpleNamespace(stdout="feat/tarefa")):
            r = gestao_cli.despachar(self.raiz, 42, "Dev", "implementacao", self.raiz,
                                    banco=self.raiz / "tarefas.db", kanban=k, rodar=lambda *a, **kw: 0,
                                    banco_execucoes=self.raiz/'execucoes.db')
        self.assertEqual(r["estado"], "bloqueado")
        self.assertEqual(sum(c[1] == "PATCH" for c in self.chamadas), 1)

    def test_dependencia_aberta_impede_reserva_movimento_e_modelos(self):
        k = self.kanban(); original = k.chamar
        dep = {'number':1,'html_url':'https://github.com/owner/jogo/issues/1','state':'open','state_reason':None}
        k.bloqueadores = lambda _: [dep]
        k.chamar = lambda caminho,*a: dep if caminho.endswith('/issues/1') else original(caminho,*a)
        db = self.raiz/'nao-criar.db'
        with patch('gestao_cli.selecionar',return_value=(PROVIDERS['codex'],'codex')),patch('gestao_cli.executar') as modelo:
            with self.assertRaisesRegex(ValueError,'não concluída'):
                gestao_cli.despachar(self.raiz,42,'Dev','implementacao',self.raiz,banco=db,kanban=k,rodar=modelo,
                                    banco_execucoes=self.raiz/'execucoes.db')
            modelo.assert_not_called()
        self.assertFalse(db.exists()); self.assertFalse(any(c[1]=='PATCH' for c in self.chamadas))

    def test_dependencia_reaberta_apos_reserva_impede_execucao(self):
        k = self.kanban(); original = k.chamar; consultas = []
        dep = {'number':1,'html_url':'https://github.com/owner/jogo/issues/1','state':'closed','state_reason':'completed'}
        def bloqueadores(_):
            consultas.append(1)
            if len(consultas)>1: dep['state']='open'
            return [dep]
        k.bloqueadores = bloqueadores
        k.chamar = lambda caminho,*a: dep if caminho.endswith('/issues/1') else original(caminho,*a)
        db = self.raiz/'tarefas.db'
        with patch('gestao_cli.selecionar',return_value=(PROVIDERS['codex'],'codex')), \
             patch('gestao_cli.validar_worktree',return_value=self.raiz), \
             patch('gestao_cli.estado_git',return_value={'branch':'feat/card-42','sha':'a'*40}), \
             patch('gestao_cli.executar') as modelo:
            with self.assertRaises(ValueError):
                gestao_cli.despachar(self.raiz,42,'Dev','implementacao',self.raiz,banco=db,kanban=k,rodar=modelo,
                                    banco_execucoes=self.raiz/'execucoes.db')
            modelo.assert_not_called()
        self.assertFalse(any(c[1]=='PATCH' for c in self.chamadas))
        self.assertEqual(gestao_cli.Controle(db).listar('owner/jogo')[0]['estado'],'bloqueado')

    def test_pr_rascunho_e_cartao_errado_nao_sao_entrega(self):
        k = self.kanban()
        for pr in ({"head": {"ref": "feat/a"}, "draft": True, "body": "Closes #42"},
                   {"head": {"ref": "feat/a"}, "draft": False, "body": "Closes #43"}):
            k.chamar = lambda *a: [pr]
            self.assertIsNone(k.entrega(42, "feat/a"))
        k.chamar = lambda *a: [{"head": {"ref": "feat/a"}, "draft": False, "body": "Closes #42"}]
        self.assertIsNotNone(k.entrega(42, "feat/a"))


if __name__ == "__main__":
    unittest.main()
