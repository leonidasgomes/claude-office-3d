"""Recibo local da coordenação; leitura pública omite motivos, prompts e caminhos."""
from contextlib import closing
import json
import math
import re
import sqlite3
import time
import uuid

TRANSICOES={'preparado':{'consultando_ceo','incerto'},
            'consultando_ceo':{'ceo_registrado','incerto'},
            'ceo_registrado':{'consultando_diretor','bloqueado','incerto'},
            'consultando_diretor':{'diretor_registrado','incerto'},
            'diretor_registrado':{'organizado','bloqueado','incerto'},
            'organizado':{'despachando','incerto'},
            'despachando':{'processado','interrompido','incerto'}}
ESTADOS=set(TRANSICOES)|{'bloqueado','processado','interrompido','incerto'}


def arquivo(projeto):
    from gestao_cli import RAIZ,pasta_dados
    arq=pasta_dados(projeto)/'coordenacao.db'
    if arq.is_symlink() or not arq.resolve().is_relative_to(RAIZ.resolve()):
        raise ValueError('Registro da coordenação fora da instalação')
    return arq


def validar(d):
    from coordenacao import selecionar
    obrigatorios={'id','repo','contexto_sha256','estado','atualizado','executores','candidatos','ceo','diretor','lote_id'}
    if (not isinstance(d,dict) or not obrigatorios.issubset(d) or set(d)-(obrigatorios|{'plano_sha256'})
        or not re.fullmatch('[0-9a-f]{32}',str(d['id']))
        or not isinstance(d['repo'],str) or not re.fullmatch('[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',d['repo'])
        or not re.fullmatch('[0-9a-f]{64}',str(d['contexto_sha256'])) or d['estado'] not in ESTADOS
        or type(d['atualizado']) not in (int,float) or not math.isfinite(d['atualizado']) or d['atualizado']<=0
        or not isinstance(d['candidatos'],list) or not 1<=len(d['candidatos'])<=20
        or any(type(n) is not int or n<1 for n in d['candidatos']) or len(set(d['candidatos']))!=len(d['candidatos'])
        or not isinstance(d['executores'],dict) or set(d['executores'])!={'ceo','diretor'}
        or (d['lote_id'] is not None and not re.fullmatch('[0-9a-f]{32}',str(d['lote_id'])))):
        raise ValueError('Recibo de coordenação inválido')
    for e in d['executores'].values():
        if (not isinstance(e,dict) or set(e)!={'console','modelo','execucao'}
            or e['console'] not in ('claude','codex','gemini','opencode') or e['execucao']!='cloud'
            or not isinstance(e['modelo'],str) or len(e['modelo'])>200):raise ValueError('Executor do recibo inválido')
    if d['ceo'] is not None:selecionar(d['ceo'],set(d['candidatos']))
    if d['diretor'] is not None:
        if not d['ceo']:raise ValueError('Recibo sem decisão do CEO')
        selecionar(d['diretor'],set(d['ceo']['cartoes']))
    if d['estado'] in ('ceo_registrado','consultando_diretor','diretor_registrado','organizado','despachando','processado','interrompido') and d['ceo'] is None:
        raise ValueError('Estado sem decisão CEO')
    if d['estado'] in ('diretor_registrado','organizado','despachando','processado','interrompido') and d['diretor'] is None:
        raise ValueError('Estado sem decisão diretor')
    if d['estado'] in ('organizado','despachando','processado','interrompido'):
        if any(not d[p]['cartoes'] or d[p]['bloqueios'] for p in ('ceo','diretor')):raise ValueError('Seleção bloqueada em estado organizado')
    if d['estado']=='bloqueado' and not any(d[p] is not None and (not d[p]['cartoes'] or d[p]['bloqueios']) for p in ('ceo','diretor')):
        raise ValueError('Estado bloqueado sem decisão impeditiva')
    if d['estado'] in ('processado','interrompido') and d['lote_id'] is None:raise ValueError('Estado final sem lote vinculado')
    if 'plano_sha256' in d and not re.fullmatch('[0-9a-f]{64}',str(d['plano_sha256'])):raise ValueError('Hash de plano inválido')
    return d


class Registro:
    def __init__(self,projeto):
        self.arquivo=arquivo(projeto)
        self.arquivo.parent.mkdir(parents=True,exist_ok=True)
        with closing(self.abrir()) as db,db:
            db.execute('CREATE TABLE IF NOT EXISTS coordenacao (id TEXT PRIMARY KEY,repo TEXT NOT NULL,atualizado REAL NOT NULL,dados TEXT NOT NULL)')

    def abrir(self):return sqlite3.connect(self.arquivo,timeout=10)

    def criar(self,repo,contexto,executores,candidatos):
        d=validar({'id':uuid.uuid4().hex,'repo':repo,'contexto_sha256':contexto,'estado':'preparado',
                   'atualizado':time.time(),'candidatos':candidatos,'ceo':None,'diretor':None,'lote_id':None,
                   'executores':{p:{'console':e['console'],'modelo':e.get('modelo',''),'execucao':'cloud'} for p,e in executores.items()}})
        with closing(self.abrir()) as db,db:
            db.execute('INSERT INTO coordenacao VALUES (?,?,?,?)',(d['id'],repo,d['atualizado'],json.dumps(d,ensure_ascii=False)))
        return d['id']

    def atualizar(self,ident,estado,**campos):
        if set(campos)-{'ceo','diretor','lote_id','plano_sha256'}:raise ValueError('Campo de recibo não permitido')
        with closing(self.abrir()) as db,db:
            db.execute('BEGIN IMMEDIATE')
            linha=db.execute('SELECT dados FROM coordenacao WHERE id=?',(ident,)).fetchone()
            if not linha:raise ValueError('Coordenação não encontrada')
            d=validar(json.loads(linha[0]))
            if estado not in TRANSICOES.get(d['estado'],set()):raise ValueError('Transição da coordenação inválida')
            if ('ceo' in campos and (d['estado']!='consultando_ceo' or estado!='ceo_registrado')
                or 'diretor' in campos and (d['estado']!='consultando_diretor' or estado!='diretor_registrado')
                or 'lote_id' in campos and (d['estado']!='despachando' or estado not in ('processado','interrompido'))):
                raise ValueError('Decisão fora da fase de registro')
            if 'plano_sha256' in campos and (d['estado']!='diretor_registrado' or estado!='organizado'):
                raise ValueError('Plano fora da fase de organização')
            for chave,valor in campos.items():
                if d.get(chave) is not None and d[chave]!=valor:raise ValueError('Decisão já registrada; concilie a coordenação')
            d.update(campos,estado=estado,atualizado=time.time());validar(d)
            db.execute('UPDATE coordenacao SET atualizado=?,dados=? WHERE id=?',(d['atualizado'],json.dumps(d,ensure_ascii=False),ident))


def resumo(projeto,repo):
    saida={'itens':[],'problemas':0,'limitado':False}
    try:
        arq=arquivo(projeto)
        if not arq.exists():return saida
        with closing(sqlite3.connect(arq.resolve().as_uri()+'?mode=ro',uri=True,timeout=5)) as db:
            linhas=db.execute('SELECT id,CASE WHEN length(dados)<=64000 THEN dados ELSE NULL END FROM coordenacao '
                             'WHERE repo=? ORDER BY atualizado DESC,id DESC LIMIT 11',(repo,)).fetchall()
        saida['limitado']=len(linhas)>10
        for ident,texto in linhas[:10]:
            try:
                if not isinstance(texto,str) or len(texto)>64000:raise ValueError('Recibo grande demais')
                d=validar(json.loads(texto))
                if d['id']!=ident or d['repo']!=repo:raise ValueError('Recibo de outro projeto')
                item={k:d[k] for k in ('id','estado','atualizado','executores','candidatos','lote_id')}
                item['plano_sha256']=d.get('plano_sha256')
                for p in ('ceo','diretor'):
                    item[p]=None if d[p] is None else {'cartoes':d[p]['cartoes'],'bloqueios':len(d[p]['bloqueios'])}
                saida['itens'].append(item)
            except (ValueError,TypeError,KeyError):saida['problemas']+=1
    except (ValueError,TypeError,OSError,sqlite3.Error):saida['problemas']+=1
    return saida
