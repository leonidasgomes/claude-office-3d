# -*- coding: utf-8 -*-
"""Banco local do escritório (SQLite, dados/escritorio.db): o que precisa persistir e só crescer, sem depender dos
transcritos (o Claude Code apaga os velhos) nem de JSON reescrito por vários processos ao mesmo tempo.
Na 1.9 ele ficava em dados/xp/escritorio.db: na primeira abertura é movido para cá sozinho.

Tabelas:
- custo_sessao(id, usd, ao_vivo, ate, visto): custo de cada sessão do time (custo_time.py); a sessão aberta é estimada
  e atualizada até fechar.
- custo_revisao(chave, pr, commit_, quando, usd): cada revisão do revisor_ia.py (dados/revisor/estado.json).
- custo_diario(dia, janela_usd, acumulado_usd, prs): uma foto por dia, para ver a evolução do custo.
- evento(id, ts, agente, ferramenta, dados): o feed do escritório (registrar_evento.py, no hook de cada sessão).
  O id é o "desde" do GET /eventos; na migração do dados/eventos.jsonl o id é o número da linha, e o escritório aberto
  não se perde. Antes o servidor relia o arquivo inteiro a cada consulta e o arquivo era separado aos 4 MB.
- decisao_xp(pr, tipo, quando, origem, motivo): "conferido" (amarelo) e "liberado" (vermelho) do Placar, com quem
  decidiu (botão do escritório, auditor_xp, linha de comando) e por quê. Antes: dados/xp/conferidos.json e
  dados/xp/auditorias_resolvidas.json, só a lista de números.
- auditoria_ia(pr, ...): o veredito do auditor_xp.py para cada amarelo (antes dados/xp/auditoria_ia.json).
- uso_plano(ts, five_pct, five_reset, seven_pct, seven_reset): limites do plano (janela de 5 h e semanal) que o Claude
  Code passa à statusline em `rate_limits` (statusline_uso.py); uma linha por mudança, no máximo uma por minuto.
- meta(chave, valor): marcas de migração.
As migrações dos arquivos antigos são automáticas e acontecem uma vez; os originais ficam como *.migrado.json(l).

Uso: python banco.py      mostra o acumulado e os últimos dias
"""
import json
import sqlite3
import sys
import time
from pathlib import Path

DADOS = Path(__file__).resolve().parent / "dados"
ARQ = DADOS / "escritorio.db"
ARQ_ANTIGO = DADOS / "xp" / "escritorio.db"       # onde a 1.9 o criou: movido para ARQ na primeira abertura
EVENTOS_JSONL = DADOS / "eventos.jsonl"           # formato antigo: migrado uma vez para a tabela evento
XP_JSON = {"conferido": DADOS / "xp" / "conferidos.json", "liberado": DADOS / "xp" / "auditorias_resolvidas.json"}
AUDITORIA_JSON = DADOS / "xp" / "auditoria_ia.json"
ESQUEMA = """
CREATE TABLE IF NOT EXISTS custo_sessao (id TEXT PRIMARY KEY, usd REAL NOT NULL, ao_vivo INTEGER NOT NULL,
                                         ate TEXT, visto TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS custo_revisao (chave TEXT PRIMARY KEY, pr INTEGER, commit_ TEXT, quando TEXT, usd REAL NOT NULL);
CREATE TABLE IF NOT EXISTS custo_diario (dia TEXT PRIMARY KEY, janela_usd REAL, acumulado_usd REAL, prs INTEGER);
CREATE TABLE IF NOT EXISTS evento (id INTEGER PRIMARY KEY, ts TEXT, agente TEXT, ferramenta TEXT, dados TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS evento_ferramenta ON evento (ferramenta);
CREATE INDEX IF NOT EXISTS evento_ts ON evento (ts);
CREATE TABLE IF NOT EXISTS meta (chave TEXT PRIMARY KEY, valor TEXT);
CREATE TABLE IF NOT EXISTS uso_plano (ts INTEGER PRIMARY KEY, five_pct REAL, five_reset INTEGER, seven_pct REAL,
                                      seven_reset INTEGER);
CREATE TABLE IF NOT EXISTS decisao_xp (pr INTEGER NOT NULL, tipo TEXT NOT NULL, quando TEXT, origem TEXT, motivo TEXT,
                                       PRIMARY KEY (pr, tipo));
CREATE TABLE IF NOT EXISTS auditoria_ia (pr INTEGER PRIMARY KEY, agente TEXT, alerta TEXT, veredito TEXT, motivo TEXT,
                                         evidencia TEXT, modelo TEXT, cartao INTEGER, custo_usd REAL, quando TEXT);
"""


def _arquivo():
    """Caminho do banco. Uma vez: dados/xp/escritorio.db (1.9) vira dados/escritorio.db; antes de mover, um checkpoint
    passa o -wal para o arquivo principal e os -wal/-shm que sobrarem vão junto. Se não der para mover agora (outro
    processo com o antigo aberto, como um escritório da versão anterior ainda rodando), usa o antigo e tenta depois."""
    if ARQ.exists() or not ARQ_ANTIGO.exists():
        return ARQ
    try:
        c = sqlite3.connect(ARQ_ANTIGO, timeout=5)
        try:
            ocupado = c.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0]
        finally:
            c.close()
        if ocupado:                 # alguém ainda usa o antigo: fica nele por enquanto
            return ARQ_ANTIGO
        ARQ_ANTIGO.rename(ARQ)      # rename (não replace): se outro processo já criou o novo, não sobrescreve
    except (OSError, sqlite3.Error):
        return ARQ if ARQ.exists() else ARQ_ANTIGO
    for suf in ("-wal", "-shm"):
        velho, novo = Path(str(ARQ_ANTIGO) + suf), Path(str(ARQ) + suf)
        try:
            if velho.exists():
                velho.unlink() if novo.exists() else velho.rename(novo)
        except OSError:
            pass
    return ARQ


def conectar(timeout=30):
    ARQ.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(_arquivo(), timeout=timeout)
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


# ---- eventos do escritório ---------------------------------------------------------------------------------------
def _migrar_eventos(c):
    """Uma vez: copia o dados/eventos.jsonl para a tabela (id = número da linha) e o renomeia para
    eventos.migrado.jsonl. BEGIN IMMEDIATE: dois hooks ao mesmo tempo não migram duas vezes."""
    if c.execute("SELECT 1 FROM meta WHERE chave = 'eventos_migrados'").fetchone():
        return
    c.execute("BEGIN IMMEDIATE")
    try:
        if not c.execute("SELECT 1 FROM meta WHERE chave = 'eventos_migrados'").fetchone():
            n = 0
            if EVENTOS_JSONL.exists():
                with EVENTOS_JSONL.open("rb") as f:
                    for bruto in f:
                        texto = bruto.decode("utf-8", errors="replace").strip()
                        if not texto:
                            continue
                        n += 1   # a linha conta mesmo se estiver quebrada, como contava o servidor antigo
                        try:
                            obj = json.loads(texto)
                        except ValueError:
                            obj = {}
                        obj = obj if isinstance(obj, dict) else {}
                        c.execute("INSERT INTO evento VALUES (?,?,?,?,?)",
                                  (n, obj.get("ts"), obj.get("agente"), obj.get("ferramenta"),
                                   json.dumps(obj, ensure_ascii=False)))
            c.execute("INSERT INTO meta VALUES ('eventos_migrados', ?)",
                      (f"{n} linhas em {time.strftime('%Y-%m-%d %H:%M')}",))
        c.execute("COMMIT")
    except BaseException:
        c.execute("ROLLBACK")
        raise
    if EVENTOS_JSONL.exists():
        try:
            EVENTOS_JSONL.replace(EVENTOS_JSONL.with_name("eventos.migrado.jsonl"))
        except OSError:
            pass


def gravar_evento(obj):
    """Hook de cada ferramenta de cada sessão: precisa ser rápido; timeout curto (quem chama trata a falha)."""
    c = conectar(timeout=5)
    try:
        _migrar_eventos(c)
        with c:
            c.execute("INSERT INTO evento (ts, agente, ferramenta, dados) VALUES (?,?,?,?)",
                      (obj.get("ts"), obj.get("agente"), obj.get("ferramenta"), json.dumps(obj, ensure_ascii=False)))
    finally:
        c.close()


def ler_eventos(desde=0, ultimos=0, maximo=500):
    """(total, eventos) como o GET /eventos sempre devolveu: total = último id; com `ultimos`, os k mais recentes;
    senão os depois de `desde` (no máximo `maximo`, os mais novos, se o cliente ficou muito para trás)."""
    c = conectar()
    try:
        _migrar_eventos(c)
        total = c.execute("SELECT COALESCE(MAX(id), 0) FROM evento").fetchone()[0]
        if ultimos > 0:
            linhas = c.execute("SELECT dados FROM evento ORDER BY id DESC LIMIT ?", (ultimos,)).fetchall()
        else:
            linhas = c.execute("SELECT dados FROM evento WHERE id > ? ORDER BY id DESC LIMIT ?", (desde, maximo)).fetchall()
    finally:
        c.close()
    out = []
    for (dados,) in reversed(linhas):
        try:
            obj = json.loads(dados)
        except ValueError:
            continue
        if isinstance(obj, dict) and obj:
            out.append(obj)
    return total, out


def eventos_periodo(de, ate, apos=0, maximo=5000):
    """Eventos com `de` <= ts < `ate` (texto ISO local, como o hook grava: "2026-10-07T14:30:00"), em ordem de id, a partir
    do id seguinte a `apos` (paginação), no máximo `maximo`. Devolve (eventos, proximo): `proximo` = id do último evento
    devolvido quando há mais na página seguinte (o cliente repete com apos=proximo), senão None. Cada evento leva "id"."""
    c = conectar()
    try:
        _migrar_eventos(c)
        linhas = c.execute("SELECT id, dados FROM evento WHERE ts >= ? AND ts < ? AND id > ? ORDER BY id LIMIT ?",
                           (de, ate, int(apos), int(maximo) + 1)).fetchall()
    finally:
        c.close()
    mais = len(linhas) > maximo
    linhas = linhas[:maximo]
    out = []
    for i, dados in linhas:
        try:
            obj = json.loads(dados)
        except ValueError:
            continue
        if isinstance(obj, dict) and obj:
            obj["id"] = i
            out.append(obj)
    return out, (linhas[-1][0] if mais and linhas else None)


def eventos_da_ferramenta(ferramenta):
    """Todos os eventos de uma ferramenta (ex.: "Skill" para o uso das skills), em ordem."""
    c = conectar()
    try:
        _migrar_eventos(c)
        linhas = c.execute("SELECT dados FROM evento WHERE ferramenta = ? ORDER BY id", (ferramenta,)).fetchall()
    finally:
        c.close()
    for (dados,) in linhas:
        try:
            yield json.loads(dados)
        except ValueError:
            continue


# ---- decisões do XP e auditoria do bot ----------------------------------------------------------------------------
COLUNAS_AUDITORIA = ("agente", "alerta", "veredito", "motivo", "evidencia", "modelo", "cartao", "custo_usd", "quando")


def _migrar_xp(c):
    """Uma vez: as listas JSON antigas viram linhas (origem "migrado"); os arquivos ficam como *.migrado.json.
    BEGIN IMMEDIATE: o servidor e o xp.py ao mesmo tempo não migram duas vezes."""
    if c.execute("SELECT 1 FROM meta WHERE chave = 'xp_migrado'").fetchone():
        return
    c.execute("BEGIN IMMEDIATE")
    try:
        if not c.execute("SELECT 1 FROM meta WHERE chave = 'xp_migrado'").fetchone():
            for tipo, arq in XP_JSON.items():
                try:
                    lista = json.loads(arq.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    lista = []
                for pr in lista if isinstance(lista, list) else []:
                    try:
                        c.execute("INSERT OR IGNORE INTO decisao_xp VALUES (?,?,?,?,?)",
                                  (int(pr), tipo, None, "migrado", None))
                    except (TypeError, ValueError):
                        continue
            try:
                aud = json.loads(AUDITORIA_JSON.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                aud = {}
            for pr, d in (aud if isinstance(aud, dict) else {}).items():
                if not isinstance(d, dict) or not str(pr).isdigit():
                    continue
                c.execute(f"INSERT OR IGNORE INTO auditoria_ia VALUES (?{',?' * len(COLUNAS_AUDITORIA)})",
                          (int(pr), *[d.get(k) for k in COLUNAS_AUDITORIA]))
            c.execute("INSERT INTO meta VALUES ('xp_migrado', ?)", (time.strftime("%Y-%m-%d %H:%M"),))
        c.execute("COMMIT")
    except BaseException:
        c.execute("ROLLBACK")
        raise
    for arq in (*XP_JSON.values(), AUDITORIA_JSON):
        if arq.exists():
            try:
                arq.replace(arq.with_suffix(".migrado.json"))
            except OSError:
                pass


def decisoes(tipo):
    """PRs com a decisão `tipo` ("conferido" ou "liberado")."""
    c = conectar()
    try:
        _migrar_xp(c)
        return {r[0] for r in c.execute("SELECT pr FROM decisao_xp WHERE tipo = ?", (tipo,))}
    finally:
        c.close()


def decidir(pr, tipo, origem="", motivo=""):
    """Grava (ou regrava) a decisão `tipo` do PR, com quem decidiu e por quê."""
    c = conectar()
    try:
        _migrar_xp(c)
        with c:
            c.execute("INSERT OR REPLACE INTO decisao_xp VALUES (?,?,?,?,?)",
                      (pr, tipo, time.strftime("%Y-%m-%d %H:%M"), origem or None, (motivo or "")[:300] or None))
    finally:
        c.close()


def desfazer(pr):
    """Apaga as decisões do PR (conferido e liberado): ele volta a ser auditado/conferido."""
    c = conectar()
    try:
        _migrar_xp(c)
        with c:
            c.execute("DELETE FROM decisao_xp WHERE pr = ?", (pr,))
    finally:
        c.close()


def auditados():
    """PRs que o auditor_xp.py já auditou."""
    c = conectar()
    try:
        _migrar_xp(c)
        return {r[0] for r in c.execute("SELECT pr FROM auditoria_ia")}
    finally:
        c.close()


def gravar_auditoria(pr, d):
    c = conectar()
    try:
        _migrar_xp(c)
        with c:
            c.execute(f"INSERT OR REPLACE INTO auditoria_ia VALUES (?{',?' * len(COLUNAS_AUDITORIA)})",
                      (pr, *[d.get(k) for k in COLUNAS_AUDITORIA]))
    finally:
        c.close()


# ---- uso do plano (rate_limits da statusline) ----------------------------------------------------------------------
def gravar_uso(five_pct, five_reset, seven_pct, seven_reset, agora=None):
    """Grava uma leitura; ignora se nada mudou ou se a última tem menos de 60 s (a statusline roda a cada mensagem)."""
    agora = int(agora or time.time())
    c = conectar(timeout=3)
    try:
        u = c.execute("SELECT ts, five_pct, five_reset, seven_pct, seven_reset FROM uso_plano ORDER BY ts DESC LIMIT 1").fetchone()
        if u and (agora - u[0] < 60 or tuple(u[1:]) == (five_pct, five_reset, seven_pct, seven_reset)):
            return False
        with c:
            c.execute("INSERT OR REPLACE INTO uso_plano VALUES (?,?,?,?,?)", (agora, five_pct, five_reset, seven_pct, seven_reset))
        return True
    finally:
        c.close()


def _consumo_por_dia(linhas):
    """{dia: pontos percentuais do semanal gastos naquele dia}: soma das subidas entre leituras; queda = reset (ignora)."""
    por_dia, ant = {}, None
    for ts, _, _, pct, _ in linhas:
        if pct is None:
            continue
        if ant is not None and pct >= ant:
            dia = time.strftime("%Y-%m-%d", time.localtime(ts))
            por_dia[dia] = por_dia.get(dia, 0.0) + (pct - ant)
        ant = pct
    return por_dia


def uso_resumo(agora=None):
    """Para o Placar: última leitura (5 h e semana), consumo do semanal por dia (8 dias) e projeção até o reset.
    None se a statusline ainda não gravou nada."""
    agora = int(agora or time.time())
    c = conectar()
    try:
        linhas = c.execute("SELECT ts, five_pct, five_reset, seven_pct, seven_reset FROM uso_plano WHERE ts >= ? ORDER BY ts",
                           (agora - 8 * 86400,)).fetchall()
    finally:
        c.close()
    if not linhas:
        return None
    ts, five, five_r, seven, seven_r = linhas[-1]
    if five_r and five_r < agora:
        five = None                     # a janela de 5 h já reiniciou desde a última leitura
    if seven_r and seven_r < agora:
        seven = None
    por_dia = _consumo_por_dia(linhas)
    # ritmo: pontos do semanal nas últimas 24 h (sem reset no meio) -> projeção no momento do reset
    dia = [l for l in linhas if l[0] >= agora - 86400 and l[3] is not None]
    ritmo = None
    if seven is not None and len(dia) >= 2 and dia[-1][3] >= dia[0][3] and dia[-1][0] > dia[0][0]:
        ritmo = (dia[-1][3] - dia[0][3]) / ((dia[-1][0] - dia[0][0]) / 86400)
    projecao = None
    if ritmo is not None and seven_r:
        projecao = round(seven + ritmo * max(0, seven_r - agora) / 86400, 1)
    return {"lido_em": ts, "five_pct": five, "five_reset": five_r, "seven_pct": seven, "seven_reset": seven_r,
            "ritmo_dia": round(ritmo, 1) if ritmo is not None else None, "projecao_reset": projecao,
            "por_dia": [{"dia": d, "pontos": round(v, 1)} for d, v in sorted(por_dia.items())[-8:]]}


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
