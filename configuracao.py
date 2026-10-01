"""Configuração do Claude Office 3D (somente biblioteca padrão).

Lida por servidor.py, registrar_evento.py e instalar.py. O arquivo é config.json, na mesma pasta deste
script (ou o caminho da variável de ambiente OFFICE_CONFIG). Toda chave ausente recebe o valor padrão.

Uso direto:  python configuracao.py --porta   -> imprime a porta configurada (usado pelos scripts .bat/.sh)
             python configuracao.py --mostrar -> imprime a configuração completa já normalizada
"""
import copy
import json
import os
import shutil
import sys
from pathlib import Path

PASTA = Path(__file__).resolve().parent
VERSAO_THREE = "0.160.0"
TEMAS = ("sao-paulo", "neutro")
MODOS_APELIDO = ("brasileiros", "cinema", "desligado")
TIPOS_MESA = ("lider", "dev", "design", "pesquisa", "padrao")
PALETA = ["#e5484d", "#3b82f6", "#f59e0b", "#22c55e", "#a855f7", "#14b8a6", "#ec4899", "#84cc16", "#06b6d4", "#f97316"]
APELIDOS_BR = ["Lia", "João", "Maria", "Aquiles", "Ana", "Bruno", "Carla", "Diego", "Fernanda", "Gabriel"]
APELIDOS_CINEMA = ["Morpheus", "Neo", "Trinity", "Indiana", "Yoda", "Leia", "Ripley", "Marty", "Gandalf", "Hermione"]

# Time genérico usado quando o usuário não define o seu. O PRIMEIRO agente é o líder: a sessão principal do
# Claude Code (sem nome de colega) aparece na mesa dele.
AGENTES_PADRAO = [
    {"nome": "Lider", "titulo": "Líder", "funcao": "Coordena o time e revisa", "cor": "#e5484d",
     "apelido_br": "Lia", "apelido_cinema": "Morpheus", "cargo": "", "mesa": "lider", "lider": True,
     "outros_nomes": ["main", "lead", "leader", "team-lead", "team_lead", "lider", "líder"]},
    {"nome": "Dev", "titulo": "Dev", "funcao": "Código e testes", "cor": "#3b82f6",
     "apelido_br": "João", "apelido_cinema": "Neo", "cargo": "", "mesa": "dev",
     "outros_nomes": ["developer", "desenvolvedor", "coder"]},
    {"nome": "Designer", "titulo": "Designer", "funcao": "Interface e modelagem", "cor": "#f59e0b",
     "apelido_br": "Maria", "apelido_cinema": "Trinity", "cargo": "", "mesa": "design",
     "outros_nomes": ["design", "modelagem", "modeler", "modelador"]},
    {"nome": "Pesquisa", "titulo": "Pesquisa", "funcao": "Busca e documentação", "cor": "#22c55e",
     "apelido_br": "Aquiles", "apelido_cinema": "Indiana", "cargo": "", "mesa": "pesquisa",
     "outros_nomes": ["researcher", "research", "pesquisador", "pesquisadora"]},
]

PADRAO = {
    "porta": 8765,
    "titulo": "Claude Office 3D",
    "projetos": [],
    "agentes": AGENTES_PADRAO,
    "github": {
        "repo": "",                 # owner/nome — painel de PRs
        "projeto_owner": "",        # dono do GitHub Projects (usuário ou organização) — Kanban
        "projeto_numero": 0,        # número do project (aparece na URL .../projects/<n>)
        "check_revisao": "",        # status check que significa "aprovado pela revisão"; vazio = aprovação de review
        "campo_time": "time",       # campo do Projects que diz qual time/agente cuida do cartão
        "campo_prioridade": "prioridade",
        "times": {},                # valor do campo_time (ou rótulo do PR) -> nome do agente
        "colunas": [],              # ordem das colunas do Kanban; vazio = na ordem em que aparecem
    },
    "tema": "neutro",
    "apelidos": "desligado",
    # SendMessage cujo resumo/mensagem contém uma destas palavras vira reunião (todos vão para a sala)
    "palavras_reuniao": ["reunião", "reuniao", "alinhamento", "daily", "stand-up", "standup", "meeting",
                         "planejamento da sprint", "todos na sala", "retrospectiva"],
}


def lider(cfg):
    """Agente líder (marcado "lider": true; senão o primeiro). A sessão principal aparece na mesa dele."""
    return next((a for a in cfg["agentes"] if a.get("lider")), cfg["agentes"][0] if cfg["agentes"] else None)


def caminho_config():
    return Path(os.environ.get("OFFICE_CONFIG") or (PASTA / "config.json"))


def chave(nome):
    """Forma comparável de um nome de agente: minúsculas, '-' e espaço viram '_'."""
    return str(nome or "").strip().lower().replace("-", "_").replace(" ", "_")


def normalizar_agente(ag, i):
    if isinstance(ag, str):
        ag = {"nome": ag}
    ag = dict(ag or {})
    nome = str(ag.get("nome") or f"Agente_{i + 1}").strip()
    cor = str(ag.get("cor") or PALETA[i % len(PALETA)]).strip()
    if not cor.startswith("#"):
        cor = "#" + cor
    mesa = str(ag.get("mesa") or ("lider" if i == 0 else "padrao")).strip().lower()
    outros = ag.get("outros_nomes") or []
    if isinstance(outros, str):
        outros = [outros]
    return {
        "nome": nome,
        "titulo": str(ag.get("titulo") or nome.replace("_", " ")),
        "funcao": str(ag.get("funcao") or ""),
        "cor": cor,
        "apelido_br": str(ag.get("apelido_br") or APELIDOS_BR[i % len(APELIDOS_BR)]),
        "apelido_cinema": str(ag.get("apelido_cinema") or APELIDOS_CINEMA[i % len(APELIDOS_CINEMA)]),
        "cargo": str(ag.get("cargo") or ""),
        "mesa": mesa if mesa in TIPOS_MESA else "padrao",
        "outros_nomes": [str(o) for o in outros if str(o).strip()],
        "lider": bool(ag.get("lider")),        # sessão principal; convoca reuniões
        "auxiliar": bool(ag.get("auxiliar")),  # não vai às reuniões
    }


def normalizar(cfg):
    """Mescla com os padrões e corrige tipos; nunca levanta exceção por valor ruim."""
    base = copy.deepcopy(PADRAO)
    cfg = cfg if isinstance(cfg, dict) else {}
    for k in ("titulo", "tema", "apelidos"):
        if cfg.get(k):
            base[k] = str(cfg[k])
    try:
        base["porta"] = int(cfg.get("porta", base["porta"]))
    except (TypeError, ValueError):
        pass
    if not 1 <= base["porta"] <= 65535:
        base["porta"] = PADRAO["porta"]
    projetos = cfg.get("projetos") or []
    if isinstance(projetos, str):
        projetos = [projetos]
    base["projetos"] = [str(p) for p in projetos if str(p).strip()]
    agentes = cfg.get("agentes") or AGENTES_PADRAO
    base["agentes"] = [normalizar_agente(a, i) for i, a in enumerate(agentes)]
    if base["agentes"] and not any(a["lider"] for a in base["agentes"]):
        base["agentes"][0]["lider"] = True   # sem líder marcado: o primeiro da lista
    palavras = cfg.get("palavras_reuniao")
    if isinstance(palavras, list):
        base["palavras_reuniao"] = [str(x).strip().lower() for x in palavras if str(x).strip()]
    gh = cfg.get("github") if isinstance(cfg.get("github"), dict) else {}
    for k, v in gh.items():
        if k in base["github"]:
            base["github"][k] = v
    try:
        base["github"]["projeto_numero"] = int(base["github"]["projeto_numero"] or 0)
    except (TypeError, ValueError):
        base["github"]["projeto_numero"] = 0
    if not isinstance(base["github"]["times"], dict):
        base["github"]["times"] = {}
    if not isinstance(base["github"]["colunas"], list):
        base["github"]["colunas"] = []
    if base["tema"] not in TEMAS:
        base["tema"] = "neutro"
    if base["apelidos"] not in MODOS_APELIDO:
        base["apelidos"] = "desligado"
    return base


def carregar(caminho=None):
    """Lê o config.json (ou o caminho dado). Arquivo ausente ou inválido = configuração padrão."""
    arq = Path(caminho) if caminho else caminho_config()
    try:
        dados = json.loads(arq.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        dados = {}
    return normalizar(dados)


def localizar_gh():
    """GitHub CLI pelo PATH; senão, os caminhos de instalação padrão. None se não houver."""
    achado = shutil.which("gh")
    if achado:
        return achado
    candidatos = [
        r"C:\Program Files\GitHub CLI\gh.exe",
        r"C:\Program Files (x86)\GitHub CLI\gh.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\GitHub CLI\gh.exe"),
        "/opt/homebrew/bin/gh", "/usr/local/bin/gh", "/usr/bin/gh",
    ]
    for c in candidatos:
        if c and Path(c).is_file():
            return c
    return None


def pasta_dentro(cwd, pastas):
    """True se cwd é uma das pastas ou está dentro de alguma (sem diferenciar maiúsculas; '\\' = '/')."""
    c = str(cwd or "").replace("\\", "/").rstrip("/").casefold()
    if not c:
        return False
    for p in pastas:
        p = str(p).replace("\\", "/").rstrip("/").casefold()
        if p and (c == p or c.startswith(p + "/")):
            return True
    return False


if __name__ == "__main__":
    cfg = carregar()
    if "--porta" in sys.argv:
        print(cfg["porta"])
    else:
        print(json.dumps(cfg, ensure_ascii=False, indent=2))
