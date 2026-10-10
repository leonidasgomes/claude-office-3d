"""Retomada explícita pelo PC; sem aceitar paths/sessões enviados pelo navegador."""
from contextlib import closing,nullcontext
import json,math,re,sqlite3,subprocess,threading,time,uuid

_ativos={}
_lock=threading.Lock()


def abrir(projeto,escrever=False):
    from gestao_cli import pasta_dados
    arq=pasta_dados(projeto)/'pedidos_retomada.db'
    if arq.is_symlink():raise ValueError('Banco de pedidos inválido')
    if escrever:
        arq.parent.mkdir(parents=True,exist_ok=True)
        db=sqlite3.connect(arq,timeout=5)
        db.execute('CREATE TABLE IF NOT EXISTS pedido_retomada ('
            'id TEXT PRIMARY KEY,repo TEXT NOT NULL,cartao INTEGER NOT NULL,estado TEXT NOT NULL,'
            'atualizado REAL NOT NULL,resultado TEXT,codigo INTEGER)')
        db.execute('CREATE TABLE IF NOT EXISTS retomada_contexto ('
            'pedido TEXT PRIMARY KEY,reserva TEXT,execucao TEXT,sha_conciliacao TEXT)')
        db.commit();return db
    if not arq.is_file():return None
    return sqlite3.connect(arq.resolve().as_uri()+'?mode=ro',uri=True,timeout=5)


def atualizar(projeto,ident,estado,resultado=None,codigo=None):
    with closing(abrir(projeto,True)) as db,db:
        if db.execute('UPDATE pedido_retomada SET estado=?,atualizado=?,resultado=?,codigo=? WHERE id=?',
            (estado,time.time(),resultado,codigo,ident)).rowcount!=1:raise ValueError('Pedido indisponível')


def localizar(projeto,numero):
    from gestao_cli import pasta_dados
    from gestao_projeto import carregar
    cfg=carregar(projeto)
    arq=pasta_dados(projeto)/'tarefas.db'
    with closing(sqlite3.connect(arq.resolve().as_uri()+'?mode=ro',uri=True,timeout=5)) as db:
        linha=db.execute('SELECT pacote FROM reserva WHERE projeto=? AND cartao=?',
            (cfg['kanban']['repo'],str(numero))).fetchone()
    if not linha:raise ValueError('Reserva indisponível')
    contexto=json.loads(linha[0]).get('contexto_execucao') or {}
    from pathlib import Path
    caminho=contexto.get('worktree')
    if not isinstance(caminho,str) or not Path(caminho).is_absolute():raise ValueError('Worktree sem vínculo')
    return Path(caminho)


def trabalhar(projeto,ident,numero,trabalho,confirmacao,versao):
    try:
        from politica_painel import snapshot
        from gestao_cli import retomar
        if snapshot(projeto)[1]!=versao:raise ValueError('Política mudou')
        atualizar(projeto,ident,'executando')
        r=retomar(projeto,numero,trabalho,confirmacao,agentes_conciliados=True,
            ao_execucao=lambda token,tentativa:vincular(projeto,ident,token,tentativa))
        if r.get('estado') not in ('bloqueado','revisao') or type(r.get('codigo')) is not int:
            raise ValueError('Retorno indisponível')
        atualizar(projeto,ident,'concluida',r['estado'],r['codigo'])
    except BaseException:
        try:atualizar(projeto,ident,'incerto')
        except Exception:pass
    finally:
        with _lock:_ativos.pop(ident,None)


def api(projetos,dados,ident):
    if ident.get('permissao')!='pc':return 403,{'erro':'Retomada disponível somente no PC'}
    campos={'projeto_id','versao','cartao','acao'}
    acao=dados.get('acao') if isinstance(dados,dict) else None
    if (acao not in ('previa','executar') or set(dados)!=(campos|({'confirmacao','agentes_conciliados'} if acao=='executar' else set()))
        or type(dados.get('cartao')) is not int or not 1<=dados['cartao']<=2**53-1):
        return 400,{'erro':'Pedido de retomada inválido'}
    if acao=='executar' and (dados['agentes_conciliados'] is not True or not isinstance(dados['confirmacao'],str)
        or not re.fullmatch('[0-9a-f]{64}',dados['confirmacao'])):
        return 400,{'erro':'Confira a prévia e os agentes/ferramentas antes de retomar'}
    from funcionarios import id_projeto
    from politica_painel import snapshot
    from gestao_cli import preparar_retomada
    projeto=next((p for p in projetos if id_projeto(p)==dados['projeto_id']),None)
    if projeto is None:return 400,{'erro':'Projeto não configurado'}
    try:
        cfg,versao,_=snapshot(projeto)
        if not cfg['ativo'] or dados['versao']!=versao:return 409,{'erro':'Política mudou; recarregue Gestão'}
        trabalho=localizar(projeto,dados['cartao'])
        previa=preparar_retomada(projeto,dados['cartao'],trabalho)[0]
        if acao=='previa':return 200,previa
        if previa['confirmacao']!=dados['confirmacao']:return 409,{'erro':'Prévia mudou; confira novamente'}
        with _lock:
            if any(t.is_alive() for t in _ativos.values()):return 409,{'erro':'Já há retomada acompanhada neste escritório'}
            with closing(abrir(projeto,True)) as db,db:
                db.execute('BEGIN IMMEDIATE')
                if db.execute("SELECT 1 FROM pedido_retomada WHERE repo=? AND cartao=? AND estado IN ('recebida','executando','incerto')",
                    (cfg['kanban']['repo'],dados['cartao'])).fetchone():
                    return 409,{'erro':'Pedido anterior exige acompanhamento/conciliação no PC'}
                pedido=uuid.uuid4().hex
                db.execute('INSERT INTO pedido_retomada VALUES (?,?,?,?,?,NULL,NULL)',
                    (pedido,cfg['kanban']['repo'],dados['cartao'],'recebida',time.time()))
                db.execute('INSERT INTO retomada_contexto VALUES (?,NULL,NULL,NULL)',(pedido,))
            t=threading.Thread(target=trabalhar,args=(projeto,pedido,dados['cartao'],trabalho,dados['confirmacao'],versao),
                daemon=True,name='office-retomada')
            _ativos[pedido]=t
            try:t.start()
            except BaseException:
                _ativos.pop(pedido,None);atualizar(projeto,pedido,'incerto');raise
        return 202,{'pedido_id':pedido,'estado':'recebida'}
    except (ValueError,TypeError,KeyError,OSError,sqlite3.Error,RuntimeError,subprocess.SubprocessError):
        return 409,{'erro':'Retomada indisponível; confira reserva, Kanban, console e worktree no PC'}


def resumo(projeto,repo):
    saida={'itens':[],'problemas':0,'limitado':False}
    try:
        db=abrir(projeto)
        if db is None:return saida
        with closing(db):linhas=db.execute('SELECT id,cartao,estado,atualizado,resultado,codigo FROM pedido_retomada WHERE repo=? '
            'ORDER BY atualizado DESC,id DESC LIMIT 11',(repo,)).fetchall()
        saida['limitado']=len(linhas)>10
        with _lock:ativos={k:t.is_alive() for k,t in _ativos.items()}
        for ident,numero,estado,atualizado,resultado,codigo in linhas[:10]:
            if (not isinstance(ident,str) or not re.fullmatch('[0-9a-f]{32}',ident)
                or type(numero) is not int or not 1<=numero<=2**53-1 or estado not in ('recebida','executando','concluida','conciliada','incerto')
                or type(atualizado) not in (int,float) or not math.isfinite(atualizado) or not 0<atualizado<1e12
                or (estado in ('concluida','conciliada') and (resultado not in ('bloqueado','revisao') or type(codigo) is not int))
                or (estado not in ('concluida','conciliada') and (resultado is not None or codigo is not None))):
                saida['problemas']+=1;continue
            if estado in ('recebida','executando') and not ativos.get(ident):estado='incerto'
            saida['itens'].append({'id':ident,'cartao':numero,'estado':estado,'atualizado':atualizado,'resultado':resultado,'codigo':codigo})
    except (ValueError,TypeError,OSError,sqlite3.Error):saida['problemas']+=1
    return saida


def vincular(projeto,pedido,token,tentativa):
    """Vínculo privado e imutável antes do launcher; falha impede inferência."""
    if any(not isinstance(v,str) or not re.fullmatch('[0-9a-f]{32}',v) for v in (pedido,token,tentativa)):
        raise ValueError('Vínculo de retomada inválido')
    from gestao_cli import pasta_dados
    arq=pasta_dados(projeto)/'tarefas.db'
    with closing(sqlite3.connect(arq.resolve().as_uri()+'?mode=ro',uri=True,timeout=5)) as tarefas:
        t=tarefas.execute('SELECT r.projeto,r.cartao,r.estado,e.fim FROM reserva r JOIN execucao_tarefa e ON e.token=r.token '
            'WHERE r.token=? AND e.id=?',(token,tentativa)).fetchone()
    with closing(abrir(projeto,True)) as db,db:
        db.execute('BEGIN IMMEDIATE')
        linha=db.execute('SELECT p.repo,p.cartao,p.estado,c.reserva,c.execucao FROM pedido_retomada p '
            'JOIN retomada_contexto c ON c.pedido=p.id WHERE p.id=?',(pedido,)).fetchone()
        if (not linha or not t or (linha[0],str(linha[1]))!=t[:2] or linha[2]!='executando'
            or t[2]!='executando' or t[3] is not None
            or (linha[3] is not None and (linha[3],linha[4])!=(token,tentativa))):
            raise ValueError('Tentativa diverge do pedido de retomada')
        db.execute('UPDATE retomada_contexto SET reserva=?,execucao=? WHERE pedido=?',(token,tentativa,pedido))


def evidencia_conciliacao(projeto,pedido,repo,db,tarefas=None):
    """Confere retorno da tentativa vinculada, sem liberar reserva/processos/travas."""
    linha=db.execute('SELECT repo,cartao,estado,atualizado,resultado,codigo FROM pedido_retomada WHERE id=?',(pedido,)).fetchone()
    if not linha or linha[0]!=repo or linha[2] not in ('recebida','executando','incerto'):
        raise ValueError('Pedido indisponível para conciliação')
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='retomada_contexto'").fetchone():
        raise ValueError('Pedido histórico sem vínculo; confira no PC')
    ctx=db.execute('SELECT reserva,execucao FROM retomada_contexto WHERE pedido=?',(pedido,)).fetchone()
    if not ctx or any(not isinstance(v,str) or not re.fullmatch('[0-9a-f]{32}',v) for v in ctx):
        raise ValueError('Pedido sem tentativa vinculada; mantenha bloqueado')
    from gestao_cli import pasta_dados
    arq=pasta_dados(projeto)/'tarefas.db'
    with (closing(sqlite3.connect(arq.resolve().as_uri()+'?mode=ro',uri=True,timeout=5)) if tarefas is None else nullcontext(tarefas)) as tarefas:
        tarefas.row_factory=sqlite3.Row
        reserva=tarefas.execute('SELECT * FROM reserva WHERE token=? AND projeto=? AND cartao=?',
            (ctx[0],repo,str(linha[1]))).fetchone()
        tentativa=tarefas.execute('SELECT * FROM execucao_tarefa WHERE id=? AND token=?',ctx[::-1]).fetchone()
        ultima=tarefas.execute('SELECT id FROM execucao_tarefa WHERE token=? ORDER BY inicio DESC,id DESC LIMIT 1',(ctx[0],)).fetchone()
        atividade=tarefas.execute('SELECT * FROM atividade_execucao WHERE execucao=?',(ctx[1],)).fetchone()
        if (not reserva or reserva['estado'] not in ('bloqueado','revisao') or not tentativa or not ultima or ultima['id']!=ctx[1]
            or tentativa['console']!=reserva['console'] or type(tentativa['codigo']) is not int
            or any(type(tentativa[c]) not in (int,float) or not math.isfinite(tentativa[c]) for c in ('inicio','fim','duracao_seg'))
            or tentativa['fim']<tentativa['inicio'] or tentativa['duracao_seg']<0
            or not atividade or atividade['estado']!='encerrado' or type(atividade['codigo_console']) is not int):
            raise ValueError('Tentativa sem retorno conclusivo ou alterada; mantenha bloqueado')
        privado={'pedido':linha,'contexto':ctx,'reserva':dict(reserva),'tentativa':dict(tentativa),'atividade':dict(atividade)}
    import hashlib
    sha=hashlib.sha256(json.dumps(privado,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    return {'pedido_id':pedido,'cartao':linha[1],'resultado':reserva['estado'],'codigo':tentativa['codigo'],'evidencia_sha256':sha}


def api_conciliar(projetos,dados,ident):
    if ident.get('permissao')!='pc':return 403,{'erro':'Conciliação disponível somente no PC'}
    campos={'projeto_id','versao','pedido_id','acao'}
    acao=dados.get('acao') if isinstance(dados,dict) else None
    if (acao not in ('previa','aplicar') or set(dados)!=(campos|({'evidencia_sha256'} if acao=='aplicar' else set()))
        or not isinstance(dados.get('pedido_id'),str) or not re.fullmatch('[0-9a-f]{32}',dados['pedido_id'])
        or (acao=='aplicar' and (not isinstance(dados['evidencia_sha256'],str) or not re.fullmatch('[0-9a-f]{64}',dados['evidencia_sha256'])))):
        return 400,{'erro':'Pedido de conciliação inválido'}
    from funcionarios import id_projeto
    from politica_painel import snapshot
    projeto=next((p for p in projetos if id_projeto(p)==dados['projeto_id']),None)
    if projeto is None:return 400,{'erro':'Projeto não configurado'}
    try:
        cfg,versao,_=snapshot(projeto)
        if dados['versao']!=versao:return 409,{'erro':'Política mudou; recarregue Gestão'}
        with _lock:
            t=_ativos.get(dados['pedido_id'])
            if t and t.is_alive():return 409,{'erro':'Pedido acompanhado; aguarde o retorno'}
            db=abrir(projeto)
            if db is None:return 409,{'erro':'Pedido indisponível'}
            with closing(db):e=evidencia_conciliacao(projeto,dados['pedido_id'],cfg['kanban']['repo'],db)
            if acao=='previa':return 200,{**e,'somente_preparacao':True}
            if dados['evidencia_sha256']!=e['evidencia_sha256']:return 409,{'erro':'Evidência mudou; confira novamente'}
            from gestao_cli import pasta_dados
            arq=pasta_dados(projeto)/'tarefas.db'
            with closing(abrir(projeto,True)) as db,closing(sqlite3.connect(arq.resolve().as_uri()+'?mode=ro',uri=True,timeout=5)) as tarefas:
                # Segura o snapshot de tarefas até o commit do ledger, sem escrever nele.
                if tarefas.execute('PRAGMA journal_mode').fetchone()[0] not in ('delete','truncate','persist'):
                    raise ValueError('Modo do banco sem trava de leitura compatível')
                tarefas.execute('BEGIN')
                with db:
                    db.execute('BEGIN IMMEDIATE')
                    atual=evidencia_conciliacao(projeto,dados['pedido_id'],cfg['kanban']['repo'],db,tarefas)
                    if atual!=e or snapshot(projeto)[1]!=versao:raise ValueError('Evidência mudou')
                    db.execute('UPDATE pedido_retomada SET estado=?,atualizado=?,resultado=?,codigo=? WHERE id=?',
                        ('conciliada',time.time(),e['resultado'],e['codigo'],dados['pedido_id']))
                    db.execute('UPDATE retomada_contexto SET sha_conciliacao=? WHERE pedido=?',(e['evidencia_sha256'],dados['pedido_id']))
        return 200,{**e,'estado':'conciliada'}
    except (ValueError,TypeError,KeyError,OSError,sqlite3.Error):
        return 409,{'erro':'Retorno não conciliável; mantenha o pedido bloqueado e confira no PC'}
