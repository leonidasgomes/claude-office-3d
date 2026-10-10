# -*- coding: utf-8 -*-
"""Importa o `.claude/` de um projeto para o OpenCode: agentes, regras e plugin do escritório (skills já funcionam sozinhas).

O que faz (sem `--aplicar`, só imprime o plano e não escreve nada):
  - `.claude/agents/*.md` -> `.opencode/agents/<nome>.md` (description, mode, model pelo mapa, tools -> permission,
    maxTurns -> steps, skills sugeridas e effort viram linhas no prompt);
  - `opencode.json`: referencia a regra oficial configurada; sem política, mantém o fluxo CLAUDE.md legado;
    conserva as demais instruções/configurações e faz backup datado;
  - copia o plugin do escritório (`opencode/office.js` desta pasta) para `.opencode/plugins/office.js` do projeto
    (é de lá que o OpenCode carrega plugins locais; o array `plugin` do `opencode.json` é só para pacotes npm);
  - confere o catálogo compartilhado; fonte personalizada recebe links em .agents/skills, sem cópia de skills.

Uso: python importar_opencode.py [--projeto ./minha-loja] [--aplicar] [--forcar]
       [--opus ID] [--sonnet ID] [--haiku ID] [--modo subagent]
Sem --opus/--sonnet/--haiku o model é omitido (o agente herda o da sessão) e avisado.
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path
from skills_compartilhados import metadados, catalogo, preparar_codex
from gestao_projeto import carregar

RAIZ = Path(__file__).resolve().parent
OFICINA = RAIZ / "opencode" / "office.js"   # plugin do escritório, registrado por caminho absoluto

# ferramenta do Claude -> permissão do OpenCode (Monitor vira task: aguardar comando longo delegando/monitorando)
FERRAMENTAS = {"read": "read", "grep": "grep", "glob": "glob", "bash": "bash", "powershell": "bash",
               "edit": "edit", "write": "edit", "skill": "skill", "agent": "task", "task": "task",
               "monitor": "task", "websearch": "websearch", "webfetch": "webfetch"}
NOME_SKILL = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*\Z")


def ler_md(caminho):
    """(frontmatter dict, corpo): frontmatter simples `chave: valor` com continuação em lista `  - item`."""
    texto = Path(caminho).read_text(encoding="utf-8-sig")
    m = re.match(r"---\s*\n(.*?)\n---\s*\n?", texto, re.S)
    if not m:
        return {}, texto
    fm, corpo = {}, m.group(1)
    chave = None
    for linha in corpo.splitlines():
        item = re.match(r"^\s+-\s+(.+?)\s*$", linha)
        if item and chave:
            v = fm.get(chave)
            fm[chave] = (v if isinstance(v, list) else []) + [item.group(1)]
            continue
        par = re.match(r"^([A-Za-z_]+):\s*(.*?)\s*$", linha)
        if par:
            chave = par.group(1)
            fm[chave] = par.group(2)
    return fm, texto[m.end():]


def converter(nome, fm, corpo, mapa_modelo, modo):
    """Devolve (texto do agente OpenCode, avisos)."""
    avisos = []
    desc = (fm.get("description") or "").strip().strip("\"'")
    if not desc:
        raise ValueError(f"{nome}: sem description")
    saida = {"description": desc, "mode": modo}
    modelo = (fm.get("model") or "").strip()
    if modelo:
        if "/" in modelo:
            saida["model"] = modelo
        elif modelo in mapa_modelo:
            saida["model"] = mapa_modelo[modelo]
        else:
            avisos.append(f"{nome}: model '{modelo}' sem --{modelo} (omitido, herda o da sessão)")
    permissoes = {}
    for ferramenta in [t.strip() for t in str(fm.get("tools") or "").split(",") if t.strip()]:
        chave = FERRAMENTAS.get(ferramenta.lower())
        if chave:
            permissoes[chave] = "allow"
        else:
            avisos.append(f"{nome}: ferramenta '{ferramenta}' sem equivalente (ignorada)")
    if permissoes:
        saida["permission"] = {"*": "deny", **permissoes}
    try:
        if fm.get("maxTurns") is not None:
            saida["steps"] = int(str(fm["maxTurns"]).strip())
    except (TypeError, ValueError):
        avisos.append(f"{nome}: maxTurns inválido (ignorado)")
    if fm.get("effort"):
        corpo = corpo.strip("\n")
        corpo += (f"\n\nNível de esforço: {str(fm['effort']).strip()} — trabalhe com minúcia e verifique o "
                  "resultado antes de entregar.")
    sugeridas = fm.get("skills") or []
    corpo = corpo.strip("\n")
    if sugeridas:
        corpo += "\n\nSkills úteis neste trabalho: " + ", ".join(sugeridas) + "."
    linhas = ["---"]
    for chave, valor in saida.items():
        if isinstance(valor, dict):
            linhas.append(f"{chave}:")
            linhas += [f"  {json.dumps(k) if k == '*' else k}: {v}" for k, v in valor.items()]
        else:
            linhas.append(f"{chave}: {json.dumps(valor, ensure_ascii=False) if chave == 'description' else valor}")
    linhas += ["---", corpo + "\n"]
    return "\n".join(linhas), avisos


def conferir_skills(pasta):
    """(válidas, problemas): mesmas regras do OpenCode (nome, description, nome == pasta)."""
    validas, problemas = [], []
    if not pasta.is_dir():
        return validas, [f"{pasta} não existe"]
    for d in sorted(pasta.iterdir()):
        f = d / "SKILL.md"
        if not f.is_file():
            problemas.append(f"{d.name}: sem SKILL.md")
            continue
        fm = metadados(f.read_text(encoding="utf-8-sig"))
        nome, desc = str(fm.get("name") or "").strip(), str(fm.get("description") or "").strip()
        if not nome or not desc:
            problemas.append(f"{d.name}: sem name/description")
        elif not NOME_SKILL.fullmatch(nome):
            problemas.append(f"{d.name}: nome inválido ({nome})")
        elif nome != d.name:
            problemas.append(f"{d.name}: nome != pasta")
        elif not 1 <= len(desc) <= 1024:
            problemas.append(f"{d.name}: description com {len(desc)} caracteres")
        else:
            validas.append(nome)
    return validas, problemas


def plano_opencode_json(projeto, atual):
    """(novo_cfg, mudanças, avisos): referencia a regra oficial, preservando configuração."""
    if not isinstance(atual,dict): raise ValueError('opencode.json deve conter um objeto')
    cfg = json.loads(json.dumps(atual or {}))
    mudancas, avisos = [], []
    claude = projeto / "CLAUDE.md"
    agents = projeto / "AGENTS.md"
    instrucoes = cfg.get("instructions", [])
    if not isinstance(instrucoes,list) or any(not isinstance(x,str) for x in instrucoes):
        raise ValueError('instructions deve ser uma lista de caminhos')
    instrucoes = list(instrucoes)
    if (projeto / '.office/projeto.json').is_file():
        politica=carregar(projeto)
        fonte=politica['fontes']['regras']
        caminho=(projeto/fonte).resolve()
        if not caminho.is_relative_to(projeto.resolve()) or not caminho.is_file():
            raise ValueError('Fonte oficial de regras ausente ou fora do projeto')
        if fonte not in instrucoes:
            instrucoes.append(fonte)
            mudancas.append('instructions += '+fonte)
        cfg['instructions']=instrucoes
        return cfg,mudancas,avisos
    if claude.is_file() and "CLAUDE.md" not in instrucoes:
        if not agents.is_file() or "CLAUDE.md" in agents.read_text(encoding="utf-8", errors="replace"):
            instrucoes.append("CLAUDE.md")
            mudancas.append("instructions += CLAUDE.md")
        else:
            avisos.append("AGENTS.md próprio sem apontar para CLAUDE.md (instructions intacto)")
    cfg["instructions"] = instrucoes
    return cfg, mudancas, avisos


def plano_plugin(projeto):
    """(destino, muda): copia do office.js para .opencode/plugins (de onde o OpenCode carrega)."""
    destino = projeto / ".opencode" / "plugins" / "office.js"
    if not OFICINA.is_file():
        return destino, "ausente", "opencode/office.js não existe nesta pasta (plugin não instalado)"
    if destino.is_file() and destino.read_bytes() == OFICINA.read_bytes():
        return destino, "igual", ""
    return destino, "copiar", ""


def main(argv=None):
    parser = argparse.ArgumentParser(description="Importa o .claude/ do projeto para o OpenCode")
    parser.add_argument("--projeto", default=".", help="pasta do projeto (padrão: atual)")
    parser.add_argument("--aplicar", action="store_true", help="escreve (sem ele, só imprime o plano)")
    parser.add_argument("--forcar", action="store_true", help="sobrescreve agentes já gerados")
    parser.add_argument("--opus", default="", help="id do modelo para agents com model: opus")
    parser.add_argument("--sonnet", default="", help="id do modelo para agents com model: sonnet")
    parser.add_argument("--haiku", default="", help="id do modelo para agents com model: haiku")
    parser.add_argument("--modo", default="subagent", help="mode dos agentes (padrão: subagent)")
    args = parser.parse_args(argv)
    projeto = Path(args.projeto).expanduser().resolve()
    claude = projeto / ".claude"
    if not claude.is_dir():
        print(f"Erro: {claude} não existe", file=sys.stderr)
        return 2
    mapa = {k: v for k, v in (("opus", args.opus), ("sonnet", args.sonnet), ("haiku", args.haiku)) if v}

    agentes = sorted((claude / "agents").glob("*.md")) if (claude / "agents").is_dir() else []
    saidas, avisos, pulados = {}, [], []
    for arq in agentes:
        try:
            fm, corpo = ler_md(arq)
            texto, av = converter(arq.stem, fm, corpo, mapa, args.modo)
            saidas[arq.stem] = texto
            avisos += av
        except ValueError as exc:
            avisos.append(f"ERRO: {exc}")
    try:
        politica=carregar(projeto)
        fonte=projeto/politica['fontes']['skills']
        itens=catalogo(projeto,politica)
        validas=[s['nome'] for s in itens if not s['problemas']]
        problemas=[s['nome']+': '+'; '.join(s['problemas']) for s in itens if s['problemas']]
        if not fonte.is_dir(): problemas.append(str(fonte)+' não existe')
        else:
            problemas.extend(d.name+': sem SKILL.md' for d in sorted(fonte.iterdir())
                             if d.is_dir() and not (d/'SKILL.md').is_file())
        links=preparar_codex(projeto) if fonte != claude/'skills' else []
    except (ValueError,OSError) as exc:
        print('Erro: '+str(exc),file=sys.stderr)
        return 2
    atual = {}
    cfg_path = projeto / "opencode.json"
    if cfg_path.is_file():
        try:
            atual = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
        except ValueError:
            print(f"Erro: {cfg_path} com JSON inválido", file=sys.stderr)
            return 2
    try:
        cfg, mudancas, avisos_cfg = plano_opencode_json(projeto, atual)
    except (ValueError,OSError) as exc:
        print('Erro: '+str(exc),file=sys.stderr)
        return 2
    avisos += avisos_cfg
    plug_dest, plug_muda, plug_aviso = plano_plugin(projeto)
    if plug_aviso:
        avisos.append(plug_aviso)

    if args.aplicar:
        if links: links=preparar_codex(projeto,True)
        destino = projeto / ".opencode" / "agents"
        destino.mkdir(parents=True, exist_ok=True)
        gravados = 0
        for nome, texto in saidas.items():
            alvo = destino / f"{nome}.md"
            if alvo.exists() and not args.forcar:
                pulados.append(nome)
                continue
            alvo.write_text(texto, encoding="utf-8")
            gravados += 1
        if plug_muda == "copiar" and (args.forcar or not plug_dest.exists()):
            plug_dest.parent.mkdir(parents=True, exist_ok=True)
            plug_dest.write_bytes(OFICINA.read_bytes())
            print("plugin: .opencode/plugins/office.js atualizado")
        elif plug_muda == "copiar":
            print("  mantido: .opencode/plugins/office.js (difere; --forcar atualiza)")
        if mudancas:
            if cfg_path.is_file():
                backup = cfg_path.with_name(f"opencode.json.bak-{time.strftime('%Y%m%d-%H%M')}")
                backup.write_bytes(cfg_path.read_bytes())
                print(f"backup: {backup.name}")
            cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"aplicado: {gravados} agentes, {len(mudancas)} mudanças no opencode.json")
    else:
        print(f"plano (sem --aplicar nada é escrito): {len(saidas)} agentes, {len(mudancas)} mudanças no opencode.json")
        for nome in saidas:
            print(f"  agente {nome} -> .opencode/agents/{nome}.md")
        for m in mudancas:
            print(f"  opencode.json: {m}")
        if plug_muda == "copiar":
            print("  plugin office.js -> .opencode/plugins/office.js")
    print(f"skills: {len(validas)} válidas no OpenCode, {len(problemas)} problemas")
    for link in links:
        print(f"  descoberta .agents/skills/{link['skill']}: {link['estado']}")
    for p in problemas:
        print(f"  skill: {p}")
    for a in avisos:
        print(f"  aviso: {a}")
    for p in pulados:
        print(f"  mantido: {p} (já existe; --forcar sobrescreve)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
