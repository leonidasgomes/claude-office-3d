"""Referências seletivas a entregas por merge; não contém instruções ou prompts."""
from contextlib import closing
import hashlib
import json
import re
import sqlite3

SHA=re.compile(r'[0-9a-f]{40}\Z')


def recuperar(banco,repo,pacote,limite=3):
    if type(limite) is not int or not 0<=limite<=5:raise ValueError('Limite de memória inválido')
    if not limite or not banco.is_file():return []
    if not isinstance(pacote,dict):return []
    meta=pacote.get('meta')
    if not isinstance(meta,dict):return []
    gdd=meta.get('gdd')
    if not isinstance(gdd,dict):return []
    if (not isinstance(gdd.get('sha256'),str) or not re.fullmatch('[0-9a-f]{64}',gdd['sha256'])
        or type(gdd.get('numero')) is not int or gdd['numero']<1):return []
    referencias=[];vistos=set()
    with closing(sqlite3.connect(banco.resolve().as_uri()+'?mode=ro',uri=True)) as db:
        tabelas={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'reserva','conclusao'}<=tabelas:return []
        rows=db.execute("SELECT r.cartao,r.equipe,r.pacote,c.evidencia FROM reserva r "
            "JOIN conclusao c ON c.token=r.token WHERE r.projeto=? AND r.estado='concluido' "
            "ORDER BY r.atualizado DESC",(repo,))
        for numero,equipe,bruto,prova in rows:
            if not isinstance(bruto,str) or not isinstance(prova,str) or len(bruto)>500000 or len(prova)>64000:continue
            try:
                anterior=json.loads(bruto);ev=json.loads(prova)
                if not isinstance(anterior,dict) or not isinstance(ev,dict):continue
                meta_antiga=anterior.get('meta')
                if not isinstance(meta_antiga,dict):continue
                antigo=meta_antiga.get('gdd')
                if not isinstance(antigo,dict):continue
                if (antigo.get('sha256')!=gdd['sha256'] or antigo.get('numero')!=gdd['numero']
                    or numero==str(pacote.get('cartao',meta.get('cartao'))) or ev.get('repo')!=repo
                    or type(ev.get('cartao')) is not int or ev['cartao']!=int(numero) or type(ev.get('pr')) is not int or ev['pr']<1
                    or not SHA.fullmatch(ev.get('head') or '') or not SHA.fullmatch(ev.get('merge_commit') or '')
                    or not isinstance(ev.get('merged_at'),str) or not 10<=len(ev['merged_at'])<=50
                    or not isinstance(equipe,str) or len(equipe)>200):continue
                checks=ev.get('checks')
                if not isinstance(checks,dict):continue
                gates=checks.get('gates')
                if not isinstance(gates,list) or not gates or any(not isinstance(g,dict) or g.get('estado')!='success' for g in gates):continue
                identidade=(int(numero),ev['pr'],ev['head'])
                if identidade in vistos:continue
                vistos.add(identidade)
                ref={'cartao':int(numero),'equipe':equipe,'pr':ev['pr'],'head':ev['head'],
                    'merge_commit':ev['merge_commit'],'merged_at':ev['merged_at'],
                    'objetivo_gdd':gdd['numero'],'origem':'conclusao_registrada',
                    'evidencia_sha256':hashlib.sha256(prova.encode()).hexdigest()}
                objetivo=(anterior.get('meta') or {}).get('objetivo')
                if isinstance(objetivo,str) and len(objetivo)<=1000:ref['objetivo']=objetivo
                ref['url']=f'https://github.com/{repo}/pull/{ev["pr"]}'
                referencias.append(ref)
                if len(referencias)>=limite:break
            except (ValueError,TypeError,KeyError):continue
    return referencias
