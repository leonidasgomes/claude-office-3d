"""Teste do hook registrar_evento.py: resultado_de (ok/codigo/erro), evento e main (nunca quebra o hook).

Uso: python -W error ferramentas/testar_registrar_evento.py
Sem tocar no banco real: o módulo `banco` é trocado por um falso em sys.modules e PASTA/FALHA apontam para uma pasta
temporária (nada é gravado em dados/).
"""
import io
import os
import json
import sys
import tempfile
import time
import types
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
import registrar_evento as re_  # noqa: E402

feitos, falhas = [], []


def checar(nome, cond, info=""):
    if cond:
        feitos.append(nome)
        print("  ok:", nome)
    else:
        falhas.append(nome)
        print("  FALHOU:", nome, info)


CWD = str(Path(tempfile.gettempdir()) / "projeto-office-teste")   # pasta de "projetos" (não precisa existir)


def hook(evento, ferramenta="Bash", resposta=None, **extra):
    d = {"hook_event_name": evento, "tool_name": ferramenta, "tool_input": {"command": "python build.py"}, "cwd": CWD,
         "teammate_name": "Dev"}
    if resposta is not None:
        d["tool_response"] = resposta
    d.update(extra)
    return d


# ---------------------------------------------------------------- resultado_de
def testar_resultado_de():
    r = re_.resultado_de
    checar("exit_code 0 → ok True", r("PostToolUse", "Bash", hook("PostToolUse", resposta={"stdout": "", "exit_code": 0})) == {"ok": True, "codigo": 0})
    checar("exit_code 2 → ok False, codigo 2", r("PostToolUse", "Bash", hook("PostToolUse", resposta={"exit_code": 2})) == {"ok": False, "codigo": 2})
    for k in ("exitCode", "returncode", "returnCode"):
        checar(f"{k} também vale", r("PostToolUse", "PowerShell", hook("PostToolUse", "PowerShell", {k: 1})) == {"ok": False, "codigo": 1})
    checar("exit_code booleano não conta (sem informação)", r("PostToolUse", "Bash", hook("PostToolUse", resposta={"exit_code": False})) == {})
    checar("exit_code texto/float não conta", r("PostToolUse", "Bash", hook("PostToolUse", resposta={"exit_code": "1", "returncode": 1.0})) == {})
    # semântica medida em 7 out. 2026: o sucesso chega no PostToolUse sem exit_code ({interrupted, isImage, noOutputExpected,
    # stderr, stdout}); a falha chega só no PostToolUseFailure ("Exit code N")
    checar("PostToolUse sem exit_code, formato medido (stdout/stderr/interrupted False) → ok True (stderr com 'Error' não vira falha)",
           r("PostToolUse", "Bash", hook("PostToolUse", resposta={"interrupted": False, "isImage": False, "noOutputExpected": False,
                                                                  "stdout": "x", "stderr": "Error: aviso"})) == {"ok": True})
    checar("PostToolUse de Bash só com stdout → ok True", r("PostToolUse", "Bash", hook("PostToolUse", resposta={"stdout": ""})) == {"ok": True})
    checar("PostToolUse de PowerShell só com stderr → ok True",
           r("PostToolUse", "PowerShell", hook("PostToolUse", "PowerShell", {"stderr": "aviso"})) == {"ok": True})
    checar("PostToolUse com tool_response dict vazio (sem stdout/stderr) → {}", r("PostToolUse", "Bash", hook("PostToolUse", resposta={})) == {})
    checar("PostToolUse sem stdout/stderr nem exit_code (interrupted False) → {}",
           r("PostToolUse", "Bash", hook("PostToolUse", resposta={"interrupted": False, "isImage": False})) == {})
    checar("interrupted True com stdout → ok False 'interrompido' (não vira sucesso)",
           r("PostToolUse", "Bash", hook("PostToolUse", resposta={"stdout": "meio", "stderr": "", "interrupted": True})) == {"ok": False, "erro": "interrompido"})
    checar("stdout/stderr fora do PostToolUse não vira ok True",
           r("PreToolUse", "Bash", hook("PreToolUse", resposta={"stdout": "x"})) == {})
    checar("PostToolUse sem tool_response → {}", r("PostToolUse", "Bash", hook("PostToolUse")) == {})
    checar("tool_response lista/None/número → {}", all(r("PostToolUse", "Bash", hook("PostToolUse", resposta=v)) == {} for v in ([1], 0, 3.5)))
    checar("interrupted True → ok False 'interrompido'",
           r("PostToolUse", "Bash", hook("PostToolUse", resposta={"interrupted": True})) == {"ok": False, "erro": "interrompido"})
    checar("exit_code tem precedência sobre interrupted",
           r("PostToolUse", "Bash", hook("PostToolUse", resposta={"interrupted": True, "exit_code": 0})) == {"ok": True, "codigo": 0})
    checar("texto 'Error: Exit code 3' → codigo 3 e erro curto (sem a saída)",
           r("PostToolUse", "Bash", hook("PostToolUse", resposta="Error: Exit code 3\nTOKEN-SECRETO")) == {"ok": False, "codigo": 3, "erro": "exit code 3"})
    checar("texto '  Error: Exit code 0' com espaço antes também vale",
           r("PostToolUse", "Bash", hook("PostToolUse", resposta="  Error: Exit code 0")).get("codigo") == 0)
    for txt in ("Error: falhou sem código", "error: exit code 3", "ERROR ruim", "  error ruim", "Error handling docs gerados",
                "Error: Exit code x", "saída\nError: Exit code 3", "Exit code 3"):
        res = r("PostToolUse", "Bash", hook("PostToolUse", resposta=txt))
        checar(f"saída em texto fora do formato exato não vira ok False: {txt!r}"[:90], res == {}, res)
    checar("texto que não começa com error → {}", r("PostToolUse", "Bash", hook("PostToolUse", resposta="tudo certo, sem Error")) == {})
    f = r("PostToolUseFailure", "Bash", hook("PostToolUseFailure", error="Exit code 1\n  saída   ruim\nTOKEN-SECRETO"))
    checar("PostToolUseFailure multi-linha → codigo e só a 1ª linha", f == {"ok": False, "codigo": 1, "erro": "Exit code 1"}, f)
    f = r("PostToolUseFailure", "Bash", hook("PostToolUseFailure", error="Exit code 3\nmais"))
    checar("PostToolUseFailure 'Exit code 3' + linha → codigo 3, erro 'Exit code 3'", f == {"ok": False, "codigo": 3, "erro": "Exit code 3"}, f)
    f = r("PostToolUseFailure", "PowerShell", hook("PostToolUseFailure", "PowerShell", error="Exit code 127"))
    checar("PostToolUseFailure de PowerShell → codigo 127", f == {"ok": False, "codigo": 127, "erro": "Exit code 127"}, f)
    f = r("PostToolUseFailure", "Bash", hook("PostToolUseFailure", error="Command timed out"))
    checar("PostToolUseFailure sem 'Exit code N' → ok False sem codigo", f == {"ok": False, "erro": "Command timed out"}, f)
    f = r("PostToolUseFailure", "Bash", hook("PostToolUseFailure", error="\n\n   Exit   code  2  \nresto"))
    checar("PostToolUseFailure: pula linhas vazias, normaliza espaços e acha o codigo", f == {"ok": False, "codigo": 2, "erro": "Exit code 2"}, f)
    # run_in_background: o PostToolUse chega no INÍCIO do comando, então não há resultado
    bg = lambda resp, ti=None: r("PostToolUse", "Bash", dict(hook("PostToolUse", resposta=resp),
                                                              tool_input=ti if ti is not None else {"command": "x", "run_in_background": True}))
    checar("run_in_background com stdout/stderr → {}", bg({"stdout": "", "stderr": "", "interrupted": False}) == {})
    checar("run_in_background com stdout e backgroundTaskId → {}", bg({"stdout": "Command running in background", "backgroundTaskId": "b1"}) == {})
    checar("run_in_background False segue ok True", bg({"stdout": "x"}, {"command": "x", "run_in_background": False}) == {"ok": True})
    checar("run_in_background não esconde exit_code nem interrupted",
           bg({"stdout": "", "exit_code": 1}) == {"ok": False, "codigo": 1} and bg({"stdout": "", "interrupted": True}) == {"ok": False, "erro": "interrompido"})
    checar("run_in_background: PostToolUseFailure continua ok False",
           r("PostToolUseFailure", "Bash", dict(hook("PostToolUseFailure", error="Exit code 4"), tool_input={"run_in_background": True})).get("codigo") == 4)
    try:
        res = bg({"stdout": "x"}, [1, 2])
        checar("tool_input lista não quebra resultado_de", isinstance(res, dict), res)
    except Exception as e:  # noqa: BLE001
        checar("tool_input lista não quebra resultado_de", False, repr(e))
    checar("PostToolUseFailure: error só com espaços → 'falhou'",
           r("PostToolUseFailure", "Bash", hook("PostToolUseFailure", error=" \n \n")) == {"ok": False, "erro": "falhou"})
    checar("PostToolUseFailure sem error → 'falhou'", r("PostToolUseFailure", "Bash", hook("PostToolUseFailure")) == {"ok": False, "erro": "falhou"})
    checar("PostToolUseFailure com error não texto não quebra",
           r("PostToolUseFailure", "Bash", hook("PostToolUseFailure", error={"a": 1}))["ok"] is False)
    checar("PostToolUseFailure: 1ª linha limitada a 120",
           len(r("PostToolUseFailure", "Bash", hook("PostToolUseFailure", error="e" * 999 + "\nx"))["erro"]) == 120)
    for f_ in ("Edit", "Read", "SendMessage", "Agent", ""):
        checar(f"ferramenta não Bash/PowerShell ({f_ or 'vazia'}) → {{}} (também no PostToolUseFailure)",
               r("PostToolUseFailure", f_, hook("PostToolUseFailure", f_, error="x")) == {} and
               r("PostToolUse", f_, hook("PostToolUse", f_, {"exit_code": 1})) == {})


# ---------------------------------------------------------------- evento
def testar_evento():
    e = re_.evento(hook("PostToolUse", resposta={"exit_code": 1}))
    checar("evento: trabalho com ok/codigo", e["tipo"] == "trabalho" and e["ok"] is False and e["codigo"] == 1
           and e["agente"] == "Dev" and e["detalhe"] == "command: python build.py", e)
    e = re_.evento(hook("PostToolUse", resposta={"stdout": "ok", "stderr": "", "interrupted": False}))
    checar("evento: sucesso medido (sem exit_code, com stdout) → ok True, sem codigo/erro",
           e["tipo"] == "trabalho" and e.get("ok") is True and not {"codigo", "erro"} & set(e), e)
    e = re_.evento(hook("PostToolUse", resposta={}))
    checar("evento: tool_response vazio → sem ok/codigo/erro", not {"ok", "codigo", "erro"} & set(e), e)
    e = re_.evento(hook("PostToolUseFailure", error="Exit code 2"))
    checar("evento: PostToolUseFailure vira trabalho com ok False e codigo 2",
           e["tipo"] == "trabalho" and e["ok"] is False and e.get("codigo") == 2 and "erro" in e, e)
    e = re_.evento(hook("PreToolUse", resposta={"exit_code": 1}))
    checar("evento: PreToolUse (início) não leva resultado", e.get("inicio") is True and "ok" not in e, e)
    checar("evento: PreToolUse em segundo plano → None",
           re_.evento(dict(hook("PreToolUse"), tool_input={"command": "x", "run_in_background": True})) is None)
    e = re_.evento(dict(hook("PostToolUse", "Edit", {"exit_code": 1}), tool_input={"file_path": "/projeto/src/a.py"}))
    checar("evento: Edit não leva ok (mesmo com exit_code na resposta)", "ok" not in e and e["detalhe"] == "file_path: /projeto/src/a.py", e)
    for f_ in ("Read", "Edit"):
        e = re_.evento(dict(hook("PostToolUse", f_, {"stdout": "x", "stderr": "", "interrupted": False}), tool_input={"file_path": "/projeto/src/a.py"}))
        checar(f"evento: {f_} com stdout/stderr na resposta nunca ganha ok", not {"ok", "codigo", "erro"} & set(e), e)
        e = re_.evento(dict(hook("PostToolUseFailure", f_, error="Exit code 1"), tool_input={"file_path": "/projeto/src/a.py"}))
        checar(f"evento: {f_} no PostToolUseFailure nunca ganha ok", e is None or not {"ok", "codigo", "erro"} & set(e), e)
    e = re_.evento(hook("PostToolUse", "SendMessage", tool_input={"to": "Lider", "message": "oi"}))
    checar("evento: SendMessage segue fala, sem ok", e["tipo"] == "fala" and "ok" not in e, e)
    e = re_.evento({"hook_event_name": "Stop", "cwd": CWD})
    checar("evento: Stop → ocioso", e["tipo"] == "ocioso", e)
    checar("evento: serializável em JSON", json.loads(json.dumps(re_.evento(hook("PostToolUseFailure", error="ç ✓"))))["ok"] is False)


# ---------------------------------------------------------------- main: nunca quebra nem bloqueia o hook
class BancoFalso(types.ModuleType):
    def __init__(self):
        super().__init__("banco")
        self.gravados, self.falhar = [], False

    def gravar_evento(self, ev):
        if self.falhar:
            raise RuntimeError("banco ocupado")
        self.gravados.append(ev)


def rodar_main(entrada):
    """Roda registrar_evento.main() com `entrada` (bytes) no stdin; devolve (código de saída, stdout, segundos)."""
    stdin, stdout = sys.stdin, sys.stdout
    sys.stdin = types.SimpleNamespace(buffer=io.BytesIO(entrada))
    sys.stdout = io.StringIO()
    t = time.time()
    try:
        re_.main()
        codigo = "sem sys.exit"
    except SystemExit as e:
        codigo = e.code
    finally:
        saida = sys.stdout.getvalue()
        sys.stdin, sys.stdout = stdin, stdout
    return codigo, saida, time.time() - t


def testar_main(tmp):
    banco = BancoFalso()
    guardar = sys.modules.get("banco"), re_.PASTA, re_.FALHA, re_.CFG["projetos"]
    sys.modules["banco"] = banco
    re_.CFG["projetos"] = [CWD]   # só registra sessões dentro das pastas de "projetos"
    re_.PASTA = Path(tmp) / "dados"
    re_.FALHA = re_.PASTA / "eventos.falha.jsonl"
    try:
        c, s, dt = rodar_main(json.dumps(hook("PostToolUseFailure", error="Exit code 1")).encode())
        checar("main: falha de comando gravada com ok False, sai 0 sem saída", c == 0 and s == "" and len(banco.gravados) == 1
               and banco.gravados[0]["ok"] is False, (c, s, banco.gravados))
        checar("main: rápido (< 1 s)", dt < 1, dt)
        for nome, entrada in (("stdin vazio", b""), ("JSON quebrado", b"{quebrado"), ("JSON lista", b"[1,2]"), ("bytes inválidos", b"\xff\xfe{"),
                              ("JSON aninhado demais", b"[" * 100000 + b"]" * 100000), ("cwd de fora", json.dumps(dict(hook("PostToolUse"), cwd="C:/x")).encode()),
                              ("cwd não texto", json.dumps(dict(hook("PostToolUse"), cwd=5)).encode()),
                              ("tool_input lista", json.dumps(dict(hook("PostToolUse"), tool_input=[1])).encode()),
                              ("tool_response estranho", json.dumps(hook("PostToolUse", resposta={"exit_code": 10 ** 30})).encode())):
            c, s, dt = rodar_main(entrada)
            checar(f"main: {nome} → sai 0, sem saída", c == 0 and s == "" and dt < 2, (c, s, dt))
        n = len(banco.gravados)
        rodar_main(json.dumps(dict(hook("PostToolUse"), cwd="C:/outro")).encode())
        checar("main: cwd fora das pastas de projetos não grava", len(banco.gravados) == n)
        banco.falhar = True
        c, s, _ = rodar_main(json.dumps(hook("PostToolUse", resposta={"exit_code": 0})).encode())
        linhas = re_.FALHA.read_text(encoding="utf-8").splitlines() if re_.FALHA.exists() else []
        checar("main: banco quebrado → linha em eventos.falha.jsonl, sai 0", c == 0 and s == "" and linhas and json.loads(linhas[-1])["ok"] is True,
               (c, linhas))
        orig = re_.evento
        re_.evento = lambda d: (_ for _ in ()).throw(KeyError("x"))
        try:
            c, s, _ = rodar_main(json.dumps(hook("PostToolUse")).encode())
        finally:
            re_.evento = orig
        checar("main: exceção inesperada em evento() → sai 0", c == 0 and s == "", (c, s))
    finally:
        if guardar[0] is None:
            sys.modules.pop("banco", None)
        else:
            sys.modules["banco"] = guardar[0]
        re_.PASTA, re_.FALHA, re_.CFG["projetos"] = guardar[1], guardar[2], guardar[3]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    t = time.time()
    os.environ.pop("OFFICE_AGENTE", None)   # o agente vem do JSON do hook, não do ambiente de quem roda o teste
    reais = [RAIZ / "dados" / "eventos.falha.jsonl", RAIZ / "dados" / "escritorio.db"]
    antes = [r.stat().st_mtime if r.exists() else None for r in reais]
    testar_resultado_de()
    testar_evento()
    with tempfile.TemporaryDirectory() as tmp:
        testar_main(tmp)
    depois = [r.stat().st_mtime if r.exists() else None for r in reais]
    checar("nada gravado em dados/ de verdade", antes == depois)
    if falhas:
        print(f"FALHOU: {len(falhas)} de {len(feitos) + len(falhas)} verificações")
        return 1
    print(f"OK: {len(feitos)} verificações em {time.time() - t:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
