"""Dependências declaradas no GitHub, verificadas por leitura antes de trabalhar."""
import re
import time

_REPO = r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+'
_URL = re.compile(r'https://github\.com/(' + _REPO + r')/(issues|pull)/([1-9][0-9]*)', re.I)
_CURTA = re.compile(r'(?:(' + _REPO + r'))?#([1-9][0-9]*)')


def referencia(texto, repo):
    m = _URL.fullmatch(texto)
    if m:
        return m[1].lower(), int(m[3]), m[2].lower()
    m = _CURTA.fullmatch(texto)
    if m:
        return (m[1] or repo).lower(), int(m[2]), 'issues'
    raise ValueError('Dependência inválida: use #42, owner/repo#42 ou URL de issue/PR no github.com')


def declaradas(corpo, repo):
    campos = list(re.finditer(r'^[ \t]*\*\*Depend[eê]ncias:\*\*[ \t]*(.*?)(?=\n[ \t]*\n|\n[ \t]*\*\*[^*]+:\*\*|\n---|\Z)',
                             corpo, re.I | re.M | re.S))
    if len(campos) > 1:
        raise ValueError('Campo Dependências repetido; mantenha uma única declaração')
    if not campos:
        return []
    texto = campos[0][1].strip()
    if texto.casefold() in ('nenhuma', 'nenhum', 'sem dependências', 'none', '-'):
        return []
    if not texto:
        raise ValueError('Campo Dependências vazio; declare nenhuma ou referências explícitas')
    itens = []
    for linha in re.split(r'[,;\n]+', texto):
        linha = re.sub(r'^[-*]\s+', '', linha.strip())
        linha = re.sub(r'^\[[ xX]\]\s*', '', linha)
        if linha:
            itens.append(referencia(linha, repo))
    return itens


def verificar(cliente, numero, corpo):
    repo = cliente.cfg['repo'].lower()
    refs = {}
    for r, n, tipo in declaradas(corpo, repo):
        refs.setdefault((r, n), {'tipo': tipo, 'origens': set()})['origens'].add('corpo')
    # Falha/endpoint indisponível não equivale a uma lista sem bloqueadores.
    for issue in cliente.bloqueadores(numero):
        if not isinstance(issue, dict):
            raise ValueError('Formato de dependência nativa incompatível')
        r, n, tipo = referencia(issue.get('html_url') or '', repo)
        if issue.get('number') != n:
            raise ValueError('Identidade da dependência nativa inconsistente')
        refs.setdefault((r, n), {'tipo': tipo, 'origens': set()})['origens'].add('github')
    if len(refs) > 100:
        raise ValueError('Mais de 100 dependências; decomponha o cartão antes do despacho')
    evidencias = []
    for (r, n), dados in sorted(refs.items()):
        if r == repo and n == numero:
            raise ValueError('Cartão depende de si mesmo')
        issue = cliente.chamar(f'repos/{r}/issues/{n}')
        if not isinstance(issue, dict) or issue.get('number') != n:
            raise ValueError('Resposta da dependência não comprova sua identidade')
        destino, atual, _ = referencia(issue.get('html_url') or '', repo)
        if (destino, atual) != (r, n):
            raise ValueError('Dependência transferida; atualize sua referência no GitHub')
        pr = bool(issue.get('pull_request')) or dados['tipo'] == 'pull'
        merge = None
        if pr:
            entrega = cliente.chamar(f'repos/{r}/pulls/{n}')
            if (not isinstance(entrega, dict) or entrega.get('number') != n or entrega.get('merged') is not True
                    or not re.fullmatch('[0-9a-f]{40}', entrega.get('merge_commit_sha') or '')):
                raise ValueError(f'Dependência {r}#{n}: PR ainda não mergeado ou sem evidência exata')
            merge = entrega['merge_commit_sha']
        elif issue.get('state') != 'closed' or issue.get('state_reason') != 'completed':
            raise ValueError(f'Dependência {r}#{n}: issue não concluída (aberta, cancelada ou motivo desconhecido)')
        evidencias.append({'repo': r, 'numero': n, 'tipo': 'pr' if pr else 'issue',
                          'origens': sorted(dados['origens']), 'estado': 'mergeado' if pr else 'concluido',
                          'merge_sha': merge})
    return {'verificadas_em': time.time(), 'itens': evidencias}


def conferir(cliente, numero, corpo, anterior):
    atual = verificar(cliente, numero, corpo)
    if atual['itens'] != anterior['itens']:
        raise ValueError('Dependências mudaram desde a preparação do trabalho')
    return atual
