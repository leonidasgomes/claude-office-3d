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


def iniciar_acompanhamento_retomada(projeto,reserva,confirmacao,banco=None):
    """Intento após a confirmação manual; não seleciona ou retoma reservas."""
    import uuid
    cfg=carregar(projeto);ident=uuid.uuid4().hex
    if not re.fullmatch('[0-9a-f]{64}',confirmacao):raise ValueError('Confirmação inválida')
    with closing(sqlite3.connect(banco or pasta_dados(projeto)/'tarefas.db')) as db,db:
        row=db.execute('SELECT estado,pacote FROM reserva WHERE projeto=? AND cartao=? AND token=?',
            (cfg['kanban']['repo'],reserva['cartao'],reserva['token'])).fetchone()
        if not row or row[0]!='bloqueado' or json.loads(row[1])!=reserva['pacote']:
            raise ValueError('Reserva mudou antes do acompanhamento')
        anteriores=[r[0] for r in db.execute('SELECT id FROM execucao_tarefa WHERE token=?',(reserva['token'],))]
        db.execute('CREATE TABLE IF NOT EXISTS acompanhamento_retomada ('
            'id TEXT PRIMARY KEY,repo TEXT NOT NULL,cartao INTEGER NOT NULL,token TEXT NOT NULL,'
            'confirmacao TEXT NOT NULL,anteriores TEXT NOT NULL,estado TEXT NOT NULL,'
            'tentativa TEXT,pr INTEGER,sha TEXT)')
        db.execute('INSERT INTO acompanhamento_retomada VALUES (?,?,?,?,?,?,?,NULL,NULL,NULL)',
            (ident,cfg['kanban']['repo'],int(reserva['cartao']),reserva['token'],confirmacao,
             json.dumps(anteriores),'iniciado'))
    return ident


def registrar_acompanhamento_retomada(projeto,ident,resultado,banco=None):
    """Só retorno real com entrega validada permite acompanhar o merge."""
    with closing(sqlite3.connect(banco or pasta_dados(projeto)/'tarefas.db')) as db,db:
        db.row_factory=sqlite3.Row
        r=db.execute('SELECT * FROM acompanhamento_retomada WHERE id=?',(ident,)).fetchone()
        if not r or r['estado']!='iniciado':raise ValueError('Acompanhamento incerto ou já registrado')
        if resultado.get('token')!=r['token']:raise ValueError('Retorno de outra reserva')
        if resultado.get('estado')!='revisao' or type(resultado.get('codigo')) is not int or resultado['codigo']!=0:
            db.execute("UPDATE acompanhamento_retomada SET estado='bloqueado' WHERE id=?",(ident,));return
        anteriores=json.loads(r['anteriores'])
        ts=[t for t in db.execute('SELECT e.id,e.fim,e.codigo,x.tipo,x.resultado,a.estado AS atividade FROM execucao_tarefa e '
            'JOIN execucao_resultado x ON x.execucao=e.id LEFT JOIN atividade_execucao a ON a.execucao=e.id '
            'WHERE e.token=? ORDER BY e.inicio,e.id',(r['token'],))
            if t['id'] not in anteriores]
        entrega=db.execute('SELECT e.pr,e.sha,r.estado FROM entrega e JOIN reserva r ON r.token=e.token '
            'WHERE r.projeto=? AND r.cartao=? AND r.token=?',(r['repo'],str(r['cartao']),r['token'])).fetchone()
        if (not ts or ts[0]['tipo']!='retomada' or any(t['fim'] is None or type(t['codigo']) is not int or t['atividade']!='encerrado' for t in ts)
            or ts[-1]['codigo']!=0 or ts[-1]['resultado'] not in ('revisao_aprovada','revisao_desativada')
            or not entrega or entrega['estado']!='revisao' or type(entrega['pr']) is not int
            or entrega['pr']<1 or not SHA.fullmatch(entrega['sha'])):
            raise ValueError('Retomada sem tentativa/entrega confirmada; confira o diário')
        db.execute("UPDATE acompanhamento_retomada SET estado='confirmado',tentativa=?,pr=?,sha=? WHERE id=?",
            (ts[-1]['id'],entrega['pr'],entrega['sha'],ident))


def incorporar_retomadas_confirmadas(projeto,registro):
    """O ciclo observa retomadas manuais novas; jamais adota reservas históricas."""
    cfg=carregar(projeto);arq=pasta_dados(projeto)/'tarefas.db'
    if not arq.is_file():return
    novos=[]
    with closing(sqlite3.connect(arq.resolve().as_uri()+'?mode=ro',uri=True)) as db:
        db.row_factory=sqlite3.Row
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='acompanhamento_retomada'").fetchone():return
        rows=db.execute("SELECT a.* FROM acompanhamento_retomada a JOIN reserva r ON r.token=a.token "
            "AND r.projeto=a.repo AND r.cartao=CAST(a.cartao AS TEXT) JOIN entrega d ON d.token=r.token "
            "JOIN execucao_tarefa e ON e.id=a.tentativa AND e.token=r.token "
            "JOIN execucao_resultado x ON x.execucao=e.id "
            "JOIN atividade_execucao v ON v.execucao=e.id AND v.estado='encerrado' "
            "WHERE a.repo=? AND a.estado='confirmado' AND r.estado='revisao' AND d.pr=a.pr AND d.sha=a.sha "
            "AND e.fim IS NOT NULL AND e.codigo=0 AND x.resultado IN ('revisao_aprovada','revisao_desativada') "
            "AND NOT EXISTS (SELECT 1 FROM execucao_tarefa n WHERE n.token=r.token AND "
            "(n.fim IS NULL OR n.inicio>e.inicio OR (n.inicio=e.inicio AND n.id>e.id))) LIMIT 1001",(cfg['kanban']['repo'],)).fetchall()
        if len(rows)>1000:raise ValueError('Retomadas demais; confira acompanhamento')
        for r in rows:
            if r['id'] in registro.get('retomadas_incorporadas',[]):continue
            existente=[v for v in registro.get('vinculos_conclusao',[]) if v.get('cartao')==r['cartao'] or v.get('token')==r['token']]
            if existente:
                if existente!=[{'cartao':r['cartao'],'token':r['token']}]:raise ValueError('Vínculo de retomada divergente')
            if any(n['cartao']==r['cartao'] or n['token']==r['token'] for n in novos):
                raise ValueError('Retomadas confirmadas duplicadas; confira diário')
            novos.append(dict(r))
    for r in novos:
        if not any(v['token']==r['token'] for v in registro.get('vinculos_conclusao',[])):
            registro.setdefault('vinculos_conclusao',[]).append({'cartao':r['cartao'],'token':r['token']})
            registro.setdefault('resultados',[]).append({'id':r['id'],'origem':'retomada_manual_confirmada',
                'resultados':[{'cartao':r['cartao'],'estado':'revisao','codigo':0}]})
        anteriores=[c for c in registro.get('conclusoes',[]) if c.get('token')==r['token'] and c.get('estado')=='bloqueado']
        if anteriores:
            registro.setdefault('conclusoes_anteriores',[]).extend(anteriores)
            registro['conclusoes']=[c for c in registro['conclusoes'] if c not in anteriores]
        registro.setdefault('retomadas_incorporadas',[]).append(r['id'])


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
    if issue.get('state') not in ('open','closed') or issue.get('pull_request') or issue.get('html_url')!=pacote.get('url'):
        raise ValueError('Issue do cartão não está no repositório esperado')
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
    # GitHub não fecha automaticamente Closes #N quando a base não é a branch
    # padrão. Só fechar após provar merge, vínculo integral, revisão e gates.
    issue=k.issue(cartao)
    pacote=json.loads(reserva['pacote'])
    if (issue.get('html_url')!=pacote.get('url') or issue.get('pull_request')
        or issue.get('state') not in ('open','closed')
        or any(pacote.get(chave)!=valor for chave,valor in instrucoes_cartao(issue).items())):
        raise ValueError('Issue mudou antes da conclusão; concilie o diário')
    if issue['state']=='open':
        resposta=k.chamar(f'repos/{cfg["kanban"]["repo"]}/issues/{cartao}','PATCH',{'state':'closed'})
        if resposta.get('state')!='closed' or resposta.get('html_url')!=pacote.get('url'):
            raise ValueError('Fechamento da issue não comprovado; confira o diário')
    if carregar(projeto)!=cfg:raise ValueError('Política mudou após fechar a issue; concilie o diário')
    atual=k.cartao(cartao,ao_vivo=True)
    if atual['status'] not in (cfg['kanban']['revisao'],cfg['kanban']['feito']) or atual['equipe']!=reserva['equipe']:
        raise ValueError('Cartão mudou antes da conclusão; concilie o diário')
    if atual['status']==cfg['kanban']['revisao']:
        k.mover(cartao,cfg['kanban']['feito'])
    controle.concluir(reserva['token'])
    return {**previa,'estado':'concluido','apenas_previa':False}


def vincular_despacho(projeto,item):
    """Vínculo privado ao worktree novo, após retorno confirmado do lote."""
    cfg=carregar(projeto);banco=pasta_dados(projeto)/'tarefas.db'
    if not banco.is_file():return None
    with closing(sqlite3.connect(banco.resolve().as_uri()+'?mode=ro',uri=True)) as db:
        row=db.execute('SELECT token,pacote FROM reserva WHERE projeto=? AND cartao=? AND estado=?',
                       (cfg['kanban']['repo'],str(item['cartao']),'revisao')).fetchone()
    if not row:return None
    contexto=json.loads(row[1]).get('contexto_execucao',{})
    if Path(contexto.get('worktree','')).resolve()!=Path(item['worktree']).resolve():return None
    return {'cartao':item['cartao'],'token':row[0]}


def confirmar_sessao(projeto,registro):
    """Somente entregas desta sessão; nunca retoma reservas ou faz merge."""
    cfg=carregar(projeto)
    if cfg['merge'].get('modo')!='automatico':return []
    banco=pasta_dados(projeto)/'tarefas.db'
    if not banco.is_file():return []
    feitos=registro.get('conclusoes',[]);novos=[]
    from finalizacao_publicada import vinculo_confirmado
    for item in registro.get('vinculos_conclusao',[]):
        retornos=[r for lote in registro.get('resultados',[]) for r in lote.get('resultados',[])
                  if r.get('cartao')==item.get('cartao') and r.get('estado')=='revisao' and r.get('codigo')==0]
        token=item.get('token');n=item.get('cartao')
        finalizado=vinculo_confirmado(projeto,registro,item)
        if (len(retornos)+int(finalizado)!=1
            or not isinstance(token,str) or not re.fullmatch('[0-9a-f]{32}',token)
            or type(n) is not int or n<1 or any(r.get('token')==token for r in feitos)):
            continue
        with closing(sqlite3.connect(banco.resolve().as_uri()+'?mode=ro',uri=True)) as db:
            row=db.execute('SELECT r.estado,e.pr FROM reserva r JOIN entrega e ON e.token=r.token '
                'WHERE r.projeto=? AND r.cartao=? AND r.token=?',
                (cfg['kanban']['repo'],str(n),token)).fetchone()
        if not row or row[0]!='revisao':continue
        pr=api(f'repos/{cfg["kanban"]["repo"]}/pulls/{row[1]}')
        if pr.get('merged') is not True:continue
        try:
            resultado=executar(projeto,n,row[1])
            novos.append({'token':token,**resultado})
        except (ValueError,OSError,sqlite3.Error) as exc:
            novos.append({'token':token,'cartao':n,'pr':row[1],'estado':'bloqueado',
                          'motivo':str(exc),'acao':'conferir conclusão; não repetir automaticamente'})
    return novos


def pendencias_sessao(projeto,registro):
    """PRs de entregas confirmadas desta sessão; sem adoção/retomada de histórico."""
    cfg=carregar(projeto);banco=pasta_dados(projeto)/'tarefas.db'
    vinculos=registro.get('vinculos_conclusao',[])
    if not vinculos:return []
    if not isinstance(vinculos,list) or len(vinculos)>1000:
        raise ValueError('Vínculos da sessão inválidos; confira Gestão')
    retornos=[r for lote in registro.get('resultados',[]) for r in lote.get('resultados',[])
              if r.get('estado')=='revisao' and r.get('codigo')==0]
    feitos=registro.get('conclusoes',[]);saida=[];vistos=set()
    from finalizacao_publicada import vinculo_confirmado
    with closing(sqlite3.connect(banco.resolve().as_uri()+'?mode=ro',uri=True)) as db:
        db.row_factory=sqlite3.Row
        for item in vinculos:
            n=item.get('cartao');token=item.get('token')
            if (type(n) is not int or n<1 or not isinstance(token,str)
                or not re.fullmatch('[0-9a-f]{32}',token) or token in vistos
                or sum(r.get('cartao')==n for r in retornos)+int(vinculo_confirmado(projeto,registro,item))!=1):
                raise ValueError('Vínculo da entrega ambíguo; confira Gestão')
            vistos.add(token)
            if any(r.get('token')==token and r.get('estado')=='concluido' for r in feitos):continue
            row=db.execute('SELECT r.estado,r.equipe,e.pr,e.sha FROM reserva r '
                'JOIN entrega e ON e.token=r.token WHERE r.projeto=? AND r.cartao=? AND r.token=?',
                (cfg['kanban']['repo'],str(n),token)).fetchone()
            if not row or row['estado'] not in ('revisao','concluido'):
                raise ValueError('Entrega da sessão mudou; confira Gestão')
            if row['estado']=='concluido':continue
            if type(row['pr']) is not int or row['pr']<1 or not SHA.fullmatch(row['sha'] or ''):
                raise ValueError('PR da entrega inválido; confira Gestão')
            falha=next((r for r in feitos if r.get('token')==token and r.get('estado')=='bloqueado'),None)
            saida.append({'cartao':n,'equipe':row['equipe'],'pr':row['pr'],'head':row['sha'],
                'estado':'conferencia_necessaria' if falha else 'aguardando_merge',
                'motivo':falha.get('motivo','') if falha else ''})
    return saida
