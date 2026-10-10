"""Regressões dos providers em projetos/SQLite temporários, sem modelos ou rede."""
import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
from providers_console import Eventos, PROVIDERS, selecionar, comando_nativo
from skills_compartilhados import contexto, metadados, preparar_codex
from console_provider import executar
import importar_opencode
import emit_evento


class TestProviders(unittest.TestCase):
    def test_opencode_recebe_contexto_e_tarefa_extensa_por_stdin(self):
        with tempfile.TemporaryDirectory() as tmp:
            raiz=Path(tmp);(raiz/'CLAUDE.md').write_text('Regra compartilhada',encoding='utf-8')
            (raiz/'.claude/rules').mkdir(parents=True)
            fonte=raiz/'.claude/skills/comum/SKILL.md';fonte.parent.mkdir(parents=True)
            fonte.write_text('---\nname: comum\ndescription: Procedimento comum\n---\nCorpo',encoding='utf-8')
            captura=raiz/'recebido.json';fake=raiz/'fake.py'
            eventos=[{'type':t,'sessionID':'ses_parent','part':{'type':p,'sessionID':'ses_parent','messageID':'m',**extra}}
                     for t,p,extra in [('step_start','step-start',{}),('step_finish','step-finish',{'reason':'stop'})]]
            fake.write_text('import sys,json\nfrom pathlib import Path\nsys.stdin.reconfigure(encoding="utf-8")\n'+
                'Path('+repr(str(captura))+').write_text(json.dumps({"argv":sys.argv[1:],"entrada":sys.stdin.read()}),encoding="utf-8")\n'+
                'for ev in '+repr(eventos)+':print(json.dumps(ev),flush=True)\n',encoding='utf-8')
            tarefa='TAREFA-LITERAL & ` $(): ação\n'+'ç'*40000
            with patch('providers_console.comando_nativo',return_value=[sys.executable,str(fake)]):
                self.assertEqual(executar(PROVIDERS['opencode'],'opencode',raiz,'Dev',prompt=tarefa,
                                         modelo='opencode/free-test',sessao='ses_parent',agente='dev',banco=raiz/'office.db'),0)
            d=json.loads(captura.read_text(encoding='utf-8'))
            self.assertTrue(d['entrada'].endswith(tarefa));self.assertIn('Fonte do projeto: CLAUDE.md',d['entrada'])
            self.assertIn('.claude/rules/',d['entrada']);self.assertIn('.claude/skills/comum/SKILL.md',d['entrada'])
            self.assertNotIn(tarefa,d['argv']);self.assertLess(sum(map(len,d['argv'])),1000)
            self.assertEqual(d['argv'][d['argv'].index('--model')+1],'opencode/free-test')
            self.assertEqual(d['argv'][d['argv'].index('--session')+1],'ses_parent')
            self.assertEqual(d['argv'][d['argv'].index('--agent')+1],'dev')
            self.assertNotIn('--auto',d['argv']);self.assertFalse((raiz/'opencode.json').exists())
    def test_callback_recebe_somente_id_nativo_do_fluxo_principal(self):
        for nome,registros in (
            ('codex',[{'type':'thread.started','thread_id':'native-codex-1'},
                      {'type':'thread.started','thread_id':'native-codex-1'},
                      {'type':'futuro','thread_id':'id-nao-comprovado'}]),
            ('gemini',[{'type':'init','session_id':'native-gemini-1'},
                       {'type':'message','session_id':'id-nao-comprovado'}]),
            ('opencode',[{'type':'step_start','sessionID':'ses_parent'},
                         {'type':'tool_use','sessionID':'ses_parent','part':{'tool':'task','state':{
                             'status':'completed','metadata':{'sessionId':'ses_child'}}}},
                         {'type':'futuro','sessionID':'id-nao-comprovado'}])):
            with self.subTest(console=nome),tempfile.TemporaryDirectory() as tmp:
                raiz=Path(tmp); fake=raiz/'fake.py'
                fake.write_text('import json\nfor r in '+repr(registros)+': print(json.dumps(r))\n',encoding='utf-8')
                recebidos=[]
                with patch.object(type(PROVIDERS[nome]),'comando',return_value=[sys.executable,str(fake),'prompt']):
                    self.assertEqual(executar(PROVIDERS[nome],sys.executable,raiz,'Dev',prompt='teste',
                                     banco=raiz/'office.db',ao_sessao=recebidos.append),1)
                esperado={'codex':'native-codex-1','gemini':'native-gemini-1','opencode':'ses_parent'}[nome]
                self.assertEqual(recebidos,[esperado])
                eventos=Eventos(nome,'Dev')
                for registro in registros: eventos.converter(registro)
                self.assertEqual(eventos.sessao,esperado)

    def test_opencode_fonte_oficial_links_e_config_preservada(self):
        import io
        from contextlib import redirect_stdout
        with tempfile.TemporaryDirectory() as tmp:
            raiz=Path(tmp); (raiz/'.claude').mkdir(); (raiz/'.office').mkdir()
            fonte=raiz/'procedimentos/compartilhada/SKILL.md'; fonte.parent.mkdir(parents=True)
            fonte.write_text('---\nname: compartilhada\ndescription: Original\n---\nConteúdo',encoding='utf-8')
            (raiz/'REGRAS.md').write_text('Regra oficial',encoding='utf-8')
            politica={'fontes':{'regras':'REGRAS.md','skills':'procedimentos'}}
            (raiz/'.office/projeto.json').write_text(json.dumps(politica),encoding='utf-8')
            cfg={'model':'fornecedor/modelo','permission':{'bash':'ask'},'instructions':['docs/extra.md']}
            (raiz/'opencode.json').write_text(json.dumps(cfg),encoding='utf-8')
            original=fonte.read_bytes()
            with redirect_stdout(io.StringIO()):
                self.assertEqual(importar_opencode.main(['--projeto',str(raiz)]),0)
            self.assertFalse((raiz/'.agents').exists())
            self.assertEqual(json.loads((raiz/'opencode.json').read_text()),cfg)
            for _ in range(2):
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(importar_opencode.main(['--projeto',str(raiz),'--aplicar']),0)
            atual=json.loads((raiz/'opencode.json').read_text(encoding='utf-8'))
            self.assertEqual(atual,{**cfg,'instructions':['docs/extra.md','REGRAS.md']})
            self.assertEqual((raiz/'.agents/skills/compartilhada').resolve(),fonte.parent)
            self.assertEqual(fonte.read_bytes(),original)
            with self.assertRaises(ValueError): importar_opencode.plano_opencode_json(raiz,{'instructions':'REGRAS.md'})
            (raiz/'REGRAS.md').unlink()
            with redirect_stdout(io.StringIO()):
                self.assertEqual(importar_opencode.main(['--projeto',str(raiz),'--aplicar']),2)
            self.assertEqual(json.loads((raiz/'opencode.json').read_text(encoding='utf-8')),atual)

    def test_fonte_configurada_unica_para_catalogo_cadastro_e_links(self):
        from skills_compartilhados import catalogo
        from gestao_projeto import carregar
        import funcionarios
        with tempfile.TemporaryDirectory() as tmp:
            raiz=Path(tmp)
            for pasta,nome in (('procedimentos','compartilhada'),('.claude/skills','antiga')):
                alvo=raiz/pasta/nome/'SKILL.md'; alvo.parent.mkdir(parents=True)
                alvo.write_text(f'---\nname: {nome}\ndescription: Procedimento\n---\n',encoding='utf-8')
            (raiz/'politicas').mkdir()
            (raiz/'politicas/REGRAS.md').write_text('Fonte oficial',encoding='utf-8')
            (raiz/'CLAUDE.md').write_text('Entrada legada',encoding='utf-8')
            (raiz/'.office').mkdir()
            (raiz/'.office/projeto.json').write_text(json.dumps({'fontes':{
                'regras':'politicas/REGRAS.md','skills':'procedimentos'}}),encoding='utf-8')
            self.assertEqual([s['nome'] for s in catalogo(raiz)],['compartilhada'])
            self.assertEqual([s['nome'] for s in funcionarios.skills(raiz,carregar(raiz))],['compartilhada'])
            self.assertEqual([s['skill'] for s in preparar_codex(raiz)],['compartilhada'])
            self.assertEqual(preparar_codex(raiz,True)[0]['estado'],'compartilhado')
            self.assertEqual((raiz/'.agents/skills/compartilhada').resolve(),raiz/'procedimentos/compartilhada')
            texto=contexto(raiz)
            self.assertIn('politicas/REGRAS.md',texto)
            self.assertIn('procedimentos/compartilhada/SKILL.md',texto)
            self.assertNotIn('Fonte do projeto: CLAUDE.md',texto)
            self.assertNotIn('antiga',texto)
            invalida=raiz/'procedimentos/invalida/SKILL.md'; invalida.parent.mkdir()
            invalida.write_text('---\nname: invalida\n---\n',encoding='utf-8')
            self.assertEqual([s['nome'] for s in funcionarios.skills(raiz,carregar(raiz))],['compartilhada'])

    def test_diagnostico_por_arquivo_sem_shell_ou_truncamento(self):
        import console_provider
        with tempfile.TemporaryDirectory() as tmp:
            raiz=Path(tmp); arq=raiz/'diagnostico.json'
            arq.write_text('Diagnóstico: ação & $(literal)\n{"cartoes":[]}',encoding='utf-8-sig')
            with patch.object(console_provider,'selecionar',return_value=(PROVIDERS['codex'],'codex')), \
                 patch.object(console_provider,'executar',return_value=0) as rodar:
                self.assertEqual(console_provider.main(['--projeto',str(raiz),'--provider','codex','--prompt-arquivo',str(arq)]),0)
                self.assertEqual(rodar.call_args.args[4],'Diagnóstico: ação & $(literal)\n{"cartoes":[]}')
                for texto in (' ', 'x'*128001):
                    arq.write_text(texto,encoding='utf-8'); rodar.reset_mock()
                    self.assertEqual(console_provider.main(['--projeto',str(raiz),'--provider','codex','--prompt-arquivo',str(arq)]),2)
                    rodar.assert_not_called()

    def test_escolha_explicita_e_fallback(self):
        with patch.dict(os.environ, {}, clear=True):
            localizar = lambda n: n if n in ("claude", "codex") else None
            self.assertEqual(selecionar(localizar=localizar)[0].nome, "claude")
            self.assertEqual(selecionar("gpt", localizar=localizar)[0].nome, "codex")
            self.assertEqual(selecionar("auto", localizar=lambda n: n if n == "opencode" else None)[0].nome, "opencode")
            with self.assertRaises(ValueError):
                selecionar("opencode", localizar=localizar)
            with self.assertRaises(ValueError):
                selecionar("inventado", localizar=localizar)

    def test_comandos_preservam_aprovacao_e_sessao(self):
        self.assertEqual(PROVIDERS["claude"].comando("claude", Path(".")), ["claude"])
        self.assertEqual(PROVIDERS["claude"].comando("claude", Path("."), sessao="abc"), ["claude", "--resume", "abc"])
        self.assertEqual(PROVIDERS["codex"].comando("codex", Path("."), "tarefa", sessao="abc"),
                         ["codex", "exec", "resume", "abc", "--json", "tarefa"])
        self.assertIn("orquestrador", PROVIDERS["opencode"].comando("opencode", Path("."), agente="orquestrador"))
        with self.assertRaises(ValueError):
            PROVIDERS["codex"].comando("codex", Path("."), agente="team-dev")

    def test_shim_windows_sem_interpretar_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            pasta = Path(tmp)
            exe = pasta / "opencode.cmd"
            nativo = pasta / "node_modules/opencode-ai/bin/opencode.exe"
            nativo.parent.mkdir(parents=True)
            nativo.touch()
            self.assertEqual(comando_nativo(str(exe), "opencode"), [str(nativo)])
            prompt = 'teste & echo "literal"'
            self.assertEqual(PROVIDERS["opencode"].comando(str(exe), pasta, prompt)[-1], prompt)

    def test_claude_adapter_nao_muda_contrato(self):
        # Hook público usa configuração de instalação; dev usa nomes fixos.
        caminho = RAIZ / "registrar_evento.py"
        if not caminho.exists():
            caminho = RAIZ / "office one" / "registrar_evento.py"
            sys.path.insert(0, str(caminho.parent))
        spec = importlib.util.spec_from_file_location("hook_regressao", caminho)
        hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook)
        adapter = Eventos("claude", "Dev", hook.evento)
        for nome, ferramenta, entrada in [
            ("PreToolUse", "Bash", {"command": "pytest"}),
            ("PostToolUse", "Bash", {"command": "pytest"}),
            ("PostToolUseFailure", "Bash", {"command": "pytest"}),
            ("PostToolUse", "SendMessage", {"recipient": "Team_Boss", "message": "pronto"}),
            ("PostToolUse", "Agent", {"name": "Team_QA", "subagent_type": "team-qa"}),
            ("TeammateIdle", "", {}), ("Stop", "", {})]:
            registro = {"hook_event_name": nome, "tool_name": ferramenta, "tool_input": entrada,
                        "error": "Exit code 1", "teammate_name": "Team_Dev"}
            esperado = hook.evento(registro)
            with patch.object(hook, "datetime") as dt:
                dt.now.return_value.isoformat.return_value = "2026-10-09T10:00:00"
                esperado = hook.evento(registro)
                self.assertEqual(adapter.converter(registro), [esperado] if esperado else [])

    def test_codex_eventos_e_deduplicacao(self):
        e = Eventos("codex", "Dev")
        self.assertEqual(e.converter({"type": "thread.started", "thread_id": "abc"}), [])
        item = {"id": "1", "type": "command_execution", "command": "pytest", "exit_code": 1}
        self.assertTrue(e.converter({"type": "item.started", "item": item})[0]["inicio"])
        fim = e.converter({"type": "item.completed", "item": item})[0]
        self.assertFalse(fim["ok"])
        self.assertEqual(fim["sessao"], "abc")
        self.assertEqual(e.converter({"type": "item.completed", "item": item}), [])
        self.assertEqual(e.converter({"type": "futuro"}), [])
        self.assertEqual(e.converter({"type": "turn.completed"})[0]["tipo"], "ocioso")
        wait = e.converter({"type": "item.completed", "item": {
            "id": "wait", "type": "collab_tool_call", "tool": "wait",
            "receiver_thread_ids": ["thread-child"], "status": "completed"}})[0]
        self.assertEqual(wait["tipo"], "trabalho")
        self.assertEqual(wait["para"], [], "UUID de sessão não cria mesa fantasma")

    def test_opencode_skill_task_erro(self):
        e = Eventos("opencode", "Dev")
        registro = {"type": "tool_use", "sessionID": "s1", "part": {"tool": "skill",
                    "state": {"status": "completed", "input": {"name": "teste"}}}}
        ev = e.converter(registro)[0]
        self.assertEqual(ev["ferramenta"], "Skill")
        self.assertEqual(ev["detalhe"], "skill: teste")
        self.assertEqual(emit_evento.normalizar(ev)["sessao"], "s1")
        registro["part"] = {"tool": "task", "state": {"status": "error", "error": "falha",
                              "input": {"subagent_type": "qa"}}}
        ev = e.converter(registro)[0]
        self.assertEqual(ev["tipo"], "subagente")
        self.assertFalse(ev["ok"])
        registro["part"]["state"].update(metadata={"sessionId": "child"},
                                         status="completed", input={"subagent_type": "qa"})
        ev = e.converter(registro)[0]
        self.assertEqual(ev["para"], ["OpenCode_qa_child"])
        self.assertEqual(emit_evento.normalizar(ev)["sessao_filho"], "child")

    def test_skill_links_sem_copia_colisao_e_contexto(self):
        with tempfile.TemporaryDirectory() as tmp:
            projeto = Path(tmp)
            fonte = projeto / ".claude" / "skills" / "teste"
            fonte.mkdir(parents=True)
            arq = fonte / "SKILL.md"
            arq.write_text('---\nname: teste\ndescription: >-\n  Descrição\n  em duas linhas\n---\ncorpo', encoding="utf-8")
            original = arq.read_bytes()
            for nome in ("CLAUDE.md", "PRODUTO.md"):
                (projeto / nome).write_text("regras", encoding="utf-8")
            self.assertEqual(metadados(arq.read_text(encoding="utf-8"))["description"], "Descrição em duas linhas")
            self.assertEqual(preparar_codex(projeto)[0]["estado"], "planejado")
            self.assertFalse((projeto / ".agents").exists())
            resultado = preparar_codex(projeto, True)
            self.assertEqual(resultado[0]["estado"], "compartilhado")
            self.assertEqual(preparar_codex(projeto, True)[0]["estado"], "compartilhado")
            self.assertEqual(arq.read_bytes(), original)
            self.assertIn("PRODUTO.md", contexto(projeto))
            self.assertIn(".claude/skills/teste/SKILL.md", contexto(projeto))
            outro = projeto / ".claude" / "skills" / "outro"
            outro.mkdir()
            (outro / "SKILL.md").write_text("---\nname: outro\ndescription: outro\n---\n", encoding="utf-8")
            destino = projeto / ".agents" / "skills" / "outro"
            destino.mkdir()
            self.assertEqual(preparar_codex(projeto, True)[0]["estado"], "conflito preservado")

    def test_agente_somente_leitura_e_yaml(self):
        texto, _ = importar_opencode.converter("qa", {"description": "QA: verificação #1", "tools": "Read, Grep"}, "prompt", {}, "subagent")
        self.assertIn('"*": deny', texto)
        self.assertIn('description: "QA: verificação #1"', texto)
        self.assertNotIn("edit: allow", texto)

    def test_execucao_fake_eventos_sqlite_e_exitcode(self):
        with tempfile.TemporaryDirectory() as tmp:
            projeto = Path(tmp)
            banco = projeto / "office.db"
            fake = projeto / "fake.py"
            fake.write_text('import json\nprint(json.dumps({"type":"item.completed","item":{"id":"1","type":"command_execution","command":"teste","exit_code":1}}))\nraise SystemExit(7)\n', encoding="utf-8")
            provider = PROVIDERS["codex"]
            with patch.object(type(provider), "comando", return_value=[sys.executable, str(fake), "prompt"]):
                self.assertEqual(executar(provider, sys.executable, projeto, "Dev", prompt="teste", banco=banco), 7)
            with closing(sqlite3.connect(banco)) as c:
                eventos = [json.loads(r[0]) for r in c.execute("SELECT dados FROM evento")]
            self.assertTrue(any(e.get("ok") is False for e in eventos))
            self.assertEqual(eventos[-1]["tipo"], "ocioso")
            with patch("emit_evento.gravar", side_effect=OSError("offline")), patch.object(type(provider), "comando", return_value=[sys.executable, str(fake), "prompt"]):
                self.assertEqual(executar(provider, sys.executable, projeto, "Dev", prompt="teste", banco=banco), 7)


if __name__ == "__main__":
    unittest.main()
