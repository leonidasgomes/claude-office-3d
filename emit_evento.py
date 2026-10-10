# -*- coding: utf-8 -*-
"""Porta de entrada neutra do escritório 3D: grava UM evento de qualquer harness (OpenCode, Claude Code, manual).

O esquema do evento é o mesmo que o `office one/registrar_evento.py` grava (seção 4.1 do SDD): o servidor, a cena e os
painéis não sabem qual harness emitiu. A origem vai em `fonte` (ex.: `opencode`, `claude`, `manual`).

Uso: python emit_evento.py --evento '{"tipo": "trabalho", "agente": "Dev", "ferramenta": "bash", "resumo": "roda pytest"}'
     echo {...} | python emit_evento.py
Nunca bloqueia o agente: banco ocupado/quebrado cai em `eventos.falha.jsonl` (código 0); só entrada inválida sai com 2.
"""
import argparse
import json
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))  # banco.py fica nesta pasta
import banco  # noqa: E402

TIPOS = ("trabalho", "fala", "reuniao", "subagente", "ocioso")
FONTE_VALIDA = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}\Z")
MAX_RESUMO = 90      # mesmos tetos do registrar_evento.py
MAX_TEXTO = 2000
MAX_DETALHE = 400


def _curto(texto, limite):
    return " ".join(str(texto).split())[:limite]


def normalizar(ev):
    """Valida o evento neutro e devolve a cópia normalizada (só chaves conhecidas). Erro: ValueError com o motivo."""
    if not isinstance(ev, dict):
        raise ValueError("o evento precisa ser um objeto JSON")
    tipo = ev.get("tipo")
    if tipo not in TIPOS:
        raise ValueError(f"tipo precisa ser um de {', '.join(TIPOS)}")
    agente = str(ev.get("agente") or "").strip()
    if not agente:
        raise ValueError("agente é obrigatório")
    if len(agente) > 64:
        raise ValueError("agente com mais de 64 caracteres")
    fonte = str(ev.get("fonte") or "manual").strip().lower()
    if not FONTE_VALIDA.fullmatch(fonte):
        raise ValueError("fonte usa só minúsculas, números, - e _ (até 32)")
    ts = ev.get("ts") or datetime.now().isoformat(timespec="seconds")
    out = {"ts": str(ts), "agente": agente, "fonte": fonte, "tipo": tipo,
           "para": [str(a) for a in ev.get("para") or [] if str(a)],
           "ferramenta": str(ev.get("ferramenta") or "")[:64],
           "resumo": _curto(ev.get("resumo") or ev.get("ferramenta") or tipo, MAX_RESUMO)}
    if ev.get("texto") is not None:
        out["texto"] = str(ev.get("texto"))[:MAX_TEXTO]
    if ev.get("detalhe") is not None:
        out["detalhe"] = str(ev.get("detalhe"))[:MAX_DETALHE]
    if "ok" in ev:
        if not isinstance(ev["ok"], bool):
            raise ValueError("ok precisa ser true ou false")
        out["ok"] = ev["ok"]
    if "codigo" in ev:
        try:
            out["codigo"] = int(ev["codigo"])
        except (TypeError, ValueError):
            raise ValueError("codigo precisa ser número") from None
    if ev.get("erro") is not None:
        out["erro"] = _curto(ev.get("erro"), 120)
    if "inicio" in ev:
        out["inicio"] = bool(ev["inicio"])
    if "espera_s" in ev:
        try:
            out["espera_s"] = max(1, min(int(ev["espera_s"]), 600))
        except (TypeError, ValueError):
            raise ValueError("espera_s precisa ser número") from None
    for chave in ("funcao", "modelo", "sessao", "sessao_pai", "agente_pai", "sessao_filho"):
        if ev.get(chave) is not None:
            out[chave] = str(ev[chave])[:128]
    return out


def gravar(obj, banco_arq=None):
    """Grava no SQLite (o padrão é o do escritório); banco ocupado/quebrado: fila em eventos.falha.jsonl. Devolve o id ou None."""
    arq = Path(banco_arq) if banco_arq else banco.ARQ
    falha = arq.parent / "eventos.falha.jsonl"
    try:
        arq.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(arq, timeout=5)
        try:
            c.execute("PRAGMA journal_mode=WAL")
            c.executescript(banco.ESQUEMA)
            banco._migrar_eventos(c)
            with c:
                cur = c.execute("INSERT INTO evento (ts, agente, ferramenta, dados) VALUES (?,?,?,?)",
                                (obj.get("ts"), obj.get("agente"), obj.get("ferramenta"),
                                 json.dumps(obj, ensure_ascii=False)))
                return cur.lastrowid
        finally:
            c.close()
    except Exception:
        try:
            with falha.open("a", encoding="utf-8") as f:
                f.write(json.dumps(obj, ensure_ascii=False) + "\n")
        except OSError:
            pass
        return None


def main(argv=None):
    parser = argparse.ArgumentParser(description="Grava um evento neutro no escritório 3D")
    parser.add_argument("--evento", help="o evento em JSON (sem ele, lê o stdin)")
    parser.add_argument("--banco", help="arquivo SQLite (padrão: o do escritório; testes usam um temporário)")
    args = parser.parse_args(argv)
    try:
        bruto = args.evento if args.evento is not None else sys.stdin.buffer.read().decode("utf-8", "replace")
        if not (bruto or "").strip():
            print("Erro: informe --evento ou o JSON no stdin", file=sys.stderr)
            return 2
        obj = normalizar(json.loads(bruto))
    except ValueError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 2
    gravar(obj, args.banco)
    return 0


if __name__ == "__main__":
    sys.exit(main())
