"""Teste da instalação silenciosa numa pasta temporária (usado no CI e localmente).

Instala com o config.exemplo.json apontando para um settings.json temporário, repete (não pode duplicar),
desinstala (tem que remover só os hooks dele) e confere um hook que já existia antes. A statusline opcional
(--statusline) entra só se não houver outra, não duplica e sai no desinstalar; uma statusline alheia nunca é trocada.
Confere também a lista PACOTE: todo item existe no repositório, todo arquivo versionado do pacote está nela e a cópia
leva modelos/, VERSION, CHANGELOG.md e LICENSE para o destino.
O .venv do escritório (1.18.0): criado no destino e reaproveitado ao repetir; hooks e statusline chamam o Python dele,
entre aspas; com --sem-venv, nada de .venv e o python do PATH. O relatório de boas práticas sai sempre e as correções
seguras só rodam com "praticas": {"corrigir": true} (num projeto temporário à parte).
A revisão de PR (1.18.0): por padrão o Revisor entra no time do config.json e o .claude/agents/revisor.md é criado nos
projetos (sem sobrescrever um que já exista); com --sem-revisao, nada disso.
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
    return r.stdout


def contar(settings, so_nossos=True):
    hooks = json.loads(settings.read_text(encoding="utf-8")).get("hooks", {})
    return sum(1 for lista in hooks.values() for e in lista
               if not so_nossos or "registrar_evento.py" in json.dumps(e))


def comandos(settings):
    """Comandos dos hooks do escritório e da statusline."""
    dados = json.loads(settings.read_text(encoding="utf-8"))
    cmds = [h["command"] for lista in dados.get("hooks", {}).values() for e in lista for h in e.get("hooks", [])
            if "registrar_evento.py" in h.get("command", "")]
    return cmds + ([dados["statusLine"]["command"]] if "statusline_uso.py" in json.dumps(dados.get("statusLine")) else [])


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
        saida = rodar(*comum)
        assert ".venv do escritório criado" in saida, f"o .venv não foi criado:\n{saida[-1500:]}"
        assert "Boas práticas dos projetos:" in saida and "Repositório git" in saida, f"sem o relatório:\n{saida[-1500:]}"
        assert "boas práticas em" not in saida, 'corrigiu sem "praticas": {"corrigir": true}'
        nomes = [a["nome"] for a in json.loads((tmp / "app" / "config.json").read_text(encoding="utf-8"))["agentes"]]
        assert "Revisor" in nomes, f"a revisão de PR não pôs o Revisor no time: {nomes}"
        rev = tmp / ".claude" / "agents" / "revisor.md"
        assert rev.is_file() and "gh pr review" in rev.read_text(encoding="utf-8"), "a revisão de PR não criou o revisor.md"
        rev.write_text("MEU revisor\n", encoding="utf-8")
        saida = rodar(*comum)
        assert rev.read_text(encoding="utf-8") == "MEU revisor\n", "repetir a instalação sobrescreveu o revisor.md"
        nomes = [a["nome"] for a in json.loads((tmp / "app" / "config.json").read_text(encoding="utf-8"))["agentes"]]
        assert nomes.count("Revisor") == 1, f"repetir a instalação duplicou o Revisor: {nomes}"
        assert ".venv do escritório reaproveitado" in saida, f"repetir a instalação recriou o .venv:\n{saida[-1500:]}"
        assert "sem mudanças" in saida and not list((tmp / "app").glob("config.json.bak-*")), \
            f"repetir a instalação com o mesmo config fez backup do config.json:\n{saida[-1500:]}"
        assert "sessão principal faz o papel de líder" in saida and not (tmp / "CLAUDE.md").exists(), \
            f"sem lider.md: devia mostrar a seção para o CLAUDE.md sem criá-lo:\n{saida[-1500:]}"
        py = instalar.python_venv(tmp / "app")
        assert py.is_file() and (tmp / "app" / ".venv" / "pyvenv.cfg").is_file(), "o .venv do escritório não existe"
        cmds = comandos(settings)
        assert len(cmds) == 7 and all(c.startswith(f'"{py.as_posix()}" ') for c in cmds), f"sem o python do .venv: {cmds}"
        for rel in ("modelos/diretor.md", "modelos/briefing_diretor.py", "skills-candidatos/externo/README.md", "VERSION",
                    "CHANGELOG.md", "LICENSE"):
            assert (tmp / "app" / rel).is_file(), f"a cópia do pacote não levou {rel}"
        sl = statusline(settings)
        assert sl and sl.get("type") == "command" and "statusline_uso.py" in sl.get("command", ""), f"statusline: {sl}"
        n = contar(settings)
        assert n == 6, f"esperava 6 hooks do escritório, achei {n}"
        assert contar(settings, so_nossos=False) == 7, "o hook que já existia sumiu ou duplicou"
        pre = json.loads(settings.read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
        assert [g.get("matcher") for g in pre] == ["Bash|PowerShell"], f"PreToolUse só nos comandos longos: {pre}"
        falha = json.loads(settings.read_text(encoding="utf-8"))["hooks"]["PostToolUseFailure"]
        assert [g.get("matcher") for g in falha] == ["Bash|PowerShell"], f"PostToolUseFailure só nos comandos: {falha}"
        rodar("--desinstalar", "--sem-perguntas", "--destino", str(tmp / "app"), "--settings-usuario", str(settings), "--sem-abrir")
        assert contar(settings) == 0, "o desinstalar deixou hooks do escritório"
        assert contar(settings, so_nossos=False) == 1, "o desinstalar mexeu no hook alheio"
        assert statusline(settings) is None, "o desinstalar deixou a statusline do escritório"
        # quem atualiza da 1.14 (5 hooks, sem PostToolUseFailure) ganha só o que falta, com o matcher dos comandos
        velho = instalar.bloco_hooks(tmp / "app")["hooks"]
        velho.pop("PostToolUseFailure")
        dados = json.loads(settings.read_text(encoding="utf-8"))
        for ev, grupos in velho.items():
            dados.setdefault("hooks", {}).setdefault(ev, []).extend(grupos)
        settings.write_text(json.dumps(dados), encoding="utf-8")
        assert contar(settings) == 5, "montagem do settings da 1.14"
        rodar(*comum)
        assert contar(settings) == 6, f"atualizar da 1.14: esperava 6 hooks do escritório, achei {contar(settings)}"
        falha = json.loads(settings.read_text(encoding="utf-8"))["hooks"]["PostToolUseFailure"]
        assert [g.get("matcher") for g in falha] == ["Bash|PowerShell"], f"atualizar da 1.14: PostToolUseFailure {falha}"
        rodar("--desinstalar", "--sem-perguntas", "--destino", str(tmp / "app"), "--settings-usuario", str(settings), "--sem-abrir")
        assert contar(settings) == 0 and contar(settings, so_nossos=False) == 1, "desinstalar depois de atualizar da 1.14"
        # statusline alheia: o instalador não troca e o desinstalar não remove
        alheia = {"type": "command", "command": "echo minha-statusline"}
        dados = json.loads(settings.read_text(encoding="utf-8"))
        dados["statusLine"] = alheia
        settings.write_text(json.dumps(dados), encoding="utf-8")
        rodar(*comum)
        assert statusline(settings) == alheia, "o instalador trocou a statusline alheia"
        rodar("--desinstalar", "--sem-perguntas", "--destino", str(tmp / "app"), "--settings-usuario", str(settings), "--sem-abrir")
        assert statusline(settings) == alheia, "o desinstalar removeu a statusline alheia"
        # --sem-venv: sem .venv, hooks com o python do PATH (outro destino e outro settings)
        settings2 = tmp / "settings2.json"
        rodar("--sem-perguntas", "--config", str(tmp / "config.json"), "--destino", str(tmp / "app2"), "--settings-usuario",
              str(settings2), "--hook", "usuario", "--sem-abrir", "--sem-venv", "--sem-revisao")
        assert not (tmp / "app2" / ".venv").exists(), "--sem-venv criou o .venv"
        nomes = [a["nome"] for a in json.loads((tmp / "app2" / "config.json").read_text(encoding="utf-8"))["agentes"]]
        assert "Revisor" not in nomes, f"--sem-revisao pôs o Revisor no time: {nomes}"
        cmds = comandos(settings2)
        assert len(cmds) == 6 and all(c.startswith(instalar.PYTHON_CMD + " ") for c in cmds), f"--sem-venv: {cmds}"
        # "praticas": {"corrigir": true}: corrige o projeto (sem python: não cria .venv), nunca toca o settings do usuário
        proj = tmp / "proj"
        proj.mkdir()
        (tmp / "config3.json").write_text(json.dumps(dict(cfg, projetos=[str(proj)], praticas={"corrigir": True})),
                                          encoding="utf-8")
        settings3 = tmp / "settings3.json"
        saida = rodar("--sem-perguntas", "--config", str(tmp / "config3.json"), "--destino", str(tmp / "app"),
                      "--settings-usuario", str(settings3), "--hook", "nenhum", "--sem-abrir")
        assert "boas práticas em" in saida and (proj / ".gitignore").is_file(), f"praticas.corrigir não corrigiu:\n{saida[-1500:]}"
        assert ".env" in (proj / ".gitignore").read_text(encoding="utf-8").splitlines(), "o .gitignore não cobre o .env"
        assert any((proj / ".claude" / "agents").glob("*.md")), "praticas.corrigir não criou as definições dos agentes"
        assert not (proj / ".venv").exists(), "praticas.corrigir criou .venv num projeto sem Python"
        assert not settings3.exists(), "praticas.corrigir escreveu no settings do usuário"
        assert len(list((tmp / "app").glob("config.json.bak-*"))) == 1, "config.json mudou: devia ter 1 backup"
        # .venv quebrado (o Python dele não roda): o modo silencioso avisa e não recria
        py.write_bytes(b"")
        saida = rodar("--sem-perguntas", "--config", str(tmp / "config3.json"), "--destino", str(tmp / "app"),
                      "--settings-usuario", str(settings3), "--hook", "nenhum", "--sem-abrir")
        assert "não recriei" in saida and py.read_bytes() == b"", f"silencioso recriou o .venv quebrado:\n{saida[-1500:]}"
    print("OK: PACOTE completo; instala, não duplica, desinstala só os seus hooks e a sua statusline; não troca statusline "
          "alheia; .venv do escritório (quebrado não é recriado no silencioso), --sem-venv, backup do config só quando"
          " muda, boas práticas e revisão de PR (--sem-revisao; sem lider.md, a seção para o CLAUDE.md)")


if __name__ == "__main__":
    main()
