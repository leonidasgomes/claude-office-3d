"""Query GraphQL somente leitura: threads, reviewDecision e proteção clássica."""
import re
import time
from kanban_gestao import api

CONSULTA = '''query OfficePendencias($owner:String!,$repo:String!,$numero:Int!,$cursor:String){
  repository(owner:$owner,name:$repo){nameWithOwner
    pullRequest(number:$numero){number state headRefOid baseRefOid baseRefName isDraft reviewDecision
      baseRef{name branchProtectionRule{id requiredApprovingReviewCount
        requiresApprovingReviews requiresCodeOwnerReviews dismissesStaleReviews
        requireLastPushApproval requiresConversationResolution requiresStrictStatusChecks
        requiresStatusChecks requiredStatusChecks{context app{databaseId}}}}
      reviewThreads(first:100,after:$cursor){totalCount pageInfo{hasNextPage endCursor}
        nodes{id isResolved isOutdated}}
    }
  }
}'''
FLAGS=('requiresApprovingReviews','requiresCodeOwnerReviews','dismissesStaleReviews',
       'requireLastPushApproval','requiresConversationResolution','requiresStrictStatusChecks','requiresStatusChecks')


def graphql(variaveis):
    return api('graphql',metodo='POST',dados={'query':CONSULTA,'variables':variaveis})


def texto(v):
    if not isinstance(v,str) or not v or len(v)>256 or any(ord(c)<32 for c in v):
        raise ValueError('Identidade GraphQL inválida')
    return v


def protecao(dados):
    if dados is None:return {'estado':'ausente','checks':[]}
    if not isinstance(dados,dict):raise ValueError('Proteção clássica inválida')
    texto(dados['id'])
    saida={'estado':'consultado'}
    for chave in FLAGS:
        if type(dados[chave]) is not bool:raise ValueError('Flag de proteção inválida')
        saida[chave]=dados[chave]
    n=dados['requiredApprovingReviewCount']
    if n is not None and (type(n) is not int or not 0<=n<=100):raise ValueError('Contagem inválida')
    if dados['requiresApprovingReviews'] and n is None:raise ValueError('Contagem desconhecida')
    saida['aprovacoes_exigidas']=n
    checks=dados['requiredStatusChecks']
    if checks is None:
        if dados['requiresStatusChecks']:raise ValueError('Checks desconhecidos')
        checks=[]
    if not isinstance(checks,list) or len(checks)>2000:raise ValueError('Checks inválidos')
    saida['checks']=[]; vistos=set()
    for c in checks:
        nome=texto(c['context']);app=c['app']
        app_id=app['databaseId'] if app is not None else None
        if app is not None and (type(app_id) is not int or app_id<1):raise ValueError('App desconhecido')
        if (nome,app_id) in vistos:raise ValueError('Check duplicado')
        vistos.add((nome,app_id));saida['checks'].append({'nome':nome,'app_id':app_id})
    return saida


def coletar(repo, numero, sha, branch, sha_base, chamar, prazo):
    owner,nome=repo.split('/');cursor=None;cursores=set();threads={};snapshot=None;total=None
    for _ in range(20):
        if time.monotonic()>prazo:raise ValueError('Prazo de coleta excedido')
        envelope=chamar({'owner':owner,'repo':nome,'numero':numero,'cursor':cursor})
        if time.monotonic()>prazo:raise ValueError('Prazo de coleta excedido')
        if (not isinstance(envelope,dict) or
                (envelope.get('errors') is not None and
                 (not isinstance(envelope['errors'],list) or envelope['errors']))):
            raise ValueError('GraphQL retornou erros ou dados parciais')
        r=envelope['data']['repository'];pr=r['pullRequest']
        if (r['nameWithOwner'].casefold()!=repo.casefold() or type(pr['number']) is not int
            or pr['number']!=numero or pr['state']!='OPEN' or pr['headRefOid']!=sha
            or pr['baseRefOid']!=sha_base or pr['baseRefName']!=branch
            or pr['baseRef']['name']!=branch):raise LookupError('PR/base mudou na consulta GraphQL')
        if type(pr['isDraft']) is not bool or pr['reviewDecision'] not in (None,'APPROVED','CHANGES_REQUESTED','REVIEW_REQUIRED'):
            raise ValueError('Estado de revisão desconhecido')
        atual={'decisao_revisao':pr['reviewDecision'],'rascunho':pr['isDraft'],
               'protecao_classica':protecao(pr['baseRef']['branchProtectionRule']),
               '_protecao_id':pr['baseRef']['branchProtectionRule']['id'] if pr['baseRef']['branchProtectionRule'] is not None else None}
        if snapshot is not None and atual!=snapshot:raise LookupError('Revisão/proteção mudou durante paginação')
        snapshot=atual;c=pr['reviewThreads'];info=c['pageInfo'];nodes=c['nodes'];n=c['totalCount']
        if type(n) is not int or not 0<=n<=2000 or type(info['hasNextPage']) is not bool or not isinstance(nodes,list) or len(nodes)>100:
            raise ValueError('Página de threads inválida')
        if total is not None and n!=total:raise LookupError('Quantidade de threads mudou')
        total=n
        for t in nodes:
            i=texto(t['id'])
            if i in threads or type(t['isResolved']) is not bool or type(t['isOutdated']) is not bool:
                raise ValueError('Thread duplicada ou inválida')
            threads[i]=(t['isResolved'],t['isOutdated'])
        if not info['hasNextPage']:
            if len(threads)!=total:raise ValueError('Cobertura de threads incompleta')
            return snapshot,threads
        prox=info['endCursor']
        if not nodes or not isinstance(prox,str) or not prox or len(prox)>1024 or prox in cursores or len(threads)>=total:
            raise ValueError('Cursor inválido ou repetido')
        cursores.add(prox);cursor=prox
    raise ValueError('Limite de paginação de threads excedido')


def ler(repo,numero,sha,branch,sha_base,chamar=None):
    if (not isinstance(repo,str) or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repo)
            or type(numero) is not int or numero<1 or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}',sha or '')
            or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}',sha_base or '')):raise ValueError('Alvo inválido')
    texto(branch);consulta=chamar or graphql;prazo=time.monotonic()+60
    try:
        antes=coletar(repo,numero,sha,branch,sha_base,consulta,prazo)
        depois=coletar(repo,numero,sha,branch,sha_base,consulta,prazo)
    except (KeyError,TypeError,AttributeError) as exc:
        raise ValueError('Cobertura GraphQL inválida ou incompleta') from exc
    if antes!=depois:raise LookupError('Threads/revisão/proteção mudaram durante coleta')
    s,threads=depois;s={k:v for k,v in s.items() if not k.startswith('_')}
    return {'estado':'consultado','branch':branch,'sha_base':sha_base,**s,
            'threads_total':len(threads),'threads_pendentes':sum(not x[0] for x in threads.values()),
            'threads_pendentes_desatualizadas':sum(not x[0] and x[1] for x in threads.values()),
            'limite':'A decisão é informada pelo GitHub, sem atestar clouds independentes. Threads desatualizadas continuam pendentes até serem resolvidas. Não autoriza merge; bypass/CODEOWNERS/merge queue e estado futuro exigem avaliação própria.'}
