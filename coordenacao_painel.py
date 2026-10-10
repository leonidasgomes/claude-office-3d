"""Pedidos pelo PC; consulta e execução registrada têm rotas separadas."""
from contextlib import closing
import json
import hashlib
import re
import sqlite3
import threading
import time
import uuid
from pathlib import Path

_ativos={}
_lock=threading.Lock()


def abrir(projeto,escrever=False):
    from coordenacao_registro import arquivo
    arq=arquivo(projeto).with_name('pedidos_coordenacao.db')
    if arq.is_symlink():raise ValueError('Banco de pedidos inválido')
    if escrever:
        arq.parent.mkdir(parents=True,exist_ok=True)
        db=sqlite3.connect(arq,timeout=5)
        db.execute('CREATE TABLE IF NOT EXISTS pedido (id TEXT PRIMARY KEY,repo TEXT NOT NULL,estado TEXT NOT NULL,atualizado REAL NOT NULL,recibo TEXT)')
        db.execute('CREATE TABLE IF NOT EXISTS pedido_contexto (id TEXT PRIMARY KEY,tipo TEXT NOT NULL,sha_conciliacao TEXT)')
        db.commit();return db
    if not arq.exists():return None
    return sqlite3.connect(arq.resolve().as_uri()+'?mode=ro',uri=True,timeout=5)


def atualizar(projeto,ident,estado,recibo=None):
    with closing(abrir(projeto,True)) as db,db:
        if db.execute('UPDATE pedido SET estado=?,atualizado=?,recibo=COALESCE(?,recibo) WHERE id=?',(estado,time.time(),recibo,ident)).rowcount!=1:
            raise ValueError('Pedido indisponível para vincular o recibo')


def trabalhar(projeto,ident,versao,plano,solicitacao):
    try:
        from politica_painel import snapshot
        from coordenacao import coordenar
        if snapshot(projeto)[1]!=versao:raise ValueError('Política mudou antes da consulta')
        atualizar(projeto,ident,'consultando')
        r=coordenar(projeto,plano,solicitacao,consultar=True,versao_politica=versao,
                    ao_recibo=lambda r:atualizar(projeto,ident,'consultando',r))
        recibo=r.get('recibo_id')
        if not isinstance(recibo,str) or not re.fullmatch('[0-9a-f]{32}',recibo):raise ValueError('Recibo indisponível')
        atualizar(projeto,ident,'concluida',recibo)
    except BaseException:
        # Não copia mensagens nativas, prompts ou paths na resposta pública.
        try:atualizar(projeto,ident,'incerto')
        except Exception:pass
    finally:
        with _lock:_ativos.pop(ident,None)


def api_consultar(projetos,dados,ident):
    if ident.get('permissao')!='pc':return 403,{'erro':'Consulta disponível somente no PC'}
    if not isinstance(dados,dict) or set(dados)!={'projeto_id','versao','plano','solicitacao'}:
        return 400,{'erro':'Pedido inválido'}
    from funcionarios import id_projeto
    from politica_painel import snapshot
    projeto=next((p for p in projetos if id_projeto(p)==dados['projeto_id']),None)
    if projeto is None:return 400,{'erro':'Projeto não configurado'}
    solicitacao=dados['solicitacao'];plano=dados['plano']
    if (not isinstance(solicitacao,str) or not solicitacao.strip() or len(solicitacao)>16000
        or not isinstance(plano,dict) or set(plano)-{'cartoes','paralelismo'}
        or not isinstance(plano.get('cartoes'),list) or not 1<=len(plano['cartoes'])<=20
        or len(json.dumps(plano,ensure_ascii=False))>64000):return 400,{'erro':'Informe objetivo e lote de candidatos válidos'}
    if type(plano.get('paralelismo',1)) is not int or not 1<=plano.get('paralelismo',1)<=4:
        return 400,{'erro':'Paralelismo inválido'}
    for item in plano['cartoes']:
        if (not isinstance(item,dict) or set(item)-{'cartao','worktree','escopo','funcionario'}
            or type(item.get('cartao')) is not int or item['cartao']<1
            or not isinstance(item.get('worktree'),str) or not Path(item['worktree']).is_absolute()
            or item.get('escopo','implementacao') not in ('planejamento','implementacao','revisao','simples')
            or ('funcionario' in item and (not isinstance(item['funcionario'],str) or len(item['funcionario'])>100))):
            return 400,{'erro':'Cartão ou worktree inválido'}
    try:
        cfg,versao,_=snapshot(projeto)
        if not cfg['ativo']:return 400,{'erro':'Gestão não habilitada'}
        if any(cfg[p].get('execucao','cloud')!='cloud' for p in ('ceo','diretor')):
            return 400,{'erro':'Consulta estruturada exige CEO e diretor cloud'}
        if not versao or dados['versao']!=versao:return 409,{'erro':'Política mudou; recarregue o painel'}
        with _lock:
            if any(t.is_alive() for t in _ativos.values()):return 409,{'erro':'Já há consulta do painel em andamento neste escritório'}
            with closing(abrir(projeto,True)) as db,db:
                db.execute('BEGIN IMMEDIATE')
                if db.execute("SELECT 1 FROM pedido WHERE repo=? AND estado IN ('recebida','consultando','executando','incerto') LIMIT 1",(cfg['kanban']['repo'],)).fetchone():
                    return 409,{'erro':'Pedido anterior exige acompanhamento/conciliação no PC'}
                ident_pedido=uuid.uuid4().hex
                db.execute('INSERT INTO pedido VALUES (?,?,?,?,NULL)',(ident_pedido,cfg['kanban']['repo'],'recebida',time.time()))
                db.execute('INSERT INTO pedido_contexto VALUES (?,?,NULL)',(ident_pedido,'consulta'))
            thread=threading.Thread(target=trabalhar,args=(projeto,ident_pedido,versao,plano,solicitacao),daemon=True,name='office-coordenacao')
            _ativos[ident_pedido]=thread
            try:thread.start()
            except BaseException:
                _ativos.pop(ident_pedido,None);atualizar(projeto,ident_pedido,'incerto');raise
        return 202,{'pedido_id':ident_pedido,'estado':'recebida'}
    except (ValueError,TypeError,OSError,sqlite3.Error,RuntimeError):return 400,{'erro':'Não foi possível iniciar a consulta; confira no PC'}


def trabalhar_execucao(projeto,ident,recibo,soma,versao):
    try:
        from coordenacao_execucao import executar
        atualizar(projeto,ident,'executando',recibo)
        executar(projeto,recibo,soma,versao)
        atualizar(projeto,ident,'concluida',recibo)
    except BaseException:
        try:atualizar(projeto,ident,'incerto',recibo)
        except Exception:pass
    finally:
        with _lock:_ativos.pop(ident,None)


def api_executar(projetos,dados,ident):
    if ident.get('permissao')!='pc':return 403,{'erro':'Execução disponível somente no PC'}
    if not isinstance(dados,dict) or set(dados)!={'projeto_id','versao','recibo_id','plano_sha256'}:
        return 400,{'erro':'Pedido inválido; use a seleção registrada'}
    from funcionarios import id_projeto
    from politica_painel import snapshot
    from coordenacao_execucao import recibo
    projeto=next((p for p in projetos if id_projeto(p)==dados['projeto_id']),None)
    if projeto is None:return 400,{'erro':'Projeto não configurado'}
    if not re.fullmatch('[0-9a-f]{32}',str(dados['recibo_id'])) or not re.fullmatch('[0-9a-f]{64}',str(dados['plano_sha256'])):
        return 400,{'erro':'Identidade da seleção inválida'}
    try:
        cfg,versao,_=snapshot(projeto);r=recibo(projeto,dados['recibo_id'])
        if (not cfg['ativo'] or dados['versao']!=versao or r['repo']!=cfg['kanban']['repo']
            or r['estado']!='organizado' or r.get('plano_sha256')!=dados['plano_sha256']):
            return 409,{'erro':'Seleção ou política mudou; confira no PC'}
        with _lock:
            if any(t.is_alive() for t in _ativos.values()):return 409,{'erro':'Já há pedido do painel em andamento'}
            with closing(abrir(projeto,True)) as db,db:
                db.execute('BEGIN IMMEDIATE')
                if db.execute("SELECT 1 FROM pedido WHERE repo=? AND estado IN ('recebida','consultando','executando','incerto') LIMIT 1",(r['repo'],)).fetchone():
                    return 409,{'erro':'Pedido anterior exige acompanhamento/conciliação no PC'}
                pedido_id=uuid.uuid4().hex
                db.execute('INSERT INTO pedido VALUES (?,?,?,?,?)',(pedido_id,r['repo'],'recebida',time.time(),r['id']))
                db.execute('INSERT INTO pedido_contexto VALUES (?,?,NULL)',(pedido_id,'execucao'))
            t=threading.Thread(target=trabalhar_execucao,args=(projeto,pedido_id,r['id'],dados['plano_sha256'],versao),
                               daemon=True,name='office-despacho')
            _ativos[pedido_id]=t
            try:t.start()
            except BaseException:
                _ativos.pop(pedido_id,None);atualizar(projeto,pedido_id,'incerto',r['id']);raise
        return 202,{'pedido_id':pedido_id,'estado':'recebida'}
    except (ValueError,TypeError,KeyError,OSError,sqlite3.Error,RuntimeError):
        return 400,{'erro':'Não foi possível iniciar a seleção registrada; confira no PC'}


def resumo(projeto,repo):
    saida={'itens':[],'problemas':0,'limitado':False}
    try:
        db=abrir(projeto)
        if db is None:return saida
        with closing(db):linhas=db.execute('SELECT id,estado,atualizado,recibo FROM pedido WHERE repo=? ORDER BY atualizado DESC,id DESC LIMIT 11',(repo,)).fetchall()
        saida['limitado']=len(linhas)>10
        with _lock:ativos={k:t.is_alive() for k,t in _ativos.items()}
        for ident,estado,atualizado,recibo in linhas[:10]:
            if (not re.fullmatch('[0-9a-f]{32}',str(ident)) or estado not in ('recebida','consultando','executando','concluida','conciliada','incerto')
                or type(atualizado) not in (int,float) or not 0<atualizado<1e12
                or (recibo is not None and not re.fullmatch('[0-9a-f]{32}',str(recibo)))):
                saida['problemas']+=1;continue
            if estado in ('recebida','consultando','executando') and not ativos.get(ident):estado='incerto'
            saida['itens'].append({'id':ident,'estado':estado,'atualizado':atualizado,'recibo_id':recibo})
    except (ValueError,TypeError,OSError,sqlite3.Error):saida['problemas']+=1
    return saida


def evidencia_conciliacao(projeto,pedido,repo,db):
    """Repara só o acompanhamento do pedido; nunca libera reservas ou processos."""
    from coordenacao_execucao import recibo
    linha=db.execute('SELECT repo,estado,atualizado,recibo FROM pedido WHERE id=?',(pedido,)).fetchone()
    if not linha or linha[0]!=repo:raise ValueError('Pedido não pertence ao projeto')
    if linha[1] not in ('recebida','consultando','executando','incerto'):
        raise ValueError('Pedido já tem retorno final')
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='pedido_contexto'").fetchone():
        raise ValueError('Pedido histórico sem vínculo verificável; confira no PC')
    contexto=db.execute('SELECT tipo FROM pedido_contexto WHERE id=?',(pedido,)).fetchone()
    if not contexto or contexto[0] not in ('consulta','execucao') or not linha[3]:
        raise ValueError('Pedido sem vínculo verificável; confira no PC')
    r=recibo(projeto,linha[3])
    if r['repo']!=repo:raise ValueError('Recibo de outro projeto')
    lote=None
    if contexto[0]=='consulta':
        if r['estado'] not in ('organizado','bloqueado','processado','interrompido'):
            raise ValueError('Consulta sem decisão conclusiva; mantenha bloqueado')
    else:
        if r['estado'] not in ('processado','interrompido'):
            raise ValueError('Despacho sem retorno conclusivo; mantenha bloqueado')
        from gestao_painel import lotes
        lote=next(iter(lotes(projeto,repo,ident=r['lote_id'])['itens']),None)
        if (not lote or lote['estado']!=r['estado'] or lote['cartao_em_execucao'] is not None
            or lote.get('cartoes_em_execucao') or set(lote['cartoes'])!=set(r['diretor']['cartoes'])):
            raise ValueError('Lote ausente, divergente ou pendente; mantenha bloqueado')
    sha=hashlib.sha256(json.dumps({'pedido':linha,'tipo':contexto[0],'recibo':r,'lote':lote},
                               ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    return {'pedido_id':pedido,'recibo_id':r['id'],'tipo':contexto[0],
            'estado_recibo':r['estado'],'lote_id':r['lote_id'],'evidencia_sha256':sha}


def api_conciliar(projetos,dados,ident):
    if ident.get('permissao')!='pc':return 403,{'erro':'Conciliação disponível somente no PC'}
    campos={'projeto_id','versao','pedido_id','acao'}
    if (not isinstance(dados,dict) or dados.get('acao') not in ('previa','aplicar')
        or set(dados)!=(campos|({'evidencia_sha256'} if dados.get('acao')=='aplicar' else set()))
        or not re.fullmatch('[0-9a-f]{32}',str(dados.get('pedido_id','')))):
        return 400,{'erro':'Pedido de conciliação inválido'}
    from funcionarios import id_projeto
    from politica_painel import snapshot
    projeto=next((p for p in projetos if id_projeto(p)==dados['projeto_id']),None)
    if projeto is None:return 400,{'erro':'Projeto não configurado'}
    try:
        cfg,versao,_=snapshot(projeto)
        if dados['versao']!=versao:return 409,{'erro':'Política mudou; recarregue o painel'}
        with _lock:
            if any(t.is_alive() for t in _ativos.values()):return 409,{'erro':'Há worker acompanhado; aguarde seu retorno'}
            db=abrir(projeto)
            if db is None:return 409,{'erro':'Pedido indisponível'}
            with closing(db):e=evidencia_conciliacao(projeto,dados['pedido_id'],cfg['kanban']['repo'],db)
            if dados['acao']=='previa':return 200,{**e,'somente_preparacao':True}
            if dados['evidencia_sha256']!=e['evidencia_sha256']:
                return 409,{'erro':'Evidência mudou; confira novamente'}
            with closing(abrir(projeto,True)) as db,db:
                db.execute('BEGIN IMMEDIATE')
                atual=evidencia_conciliacao(projeto,dados['pedido_id'],cfg['kanban']['repo'],db)
                if atual!=e or snapshot(projeto)[1]!=versao:raise ValueError('Evidência mudou; confira novamente')
                db.execute("UPDATE pedido SET estado='conciliada',atualizado=? WHERE id=?",(time.time(),dados['pedido_id']))
                db.execute('UPDATE pedido_contexto SET sha_conciliacao=? WHERE id=?',(e['evidencia_sha256'],dados['pedido_id']))
        return 200,{**e,'estado':'conciliada'}
    except ValueError as exc:return 409,{'erro':str(exc)}
    except (TypeError,KeyError,OSError,sqlite3.Error):return 409,{'erro':'Registros indisponíveis; mantenha o pedido bloqueado e confira no PC'}
