"""Identidade, persistência e decisões XP isoladas por projeto registrado."""
from contextlib import closing
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import time

def contexto(projeto,base):
    from politica_painel import snapshot
    from gestao_cli import pasta_dados,RAIZ
    from funcionarios import id_projeto
    raiz=Path(projeto).resolve();politica,versao,_=snapshot(raiz)
    if not politica['ativo'] or not politica['kanban']['repo']:raise ValueError('Gestão/repositório do projeto não configurado')
    dados=pasta_dados(raiz)
    if not dados.resolve().is_relative_to(RAIZ.resolve()):raise ValueError('Dados XP fora da instalação')
    repo_id=hashlib.sha256(politica['kanban']['repo'].casefold().encode()).hexdigest()[:20]
    pasta=dados/'xp'/repo_id
    if pasta.is_symlink() or not pasta.resolve().is_relative_to(dados.resolve()):raise ValueError('Pasta XP inválida')
    if any((pasta/n).is_symlink() for n in ('estado.json','placar.json','decisoes.db')):raise ValueError('Arquivo XP inválido')
    cfg=copy.deepcopy(base);k=politica['kanban']
    cfg['github'].update(repo=k['repo'],projeto_owner=k['owner'],projeto_numero=k['numero'],campo_time=k['campo_time'])
    cfg['github']['colunas']=[k[x] for x in ('backlog','andamento','revisao','feito')]
    cfg['agentes']=[{'nome':e['nome'],'outros_nomes':[],'auxiliar':False} for e in politica['equipes']]
    cfg['github']['times']={e['nome']:e['nome'] for e in politica['equipes']}
    nomes={a['nome'] for a in cfg['agentes']}
    cfg['xp']['atribuicao']['prefixos_branch']={k:v for k,v in cfg['xp']['atribuicao']['prefixos_branch'].items() if v in nomes}
    cfg['xp']['atribuicao']['padrao']=''
    return {'raiz':raiz,'politica':politica,'versao':versao,'id':id_projeto(raiz),'cfg':cfg,'pasta':pasta,
            'placar':pasta/'placar.json','estado':pasta/'estado.json','decisoes':Decisoes(pasta/'decisoes.db'),'kanban_cache':dados/'kanban.json'}

class Decisoes:
    def __init__(self,arquivo):self.arquivo=Path(arquivo)
    def abrir(self,escrever=False):
        p=self.arquivo
        if p.is_symlink():raise ValueError('Banco de decisões inválido')
        if not escrever:
            if not p.exists():return None
            return sqlite3.connect(p.resolve().as_uri()+'?mode=ro',uri=True,timeout=10)
        p.parent.mkdir(parents=True,exist_ok=True)
        db=sqlite3.connect(p,timeout=10)
        db.execute('CREATE TABLE IF NOT EXISTS decisao_xp (pr INTEGER NOT NULL,tipo TEXT NOT NULL,quando TEXT,origem TEXT,motivo TEXT,PRIMARY KEY(pr,tipo))')
        db.commit();return db
    def decisoes(self,tipo):
        db=self.abrir()
        if db is None:return set()
        with closing(db):return {r[0] for r in db.execute('SELECT pr FROM decisao_xp WHERE tipo=?',(tipo,))}
    def decidir(self,pr,tipo,origem='',motivo=''):
        if type(pr) is not int or pr<1 or tipo not in ('conferido','liberado'):raise ValueError('Decisão XP inválida')
        with closing(self.abrir(True)) as db,db:
            db.execute('INSERT OR REPLACE INTO decisao_xp VALUES (?,?,?,?,?)',(pr,tipo,time.strftime('%Y-%m-%d %H:%M'),origem,(motivo or '')[:300]))
    def desfazer(self,pr):
        if type(pr) is not int or pr<1:raise ValueError('PR inválido')
        with closing(self.abrir(True)) as db,db:db.execute('DELETE FROM decisao_xp WHERE pr=?',(pr,))

def ler(ctx):
    p=ctx['placar']
    if p.is_symlink():raise ValueError('Placar inválido')
    with p.open('rb') as f:bruto=f.read(2*1024*1024+1)
    if len(bruto)>2*1024*1024:raise ValueError('Placar grande demais')
    d=json.loads(bruto)
    if (not isinstance(d,dict) or d.get('repo')!=ctx['politica']['kanban']['repo']
        or d.get('projeto_id')!=ctx['id'] or d.get('politica_versao')!=ctx['versao']
        or not isinstance(d.get('agentes'),dict)):
        raise ValueError('Placar diverge da política; recalcule o projeto')
    return d

def vista(projetos,base,ident=None):
    from kanban_painel import escolher
    selecao=escolher(projetos,ident,'Placar')
    if selecao is None:return None
    escolhido,publicos,erro=selecao
    r={'fonte':'gestao','ativo':bool(base['xp']['ativo']),'projetos':publicos,'projeto_id':'','politica_versao':'',
       'agentes':{},'erro':erro,'custos':None,'uso':None}
    if erro:return r
    ctx=contexto(escolhido[0],base);r.update(projeto_id=ctx['id'],politica_versao=ctx['versao'],repo=ctx['politica']['kanban']['repo'])
    if not r['ativo']:return r
    try:r.update(ler(ctx))
    except (OSError,ValueError,TypeError):r['erro']='Placar indisponível ou desatualizado; calcule XP para este projeto'
    from auditor_projeto import resumo
    r['auditor']=resumo(ctx)
    return r
