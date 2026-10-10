"""Política de gestão por projeto; carregar nunca altera GitHub nem consoles.

A fonte é <projeto>/.office/projeto.json. Projetos legados permanecem
desativados até adoção explícita; dados inválidos nunca habilitam automação.
"""
import copy
import hashlib
import json
from pathlib import Path

CONSOLES = ("claude", "codex", "opencode", "gemini")
PADRAO = {
    "versao": 1,
    "ativo": False,
    "fontes": {"regras": "CLAUDE.md", "produto": "PRODUTO.md",
               "arquitetura": "docs/ARCHITECTURE_GRAPH.yaml", "skills": ".claude/skills"},
    "merge": {"modo": "manual", "checks": [], "rotulos_manuais": ["merge-manual"]},
    "ceo": {"console": "claude", "modelo": "", "execucao": "cloud", "autonomia": "limites_aprovados"},
    "diretor": {"console": "claude", "modelo": "", "execucao": "cloud"},
    "equipes": [],
    "rotas": {},
    "sugestoes": {"ativo": False, "bots": [], "triagem": False},
    "auditor": {"ativo": False, "max_diff": 60000, "max_prs": 3},
    "revisao": {"ativo": False, "clouds_distintas": 2, "separar_autor": True, "revisores": []},
    "kanban": {"repo": "", "owner": "", "numero": 0, "tipo_owner": "users",
               "campo_status": "Status", "campo_time": "Time",
               "campo_prioridade": "Prioridade", "campo_etapa": "Etapa GDD", "prioridades": [],
               "backlog": "Backlog", "andamento": "Em andamento",
               "revisao": "Em revisão", "feito": "Feito"},
    "local": {"ativo": False, "team": False, "max_paralelo": 1,
              "ram_livre_min_gb": 8, "bloquear_pesados": True, "cpu_uso_max_pct": 75,
              "ollama_memoria_max_gb": 4, "vram_livre_min_gb": 2, "gpu_uso_max_pct": 75},
}


def _objeto(valor, nome):
    if not isinstance(valor, dict):
        raise ValueError(f"{nome}: esperado objeto")
    return valor


def _mesclar(base, dados, prefixo=""):
    _objeto(dados, prefixo or "projeto")
    resultado = copy.deepcopy(base)
    for chave, valor in dados.items():
        nome = f"{prefixo}.{chave}" if prefixo else chave
        if chave in ("cloud", "sandbox") and prefixo in ("ceo", "diretor"):
            resultado[chave] = copy.deepcopy(valor)
            continue
        if chave not in base:
            raise ValueError(f"Configuração desconhecida: {nome}")
        resultado[chave] = (_mesclar(base[chave], valor, nome)
                            if isinstance(base[chave], dict) and base[chave]
                            else copy.deepcopy(valor))
    return resultado


def _executor(valor, nome):
    _objeto(valor, nome)
    permitidas = {"console", "modelo", "execucao", "cloud", "sandbox"}
    if nome == "ceo":
        permitidas.add("autonomia")
    if set(valor) - permitidas:
        raise ValueError(f"{nome}: campos desconhecidos")
    if valor.get("console") not in CONSOLES:
        raise ValueError(f"{nome}: console desconhecido")
    if not isinstance(valor.get("modelo", ""), str):
        raise ValueError(f"{nome}: modelo deve ser texto")
    if valor.get("execucao", "cloud") not in ("cloud", "local"):
        raise ValueError(f"{nome}: execução deve ser cloud ou local")
    if "cloud" in valor and (not isinstance(valor["cloud"], str) or not valor["cloud"].strip()):
        raise ValueError(f"{nome}: cloud deve identificar o fornecedor real do modelo")
    if 'sandbox' in valor:
        if (valor['console']!='codex' or valor.get('execucao','cloud')!='cloud'
            or valor['sandbox'] not in ('read-only','workspace-write')):
            raise ValueError(f'{nome}: sandbox exige Codex cloud e read-only ou workspace-write')
        if nome.startswith('revisor ') and valor['sandbox']!='read-only':
            raise ValueError('Revisores Codex exigem sandbox read-only')


def validar(dados):
    cfg = _mesclar(PADRAO, dados)
    s=cfg['sugestoes']
    if type(s['triagem']) is not bool:raise ValueError('Sugestões: triagem deve ser booleana')
    if s['triagem'] and (not s['ativo'] or cfg['diretor'].get('execucao','cloud')!='cloud'):
        raise ValueError('Triagem exige sugestões ativas e diretor cloud')
    if type(s['ativo']) is not bool or not isinstance(s['bots'],list):raise ValueError('Sugestões exigem ativo booleano e lista de bots')
    if (len(s['bots'])>30 or any(not isinstance(b,str) or not b.strip() or b!=b.strip() or len(b)>100 for b in s['bots'])
        or len({b.casefold() for b in s['bots']})!=len(s['bots']) or (s['ativo'] and not s['bots'])):
        raise ValueError('Configure logins explícitos e únicos dos bots para habilitar sugestões')
    if type(cfg["versao"]) is not int or cfg["versao"] != 1:
        raise ValueError("Versão de política não suportada")
    for valor in (cfg["ativo"], cfg["local"]["ativo"], cfg["local"]["team"],
                  cfg["local"]["bloquear_pesados"]):
        if type(valor) is not bool:
            raise ValueError("Flags de gestão devem ser booleanas")
    merge = cfg["merge"]
    if merge["modo"] not in ("manual", "automatico"):
        raise ValueError("Modo de merge inválido")
    for chave in ("checks", "rotulos_manuais"):
        if not isinstance(merge[chave], list) or any(
                not isinstance(x, str) or not x.strip() for x in merge[chave]):
            raise ValueError(f"merge.{chave}: esperado lista de nomes")
    if merge["modo"] == "automatico" and not merge["checks"]:
        raise ValueError("Auto-merge exige checks explícitos; GitHub continua responsável pelo merge")
    for nome in ("ceo", "diretor"):
        _executor(cfg[nome], nome)
    if cfg["ceo"]["autonomia"] != "limites_aprovados":
        raise ValueError("CEO deve respeitar limites aprovados pelo usuário")
    if not isinstance(cfg["equipes"], list):
        raise ValueError("equipes: esperado lista")
    nomes = set()
    for equipe in cfg["equipes"]:
        _objeto(equipe, "equipe")
        if set(equipe) - {"nome", "especialidade", "executor"}:
            raise ValueError("equipe: campos desconhecidos")
        nome = equipe.get("nome")
        if not isinstance(nome, str) or not nome.strip() or nome.casefold() in nomes:
            raise ValueError("Equipe sem nome ou duplicada")
        nomes.add(nome.casefold())
        if not isinstance(equipe.get("especialidade"), str) or not equipe["especialidade"].strip():
            raise ValueError("Equipe exige especialidade")
        _executor(equipe.get("executor"), f"equipe {nome}")
    _objeto(cfg["rotas"], "rotas")
    for escopo, executor in cfg["rotas"].items():
        if escopo not in ("planejamento", "implementacao", "revisao", "simples"):
            raise ValueError(f"Escopo desconhecido: {escopo}")
        _executor(executor, f"rota {escopo}")
    for chave in ("max_paralelo", "ram_livre_min_gb"):
        numero = cfg["local"][chave]
        if type(numero) is not int or numero < 1:
            raise ValueError(f"local.{chave}: inteiro positivo obrigatório")
    if not cfg["local"]["team"] and cfg["local"]["max_paralelo"] != 1:
        raise ValueError("Paralelismo local exige team explícito")
    cpu=cfg['local']['cpu_uso_max_pct']
    if type(cpu) is not int or not 1<=cpu<=100:
        raise ValueError('local.cpu_uso_max_pct: inteiro de 1 a 100 obrigatório')
    for chave in ('ollama_memoria_max_gb', 'vram_livre_min_gb'):
        numero=cfg['local'][chave]
        if type(numero) is not int or not 1<=numero<=1024:
            raise ValueError(f'local.{chave}: inteiro de 1 a 1024 obrigatório')
    gpu=cfg['local']['gpu_uso_max_pct']
    if type(gpu) is not int or not 1<=gpu<=100:
        raise ValueError('local.gpu_uso_max_pct: inteiro de 1 a 100 obrigatório')
    for nome, caminho in cfg["fontes"].items():
        if not isinstance(caminho, str) or not caminho.strip():
            raise ValueError(f"fontes.{nome}: caminho obrigatório")
        relativo = Path(caminho)
        if relativo.is_absolute() or relativo.drive or ".." in relativo.parts:
            raise ValueError(f"fontes.{nome}: caminho deve permanecer no projeto")
    kanban = cfg["kanban"]
    if kanban["tipo_owner"] not in ("users", "orgs"):
        raise ValueError("kanban.tipo_owner deve ser users ou orgs")
    if type(kanban["numero"]) is not int or kanban["numero"] < 0:
        raise ValueError("kanban.numero deve ser inteiro não negativo")
    prioridades=kanban['prioridades']
    if (not isinstance(prioridades,list) or any(not isinstance(p,str) or not p.strip() or p!=p.strip() for p in prioridades)
        or len(prioridades)!=len(set(prioridades))):
        raise ValueError('kanban.prioridades: lista ordenada de nomes únicos obrigatória')
    if prioridades and not kanban['campo_prioridade'].strip():
        raise ValueError('Configure campo_prioridade para usar ordem de prioridades')
    for chave, valor in kanban.items():
        if chave not in ("numero", "prioridades") and not isinstance(valor, str):
            raise ValueError(f"kanban.{chave}: esperado texto")
    revisao = cfg["revisao"]
    if type(revisao["ativo"]) is not bool or type(revisao["separar_autor"]) is not bool:
        raise ValueError("Flags de revisão devem ser booleanas")
    if type(revisao["clouds_distintas"]) is not int or revisao["clouds_distintas"] < 1:
        raise ValueError("revisao.clouds_distintas deve ser inteiro positivo")
    if not isinstance(revisao["revisores"], list):
        raise ValueError("revisao.revisores deve ser lista")
    nomes_revisores = set()
    clouds = set()
    for revisor in revisao["revisores"]:
        _objeto(revisor, "revisor")
        if set(revisor) != {"nome", "executor"}:
            raise ValueError("Revisor exige nome e executor")
        nome = revisor["nome"]
        if not isinstance(nome, str) or not nome.strip() or nome.casefold() in nomes_revisores:
            raise ValueError("Revisor sem nome ou duplicado")
        nomes_revisores.add(nome.casefold())
        _executor(revisor["executor"], f"revisor {nome}")
        if revisor["executor"].get("execucao", "cloud") != "cloud":
            raise ValueError("Revisão cruzada exige execução cloud")
        clouds.add(cloud_executor(revisor["executor"]))
    if revisao["ativo"] and len(clouds) < revisao["clouds_distintas"]:
        raise ValueError("Número insuficiente de clouds distintas para revisão cruzada")
    a=cfg['auditor']
    if (type(a['ativo']) is not bool or type(a['max_diff']) is not int or not 1000<=a['max_diff']<=180000
        or type(a['max_prs']) is not int or not 1<=a['max_prs']<=10):raise ValueError('Limites do auditor inválidos')
    if a['ativo'] and (not revisao['ativo'] or revisao['clouds_distintas']<2 or not revisao['separar_autor']):
        raise ValueError('Auditor exige revisão ativa com duas clouds e separação do autor')
    return cfg


def cloud_executor(executor):
    """Identidade declarada do fornecedor do modelo, distinta do console utilizado."""
    if executor.get("execucao", "cloud") == "local":
        return "local"
    if executor.get("cloud"):
        import unicodedata
        nome=unicodedata.normalize('NFKC',executor['cloud']).strip().casefold()
        chave=''.join(c for c in nome if c not in ' -_\t\r\n')
        aliases={'openai':'openai','openaiapi':'openai',
                 'anthropic':'anthropic','anthropicapi':'anthropic',
                 'google':'google','googleai':'google','googlecloud':'google','vertexai':'google',
                 'nvidia':'nvidia','nvidianim':'nvidia'}
        if chave in ('zen','opencode','opencodezen','openrouter'):
            raise ValueError('Declare o fornecedor real do modelo; gateway não comprova diversidade')
        return aliases.get(chave,nome)
    conhecidos = {"claude": "anthropic", "codex": "openai", "gemini": "google"}
    cloud = conhecidos.get(executor["console"])
    if cloud is None:
        raise ValueError("OpenCode: declare cloud do modelo; trocar console não comprova diversidade")
    return cloud


def revisores(cfg, autor):
    """Escolhe o mínimo de fornecedores distintos, sem herdar conversa do autor."""
    cfg = validar(cfg)
    politica = cfg["revisao"]
    if not politica["ativo"]:
        return []
    autor_cloud = cloud_executor(autor)
    usados, escolhidos = set(), []
    for revisor in politica["revisores"]:
        cloud = cloud_executor(revisor["executor"])
        if cloud in usados or (politica["separar_autor"] and cloud == autor_cloud):
            continue
        escolhidos.append(copy.deepcopy(revisor))
        usados.add(cloud)
        if len(usados) >= politica["clouds_distintas"]:
            return escolhidos
    raise ValueError("Não há revisores suficientes em clouds diferentes do autor; revisão não pode aprovar")


def carregar(projeto):
    caminho = Path(projeto) / ".office" / "projeto.json"
    if not caminho.exists():
        return copy.deepcopy(PADRAO)
    return validar(json.loads(caminho.read_text(encoding="utf-8-sig")))


def executor(cfg, papel=None, equipe=None, escopo=None):
    """Escolha explícita por função/escopo; nunca substitui um console indisponível."""
    cfg = validar(cfg)
    if not cfg["ativo"]:
        raise ValueError("Gestão não habilitada neste projeto")
    if papel:
        if papel not in ("ceo", "diretor") or equipe or escopo:
            raise ValueError("Papel deve ser ceo ou diretor, sem equipe/escopo")
        if cfg[papel].get('execucao','cloud')=='local':
            if not cfg['local']['ativo']:raise ValueError('Execução local desativada no projeto')
            if not cfg['local']['team']:raise ValueError('CEO e diretor exigem cloud no perfil local de tarefas simples')
        return copy.deepcopy(cfg[papel])
    if escopo and escopo not in ("planejamento", "implementacao", "revisao", "simples"):
        raise ValueError("Escopo desconhecido")
    time = next((x for x in cfg["equipes"] if x["nome"] == equipe), None)
    if equipe and time is None:
        raise ValueError(f"Equipe desconhecida: {equipe}")
    escolhido = cfg["rotas"].get(escopo) if escopo else None
    if escolhido is None and time:
        escolhido = time["executor"]
    if escolhido is None:
        raise ValueError("Escolha uma equipe ou uma rota configurada")
    if escolhido.get("execucao", "cloud") == "local":
        if not cfg["local"]["ativo"]:
            raise ValueError("Execução local desativada no projeto")
        if not cfg["local"]["team"] and escopo != "simples":
            raise ValueError("Perfil local restrito a tarefas simples")
    return copy.deepcopy(escolhido)


def fontes_resolvidas(projeto, cfg):
    """Identidade/conteúdo das fontes documentais; sem copiar corpos para o estado."""
    cfg=validar(cfg); raiz=Path(projeto).resolve(); saida=[]
    for nome in ('regras','produto','arquitetura'):
        relativo=cfg['fontes'][nome]; caminho=(raiz/relativo).resolve()
        if not caminho.is_relative_to(raiz):
            raise ValueError('Fonte documental fora do projeto: '+nome)
        item={'tipo':nome,'caminho':relativo,'destino':caminho.relative_to(raiz).as_posix()}
        if not caminho.exists():
            item['estado']='ausente'
        else:
            if not caminho.is_file(): raise ValueError('Fonte documental deve ser arquivo: '+nome)
            with caminho.open('rb') as fonte: conteudo=fonte.read(8*1024*1024+1)
            if len(conteudo)>8*1024*1024:
                raise ValueError('Fonte documental maior que 8 MiB; divida em referências: '+nome)
            item.update(estado='arquivo',sha256=hashlib.sha256(conteudo).hexdigest())
        saida.append(item)
    return saida


def contexto(projeto, cfg=None, papel=None, equipe=None):
    """Referências canônicas, sem repetir o conteúdo dos documentos no prompt."""
    raiz = Path(projeto).resolve()
    cfg = validar(cfg) if cfg is not None else carregar(raiz)
    if not cfg["ativo"]:
        return ""
    linhas = ["Política de gestão: .office/projeto.json. O usuário define escopo e limites.",
              "Raiz canônica do projeto: " + json.dumps(raiz.as_posix(),ensure_ascii=False) + ".",
              "Política canônica: " + json.dumps((raiz/'.office/projeto.json').as_posix(),ensure_ascii=False) + ".",
              "As fontes abaixo pertencem à raiz canônica, mesmo quando o console executa em outro worktree. "
              "Consulte-as como referências de leitura; alterações da tarefa pertencem ao próprio worktree/branch. "
              "Não modifique o checkout canônico para contornar a revisão. Se as permissões impedirem leitura, "
              "informe o bloqueio; não substitua a fonte por uma versão divergente nem amplie permissões."]
    for nome, relativo in cfg["fontes"].items():
        caminho = (raiz / relativo).resolve()
        if not caminho.is_relative_to(raiz):
            raise ValueError(f"Fonte {nome} aponta para fora do projeto")
        if caminho.exists():
            linhas.append(f"Fonte única de {nome}: {relativo}. Caminho canônico: " + json.dumps(caminho.as_posix(),ensure_ascii=False) + ". Consulte somente as partes relevantes.")
    linhas.append("Equipes são especialidades; consoles e modelos são meios de execução.")
    linhas.append("Kanban do projeto define tarefas, dependências e aceite. Não invente conclusão ou status.")
    linhas.append("O agente não executa merge nem altera a política de gestão por conta própria.")
    if papel == "ceo":
        linhas.append("Papel CEO: acompanhe objetivos, prioridades e bloqueios; delegue através do despacho "
                      "do escritório dentro do escopo aprovado. Escale mudanças de escopo, processo ou orçamento ao usuário.")
    elif papel == "diretor":
        linhas.append("Papel Diretor: transforme prioridades em tarefas com aceite, dependências e equipe; "
                      "acompanhe qualidade e encaminhe bloqueios ao CEO.")
    if equipe:
        linhas.append(f"Equipe responsável: {equipe}.")
    return "\n".join(linhas)


def decidir_merge(cfg, checks, rotulos=(), relatorio_revisao=None, sha=None):
    """Só informa elegibilidade; nunca executa merge ou publica checks."""
    cfg = validar(cfg)
    if not cfg["ativo"] or cfg["merge"]["modo"] != "automatico":
        return False
    if set(rotulos) & set(cfg["merge"]["rotulos_manuais"]):
        return False
    if cfg["revisao"]["ativo"]:
        from revisao_cruzada import conferir
        if not conferir(cfg, relatorio_revisao, sha):
            return False
    return all(checks.get(nome) == "success" for nome in cfg["merge"]["checks"])
