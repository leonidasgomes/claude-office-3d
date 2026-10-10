# -*- coding: utf-8 -*-
"""Testes do emit_evento.py (porta neutra do escritório): validação, padrões, tetos e gravação, num banco temporário.

Nunca toca no banco real: tudo passa por --banco apontando para uma pasta temporária.
Uso: python -W error ferramentas/testar_emit_evento.py
"""
import json
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
import emit_evento as ee  # noqa: E402

FALHAS = []


def checar(nome, condicao, detalhe=""):
    print(f"  {'ok' if condicao else 'FALHOU'}: {nome}")
    if not condicao:
        FALHAS.append(f"{nome} {detalhe}")


def linhas(banco):
    c = sqlite3.connect(banco)
    try:
        return [json.loads(d) for (d,) in c.execute("SELECT dados FROM evento ORDER BY id")]
    finally:
        c.close()


def rodar(*args, banco, entrada=None):
    return subprocess.run([sys.executable, str(RAIZ / "emit_evento.py"), "--banco", str(banco), *args],
                          input=entrada, capture_output=True, text=True, timeout=60)


def main():
    tmp = Path(tempfile.mkdtemp(prefix="emit-teste-"))
    banco = tmp / "escritorio.db"

    ev = ee.normalizar({"tipo": "trabalho", "agente": "Dev", "fonte": "opencode",
                        "ferramenta": "bash", "resumo": "roda pytest", "detalhe": "command: pytest -q"})
    checar("normaliza válido com fonte", ev["fonte"] == "opencode" and ev["tipo"] == "trabalho")

    ev = ee.normalizar({"tipo": "ocioso", "agente": "Lider"})
    checar("padrões (fonte manual, ts de agora)", ev["fonte"] == "manual" and len(ev["ts"]) >= 19)

    ev = ee.normalizar({"tipo": "fala", "agente": "Dev", "resumo": "x" * 200, "texto": "y" * 3000})
    checar("tetos (resumo 90, texto 2000)", len(ev["resumo"]) <= 90 and len(ev["texto"]) <= 2000)

    for ruim, motivo in [({"agente": "Dev"}, "sem tipo"), ({"tipo": "dança", "agente": "Dev"}, "tipo fora"),
                         ({"tipo": "trabalho"}, "sem agente"), ({"tipo": "trabalho", "agente": "Dev", "fonte": "O P E N"}, "fonte fora"),
                         ({"tipo": "trabalho", "agente": "Dev", "ok": "sim"}, "ok texto")]:
        try:
            ee.normalizar(ruim)
            checar(f"rejeita ({motivo})", False, ruim)
        except ValueError:
            checar(f"rejeita ({motivo})", True)

    r = rodar("--evento", json.dumps({"tipo": "trabalho", "agente": "Dev", "fonte": "opencode",
                                      "ferramenta": "bash", "resumo": "roda pytest"}), banco=banco)
    checar("--evento grava e sai 0 sem saída", r.returncode == 0 and r.stdout == "" and r.stderr == "", (r.returncode, r.stdout, r.stderr))
    rows = linhas(banco)
    checar("linha legível com fonte", len(rows) == 1 and rows[0]["fonte"] == "opencode" and rows[0]["resumo"] == "roda pytest", rows)

    r = rodar(banco=banco, entrada=json.dumps({"tipo": "ocioso", "agente": "Lider"}))
    checar("stdin grava", r.returncode == 0 and len(linhas(banco)) == 2, (r.returncode, r.stderr))

    antes = len(linhas(banco))
    r = rodar("--evento", json.dumps({"tipo": "trabalho"}), banco=banco)
    checar("inválido sai 2 com motivo e nada grava", r.returncode == 2 and "agente" in r.stderr and len(linhas(banco)) == antes,
           (r.returncode, r.stderr))

    r = rodar("--evento", "não é json{", banco=banco)
    checar("json quebrado sai 2", r.returncode == 2, (r.returncode, r.stderr))

    r = rodar(banco=banco, entrada="")
    checar("stdin vazio sai 2", r.returncode == 2, (r.returncode, r.stderr))

    ruim = tmp / "pasta"  # --banco apontando para um diretório: o sqlite não abre, cai na fila
    ruim.mkdir()
    r = rodar("--evento", json.dumps({"tipo": "trabalho", "agente": "Dev"}), banco=ruim)
    fila = tmp / "eventos.falha.jsonl"  # irmã do arquivo de banco, como no escritório real
    checar("banco quebrado fila e sai 0", r.returncode == 0 and fila.exists()
           and json.loads(fila.read_text(encoding="utf-8").splitlines()[0])["agente"] == "Dev",
           (r.returncode, r.stderr))

    print("OK" if not FALHAS else f"{len(FALHAS)} FALHA(S): {FALHAS}")
    return 1 if FALHAS else 0


if __name__ == "__main__":
    sys.exit(main())
