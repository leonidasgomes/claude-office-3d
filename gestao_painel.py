"""Projeção pública de gestão: sem prompts, tokens de reserva ou caminhos locais."""
from contextlib import closing
from pathlib import Path
import json
import sqlite3
import math
import re
import time
import hashlib

from gestao_cli import pasta_dados
from gestao_projeto import carregar
from coordenacao_registro import resumo as coordenacoes
from coordenacao_painel import resumo as pedidos_coordenacao
from retomada_painel import resumo as pedidos_retomada


def lotes(projeto, repo, ident=None):
    """Projeção limitada de relatórios locais; estado registrado não prova processo vivo."""
    base=pasta_dados(projeto).resolve(); pasta=base/'lotes'
    saida={'itens':[],'problemas':0,'limitado':False}
    if ident is not None and (not isinstance(ident,str) or not re.fullmatch('[0-9a-f]{32}',ident)):
        saida['problemas']=1;return saida
    if pasta.is_symlink():
        saida['problemas']=1; return saida
    if not pasta.exists(): return saida
    if not pasta.is_dir() or not pasta.resolve().is_relative_to(base):
        saida['problemas']=1; return saida
    arquivos=[]
    for i,arq in enumerate([pasta/(ident+'.json')] if ident is not None else pasta.glob('*.json')):
        if i>=500:
            saida['limitado']=True; break
        try:
            if arq.is_symlink() or not arq.is_file():
                saida['problemas']+=1; continue
            arquivos.append((arq.stat().st_mtime,arq))
        except OSError: saida['problemas']+=1
    arquivos.sort(key=lambda item:item[0],reverse=True)
    consultados=0
    for _,arq in arquivos[:40]:
        consultados+=1
        try:
            if arq.stat().st_size>64000: raise ValueError('Relatório excede limite')
            with arq.open('rb') as fonte:
                conteudo=fonte.read(64001)
            if len(conteudo)>64000: raise ValueError('Relatório excede limite')
            dados=json.loads(conteudo.decode('utf-8'))
            ident=dados['id']; estado=dados['estado']; atualizado=dados['atualizado']
            cartoes=dados['cartoes']; resultados=dados['resultados']; atual=dados['cartao_em_execucao']
            paralelo='paralelismo' in dados or 'cartoes_em_execucao' in dados
            limite=dados.get('paralelismo',1); ativos=dados.get('cartoes_em_execucao',[])
            if paralelo and (type(limite) is not int or not 2<=limite<=4 or atual is not None
                or not isinstance(ativos,list) or len(ativos)>limite
                or any(type(n) is not int or n not in cartoes for n in ativos) or len(set(ativos))!=len(ativos)):
                raise ValueError('Paralelismo inválido')
            if (not isinstance(ident,str) or not re.fullmatch('[0-9a-f]{32}',ident) or ident!=arq.stem
                or dados['repo']!=repo or estado not in ('preparado','executando','processado','interrompido','incerto')
                or type(atualizado) not in (int,float) or not math.isfinite(atualizado) or atualizado<0
                or not isinstance(cartoes,list) or not 1<=len(cartoes)<=20
                or any(type(n) is not int or n<1 for n in cartoes) or len(set(cartoes))!=len(cartoes)
                or not isinstance(resultados,list) or len(resultados)>len(cartoes)
                or (atual is not None and (type(atual) is not int or atual not in cartoes))):
                raise ValueError('Relatório inválido')
            seguro=[]; vistos=set(); posicao=-1
            for i,r in enumerate(resultados):
                if (not isinstance(r,dict) or type(r.get('cartao')) is not int or r['cartao'] not in cartoes or r['cartao'] in vistos
                    or (not paralelo and r['cartao']!=cartoes[i])
                    or (paralelo and (cartoes.index(r['cartao'])<=posicao or r['cartao'] in ativos))
                    or r.get('estado') not in ('revisao','bloqueado') or type(r.get('codigo')) is not int):
                    raise ValueError('Resultado inválido')
                seguro.append({k:r[k] for k in ('cartao','estado','codigo')})
                vistos.add(r['cartao']); posicao=cartoes.index(r['cartao'])
            if estado=='processado' and (atual is not None or ativos or len(seguro)!=len(cartoes)
                or any(r['estado']!='revisao' or r['codigo'] for r in seguro)):
                raise ValueError('Lote processado inconsistente')
            saida['itens'].append({'id':ident,'estado':estado,'atualizado':atualizado,'cartoes':cartoes,
                                  'resultados':seguro,'cartao_em_execucao':atual,
                                  **({'paralelismo':limite,'cartoes_em_execucao':ativos} if paralelo else {})})
            if len(saida['itens'])>=10: break
        except (ValueError,OSError,TypeError,KeyError,OverflowError):
            saida['problemas']+=1
    saida['limitado']=saida['limitado'] or len(arquivos)>consultados
    return saida


def desempenho(db, repo, agora=None):
    agora=time.time() if agora is None else agora
    saida={'dias':7,'desde':agora-7*86400,'grupos':[],'limitado':False,
           'historico_sem_vinculo':False,'por_cartao':{}}
    if db is None or not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='execucao_tarefa'").fetchone():
        return saida
    contexto=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='execucao_contexto'").fetchone()
    resultados=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='execucao_resultado'").fetchone()
    juntar='FROM execucao_tarefa e LEFT JOIN reserva r ON e.token=r.token '
    if contexto:
        juntar+='LEFT JOIN execucao_contexto h ON h.token=e.token '
    if resultados:juntar+='LEFT JOIN execucao_resultado a ON a.execucao=e.id '
    cartao='COALESCE(h.cartao,r.cartao)' if contexto else 'r.cartao'
    projeto='(h.projeto=? OR r.projeto=?)' if contexto else 'r.projeto=?'
    extras=',h.projeto,r.projeto,h.cartao,r.cartao' if contexto else ''
    extras+=',a.equipe,a.tipo,a.resultado,a.atualizado' if resultados else ',NULL,NULL,NULL,NULL'
    parametros=(repo,repo) if contexto else (repo,)
    colunas=('cartao','console','modelo','origem_modelo','execucao','inicio','fim','duracao_seg','codigo')
    linhas=db.execute('SELECT '+cartao+',e.console,e.modelo,e.origem_modelo,e.execucao,e.inicio,e.fim,e.duracao_seg,e.codigo,'
        'r.token IS NOT NULL'+extras+',e.id '+juntar+'WHERE '+projeto+' AND e.inicio>=? AND e.inicio<=? '
        'ORDER BY e.inicio DESC,e.id DESC LIMIT 1001',(*parametros,saida['desde'],agora)).fetchall()
    sem_vinculo='r.token IS NULL AND h.token IS NULL' if contexto else 'r.token IS NULL'
    saida['historico_sem_vinculo']=bool(db.execute('SELECT 1 '+juntar+'WHERE '+sem_vinculo+
        ' AND e.inicio>=? AND e.inicio<=? LIMIT 1',(saida['desde'],agora)).fetchone())
    saida['limitado']=len(linhas)>1000; grupos={}
    for linha in linhas[:1000]:
        if contexto and linha[10] is not None and linha[11] is not None and (
                linha[10]!=linha[11] or linha[12]!=linha[13]):
            raise ValueError('Contexto de execução diverge da reserva')
        item=dict(zip(colunas,linha)); cartao=str(item.pop('cartao'));item['_tentativa']=linha[-1]
        equipe,tipo,resultado,atualizado=linha[-5:-1]
        tipos_resultado=('falha_console','sem_entrega','revisao_aprovada','revisao_desativada','revisao_reprovada','gate_bloqueado')
        if equipe is not None:
            if (not isinstance(equipe,str) or not equipe.strip() or len(equipe)>200
                or tipo not in ('despacho','retomada') or resultado not in (*tipos_resultado,None)
                or type(atualizado) not in (int,float) or not math.isfinite(atualizado)
                or type(item['inicio']) not in (int,float) or not math.isfinite(item['inicio']) or atualizado<item['inicio']
                or (item['fim'] is not None and (type(item['fim']) not in (int,float)
                    or not math.isfinite(item['fim']) or item['fim']<item['inicio']))
                or (resultado is not None and (item['fim'] is None or atualizado<item['fim']
                    or (item['codigo']!=0)!=(resultado=='falha_console')))):
                raise ValueError('Resultado de tentativa inconsistente')
        elif any(v is not None for v in (tipo,resultado,atualizado)):
            raise ValueError('Resultado sem atribuição')
        item.update(equipe=equipe or 'não informado',tipo=tipo,resultado=resultado)
        duracao=item['duracao_seg']
        inicio,fim,codigo=item['inicio'],item['fim'],item['codigo']
        if (type(inicio) not in (int,float) or not math.isfinite(inicio) or inicio<0
            or (fim is not None and (type(fim) not in (int,float) or not math.isfinite(fim) or fim<inicio))
            or (codigo is not None and type(codigo) is not int)
            or (fim is None and (codigo is not None or duracao is not None))
            or (fim is not None and (codigo is None or duracao is None))):
            raise ValueError('Retorno inconsistente no estado de gestão')
        if duracao is not None and (type(duracao) not in (int,float) or not math.isfinite(duracao) or duracao<0):
            raise ValueError('Intervalo inválido no estado de gestão')
        # O histórico entra no agregado, mas nunca vira atividade da reserva nova.
        if linha[9]: saida['por_cartao'].setdefault(cartao,item)
        chave=tuple(item[k] for k in ('equipe','console','modelo','origem_modelo','execucao'))
        g=grupos.setdefault(chave,dict(zip(('equipe','console','modelo','origem_modelo','execucao'),chave),
            tentativas=0,com_intervalo=0,sem_retorno=0,saida_zero=0,saida_nao_zero=0,soma_seg=0,_tentativas=[],
            despachos=0,retomadas=0,tipo_nao_informado=0,sem_resultado=0,resultados=dict.fromkeys(tipos_resultado,0)))
        g['_tentativas'].append(linha[-1])
        g['tentativas']+=1
        g['despachos' if tipo=='despacho' else 'retomadas' if tipo=='retomada' else 'tipo_nao_informado']+=1
        if resultado is None:g['sem_resultado']+=1
        else:g['resultados'][resultado]+=1
        if item['fim'] is None: g['sem_retorno']+=1
        if item['codigo']==0: g['saida_zero']+=1
        elif item['codigo'] is not None: g['saida_nao_zero']+=1
        if duracao is not None:
            g['com_intervalo']+=1; g['soma_seg']+=duracao
    for chave,g in sorted(grupos.items()):
        g['media_seg']=round(g['soma_seg']/g['com_intervalo'],3) if g['com_intervalo'] else None
        g['soma_seg']=round(g['soma_seg'],3) if g['com_intervalo'] else None; saida['grupos'].append(g)
    return saida


def saude_tarefas(db, repo):
    """Estado registrado por reserva atual, sem inferir vida de processo por idade.

    Ao contrário das métricas semanais, inclui pendências antigas. Nunca libera
    reservas, conclui cartões ou chama consoles. Não expõe tokens/pacotes/sessões.
    """
    saida={'consultadas':0,'limitado':False,'pendencias':[],'atividades':{},
           'contagens':dict.fromkeys(('bloqueada','sem_retorno','falha','sem_medicao'),0)}
    if db is None: return saida
    tem_medicao=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='execucao_tarefa'").fetchone()
    tem_atividade=tem_medicao and db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='atividade_execucao'").fetchone()
    tem_eventos=tem_atividade and db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='atividade_eventos'").fetchone()
    medicao=',e.inicio,e.fim,e.codigo,e.id' if tem_medicao else ',NULL,NULL,NULL,NULL'
    juntar=(' LEFT JOIN execucao_tarefa e ON e.id=(SELECT x.id FROM execucao_tarefa x '
            'WHERE x.token=r.token ORDER BY x.inicio DESC,x.id DESC LIMIT 1)') if tem_medicao else ''
    atividade=',a.ultimo_sinal,a.estado,a.pid_console,a.codigo_console' if tem_atividade else ',NULL,NULL,NULL,NULL'
    if tem_atividade:juntar+=' LEFT JOIN atividade_execucao a ON a.execucao=e.id'
    eventos=',v.ultimo_evento,v.total,v.ultimo_tipo,v.eventos_filhos' if tem_eventos else ',NULL,NULL,NULL,NULL'
    if tem_eventos:juntar+=' LEFT JOIN atividade_eventos v ON v.execucao=e.id'
    linhas=db.execute('SELECT r.cartao,r.equipe,r.console,r.estado,r.atualizado,r.token'+medicao+atividade+eventos+
        ' FROM reserva r'+juntar+' WHERE r.projeto=? ORDER BY r.atualizado DESC,r.cartao LIMIT 201',(repo,)).fetchall()
    saida['limitado']=len(linhas)>200
    for valores in linhas[:200]:
        cartao,equipe,console,estado,atualizado,token,inicio,fim,codigo,tentativa,sinal,estado_atividade,pid_console,codigo_console,ultimo_evento,total_eventos,ultimo_tipo,eventos_filhos=tuple(valores)
        if estado not in ('reservado','executando','bloqueado','revisao','concluido','cancelado'):
            raise ValueError('Estado de tarefa inválido')
        for valor in (atualizado,inicio,fim):
            if valor is not None and (type(valor) not in (int,float) or not math.isfinite(valor) or valor<0):
                raise ValueError('Data de tarefa inválida')
        if (codigo is not None and type(codigo) is not int) or (inicio is None and (fim is not None or codigo is not None)):
            raise ValueError('Medição inconsistente')
        if inicio is not None and ((fim is None)!=(codigo is None) or (fim is not None and fim<inicio)):
            raise ValueError('Retorno de tarefa inconsistente')
        observada=None
        if sinal is not None:
            if (type(sinal) not in (int,float) or not math.isfinite(sinal) or sinal<0
                or estado_atividade not in ('acompanhando','encerrado','interrompido')
                or (pid_console is not None and (type(pid_console) is not int or pid_console<=0))
                or (codigo_console is not None and type(codigo_console) is not int)):
                raise ValueError('Sinal de atividade inválido')
            observada={'ultimo_sinal':sinal,'estado':estado_atividade,
                       'console_observado':pid_console is not None,'codigo_console':codigo_console}
            saida['atividades'][str(cartao)]=observada
        if ultimo_evento is not None:
            from emit_evento import TIPOS
            if (observada is None or type(ultimo_evento) not in (int,float)
                or not math.isfinite(ultimo_evento) or ultimo_evento<0
                or ultimo_tipo not in TIPOS or type(total_eventos) is not int
                or not 1<=total_eventos<=2**53-1 or type(eventos_filhos) is not int
                or not 0<=eventos_filhos<=total_eventos):
                raise ValueError('Eventos de atividade inválidos')
            observada['eventos']={'ultimo_evento':ultimo_evento,'total':total_eventos,
                                 'ultimo_tipo':ultimo_tipo,'eventos_filhos':eventos_filhos}
        sinais=[]
        # Uma reserva cancelada não prova que o processo iniciado terminou.
        if inicio is not None and fim is None: sinais.append('sem_retorno')
        if estado=='bloqueado': sinais.append('bloqueada')
        if estado not in ('cancelado','concluido') and codigo is not None and codigo!=0: sinais.append('falha')
        if estado=='executando' and inicio is None: sinais.append('sem_medicao')
        saida['consultadas']+=1
        for sinal in sinais: saida['contagens'][sinal]+=1
        if sinais: saida['pendencias'].append({'cartao':cartao,'equipe':equipe,'console':console,
            'estado':estado,'atualizado':atualizado,'inicio':inicio,'fim':fim,'codigo':codigo,'sinais':sinais,
            'registro':hashlib.sha256(json.dumps([token,tentativa],ensure_ascii=False).encode()).hexdigest()[:32]})
        if sinais and observada:saida['pendencias'][-1]['atividade']=observada
    return saida


def consumo_desempenho(metricas,arquivo,raiz):
    """Só vínculos gravados no despacho; IDs internos são retirados mesmo em erro."""
    from consumo_providers import Registro,identidade_projeto
    ids=[t for g in metricas['grupos'] for t in g.get('_tentativas',[])]
    por_tentativa={};erro=None
    try:
        if ids:por_tentativa=Registro(arquivo).resumos_tentativas(ids,identidade_projeto(raiz))
    except (ValueError,OSError,sqlite3.Error,TypeError):erro='Consumo das tentativas indisponível'
    for item in metricas['por_cartao'].values():
        ident=item.pop('_tentativa',None);item['consumo']=por_tentativa.get(ident)
    for g in metricas['grupos']:
        tentativas=g.pop('_tentativas',[])
        g['tentativas_com_consumo']=sum(t in por_tentativa for t in tentativas)
        # Cada tentativa mantém seus próprios modelos observados, sem transformar
        # modelo configurado do despacho em identidade nativa comprovada.
        grupos=[x for t in tentativas for x in por_tentativa.get(t,{}).get('grupos',[])]
        g['consumo_observado']={'amostras':sum(x['amostras'] for x in grupos)}
        for campo,cobertura in (('entrada','com_entrada'),('saida','com_saida'),('total','com_total')):
            presentes=[x for x in grupos if x[cobertura]>0 and x[campo] is not None]
            g['consumo_observado'][campo]=sum(x[campo] for x in presentes) if presentes else None
            g['consumo_observado'][cobertura]=sum(x[cobertura] for x in presentes)
        from decimal import Decimal
        precos=[x for x in grupos if x.get('com_preco',0)>0 and x.get('equivalente_api_usd') is not None]
        g['consumo_observado']['com_preco']=sum(x['com_preco'] for x in precos)
        g['consumo_observado']['equivalente_api_usd']=format(sum((Decimal(x['equivalente_api_usd']) for x in precos),Decimal(0)),'f') if precos else None
    if erro:metricas['consumo_erro']=erro


def saude_projeto(projeto, repo):
    """Leitura pequena reutilizada pelo detector, sem catálogo de skills/modelos."""
    banco=pasta_dados(projeto)/'tarefas.db'
    if banco.is_symlink(): raise ValueError('Banco de tarefas por link não aceito')
    if not banco.exists(): return saude_tarefas(None,repo)
    if not banco.is_file(): raise ValueError('Banco de tarefas inválido')
    with closing(sqlite3.connect(banco.resolve().as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
        return saude_tarefas(db,repo)


def resumo(projetos,banco_consumo=None):
    if banco_consumo is None:
        import banco
        banco_consumo=banco.ARQ.parent/'consumo_providers.db'
    saida = []
    for projeto in projetos:
        raiz = Path(projeto)
        try:
            from politica_painel import snapshot
            cfg, politica_versao, _ = snapshot(raiz)
            import funcionarios
            from fontes_documentais import resumo as resumo_fontes
            from consumo_providers import Registro,identidade_projeto
            try:
                consumo=funcionarios.rotular_consumo([raiz],Registro(banco_consumo).resumo(projeto_hash=identidade_projeto(raiz)))
            except (OSError,sqlite3.Error,ValueError,TypeError):
                consumo={'escopo':'projeto','grupos':[],'erro':'Histórico de consumo deste projeto indisponível'}
            tarefas = []
            saude=saude_tarefas(None,cfg["kanban"]["repo"])
            metricas=desempenho(None,cfg["kanban"]["repo"])
            banco = pasta_dados(raiz) / "tarefas.db"
            if banco.is_file():
                with closing(sqlite3.connect(banco.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)) as db:
                    db.row_factory = sqlite3.Row
                    tem_revisao = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='entrega'").fetchone()
                    revisao = ',e.sha revisao_sha,e.pr revisao_pr,e.aprovado revisao_aprovada' if tem_revisao else ''
                    juntar = ' LEFT JOIN entrega e ON e.token=r.token' if tem_revisao else ''
                    tarefas = [dict(x) for x in db.execute(
                        'SELECT r.cartao,r.equipe,r.console,r.estado,r.atualizado,r.sessao,r.pacote'+revisao+
                        ' FROM reserva r'+juntar+' WHERE r.projeto=? ORDER BY r.atualizado DESC LIMIT 200',
                        (cfg["kanban"]["repo"],))]
                    metricas=desempenho(db,cfg["kanban"]["repo"])
                    saude=saude_tarefas(db,cfg["kanban"]["repo"])
                    for tarefa in tarefas:
                        tarefa['atividade']=saude['atividades'].get(str(tarefa['cartao']))
                        tarefa["ultima_execucao"]=metricas["por_cartao"].get(tarefa["cartao"])
                        membro=json.loads(tarefa.pop('pacote')).get('funcionario')
                        if membro:
                            tarefa['funcionario_id']=membro['id']
                            tarefa['funcionario_nome']=membro['nome']
            consumo_desempenho(metricas,banco_consumo,raiz)
            metricas.pop("por_cartao")
            from agentes_nativos import resumo as resumo_perfil
            membros=[{**f,'perfil_nativo':resumo_perfil(raiz,f['id'])} for f in funcionarios.listar(raiz)]
            saida.append({"nome": raiz.name, "id": funcionarios.id_projeto(raiz),
                          "funcionarios":membros, "skills":funcionarios.skills(raiz,cfg),
                          "ativo": cfg["ativo"], "politica_versao":politica_versao, "ceo": cfg["ceo"],
                          "diretor": cfg["diretor"], "equipes": cfg["equipes"],
                          "merge": cfg["merge"]["modo"], "local": cfg["local"],
                          "merge_config":cfg["merge"],
                          "documentacao":resumo_fontes(raiz,cfg),
                          "consumo":consumo,
                          "repo": cfg["kanban"]["repo"], "tarefas": tarefas, "lotes":lotes(raiz,cfg["kanban"]["repo"]),
                          "coordenacoes":coordenacoes(raiz,cfg['kanban']['repo']),
                          "pedidos_coordenacao":pedidos_coordenacao(raiz,cfg['kanban']['repo']),
                          "pedidos_retomada":pedidos_retomada(raiz,cfg['kanban']['repo']),
                          "saude_tarefas":saude, "desempenho":metricas})
        except (ValueError, OSError, sqlite3.Error, TypeError, KeyError):
            saida.append({"nome": raiz.name, "ativo": False, "erro": "Política ou estado de gestão inválido; confira no PC"})
    return {"projetos": saida}
