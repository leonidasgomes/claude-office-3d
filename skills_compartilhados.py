"""Catálogo compatível e links de diretório; a fonte permanece em .claude/skills."""
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

REGRAS_PASTA = ('Regras por escopo, quando presentes, ficam em .claude/rules/. '
    'Antes de trabalhar em um arquivo, consulte as regras sem paths e as regras cujo '
    'frontmatter paths corresponda ao arquivo. Preserve o escopo: não aplique regras '
    'condicionais a todo o projeto. Se não conseguir determinar o escopo ou ler uma '
    'regra aplicável, informe o impedimento antes de editar. Referência textual não '
    'comprova carregamento nativo; hooks e controles de execução continuam específicos do console.')


def metadados(texto):
    """Lê name/description YAML simples, incluindo blocos e strings entre aspas."""
    match = re.match(r"\A---\s*\n(.*?)\n---(?:\s*\n|$)", texto, re.S)
    if not match:
        return {}
    linhas = match.group(1).splitlines()
    resultado = {}
    for i, linha in enumerate(linhas):
        par = re.match(r"^(name|description):\s*(.*)$", linha)
        if not par:
            continue
        chave, valor = par.groups()
        if valor in (">", "|", ">-", "|-"):
            bloco = []
            for seguinte in linhas[i + 1:]:
                if seguinte and not seguinte[0].isspace():
                    break
                bloco.append(seguinte.strip())
            valor = ("\n" if valor.startswith("|") else " ").join(bloco)
        elif valor.startswith('"'):
            try:
                valor = json.loads(valor)
            except ValueError:
                continue
        elif valor.startswith("'") and valor.endswith("'"):
            valor = valor[1:-1].replace("''", "'")
        resultado[chave] = valor
    return resultado


def catalogo(projeto, cfg=None):
    from gestao_projeto import carregar, validar
    raiz = Path(projeto).resolve()
    cfg = carregar(raiz) if cfg is None else validar(cfg)
    fonte = (raiz / cfg['fontes']['skills']).resolve()
    if not fonte.is_relative_to(raiz):
        raise ValueError('Fonte de skills fora do projeto')
    saida = []
    for arq in sorted(fonte.glob("*/SKILL.md")):
        if not arq.resolve().is_relative_to(raiz):
            continue
        conteudo = arq.read_bytes()
        texto = conteudo.decode("utf-8-sig")
        meta = metadados(texto)
        nome, desc = meta.get("name", ""), meta.get("description", "")
        problemas = []
        from compatibilidade_skills import analisar
        analise=analisar(texto)
        problemas.extend(analise['problemas'])
        if not 1 <= len(nome) <= 64 or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", nome) or nome != arq.parent.name:
            problemas.append("name inválido ou diferente da pasta")
        if not desc or len(desc) > 1024:
            problemas.append("description ausente ou maior que 1024")
        limites = [campo for campo in ("hooks:", "allowed-tools:", "context:", "agent:")
                   if campo.split(':')[0] in analise['recursos']]
        nativo=raiz/'.claude/skills'/arq.parent.name/'SKILL.md'
        saida.append({"nome": nome or arq.parent.name, "descricao": desc, "pasta": arq.parent,
                      "problemas": problemas, "limites": limites, "sha256": hashlib.sha256(conteudo).hexdigest(),
                      'recursos_runtime':analise['recursos'], 'claude_nativo':nativo.is_file() and nativo.resolve()==arq.resolve()})
    return saida


def nomes_cartao(texto):
    """Nomes canônicos separados por vírgula, ponto e vírgula ou linhas."""
    if not isinstance(texto,str):
        raise ValueError('Skills do cartão devem ser texto')
    texto=texto.strip()
    if texto.endswith('.'):
        if not re.split(r'[,;\n]',texto[:-1])[-1].strip():
            raise ValueError('Skills: use nomes do catálogo separados por vírgula ou linhas')
        texto=texto[:-1]
    nomes=[]
    for parte in re.split(r'[,;\n]',texto):
        nome=re.sub(r'^[-*]\s+', '', parte.strip()).strip('`').strip()
        if not nome: continue
        if len(nome)>64 or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',nome):
            raise ValueError('Skills: use nomes do catálogo separados por vírgula ou linhas')
        if nome not in nomes: nomes.append(nome)
    return nomes


def resolver(projeto, nomes, cfg=None, provider=None, local=False):
    """Snapshot de referências; nunca copia corpo nem adapta permissões/hook."""
    if not isinstance(nomes,list) or any(not isinstance(n,str) for n in nomes):
        raise ValueError('Skills solicitadas devem ser uma lista de nomes')
    if not nomes: return []
    raiz=Path(projeto).resolve()
    disponiveis={s['nome']:s for s in catalogo(raiz,cfg)}
    saida=[]
    for nome in sorted(set(nomes)):
        skill=disponiveis.get(nome)
        if not skill or skill['problemas']:
            raise ValueError('Skill indisponível na fonte compartilhada: '+nome)
        ativacao = None
        if provider:
            from compatibilidade_skills import conferir
            d = conferir(skill,provider,local)
            if d['estado'] == 'nativa-claude': ativacao = 'Skill'
        ref = {'nome':nome, 'caminho':(skill['pasta']/'SKILL.md').relative_to(raiz).as_posix(),
               'sha256':skill['sha256'], 'limites':skill['limites']}
        if ativacao: ref['ativacao_nativa'] = ativacao
        saida.append(ref)
    return saida


def instrucoes_ativacao(referencias):
    nomes = [r['nome'] for r in referencias if r.get('ativacao_nativa') == 'Skill']
    if not nomes: return ''
    return ('\nSkills Claude selecionadas com recursos nativos: '+', '.join(nomes)+
            '. Ative cada uma pela ferramenta nativa Skill antes de executar a tarefa. '
            'Ler SKILL.md não ativa esses recursos. Se a ferramenta ou a skill não estiver '
            'disponível, interrompa a tarefa e informe o impedimento; não substitua por leitura do arquivo. '
            'A configuração e as permissões nativas continuam prevalecendo.')


def preparar_compartilhados(projeto, aplicar=False):
    """Link por skill, idempotente; colisões são preservadas. Sem cópia como fallback."""
    relatorio = []
    for skill in catalogo(projeto):
        fonte = skill["pasta"].resolve()
        destino = Path(projeto) / ".agents" / "skills" / fonte.name
        if not destino.parent.resolve().is_relative_to(Path(projeto).resolve()):
            raise ValueError('Pasta de links compartilhados aponta para fora do projeto')
        estado = "planejado"
        if skill["problemas"]:
            estado = "incompatível: " + "; ".join(skill["problemas"])
        elif skill['recursos_runtime']:
            estado = 'adaptação pendente: '+', '.join(skill['recursos_runtime'])
        elif os.path.lexists(destino):
            estado = "compartilhado" if destino.resolve() == fonte else "conflito preservado"
        elif aplicar:
            destino.parent.mkdir(parents=True, exist_ok=True)
            try:
                destino.symlink_to(fonte, target_is_directory=True)
            except OSError:
                if os.name != "nt":
                    estado = "link indisponível; use o catálogo no prompt"
                else:
                    # PowerShell nativo: sem cmd/mklink nem comandos construídos com caminhos.
                    script = "New-Item -ItemType Junction -Path $env:OFFICE_LINK -Target $env:OFFICE_SOURCE -ErrorAction Stop | Out-Null"
                    env = {**os.environ, "OFFICE_LINK": str(destino), "OFFICE_SOURCE": str(fonte)}
                    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                                       env=env, capture_output=True, text=True)
                    estado = "compartilhado" if r.returncode == 0 else "link indisponível; use o catálogo no prompt"
            else:
                estado = "compartilhado"
        relatorio.append({"skill": fonte.name, "estado": estado, "limites": skill["limites"]})
    return relatorio


# Compatibilidade com callers existentes; .agents/skills também é usado por Gemini/OpenCode.
preparar_codex = preparar_compartilhados


def contexto(projeto, provider=None):
    from gestao_projeto import carregar
    projeto = Path(projeto).resolve()
    cfg = carregar(projeto)
    linhas = ["Siga as regras do projeto e preserve o fluxo branch/PR/aprovação."]
    if (projeto / '.office/projeto.json').is_file():
        fontes = [cfg['fontes'][chave] for chave in ('regras', 'produto', 'arquitetura')]
    else:
        fontes = ["AGENTS.md", "CLAUDE.md", "PRODUTO.md"]
    for nome in dict.fromkeys(fontes):
        if not (projeto / nome).resolve().is_relative_to(projeto):
            raise ValueError('Fonte de contexto fora do projeto')
        if (projeto / nome).is_file():
            linhas.append(f"Fonte do projeto: {nome}. Consulte as partes relevantes antes de implementar.")
    regras=projeto/'.claude/rules'
    if regras.exists():
        if not regras.resolve().is_relative_to(projeto) or not regras.is_dir():
            raise ValueError('Regras por escopo fora do projeto ou pasta inválida')
        linhas.append(REGRAS_PASTA)
    linhas.append("Skills compartilhadas (leia SKILL.md no caminho original antes de usar):")
    for skill in catalogo(projeto, cfg):
        if not skill["problemas"]:
            if provider:
                from compatibilidade_skills import diagnostico
                d=diagnostico(skill,provider)
                if d['pendencias']:
                    linhas.append(f"- {skill['nome']}: adaptação pendente para {provider} ({', '.join(d['pendencias'])}). Não trate como skill equivalente.")
                    continue
            caminho = skill["pasta"].relative_to(projeto).as_posix()
            linhas.append(f"- {skill['nome']}: {skill['descricao']} ({caminho}/SKILL.md)")
            if provider and d['estado'] == 'nativa-claude':
                linhas.append('  Recursos nativos: use a ferramenta Skill para ativar; leitura do arquivo não equivale à ativação. Se indisponível, informe o impedimento.')
    linhas.append("Hooks, permissões, modelos e team do Claude não são portáveis automaticamente. "
                  "Se faltar uma ferramenta ou integração, informe a limitação; não simule execução.")
    return "\n".join(linhas)
