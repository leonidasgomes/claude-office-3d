"""Vigia da cota da API do GitHub (somente biblioteca padrão).

O GraphQL do GitHub dá 5000 pontos por hora para a conta inteira (todos os agentes e ferramentas); o REST dá outros 5000.
Este módulo lê `gh api rate_limit` (REST) e a consulta GraphQL `{rateLimit}` (nenhuma das duas é cobrada) a cada 5 min, guarda o histórico
em dados/github_cota.jsonl (uma linha por leitura) e entrega ao servidor o último valor, o texto do rodapé do Kanban/PRs
("GraphQL: 3.200/5.000 (volta 11:25)") e o aviso de cota baixa (restando menos de 20%), que o alertas.py transforma em alerta.
"""
import calendar
import json
import subprocess
import threading
import time
from pathlib import Path

INTERVALO = 300            # s entre leituras
LIMIAR_BAIXA = 0.20        # alerta quando restar menos de 20% do limite
MAX_LINHAS = 2016          # 7 dias de leituras de 5 em 5 min
RECURSOS = ("graphql", "core")
ROTULOS = {"graphql": "GraphQL", "core": "REST"}


def milhar(n):
    return f"{int(n):,}".replace(",", ".")


def hora(epoch):
    return time.strftime("%H:%M", time.localtime(epoch))


def normalizar(bruto):
    """{"graphql": {limit, remaining, used, reset}, "core": {...}} a partir do JSON do rate_limit; None se não serve."""
    try:
        recursos = bruto["resources"]
        saida = {}
        for k in RECURSOS:
            r = recursos[k]
            limite, restante = int(r["limit"]), int(r["remaining"])
            saida[k] = {"limit": limite, "remaining": restante, "used": int(r.get("used", limite - restante)), "reset": int(r["reset"])}
        return saida
    except (KeyError, TypeError, ValueError):
        return None


CONSULTA_GQL = "{rateLimit{limit remaining used resetAt}}"


def normalizar_gql(bruto):
    """{"limit", "remaining", "used", "reset"} do GraphQL `rateLimit` (resetAt ISO em UTC); None se não serve."""
    try:
        r = bruto["data"]["rateLimit"]
        reset = calendar.timegm(time.strptime(r["resetAt"], "%Y-%m-%dT%H:%M:%SZ"))
        return {"limit": int(r["limit"]), "remaining": int(r["remaining"]), "used": int(r["used"]), "reset": reset}
    except (KeyError, TypeError, ValueError):
        return None


def _gh_json(gh, args, timeout):
    try:
        r = subprocess.run([gh, *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        return json.loads(r.stdout) if r.stdout.strip() else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def ler(gh, timeout=20):
    """Lê a cota. REST: `gh api rate_limit` (não conta em nenhuma cota). GraphQL: a consulta `{rateLimit{...}}`, que o GitHub NÃO
    cobra (testado: o "remaining" não anda) e que é a leitura exata; o `rate_limit` REST chegou a devolver a janela GraphQL
    ANTERIOR (valores velhos), então ele só vale para o GraphQL quando a consulta falha. None se nada respondeu."""
    rest = normalizar(_gh_json(gh, ["api", "rate_limit"], timeout))
    gql = normalizar_gql(_gh_json(gh, ["api", "graphql", "-f", f"query={CONSULTA_GQL}"], timeout))
    if gql:
        rest = rest or {"core": {"limit": 5000, "remaining": 5000, "used": 0, "reset": gql["reset"]}}
        rest["graphql"] = gql
    return rest


def baixa(rec, limiar=LIMIAR_BAIXA):
    """True se algum recurso tem menos de `limiar` do limite restante (e a janela ainda não virou)."""
    agora = time.time()
    return any(r["reset"] > agora and r["remaining"] < limiar * r["limit"] for r in (rec or {}).values())


def texto(rec):
    """Rodapé: "GraphQL: 3.200/5.000 (volta 11:25)" (pontos usados na hora / limite). Inclui o REST só quando está baixo."""
    if not rec:
        return ""
    g = rec["graphql"]
    partes = [f"{ROTULOS['graphql']}: {milhar(g['used'])}/{milhar(g['limit'])} (volta {hora(g['reset'])})"]
    c = rec["core"]
    if c["remaining"] < LIMIAR_BAIXA * c["limit"]:
        partes.append(f"{ROTULOS['core']}: {milhar(c['used'])}/{milhar(c['limit'])} (volta {hora(c['reset'])})")
    return " · ".join(partes)


def ritmo_hora(historico, recurso="graphql", janela=3600):
    """Pontos gastos por hora, pelas leituras da última `janela` s dentro da mesma janela de reset (None sem dados)."""
    if not historico:
        return None
    ultimo = historico[-1]
    mesmas = [h for h in historico if h["t"] >= ultimo["t"] - janela and h[recurso]["reset"] == ultimo[recurso]["reset"]]
    if len(mesmas) < 2 or mesmas[-1]["t"] == mesmas[0]["t"]:
        return None
    gasto = mesmas[-1][recurso]["used"] - mesmas[0][recurso]["used"]
    return round(max(0, gasto) * 3600 / (mesmas[-1]["t"] - mesmas[0]["t"]))


class Vigia:
    """Thread barata: uma consulta REST de `rate_limit` a cada `intervalo` s. `ultimo()` não faz E/S."""

    def __init__(self, pasta_dados, gh, intervalo=INTERVALO, leitor=None):
        self.arq = Path(pasta_dados) / "github_cota.jsonl"
        self.gh, self.intervalo = gh, intervalo
        self.leitor = leitor or (lambda: ler(self.gh))
        self._ultimo, self._trava = None, threading.Lock()

    def historico(self, maximo=MAX_LINHAS):
        saida = []
        try:
            for linha in self.arq.read_text(encoding="utf-8").splitlines()[-maximo:]:
                try:
                    x = json.loads(linha)
                except ValueError:
                    continue
                if isinstance(x, dict) and "t" in x and all(k in x for k in RECURSOS):
                    saida.append(x)
        except OSError:
            pass
        return saida

    def _gravar(self, registro):
        try:
            self.arq.parent.mkdir(parents=True, exist_ok=True)
            with open(self.arq, "a", encoding="utf-8") as f:
                f.write(json.dumps(registro, ensure_ascii=False) + "\n")
            if self.arq.stat().st_size > MAX_LINHAS * 400:   # aparo o arquivo de vez em quando
                linhas = self.arq.read_text(encoding="utf-8").splitlines()[-MAX_LINHAS:]
                tmp = self.arq.with_suffix(".tmp")
                tmp.write_text("\n".join(linhas) + "\n", encoding="utf-8")
                tmp.replace(self.arq)
        except OSError:
            pass

    def passo(self, agora=None):
        """Uma leitura: grava no histórico e guarda como último. Devolve o registro (ou None se o gh falhou)."""
        agora = time.time() if agora is None else agora
        rec = self.leitor()
        if not rec:
            return None
        registro = {"t": round(agora, 1), **rec}
        self._gravar(registro)
        with self._trava:
            self._ultimo = registro
        return registro

    def ultimo(self):
        """Último registro lido (dict) ou, se o servidor acabou de subir, o último gravado no arquivo (None se não há)."""
        with self._trava:
            if self._ultimo:
                return self._ultimo
        h = self.historico(2)
        return h[-1] if h else None

    def resumo(self):
        """Para o servidor/rodapé: {"texto", "baixa", "graphql", "core", "ritmo_hora", "t"} (None se nunca leu)."""
        u = self.ultimo()
        if not u:
            return None
        rec = {k: u[k] for k in RECURSOS}
        return {"texto": texto(rec), "baixa": baixa(rec), "graphql": rec["graphql"], "core": rec["core"],
                "ritmo_hora": ritmo_hora(self.historico(100)), "t": u["t"]}

    def laco(self, parar, atraso=3):
        if parar.wait(atraso):
            return
        while not parar.is_set():
            try:
                self.passo()
            except Exception as e:
                print(f"[cota] {str(e)[:120]}", flush=True)
            parar.wait(self.intervalo)

    def iniciar(self):
        parar = threading.Event()
        threading.Thread(target=self.laco, args=(parar,), daemon=True, name="cota").start()
        return parar
