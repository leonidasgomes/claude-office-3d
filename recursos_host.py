"""Hidratação restrita de pointers LFS pelo cache local, sem checkout ou rede."""
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import uuid
from contextlib import closing
from pathlib import Path
from controlador_local import RAIZ,atomico


class PoliticaRecursosDivergente(ValueError):
    """Acesso antigo permanece negado, sem invalidar o planejamento da fila."""


def diretorios_travas(projeto,dados,cfg,equipe):
    """Autorização operacional do host; ausente nunca amplia escrita do console."""
    f=Path(dados)/'recursos_escrita.json'
    if not f.exists():return []
    if f.is_symlink() or f.stat().st_size>16000:raise ValueError('Autorização de recursos inválida')
    r=json.loads(f.read_text(encoding='utf-8'))
    politica=hashlib.sha256(json.dumps(cfg,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    if (not isinstance(r,dict) or set(r)!={'projeto','politica','origem','equipes','travas'}
        or r['projeto']!=str(Path(projeto).resolve())
        or not re.fullmatch('[0-9a-f]{64}',str(r['politica']))
        or not isinstance(r['origem'],str) or not r['origem'].strip()
        or not isinstance(r['equipes'],list) or not r['equipes']
        or any(e not in {t['nome'] for t in cfg['equipes']} for e in r['equipes'])
        or not isinstance(r['travas'],str)):
        raise ValueError('Autorização de recursos diverge do projeto/política')
    p=Path(r['travas']);raiz=RAIZ.parent.resolve()
    if (not p.is_absolute() or not p.is_dir() or p.is_symlink() or p.is_junction()
        or p.resolve().parent!=raiz or p.name not in ('travas','locks')):
        raise ValueError('Recurso deve ser somente a pasta de travas do cache do escritório')
    if r['politica']!=politica:
        raise PoliticaRecursosDivergente('Autorização da pasta de travas pertence a outra política')
    return [p.resolve()] if equipe in r['equipes'] else []


def contexto_travas(projeto,dados,cfg):
    """Somente leitura para o diretor; não revalida permissões antigas."""
    nomes=[e['nome'] for e in cfg['equipes']]
    try:
        travas={nome:[str(p) for p in diretorios_travas(projeto,dados,cfg,nome)] for nome in nomes}
    except PoliticaRecursosDivergente as exc:
        return {'travas_por_equipe':{nome:[] for nome in nomes},
                'pendencias':[{'recurso':'travas','motivo':str(exc),
                    'acao':'Conferir autorização de recursos; acesso antigo não está disponível.'}]}
    return {'travas_por_equipe':travas,'pendencias':[]}


def hidratar_lfs(projeto,dados):
    from controle_tarefas import Controle
    from gestao_cli import pasta_dados
    from gestao_projeto import carregar
    if (not isinstance(dados,dict) or set(dados)!={'cartao','worktree','arquivos'}
        or type(dados['cartao']) is not int or dados['cartao']<1
        or not isinstance(dados['worktree'],str) or not isinstance(dados['arquivos'],list)
        or not 1<=len(dados['arquivos'])<=128
        or any(not isinstance(n,str) or not n or '\\' in n or ':' in n or n.startswith('/')
               or any(x in ('','.','..','.git') for x in n.split('/')) for n in dados['arquivos'])
        or len(set(dados['arquivos']))!=len(dados['arquivos'])):
        raise ValueError('Assets exigem cartão, worktree e até 128 caminhos relativos distintos')
    projeto=Path(projeto).resolve();work=Path(dados['worktree']).resolve()
    if not work.is_relative_to((RAIZ.parent/'worktrees').resolve()) or work==projeto:
        raise ValueError('Assets somente no worktree separado do escritório')
    cfg=carregar(projeto);n=dados['cartao'];pasta=pasta_dados(projeto)
    if not cfg['ativo'] or not cfg['ciclo']['ativo']:raise ValueError('Gestão/ciclo desativados')
    controle=Controle(pasta/'tarefas.db')
    def reserva():
        r=next((r for r in controle.listar(cfg['kanban']['repo']) if r['cartao']==str(n)),None)
        if not r or r['estado']!='executando':raise ValueError('Assets exigem reserva em execução')
        ctx=r['pacote'].get('contexto_execucao') or {}
        politica=hashlib.sha256(json.dumps(cfg,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        if (Path(ctx.get('worktree','')).resolve()!=work or ctx.get('politica_sha256')!=politica):
            raise ValueError('Assets divergem da reserva/política')
        with closing(sqlite3.connect(pasta/'tarefas.db')) as db:
            ts=db.execute('SELECT id FROM execucao_tarefa WHERE token=? AND fim IS NULL',(r['token'],)).fetchall()
        if len(ts)!=1:raise ValueError('Assets exigem tentativa em curso registrada')
        return r
    original=reserva();criados=[]
    for f in (RAIZ/'dados/worktrees').glob('*.json'):
        if f.is_symlink() or f.stat().st_size>128000:raise ValueError('Recibo de worktree inválido')
        r=json.loads(f.read_text(encoding='utf-8'))
        if r.get('projeto')==str(projeto) and r.get('estado')=='criado':
            criados.extend(i for i in r['criados'] if i['cartao']==n and Path(i['worktree']).resolve()==work)
    if len(criados)!=1:raise ValueError('Assets sem recibo único de criação')
    def git(raiz,*args):
        return subprocess.run(['git','-C',str(raiz),*args],capture_output=True,check=True,timeout=15).stdout
    comum=Path(git(projeto,'rev-parse','--path-format=absolute','--git-common-dir').decode().strip()).resolve()
    if Path(git(work,'rev-parse','--path-format=absolute','--git-common-dir').decode().strip()).resolve()!=comum:
        raise ValueError('Assets de outro repositório')
    branch=git(work,'branch','--show-current').decode().strip()
    if branch!=original['pacote']['contexto_execucao'].get('branch') or branch!=criados[0]['branch']:
        raise ValueError('Assets de outro branch')
    head=git(work,'rev-parse','HEAD').decode().strip();itens=[];total=0
    for nome in dados['arquivos']:
        alvo=work/nome
        if (not alvo.resolve().is_relative_to(work) or any(p.is_symlink() or p.is_junction()
            for p in (alvo,*alvo.parents) if p!=work and p.is_relative_to(work))):
            raise ValueError('Asset fora do worktree ou por link')
        git(work,'ls-files','--error-unmatch','--',nome)
        tamanho=git(work,'cat-file','-s',head+':'+nome).decode().strip()
        if not tamanho.isdigit() or int(tamanho)>1024:raise ValueError('Asset não é pointer LFS no commit')
        bruto=git(work,'show',head+':'+nome).replace(b'\r\n',b'\n')
        m=re.fullmatch(rb'version https://git-lfs.github.com/spec/v1\noid sha256:([0-9a-f]{64})\nsize ([0-9]+)\n',bruto)
        if not m:raise ValueError('Pointer LFS inválido')
        oid=m[1].decode();size=int(m[2]);total+=size
        if size>256*1024*1024 or total>1024*1024*1024:raise ValueError('Assets excedem o limite desta preparação')
        objeto=comum/'lfs/objects'/oid[:2]/oid[2:4]/oid
        if (not objeto.is_file() or objeto.is_symlink() or not objeto.resolve().is_relative_to(comum/'lfs/objects')
            or objeto.stat().st_size!=size):raise ValueError('Asset não está no cache LFS local: '+nome)
        if not alvo.is_file() or alvo.stat().st_size>1024 or alvo.read_bytes().replace(b'\r\n',b'\n')!=bruto:
            raise ValueError('Asset já hidratado ou modificado: '+nome)
        bruto=alvo.read_bytes()  # Preserva bytes locais para conferir a corrida antes da troca.
        itens.append((nome,alvo,objeto,oid,size,bruto))
    assinatura=hashlib.sha256(json.dumps({'token':original['token'],'head':head,'arquivos':dados['arquivos']},sort_keys=True).encode()).hexdigest()
    recibo=pasta/'assets'/(assinatura+'.json');recibo.parent.mkdir(exist_ok=True)
    if recibo.exists():raise ValueError('Preparação anterior exige conferência; não repetir')
    registro={'estado':'preparando','cartao':n,'token':original['token'],'head':head,
              'origem':'cache_lfs_local','arquivos':dados['arquivos'],'hidratados':[]}
    atomico(recibo,registro)
    try:
        for nome,alvo,objeto,oid,size,bruto in itens:
            temporario=alvo.with_name(alvo.name+'.office-lfs-'+uuid.uuid4().hex)
            try:
                with objeto.open('rb') as origem,temporario.open('xb') as destino:
                    shutil.copyfileobj(origem,destino,1024*1024)
                with temporario.open('rb') as f:obtido=hashlib.file_digest(f,'sha256').hexdigest()
                if obtido!=oid:raise ValueError('Cache LFS corrompido: '+nome)
                if (carregar(projeto)!=cfg or reserva()['token']!=original['token']
                    or git(work,'rev-parse','HEAD').decode().strip()!=head or alvo.read_bytes()!=bruto):
                    raise ValueError('Reserva/commit/asset mudou durante preparação')
                os.replace(temporario,alvo)
                registro['hidratados'].append({'arquivo':nome,'oid':oid,'bytes':size});atomico(recibo,registro)
            finally:temporario.unlink(missing_ok=True)
        registro['estado']='preparado';atomico(recibo,registro)
        return registro
    except Exception as e:
        registro.update(estado='interrompido',erro=str(e));atomico(recibo,registro)
        raise
