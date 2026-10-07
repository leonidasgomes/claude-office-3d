"""Teste da triagem das sugestões do bot (sugestoes_bot.triar, _para_triar, _ha_para_triar e o ramo de triagem do coletar).

Uso: python -W error ferramentas/testar_sugestoes_triagem.py
Sem rede e sem tokens: a caixa fica numa pasta temporária, o GitHub (gh_api) e o `claude -p` (subprocess.run e
_achar_claude) são falsos. Cobre: item "nova" já na caixa é triado na coleta seguinte mesmo sem novas (a thread `pronto`
coleta sem triagem e pegava as novas antes); a tentativa é contada ANTES da chamada; depois de MAX_TENTATIVAS_TRIAGEM
chamadas sem classificação o item não vai mais ao modelo; falha do modelo conta tentativa; item tratado pelo líder no meio
da chamada não é sobrescrito; coletar(triagem=False) nunca chama o modelo.
"""
import json
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
import sugestoes_bot as sb  # noqa: E402

feitos, falhas = [], []


def checar(nome, cond, info=""):
    if cond:
        feitos.append(nome)
        print("  ok:", nome)
    else:
        falhas.append(nome)
        print("  FALHOU:", nome, info)


class Resp:
    def __init__(self, codigo, saida, erro=b""):
        self.returncode, self.stdout, self.stderr = codigo, saida, erro


class ModeloFalso:
    """Substitui subprocess.run. modo: 'ok' classifica tudo, 'vazio' responde sem classificar, 'falha' sai com 1,
    'lixo' responde texto sem JSON. `antes` (opcional) roda dentro da chamada (ex.: o líder trata um item no meio)."""

    def __init__(self, cfg):
        self.cfg, self.modo, self.chamadas, self.antes, self.tentativas_vistas = cfg, "ok", [], None, []

    def __call__(self, cmd, input=None, **kw):
        itens = json.loads(input.decode("utf-8").split("Itens:\n", 1)[1])
        self.chamadas.append([x["id"] for x in itens])
        caixa = {x["id"]: x for x in sb.ler_caixa(self.cfg)}
        self.tentativas_vistas.append({i["id"]: caixa[i["id"]].get("tentativas_triagem") for i in itens})
        if self.antes:
            self.antes()
        if self.modo == "falha":
            return Resp(1, b"", b"erro do modelo")
        if self.modo == "lixo":
            return Resp(0, json.dumps({"result": "nao sei", "is_error": False}).encode())
        resp = [] if self.modo == "vazio" else [{"id": i["id"], "acao": "corrigir", "motivo": "bug", "time_sugerido": "Dev"}
                                                 for i in itens]
        env = {"result": json.dumps(resp), "is_error": False, "total_cost_usd": 0.001, "usage": {"input_tokens": 10}}
        return Resp(0, json.dumps(env).encode())


def gh_falso(cfg, caminho, etag=None, timeout=90):
    """GitHub falso: um PR aberto (#10), nenhum comentário novo, nenhuma revisão."""
    if "/pulls?state=open" in caminho:
        return 200, [{"number": 10, "head": {"ref": "feat/x"}, "user": {"login": "dev"}, "title": "t", "labels": []}], {}
    return 200, [], {}


def item(id_, situacao="nova", **extra):
    x = {"id": id_, "tipo": "linha", "pr": 10, "arquivo": "a.py", "linha": 1, "prioridade": "P2", "titulo": "t " + id_,
         "texto": "texto", "link": "", "criado": "2026-10-07T00:00:00Z", "autor": "Copilot", "situacao": situacao,
         "branch": "feat/x", "pr_autor": "dev", "time_pr": "", "pr_titulo": "t", "acao_sugerida": "", "motivo": "",
         "time_sugerido": "", "nota": "", "tratada_em": "", "coletada_em": ""}
    x.update(extra)
    return x


def por_id(cfg):
    return {x["id"]: x for x in sb.ler_caixa(cfg)}


def main():
    with tempfile.TemporaryDirectory() as tmp:
        pasta = Path(tmp) / "sugestoes"
        cfg = {"repo": "dono/repo", "bots": ["Copilot"], "modelo": "modelo-falso", "intervalo_min": 15, "janela_dias": 3,
               "times": {}, "agentes": ["Dev"], "gh": "gh-falso", "pasta": pasta, "revisor": False}
        modelo = ModeloFalso(cfg)
        orig = (sb.subprocess.run, sb._achar_claude, sb.gh_api, sb.GLOSSARIO)
        sb.subprocess.run = modelo
        sb._achar_claude = lambda: "claude-falso"
        sb.gh_api = gh_falso
        sb.GLOSSARIO = Path(tmp) / "sem_glossario.md"
        try:
            # 1) a thread `pronto` coletou sem triagem: novas já na caixa, coleta atual sem novas -> tria mesmo assim
            sb.gravar_caixa(cfg, [item("1"), item("2"), item("3", "ignorada")])
            r = sb.coletar(cfg, triagem=False)
            checar("coletar(triagem=False) não chama o modelo", not modelo.chamadas and r["triadas"] == 0, (r, modelo.chamadas))
            checar("_ha_para_triar: há 'nova' sem tentativas", sb._ha_para_triar(cfg))
            r = sb.coletar(cfg)
            c = por_id(cfg)
            checar("coleta sem novas tria as 'nova' que já estavam na caixa", r["novas"] == 0 and r["triadas"] == 2
                   and c["1"]["situacao"] == c["2"]["situacao"] == "triada", (r, c["1"]["situacao"]))
            checar("só os 'nova' vão ao modelo (ignorada fica de fora)", modelo.chamadas == [["1", "2"]], modelo.chamadas)
            checar("tentativa contada ANTES da chamada (o modelo já vê 1)", modelo.tentativas_vistas[-1] == {"1": 1, "2": 1},
                   modelo.tentativas_vistas)
            checar("item ignorado não ganha tentativa", "tentativas_triagem" not in c["3"] and c["3"]["situacao"] == "ignorada")
            checar("_ha_para_triar falso depois de triar tudo", not sb._ha_para_triar(cfg))
            r = sb.coletar(cfg)
            checar("coleta seguinte sem 'nova' não chama o modelo", len(modelo.chamadas) == 1 and r["triadas"] == 0)

            # 2) resposta sem classificação: 2 tentativas e para
            modelo.chamadas.clear()
            modelo.modo = "vazio"
            sb.gravar_caixa(cfg, [item("4")])
            sb.coletar(cfg)
            checar("1ª resposta sem classificação: item continua 'nova' com 1 tentativa",
                   por_id(cfg)["4"]["situacao"] == "nova" and por_id(cfg)["4"]["tentativas_triagem"] == 1)
            sb.coletar(cfg)
            checar("2ª tentativa enviada", modelo.chamadas == [["4"], ["4"]] and por_id(cfg)["4"]["tentativas_triagem"] == 2,
                   modelo.chamadas)
            checar("_ha_para_triar falso com o item esgotado", not sb._ha_para_triar(cfg))
            checar("_para_triar exclui tentativas >= MAX", sb._para_triar(sb.ler_caixa(cfg)) == [])
            for _ in range(3):
                sb.coletar(cfg)
            checar("depois de 2 tentativas o item não é mais enviado (3 coletas, 0 chamadas)", len(modelo.chamadas) == 2,
                   modelo.chamadas)
            checar("triar direto também não envia o esgotado", sb.triar(cfg) == 0 and len(modelo.chamadas) == 2)
            checar("item esgotado continua 'nova' para o líder", por_id(cfg)["4"]["situacao"] == "nova"
                   and "NADA" != sb.texto_pendentes(cfg))
            checar("resumo() (painel/servidor) lê a caixa com o campo novo", any(x["id"] == "4" for x in sb.resumo(cfg)["itens"]))
            checar("--listar lê a caixa com o campo novo", "4" in sb.texto_listar(cfg))

            # 3) falha do modelo conta tentativa (código != 0 e texto sem JSON)
            modelo.chamadas.clear()
            modelo.modo = "falha"
            sb.gravar_caixa(cfg, [item("5"), item("6", tentativas_triagem=1)])
            r = sb.coletar(cfg)
            c = por_id(cfg)
            checar("falha do modelo: coletar não levanta e conta a tentativa",
                   r["erro"] == "" and r["triadas"] == 0 and c["5"]["tentativas_triagem"] == 1 and c["6"]["tentativas_triagem"] == 2,
                   (r, c["5"].get("tentativas_triagem"), c["6"].get("tentativas_triagem")))
            modelo.modo = "lixo"
            sb.coletar(cfg)
            sb.coletar(cfg)
            c = por_id(cfg)
            checar("resposta sem JSON conta tentativa; com o teto, para de chamar",
                   modelo.chamadas == [["5", "6"], ["5"]] and c["5"]["tentativas_triagem"] == 2, modelo.chamadas)
            checar("triagem só conta chamada no estado quando o modelo respondeu", (sb.ler_estado(cfg).get("triagem") or {}).get("chamadas") == 3,
                   sb.ler_estado(cfg).get("triagem"))

            # 4) o líder trata um item durante a chamada: a resposta do modelo não sobrescreve
            modelo.chamadas.clear()
            modelo.modo = "ok"
            sb.gravar_caixa(cfg, [item("7"), item("8")])
            modelo.antes = lambda: sb.tratar(cfg, "7", "ignorada", "falso positivo")
            n = sb.triar(cfg)
            modelo.antes = None
            c = por_id(cfg)
            checar("item tratado no meio não é sobrescrito", c["7"]["situacao"] == "ignorada" and c["7"]["acao_sugerida"] == ""
                   and c["7"]["nota"] == "falso positivo", c["7"])
            # triar devolve len(aplicadas), que conta também o item tratado no meio (2 aqui): só o estado é conferido
            checar("o outro item é triado normalmente", n >= 1 and c["8"]["situacao"] == "triada" and c["8"]["acao_sugerida"] == "corrigir")

            # 5) sem o executável do claude: não chama e não gasta tentativa
            sb._achar_claude = lambda: None
            sb.gravar_caixa(cfg, [item("9")])
            checar("sem claude: triar devolve 0 e não conta tentativa", sb.triar(cfg) == 0
                   and "tentativas_triagem" not in por_id(cfg)["9"])
            sb._achar_claude = lambda: "claude-falso"

            # 6) itens_max: só os primeiros 30 contam tentativa; o resto fica para a próxima
            modelo.chamadas.clear()
            sb.gravar_caixa(cfg, [item(str(100 + i)) for i in range(35)])
            sb.triar(cfg)
            c = por_id(cfg)
            checar("só os itens enviados ganham tentativa (30 de 35)", len(modelo.chamadas[0]) == sb.MAX_TRIAGEM
                   and sum(1 for x in c.values() if x.get("tentativas_triagem")) == sb.MAX_TRIAGEM)
            sb.coletar(cfg)
            checar("os 5 restantes saem na coleta seguinte", modelo.chamadas[-1] == [str(100 + i) for i in range(30, 35)],
                   modelo.chamadas[-1])
        finally:
            sb.subprocess.run, sb._achar_claude, sb.gh_api, sb.GLOSSARIO = orig
    print(f"\n{len(feitos)} ok, {len(falhas)} falha(s)")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
