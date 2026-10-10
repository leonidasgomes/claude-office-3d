"""Teste do filtro por tempo do GET /eventos (replay do dia): banco.eventos_periodo e servidor.eventos_periodo.

Uso: python -W error ferramentas/testar_eventos.py
Usa um banco temporário (banco.ARQ e banco.EVENTOS_JSONL apontam para uma pasta temporária); não sobe servidor nem toca em
dados/escritorio.db.
"""
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
import banco  # noqa: E402
import servidor  # noqa: E402

feitos, falhas = [], []


def checar(nome, cond, info=""):
    if cond:
        feitos.append(nome)
        print("  ok:", nome)
    else:
        falhas.append(nome)
        print("  FALHOU:", nome, info)


def qs(**k):
    return {chave: [str(v)] for chave, v in k.items()}


def extras():
    """Casos de borda: ts fora de ordem de id, dados quebrados, limites de apos e datas, concorrência com o hook gravando,
    e a rota HTTP de verdade (servidor em thread, porta livre, pasta temporária) no modo novo e no antigo."""
    import http.client
    import json
    import sqlite3
    import threading
    from functools import partial
    from http.server import ThreadingHTTPServer
    import rede
    guardar = banco.ARQ, banco.EVENTOS_JSONL, servidor.MAX_PERIODO, servidor.Handler.rede
    with tempfile.TemporaryDirectory() as tmp:
        banco.ARQ = Path(tmp) / "escritorio.db"
        banco.EVENTOS_JSONL = Path(tmp) / "eventos.jsonl"
        srv = None
        try:
            print("extras: ts fora da ordem do id")
            # hooks concorrentes gravam fora de ordem: id crescente, ts indo e voltando (dentro e fora do período)
            tss = ["2026-10-07T10:00:05", "2026-10-07T09:59:59", "2026-10-06T23:59:59", "2026-10-07T10:00:01",
                   "2026-10-08T00:00:00", "2026-10-07T00:00:00", "2026-10-07T23:59:59", "2026-10-07T10:00:00"]
            for k, ts in enumerate(tss):
                banco.gravar_evento({"ts": ts, "agente": "A", "tipo": "trabalho", "resumo": f"e{k}"})
            dentro = [f"e{k}" for k, ts in enumerate(tss) if "2026-10-07" <= ts < "2026-10-08"]
            for maximo in (1, 2, 3, 100):
                vistos, apos, voltas = [], 0, 0
                while voltas < 50:
                    ev, prox = banco.eventos_periodo("2026-10-07", "2026-10-08", apos, maximo)
                    vistos += [e["resumo"] for e in ev]
                    voltas += 1
                    if prox is None:
                        break
                    apos = prox
                checar(f"ts fora de ordem, página de {maximo}: todos, sem repetir, em ordem de id", vistos == dentro, vistos)
            c = sqlite3.connect(banco.ARQ)
            with c:   # linha com JSON quebrado e linha com JSON não-objeto no período (o id ainda avança a paginação)
                c.execute("INSERT INTO evento (ts, agente, ferramenta, dados) VALUES ('2026-10-07T12:00:00','B',NULL,'{quebrado')")
                c.execute("INSERT INTO evento (ts, agente, ferramenta, dados) VALUES ('2026-10-07T12:00:01','B',NULL,'[1,2]')")
            c.close()
            banco.gravar_evento({"ts": "2026-10-07T12:00:02", "agente": "C", "tipo": "trabalho", "resumo": "depois"})
            vistos, apos = [], 0
            for _ in range(20):
                ev, prox = banco.eventos_periodo("2026-10-07", "2026-10-08", apos, 1)
                vistos += [e["resumo"] for e in ev]
                if prox is None:
                    break
                apos = prox
            checar("linha quebrada no período: pulada, a paginação não para nem repete", vistos == dentro + ["depois"], vistos)

            print("extras: limites dos parâmetros")
            c_, d = servidor.eventos_periodo(qs(de="2026-10-07T10:00", ate="2026-10-07T10:00:01"))
            checar("de com minutos inclui :00 (de inclusivo), ate com segundos exclusivo",
                   c_ == 200 and [e["resumo"] for e in d["eventos"]] == ["e7"], d)
            c_, d = servidor.eventos_periodo(qs(de="2026-10-07T10:00", ate="2026-10-07T10:00:00"))
            checar("de=T10:00 e ate=T10:00:00 (o mesmo instante): 200 vazio ou 400, nunca eventos",
                   (c_ == 200 and d["eventos"] == []) or c_ == 400, (c_, d))
            c_, d = servidor.eventos_periodo(qs(de="2026-10-07", ate="2026-10-07T00:00"))
            checar("de=dia e ate=meia-noite do mesmo dia: nada", (c_ == 200 and d["eventos"] == []) or c_ == 400, (c_, d))
            c_, d = servidor.eventos_periodo(qs(de="2026-10-07", apos=str(10 ** 30)))
            checar("apos gigante: 400 (não 503 de OverflowError no sqlite)", c_ == 400, (c_, d))
            c_, d = servidor.eventos_periodo(qs(de="٢٠٢٦-١٠-٠٧",
                                               ate="٢٠٢٦-١٠-٠٨"))
            checar("dígitos não ASCII (\\d do re aceita): 400", c_ == 400, (c_, d))
            c_, d = servidor.eventos_periodo(qs(de="2026-13-45"))
            checar("data impossível (mês 13): 400", c_ == 400, (c_, d))
            c_, d = servidor.eventos_periodo(qs(de="2026-10-07T25:61"))
            checar("hora impossível (25:61): 400", c_ == 400, (c_, d))
            for ruim in ["2026-10-07 10:00", "2026-10-07T10", "2026-10-07T10:00:00Z", "2026-10-07T10:00:00.5", " 2026-10-07x"]:
                c_, d = servidor.eventos_periodo(qs(de=ruim))
                checar(f"formato fora do aceito {ruim!r}: 400", c_ == 400, (c_, d))

            print("extras: concorrência (hook gravando enquanto pagina)")
            parar, erros = threading.Event(), []

            def gravador():
                k = 0
                while not parar.is_set() and k < 400:
                    try:
                        banco.gravar_evento({"ts": "2026-10-07T15:00:%02d" % (k % 60), "agente": "D", "tipo": "trabalho",
                                             "resumo": f"c{k}"})
                    except Exception as e:   # o hook trata a falha; aqui só registra
                        erros.append(repr(e))
                    k += 1
            t = threading.Thread(target=gravador)
            t.start()
            ids, falhou = [], None
            try:
                for _ in range(30):
                    apos = 0
                    for _ in range(500):
                        ev, prox = banco.eventos_periodo("2026-10-07", "2026-10-08", apos, 7)
                        ids += [e["id"] for e in ev]
                        if prox is None:
                            break
                        apos = prox
            except Exception as e:
                falhou = repr(e)
            finally:
                parar.set()
                t.join()
            checar("leitura paginada durante gravações: sem exceção", falhou is None and not erros, (falhou, erros[:3]))
            ev, _ = banco.eventos_periodo("2026-10-07", "2026-10-08", 0, 100000)
            checar("depois das gravações: ids únicos e crescentes", [e["id"] for e in ev] == sorted({e["id"] for e in ev}))

            print("extras: rota HTTP de verdade")
            r = rede.Rede(Path(tmp), False, False)
            servidor.Handler.rede = r
            srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(servidor.Handler, directory=str(tmp)))
            porta = srv.server_address[1]
            threading.Thread(target=srv.serve_forever, daemon=True).start()

            def get(caminho):
                con = http.client.HTTPConnection("127.0.0.1", porta, timeout=10)
                con.request("GET", caminho, headers={"Host": f"127.0.0.1:{porta}"})
                resp = con.getresponse()
                corpo = resp.read()
                con.close()
                try:
                    return resp.status, json.loads(corpo)
                except ValueError:
                    return resp.status, corpo[:200]
            servidor.MAX_PERIODO = 5
            st, d = get("/eventos?de=2026-10-07&ate=2026-10-08")
            checar("HTTP replay: 200, 5 eventos e proximo", st == 200 and len(d["eventos"]) == 5 and d["proximo"] == d["eventos"][-1]["id"],
                   (st, str(d)[:200]))
            junta, apos = [], 0
            for _ in range(500):
                st, d = get("/eventos?de=2026-10-07&ate=2026-10-08" + (f"&apos={apos}" if apos else ""))
                junta += [e["id"] for e in d["eventos"]]
                if not d["proximo"]:
                    break
                apos = d["proximo"]
            total_db = len(banco.eventos_periodo("2026-10-07", "2026-10-08", 0, 100000)[0])
            checar("HTTP replay: paginando com apos chega a todos, sem repetir", len(junta) == len(set(junta)) == total_db, (len(junta), total_db))
            st, d = get("/eventos?de=2026-10-07%27%20OR%201=1--")
            checar("HTTP replay: injeção no de → 400", st == 400 and "erro" in d, (st, d))
            st, d = get("/eventos?ate=2026-10-08")
            checar("HTTP replay: só ate (sem de) → 400", st == 400, (st, d))
            st, d = get("/eventos?de=")
            checar("HTTP replay: de vazio → 400 (parse_qs descarta vazio e cai no modo antigo)", st == 400, (st, str(d)[:120]))
            st, d = get("/eventos?desde=0&ultimos=3")
            checar("HTTP antigo: ultimos=3 → {total, eventos} sem id", st == 200 and set(d) == {"total", "eventos"}
                   and len(d["eventos"]) == 3 and "id" not in d["eventos"][0], (st, str(d)[:200]))
            st, d2 = get(f"/eventos?desde={d['total'] - 2}")
            checar("HTTP antigo: desde=total-2 → 2 eventos", st == 200 and len(d2["eventos"]) == 2 and d2["total"] == d["total"], (st, d2))
            st, d3 = get("/eventos?desde=x&ultimos=y")
            checar("HTTP antigo: desde/ultimos inválidos viram 0 (como antes)", st == 200 and d3["total"] == d["total"], (st, str(d3)[:120]))
        finally:
            if srv is not None:
                srv.shutdown()
                srv.server_close()
            banco.ARQ, banco.EVENTOS_JSONL, servidor.MAX_PERIODO, servidor.Handler.rede = guardar


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    guardar = banco.ARQ, banco.EVENTOS_JSONL, servidor.MAX_PERIODO
    with tempfile.TemporaryDirectory() as tmp:
        banco.ARQ = Path(tmp) / "escritorio.db"
        banco.EVENTOS_JSONL = Path(tmp) / "eventos.jsonl"   # não existe: a migração só marca como feita
        try:
            for h in range(8, 20):   # um evento por hora de 7/out (08h..19h) e dois no dia 8
                banco.gravar_evento({"ts": f"2026-10-07T{h:02d}:30:00", "agente": "Dev", "tipo": "trabalho", "ferramenta": "Bash",
                                     "resumo": f"h{h}"})
            banco.gravar_evento({"ts": "2026-10-08T09:00:00", "agente": "Lider", "tipo": "fala", "ferramenta": "SendMessage"})
            banco.gravar_evento({"ts": None, "agente": "X", "tipo": "trabalho"})   # sem ts: nunca entra no período
            banco.gravar_evento({"ts": "2026-10-08T10:00:00", "agente": "QA", "tipo": "ocioso"})

            print("banco.eventos_periodo")
            ev, prox = banco.eventos_periodo("2026-10-07", "2026-10-08")
            checar("dia inteiro: 12 eventos, sem próxima página", len(ev) == 12 and prox is None, (len(ev), prox))
            checar("ordem por id e cada evento leva id", [e["id"] for e in ev] == sorted(e["id"] for e in ev) and all("id" in e for e in ev))
            ev, _ = banco.eventos_periodo("2026-10-07T14:00", "2026-10-07T16:00")
            checar("intervalo de horas (ate exclusivo)", [e["resumo"] for e in ev] == ["h14", "h15"], [e.get("resumo") for e in ev])
            ev, prox = banco.eventos_periodo("2026-10-07", "2026-10-08", 0, 5)
            checar("paginação: 5 e proximo = id do 5º", len(ev) == 5 and prox == ev[-1]["id"], (len(ev), prox))
            ev2, prox2 = banco.eventos_periodo("2026-10-07", "2026-10-08", prox, 5)
            ev3, prox3 = banco.eventos_periodo("2026-10-07", "2026-10-08", prox2, 5)
            todos = ev + ev2 + ev3
            checar("paginação cobre tudo sem repetir", len(todos) == 12 and len({e["id"] for e in todos}) == 12 and prox3 is None,
                   (len(todos), prox3))
            ev, prox = banco.eventos_periodo("2026-10-07", "2026-10-08", 0, 12)
            checar("exatamente o máximo: sem próxima página", len(ev) == 12 and prox is None, prox)
            ev, _ = banco.eventos_periodo("2026-10-08", "9999-12-31")
            checar("evento sem ts fica de fora", [e["agente"] for e in ev] == ["Lider", "QA"], [e.get("agente") for e in ev])
            ev, prox = banco.eventos_periodo("2026-10-09", "2026-10-10")
            checar("dia sem eventos", ev == [] and prox is None)

            print("servidor.eventos_periodo (parâmetros da rota)")
            c, d = servidor.eventos_periodo(qs(de="2026-10-07", ate="2026-10-08"))
            checar("200 com eventos, proximo, de, ate, maximo", c == 200 and len(d["eventos"]) == 12 and d["proximo"] is None
                   and d["de"] == "2026-10-07" and d["ate"] == "2026-10-08" and d["maximo"] == servidor.MAX_PERIODO, (c, d.get("proximo")))
            c, d = servidor.eventos_periodo(qs(de="2026-10-08T09:30"))
            checar("sem ate: até agora", c == 200 and [e["agente"] for e in d["eventos"]] == ["QA"], d)
            servidor.MAX_PERIODO = 4
            c, d = servidor.eventos_periodo(qs(de="2026-10-07", ate="2026-10-08"))
            c2, d2 = servidor.eventos_periodo(qs(de="2026-10-07", ate="2026-10-08", apos=d["proximo"]))
            checar("MAX_PERIODO limita e apos pagina", c == 200 and len(d["eventos"]) == 4 and d["proximo"] == d["eventos"][-1]["id"]
                   and d2["eventos"][0]["id"] > d["proximo"], (d.get("proximo"), d2.get("eventos", [{}])[0]))
            servidor.MAX_PERIODO = guardar[2]
            for nome, q in [("de faltando", qs(ate="2026-10-08")), ("de inválido", qs(de="ontem")),
                            ("injeção no de", qs(de="2026-10-07' OR 1=1 --")), ("ate inválido", qs(de="2026-10-07", ate="amanhã")),
                            ("ate antes de de", qs(de="2026-10-08", ate="2026-10-07")), ("ate igual a de", qs(de="2026-10-07", ate="2026-10-07")),
                            ("apos não numérico", qs(de="2026-10-07", apos="x"))]:
                c, d = servidor.eventos_periodo(q)
                checar("400: " + nome, c == 400 and "erro" in d, (c, d))
            c, d = servidor.eventos_periodo(qs(de="2026-10-07", apos="-5"))
            checar("apos negativo vira 0", c == 200 and len(d["eventos"]) == 14, len(d.get("eventos", [])))

            print("GET /eventos de sempre não mudou")
            total, ev = banco.ler_eventos(0, 3)
            checar("ultimos=3 continua igual (sem id no evento)", total == 15 and len(ev) == 3 and "id" not in ev[0], (total, ev[:1]))
            total, ev = banco.ler_eventos(13, 0)
            checar("desde=13 devolve os 2 últimos", len(ev) == 2, len(ev))
            orig = banco.eventos_periodo

            def quebra(*a, **k):
                raise RuntimeError("banco travado")
            banco.eventos_periodo = quebra
            try:
                import contextlib
                import io
                with contextlib.redirect_stdout(io.StringIO()):
                    c, d = servidor.eventos_periodo(qs(de="2026-10-07"))
                checar("banco quebrado: 503 sem exceção", c == 503 and "erro" in d, (c, d))
            finally:
                banco.eventos_periodo = orig
        finally:
            banco.ARQ, banco.EVENTOS_JSONL, servidor.MAX_PERIODO = guardar
    extras()
    print(f"\n{len(feitos)} ok, {len(falhas)} falha(s)")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
