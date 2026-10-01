"""Teste da instalação silenciosa numa pasta temporária (usado no CI e localmente).

Instala com o config.exemplo.json apontando para um settings.json temporário, repete (não pode duplicar),
desinstala (tem que remover só os hooks dele) e confere um hook que já existia antes.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def rodar(*args):
    r = subprocess.run([sys.executable, str(RAIZ / "instalar.py"), *args], cwd=RAIZ, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL, timeout=120)
    if r.returncode:
        sys.exit(f"instalar.py {' '.join(args)} falhou:\n{r.stdout[-2000:]}\n{r.stderr[-2000:]}")


def contar(settings, so_nossos=True):
    hooks = json.loads(settings.read_text(encoding="utf-8")).get("hooks", {})
    return sum(1 for lista in hooks.values() for e in lista
               if not so_nossos or "registrar_evento.py" in json.dumps(e))


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="c3d") as tmp:
        tmp = Path(tmp)
        settings = tmp / "settings.json"
        alheio = {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo outro-hook"}]}
        settings.write_text(json.dumps({"hooks": {"PostToolUse": [alheio]}}), encoding="utf-8")
        cfg = json.loads((RAIZ / "config.exemplo.json").read_text(encoding="utf-8"))
        cfg["projetos"] = [str(tmp)]
        (tmp / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        comum = ["--sem-perguntas", "--config", str(tmp / "config.json"), "--destino", str(tmp / "app"),
                 "--settings-usuario", str(settings), "--hook", "usuario", "--sem-abrir"]
        rodar(*comum)
        rodar(*comum)
        n = contar(settings)
        assert n == 4, f"esperava 4 hooks do escritório, achei {n}"
        assert contar(settings, so_nossos=False) == 5, "o hook que já existia sumiu ou duplicou"
        rodar("--desinstalar", "--sem-perguntas", "--destino", str(tmp / "app"), "--settings-usuario", str(settings), "--sem-abrir")
        assert contar(settings) == 0, "o desinstalar deixou hooks do escritório"
        assert contar(settings, so_nossos=False) == 1, "o desinstalar mexeu no hook alheio"
    print("OK: instala, não duplica, desinstala só os seus hooks")


if __name__ == "__main__":
    main()
