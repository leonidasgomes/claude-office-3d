"""Política isolada por projeto; sem rede, modelos ou alteração do GitHub."""
import json
import os
import subprocess
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gestao_projeto import carregar, validar, decidir_merge, contexto, fontes_resolvidas


class Politica(unittest.TestCase):
    def test_cpu_configuravel_sem_desativar_medicao(self):
        self.assertEqual(validar({})['local']['cpu_uso_max_pct'],75)
        self.assertEqual(validar({'local':{'cpu_uso_max_pct':60}})['local']['cpu_uso_max_pct'],60)
        for valor in (0,101,True,75.5,'75'):
            with self.subTest(valor=valor),self.assertRaises(ValueError):validar({'local':{'cpu_uso_max_pct':valor}})

    def test_papeis_locais_nao_escapam_do_perfil_simples(self):
        from gestao_projeto import executor
        for papel in ('ceo','diretor'):
            dados={'ativo':True,papel:{'console':'codex','modelo':'qwen','execucao':'local'}}
            for local in ({'ativo':False},{'ativo':True,'team':False}):
                with self.subTest(papel=papel,local=local),self.assertRaises(ValueError):
                    executor(validar({**dados,'local':local}),papel=papel)
            cfg=validar({**dados,'local':{'ativo':True,'team':True}})
            self.assertEqual(executor(cfg,papel=papel)['execucao'],'local')
    def test_legado_permanece_desativado(self):
        with tempfile.TemporaryDirectory() as pasta:
            cfg = carregar(pasta)
            self.assertFalse(cfg["ativo"])
            self.assertEqual(cfg["merge"]["modo"], "manual")
            self.assertFalse((Path(pasta) / ".office").exists())

    def test_merge_checks_e_excecao_manual(self):
        cfg = validar({"ativo": True, "merge": {"modo": "automatico", "checks": ["arquitetura", "revisor"]}})
        self.assertFalse(decidir_merge(cfg, {"arquitetura": "success"}))
        self.assertFalse(decidir_merge(cfg, {"arquitetura": "success", "revisor": "failure"}))
        checks = {"arquitetura": "success", "revisor": "success"}
        self.assertTrue(decidir_merge(cfg, checks))
        self.assertFalse(decidir_merge(cfg, checks, ["merge-manual"]))

    def test_erros_nao_habilitam_automacao(self):
        for cfg in ({"ativo": "false"}, {"merge": {"modo": "automatico"}},
                    {"versao": 2}, {"local": {"max_paralelo": 2}},
                    {"ceo": {"autonomia": "ilimitada"}}, {"rotas": {"inventado": {}}},
                    {"fontes": {"regras": "../segredo"}}, {"actvo": True}):
            with self.subTest(cfg=cfg), self.assertRaises(ValueError):
                validar(cfg)

    def test_prioridades_explicitas_unicas_e_sem_inferencia(self):
        self.assertEqual(validar({})['kanban']['prioridades'],[])
        self.assertEqual(validar({'kanban':{'prioridades':['Urgente','Normal']}})['kanban']['prioridades'],['Urgente','Normal'])
        for lista in ('P0', ['P0','P0'], [' '], [1], [' P0']):
            with self.subTest(lista=lista),self.assertRaises(ValueError):
                validar({'kanban':{'prioridades':lista}})
        with self.assertRaises(ValueError):
            validar({'kanban':{'prioridades':['P0'],'campo_prioridade':''}})

    def test_equipes_independentes_do_console(self):
        cfg = validar({"equipes": [
            {"nome": "Dev", "especialidade": "C++", "executor": {"console": "codex", "modelo": ""}},
            {"nome": "QA", "especialidade": "testes", "executor": {"console": "opencode", "modelo": ""}}]})
        self.assertEqual(cfg["equipes"][0]["executor"]["console"], "codex")
        duplicado = dict(cfg)
        duplicado["equipes"] = [cfg["equipes"][0]] * 2
        with self.assertRaises(ValueError):
            validar(duplicado)

    def test_referencias_canonicas_sao_explicitas_sem_copiar_corpo(self):
        with tempfile.TemporaryDirectory() as tmp:
            raiz=Path(tmp).resolve(); (raiz/'docs').mkdir()
            arq=raiz/'docs/Regras base.md'; arq.write_text('CORPO_PRIVADO',encoding='utf-8')
            cfg=validar({'ativo':True,'fontes':{'regras':'docs/Regras base.md'}})
            texto=contexto(raiz,cfg,equipe='Dev')
            self.assertIn(json.dumps(arq.as_posix()),texto)
            self.assertIn(json.dumps((raiz/'.office/projeto.json').as_posix()),texto)
            self.assertIn('outro worktree',texto)
            self.assertNotIn('CORPO_PRIVADO',texto)
            fontes=fontes_resolvidas(raiz,cfg)
            self.assertNotIn('CORPO_PRIVADO',json.dumps(fontes))
            self.assertEqual(fontes[0]['estado'],'arquivo'); self.assertEqual(len(fontes[0]['sha256']),64)
            self.assertEqual(fontes[1]['estado'],'ausente')

    def test_fonte_editada_ou_criada_muda_snapshot_sem_usar_horario(self):
        with tempfile.TemporaryDirectory() as tmp:
            raiz=Path(tmp); cfg=validar({'ativo':True})
            antes=fontes_resolvidas(raiz,cfg)
            self.assertEqual(antes,fontes_resolvidas(raiz,cfg))
            arq=raiz/'CLAUDE.md'; arq.write_text('Primeira regra',encoding='utf-8')
            criado=fontes_resolvidas(raiz,cfg); self.assertNotEqual(antes,criado)
            self.assertEqual(criado,fontes_resolvidas(raiz,cfg))
            arq.write_text('Outra regra',encoding='utf-8'); self.assertNotEqual(criado,fontes_resolvidas(raiz,cfg))

    def test_fonte_em_junction_fora_do_projeto_e_rejeitada(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp); raiz=base/'projeto'; raiz.mkdir(); fora=base/'fora'; fora.mkdir()
            (fora/'CLAUDE.md').write_text('regra externa',encoding='utf-8')
            try: (raiz/'referencias').symlink_to(fora,target_is_directory=True)
            except OSError:
                if os.name!='nt': self.skipTest('Symlink indisponível')
                ambiente={**os.environ,'TEST_REF_LINK':str(raiz/'referencias'),'TEST_REF_SOURCE':str(fora)}
                r=subprocess.run(['powershell','-NoProfile','-NonInteractive','-Command',
                    'New-Item -ItemType Junction -Path $env:TEST_REF_LINK -Target $env:TEST_REF_SOURCE -ErrorAction Stop | Out-Null'],
                    env=ambiente,capture_output=True,text=True,timeout=15)
                if r.returncode: self.skipTest('Junction indisponível')
            cfg=validar({'ativo':True,'fontes':{'regras':'referencias/CLAUDE.md'}})
            with self.assertRaisesRegex(ValueError,'fora do projeto'): fontes_resolvidas(raiz,cfg)

    def test_isolamento_de_projetos(self):
        with tempfile.TemporaryDirectory() as pasta:
            a, b = Path(pasta) / "a", Path(pasta) / "b"
            (a / ".office").mkdir(parents=True)
            (a / ".office" / "projeto.json").write_text(json.dumps({"ativo": True}), encoding="utf-8")
            self.assertTrue(carregar(a)["ativo"])
            self.assertFalse(carregar(b)["ativo"])


if __name__ == "__main__":
    unittest.main()
