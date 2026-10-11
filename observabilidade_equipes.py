"""Projeções do diário existente; não inferem presença, aceite ou entrega."""
from contextlib import closing
import json
import sqlite3
import re


def nome_comando(texto):
    """Rótulo heurístico, sem expor argumentos/caminhos no painel de gestão."""
    texto=str(texto or '').lower()
    if re.search(r'\b(pytest|unittest|ctest|test[-_][\w.-]+|validate[-_][\w.-]+)\b',texto):return 'Testes'
    if re.search(r'\b(cmake|msbuild|build[-_][\w.-]+|unrealbuildtool)\b',texto):return 'Build'
    return 'Comando'


def etapa_reserva(db, token, estado, instante):
    db.execute('''CREATE TABLE IF NOT EXISTS reserva_etapa (
        id INTEGER PRIMARY KEY,token TEXT NOT NULL,estado TEXT NOT NULL,instante REAL NOT NULL)''')
    db.execute('INSERT INTO reserva_etapa(token,estado,instante) VALUES (?,?,?)',(token,estado,instante))


def registrar_operacoes(db, execucao, operacoes):
    db.execute('''CREATE TABLE IF NOT EXISTS atividade_operacao (
        execucao TEXT NOT NULL,sessao TEXT NOT NULL,operacao TEXT NOT NULL,
        ferramenta TEXT NOT NULL,inicio REAL,fim REAL,estado TEXT NOT NULL,codigo INTEGER,
        PRIMARY KEY(execucao,sessao,operacao))''')
    for (sessao, ident), op in operacoes.items():
        db.execute('''INSERT INTO atividade_operacao VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(execucao,sessao,operacao) DO UPDATE SET
            fim=excluded.fim,estado=excluded.estado,codigo=excluded.codigo''',
            (execucao, sessao, ident, op['ferramenta'], op['inicio'], op['fim'], op['estado'], op['codigo']))


def operacoes(db, token, ativo, agora):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='atividade_operacao'").fetchone():
        return []
    rows = db.execute('''SELECT o.ferramenta,o.inicio,o.fim,o.estado,o.codigo,e.fim
        FROM atividade_operacao o JOIN execucao_tarefa e ON e.id=o.execucao
        WHERE e.token=? ORDER BY COALESCE(o.fim,o.inicio,0) DESC LIMIT 20''', (token,)).fetchall()
    saida = []
    for ferramenta, inicio, fim, estado, codigo, fim_tentativa in rows:
        confirmado = ativo and fim_tentativa is None and fim is None
        ate = fim if fim is not None else (agora if confirmado else None)
        # Nunca expõe o comando completo, caminhos ou prompts privados.
        saida.append({'ferramenta': ferramenta, 'estado': estado if fim is not None or confirmado else 'sem_retorno',
                      'duracao_seg': max(0, ate-inicio) if inicio is not None and ate is not None else None,
                      'codigo': codigo, 'inicio_observado': inicio is not None})
    return saida


def etapa(arquivo, ciclo, estado, instante, cartoes):
    """Batidas na mesma etapa não reiniciam o intervalo."""
    with closing(sqlite3.connect(arquivo, timeout=2)) as db, db:
        db.execute('''CREATE TABLE IF NOT EXISTS ciclo_etapa (
            id INTEGER PRIMARY KEY,ciclo TEXT NOT NULL,estado TEXT NOT NULL,
            instante REAL NOT NULL,cartoes TEXT NOT NULL)''')
        cartoes_json=json.dumps([str(c['cartao']) for c in cartoes])
        ultimo = db.execute('SELECT estado,instante,cartoes FROM ciclo_etapa WHERE ciclo=? ORDER BY id DESC LIMIT 1',
                            (ciclo,)).fetchone()
        if ultimo and ((ultimo[0] == estado and ultimo[2]==cartoes_json) or instante < ultimo[1]):
            return
        db.execute('INSERT INTO ciclo_etapa(ciclo,estado,instante,cartoes) VALUES (?,?,?,?)',
                   (ciclo, estado, instante, cartoes_json))


def esperas(db):
    """Somente intervalos fechados; a cauda aberta/incerta não é medida."""
    if db is None:
        return {'intervalos': [], 'segundos': 0, 'fonte': 'transições do controlador', 'parcial': True}
    tabelas={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    rows = db.execute('SELECT ciclo,estado,instante,cartoes FROM ciclo_etapa ORDER BY id DESC LIMIT 1001').fetchall() if 'ciclo_etapa' in tabelas else []
    intervalos, seguintes = [], {}
    for ciclo, estado, instante, cartoes in rows[:1000]:
        fim = seguintes.get(ciclo); seguintes[ciclo] = instante
        if fim is not None and fim >= instante and estado in ('aguardando','diretor'):
            intervalos.append({'etapa': estado, 'inicio': instante, 'fim': fim,
                              'segundos': fim-instante, 'cartoes': json.loads(cartoes)})
    if {'reserva_etapa','reserva'}<=tabelas:
        etapas=db.execute('SELECT e.token,e.estado,e.instante,r.cartao FROM reserva_etapa e '
            'JOIN reserva r ON r.token=e.token ORDER BY e.id DESC LIMIT 1001').fetchall()
        seguintes={}
        for token,estado,instante,cartao in etapas[:1000]:
            fim=seguintes.get(token);seguintes[token]=instante
            if fim is not None and fim>=instante and estado in ('revisao','bloqueado'):
                intervalos.append({'etapa':estado,'inicio':instante,'fim':fim,'segundos':fim-instante,'cartoes':[cartao]})
    intervalos.sort(key=lambda i:i['fim'],reverse=True)
    return {'intervalos': intervalos[:50], 'segundos': sum(i['segundos'] for i in intervalos),
            'fonte': 'transições do controlador', 'parcial': True, 'limitado': len(rows)>1000}


def entregas(db, repo, consumo, raiz):
    """Tokens observados por merge comprovado, nunca por PR simplesmente aberto."""
    saida={'merges':0,'tokens_observados':None,'tokens_por_merge':None,'merges_com_consumo':0,
           'parcial':True,'periodo_consumo_dias':7}
    tabelas={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {'conclusao','reserva','execucao_tarefa'}<=tabelas:return saida
    rows=db.execute('SELECT r.token,c.evidencia FROM reserva r JOIN conclusao c ON c.token=r.token '
                    "WHERE r.projeto=? AND r.estado='concluido' ORDER BY c.atualizado DESC LIMIT 101",(repo,)).fetchall()
    saida['limitado']=len(rows)>100
    merges={}
    for token,texto in rows[:100]:
        ev=json.loads(texto);sha=ev.get('merge_commit')
        if not re.fullmatch('[0-9a-f]{40}',sha or '') or not ev.get('merged_at'):continue
        tokens={token};anterior=token
        if 'contrato_correcao' in tabelas:
            for _ in range(20):
                row=db.execute('SELECT anterior FROM contrato_correcao WHERE token=?',(anterior,)).fetchone()
                if not row or row[0] in tokens:break
                anterior=row[0];tokens.add(anterior)
        ids={r[0] for t in tokens for r in db.execute('SELECT id FROM execucao_tarefa WHERE token=? LIMIT 1000',(t,))}
        merges.setdefault(sha,set()).update(ids)
    saida['merges']=len(merges)
    from consumo_providers import Registro,identidade_projeto
    ids=sorted(set().union(*merges.values())) if merges else []
    if len(ids)>1000:saida['limitado']=True;ids=ids[:1000]
    dados=Registro(consumo).resumos_tentativas(ids,identidade_projeto(raiz)) if ids else {}
    total=0;com=0
    for tentativas in merges.values():
        grupos=[g for t in tentativas for g in dados.get(t,{}).get('grupos',[])]
        valores=[g['total'] for g in grupos if g.get('com_total',0)>0 and type(g.get('total')) is int]
        if valores:total+=sum(valores);com+=1
    saida.update(merges_com_consumo=com,tokens_observados=total if com else None,
                 tokens_por_merge=total/com if com else None)
    return saida
