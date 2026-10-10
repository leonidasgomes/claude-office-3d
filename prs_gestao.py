"""PRs do repositório canônico por projeto. Só leitura; nenhum veredito de merge."""
import re
import subprocess
import time
from gestao_projeto import carregar
from kanban_painel import escolher
from kanban_gestao import api


def vista(projetos, ident=None, chamar=None):
    selecao=escolher(projetos,ident,'painel de PRs')
    if selecao is None: return None
    escolhido,publicos,erro=selecao
    resposta={'fonte':'gestao','configurado':True,'projetos':publicos,'projeto_id':'',
              'repo':'','prs':[],'erro':erro,'atualizado':'','limite':'','limitado':False}
    if erro: return resposta
    raiz,cfg,publico=escolhido; repo=cfg['kanban']['repo']
    resposta.update(repo=repo,projeto_id=publico['id'],merge=cfg['merge']['modo'])
    try:
        dados=(chamar or api)(f'repos/{repo}/pulls?state=open&per_page=100',paginar=True)
        if not isinstance(dados,list): raise ValueError('Lista inválida')
        prs=[]; vistos=set()
        for pr in dados[:1000]:
            n=pr['number']; sha=pr['head']['sha']
            if (type(n) is not int or n<1 or n in vistos or pr.get('state')!='open'
                or pr['html_url']!=f'https://github.com/{repo}/pull/{n}'
                or not isinstance(sha,str) or not re.fullmatch('[0-9a-fA-F]{40}|[0-9a-fA-F]{64}',sha)
                or (pr.get('base') or {}).get('repo',{}).get('full_name','').lower()!=repo.lower()):
                raise ValueError('PR incompatível com o projeto')
            vistos.add(n)
            prs.append({'numero':n,'titulo':str(pr['title']),'url':pr['html_url'],
                        'branch':str(pr['head']['ref']),'sha':sha,'rascunho':bool(pr.get('draft')),
                        'autor':str((pr.get('user') or {}).get('login','')),
                        'rotulos':[],'fecha':[],'revisao':'','checks':{},'conflito':False,
                        'validacao':'Gates e revisões deste projeto ainda precisam ser conferidos no commit atual.'})
        # Política alterada durante a consulta não pode receber a resposta anterior.
        if carregar(raiz)!=cfg: raise ValueError('Política mudou')
        resposta.update(prs=prs,atualizado=time.strftime('%H:%M:%S'),limitado=len(dados)>1000)
    except (ValueError,TypeError,KeyError,AttributeError,OSError,RuntimeError,subprocess.SubprocessError):
        resposta['erro']='Não foi possível ler os PRs da política deste projeto. Confira configuração e acesso do gh.'
    return resposta
