"""Commit/push/PR restritos ao worktree criado e reservado pelo escritório."""
import json
from pathlib import Path
import re
import subprocess
from controlador_local import RAIZ, atomico


def publicar(projeto,dados):
    from gestao_cli import pasta_dados
    from controle_tarefas import Controle
    from gestao_projeto import carregar
    if not isinstance(dados,dict) or set(dados)!={'cartao','worktree','titulo','corpo'}:
        raise ValueError('Publicação exige cartão, worktree, título e corpo')
    n=dados['cartao']
    if type(n) is not int or n<1 or not isinstance(dados['worktree'],str):raise ValueError('Cartão/worktree inválido')
    p=Path(dados['worktree']).resolve();cfg=carregar(projeto)
    if not cfg['ciclo']['ativo'] or not p.is_relative_to((RAIZ.parent/'worktrees').resolve()):
        raise ValueError('Publicação fora do worktree autorizado')
    if any(not isinstance(dados[k],str) or not dados[k].strip() or len(dados[k])>16000 for k in ('titulo','corpo')):
        raise ValueError('Descrição inválida')
    if not re.search(rf'(?:Closes|Fixes|Resolves|Parte de)\s+#{n}\b',dados['corpo'],re.I):
        raise ValueError('PR precisa vincular o cartão real')
    criados=[]
    for recibo in (RAIZ/'dados'/'worktrees').glob('*.json'):
        r=json.loads(recibo.read_text(encoding='utf-8'))
        if r.get('projeto')==str(projeto) and r['estado']=='criado':
            criados += [i for i in r['criados'] if i['cartao']==n and Path(i['worktree']).resolve()==p]
    if len(criados)!=1:raise ValueError('Worktree não tem recibo único de criação')
    reserva=next((r for r in Controle(pasta_dados(projeto)/'tarefas.db').listar(cfg['kanban']['repo'])
                  if r['cartao']==str(n)),None)
    if not reserva or reserva['estado']!='executando':raise ValueError('Publicação exige reserva em execução')
    def rodar(args):
        r=subprocess.run(args,cwd=p,capture_output=True,text=True,encoding='utf-8',timeout=120)
        if r.returncode:raise ValueError('Publicação falhou: '+r.stderr[-2000:])
        return r.stdout.strip()
    def git(*args):return rodar(['git','-C',str(p),*args])
    branch=git('branch','--show-current')
    if branch!=criados[0]['branch'] or branch in ('main','master',cfg['ciclo']['base'].removeprefix('origin/')):
        raise ValueError('Branch diverge do recibo')
    recibo=pasta_dados(projeto)/'publicacoes'/(str(n)+'.json');recibo.parent.mkdir(exist_ok=True)
    if recibo.exists():raise ValueError('Publicação anterior exige conciliação; não repetir')
    nomes=set(git('diff','--name-only','HEAD').splitlines())|set(git('ls-files','--others','--exclude-standard').splitlines())
    for nome in nomes:
        if nome in ('CLAUDE.md','AGENTS.md','.office/projeto.json') or nome.startswith(('.github/','.git/','.claude/hooks/','.claude/settings')):
            raise ValueError('Publicação não altera regras/política/hooks')
    registro={'estado':'publicando','cartao':n,'worktree':str(p),'branch':branch};atomico(recibo,registro)
    if git('status','--porcelain'):
        git('add','--all');git('commit','-m',dados['titulo'])
    sha=git('rev-parse','HEAD');git('push','origin','HEAD:refs/heads/'+branch)
    corpo=recibo.with_suffix('.md');corpo.write_text(dados['corpo'],encoding='utf-8')
    url=rodar(['gh','pr','create','--repo',cfg['kanban']['repo'],'--base',
        cfg['ciclo']['base'].removeprefix('origin/'),'--head',branch,'--title',dados['titulo'],'--body-file',str(corpo)])
    registro.update(estado='publicado',sha=sha,pr=url);atomico(recibo,registro)
    return registro
