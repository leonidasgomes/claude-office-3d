"""Configuração do Claude Office 3D (somente biblioteca padrão).

Lida por servidor.py, registrar_evento.py e instalar.py. O arquivo é config.json, na mesma pasta deste
script (ou o caminho da variável de ambiente OFFICE_CONFIG). Toda chave ausente recebe o valor padrão.

Uso direto:  python configuracao.py --porta   -> imprime a porta configurada (usado pelos scripts .bat/.sh)
             python configuracao.py --mostrar -> imprime a configuração completa já normalizada
"""
import copy
import json
import os
import re
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

# XP e níveis (opcional, "xp.ativo"): pontos por resultado verificado dos PRs mergeados; ver INSTALACAO.md.
XP_PESOS = {
    "aprovado_de_primeira": 3,      # nenhum commit do PR reprovado pela revisão (check_revisao ou review)
    "sem_conflito_com_testes": 2,   # sem merge da base no meio do PR e o corpo cita teste/validação
    "cartao_fechado": 2,            # o cartão do Kanban atribuído está na coluna final
    "bug_nao_voltou_14d": 2,        # PR de fix sem novo fix/revert citando-o em 14 dias
    "retrabalho": -2,               # reprovado pela revisão ou fix posterior citando o PR em até 14 dias
    "regressao": -3,                # PR posterior de revert/regress citando o PR
    "skill_reusada_por_outro": 5,   # outro agente usou uma skill de que o agente é autor
    "skill_promovida": 3,           # skill candidata do agente foi promovida
}
XP_NIVEIS = [{"nivel": 1, "titulo": "Estagiário", "xp": 0}, {"nivel": 2, "titulo": "Júnior", "xp": 20},
             {"nivel": 3, "titulo": "Pleno", "xp": 60}, {"nivel": 4, "titulo": "Sênior", "xp": 150},
             {"nivel": 5, "titulo": "Mestre", "xp": 300}]
# expressões regulares (sem diferenciar maiúsculas) que reconhecem ARQUIVO DE TESTE pelo caminho
XP_PADROES_TESTE = [r"(^|/)(tests?|testes|specs?|__tests__|e2e)/", r"(^|/)test_[^/]*$",
                    r"_tests?\.[a-z]+$", r"\.(test|spec)\.[a-z]+$", r"(^|/)[^/]*tests?\.(cpp|h|cs)$"]
# arquivos de AVALIAÇÃO (evals, notas, benchmarks): qualquer mudança neles zera os pontos do PR e abre auditoria
XP_PADROES_AVALIACAO = [r"(^|/)evals?/", r"(^|/)[^/]*evals?\.json$", r"(^|[/_.\-])grading([/_.\-]|$)",
                        r"(^|/)benchmark\.json$"]
XP_AMOSTRA_1_EM = 10   # 1 em cada N PRs vai para conferência humana mesmo sem suspeita (0 = desliga)
# prefixo de branch -> mesas cujo agente recebe o PR (usado quando "xp.atribuicao.prefixos_branch" não existe)
XP_PREFIXOS_POR_MESA = {"pesquisa": ["research/", "docs/", "estudo/"], "design": ["design/", "ui/"]}

# Alertas (notificação/push quando algo espera por você): cada tipo liga/desliga; "conferir" vem desligado
ALERTAS_TIPOS = {"pr_pronto": True, "pr_problema": True, "auditoria": True, "conferir": False, "escalonamento": True,
                 "pergunta": True, "lembrete": True, "sugestao": True}

# Sugestões do bot de revisão (sugestoes_bot.py): só funciona com github.repo e github.bots_revisao preenchidos
SUGESTOES_MODELO = "claude-haiku-4-5-20251001"   # triagem barata (uma chamada de `claude -p` por coleta com itens novos)

# Revisor de código próprio (revisor_ia.py): uma chamada de `claude -p` por commit novo de PR; comenta com a marca [revisor-ia]
REVISOR_MODELO = "claude-sonnet-5-5"
REVISOR_MAX_DIFF = 90_000   # caracteres de diff por revisão (o resto é listado como não revisado)

# Auditor do "para conferir" (auditor_xp.py): o modelo barato julga cada amarelo do Placar; só o suspeito vai ao segundo
AUDITOR_MODELO = "claude-haiku-4-5-20251001"
AUDITOR_MODELO_2 = "claude-sonnet-5-5"
AUDITOR_MAX_DIFF = 40_000

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
        "bots_revisao": [],         # logins dos bots de revisão (ex.: "chatgpt-codex-connector[bot]"); vazio = sugestões desligadas
        "campo_time": "time",       # campo do Projects que diz qual time/agente cuida do cartão
        "campo_prioridade": "prioridade",
        "times": {},                # valor do campo_time (ou rótulo do PR) -> nome do agente
        "colunas": [],              # ordem das colunas do Kanban; vazio = na ordem em que aparecem
    },
    "xp": {"ativo": False, "desde": "", "pesos": XP_PESOS, "niveis": XP_NIVEIS, "padroes_teste": XP_PADROES_TESTE,
           "padroes_avaliacao": XP_PADROES_AVALIACAO, "amostra_1_em": XP_AMOSTRA_1_EM,
           "atribuicao": {"prefixos_branch": {}, "padrao": ""}},
    "sugestoes": {"triagem_modelo": SUGESTOES_MODELO,   # "" desliga a triagem (o líder tria sozinho)
                  "intervalo_min": 15,                   # de quanto em quanto tempo o servidor coleta
                  "janela_dias": 3},                     # na 1ª coleta, quanto do passado olhar
    "revisor": {"ativo": False,                          # True: o servidor revisa os PRs pendentes antes de cada coleta
                "modelo": REVISOR_MODELO,
                "max_diff": REVISOR_MAX_DIFF,
                "contexto": []},                         # arquivos de padrões/lições/glossário (absolutos ou relativos a "projetos")
    "auditor": {"ativo": False,                          # True (e xp.ativo): o servidor audita os amarelos a cada coleta
                "modelo": AUDITOR_MODELO,                # primeira opinião (barata)
                "modelo_2": AUDITOR_MODELO_2,            # segunda opinião, só quando o primeiro acha suspeito
                "max_diff": AUDITOR_MAX_DIFF,
                "rotulos": []},                          # rótulos extras da issue aberta na suspeita (ex.: ["P2"])
    "vigia": {"intervalo_min": 15,                     # vigia_lider.py: de quanto em quanto tempo roda os comandos
              "sugestoes": True,                      # inclui `sugestoes_bot.py --pendentes` (com bots configurados)
              "comandos": []},                        # extras: [{"rotulo", "comando" (texto, roda no shell), "acao"}]
    "alertas": {"ativo": True, "tipos": ALERTAS_TIPOS, "lembrete_horas": 24, "limite_push_hora": 20, "toast_windows": False,
                "contato": "", "escalonamentos": "", "agentes_pergunta": []},
    "tema": "neutro",
    "apelidos": "desligado",
    "rede_local": False,        # True: escuta na rede local para o celular (QR code + sessão pareada); False: só 127.0.0.1
    "rede_https": True,         # com rede_local: HTTPS com CA própria (porta+1) e certificado público em porta+2
    "rede_tailscale": False,    # com rede_local: aceita também a faixa 100.64.0.0/10 do Tailscale (entra na CA)
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
        "sala": "diretoria" if str(ag.get("sala") or "").strip().lower() == "diretoria" else "",   # "diretoria": sala fechada própria
        "rotulo_issue": str(ag.get("rotulo_issue") or "").strip(),   # rótulo das issues abertas para este agente (auditor_xp.py)
        "time_kanban": str(ag.get("time_kanban") or "").strip(),     # valor do github.campo_time do cartão deste agente
    }


def _agente_canonico(agentes, nome):
    """Nome canônico do agente configurado que corresponde a 'nome' (por nome ou outros_nomes), ou ''."""
    k = chave(nome)
    for a in agentes:
        if chave(a["nome"]) == k or any(chave(o) == k for o in a["outros_nomes"]):
            return a["nome"]
    return ""


def normalizar_xp(bruto, agentes):
    """Bloco "xp" do config: tipos corrigidos, padrões sensatos, atribuição só para agentes que existem."""
    bruto = bruto if isinstance(bruto, dict) else {}
    xp = copy.deepcopy(PADRAO["xp"])
    xp["ativo"] = bool(bruto.get("ativo", xp["ativo"]))
    desde = str(bruto.get("desde") or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", desde):
        xp["desde"] = desde
    pesos = bruto.get("pesos")
    if isinstance(pesos, dict):
        for k in XP_PESOS:
            try:
                xp["pesos"][k] = int(pesos[k]) if k in pesos else XP_PESOS[k]
            except (TypeError, ValueError):
                pass
    niveis = []
    for n in bruto.get("niveis") or []:
        try:
            niveis.append({"nivel": int(n["nivel"]), "titulo": str(n["titulo"]), "xp": int(n["xp"])})
        except (TypeError, ValueError, KeyError):
            niveis = []
            break
    niveis.sort(key=lambda n: n["xp"])
    if niveis and niveis[0]["xp"] == 0 and len({n["nivel"] for n in niveis}) == len(niveis):
        xp["niveis"] = niveis
    padroes = []
    for p in bruto.get("padroes_teste") or []:
        try:
            re.compile(str(p))
            padroes.append(str(p))
        except re.error:
            pass
    if padroes:
        xp["padroes_teste"] = padroes
    aval = []
    for p in bruto.get("padroes_avaliacao") or []:
        try:
            re.compile(str(p))
            aval.append(str(p))
        except re.error:
            pass
    if aval:
        xp["padroes_avaliacao"] = aval
    try:
        xp["amostra_1_em"] = max(0, int(bruto["amostra_1_em"])) if "amostra_1_em" in bruto else XP_AMOSTRA_1_EM
    except (TypeError, ValueError):
        pass
    atrib = bruto.get("atribuicao") if isinstance(bruto.get("atribuicao"), dict) else {}
    if "prefixos_branch" in atrib and isinstance(atrib["prefixos_branch"], dict):
        brutos = atrib["prefixos_branch"].items()
    else:   # padrão: pelas mesas dos agentes (pesquisa, design)
        brutos = [(pref, a["nome"]) for a in agentes for pref in XP_PREFIXOS_POR_MESA.get(a["mesa"], [])]
    prefixos = {}
    for pref, ag in brutos:
        nome = _agente_canonico(agentes, ag)
        if nome and str(pref).strip():
            prefixos.setdefault(str(pref).strip().lower(), nome)
    padrao = _agente_canonico(agentes, atrib.get("padrao"))
    if not padrao:   # sem padrão: o agente da mesa "dev"; senão o líder
        padrao = next((a["nome"] for a in agentes if a["mesa"] == "dev"), "") or             next((a["nome"] for a in agentes if a["lider"]), "")
    xp["atribuicao"] = {"prefixos_branch": prefixos, "padrao": padrao}
    return xp


def normalizar_sugestoes(bruto):
    """Bloco "sugestoes" do config: modelo da triagem ("" desliga), intervalo em minutos e janela inicial em dias."""
    bruto = bruto if isinstance(bruto, dict) else {}
    s = copy.deepcopy(PADRAO["sugestoes"])
    if isinstance(bruto.get("triagem_modelo"), str):
        s["triagem_modelo"] = bruto["triagem_modelo"].strip()[:80]
    for k, minimo, maximo in (("intervalo_min", 1, 1440), ("janela_dias", 1, 30)):
        try:
            s[k] = max(minimo, min(maximo, int(bruto[k]))) if k in bruto else s[k]
        except (TypeError, ValueError):
            pass
    return s


def normalizar_vigia(bruto):
    """Bloco "vigia" do config (vigia_lider.py): intervalo em minutos (5 a 240), sugestões ligadas por padrão e comandos
    extras do projeto, cada um com rótulo, comando de shell e a ação que o líder faz quando o comando tiver saída."""
    bruto = bruto if isinstance(bruto, dict) else {}
    v = copy.deepcopy(PADRAO["vigia"])
    try:
        v["intervalo_min"] = max(5, min(240, int(bruto["intervalo_min"]))) if "intervalo_min" in bruto else v["intervalo_min"]
    except (TypeError, ValueError):
        pass
    v["sugestoes"] = bruto.get("sugestoes") is not False
    for i, c in enumerate(bruto.get("comandos") or []):
        if isinstance(c, dict) and isinstance(c.get("comando"), str) and c["comando"].strip():
            v["comandos"].append({"rotulo": str(c.get("rotulo") or f"comando{i + 1}").strip()[:30],
                                  "comando": c["comando"].strip()[:500],
                                  "acao": str(c.get("acao") or "veja a saída").strip()[:200]})
    return v


def normalizar_revisor(bruto):
    """Bloco "revisor" do config: ligado só com true explícito, modelo (vazio = padrão), limite do diff e lista de
    arquivos de contexto (texto; caminho absoluto ou relativo a cada pasta de "projetos")."""
    bruto = bruto if isinstance(bruto, dict) else {}
    r = copy.deepcopy(PADRAO["revisor"])
    r["ativo"] = bruto.get("ativo") is True
    if isinstance(bruto.get("modelo"), str) and bruto["modelo"].strip():
        r["modelo"] = bruto["modelo"].strip()[:80]
    try:
        r["max_diff"] = max(5_000, min(400_000, int(bruto["max_diff"]))) if "max_diff" in bruto else r["max_diff"]
    except (TypeError, ValueError):
        pass
    contexto = bruto.get("contexto") or []
    if isinstance(contexto, str):
        contexto = [contexto]
    if isinstance(contexto, list):
        r["contexto"] = [str(x).strip() for x in contexto if isinstance(x, str) and x.strip()]
    return r


def normalizar_auditor(bruto):
    """Bloco "auditor" do config (auditor_xp.py): ligado só com true explícito, modelos (vazio = padrão), limite do diff
    e rótulos extras da issue de suspeita."""
    bruto = bruto if isinstance(bruto, dict) else {}
    a = copy.deepcopy(PADRAO["auditor"])
    a["ativo"] = bruto.get("ativo") is True
    for k in ("modelo", "modelo_2"):
        if isinstance(bruto.get(k), str) and bruto[k].strip():
            a[k] = bruto[k].strip()[:80]
    try:
        a["max_diff"] = max(5_000, min(400_000, int(bruto["max_diff"]))) if "max_diff" in bruto else a["max_diff"]
    except (TypeError, ValueError):
        pass
    rotulos = bruto.get("rotulos") or []
    if isinstance(rotulos, str):
        rotulos = [rotulos]
    if isinstance(rotulos, list):
        a["rotulos"] = [str(x).strip()[:50] for x in rotulos if isinstance(x, str) and x.strip()]
    return a


def normalizar_alertas(bruto):
    """Bloco "alertas" do config: tipos corrigidos e padrões sensatos (a validação final é do alertas.py)."""
    bruto = bruto if isinstance(bruto, dict) else {}
    a = copy.deepcopy(PADRAO["alertas"])
    a["ativo"] = bruto.get("ativo") is not False
    a["toast_windows"] = bruto.get("toast_windows") is True
    for k, minimo, maximo in (("lembrete_horas", 1, 24 * 14), ("limite_push_hora", 1, 200)):
        try:
            a[k] = max(minimo, min(maximo, int(bruto[k]))) if k in bruto else a[k]
        except (TypeError, ValueError):
            pass
    if isinstance(bruto.get("tipos"), dict):
        for k in ALERTAS_TIPOS:
            if k in bruto["tipos"]:
                a["tipos"][k] = bruto["tipos"][k] is True
    for k in ("contato", "escalonamentos"):
        if isinstance(bruto.get(k), str):
            a[k] = bruto[k].strip()[:300]
    if isinstance(bruto.get("agentes_pergunta"), list):
        a["agentes_pergunta"] = [str(x).strip() for x in bruto["agentes_pergunta"] if str(x).strip()]
    return a


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
    base["rede_local"] = cfg.get("rede_local") is True
    base["rede_https"] = cfg.get("rede_https") is not False
    base["rede_tailscale"] = cfg.get("rede_tailscale") is True
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
    bots = base["github"]["bots_revisao"]
    base["github"]["bots_revisao"] = [str(b).strip() for b in bots if str(b).strip()] if isinstance(bots, list) else []
    base["github"]["repo"] = str(base["github"]["repo"] or "").strip()
    if not isinstance(base["github"]["colunas"], list):
        base["github"]["colunas"] = []
    base["xp"] = normalizar_xp(cfg.get("xp"), base["agentes"])
    base["alertas"] = normalizar_alertas(cfg.get("alertas"))
    base["sugestoes"] = normalizar_sugestoes(cfg.get("sugestoes"))
    base["revisor"] = normalizar_revisor(cfg.get("revisor"))
    base["auditor"] = normalizar_auditor(cfg.get("auditor"))
    base["vigia"] = normalizar_vigia(cfg.get("vigia"))
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
