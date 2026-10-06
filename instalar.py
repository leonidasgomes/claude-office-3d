"""Assistente de instalação do Claude Office 3D (somente biblioteca padrão, Python 3.9+).

    python instalar.py                                   instalação guiada, passo a passo
    python instalar.py --sem-perguntas --config X.json   instalação silenciosa (para automatizar)
    python instalar.py --desinstalar                     remove os hooks deste escritório (com backup)

Opções:
    --settings-usuario CAMINHO   usa outro settings.json no lugar de ~/.claude/settings.json
    --destino PASTA              pasta de instalação (padrão: esta pasta)
    --hook usuario|projeto|nenhum   escopo do hook no modo silencioso (padrão: usuario)
    --sem-abrir                  não pergunta / não abre o escritório no final

No modo silencioso, o arquivo de --config tem o formato do config.json e pode trazer um bloco extra
"instalacao": {"destino": "...", "hook": "usuario|projeto|nenhum", "three_offline": false, "abrir": false}.
"""
import argparse
import copy
import json
import os
import platform
import re
import shutil
import socket
import stat
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

if sys.version_info < (3, 9):
    print("O Claude Office 3D precisa do Python 3.9 ou mais novo (você tem %d.%d)." % sys.version_info[:2])
    sys.exit(1)

PASTA = Path(__file__).resolve().parent
sys.path.insert(0, str(PASTA))
import configuracao  # noqa: E402

for _fluxo in (sys.stdout, sys.stderr):
    try:
        _fluxo.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

WINDOWS = os.name == "nt"
PYTHON_CMD = "python" if WINDOWS else "python3"
TOTAL_PASSOS = 7
EVENTOS_HOOK = ("PostToolUse", "TeammateIdle", "Stop", "SubagentStop")
PACOTE = ["index.html", "escritorio.js", "config.js", "kanban.js", "prs.js", "estilo.css", "kanban.css", "prs.css",
          "servidor.py", "registrar_evento.py", "configuracao.py", "instalar.py", "instalar.bat", "instalar.sh",
          "abrir_escritorio.bat", "abrir_escritorio.sh", "reiniciar_escritorio.bat", "reiniciar_escritorio.sh",
          "placar.js", "placar.css", "rede.py", "tls.py", "qr.js", "movel.js", "celular.js", "celular.css", "alertas.py", "alertas.js", "alertas.css", "push.py", "cota.py", "sugestoes_bot.py", "revisor_ia.py", "custo_time.py", "plugins_projeto.py", "sw.js",
          "icone-192.png", "icone-512.png", "xp.py", "skills.py", "skills-candidatos/MODELO.md", "config.exemplo.json", "glossario_triagem.exemplo.md", "INSTALACAO.md", "README.md", ".gitignore"]
CDN_THREE = f"https://cdn.jsdelivr.net/npm/three@{configuracao.VERSAO_THREE}/"
ARQUIVOS_THREE = ["build/three.module.js", "examples/jsm/controls/OrbitControls.js"]
MESAS_SUGERIDAS = ["lider", "dev", "design", "pesquisa"]


class Cancelado(Exception):
    pass


# ---------------------------------------------------------------- entrada e saída
def titulo_passo(n, texto):
    print()
    print("=" * 64)
    print(f" Passo {n} de {TOTAL_PASSOS} — {texto}")
    print("=" * 64)


def ler(texto):
    try:
        return input(texto)
    except (EOFError, KeyboardInterrupt):
        raise Cancelado()


def perguntar(texto, padrao="", validar=None):
    """Pergunta com valor padrão entre colchetes; Enter aceita. validar(valor) -> mensagem de erro ou None."""
    while True:
        sufixo = f" [{padrao}]" if padrao != "" else ""
        v = ler(f"{texto}{sufixo}: ").strip()
        if not v:
            v = str(padrao)
        erro = validar(v) if validar else None
        if not erro:
            return v
        print(f"  ! {erro}")


def sim_nao(texto, padrao=True):
    while True:
        v = ler(f"{texto} [{'S/n' if padrao else 's/N'}]: ").strip().lower()
        if not v:
            return padrao
        if v in ("s", "sim", "y", "yes"):
            return True
        if v in ("n", "nao", "não", "no"):
            return False
        print("  ! responda s ou n")


def escolher(texto, opcoes, padrao=1):
    """opcoes: lista de rótulos. Devolve o índice (0-based)."""
    for i, o in enumerate(opcoes, 1):
        print(f"  {i}) {o}")
    v = perguntar(texto, str(padrao), lambda x: None if x.isdigit() and 1 <= int(x) <= len(opcoes)
                  else f"escolha um número de 1 a {len(opcoes)}")
    return int(v) - 1


def rodar(cmd, timeout=20, cwd=None):
    """(código, saída) de um comando; (None, '') se não existir."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, cwd=cwd)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except (OSError, subprocess.SubprocessError):
        return None, ""


# ---------------------------------------------------------------- checagens
def checar_ambiente(silencioso=False):
    info = {"python": platform.python_version(), "claude": None, "gh": configuracao.localizar_gh(), "gh_auth": False}
    claude = shutil.which("claude")
    if claude:
        cod, out = rodar([claude, "--version"])
        info["claude"] = out.strip().splitlines()[0] if cod == 0 and out.strip() else "instalado (versão não lida)"
    if info["gh"]:
        cod, _ = rodar([info["gh"], "auth", "status"])
        info["gh_auth"] = cod == 0
    if not silencioso:
        print(f"  [ok] Python {info['python']}")
        print(f"  [{'ok' if info['claude'] else '!!'}] Claude Code: "
              f"{info['claude'] or 'não encontrado no PATH (instale: https://docs.claude.com/claude-code)'}")
        if info["gh"]:
            print(f"  [ok] GitHub CLI: {info['gh']}  —  login: {'ok' if info['gh_auth'] else 'NÃO (rode: gh auth login)'}")
        else:
            print("  [--] GitHub CLI (gh) não encontrado — opcional; sem ele o Kanban e os PRs ficam desligados")
    return info


def porta_ocupada(porta):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", int(porta))) == 0


# ---------------------------------------------------------------- agentes
def ler_agentes_md(pastas):
    """Agentes definidos em <projeto>/.claude/agents/*.md (campos name e description do cabeçalho YAML)."""
    achados, vistos = [], set()
    for p in pastas:
        for md in sorted((Path(p) / ".claude" / "agents").glob("*.md")):
            try:
                texto = md.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            m = re.match(r"^---\s*\n(.*?)\n---", texto, re.S)
            campos = {}
            if m:
                for linha in m.group(1).splitlines():
                    if ":" in linha and not linha.startswith((" ", "\t")):
                        k, v = linha.split(":", 1)
                        campos[k.strip().lower()] = v.strip().strip("\"'")
            nome = campos.get("name") or md.stem
            if configuracao.chave(nome) in vistos:
                continue
            vistos.add(configuracao.chave(nome))
            desc = campos.get("description", "")
            desc = desc if len(desc) <= 48 else desc[:47].rstrip() + "…"
            achados.append({"nome": nome, "funcao": desc})
    return achados


def completar_agentes(lista):
    """Título, cor, mesa e apelidos sugeridos para quem não tem."""
    saida = []
    for i, ag in enumerate(lista):
        ag = dict(ag)
        ag.setdefault("titulo", ag["nome"].replace("_", " ").replace("-", " "))
        ag.setdefault("cor", configuracao.PALETA[i % len(configuracao.PALETA)])
        ag.setdefault("mesa", MESAS_SUGERIDAS[i] if i < len(MESAS_SUGERIDAS) else "padrao")
        saida.append(configuracao.normalizar_agente(ag, i))
    return saida


def mostrar_agentes(agentes):
    for i, a in enumerate(agentes):
        papel = "  (líder: sessão principal)" if i == 0 else ""
        print(f"   {i + 1:>2}. {a['nome']:<22} {a['titulo']:<18} {a['cor']}  mesa {a['mesa']:<8} {a['funcao']}{papel}")


def validar_cor(v):
    return None if re.fullmatch(r"#?[0-9a-fA-F]{6}", v) else "use o formato #rrggbb (ex.: #3b82f6)"


def digitar_agentes():
    print("  O primeiro é o LÍDER: a sessão principal do Claude Code aparece na mesa dele.")
    lider = perguntar("  Nome do líder (como aparece nos eventos)", "Lider")
    agentes = [{"nome": lider, "titulo": perguntar("  Título do líder", "Líder"), "lider": True,
                "funcao": perguntar("  Função do líder", "Coordena o time e revisa"),
                "outros_nomes": ["main", "lead", "leader", "team-lead"]}]
    print("  Agora os colegas do time (nome igual ao 'name' do colega / subagente). Enter vazio termina.")
    while len(agentes) < 10:
        i = len(agentes)
        nome = ler(f"  Nome do agente {i + 1} (Enter = terminar): ").strip()
        if not nome:
            break
        sug = configuracao.PALETA[i % len(configuracao.PALETA)]
        agentes.append({
            "nome": nome,
            "titulo": perguntar("    Título", nome.replace("_", " ")),
            "funcao": perguntar("    Função", ""),
            "cor": "#" + perguntar("    Cor", sug, validar_cor).lstrip("#"),
            "mesa": perguntar("    Mesa (lider/dev/design/pesquisa/padrao)",
                              MESAS_SUGERIDAS[i] if i < len(MESAS_SUGERIDAS) else "padrao",
                              lambda v: None if v in configuracao.TIPOS_MESA else "use lider, dev, design, pesquisa ou padrao"),
        })
    return completar_agentes(agentes)


# ---------------------------------------------------------------- GitHub
def repo_do_git(pasta):
    cod, out = rodar(["git", "-C", str(pasta), "remote", "get-url", "origin"])
    if cod != 0:
        return ""
    m = re.search(r"github\.com[:/]([^/\s]+)/([^/\s]+?)(?:\.git)?/?$", out.strip())
    return f"{m.group(1)}/{m.group(2)}" if m else ""


def listar_projects(gh, owner):
    cod, out = rodar([gh, "project", "list", "--owner", owner, "--format", "json", "--limit", "50"], timeout=40)
    if cod != 0:
        return None
    try:
        return json.loads(out[out.index("{"):]).get("projects", [])
    except (ValueError, AttributeError):
        return None


# ---------------------------------------------------------------- hooks do Claude Code
def comando_hook(pasta):
    return f'{PYTHON_CMD} "{(Path(pasta) / "registrar_evento.py").as_posix()}"'


def bloco_hooks(pasta):
    # async: o registrar_evento.py só grava o evento (não imprime nem decide), então não precisa travar cada chamada de
    # ferramenta do agente esperando o Python subir (doc hooks: "Run hooks in the background").
    h = {"type": "command", "command": comando_hook(pasta), "timeout": 5, "async": True}
    return {"hooks": {ev: [({"matcher": "*"} if ev == "PostToolUse" else {}) | {"hooks": [dict(h)]}]
                      for ev in EVENTOS_HOOK}}


def _norm(t):
    return str(t).replace("\\", "/").casefold()


def eh_nosso(hook, pasta):
    """Hook deste escritório: o comando aponta para o registrar_evento.py desta pasta."""
    return isinstance(hook, dict) and _norm((Path(pasta) / "registrar_evento.py").as_posix()) in _norm(hook.get("command", ""))


def ler_settings(arq):
    if not arq.exists():
        return {}
    texto = arq.read_text(encoding="utf-8-sig").strip()
    if not texto:
        return {}
    dados = json.loads(texto)  # JSON inválido: deixa o erro subir (não sobrescreve o arquivo do usuário)
    if not isinstance(dados, dict):
        raise ValueError(f"{arq} não contém um objeto JSON")
    return dados


def backup(arq):
    if not arq.exists():
        return None
    destino = arq.with_name(f"{arq.name}.bak-{datetime.now():%Y%m%d-%H%M%S}")
    n = 1
    while destino.exists():
        destino = arq.with_name(f"{arq.name}.bak-{datetime.now():%Y%m%d-%H%M%S}-{n}")
        n += 1
    shutil.copy2(arq, destino)
    return destino


def gravar_settings(arq, dados):
    arq.parent.mkdir(parents=True, exist_ok=True)
    arq.write_text(json.dumps(dados, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def mesclar_hooks(dados, pasta):
    """Acrescenta os hooks sem apagar os existentes; idempotente. Devolve (dados, n_adicionados)."""
    dados = copy.deepcopy(dados)
    hooks = dados.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError('"hooks" no settings.json não é um objeto')
    novo = bloco_hooks(pasta)["hooks"]
    adicionados = 0
    for ev in EVENTOS_HOOK:
        grupos = hooks.setdefault(ev, [])
        ja = False
        for g in grupos:
            for h in g.get("hooks", []) if isinstance(g, dict) else []:
                if eh_nosso(h, pasta):
                    h.update(novo[ev][0]["hooks"][0])  # atualiza comando/timeout se mudou
                    ja = True
        if not ja:
            grupos.append(copy.deepcopy(novo[ev][0]))
            adicionados += 1
    return dados, adicionados


def remover_hooks(dados, pasta):
    """Tira só os hooks deste escritório. Devolve (dados, n_removidos)."""
    dados = copy.deepcopy(dados)
    hooks = dados.get("hooks")
    if not isinstance(hooks, dict):
        return dados, 0
    removidos = 0
    for ev in list(hooks):
        grupos = hooks[ev] if isinstance(hooks[ev], list) else []
        novos = []
        for g in grupos:
            if not isinstance(g, dict):
                novos.append(g)
                continue
            antes = g.get("hooks", [])
            ficam = [h for h in antes if not eh_nosso(h, pasta)]
            removidos += len(antes) - len(ficam)
            if ficam:
                novos.append({**g, "hooks": ficam})
            elif not antes:
                novos.append(g)
        if novos:
            hooks[ev] = novos
        else:
            del hooks[ev]
    if not hooks:
        del dados["hooks"]
    return dados, removidos


def instalar_hook(arq, pasta):
    arq = Path(arq)
    atual = ler_settings(arq)
    novo, n = mesclar_hooks(atual, pasta)
    if novo == atual:
        return None, 0
    copia = backup(arq)
    gravar_settings(arq, novo)
    return copia, n


def desinstalar_hook(arq, pasta):
    arq = Path(arq)
    if not arq.exists():
        return None, 0
    atual = ler_settings(arq)
    novo, n = remover_hooks(atual, pasta)
    if not n:
        return None, 0
    copia = backup(arq)
    gravar_settings(arq, novo)
    return copia, n


def settings_usuario(args):
    return Path(args.settings_usuario).expanduser() if args.settings_usuario else Path.home() / ".claude" / "settings.json"


def arquivos_settings(escopo, projetos, args):
    if escopo == "usuario":
        return [settings_usuario(args)]
    if escopo == "projeto":
        return [Path(p) / ".claude" / "settings.local.json" for p in projetos]
    return []


# ---------------------------------------------------------------- arquivos da instalação
ATALHO_BAT = """@echo off
rem Abre o Claude Office 3D: sobe o servidor local (porta do config.json) e abre o navegador.
rem   abrir_escritorio.bat           -> so neste PC (127.0.0.1)
rem   abrir_escritorio.bat celular   -> liga o acesso pelo celular na rede local (QR code no botao Celular)
chcp 65001 >nul
cd /d "%~dp0"
set EXTRA=
if /i "%~1"=="celular" set EXTRA=--rede-local
echo Iniciando o Claude Office 3D...
where python >nul 2>nul
if %errorlevel%==0 (python "servidor.py" %EXTRA%) else (py -3 "servidor.py" %EXTRA%)
pause
"""
ATALHO_SH = """#!/usr/bin/env sh
# Abre o Claude Office 3D: sobe o servidor local (porta do config.json) e abre o navegador.
#   ./abrir_escritorio.sh           -> só neste PC (127.0.0.1)
#   ./abrir_escritorio.sh celular   -> liga o acesso pelo celular na rede local (QR code no botão Celular)
cd "$(dirname "$0")" || exit 1
echo "Iniciando o Claude Office 3D..."
if [ "$1" = "celular" ]; then shift; set -- --rede-local "$@"; fi
exec python3 servidor.py "$@"
"""
REINICIAR_BAT = """@echo off
rem Reinicia o Claude Office 3D: encerra o servidor da porta configurada (se estiver rodando) e sobe de novo, minimizado.
rem   reiniciar_escritorio.bat celular   -> sobe com o acesso pelo celular na rede local (--rede-local)
chcp 65001 >nul
cd /d "%~dp0"
set EXTRA=
if /i "%~1"=="celular" set EXTRA=--rede-local
set PY=python
where python >nul 2>nul || set PY=py -3
for /f "usebackq delims=" %%p in (`%PY% configuracao.py --porta`) do set PORTA=%%p
if "%PORTA%"=="" set PORTA=8765
echo Encerrando o servidor antigo do escritorio (porta %PORTA%)...
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort %PORTA% -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue; Write-Host ('  processo ' + $_ + ' encerrado') }"
powershell -NoProfile -Command "Start-Sleep -Seconds 1"
echo Subindo o escritorio de novo...
start "Claude Office 3D" /min /D "%~dp0" cmd /c %PY% servidor.py --sem-navegador %EXTRA%
echo Pronto: http://127.0.0.1:%PORTA%/  (a pagina aberta reconecta sozinha)
if defined EXTRA echo Acesso pelo celular LIGADO: use o botao Celular na pagina para ver o QR code.
"""
REINICIAR_SH = """#!/usr/bin/env sh
# Reinicia o Claude Office 3D: encerra o servidor da porta configurada (se estiver rodando) e sobe de novo em segundo plano.
#   ./reiniciar_escritorio.sh celular   -> sobe com o acesso pelo celular na rede local (--rede-local)
cd "$(dirname "$0")" || exit 1
EXTRA=""
[ "$1" = "celular" ] && EXTRA="--rede-local"
PORTA=$(python3 configuracao.py --porta 2>/dev/null || echo 8765)
echo "Encerrando o servidor antigo do escritório (porta $PORTA)..."
PIDS=$(lsof -ti tcp:"$PORTA" -sTCP:LISTEN 2>/dev/null)
if [ -n "$PIDS" ]; then kill $PIDS 2>/dev/null; echo "  processo(s) $PIDS encerrado(s)"; sleep 1; fi
echo "Subindo o escritório de novo..."
nohup python3 servidor.py --sem-navegador $EXTRA >/dev/null 2>&1 &
echo "Pronto: http://127.0.0.1:$PORTA/"
"""
ATALHOS = {"abrir_escritorio.bat": ATALHO_BAT, "abrir_escritorio.sh": ATALHO_SH,
           "reiniciar_escritorio.bat": REINICIAR_BAT, "reiniciar_escritorio.sh": REINICIAR_SH}


def escrever_atalhos(destino):
    feitos = []
    for nome, texto in ATALHOS.items():
        arq = Path(destino) / nome
        quebra = "\r\n" if nome.endswith(".bat") else "\n"
        with open(arq, "w", encoding="utf-8", newline=quebra) as f:
            f.write(texto)
        if nome.endswith(".sh"):
            arq.chmod(arq.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        feitos.append(arq)
    return feitos


def copiar_pacote(destino):
    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=True)
    copiados = 0
    for nome in PACOTE:
        origem = PASTA / nome
        if origem.is_file():
            (destino / nome).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(origem, destino / nome)
            copiados += 1
    if (PASTA / "vendor").is_dir() and not (destino / "vendor").exists():
        shutil.copytree(PASTA / "vendor", destino / "vendor")
    return copiados


def baixar_three(destino):
    erros = []
    for rel in ARQUIVOS_THREE:
        arq = Path(destino) / "vendor" / "three" / rel
        arq.parent.mkdir(parents=True, exist_ok=True)
        try:
            with urllib.request.urlopen(CDN_THREE + rel, timeout=60) as r:
                dados = r.read()
            if len(dados) < 1000:
                raise OSError("arquivo baixado vazio")
            arq.write_bytes(dados)
            print(f"  baixado: vendor/three/{rel} ({len(dados) // 1024} KB)")
        except Exception as e:
            erros.append(f"{rel}: {e}")
    return erros


def abrir_escritorio(destino):
    servidor = str(Path(destino) / "servidor.py")
    if WINDOWS:
        subprocess.Popen([sys.executable, servidor], cwd=str(destino), creationflags=subprocess.CREATE_NEW_CONSOLE)
    else:
        subprocess.Popen([sys.executable, servidor], cwd=str(destino), stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)


# ---------------------------------------------------------------- aplicação (comum aos dois modos)
def aplicar(plano, args, log=print):
    destino = Path(plano["destino"]).resolve()
    if destino != PASTA:
        n = copiar_pacote(destino)
        log(f"  {n} arquivos copiados para {destino}")
    cfg = configuracao.normalizar(plano["config"])
    arq_cfg = destino / "config.json"
    if arq_cfg.exists():
        b = backup(arq_cfg)
        log(f"  config.json anterior guardado em {b.name}")
    arq_cfg.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log(f"  gravado {arq_cfg}")
    (destino / "dados").mkdir(exist_ok=True)
    escrever_atalhos(destino)
    log(f"  atalhos: abrir_escritorio.{'bat' if WINDOWS else 'sh'} e reiniciar_escritorio.{'bat' if WINDOWS else 'sh'}")
    if plano.get("three_offline"):
        erros = baixar_three(destino)
        if erros:
            log("  ! não consegui baixar o three.js (o escritório continua usando o CDN): " + "; ".join(erros))
    for arq in arquivos_settings(plano["hook"], cfg["projetos"], args):
        copia, n = instalar_hook(arq, destino)
        if copia or n:
            log(f"  hook instalado em {arq} ({n} evento(s) novo(s))" + (f"; backup: {copia.name}" if copia else ""))
        else:
            log(f"  hook já estava instalado em {arq} (nada mudou)")
    return destino, cfg


# ---------------------------------------------------------------- modo interativo
def assistente(args):
    print()
    print("  ┌──────────────────────────────────────────────────────────┐")
    print("  │   Claude Office 3D — assistente de instalação            │")
    print("  │   Um escritório 3D que mostra seus agentes trabalhando.  │")
    print("  └──────────────────────────────────────────────────────────┘")
    print("  Enter aceita o valor entre colchetes. Ctrl+C cancela a qualquer momento (nada é gravado antes do fim).")

    titulo_passo(1, "Boas-vindas e checagens")
    amb = checar_ambiente()
    if not amb["claude"] and not sim_nao("  Claude Code não encontrado. Continuar mesmo assim?", True):
        raise Cancelado()

    titulo_passo(2, "Onde instalar")
    print(f"  Pasta atual do pacote: {PASTA}")
    destino = Path(perguntar("  Pasta de instalação", args.destino or str(PASTA))).expanduser().resolve()
    if destino != PASTA:
        print(f"  Os arquivos serão copiados para {destino}")

    titulo_passo(3, "Pastas de projeto a monitorar")
    print("  O hook só registra sessões do Claude Code abertas DENTRO destas pastas (e subpastas).")
    projetos = []
    sugestao = str(Path.cwd()) if Path.cwd().resolve() not in (PASTA, destino) else ""
    while True:
        rotulo = f"  Pasta {len(projetos) + 1}" + (" (Enter vazio = terminar)" if projetos else "")
        v = perguntar(rotulo, sugestao if not projetos else "",
                      lambda x: None if (not x and projetos) or (x and Path(x).expanduser().is_dir())
                      else "pasta não encontrada")
        if not v:
            break
        p = Path(v).expanduser().resolve().as_posix()
        if p not in projetos:
            projetos.append(p)
            print(f"    + {p}")
        sugestao = ""

    titulo_passo(4, "Agentes do time")
    encontrados = ler_agentes_md(projetos)
    opcoes = ["Time genérico (Líder, Dev, Designer, Pesquisa)"]
    if encontrados:
        opcoes.append(f"Importar {len(encontrados)} agente(s) de .claude/agents/*.md: "
                      + ", ".join(a["nome"] for a in encontrados[:5]) + ("…" if len(encontrados) > 5 else ""))
    opcoes.append("Digitar os agentes")
    i = escolher("  Escolha", opcoes, 1)
    if i == 0:
        agentes = completar_agentes(configuracao.AGENTES_PADRAO)
    elif encontrados and i == 1:
        lider = perguntar("  Nome do líder (sessão principal)", "Lider")
        lista = [{"nome": lider, "titulo": "Líder", "funcao": "Coordena o time", "lider": True,
                  "outros_nomes": ["main", "lead", "leader", "team-lead"]}]
        lista += [a for a in encontrados if configuracao.chave(a["nome"]) != configuracao.chave(lider)][:9]
        agentes = completar_agentes(lista)
    else:
        agentes = digitar_agentes()
    print("  Time:")
    mostrar_agentes(agentes)
    print("  (títulos, funções e cores podem ser ajustados depois no config.json)")

    titulo_passo(5, "GitHub (opcional): painel de PRs e Kanban")
    github = copy.deepcopy(configuracao.PADRAO["github"])
    if not amb["gh"]:
        print("  GitHub CLI (gh) não encontrado: você pode configurar agora e instalar o gh depois.")
    if sim_nao("  Configurar o GitHub?", bool(amb["gh"])):
        sug = next((r for r in (repo_do_git(p) for p in projetos) if r), "")
        github["repo"] = perguntar("  Repositório para o painel de PRs (owner/nome, vazio = sem PRs)", sug,
                                   lambda v: None if not v or re.fullmatch(r"[\w.-]+/[\w.-]+", v) else "use owner/nome")
        owner = perguntar("  Dono do GitHub Projects para o Kanban (vazio = sem Kanban)",
                          github["repo"].split("/")[0] if github["repo"] else "")
        if owner:
            projs = listar_projects(amb["gh"], owner) if amb["gh"] else None
            if projs:
                print(f"  Projects de {owner}:")
                ops = [f"#{p.get('number')} — {p.get('title')}" for p in projs] + ["nenhum (sem Kanban)"]
                k = escolher("  Qual quadro?", ops, 1)
                if k < len(projs):
                    github["projeto_owner"], github["projeto_numero"] = owner, int(projs[k]["number"])
            else:
                if amb["gh"]:
                    print("  (não consegui listar os projects — confira 'gh auth status' e o escopo 'project': "
                          "gh auth refresh -s project)")
                n = perguntar("  Número do project (0 = sem Kanban)", "0", lambda v: None if v.isdigit() else "número")
                if int(n):
                    github["projeto_owner"], github["projeto_numero"] = owner, int(n)
            if github["projeto_numero"]:
                github["campo_time"] = perguntar("  Campo do Projects que diz o time do cartão", "time")
                github["times"] = {a["titulo"]: a["nome"] for a in agentes if a["titulo"] != a["nome"]}
        if github["repo"]:
            print("  Status check que significa \"aprovado pela revisão\" (ex.: o nome de um job do CI).")
            github["check_revisao"] = perguntar("  Nome do check (vazio = usar a aprovação de review do GitHub)", "")

    titulo_passo(6, "Aparência e servidor")
    titulo = perguntar("  Título do escritório", "Claude Office 3D")
    tema = ("neutro", "sao-paulo")[escolher("  Tema", ["neutro (escritório genérico)",
                                                  "sao-paulo (maquete de SP, placas de rua, orelhão, ipês, coxinha…)"], 1)]
    apelidos = configuracao.MODOS_APELIDO[escolher("  Apelidos na tela (só diversão; os nomes reais seguem nos eventos)",
                                                   ["brasileiros (João, Maria…)", "cinema (Neo, Trinity…)", "desligado"], 3)]
    xp_ativo = sim_nao("  Ativar XP e níveis? (pontos por PR mergeado e skills; mostra o nível de cada agente na mesa)", True)
    porta = int(perguntar("  Porta do servidor local", "8765",
                          lambda v: None if v.isdigit() and 1024 <= int(v) <= 65535 else "porta entre 1024 e 65535"))
    if porta_ocupada(porta):
        print(f"  Aviso: a porta {porta} está em uso agora (talvez o escritório já esteja aberto). Tudo bem se for ele.")
    rede_local = sim_nao("  Permitir acesso pelo celular na rede local? (protegido por QR code; só redes privadas)", False)
    rede_https = sim_nao("  Usar HTTPS (recomendado)? (CA local gerada no seu PC; precisa instalar o certificado no celular uma vez)", True) if rede_local else True
    three_offline = sim_nao(f"  Baixar o three.js {configuracao.VERSAO_THREE} para vendor/ (funciona sem internet)?", False)

    titulo_passo(7, "Hook do Claude Code")
    print("  O hook chama o registrar_evento.py a cada ferramenta usada e quando um agente fica ocioso.")
    e = escolher("  Onde instalar o hook?", [
        f"usuário — {settings_usuario(args)} (vale para todas as sessões; o filtro de pastas do passo 3 se aplica)",
        "projeto — <projeto>/.claude/settings.local.json de cada pasta do passo 3",
        "não instalar agora (instalação manual, veja INSTALACAO.md)"], 1)
    hook = ("usuario", "projeto", "nenhum")[e]
    if hook != "nenhum":
        print("  Bloco que será ACRESCENTADO (os hooks que você já tem são mantidos; antes é feito um backup):")
        print("    " + json.dumps(bloco_hooks(destino), ensure_ascii=False, indent=2).replace("\n", "\n    "))

    config = {"porta": porta, "titulo": titulo, "projetos": projetos, "agentes": agentes, "github": github,
              "tema": tema, "apelidos": apelidos, "rede_local": rede_local, "rede_https": rede_https,
              "xp": {"ativo": xp_ativo, "desde": (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")}}
    print()
    print("=" * 64)
    print(" Resumo")
    print("=" * 64)
    print(f"  Pasta:      {destino}")
    print(f"  Projetos:   {', '.join(projetos)}")
    print(f"  Agentes:    {', '.join(a['nome'] for a in agentes)}")
    print(f"  GitHub:     PRs={github['repo'] or '—'}  Kanban="
          f"{(github['projeto_owner'] + ' #' + str(github['projeto_numero'])) if github['projeto_numero'] else '—'}"
          f"  check={github['check_revisao'] or '(review)'}")
    print(f"  Tema:       {tema}   apelidos: {apelidos}   porta: {porta}   three.js: {'local' if three_offline else 'CDN'}")
    print(f"  Celular:    {('LIGADO (rede local, ' + ('HTTPS' if rede_https else 'HTTP') + '; veja a seção Acesso pelo celular do INSTALACAO.md)') if rede_local else 'desligado (só neste PC)'}")
    print(f"  XP/níveis:  {'ativado (rode python xp.py para calcular; veja o INSTALACAO.md)' if xp_ativo else 'desligado'}")
    print("  Alertas:    ligados (botão 🔔 Alertas; Web Push no celular: veja a seção Alertas no celular do INSTALACAO.md)")
    alvos = arquivos_settings(hook, projetos, args)
    print(f"  Hook:       {', '.join(str(a) for a in alvos) if alvos else 'não instalar'}")
    if not sim_nao("  Gravar tudo isso agora?", True):
        raise Cancelado()
    print()
    destino, cfg = aplicar({"destino": destino, "config": config, "hook": hook, "three_offline": three_offline}, args)
    print()
    print("  Instalação concluída!")
    print(f"  Para abrir depois: {'abrir_escritorio.bat (duplo clique)' if WINDOWS else './abrir_escritorio.sh'}"
          f" em {destino}  →  http://127.0.0.1:{cfg['porta']}/")
    if cfg.get("rede_local"):
        print("  Acesso pelo celular: se o Firewall do Windows perguntar ao abrir, marque SÓ \"Redes privadas\"; depois use o botão"
              " 📱 Celular da página (no PC) para ver o QR code.")
        if WINDOWS:   # só mostra: o instalador nunca altera o Firewall
            portas = f"{cfg['porta'] + 1},{cfg['porta'] + 2}" if cfg.get("rede_https", True) else str(cfg["porta"])
            print("  Se o celular não abrir o link (tempo esgotado), crie a regra de entrada UMA vez, no PowerShell como Administrador:")
            print(f'    New-NetFirewallRule -DisplayName "Claude Office 3D (celular)" -Direction Inbound -Program "{sys.executable}"'
                  f" -Protocol TCP -LocalPort {portas} -Profile Private -Action Allow")
            print("  (confira também: celular e PC na mesma sub-rede e a rede do Windows como Privada; detalhes no INSTALACAO.md,"
                  " seção Acesso pelo celular > Não abre no celular?)")
    if hook != "nenhum":
        print("  Sessões do Claude Code já abertas precisam ser reiniciadas para carregar o hook.")
    if not args.sem_abrir and sim_nao("  Abrir o escritório agora?", True):
        abrir_escritorio(destino)


# ---------------------------------------------------------------- modo silencioso e desinstalação
def silencioso(args):
    if not args.config:
        print("--sem-perguntas precisa de --config arquivo.json")
        return 2
    dados = json.loads(Path(args.config).read_text(encoding="utf-8-sig"))
    inst = dados.pop("instalacao", {}) if isinstance(dados, dict) else {}
    plano = {
        "destino": args.destino or inst.get("destino") or str(PASTA),
        "config": dados,
        "hook": args.hook or inst.get("hook") or "usuario",
        "three_offline": bool(inst.get("three_offline")),
    }
    if plano["hook"] not in ("usuario", "projeto", "nenhum"):
        print("hook deve ser usuario, projeto ou nenhum")
        return 2
    for p in configuracao.normalizar(dados)["projetos"]:
        if not Path(p).is_dir():
            print(f"Aviso: pasta de projeto não encontrada: {p}")
    print("Claude Office 3D — instalação silenciosa")
    destino, cfg = aplicar(plano, args)
    print(f"Pronto. Abra com abrir_escritorio.{'bat' if WINDOWS else 'sh'} → http://127.0.0.1:{cfg['porta']}/")
    if inst.get("abrir") and not args.sem_abrir:
        abrir_escritorio(destino)
    return 0


def desinstalar(args):
    destino = Path(args.destino).resolve() if args.destino else PASTA
    cfg = configuracao.carregar(destino / "config.json")
    alvos = [settings_usuario(args)] + [Path(p) / ".claude" / "settings.local.json" for p in cfg["projetos"]]
    print("Claude Office 3D — desinstalação dos hooks")
    print(f"  Remove só os hooks que chamam {(destino / 'registrar_evento.py').as_posix()} de:")
    for a in alvos:
        print(f"    {a}{'' if a.exists() else '  (não existe)'}")
    if not args.sem_perguntas and not sim_nao("  Continuar?", True):
        raise Cancelado()
    total = 0
    for a in alvos:
        copia, n = desinstalar_hook(a, destino)
        total += n
        if n:
            print(f"  {n} hook(s) removido(s) de {a} (backup: {copia.name})")
    if not total:
        print("  Nenhum hook deste escritório encontrado.")
    print("  config.json, dados/ e os arquivos do escritório foram mantidos (apague a pasta se quiser remover tudo).")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Assistente de instalação do Claude Office 3D")
    ap.add_argument("--sem-perguntas", action="store_true", help="instalação silenciosa (exige --config)")
    ap.add_argument("--config", help="arquivo JSON com a configuração (modo silencioso)")
    ap.add_argument("--desinstalar", action="store_true", help="remove os hooks deste escritório")
    ap.add_argument("--settings-usuario", help="settings.json do usuário a usar (padrão ~/.claude/settings.json)")
    ap.add_argument("--destino", help="pasta de instalação")
    ap.add_argument("--hook", choices=["usuario", "projeto", "nenhum"], help="escopo do hook (modo silencioso)")
    ap.add_argument("--sem-abrir", action="store_true", help="não abre o escritório no final")
    args = ap.parse_args()
    try:
        if args.desinstalar:
            return desinstalar(args)
        if args.sem_perguntas:
            return silencioso(args)
        assistente(args)
        return 0
    except Cancelado:
        print("\n  Cancelado. Nada foi gravado.")
        return 1
    except (OSError, ValueError) as e:
        print(f"\n  Erro: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
