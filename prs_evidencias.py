"""Evidências GitHub vinculadas ao projeto/PR/commit; nunca autorizam merge."""
from datetime import datetime
import re
import subprocess
import time
from urllib.parse import quote
from gestao_projeto import carregar
from kanban_painel import escolher
from kanban_gestao import api


def texto(v, limite=256):
    if not isinstance(v,str) or not v or len(v)>limite:
        raise ValueError('Texto inválido')
    return v


def ident(v):
    if type(v) is not int or v<1:
        raise ValueError('Identidade inválida')
    return v


def commit(v):
    if not isinstance(v,str) or not re.fullmatch('[0-9a-f]{40}|[0-9a-f]{64}',v):
        raise ValueError('Commit inválido')
    return v


def conferir(pr, repo, numero, sha):
    if (not isinstance(pr,dict) or type(pr.get('number')) is not int or pr['number']!=numero or
        pr.get('state')!='open' or pr.get('html_url')!=f'https://github.com/{repo}/pull/{numero}' or
        pr['base']['repo']['full_name'].lower()!=repo.lower()):
        raise ValueError('PR incompatível')
    if commit(pr['head']['sha'])!=sha:
        raise LookupError('Commit mudou')


def colecao(dados):
    if not isinstance(dados,list) or len(dados)>2000:
        raise ValueError('Cobertura inválida')
    return dados


def projetar_checks(runs, statuses, sha, obrigatorios):
    checks=[]; vistos=set()
    for r in colecao(runs):
        i=ident(r['id'])
        if i in vistos or commit(r['head_sha'])!=sha:
            raise ValueError('Check duplicado ou de outro commit')
        vistos.add(i)
        estado=r['status']; conclusao=r.get('conclusion')
        if estado not in ('queued','in_progress','completed','requested','waiting','pending'):
            raise ValueError('Estado de check desconhecido')
        if conclusao not in (None,'success','failure','neutral','cancelled','skipped','timed_out','action_required','stale','startup_failure'):
            raise ValueError('Conclusão desconhecida')
        if (estado=='completed') != (conclusao is not None):
            raise ValueError('Conclusão inconsistente')
        checks.append({'tipo':'check','id':i,'nome':texto(r['name']),
                       'estado':conclusao if estado=='completed' else 'pending',
                       'app_id':ident(r['app']['id'])})
    contextos=set(); vistos=set()
    # Contrato GitHub: statuses em ordem cronológica inversa; primeiro por contexto vale.
    for s in colecao(statuses):
        i=ident(s['id']); nome=texto(s['context'])
        if i in vistos or s['state'] not in ('error','failure','pending','success'):
            raise ValueError('Status inválido')
        vistos.add(i)
        if nome not in contextos:
            contextos.add(nome)
            checks.append({'tipo':'status','id':i,'nome':nome,'estado':s['state'],'app_id':None})
    gates=[]
    for nome in dict.fromkeys(obrigatorios):
        correspondentes=[c for c in checks if c['nome']==nome]
        estado=('ausente' if not correspondentes else 'ambíguo' if len(correspondentes)>1 else correspondentes[0]['estado'])
        gates.append({'nome':nome,'estado':estado})
    return checks,gates


def projetar_revisoes(dados, sha):
    revisoes=[]; vistos=set()
    for r in colecao(dados):
        i=ident(r['id']); estado=r['state']
        if i in vistos or estado not in ('APPROVED','CHANGES_REQUESTED','COMMENTED','DISMISSED','PENDING'):
            raise ValueError('Revisão inválida')
        vistos.add(i)
        revisado=r.get('commit_id')
        if revisado is not None: commit(revisado)
        data=r.get('submitted_at')
        if estado!='PENDING':
            if not isinstance(data,str) or len(data)>40 or datetime.fromisoformat(data.replace('Z','+00:00')).tzinfo is None:
                raise ValueError('Data de revisão inválida')
        else: data=None
        revisoes.append({'id':i,'autor':texto(r['user']['login']), 'estado':estado,
                         'sha':revisado, 'commit_atual':revisado==sha, 'enviada_em':data})
    return revisoes


def alvo_base(pr):
    """Base e commit fazem parte da evidência; mudar o alvo invalida a consulta."""
    base=pr['base']
    return texto(base['ref']),commit(base['sha'])


def projetar_regras(dados, checks, branch, sha_base):
    regras=[]; gates=[]; vistos=set()
    for r in colecao(dados):
        if not isinstance(r,dict): raise ValueError('Regra inválida')
        tipo=texto(r['type'],100); i=ident(r['ruleset_id'])
        fonte=r['ruleset_source_type']
        if fonte not in ('Repository','Organization','Enterprise') or (i,tipo) in vistos:
            raise ValueError('Origem de regra inválida ou duplicada')
        vistos.add((i,tipo)); regra={'tipo':tipo,'ruleset_id':i,'origem':fonte}
        if tipo=='required_status_checks':
            p=r['parameters']; obrigatorios=colecao(p['required_status_checks'])
            if type(p['strict_required_status_checks_policy']) is not bool:
                raise ValueError('Política de check inválida')
            regra['base_atualizada_exigida']=p['strict_required_status_checks_policy']
            nomes=set()
            for c in obrigatorios:
                nome=texto(c['context']); app=c.get('integration_id')
                if app is not None:ident(app)
                if (nome,app) in nomes:raise ValueError('Check obrigatório duplicado')
                nomes.add((nome,app))
                correspondentes=[x for x in checks if x['nome']==nome and (app is None or x['app_id']==app)]
                estado=('ausente' if not correspondentes else 'ambíguo' if len(correspondentes)>1 else correspondentes[0]['estado'])
                gates.append({'nome':nome,'app_id':app,'ruleset_id':i,'estado':estado})
        elif tipo=='pull_request':
            p=r['parameters']; n=p['required_approving_review_count']
            if type(n) is not int or not 0<=n<=100:raise ValueError('Contagem de aprovação inválida')
            regra['aprovacoes_exigidas']=n
            for chave in ('dismiss_stale_reviews_on_push','require_code_owner_review',
                          'require_last_push_approval','required_review_thread_resolution'):
                if type(p[chave]) is not bool:raise ValueError('Política de revisão inválida')
                regra[chave]=p[chave]
            # Regras novas de reviewers e outras extensões não são transformadas em aceite.
            regra['parametros_adicionais']=bool(set(p)-{'required_approving_review_count',
                'dismiss_stale_reviews_on_push','require_code_owner_review',
                'require_last_push_approval','required_review_thread_resolution'})
        regras.append(regra)
    return {'estado':'consultado','branch':branch,'sha_base':sha_base,
            'regras':regras,'gates':gates,
            'limite':'Regras ativas de rulesets. Proteção clássica, threads, CODEOWNERS, bypass, merge queue e avaliação final do GitHub não estão comprovados por esta leitura.'}


def ler(projetos, projeto_id, numero, sha, chamar=None, chamar_pendencias=None):
    resposta={'ok':False,'projeto_id':projeto_id if isinstance(projeto_id,str) and re.fullmatch('[0-9a-f]{20}',projeto_id) else '',
              'numero':numero if type(numero) is int else None,'sha':sha if isinstance(sha,str) and re.fullmatch('[0-9a-f]{40}|[0-9a-f]{64}',sha) else '',
              'checks':[],'gates':[],'revisoes':[],'erro':'',
              'regras_branch':{'estado':'indisponivel','regras':[],'gates':[]},
              'pendencias_revisao':{'estado':'indisponivel'}}
    try:
        ident(numero); commit(sha)
        if not isinstance(projeto_id,str) or not re.fullmatch('[0-9a-f]{20}',projeto_id):
            # A validação real é a seleção opaca; formato definido por id_projeto.
            raise ValueError('Projeto inválido')
        selecao=escolher(projetos,projeto_id,'evidências do PR')
        if selecao is None or selecao[2]: raise ValueError('Projeto não selecionado')
        raiz,cfg,publico=selecao[0]; repo=cfg['kanban']['repo']; chamada=chamar or api
        inicio=time.time(); base=f'repos/{repo}'
        pr=chamada(f'{base}/pulls/{numero}'); conferir(pr,repo,numero,sha)
        regras=None; alvo=None
        try:
            alvo=alvo_base(pr)
            url_regras=f'{base}/rules/branches/{quote(alvo[0],safe="")}?per_page=100'
            regras=chamada(url_regras,paginar=True)
        except (ValueError,TypeError,KeyError,OSError,RuntimeError,subprocess.SubprocessError):
            pass  # Acesso desconhecido não vira ausência de regras ou permissão de merge.
        runs=chamada(f'{base}/commits/{sha}/check-runs?filter=latest&per_page=100',paginar=True,campo='check_runs')
        statuses=chamada(f'{base}/commits/{sha}/statuses?per_page=100',paginar=True)
        revisoes=chamada(f'{base}/pulls/{numero}/reviews?per_page=100',paginar=True)
        checks,gates=projetar_checks(runs,statuses,sha,cfg['merge']['checks'])
        revisoes=projetar_revisoes(revisoes,sha)
        pendencias=resposta['pendencias_revisao']
        if alvo is not None and (chamar is None or chamar_pendencias is not None):
            from prs_pendencias import ler as ler_pendencias
            try:
                pendencias=ler_pendencias(repo,numero,sha,*alvo,chamar=chamar_pendencias)
                for g in pendencias['protecao_classica']['checks']:
                    correspondentes=[c for c in checks if c['nome']==g['nome'] and (g['app_id'] is None or c['app_id']==g['app_id'])]
                    g['estado']=('ausente' if not correspondentes else 'ambíguo' if len(correspondentes)>1 else correspondentes[0]['estado'])
            except (ValueError,TypeError,KeyError,AttributeError,OSError,RuntimeError,subprocess.SubprocessError):
                pendencias=resposta['pendencias_revisao']
        regras_publicas=resposta['regras_branch']
        if regras is not None:
            try:
                regras_publicas=projetar_regras(regras,checks,*alvo)
                if chamada(url_regras,paginar=True)!=regras:
                    raise LookupError('Rulesets mudaram')
            except (ValueError,TypeError,KeyError,OSError,RuntimeError,subprocess.SubprocessError):
                regras_publicas=resposta['regras_branch']
        final=chamada(f'{base}/pulls/{numero}'); conferir(final,repo,numero,sha)
        if alvo is not None and alvo_base(final)!=alvo:raise LookupError('Base do PR mudou')
        if carregar(raiz)!=cfg: raise LookupError('Política mudou')
        resposta.update(ok=True,repo=repo,checks=checks,gates=gates,revisoes=revisoes,regras_branch=regras_publicas,pendencias_revisao=pendencias,
                        rascunho=final.get('draft') is True,
                        mergeavel=final.get('mergeable') if type(final.get('mergeable')) is bool else None,
                        iniciado_em=inicio,coletado_em=time.time(),
                        aviso='Evidências observadas no commit solicitado. Não autorizam merge; identidade cloud, CODEOWNERS, bypass, merge queue e avaliação final do GitHub precisam ser conferidos.')
    except LookupError:
        resposta['erro']='Commit ou política mudou durante a consulta. Atualize a lista e consulte novamente.'
    except (ValueError,TypeError,KeyError,AttributeError,OSError,RuntimeError,subprocess.SubprocessError):
        resposta['erro']='Evidências indisponíveis ou incompletas. Confira projeto, commit e acesso do gh.'
    return resposta
