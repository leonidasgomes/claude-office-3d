"""Cota não é cobrança; dados ausentes não viram zero. RPC simulado sem modelos."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from uso_providers import normalizar_limites
from rpc_console import Rpc


class Uso(unittest.TestCase):
    def test_multiplas_cotas_e_semana_por_duracao(self):
        resposta = {"rateLimits": {"limitId": "antigo"}, "rateLimitsByLimitId": {
            "a": {"primary": {"usedPercent": 12, "windowDurationMins": 300, "resetsAt": 200},
                  "secondary": {"usedPercent": 25, "windowDurationMins": 10080, "resetsAt": 500}},
            "b": {"primary": {"usedPercent": None, "windowDurationMins": 60}}}}
        dados = normalizar_limites(resposta, 100)
        self.assertEqual(len(dados["limites"]), 2)
        self.assertEqual(dados["limites"][0]["janelas"][1]["nome"], "semanal")
        self.assertEqual(dados["limites"][0]["janelas"][1]["restante_pct"], 75)
        self.assertIsNone(dados["limites"][1]["janelas"][0]["restante_pct"])
        self.assertNotIn("usd", json.dumps(dados))

    def test_reset_passado_nao_zera_uso(self):
        dados = normalizar_limites({"rateLimits": {"secondary": {
            "usedPercent": 90, "windowDurationMins": 10080, "resetsAt": 100}}}, 200)
        janela = dados["limites"][0]["janelas"][0]
        self.assertTrue(janela["expirado"])
        self.assertEqual(janela["usado_pct"], 90)
        self.assertFalse(normalizar_limites({})["disponivel"])

    def test_rpc_notificacoes_e_requisicao_nao_autorizada(self):
        script = '''import json,sys
for linha in sys.stdin:
 m=json.loads(linha)
 if "method" not in m: continue
 if m["method"]=="initialize":
  print(json.dumps({"id":m["id"],"result":{}}),flush=True)
 elif m["method"]=="read":
  print(json.dumps({"method":"news","params":{}}),flush=True)
  print(json.dumps({"method":"approval","id":99,"params":{}}),flush=True)
  resposta=json.loads(sys.stdin.readline())
  print(json.dumps({"id":m["id"],"result":{"negado":"error" in resposta}}),flush=True)
'''
        with tempfile.TemporaryDirectory() as pasta:
            arquivo = Path(pasta) / "fake.py"
            arquivo.write_text(script, encoding="utf-8")
            notificacoes = []
            with Rpc([sys.executable, "-u", str(arquivo)], notificar=notificacoes.append) as rpc:
                rpc.chamar("initialize", {})
                self.assertTrue(rpc.chamar("read")["negado"])
            self.assertEqual(notificacoes[0]["method"], "news")


if __name__ == "__main__":
    unittest.main()
