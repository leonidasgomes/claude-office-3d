"""Plano privado imutável da seleção; navegador recebe só identidade e hash."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3


def caminho(projeto,ident):
    from coordenacao_registro import arquivo
    if not isinstance(ident,str) or not re.fullmatch('[0-9a-f]{32}',ident):raise ValueError('ID da coordenação inválido')
    base=arquivo(projeto).parent;p=base/'planos_coordenacao'/(ident+'.json')
    if p.is_symlink() or not p.resolve().is_relative_to(base.resolve()):raise ValueError('Plano fora do registro local')
    return p


def salvar(projeto,ident,plano,preparado):
    from politica_painel import snapshot
    p=caminho(projeto,ident);p.parent.mkdir(exist_ok=True)
    d={'versao':1,'recibo_id':ident,'politica_versao':snapshot(projeto)[1],
       'plano':plano,'preparado':preparado}
    bruto=json.dumps(d,ensure_ascii=False,sort_keys=True).encode('utf-8')
    if len(bruto)>1024*1024:raise ValueError('Plano privado excede 1 MiB')
    # Publicado no recibo somente após fechamento/fsync bem-sucedidos.
    with p.open('xb') as f:f.write(bruto);f.flush();os.fsync(f.fileno())
    return hashlib.sha256(bruto).hexdigest()


def recibo(projeto,ident):
    from coordenacao_registro import arquivo,validar
    p=arquivo(projeto)
    if not p.is_file():raise ValueError('Recibo indisponível')
    with closing(sqlite3.connect(p.resolve().as_uri()+'?mode=ro',uri=True,timeout=5)) as db:
        linha=db.execute('SELECT dados FROM coordenacao WHERE id=?',(ident,)).fetchone()
    if not linha or len(linha[0])>64000:raise ValueError('Recibo indisponível')
    return validar(json.loads(linha[0]))


def preparar(projeto,ident,soma,versao,kanban=None):
    from politica_painel import snapshot
    from coordenacao import identidade
    from gestao_cli import preparar_lote
    p=caminho(projeto,ident);r=recibo(projeto,ident)
    if (r['estado']!='organizado' or not isinstance(soma,str) or not re.fullmatch('[0-9a-f]{64}',soma)
        or r.get('plano_sha256')!=soma):raise ValueError('Seleção não está disponível para execução')
    cfg,atual,_=snapshot(projeto)
    if atual!=versao or r['repo']!=cfg['kanban']['repo']:raise ValueError('Política diverge da seleção')
    with p.open('rb') as f:bruto=f.read(1024*1024+1)
    if len(bruto)>1024*1024 or hashlib.sha256(bruto).hexdigest()!=soma:raise ValueError('Plano privado mudou')
    d=json.loads(bruto)
    if (not isinstance(d,dict) or set(d)!={'versao','recibo_id','politica_versao','plano','preparado'}
        or type(d['versao']) is not int or d['versao']!=1 or d['recibo_id']!=ident or d['politica_versao']!=versao):
        raise ValueError('Plano privado inválido')
    atual_lote=preparar_lote(projeto,d['plano'],kanban)
    if (set(i['cartao'] for i in atual_lote['cartoes'])!=set(r['diretor']['cartoes'])
        or identidade(atual_lote)!=identidade(d['preparado'])):
        raise ValueError('Kanban, política ou worktrees divergem da seleção registrada')
    if snapshot(projeto)[1]!=versao:raise ValueError('Política mudou durante preparação')
    return d


def executar(projeto,ident,soma,versao,kanban=None,despacho=None):
    from coordenacao_registro import Registro
    from gestao_cli import executar_lote
    from politica_painel import snapshot
    d=preparar(projeto,ident,soma,versao,kanban)
    registro=Registro(projeto)
    # Claim transacional: organizado→despachando só pode acontecer uma vez.
    registro.atualizar(ident,'despachando')
    try:
        if snapshot(projeto)[1]!=versao:raise ValueError('Política mudou antes da execução')
        r=executar_lote(projeto,d['plano'],kanban,despacho,esperado=d['preparado'])
        registro.atualizar(ident,r['estado'],lote_id=r['id'])
        return r
    except BaseException:
        try:registro.atualizar(ident,'incerto')
        except Exception:pass
        raise
