"""Projeção do mesmo Kanban usado pelo despacho. Apenas leitura de projetos registrados."""
from pathlib import Path
import re
import subprocess
import threading
import time

from funcionarios import id_projeto
from gestao_projeto import carregar
from kanban_gestao import Kanban

_travas = {}
_trava = threading.Lock()


def catalogo(projetos):
    ativos, invalidos, vistos = [], [], set()
    for projeto in projetos:
        raiz = Path(projeto).resolve()
        ident = id_projeto(raiz)
        if ident in vistos:
            continue
        vistos.add(ident)
        try:
            cfg = carregar(raiz)
        except (OSError, ValueError, TypeError):
            invalidos.append({"id": ident, "nome": raiz.name})
            continue
        if cfg['ativo']:
            ativos.append((raiz, cfg, {"id": ident, "nome": raiz.name}))
    return ativos, invalidos


def habilitado(projetos):
    ativos, invalidos = catalogo(projetos)
    return bool(ativos or invalidos)


def _valor(item, campos, nome):
    campo = campos.get(nome, {})
    if not campo:
        return ''
    bruto = next((f for f in item.get('fields', []) if f.get('id') == campo.get('id')), {})
    valor = bruto.get('value')
    if isinstance(valor, dict):
        valor = valor.get('name') or valor.get('raw') or ''
    if isinstance(valor, dict):
        valor = valor.get('raw', '')
    return str(valor or '')



def escolher(projetos, ident=None, assunto='Kanban'):
    """Mesma seleção registrada para painéis; ID nunca é interpretado como caminho."""
    ativos, invalidos = catalogo(projetos)
    if not ativos and not invalidos and ident is None: return None
    publicos=[p[2] for p in ativos]+invalidos
    if ident is None:
        if invalidos: return None,publicos,'Há uma política de projeto inválida. Corrija-a ou selecione outro projeto.'
        if len(ativos)!=1: return None,publicos,f'Selecione o projeto para consultar seu {assunto}.'
        return ativos[0],publicos,''
    escolhido=next((p for p in ativos if p[2]['id']==ident),None)
    return escolhido,publicos,'' if escolhido else 'Projeto desconhecido, desativado ou com política inválida.'

def vista(projetos, ident=None, somente_cache=False):
    selecao = escolher(projetos, ident)
    if selecao is None: return None
    selecionado, projetos_publicos, erro = selecao
    resposta = {"fonte": "gestao", "configurado": True, "projeto": "", "repo": "",
                "cartoes": [], "atualizado": "", "erro": erro, "limite": "",
                "projetos": projetos_publicos, "projeto_id": "", "colunas": []}
    if erro: return resposta
    raiz, cfg, publico = selecionado
    resposta['projeto_id'] = publico['id']
    k = cfg['kanban']
    resposta.update(repo=k['repo'], colunas=[k[x] for x in ('backlog', 'andamento', 'revisao', 'feito')],
                    concluido=k['feito'])
    try:
        # O despacho invalida este mesmo arquivo depois de mover um cartão.
        from gestao_cli import pasta_dados
        cliente = Kanban(cfg, pasta_dados(raiz) / 'kanban.json')
        with _trava:
            trava = _travas.setdefault(publico['id'], threading.Lock())
        with trava:
            quadro = cliente.quadro(somente_cache=somente_cache)
        campos = {c['name']: c for c in quadro['campos']}
        if k['campo_status'] not in campos or k['campo_time'] not in campos:
            raise ValueError('Campos obrigatórios ausentes')
        board = f"https://github.com/{k['tipo_owner']}/{k['owner']}/projects/{k['numero']}"
        padrao = re.compile(r'https://github\.com/' + re.escape(k['repo']) + r'/(issues|pull)/(\d+)$', re.I)
        cartoes = []
        for item in quadro['itens']:
            conteudo = item.get('content') or {}
            url = conteudo.get('html_url') or ''
            match = padrao.fullmatch(url)
            tipo = item.get('content_type') or ''
            if not match and tipo != 'DraftIssue':
                continue  # Boards compartilhados podem conter issues de outros repositórios.
            if tipo == 'DraftIssue' and url:
                continue
            numero = int(match[2]) if match else None
            cartoes.append({'numero': numero, 'titulo': conteudo.get('title') or '',
                'url': url or (f'{board}?pane=issue&itemId={item["id"]}' if type(item.get('id')) is int else board),
                'tipo': tipo or ('Issue' if match[1] == 'issues' else 'PullRequest'),
                'status': _valor(item, campos, k['campo_status']) or 'Sem status',
                'time': _valor(item, campos, k['campo_time']),
                'prioridade': _valor(item, campos, k['campo_prioridade']), 'etapa': _valor(item, campos, k['campo_etapa']),
                'item_id': str(item.get('node_id') or '')})
        resposta.update(projeto=board, cartoes=cartoes,
                        atualizado=time.strftime('%H:%M:%S', time.localtime(quadro['gravado_em'])))
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, subprocess.SubprocessError):
        resposta['erro'] = 'Não foi possível ler o Kanban da política deste projeto. Confira configuração e acesso do gh.'
    return resposta
