"""Gestão por projeto: estado e despacho pelo mesmo Kanban para todos os consoles."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import sqlite3
import time
import os
import uuid
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED

from controle_tarefas import Controle, ocupar_worktree
from skills_compartilhados import nomes_cartao, resolver as resolver_skills
from gestao_projeto import carregar, contexto, executor, revisores, fontes_resolvidas
from kanban_gestao import Kanban
from providers_console import selecionar
from console_provider import executar
from dependencias_tarefas import verificar as verificar_dependencias, conferir as conferir_dependencias

RAIZ = Path(__file__).resolve().parent


def pasta_dados(projeto):
    chave = hashlib.sha256(str(Path(projeto).resolve()).encode()).hexdigest()[:20]
    return RAIZ / "dados" / "gestao" / chave


def campo(corpo, nome):
    m = re.search(rf"\*\*{nome}:\*\*\s*(.+?)(?=\n\s*\n|\n---|\*\*[A-ZÀ-Ú][^*]{{0,40}}:\*\*|$)", corpo, re.S | re.I)
    return m.group(1).strip() if m else ""


def instrucoes_cartao(issue):
    """Única projeção das instruções canônicas usadas no despacho e nos gates."""
    corpo = issue.get('body') or ''
    return {'objetivo': campo(corpo, 'Objetivo') or issue.get('title', ''),
            'aceite': campo(corpo, 'Aceite'),
            'escopo': campo(corpo, 'Escopo') or 'Somente o necessário para o aceite',
            'skills': campo(corpo, 'Skills')}


def conferir_cartao(k, numero, projeto, cfg, equipe, pacote, status):
    if carregar(projeto)!=cfg:
        raise ValueError('Política mudou antes da conferência do cartão; concilie com o projeto')
    cartao = k.cartao(numero, ao_vivo=True)
    issue = k.issue(numero)
    if (cartao['status'] != status or cartao['equipe'] != equipe
        or cartao.get('prioridade','') != pacote.get('prioridade','')
        or issue.get('state') != 'open' or issue.get('pull_request')
        or any(pacote[chave] != valor for chave, valor in instrucoes_cartao(issue).items())):
        raise ValueError('Cartão/instruções mudou desde o despacho; concilie com o Kanban')
    nomes=nomes_cartao(pacote['skills']) + (pacote.get('funcionario') or {}).get('skills',[])
    rota=pacote['executor']
    if resolver_skills(projeto,nomes,cfg,rota['console'],rota.get('execucao','cloud')=='local') != pacote['skills_resolvidas']:
        raise ValueError('Skill mudou desde o despacho; concilie com a fonte compartilhada')
    if fontes_resolvidas(projeto,cfg)!=pacote['fontes_resolvidas']:
        raise ValueError('Fonte documental mudou desde o despacho; concilie com a raiz canônica')
    if carregar(projeto)!=cfg:
        raise ValueError('Política mudou durante a conferência do cartão; concilie com o projeto')
    return issue


def preparar(projeto, numero, equipe, escopo="implementacao", kanban=None, funcionario=None, ao_vivo=True):
    cfg = carregar(projeto)
    membro = None
    if funcionario:
        import funcionarios
        membro, rota = funcionarios.executor(projeto, funcionario, equipe, escopo)
    else:
        rota = executor(cfg, equipe=equipe, escopo=escopo)
    for revisor in revisores(cfg, rota):
        selecionar(revisor["executor"]["console"])
    if rota.get("execucao", "cloud") != "cloud":
        from executor_local import validar_modelo
        from recursos_local import verificar
        verificar(cfg)
        validar_modelo(rota)
    # Resolve o CLI antes de reservar/mudar o quadro; não muda conta silenciosamente.
    provider, exe = selecionar(rota["console"])
    k = kanban or Kanban(cfg, pasta_dados(projeto) / "kanban.json")
    cartao = k.cartao(numero, ao_vivo=ao_vivo)
    if cartao["status"] != cfg["kanban"]["backlog"]:
        raise ValueError("Despacho novo exige cartão no Backlog; use retomada para execução existente")
    if cartao["equipe"] != equipe:
        raise ValueError("Equipe diverge do campo Time do Kanban")
    issue = k.issue(numero)
    if issue.get("state") != "open" or issue.get("pull_request"):
        raise ValueError("Cartão deve ser uma issue aberta")
    corpo = issue.get("body") or ""
    aceite = campo(corpo, "Aceite")
    if not aceite:
        raise ValueError("Cartão sem **Aceite:**; escreva critérios verificáveis antes do despacho")
    dependencias = verificar_dependencias(k, numero, corpo)
    pacote = {**instrucoes_cartao(issue), "cartao": numero, "url": issue.get("html_url"),
              "executor": rota, "dependencias": dependencias, "prioridade":cartao.get("prioridade","")}
    if membro:
        pacote['funcionario']=membro
    pacote['fontes_resolvidas']=fontes_resolvidas(projeto,cfg)
    pacote['skills_resolvidas']=resolver_skills(projeto,nomes_cartao(pacote['skills']) + (membro or {}).get('skills',[]),cfg,
                                               rota['console'],rota.get('execucao','cloud')=='local')
    return cfg, provider, exe, k, pacote


def planejar(projeto, max_cartoes=10, kanban=None, apos_cartao=0):
    """Diagnóstico do diretor. Não reserva, move cartões ou executa modelos."""
    if type(max_cartoes) is not int or not 1 <= max_cartoes <= 20:
        raise ValueError('max-cartoes deve estar entre 1 e 20')
    if type(apos_cartao) is not int or apos_cartao < 0:
        raise ValueError('apos-cartao deve ser inteiro não negativo')
    cfg = carregar(projeto)
    if not cfg['ativo']:
        raise ValueError('Gestão não habilitada neste projeto')
    k = kanban or Kanban(cfg, pasta_dados(projeto) / 'kanban.json')
    cartoes = [c for c in k.cartoes(ao_vivo=True) if c['status'] == cfg['kanban']['backlog']]
    prioridades=cfg['kanban']['prioridades']
    if prioridades:
        ordem={p:i for i,p in enumerate(prioridades)}
        cartoes.sort(key=lambda c:(ordem.get(c.get('prioridade',''),len(ordem)),c['numero']))
        if apos_cartao:
            posicao=next((i for i,c in enumerate(cartoes) if c['numero']==apos_cartao),None)
            if posicao is None:
                raise ValueError('Cursor não está mais no Backlog; reinicie o diagnóstico de prioridades')
            cartoes=cartoes[posicao+1:]
    else:
        cartoes=sorted((c for c in cartoes if c['numero']>apos_cartao),key=lambda c:c['numero'])
    estados = {}
    banco = pasta_dados(projeto) / 'tarefas.db'
    if banco.is_file():
        try:
            with closing(sqlite3.connect(banco.resolve().as_uri() + '?mode=ro', uri=True, timeout=5)) as db:
                estados = dict(db.execute('SELECT cartao,estado FROM reserva WHERE projeto=?', (cfg['kanban']['repo'],)))
        except sqlite3.Error as exc:
            raise ValueError('Estado local das tarefas indisponível; concilie antes de planejar') from exc
    saida = []
    for cartao in cartoes[:max_cartoes]:
        item = dict(cartao, preparavel=False)
        try:
            if prioridades and cartao.get('prioridade','') not in prioridades:
                raise ValueError('Prioridade ausente ou fora da ordem configurada no projeto')
            estado = estados.get(str(cartao['numero']))
            if estado and estado not in ('cancelado','concluido'):
                raise ValueError(f'Cartão já tem reserva {estado}; requer conciliação')
            pacote = preparar(projeto, cartao['numero'], cartao['equipe'], kanban=k, ao_vivo=False)[4]
            if carregar(projeto) != cfg:
                raise ValueError('Política mudou durante o diagnóstico')
            item.update(preparavel=True, pacote=pacote)
        except (ValueError, OSError, subprocess.SubprocessError) as exc:
            item['bloqueio'] = str(exc)
        saida.append(item)
    if carregar(projeto) != cfg:
        raise ValueError('Política mudou durante o diagnóstico')
    restantes = max(0,len(cartoes)-len(saida))
    return {'apenas_diagnostico':True, 'consultado_em':time.time(), 'repo':cfg['kanban']['repo'],
            'ceo':cfg['ceo'], 'diretor':cfg['diretor'], 'cartoes':saida,
            'ordem':{'criterio':'prioridade' if prioridades else 'numero','prioridades':prioridades},
            'nao_avaliados':restantes, 'proximo_cartao':saida[-1]['numero'] if restantes else None}


def estado_git(trabalho):
    def git(*args):
        return subprocess.run(['git','-C',str(trabalho),*args],capture_output=True,text=True,
            encoding='utf-8',check=True,timeout=10).stdout.strip()
    return {'branch':git('branch','--show-current'),'sha':git('rev-parse','--verify','HEAD^{commit}')}


def conferir_disponibilidade(projeto, cfg, numero, trabalho):
    banco=pasta_dados(projeto)/'tarefas.db'
    if banco.is_file():
        with closing(sqlite3.connect(banco.resolve().as_uri()+'?mode=ro',uri=True,timeout=5)) as db:
            atual=db.execute('SELECT estado FROM reserva WHERE projeto=? AND cartao=?',
                (cfg['kanban']['repo'],str(numero))).fetchone()
        if atual and atual[0] not in ('cancelado','concluido'):
            raise ValueError('Cartão já reservado; concilie antes de iniciar lote')
    ocupacoes=banco_worktrees(trabalho)
    if ocupacoes.is_file():
        with closing(sqlite3.connect(ocupacoes.resolve().as_uri()+'?mode=ro',uri=True,timeout=5)) as db:
            recurso=os.path.normcase(str(Path(trabalho).resolve()))
            if db.execute('SELECT 1 FROM worktree_ocupado WHERE recurso=?',(recurso,)).fetchone():
                raise ValueError('Worktree já ocupado; concilie antes de iniciar lote')


def preparar_lote(projeto, plano, kanban=None):
    """Pré-valida todos os cartões/worktrees; sem reservar, inferir ou mover."""
    if not isinstance(plano,dict) or 'cartoes' not in plano or set(plano)-{'cartoes','paralelismo'}:
        raise ValueError('Plano de lote exige cartoes e paralelismo opcional')
    paralelismo=plano.get('paralelismo',1)
    if type(paralelismo) is not int or not 1<=paralelismo<=4:
        raise ValueError('Paralelismo exige inteiro de 1 a 4')
    itens=plano['cartoes']
    if not isinstance(itens,list) or not 1<=len(itens)<=20:
        raise ValueError('Lote exige entre 1 e 20 cartões')
    cfg=carregar(projeto)
    if not cfg['ativo']: raise ValueError('Gestão não habilitada neste projeto')
    numeros=set(); caminhos=set(); entradas=[]
    for item in itens:
        if (not isinstance(item,dict) or set(item)-{'cartao','worktree','escopo','funcionario'}
            or type(item.get('cartao')) is not int or item['cartao']<1
            or not isinstance(item.get('worktree'),str) or not item['worktree'].strip()
            or not Path(item['worktree']).is_absolute()
            or item.get('escopo','implementacao') not in ('planejamento','implementacao','revisao','simples')
            or ('funcionario' in item and (not isinstance(item['funcionario'],str) or not item['funcionario']))):
            raise ValueError('Entrada do lote inválida; informe cartão e worktree absoluto')
        trabalho=Path(item['worktree']).resolve()
        caminho=os.path.normcase(str(trabalho))
        if item['cartao'] in numeros or caminho in caminhos:
            raise ValueError('Lote não pode repetir cartão ou worktree')
        numeros.add(item['cartao']); caminhos.add(caminho)
        entradas.append({**item,'worktree':str(trabalho),'escopo':item.get('escopo','implementacao')})
    k=kanban or Kanban(cfg,pasta_dados(projeto)/'kanban.json')
    quadro={c['numero']:c for c in k.cartoes(ao_vivo=True)}
    prioridades=cfg['kanban']['prioridades']
    for item in entradas:
        cartao=quadro.get(item['cartao'])
        if not cartao: raise ValueError('Cartão do lote não está no Kanban do projeto')
        if prioridades and cartao.get('prioridade','') not in prioridades:
            raise ValueError('Cartão do lote sem prioridade na ordem configurada')
        item['equipe']=cartao['equipe']; item['prioridade']=cartao.get('prioridade','')
    entradas.sort(key=lambda i:((prioridades.index(i['prioridade']) if prioridades else 0),i['cartao']))
    branches=set()
    for item in entradas:
        atual,_,_,_,pacote=preparar(projeto,item['cartao'],item['equipe'],item['escopo'],k,
            item.get('funcionario'),ao_vivo=False)
        if atual!=cfg: raise ValueError('Política mudou durante preparação do lote')
        trabalho=validar_worktree(projeto,item['worktree'])
        item['git']=estado_git(trabalho)
        if item['git']['branch'] in branches:
            raise ValueError('Lote exige branch distinto por cartão')
        branches.add(item['git']['branch'])
        conferir_disponibilidade(projeto,cfg,item['cartao'],trabalho)
        item['pacote']=pacote
    if carregar(projeto)!=cfg: raise ValueError('Política mudou durante preparação do lote')
    return {'politica':cfg,'cartoes':entradas,'modo':'paralelo' if paralelismo>1 else 'sequencial','paralelismo':paralelismo,'somente_preparacao':True}


def executar_lote(projeto, plano, kanban=None, despacho=None, esperado=None):
    preparado=preparar_lote(projeto,plano,kanban)
    if esperado is not None:
        from coordenacao import identidade
        if identidade(preparado)!=identidade(esperado):
            raise ValueError('Lote diverge da seleção do CEO/diretor; coordene novamente')
    cfg=preparado['politica']; ident=uuid.uuid4().hex
    arquivo=pasta_dados(projeto)/'lotes'/(ident+'.json')
    registro={'id':ident,'repo':cfg['kanban']['repo'],'estado':'preparado','atualizado':time.time(),
              'cartoes':[i['cartao'] for i in preparado['cartoes']],'resultados':[], 'cartao_em_execucao':None}
    def salvar():
        registro['atualizado']=time.time()
        arquivo.parent.mkdir(parents=True,exist_ok=True)
        tmp=arquivo.with_suffix('.tmp')
        try:
            tmp.write_text(json.dumps(registro,ensure_ascii=False),encoding='utf-8')
            tmp.replace(arquivo)
        finally: tmp.unlink(missing_ok=True)
    salvar()
    def despachar_item(item):
        return (despacho or despachar)(projeto,item['cartao'],item['equipe'],item['escopo'],item['worktree'],
            kanban=kanban,funcionario=item.get('funcionario'),
            esperado={'politica':cfg,'pacote':item['pacote'],'git':item['git']})
    try:
        if preparado['paralelismo']>1:
            registro.update(paralelismo=preparado['paralelismo'],cartoes_em_execucao=[])
            executar_lote_paralelo(preparado,registro,salvar,despachar_item)
            return {**registro,'relatorio':str(arquivo)}
        for item in preparado['cartoes']:
            registro.update(estado='executando',cartao_em_execucao=item['cartao']); salvar()
            resultado=despachar_item(item)
            registro['resultados'].append({'cartao':item['cartao'],'estado':resultado['estado'],'codigo':resultado['codigo']})
            registro['cartao_em_execucao']=None
            if resultado['estado']!='revisao' or resultado['codigo']:
                registro['estado']='interrompido'; salvar(); break
            salvar()
        else:
            registro['estado']='processado'; salvar()
    except BaseException:
        # Não presume que filhos morreram ou que a mutação remota foi revertida.
        registro['estado']='incerto'; salvar(); raise
    return {**registro,'relatorio':str(arquivo)}


def executar_lote_paralelo(preparado, registro, salvar, despacho):
    """Só o controlador grava o relatório; aguarda os iniciados e nunca repete cartão."""
    itens=iter(preparado['cartoes']); ordem=registro['cartoes']; ativos={}
    interrompido=False; erro=None; esgotado=False
    with ThreadPoolExecutor(max_workers=preparado['paralelismo']) as pool:
        while ativos or not esgotado:
            while not interrompido and not esgotado and len(ativos)<preparado['paralelismo']:
                try: item=next(itens)
                except StopIteration:
                    esgotado=True; break
                # Publica a intenção antes de iniciar; queda aqui exige conciliação.
                registro['cartoes_em_execucao'].append(item['cartao'])
                registro['estado']='executando'; salvar()
                ativos[pool.submit(despacho,item)]=item['cartao']
            if not ativos: break
            prontos,_=wait(ativos,return_when=FIRST_COMPLETED)
            # Drena todos os retornos já conhecidos antes de admitir outro cartão.
            prontos.update(f for f in ativos if f.done())
            for futuro in prontos:
                numero=ativos.pop(futuro)
                try:
                    r=futuro.result()
                    if (not isinstance(r,dict) or r.get('estado') not in ('revisao','bloqueado')
                        or type(r.get('codigo')) is not int):
                        raise ValueError('Retorno do despacho inválido')
                    registro['resultados'].append({'cartao':numero,'estado':r['estado'],'codigo':r['codigo']})
                    registro['resultados'].sort(key=lambda r:ordem.index(r['cartao']))
                    registro['cartoes_em_execucao'].remove(numero)
                    if r['estado']!='revisao' or r['codigo']: interrompido=True
                except BaseException as exc:
                    erro=erro or exc; interrompido=True
                    # Falhou sem comprovar término: mantém número para conciliação.
                registro['estado']='incerto' if erro else 'interrompido' if interrompido else 'executando'
                salvar()
            if interrompido: esgotado=True
    if erro: raise erro
    registro['estado']='interrompido' if interrompido else 'processado'; salvar()


def validar_worktree(projeto, worktree):
    def git(pasta, *args):
        r = subprocess.run(["git", "-C", str(pasta), *args], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=10, check=True)
        return r.stdout.strip()
    raiz = Path(projeto).resolve()
    trabalho = Path(worktree).resolve()
    comum = Path(git(raiz, "rev-parse", "--path-format=absolute", "--git-common-dir")).resolve()
    if Path(git(trabalho, "rev-parse", "--path-format=absolute", "--git-common-dir")).resolve() != comum:
        raise ValueError("Worktree pertence a outro repositório")
    principal=Path(git(raiz,'rev-parse','--show-toplevel')).resolve()
    destino=Path(git(trabalho,'rev-parse','--show-toplevel')).resolve()
    if destino==principal:
        raise ValueError('Use um worktree separado; o checkout principal pode estar sendo usado por outra equipe')
    if trabalho!=destino:
        raise ValueError('Informe a raiz do worktree, não uma subpasta')
    branch = git(trabalho, "branch", "--show-current")
    if not branch or branch in ("main", "master", "codex/unreal-mvp"):
        raise ValueError("Despacho exige branch próprio em worktree")
    if git(trabalho, "status", "--porcelain"):
        raise ValueError("Worktree tem alterações; concilie antes de iniciar outro agente")
    return trabalho


def banco_worktrees(trabalho):
    comum=subprocess.run(['git','-C',str(trabalho),'rev-parse','--path-format=absolute','--git-common-dir'],
        capture_output=True,text=True,encoding='utf-8',check=True,timeout=10).stdout.strip()
    pasta=Path(comum)
    if not pasta.is_absolute() or not pasta.is_dir():
        raise ValueError('Diretório compartilhado do Git inválido')
    return pasta/'office-execucoes.db'


def snapshot_pacote(pacote):
    # Nova consulta deve comprovar as mesmas dependências, com horário atualizado.
    return {**pacote,'dependencias':{k:v for k,v in pacote['dependencias'].items() if k!='verificadas_em'}}


def despachar(projeto, numero, equipe, escopo, worktree, banco=None, kanban=None, rodar=executar, revisar=None, funcionario=None,
              banco_execucoes=None, esperado=None):
    preparado=preparar(projeto, numero, equipe, escopo, kanban, funcionario)
    if esperado is not None and (preparado[0]!=esperado['politica'] or snapshot_pacote(preparado[4])!=snapshot_pacote(esperado['pacote'])):
        raise ValueError('Despacho diverge do plano do lote; prepare novamente')
    trabalho=validar_worktree(projeto,worktree)
    with ocupar_worktree(banco_execucoes or banco_worktrees(trabalho),trabalho):
        # Outro agente pode ter alterado o checkout entre a primeira leitura e a trava.
        trabalho=validar_worktree(projeto,worktree)
        if esperado is not None and estado_git(trabalho)!=esperado['git']:
            raise ValueError('Branch/HEAD mudou desde o plano do lote')
        return _despachar(projeto,numero,equipe,escopo,trabalho,banco,rodar,revisar,funcionario,preparado)


def _despachar(projeto, numero, equipe, escopo, trabalho, banco, rodar, revisar, funcionario, preparado, retomada=None, ao_execucao=None):
    cfg, provider, exe, k, pacote = preparado
    from skills_execucao import conferir_worktree
    conferir_worktree(trabalho,pacote['skills_resolvidas'])
    controle = Controle(banco or pasta_dados(projeto) / "tarefas.db")
    chave = cfg["kanban"]["repo"]
    if retomada is None:
        pacote={**pacote,'contexto_execucao':{'worktree':str(Path(trabalho).resolve()),
            'branch':estado_git(trabalho)['branch'],'escopo':escopo,
            'politica_sha256':hashlib.sha256(json.dumps(cfg,sort_keys=True,ensure_ascii=False).encode()).hexdigest()}}
        token = controle.reservar(chave, str(numero), equipe, provider.nome, pacote, quadro_atual=True)
    else:
        token=retomada['token']
    medicao=None; retorno_registrado=False; resultado_registrado=False
    try:
        if carregar(projeto) != cfg:
            raise ValueError('Política mudou antes do despacho')
        inicio = conferir_cartao(k,numero,projeto,cfg,equipe,pacote,
            cfg['kanban']['andamento'] if retomada else cfg['kanban']['backlog'])
        if retomada:controle.retomar(retomada)
        controle.registrar_dependencias(token,'antes_execucao',
            conferir_dependencias(k, numero, inicio.get('body') or '', pacote['dependencias']))
        if retomada is None:k.mover(numero, cfg["kanban"]["andamento"])
        if retomada is None:controle.transicao(token, "executando")
        prompt = contexto(projeto, cfg, equipe=equipe) + "\n\nDespacho:\n" + json.dumps(pacote, ensure_ascii=False)
        nome = equipe
        if funcionario:
            import funcionarios
            atual, _ = funcionarios.executor(projeto,funcionario,equipe,escopo)
            if atual != pacote['funcionario']: raise ValueError('Cadastro mudou antes da execução')
            prompt = funcionarios.contexto(projeto,atual) + '\n\nDespacho:\n' + json.dumps(pacote,ensure_ascii=False)
            nome = funcionarios.nome_eventos(atual)
        from skills_compartilhados import instrucoes_ativacao
        prompt += instrucoes_ativacao(pacote['skills_resolvidas'])
        medicao=controle.iniciar_execucao(token,'retomada' if retomada else 'despacho')
        if ao_execucao is not None:ao_execucao(token,medicao)
        inicio_execucao=time.monotonic()
        from atividade_execucao import Acompanhamento
        with Acompanhamento(controle.banco,medicao) as atividade:
            if pacote['executor'].get('execucao','cloud') == 'local':
                from executor_local import executar as local
                codigo = local(pacote['executor'],cfg,provider,exe,trabalho,nome,prompt,
                               projeto_consumo=projeto,tentativa_consumo=medicao,
                               ao_sessao=lambda ident:controle.vincular_sessao(token,provider.nome,ident),
                               ao_processo=atividade.vincular,ao_evento=atividade.evento)
            else:
                parametros_skills={}
                nativas=[r['nome'] for r in pacote['skills_resolvidas'] if r.get('ativacao_nativa')=='Skill']
                if nativas:
                    parametros_skills={'skills_nativas':nativas,
                                       'ao_skills':lambda e:controle.registrar_skills(token,e)}
                codigo = rodar(provider, exe, trabalho, nome, prompt=prompt, modelo=pacote["executor"].get("modelo") or None,
                               projeto_consumo=projeto,tentativa_consumo=medicao,
                               ao_sessao=lambda ident:controle.vincular_sessao(token,provider.nome,ident),
                               ao_processo=atividade.vincular,ao_evento=atividade.evento,
                               **({'sessao':retomada['sessao']} if retomada else {}),
                               **({'sandbox':pacote['executor']['sandbox']} if 'sandbox' in pacote['executor'] else {}),**parametros_skills)
                if nativas and not controle.skills(token).get('valida'):
                    if codigo==0: codigo=1
        controle.terminar_execucao(medicao,codigo,time.monotonic()-inicio_execucao)
        retorno_registrado=True
        if codigo:
            controle.transicao(token, "bloqueado")
            controle.registrar_resultado(medicao,'falha_console');resultado_registrado=True
        else:
            if carregar(projeto) != cfg:
                raise ValueError('Política mudou durante a execução')
            conferir_worktree(trabalho,pacote['skills_resolvidas'])
            if funcionario and funcionarios.executor(projeto,funcionario,equipe,escopo)[0] != pacote['funcionario']:
                raise ValueError('Cadastro mudou durante a execução')
            conferir_cartao(k,numero,projeto,cfg,equipe,pacote,cfg['kanban']['andamento'])
            branch = subprocess.run(["git", "-C", str(trabalho), "branch", "--show-current"],
                                    capture_output=True, text=True, check=True, timeout=10).stdout.strip()
            entrega = k.entrega(numero, branch)
            if entrega:
                atual_issue = k.issue(numero)
                controle.registrar_dependencias(token,'entrega',
                    conferir_dependencias(k, numero, atual_issue.get('body') or '', pacote['dependencias']))
                if cfg['revisao']['ativo']:
                    import revisao_execucao
                    sha = revisao_execucao.git(trabalho, 'rev-parse', '--verify', 'HEAD^{commit}')
                    head, base = (entrega.get('head') or {}).get('sha'), (entrega.get('base') or {}).get('sha')
                    if head != sha or not re.fullmatch('[0-9a-f]{40}', base or ''):
                        raise ValueError('PR diverge do commit local ou não informa base exata')
                    parametros = {'escopo':escopo}
                    if funcionario: parametros['funcionario']=funcionario
                    relatorio = (revisar or revisao_execucao.executar)(
                        projeto, trabalho, base, equipe, pacote['aceite'], **parametros)
                    atual_pr = k.entrega(numero, branch)
                    cartao_atual = k.cartao(numero, ao_vivo=True)
                    issue_atual = conferir_cartao(k,numero,projeto,cfg,equipe,pacote,cfg['kanban']['andamento'])
                    controle.registrar_dependencias(token,'apos_revisao',
                        conferir_dependencias(k, numero, issue_atual.get('body') or '', pacote['dependencias']))
                    if funcionario and funcionarios.executor(projeto,funcionario,equipe,escopo)[0] != pacote['funcionario']:
                        raise ValueError('Cadastro mudou durante a revisão')
                    if (carregar(projeto) != cfg or not atual_pr or atual_pr.get('number') != entrega.get('number')
                        or (atual_pr.get('head') or {}).get('sha') != sha
                        or (atual_pr.get('base') or {}).get('sha') != base
                        or relatorio.get('sha') != sha or relatorio.get('autor') != pacote['executor']
                        or revisao_execucao.git(trabalho, 'rev-parse', '--verify', 'HEAD^{commit}') != sha
                        or revisao_execucao.git(trabalho, 'branch', '--show-current') != branch
                        or revisao_execucao.git(trabalho, 'status', '--porcelain')
                        or cartao_atual['equipe'] != equipe or cartao_atual['status'] != cfg['kanban']['andamento']
                        or issue_atual.get('state') != 'open'):
                        raise ValueError('Entrega/política mudou durante a revisão')
                    if not controle.registrar_revisao(token, entrega.get('number'), relatorio, cfg):
                        controle.transicao(token, 'bloqueado')
                        controle.registrar_resultado(medicao,'revisao_reprovada');resultado_registrado=True
                        return {'token':token, 'codigo':codigo, 'estado':'bloqueado', 'revisao_aprovada':False}
                conferir_cartao(k,numero,projeto,cfg,equipe,pacote,cfg['kanban']['andamento'])
                k.mover(numero, cfg["kanban"]["revisao"])
                controle.transicao(token, "revisao")
                controle.registrar_resultado(medicao,'revisao_aprovada' if cfg['revisao']['ativo'] else 'revisao_desativada');resultado_registrado=True
            else:
                controle.transicao(token, "bloqueado")
                controle.registrar_resultado(medicao,'sem_entrega');resultado_registrado=True
        atual = next(x for x in controle.listar(chave) if x["token"] == token)
        return {"token": token, "codigo": codigo, "estado": atual["estado"]}
    except BaseException:
        atual = next((x for x in controle.listar(chave) if x["token"] == token), None)
        if atual and atual["estado"] in ("reservado", "executando"):
            controle.transicao(token, "bloqueado")
        if medicao and retorno_registrado and not resultado_registrado:
            # Falha na projeção não deve substituir a exceção original do gate.
            try:controle.registrar_resultado(medicao,'falha_console' if codigo else 'gate_bloqueado')
            except (ValueError,OSError,sqlite3.Error):pass
        raise


def preparar_retomada(projeto, numero, worktree, banco=None, kanban=None):
    """Prévia sem inferência; não recupera processo interrompido nem rouba trava."""
    cfg=carregar(projeto)
    if not cfg['ativo']:raise ValueError('Gestão não habilitada neste projeto')
    arq=Path(banco or pasta_dados(projeto)/'tarefas.db')
    with closing(sqlite3.connect(arq.resolve().as_uri()+'?mode=ro',uri=True,timeout=5)) as db:
        db.row_factory=sqlite3.Row
        linha=db.execute('SELECT * FROM reserva WHERE projeto=? AND cartao=?',
            (cfg['kanban']['repo'],str(numero))).fetchone()
        if not linha or linha['estado']!='bloqueado' or not linha['sessao']:
            raise ValueError('Retomada exige reserva bloqueada com sessão vinculada')
        reserva=dict(linha);pacote=json.loads(reserva['pacote']);reserva['pacote']=pacote
        tentativas=db.execute('SELECT * FROM execucao_tarefa WHERE token=? ORDER BY inicio,id',
            (reserva['token'],)).fetchall()
        if not tentativas or any(t['fim'] is None or type(t['codigo']) is not int for t in tentativas):
            raise ValueError('Tentativa sem retorno confirmado; concilie processos e sessões')
        ultima=tentativas[-1]
        atividade=db.execute('SELECT estado,codigo_console FROM atividade_execucao WHERE execucao=?',
            (ultima['id'],)).fetchone()
        if not atividade or atividade['estado']!='encerrado' or type(atividade['codigo_console']) is not int:
            raise ValueError('Processo principal sem encerramento registrado; concilie antes de retomar')
    ctx=pacote.get('contexto_execucao') or {}
    trabalho=validar_worktree(projeto,worktree);git=estado_git(trabalho)
    politica=hashlib.sha256(json.dumps(cfg,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    if (ctx.get('worktree')!=str(trabalho.resolve()) or ctx.get('branch')!=git['branch']
        or ctx.get('politica_sha256')!=politica or ctx.get('escopo') not in ('planejamento','implementacao','revisao','simples')):
        raise ValueError('Worktree/branch/política diverge da reserva; concilie antes de retomar')
    equipe=reserva['equipe'];escopo=ctx['escopo'];membro=pacote.get('funcionario');funcionario=(membro or {}).get('id')
    if funcionario:
        import funcionarios
        atual,rota=funcionarios.executor(projeto,funcionario,equipe,escopo)
        if atual!=membro:raise ValueError('Cadastro mudou desde a execução')
    else:rota=executor(cfg,equipe=equipe,escopo=escopo)
    if rota!=pacote['executor'] or rota.get('execucao','cloud')!='cloud' or rota['console']!=reserva['console']:
        raise ValueError('Retomada exige o mesmo executor cloud da reserva')
    provider,exe=selecionar(rota['console'])
    if not provider.capacidades.retomar:raise ValueError('Console sem retomada de sessão')
    for revisor in revisores(cfg,rota):selecionar(revisor['executor']['console'])
    k=kanban or Kanban(cfg,pasta_dados(projeto)/'kanban.json')
    issue=conferir_cartao(k,numero,projeto,cfg,equipe,pacote,cfg['kanban']['andamento'])
    conferir_dependencias(k,numero,issue.get('body') or '',pacote['dependencias'])
    from skills_execucao import conferir_worktree
    conferir_worktree(trabalho,pacote['skills_resolvidas'])
    if carregar(projeto)!=cfg:raise ValueError('Política mudou durante a prévia')
    evidencia={'reserva':reserva,'ultima_execucao':dict(ultima),'atividade':dict(atividade),'git':git}
    confirmacao=hashlib.sha256(json.dumps(evidencia,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    return {'confirmacao':confirmacao,'cartao':numero,'equipe':equipe,'console':rota['console'],
            'apenas_previa':True},(cfg,provider,exe,k,pacote),reserva


def retomar(projeto,numero,worktree,confirmacao,banco=None,kanban=None,rodar=executar,revisar=None,banco_execucoes=None,agentes_conciliados=False,ao_execucao=None):
    if agentes_conciliados is not True:
        raise ValueError('Confira agentes/ferramentas nativos antes de declarar --agentes-conciliados')
    if not isinstance(confirmacao,str) or not re.fullmatch('[0-9a-f]{64}',confirmacao):
        raise ValueError('Informe a confirmação da prévia de retomada')
    trabalho=validar_worktree(projeto,worktree)
    falha_previa=None
    with ocupar_worktree(banco_execucoes or banco_worktrees(trabalho),trabalho):
        try:
            previa,preparado,reserva=preparar_retomada(projeto,numero,trabalho,banco,kanban)
            if previa['confirmacao']!=confirmacao:raise ValueError('Prévia mudou; confira a retomada novamente')
        except (ValueError,OSError,sqlite3.Error,subprocess.SubprocessError) as exc:falha_previa=exc
        if falha_previa is None:
            pacote=reserva['pacote'];ctx=pacote['contexto_execucao']
            return _despachar(projeto,numero,reserva['equipe'],ctx['escopo'],trabalho,banco,rodar,revisar,
                (pacote.get('funcionario') or {}).get('id'),preparado,retomada=reserva,ao_execucao=ao_execucao)
    raise falha_previa


def main(argv=None):
    for fluxo in (sys.stdout,sys.stderr):
        if hasattr(fluxo,'reconfigure'):fluxo.reconfigure(encoding='utf-8')
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--projeto", required=True, type=Path)
    sub = p.add_subparsers(dest="acao", required=True)
    sub.add_parser("estado")
    retomada=sub.add_parser('retomar',help='prévia ou retomada explícita de sessão com retorno anterior confirmado')
    retomada.add_argument('--cartao',required=True,type=int)
    retomada.add_argument('--worktree',required=True,type=Path)
    retomada.add_argument('--confirmacao',help='hash exibido pela prévia atual')
    retomada.add_argument('--agentes-conciliados',action='store_true',help='declara conferência manual dos agentes/ferramentas da sessão anterior')
    retomada.add_argument('--executar',action='store_true')
    planejamento = sub.add_parser('planejar', help='diagnóstico do diretor: cartões preparáveis/bloqueados, sem execução')
    planejamento.add_argument('--max-cartoes', type=int, default=10, help='de 1 a 20 cartões do Backlog por consulta')
    planejamento.add_argument('--apos-cartao', type=int, default=0, help='continuar o diagnóstico após este número de issue')
    lote = sub.add_parser('lote', help='prepara ou executa um lote explícito em worktrees distintos')
    lote.add_argument("--plano", required=True, type=Path, help='JSON UTF-8 com cartoes e worktrees absolutos')
    lote.add_argument("--executar", action='store_true', help='sem a flag, somente valida e mostra o lote')
    coord = sub.add_parser('coordenar', help='CEO e diretor selecionam um lote pelo contrato comum')
    coord.add_argument('--plano',required=True,type=Path,help='candidatos JSON com cartões/worktrees autorizados')
    coord.add_argument('--solicitacao',required=True,type=Path,help='objetivo do usuário em UTF-8')
    coord.add_argument('--consultar',action='store_true',help='consulta CEO/diretor cloud, sem despacho')
    coord.add_argument('--executar',action='store_true',help='consulta CEO/diretor e executa seleção pelos gates comuns')
    r = sub.add_parser('revisar')
    r.add_argument("--worktree", required=True, type=Path)
    r.add_argument("--base", required=True)
    r.add_argument("--equipe", required=True)
    r.add_argument("--funcionario", help="ID do autor especialista, quando utilizado no despacho")
    r.add_argument("--aceite", required=True, type=Path, help='arquivo UTF-8 com o aceite do cartão')
    r.add_argument("--executar", action='store_true', help='executa os revisores; sem a flag apenas prepara')
    d = sub.add_parser("despachar")
    d.add_argument("--cartao", required=True, type=int)
    d.add_argument("--equipe", required=True)
    d.add_argument("--funcionario", help="ID do especialista cadastrado para executar o cartão")
    d.add_argument("--escopo", default="implementacao", choices=["planejamento", "implementacao", "revisao", "simples"])
    d.add_argument("--worktree", type=Path)
    d.add_argument("--executar", action="store_true", help="sem esta flag, apenas prepara e mostra o despacho")
    args = p.parse_args(argv)
    try:
        cfg = carregar(args.projeto)
        if args.acao == "estado":
            banco = pasta_dados(args.projeto) / "tarefas.db"
            resultado = {"politica": cfg, "tarefas": Controle(banco).listar(cfg["kanban"]["repo"]) if banco.exists() else []}
        elif args.acao=='retomar':
            resultado=retomar(args.projeto,args.cartao,args.worktree,args.confirmacao,agentes_conciliados=args.agentes_conciliados) if args.executar else preparar_retomada(args.projeto,args.cartao,args.worktree)[0]
        elif args.acao == 'planejar':
            resultado = planejar(args.projeto, args.max_cartoes, apos_cartao=args.apos_cartao)
        elif args.acao == 'coordenar':
            from coordenacao import coordenar
            with args.plano.open(encoding='utf-8-sig') as f: texto_plano=f.read(128001)
            with args.solicitacao.open(encoding='utf-8-sig') as f: solicitacao=f.read(16001)
            if len(texto_plano)>128000:raise ValueError('Plano maior que 128 mil caracteres')
            resultado=coordenar(args.projeto,json.loads(texto_plano),solicitacao,args.consultar,args.executar)
        elif args.acao == 'lote':
            if args.plano.stat().st_size>128000:
                raise ValueError('Plano de lote maior que 128 mil bytes')
            plano=json.loads(args.plano.read_text(encoding='utf-8-sig'))
            resultado=executar_lote(args.projeto,plano) if args.executar else preparar_lote(args.projeto,plano)
        elif args.acao == 'revisar':
            import revisao_execucao
            aceite = args.aceite.read_text(encoding='utf-8-sig')
            if args.executar:
                resultado = revisao_execucao.executar(args.projeto, args.worktree, args.base, args.equipe, aceite, funcionario=args.funcionario)
            else:
                resultado = revisao_execucao.preparar(args.projeto, args.worktree, args.base, args.equipe, aceite, funcionario=args.funcionario)[2]
        elif args.executar:
            if not args.worktree:
                raise ValueError("Informe --worktree para execução")
            resultado = despachar(args.projeto, args.cartao, args.equipe, args.escopo, args.worktree, funcionario=args.funcionario)
        else:
            resultado = preparar(args.projeto, args.cartao, args.equipe, args.escopo, funcionario=args.funcionario)[4]
        print(json.dumps(resultado, ensure_ascii=False, indent=2))
        if args.acao == 'revisar' and args.executar and not resultado['aprovado']:
            return 1
        if args.acao == 'lote' and args.executar and resultado['estado']!='processado':
            return 1
        if args.acao == 'coordenar' and (resultado.get('estado')=='bloqueado'
                                      or (args.executar and resultado.get('estado')!='processado')):
            return 1
        if args.acao in ('despachar','retomar') and args.executar and resultado['estado'] == 'bloqueado':
            return 1
        return 0
    except (ValueError, RuntimeError, OSError, sqlite3.Error, subprocess.SubprocessError) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
