"""Conciliação de conclusão depois de merge comprovado no GitHub."""
import hashlib
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path

from controle_tarefas import Controle
from gestao_projeto import carregar, fontes_resolvidas
from kanban_gestao import Kanban, api
from prs_evidencias import projetar_checks
from gestao_cli import instrucoes_cartao, pasta_dados

SHA=re.compile(r'[0-9a-f]{40}\Z')


def _obrigatorios(k, sha, nomes):
    caminho=f'repos/{k.cfg["repo"]}/commits/{sha}'
    if k.chamar is api:
        runs=api(caminho+'/check-runs?per_page=100',paginar=True,campo='check_runs')
    else:
        envelope=k.chamar(caminho+'/check-runs?per_page=100')
        if (not isinstance(envelope,dict) or not isinstance(envelope.get('check_runs'),list)
            or type(envelope.get('total_count')) is not int
            or envelope['total_count']!=len(envelope['check_runs'])):
            raise ValueError('Cobertura dos checks incompleta')
        runs=envelope['check_runs']
    statuses=k._paginas(caminho+'/statuses')
    checks,gates=projetar_checks(runs,statuses,sha,nomes)
    if any(g['estado']!='success' for g in gates):
        raise ValueError('Check obrigatório ausente, ambíguo ou não aprovado')
    return {'checks':checks,'gates':gates}


def preparar(projeto,cartao,pr,banco=None,kanban=None):
    if type(cartao) is not int or cartao<1 or type(pr) is not int or pr<1:
        raise ValueError('Cartão e PR devem ser números positivos')
    cfg=carregar(projeto)
    if not cfg['ativo']:raise ValueError('Gestão desativada')
    arq=Path(banco or pasta_dados(projeto)/'tarefas.db')
    with closing(sqlite3.connect(arq.resolve().as_uri()+'?mode=ro',uri=True)) as db:
        db.row_factory=sqlite3.Row
        row=db.execute('SELECT * FROM reserva WHERE projeto=? AND cartao=?',
                       (cfg['kanban']['repo'],str(cartao))).fetchone()
        if not row or row['estado'] not in ('revisao','concluido'):
            raise ValueError('Conclusão exige reserva em revisão')
        reserva=dict(row); pacote=json.loads(row['pacote'])
        tem_conclusao=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='conclusao'").fetchone()
        anterior=db.execute('SELECT evidencia FROM conclusao WHERE token=?',(row['token'],)).fetchone() if tem_conclusao else None
        anterior=json.loads(anterior['evidencia']) if anterior else None
        entrega=db.execute('SELECT * FROM entrega WHERE token=?',(row['token'],)).fetchone()
    if reserva['estado']=='concluido' and not anterior:
        raise ValueError('Reserva concluída sem evidência de conclusão')
    ctx=pacote.get('contexto_execucao') or {}
    politica=hashlib.sha256(json.dumps(cfg,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    if ctx.get('politica_sha256')!=politica or not ctx.get('branch') or not ctx.get('worktree'):
        raise ValueError('Política ou contexto da reserva divergente')
    if fontes_resolvidas(projeto,cfg)!=pacote.get('fontes_resolvidas'):
        raise ValueError('Fontes do contexto foram alteradas')
    k=kanban or Kanban(cfg,pasta_dados(projeto)/'kanban.json',sem_escrita=True)
    atual=k.cartao(cartao,ao_vivo=True)
    estados={cfg['kanban']['revisao']}
    if anterior:estados.add(cfg['kanban']['feito'])
    if atual['status'] not in estados or atual['equipe']!=reserva['equipe'] or atual.get('prioridade','')!=pacote.get('prioridade',''):
        raise ValueError('Cartão diverge da reserva ou não está em revisão')
    issue=k.issue(cartao)
    if issue.get('state')!='closed' or issue.get('pull_request') or issue.get('html_url')!=pacote.get('url'):
        raise ValueError('Issue do cartão não está fechada no repositório esperado')
    if any(pacote.get(chave)!=valor for chave,valor in instrucoes_cartao(issue).items()):
        raise ValueError('Instruções do cartão mudaram')
    pull=k.chamar(f'repos/{cfg["kanban"]["repo"]}/pulls/{pr}')
    head=pull.get('head') or {}; repo=(head.get('repo') or {}).get('full_name')
    sha=head.get('sha'); merge=pull.get('merge_commit_sha')
    alvo=r'(?:#|(?:https://github\.com/)?'+re.escape(cfg['kanban']['repo'])+r'/(?:issues/|#))'
    vinculo=re.search(r'(?im)\b(?:Closes|Fixes|Resolves)\s+'+alvo+str(cartao)+r'(?!\d)',pull.get('body') or '')
    if (pull.get('number')!=pr or pull.get('state')!='closed' or pull.get('merged') is not True
        or not pull.get('merged_at') or not SHA.fullmatch(merge or '') or not SHA.fullmatch(sha or '')
        or (pull.get('base') or {}).get('repo',{}).get('full_name')!=cfg['kanban']['repo']
        or repo!=cfg['kanban']['repo'] or head.get('ref')!=ctx['branch'] or not vinculo):
        raise ValueError('PR/merge/branch/vínculo não comprovado')
    if cfg['revisao']['ativo']:
        from revisao_cruzada import conferir
        if not entrega or entrega['pr']!=pr or entrega['sha']!=sha or not conferir(cfg,json.loads(entrega['relatorio']),sha):
            raise ValueError('Revisão aprovada e vinculada ao head ausente')
    checks=_obrigatorios(k,sha,cfg['merge']['checks'])
    evidencia={'repo':cfg['kanban']['repo'],'cartao':cartao,'pr':pr,'branch':ctx['branch'],
               'head':sha,'merge_commit':merge,'merged_at':pull['merged_at'],
               'politica_sha256':politica,'checks':checks,'revisao':bool(cfg['revisao']['ativo'])}
    if anterior and anterior!=evidencia:raise ValueError('Evidência anterior diverge; concilie')
    if carregar(projeto)!=cfg:raise ValueError('Política mudou durante a conferência')
    return {'estado':'concluido' if reserva['estado']=='concluido' else 'pronto',
            'cartao':cartao,'pr':pr,'evidencia':evidencia,'apenas_previa':True},(k,reserva,atual,anterior)


def executar(projeto,cartao,pr,banco=None,kanban=None):
    previa,(k,reserva,atual,anterior)=preparar(projeto,cartao,pr,banco,kanban)
    if reserva['estado']=='concluido':return {**previa,'apenas_previa':False}
    cfg=carregar(projeto)
    if hashlib.sha256(json.dumps(cfg,sort_keys=True,ensure_ascii=False).encode()).hexdigest()!=previa['evidencia']['politica_sha256']:
        raise ValueError('Política mudou antes da conclusão')
    controle=Controle(banco or pasta_dados(projeto)/'tarefas.db')
    controle.registrar_conclusao(reserva['token'],previa['evidencia'])
    if carregar(projeto)!=cfg:raise ValueError('Política mudou antes de mover o cartão; concilie o diário')
    atual=k.cartao(cartao,ao_vivo=True)
    if atual['status'] not in (cfg['kanban']['revisao'],cfg['kanban']['feito']) or atual['equipe']!=reserva['equipe']:
        raise ValueError('Cartão mudou antes da conclusão; concilie o diário')
    if atual['status']==cfg['kanban']['revisao']:
        k.mover(cartao,cfg['kanban']['feito'])
    controle.concluir(reserva['token'])
    return {**previa,'estado':'concluido','apenas_previa':False}
