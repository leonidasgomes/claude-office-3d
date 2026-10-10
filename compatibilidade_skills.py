"""Diagnóstico conservador de recursos de runtime; não executa YAML ou comandos."""
import re

COMUNS={'name','description','license','compatibility','metadata'}
CLAUDE={'hooks','allowed-tools','context','agent','model','disable-model-invocation',
        'user-invocable','argument-hint','arguments','shell','paths','effort'}


def analisar(texto):
    m=re.match(r'\A---\s*\n(.*?)\n---(?:\s*\n|$)',texto,re.S)
    campos=[]; problemas=[]
    if m:
        for linha in m.group(1).splitlines():
            par=re.match(r'^([A-Za-z][A-Za-z0-9_-]*):(?:\s|$)',linha)
            if par:
                chave=par.group(1)
                if chave in campos: problemas.append('campo repetido no frontmatter: '+chave)
                campos.append(chave)
            elif linha and not linha[0].isspace() and not linha.startswith('#'):
                problemas.append('frontmatter fora do subconjunto normalizado')
    else: problemas.append('frontmatter ausente ou incompleto')
    corpo=texto[m.end():] if m else texto
    recursos=sorted(set(campos)-COMUNS)
    if re.search(r'!`|^```!',corpo,re.M): recursos.append('injecao-dinamica')
    if re.search(r'\$\{CLAUDE_[A-Z_]+\}|\$ARGUMENTS\b|(?<!\\)\$[0-9]\b',corpo): recursos.append('substituicoes-claude')
    return {'campos':sorted(set(campos)),'recursos':sorted(set(recursos)),
            'problemas':sorted(set(problemas))}


def diagnostico(skill, provider, local=False):
    if provider not in ('claude','codex','opencode','gemini'):
        return {'estado':'adaptacao-pendente','pendencias':['provider desconhecido']}
    recursos=skill.get('recursos_runtime',[])
    if skill['problemas']:
        return {'estado':'invalida','pendencias':list(skill['problemas'])}
    if not recursos:
        return {'estado':'instrucoes','pendencias':[]}
    conhecidos=CLAUDE|{'injecao-dinamica','substituicoes-claude'}
    if provider=='claude' and not local and skill.get('claude_nativo') and not set(recursos)-conhecidos:
        return {'estado':'nativa-claude','pendencias':[]}
    return {'estado':'adaptacao-pendente','pendencias':recursos}


def conferir(skill, provider, local=False):
    d=diagnostico(skill,provider,local)
    if d['pendencias']:
        raise ValueError('Skill '+skill['nome']+' incompatível com '+provider+
                         (' local' if local else '')+': '+', '.join(d['pendencias'])+
                         '. Use o provider nativo ou revise o mapeamento; permissões não são ampliadas automaticamente.')
    return d
