"""Commit/push/PR restritos ao worktree criado e reservado pelo escritório."""
import json
from pathlib import Path
import re
import subprocess
from controlador_local import RAIZ, atomico


def corpo_texto(corpo):
    """Get-Content sem -Raw envia linhas; aceita só texto, sem coerção de objetos."""
    if isinstance(corpo,list):
        if (not corpo or any(not isinstance(linha,str) for linha in corpo)
            or sum(map(len,corpo))+len(corpo)-1>16000):
            raise ValueError('Corpo do PR exige texto ou linhas de texto, até 16000 caracteres')
        corpo='\n'.join(corpo)
    if not isinstance(corpo,str) or not corpo.strip() or len(corpo)>16000:
        raise ValueError('Corpo do PR exige texto ou linhas de texto, até 16000 caracteres')
    return corpo


def publicar(projeto,dados):
    from gestao_cli import pasta_dados
    from controle_tarefas import Controle
    from gestao_projeto import carregar
    campos={'cartao','worktree','titulo','corpo'}
    atualizar=isinstance(dados,dict) and set(dados)==campos|{'pr','head_sha'}
    if not isinstance(dados,dict) or (set(dados)!=campos and not atualizar):
        raise ValueError('Publicação exige cartão, worktree, título e corpo')
    pedido_original=dados
    dados={**dados,'corpo':corpo_texto(dados['corpo'])}
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
    pr_atual=None
    if atualizar:
        from kanban_gestao import api
        if (type(dados['pr']) is not int or dados['pr']<1
            or not isinstance(dados['head_sha'],str) or not re.fullmatch('[0-9a-f]{40}',dados['head_sha'])):
            raise ValueError('Correção exige PR e commit completo')
        ctx=reserva['pacote'].get('contexto_execucao') or {}
        import hashlib
        politica=hashlib.sha256(json.dumps(cfg,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        if (ctx.get('worktree')!=str(p) or ctx.get('branch')!=branch or ctx.get('politica_sha256')!=politica):
            raise ValueError('Correção exige contexto atual da reserva')
        evidencia=Controle(pasta_dados(projeto)/'tarefas.db').revisao(reserva['token'])
        if not evidencia or evidencia['pr']!=dados['pr'] or evidencia['sha']!=dados['head_sha']:
            raise ValueError('Correção não corresponde à entrega registrada')
        def conferir_pr():
            atual=api(f"repos/{cfg['kanban']['repo']}/pulls/{dados['pr']}")
            vigente=next((r for r in Controle(pasta_dados(projeto)/'tarefas.db').listar(cfg['kanban']['repo'])
                          if r['token']==reserva['token']),None)
            if not vigente or vigente['estado']!='executando' or vigente['pacote']!=reserva['pacote']:
                raise ValueError('Reserva mudou durante a correção')
            if (carregar(projeto)!=cfg or atual.get('state')!='open' or atual.get('draft') is not False
                or atual.get('merged') is not False or atual.get('number')!=dados['pr']
                or atual.get('head',{}).get('sha')!=dados['head_sha']
                or atual.get('head',{}).get('ref')!=branch
                or atual.get('head',{}).get('repo',{}).get('full_name')!=cfg['kanban']['repo']
                or atual.get('base',{}).get('ref')!=cfg['ciclo']['base'].removeprefix('origin/')
                or atual.get('base',{}).get('repo',{}).get('full_name')!=cfg['kanban']['repo']):
                raise ValueError('PR/commit/base divergente; não publicar correção')
            if not re.search(rf'(?:Closes|Fixes|Resolves|Parte de)\s+#{n}\b',atual.get('body') or '',re.I):
                raise ValueError('PR não vincula o cartão da correção')
            return atual
        pr_atual=conferir_pr()
        if git('rev-parse','HEAD')!=dados['head_sha']:
            raise ValueError('Checkout não corresponde ao commit revisado')
    nome_recibo=(str(n)+'-pr-'+str(dados['pr'])+'-'+dados['head_sha']) if atualizar else str(n)
    recibo=pasta_dados(projeto)/'publicacoes'/(nome_recibo+'.json');recibo.parent.mkdir(exist_ok=True)
    if recibo.exists():raise ValueError('Publicação anterior exige conciliação; não repetir')
    alterados=set(filter(None,git('diff','--name-only','-z','HEAD').split('\0')))
    novos=set(filter(None,git('ls-files','--others','--exclude-standard','-z').split('\0')))
    nomes=alterados|novos
    for nome in nomes:
        if nome in ('CLAUDE.md','AGENTS.md','.office/projeto.json') or nome.startswith(('.github/','.git/','.claude/hooks/','.claude/settings')):
            raise ValueError('Publicação não altera regras/política/hooks')
    pedidos=[]
    for nome in novos:
        arquivo=p/nome
        if (arquivo.suffix.lower()!='.json' or arquivo.is_symlink() or not arquivo.is_file()
            or arquivo.stat().st_size>128000):continue
        try:
            if json.loads(arquivo.read_text(encoding='utf-8-sig')) in (pedido_original,dados):pedidos.append(nome)
        except (ValueError,UnicodeError,OSError):pass
    # O envelope exato da operação é dado do controlador, não uma entrega do cartão.
    nomes.difference_update(pedidos)
    for nome in alterados:
        arquivo=p/nome
        if arquivo.suffix.lower()=='.json' and arquivo.is_file() and not arquivo.is_symlink() and arquivo.stat().st_size<=128000:
            try:
                if json.loads(arquivo.read_text(encoding='utf-8-sig')) in (pedido_original,dados):
                    raise ValueError('Pedido de publicação já versionado/indexado; retire-o da entrega antes de publicar')
            except (json.JSONDecodeError,UnicodeError,OSError):pass
    registro={'estado':'publicando','cartao':n,'worktree':str(p),'branch':branch,
              'arquivos_pedido_excluidos':sorted(pedidos)}
    if atualizar:
        conferir_pr()
        registro.update(pr=f"https://github.com/{cfg['kanban']['repo']}/pull/{dados['pr']}",head_anterior=dados['head_sha'],operacao='atualizar_pr')
        if not nomes:
            if pr_atual.get('title')==dados['titulo'] and pr_atual.get('body')==dados['corpo']:
                raise ValueError('Correção sem alterações de arquivos ou descrição')
            registro['operacao']='atualizar_descricao_pr'
    atomico(recibo,registro)
    if nomes:
        git('add','--all','--',*sorted(nomes));git('commit','-m',dados['titulo'])
    sha=git('rev-parse','HEAD')
    if atualizar:conferir_pr()
    if not atualizar or nomes:git('push','origin','HEAD:refs/heads/'+branch)
    if atualizar:
        atual=api(f"repos/{cfg['kanban']['repo']}/pulls/{dados['pr']}")
        if atual.get('head',{}).get('sha')!=sha:
            raise ValueError('Push sem confirmação remota; concilie antes de repetir')
        # A entrega pode ser documental no próprio PR; sem commit artificial ou push vazio.
        api(f"repos/{cfg['kanban']['repo']}/pulls/{dados['pr']}",'PATCH',
            {'title':dados['titulo'],'body':dados['corpo']})
        confirmacao=api(f"repos/{cfg['kanban']['repo']}/pulls/{dados['pr']}")
        if (confirmacao.get('head',{}).get('sha')!=sha or confirmacao.get('state')!='open'
            or confirmacao.get('title')!=dados['titulo'] or confirmacao.get('body')!=dados['corpo']):
            raise ValueError('Descrição sem confirmação remota; concilie antes de repetir')
        registro.update(estado='publicado',sha=sha)
        atomico(recibo,registro)
        return registro
    corpo=recibo.with_suffix('.md');corpo.write_text(dados['corpo'],encoding='utf-8')
    url=rodar(['gh','pr','create','--repo',cfg['kanban']['repo'],'--base',
        cfg['ciclo']['base'].removeprefix('origin/'),'--head',branch,'--title',dados['titulo'],'--body-file',str(corpo)])
    registro.update(estado='publicado',sha=sha,pr=url);atomico(recibo,registro)
    return registro
