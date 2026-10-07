"""Teste da instalação silenciosa numa pasta temporária (usado no CI e localmente).

Instala com o config.exemplo.json apontando para um settings.json temporário, repete (não pode duplicar),
desinstala (tem que remover só os hooks dele) e confere um hook que já existia antes. A statusline opcional
(--statusline) entra só se não houver outra, não duplica e sai no desinstalar; uma statusline alheia nunca é trocada.
Confere também a lista PACOTE: todo item existe no repositório, todo arquivo versionado do pacote está nela e a cópia
leva modelos/, VERSION, CHANGELOG.md e LICENSE para o destino.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
import instalar  # noqa: E402

# versionados que não vão para a pasta de destino (o build.py também tira .github/ e ferramentas/)
FORA_DO_PACOTE = (".gitattributes", ".github/", "ferramentas/")


def rodar(*args):
    r = subprocess.run([sys.executable, str(RAIZ / "instalar.py"), *args], cwd=RAIZ, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL, timeout=120)
    if r.returncode:
        sys.exit(f"instalar.py {' '.join(args)} falhou:\n{r.stdout[-2000:]}\n{r.stderr[-2000:]}")


def contar(settings, so_nossos=True):
    hooks = json.loads(settings.read_text(encoding="utf-8")).get("hooks", {})
    return sum(1 for lista in hooks.values() for e in lista
               if not so_nossos or "registrar_evento.py" in json.dumps(e))


def statusline(settings):
    return json.loads(settings.read_text(encoding="utf-8")).get("statusLine")


def conferir_pacote():
    faltam = [n for n in instalar.PACOTE if not (RAIZ / n).is_file()]
    assert not faltam, f"PACOTE cita arquivos que não existem: {faltam}"
    try:
        r = subprocess.run(["git", "ls-files"], cwd=RAIZ, capture_output=True, text=True, timeout=30)
        versionados = r.stdout.split() if r.returncode == 0 else []
    except (OSError, subprocess.SubprocessError):
        versionados = []
    fora = [f for f in versionados if f not in instalar.PACOTE and not f.startswith(FORA_DO_PACOTE)]
    assert not fora, f"arquivos versionados fora do instalar.PACOTE (inclua ou ponha em FORA_DO_PACOTE): {fora}"


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    conferir_pacote()
    with tempfile.TemporaryDirectory(prefix="c3d") as tmp:
        tmp = Path(tmp)
        settings = tmp / "settings.json"
        alheio = {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo outro-hook"}]}
        settings.write_text(json.dumps({"hooks": {"PostToolUse": [alheio]}}), encoding="utf-8")
        cfg = json.loads((RAIZ / "config.exemplo.json").read_text(encoding="utf-8"))
        cfg["projetos"] = [str(tmp)]
        (tmp / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        comum = ["--sem-perguntas", "--config", str(tmp / "config.json"), "--destino", str(tmp / "app"),
                 "--settings-usuario", str(settings), "--hook", "usuario", "--sem-abrir", "--statusline"]
        rodar(*comum)
        rodar(*comum)
        for rel in ("modelos/diretor.md", "modelos/briefing_diretor.py", "skills-candidatos/externo/README.md", "VERSION",
                    "CHANGELOG.md", "LICENSE"):
            assert (tmp / "app" / rel).is_file(), f"a cópia do pacote não levou {rel}"
        sl = statusline(settings)
        assert sl and sl.get("type") == "command" and "statusline_uso.py" in sl.get("command", ""), f"statusline: {sl}"
        n = contar(settings)
        assert n == 5, f"esperava 5 hooks do escritório, achei {n}"
        assert contar(settings, so_nossos=False) == 6, "o hook que já existia sumiu ou duplicou"
        pre = json.loads(settings.read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
        assert [g.get("matcher") for g in pre] == ["Bash|PowerShell"], f"PreToolUse só nos comandos longos: {pre}"
        rodar("--desinstalar", "--sem-perguntas", "--destino", str(tmp / "app"), "--settings-usuario", str(settings), "--sem-abrir")
        assert contar(settings) == 0, "o desinstalar deixou hooks do escritório"
        assert contar(settings, so_nossos=False) == 1, "o desinstalar mexeu no hook alheio"
        assert statusline(settings) is None, "o desinstalar deixou a statusline do escritório"
        # statusline alheia: o instalador não troca e o desinstalar não remove
        alheia = {"type": "command", "command": "echo minha-statusline"}
        dados = json.loads(settings.read_text(encoding="utf-8"))
        dados["statusLine"] = alheia
        settings.write_text(json.dumps(dados), encoding="utf-8")
        rodar(*comum)
        assert statusline(settings) == alheia, "o instalador trocou a statusline alheia"
        rodar("--desinstalar", "--sem-perguntas", "--destino", str(tmp / "app"), "--settings-usuario", str(settings), "--sem-abrir")
        assert statusline(settings) == alheia, "o desinstalar removeu a statusline alheia"
    print("OK: PACOTE completo; instala, não duplica, desinstala só os seus hooks e a sua statusline; não troca statusline alheia")


if __name__ == "__main__":
    main()
