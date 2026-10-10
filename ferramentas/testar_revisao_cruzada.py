"""Diversidade de fornecedores, contextos independentes e gate do commit exato."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gestao_projeto import validar, revisores, decidir_merge
from revisao_cruzada import revisar, conferir

SHA = "a" * 40
AUTOR = {"console": "claude", "modelo": ""}


class Revisao(unittest.TestCase):
    def test_aliases_do_mesmo_fornecedor_nao_criam_diversidade(self):
        from gestao_projeto import cloud_executor
        familias={'openai':['OpenAI','Open AI','open-ai','OpenAI API','ＯｐｅｎＡＩ'],
                  'anthropic':['Anthropic','anthropic-api'],
                  'google':['Google','Google AI','Google Cloud','Vertex AI'],
                  'nvidia':['NVIDIA','NVIDIA NIM']}
        for esperado,nomes in familias.items():
            for nome in nomes:
                with self.subTest(nome=nome):
                    self.assertEqual(cloud_executor({'console':'opencode','cloud':nome}),esperado)
        for nome in familias['openai']:
            cfg=self.cfg()
            cfg['revisao']['revisores']=[{'nome':'a','executor':{'console':'codex'}},
                {'nome':'b','executor':{'console':'opencode','cloud':nome}}]
            with self.subTest(nome=nome),self.assertRaises(ValueError):validar(cfg)

    def test_alias_do_autor_e_gateway_nao_aprovam_revisao(self):
        from gestao_projeto import cloud_executor
        cfg=self.cfg()
        cfg['revisao']['revisores']=[{'nome':'a','executor':{'console':'opencode','cloud':'Open AI'}},
                                    {'nome':'b','executor':{'console':'gemini'}}]
        with self.assertRaises(ValueError):revisores(cfg,{'console':'codex'})
        for nome in ('Zen','OpenCode Zen','open-router','ＯｐｅｎＣｏｄｅ'):
            with self.subTest(nome=nome),self.assertRaises(ValueError):
                cloud_executor({'console':'opencode','cloud':nome})
        self.assertEqual(cloud_executor({'console':'opencode','cloud':'Fornecedor Próprio'}),'fornecedor próprio')
        self.assertEqual(cloud_executor({'console':'opencode','execucao':'local','cloud':'Zen'}),'local')

    def test_relatorio_antigo_com_duas_grafias_nao_libera_merge(self):
        cfg=self.cfg()
        cfg['revisao']['revisores']=[{'nome':'a','executor':{'console':'codex'}},
            {'nome':'b','executor':{'console':'opencode','cloud':'Open AI'}},
            {'nome':'c','executor':{'console':'gemini'}}]
        atual=revisar(cfg,AUTOR,SHA,'diff','aceite','regras',lambda *a:{'veredito':'aprovado','achados':[]})
        self.assertEqual([r['nome'] for r in atual['revisoes']],['a','c'])
        self.assertTrue(conferir(cfg,atual,SHA))
        antigo=copy.deepcopy(atual)
        antigo['revisoes'][1].update(nome='b',cloud='open ai',executor=cfg['revisao']['revisores'][1]['executor'])
        self.assertFalse(conferir(cfg,antigo,SHA))
        self.assertFalse(decidir_merge(cfg,{'CI':'success'},relatorio_revisao=antigo,sha=SHA))

    def cfg(self):
        return validar({"ativo": True, "merge": {"modo": "automatico", "checks": ["CI"]},
            "revisao": {"ativo": True, "revisores": [
                {"nome": "Claude", "executor": {"console": "claude"}},
                {"nome": "Codex", "executor": {"console": "codex"}},
                {"nome": "Gemini", "executor": {"console": "gemini"}}]}})

    def test_zen_com_backend_nao_informado_nao_comprova_separacao_do_autor(self):
        with self.assertRaises(ValueError):
            revisores(self.cfg(),{'console':'opencode','modelo':'opencode/space-bunny-free'})

    def test_duas_clouds_distintas_do_autor(self):
        self.assertEqual([x["nome"] for x in revisores(self.cfg(), AUTOR)], ["Codex", "Gemini"])
        cfg = self.cfg()
        cfg["revisao"]["revisores"] = cfg["revisao"]["revisores"][:2]
        with self.assertRaises(ValueError):
            revisores(cfg, AUTOR)

    def test_console_diferente_nao_significa_cloud_diferente(self):
        cfg = self.cfg()
        cfg["revisao"]["revisores"] = [
            {"nome": "a", "executor": {"console": "codex"}},
            {"nome": "b", "executor": {"console": "opencode", "cloud": "openai"}}]
        with self.assertRaises(ValueError):
            validar(cfg)
        cfg["revisao"]["revisores"][1]["executor"].pop("cloud")
        with self.assertRaises(ValueError):
            validar(cfg)

    def test_contextos_independentes_e_sha_exato(self):
        prompts = []
        def chamar(executor, prompt):
            prompts.append(prompt)
            return {"veredito": "aprovado", "achados": []}
        cfg = self.cfg()
        relatorio = revisar(cfg, AUTOR, SHA, "+ correção", "teste passa", "regras", chamar)
        self.assertEqual(prompts[0], prompts[1])
        self.assertTrue(conferir(cfg, relatorio, SHA))
        self.assertTrue(decidir_merge(cfg, {"CI": "success"}, relatorio_revisao=relatorio, sha=SHA))
        self.assertFalse(decidir_merge(cfg, {"CI": "success"}))
        self.assertFalse(conferir(cfg, relatorio, "b" * 40))
        alterado = copy.deepcopy(cfg)
        alterado["revisao"]["separar_autor"] = False
        self.assertFalse(conferir(alterado, relatorio, SHA))

    def test_divergencia_e_falha_bloqueiam_sem_maioria(self):
        cfg = self.cfg()
        def chamar(executor, prompt):
            if executor["console"] == "gemini":
                return {"veredito": "reprovado", "achados": [{"prioridade": "P1", "arquivo": "a.py", "linha": 3, "evidencia": "Regressão no caso vazio"}]}
            return {"veredito": "aprovado", "achados": []}
        relatorio = revisar(cfg, AUTOR, SHA, "diff", "aceite", "regras", chamar)
        self.assertFalse(conferir(cfg, relatorio, SHA))
        relatorio = revisar(cfg, AUTOR, SHA, "diff", "aceite", "regras", lambda *a: "JSON quebrado")
        self.assertFalse(conferir(cfg, relatorio, SHA))
        self.assertTrue(all(x.get("erro") for x in relatorio["revisoes"]))

    def test_falha_console_enumerada_bloqueia_gate_sem_vazar_diagnostico(self):
        from revisores_console import FalhaRevisor
        import json
        cfg=self.cfg()
        def chamar(executor,prompt):
            if executor['console']=='gemini':raise FalhaRevisor(1,'cliente_nao_suportado')
            return {'veredito':'aprovado','achados':[]}
        r=revisar(cfg,AUTOR,SHA,'diff','aceite','regras',chamar)
        self.assertFalse(r['aprovado']);self.assertFalse(conferir(cfg,r,SHA))
        self.assertEqual(r['revisoes'][1]['falha_console'],{'motivo':'cliente_nao_suportado','codigo':1})
        self.assertIn('fornecedor recusou',r['revisoes'][1]['erro'])
        self.assertNotIn('stderr',json.dumps(r))
        valido=revisar(cfg,AUTOR,SHA,'diff','aceite','regras',lambda *a:{'veredito':'aprovado','achados':[]})
        for campo,valor in [('erro',''),('falha_console',{}),('aprovado',False)]:
            alterado=copy.deepcopy(valido);alterado['revisoes'][1][campo]=valor
            self.assertFalse(conferir(cfg,alterado,SHA))


if __name__ == "__main__":
    unittest.main()
