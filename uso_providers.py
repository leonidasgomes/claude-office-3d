"""Cotas da conta Codex por API oficial, sem inferência, login ou consumo de resets."""
import json
import math
from pathlib import Path
import threading
import time

from providers_console import selecionar, comando_nativo
from rpc_console import Rpc

RAIZ = Path(__file__).resolve().parent
_trava = threading.Lock()


def normalizar_limites(resposta, agora=None):
    agora = time.time() if agora is None else agora
    if not isinstance(resposta, dict):
        raise ValueError("Formato de limites inválido")
    buckets = resposta.get("rateLimitsByLimitId")
    if not isinstance(buckets, dict):
        antigo = resposta.get("rateLimits")
        buckets = {antigo.get("limitId") or "codex": antigo} if isinstance(antigo, dict) else {}
    limites = []
    for chave, bucket in buckets.items():
        if not isinstance(bucket, dict):
            continue
        janelas = []
        for nome in ("primary", "secondary"):
            janela = bucket.get(nome)
            if not isinstance(janela, dict):
                continue
            pct = janela.get("usedPercent")
            pct = float(pct) if type(pct) in (int, float) and math.isfinite(pct) else None
            duracao, reset = janela.get("windowDurationMins"), janela.get("resetsAt")
            duracao = duracao if type(duracao) is int and duracao > 0 else None
            reset = reset if type(reset) is int and reset > 0 else None
            janelas.append({"nome": "semanal" if duracao == 10080 else nome,
                "usado_pct": pct, "restante_pct": max(0, min(100, 100 - pct)) if pct is not None else None,
                "duracao_min": duracao, "renova_em": reset, "expirado": reset is not None and reset <= agora})
        limites.append({"id": str(chave), "nome": bucket.get("limitName") or str(chave), "janelas": janelas})
    return {"provider": "codex", "fonte": "account/rateLimits/read", "coletado_em": agora,
            "disponivel": bool(limites), "limites": limites}


def coletar_codex(cliente=Rpc):
    _, exe = selecionar("codex")
    with cliente(comando_nativo(exe, "codex") + ["app-server"]) as rpc:
        rpc.chamar("initialize", {"clientInfo": {"name": "office_3d", "title": "Office 3D", "version": "1"}})
        rpc.notificar_servidor("initialized")
        return normalizar_limites(rpc.chamar("account/rateLimits/read", timeout=20))


def limites_codex(forcar=False):
    arquivo = RAIZ / "dados" / "providers" / "limites_codex.json"
    with _trava:
        ultimo = None
        if arquivo.is_file():
            try:
                ultimo = json.loads(arquivo.read_text(encoding="utf-8"))
                idade = time.time() - ultimo["coletado_em"]
                if not forcar and 0 <= idade < 300:
                    return ultimo
            except (ValueError, KeyError, TypeError, OSError):
                ultimo = None
        try:
            dados = coletar_codex()
            arquivo.parent.mkdir(parents=True, exist_ok=True)
            temporario = arquivo.with_suffix(".tmp")
            temporario.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
            temporario.replace(arquivo)
            return dados
        except (ValueError, OSError, RuntimeError, TimeoutError):
            if ultimo:
                return {**ultimo, "desatualizado": True, "erro": "Não foi possível atualizar a cota do Codex"}
            return {"provider": "codex", "disponivel": False, "limites": [],
                    "erro": "Cota indisponível; confira autenticação e compatibilidade do Codex no PC"}
