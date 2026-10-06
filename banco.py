# -*- coding: utf-8 -*-
"""Banco local do escritório (SQLite, dados/xp/escritorio.db): o que precisa persistir e só crescer, sem depender dos
transcritos (o Claude Code apaga os velhos) nem de JSON reescrito por vários processos ao mesmo tempo.

Tabelas:
- custo_sessao(id, usd, ao_vivo, ate, visto): custo de cada sessão do time (custo_time.py); a sessão aberta é estimada
  e atualizada até fechar.
- custo_revisao(chave, pr, commit_, quando, usd): cada revisão do revisor_ia.py (dados/revisor/estado.json).
- custo_diario(dia, janela_usd, acumulado_usd, prs): uma foto por dia, para ver a evolução do custo.

Uso: python banco.py      mostra o acumulado e os últimos dias
"""
import sqlite3
import sys
import time
from pathlib import Path

ARQ = Path(__file__).resolve().parent / "dados" / "xp" / "escritorio.db"
ESQUEMA = """
CREATE TABLE IF NOT EXISTS custo_sessao (id TEXT PRIMARY KEY, usd REAL NOT NULL, ao_vivo INTEGER NOT NULL,
                                         ate TEXT, visto TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS custo_revisao (chave TEXT PRIMARY KEY, pr INTEGER, commit_ TEXT, quando TEXT, usd REAL NOT NULL);
CREATE TABLE IF NOT EXISTS custo_diario (dia TEXT PRIMARY KEY, janela_usd REAL, acumulado_usd REAL, prs INTEGER);
"""


def conectar():
    ARQ.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(ARQ, timeout=30)
    c.execute("PRAGMA journal_mode=WAL")    # o servidor lê enquanto o custo_time.py grava
    c.executescript(ESQUEMA)
    return c


def sessoes_fechadas(c):
    """Ids das sessões já fechadas (custo definitivo): o custo_time.py não precisa relê-las fora da janela."""
    return {r[0] for r in c.execute("SELECT id FROM custo_sessao WHERE ao_vivo = 0")}


def gravar_sessao(c, sid, usd, ao_vivo, ate):
    c.execute("INSERT INTO custo_sessao VALUES (?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET usd=excluded.usd, "
              "ao_vivo=excluded.ao_vivo, ate=excluded.ate, visto=excluded.visto",
              (sid, usd, int(ao_vivo), ate, time.strftime("%Y-%m-%d %H:%M")))


def gravar_revisao(c, pr, commit_, quando, usd):
    c.execute("INSERT OR IGNORE INTO custo_revisao VALUES (?,?,?,?,?)", (f"{pr}:{commit_}:{quando}", pr, commit_, quando, usd))


def acumulado(c):
    """(US$ acumulado das sessões + revisões, primeiro dia visto)."""
    s, desde = c.execute("SELECT COALESCE(SUM(usd),0), MIN(ate) FROM custo_sessao").fetchone()
    r = c.execute("SELECT COALESCE(SUM(usd),0) FROM custo_revisao").fetchone()[0]
    return s + r, (desde or "")[:10]


def gravar_dia(c, janela_usd, acumulado_usd, prs):
    c.execute("INSERT OR REPLACE INTO custo_diario VALUES (?,?,?,?)",
              (time.strftime("%Y-%m-%d"), round(janela_usd, 2), round(acumulado_usd, 2), prs))


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    with conectar() as c:
        usd, desde = acumulado(c)
        print(f"Acumulado desde {desde}: US$ {usd:.2f}")
        for dia, jan, acum, prs in c.execute("SELECT * FROM custo_diario ORDER BY dia DESC LIMIT 14"):
            print(f"  {dia}  janela US$ {jan:8.2f}  acumulado US$ {acum:8.2f}  {prs} PR(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
