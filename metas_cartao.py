"""Metas por tentativa: Kanban e GDD canônicos, limites observados no host."""
from contextlib import contextmanager, closing
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import sqlite3
import subprocess
import threading
import time


def planejamento_registrado(projeto,cartao,issue,pacote):
    """Exceção de classificação só para subtarefa criada e registrada pelo host."""
    from gestao_cli import pasta_dados,campo
    corpo=issue.get('body') or ''
    marca=re.search(r'<!-- office-desbloqueio:([1-9][0-9]*) -->',corpo)
    if not marca or campo(corpo,'Objetivo GDD')!='classificação a confirmar':return None
    pai=int(marca[1]);pasta=pasta_dados(projeto)/'desbloqueios';arquivo=pasta/(str(pai)+'.json')
    if not arquivo.is_file() or arquivo.is_symlink() or not arquivo.resolve().is_relative_to(pasta.resolve()):return None
    r=json.loads(arquivo.read_text(encoding='utf-8'));s=r.get('proposta') or {}
    if (r.get('estado')!='criado' or r.get('pai')!=pai or r.get('numero')!=cartao['numero']
        or pacote['cartao']!=cartao['numero'] or s.get('equipe')!=cartao['equipe']
        or s.get('titulo')!=issue.get('title') or s.get('objetivo')!=pacote['objetivo']
        or s.get('aceite')!=pacote['aceite'] or s.get('skills')!=pacote.get('skills')
        or pacote['escopo']!='Planejamento/investigação deste bloqueio; não implementar o pai.'):
        return None
    return {'pai':pai,'recibo_sha256':hashlib.sha256(arquivo.read_bytes()).hexdigest()}


def construir(projeto,cfg,cartao,issue,pacote):
    if not cfg['metas']['ativo']:return None
    from ciclo_gdd import documentos,objetivos,objetivo_cartao
    from gestao_cli import campo
    doc=documentos(Path(projeto).resolve(),cfg)[0]
    texto=doc['conteudo'];numero=objetivo_cartao(cartao,objetivos(texto),texto)
    explicito=campo(issue.get('body') or '', 'Objetivo GDD')
    secoes=list(re.finditer(r'^#### Objetivo ([1-9][0-9]*)[^\n]*\n(.*?)(?=^#### |^### |\Z)',texto,re.M|re.S))
    planejamento=planejamento_registrado(projeto,cartao,issue,pacote) if explicito=='classificação a confirmar' else None
    if planejamento:
        if numero is not None:raise ValueError('Meta: cartão já classificado no GDD; confira o planejamento')
        if not secoes:raise ValueError('Meta: fonte GDD sem objetivos para classificar')
        gdd={'numero':None,'titulo':'Planejamento do vínculo com o GDD','caminho':doc['caminho'],
             'sha256':doc['sha256'],'trecho':'\n'.join(m[0] for m in secoes),**planejamento}
    elif explicito:
        correspondencias=[int(m[1]) for m in secoes if explicito in (m[1],m[0].splitlines()[0].removeprefix('#### '))
                          or re.fullmatch(r'Objetivo '+m[1],explicito,re.I)]
        if len(correspondencias)!=1:raise ValueError('Meta: Objetivo GDD deve identificar uma seção existente')
        if numero is not None and numero!=correspondencias[0]:raise ValueError('Meta: vínculo GDD divergente do cartão')
        numero=correspondencias[0]
    if not planejamento:
        secao=next((m for m in secoes if int(m[1])==numero),None)
        if secao is None:raise ValueError('Meta: vincule o cartão a um Objetivo GDD antes de despachar')
        gdd={'numero':numero,'titulo':secao[0].splitlines()[0].removeprefix('#### '),
             'caminho':doc['caminho'],'sha256':doc['sha256'],'trecho':secao[0]}
    bruto=json.dumps({'title':issue.get('title'),'body':issue.get('body') or ''},sort_keys=True,ensure_ascii=False).encode()
    return {'cartao':pacote['cartao'],'repo':cfg['kanban']['repo'],'url':pacote['url'],
            'equipe':cartao['equipe'],'objetivo':pacote['objetivo'],'aceite':pacote['aceite'],'escopo':pacote['escopo'],
            'dependencias':{k:v for k,v in pacote['dependencias'].items() if k!='verificadas_em'},
            'issue_sha256':hashlib.sha256(bruto).hexdigest(),
            'gdd':gdd,
            'limites':{'tempo_min':cfg['metas']['tempo_min'],'tokens':cfg['metas']['tokens']}}


def tokens_observados(arquivo,projeto,tentativa):
    """Leitura exata do ledger por tentativa; cache já está incluído na entrada."""
    from consumo_providers import identidade_projeto
    p=Path(arquivo)
    if not p.is_file():return None,'sem_amostras'
    try:
        with closing(sqlite3.connect(p.resolve().as_uri()+'?mode=ro',uri=True,timeout=1)) as db:
            if any(not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(t,)).fetchone()
                   for t in ('consumo','consumo_tentativa')):return None,'sem_amostras'
            r=db.execute('SELECT SUM(c.total),COUNT(*),COUNT(c.total) FROM consumo c '
                         'JOIN consumo_tentativa v ON v.chave=c.chave '
                         'WHERE v.projeto=? AND c.projeto=v.projeto AND v.tentativa=?',
                         (identidade_projeto(projeto),tentativa)).fetchone()
            if not r[1]:return None,'sem_amostras'
            return r[0],('observado' if r[1]==r[2] else 'parcial')
    except (OSError,sqlite3.Error):return None,'indisponivel'


def saldo_retomada(projeto,pasta,banco,token,meta,consumo):
    """Histórico persistido, sem inferência ou renovação do limite por cartão."""
    with closing(sqlite3.connect(Path(banco).resolve().as_uri()+'?mode=ro',uri=True)) as db:
        db.row_factory=sqlite3.Row
        rows=db.execute('SELECT id,fim,codigo,duracao_seg FROM execucao_tarefa WHERE token=? '
                        'ORDER BY inicio,id LIMIT 1001',(token,)).fetchall()
    if not rows or len(rows)>1000:raise ValueError('Histórico de meta incompleto; concilie antes de retomar')
    tempos={};total_tokens=0
    for r in rows:
        ident=r['id'];duracao=r['duracao_seg']
        if (not re.fullmatch('[0-9a-f]{32}',ident) or r['fim'] is None or type(r['codigo']) is not int
            or type(duracao) not in (int,float) or not math.isfinite(duracao) or duracao<0):
            raise ValueError('Tentativa de meta sem retorno/tempo confirmado')
        arq=Path(pasta)/'metas'/(ident+'.json')
        if not arq.is_file() or arq.is_symlink() or arq.stat().st_size>128000:
            raise ValueError('Evidência de meta ausente; não renovar orçamento')
        registro=json.loads(arq.read_text(encoding='utf-8'))
        if not isinstance(registro,dict):raise ValueError('Registro de meta inválido')
        tempo=registro.get('tempo_seg');anteriores=registro.get('tentativas_anteriores',[])
        if (registro.get('tentativa')!=ident or registro.get('meta')!=meta or registro.get('fim') is None
            or type(tempo) not in (int,float) or not math.isfinite(tempo) or tempo<0
            or not isinstance(anteriores,list) or any(not isinstance(i,str) for i in anteriores)
            or len(set(anteriores))!=len(anteriores)
            or any(i not in tempos for i in anteriores)):
            raise ValueError('Histórico de tempo/meta divergente; não renovar orçamento')
        # Correções registram tempo acumulado: descontar os antecedentes evita
        # cobrar a mesma tentativa duas vezes. Retomadas antigas sem vínculo
        # conservam seus próprios gastos; não apagam tentativas anteriores.
        delta=tempo-sum(tempos[i] for i in anteriores)
        if delta<-.001:raise ValueError('Tempo acumulado regrediu; concilie a meta')
        tempos[ident]=max(duracao,delta,0)
        tokens,estado=tokens_observados(consumo,projeto,ident)
        if estado!='observado' or type(tokens) is not int or tokens<0:
            raise ValueError('Consumo anterior incompleto; não renovar orçamento')
        total_tokens+=tokens
    usados=sum(tempos.values());limites=meta['limites']
    if usados>=60*limites['tempo_min'] or total_tokens>=limites['tokens']:
        raise ValueError('Meta do cartão esgotada; retomada não renova tempo ou tokens')
    return {'tentativas':list(tempos),'tempo_consumido_seg':usados,'tokens_consumidos':total_tokens,
            'tempo_restante_seg':60*limites['tempo_min']-usados,'tokens_restantes':limites['tokens']-total_tokens}


def antecedentes_retomada(saldo,meta):
    agora=time.time();inicio=agora-saldo['tempo_consumido_seg']
    return {'tentativas':saldo['tentativas'],'inicio_monotonic':time.monotonic()-saldo['tempo_consumido_seg'],
            'inicio':inicio,'limite':inicio+60*meta['limites']['tempo_min']}


def encerrar_arvore(processo):
    if processo.poll() is not None:return
    if os.name=='nt':
        r=subprocess.run(['taskkill','/PID',str(processo.pid),'/T','/F'],capture_output=True,timeout=10)
        if r.returncode and processo.poll() is None:raise ValueError('Encerramento da árvore não confirmado')
    else:
        os.killpg(processo.pid,signal.SIGTERM)
        try:processo.wait(timeout=5)
        except subprocess.TimeoutExpired:pass
        try:os.killpg(processo.pid,signal.SIGKILL)
        except ProcessLookupError:pass


class Execucao:
    def __init__(self,projeto,pasta,tentativa,meta,consumo,relogio=time.monotonic,leitor=tokens_observados,encerrar=encerrar_arvore,antecedentes=None):
        if not re.fullmatch('[0-9a-f]{32}',tentativa):raise ValueError('Tentativa de meta inválida')
        self.projeto=Path(projeto);self.arquivo=Path(pasta)/'metas'/(tentativa+'.json')
        self.consumo=consumo;self.relogio=relogio;self.leitor=leitor;self.encerrar=encerrar
        self.inicio=relogio();self.fim_execucao=None;self.trava=threading.RLock();self.motivo=None
        agora=time.time()
        self.registro={'tentativa':tentativa,'meta':meta,'estado':'executando','inicio':agora,
                       'limite':agora+60*meta['limites']['tempo_min'],'atualizado':agora,
                       'tokens_observados':None,'medicao':'sem_amostras','motivo':''}
        self.anteriores=[]
        if antecedentes is not None:
            ids=antecedentes.get('tentativas',[])
            inicio=antecedentes.get('inicio_monotonic')
            if (not isinstance(ids,list) or not 1<=len(ids)<=1000 or len(set(ids))!=len(ids)
                or any(not isinstance(i,str) or not re.fullmatch('[0-9a-f]{32}',i) or i==tentativa for i in ids)
                or type(inicio) not in (int,float) or not math.isfinite(inicio) or inicio>self.inicio
                or antecedentes.get('limite')!=antecedentes.get('inicio',0)+60*meta['limites']['tempo_min']):
                raise ValueError('Histórico de orçamento inválido')
            self.anteriores=ids[:];self.inicio=inicio
            self.registro.update(inicio=antecedentes['inicio'],limite=antecedentes['limite'],tentativas_anteriores=ids[:])
        self.arquivo.parent.mkdir(parents=True,exist_ok=True)
        if self.arquivo.exists():raise ValueError('Meta existente: não retomar automaticamente')
        self.salvar()

    def salvar(self):
        from controlador_local import atomico
        self.registro['atualizado']=time.time();atomico(self.arquivo,self.registro)

    def conferir(self):
        with self.trava:
            amostras=[self.leitor(self.consumo,self.projeto,i) for i in self.anteriores+[self.registro['tentativa']]]
            total=sum(t for t,e in amostras) if all(t is not None for t,e in amostras) else None
            estado='observado' if all(e=='observado' for t,e in amostras) else (amostras[-1][1] if len(amostras)==1 else 'parcial')
            self.registro.update(tokens_observados=total,medicao=estado)
            if self.motivo is None:
                if (self.relogio() if self.fim_execucao is None else self.fim_execucao)-self.inicio>=60*self.registro['meta']['limites']['tempo_min']:self.motivo='limite_tempo'
                elif total is not None and total>=self.registro['meta']['limites']['tokens']:self.motivo='limite_tokens'
            if self.motivo:self.registro.update(estado=self.motivo,motivo=self.motivo)
            self.salvar()
            return self.motivo

    def encerrar_medicao(self):
        with self.trava:
            if self.fim_execucao is None:self.fim_execucao=self.relogio()
            self.registro['tempo_seg']=max(0,self.fim_execucao-self.inicio)
            return self.conferir()

    @contextmanager
    def vigiar(self,processo,intervalo=1):
        parar=threading.Event();falhas=[]
        def monitor():
            while not parar.wait(intervalo):
                try:
                    motivo=self.conferir()
                    if motivo:
                        self.encerrar(processo);return
                    if processo.poll() is not None:return
                except BaseException as exc:
                    falhas.append(exc)
                    try:self.encerrar(processo)
                    except BaseException as erro:falhas.append(erro)
                    return
        thread=threading.Thread(target=monitor,daemon=True);thread.start()
        try:yield
        finally:
            parar.set();thread.join(timeout=17)
            if thread.is_alive() or falhas:raise ValueError('Monitor de meta indisponível; concilie a tentativa')
            self.encerrar_medicao()

    def orcamento_correcao(self):
        """Somente continuação em memória, sem renovar o orçamento do cartão."""
        self.conferir()
        if (self.motivo or self.registro['medicao']!='observado'
            or self.registro['tokens_observados'] is None
            or self.registro['tokens_observados']+1000>=self.registro['meta']['limites']['tokens']
            or self.relogio()-self.inicio+5>=60*self.registro['meta']['limites']['tempo_min']
            or len(self.anteriores)>=2):return None
        return {'tentativas':self.anteriores+[self.registro['tentativa']],
                'inicio_monotonic':self.inicio,'inicio':self.registro['inicio'],'limite':self.registro['limite']}

    def finalizar(self,estado,motivo='',pr=None):
        with self.trava:
            self.conferir()
            self.registro.update(estado=estado if estado=='incerto' else self.motivo or estado,
                                 motivo=motivo or self.motivo or '',fim=time.time(),pr=pr)
            self.salvar()


def resumo(pasta):
    itens=[];problemas=False
    arquivos=sorted((Path(pasta)/'metas').glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True)
    for p in arquivos[:200]:
        try:
            r=json.loads(p.read_text(encoding='utf-8'));m=r['meta']
            banco=Path(pasta)/'tarefas.db'
            if r['estado']=='em_revisao' and banco.is_file():
                with closing(sqlite3.connect(banco.resolve().as_uri()+'?mode=ro',uri=True,timeout=1)) as db:
                    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='execucao_tarefa'").fetchone():
                        if db.execute("SELECT 1 FROM execucao_tarefa e JOIN reserva r ON r.token=e.token "
                                      "WHERE e.id=? AND r.projeto=? AND r.cartao=? AND r.estado='concluido'",
                                      (r['tentativa'],m['repo'],str(m['cartao']))).fetchone():r['estado']='entregue'
            itens.append({**{k:r.get(k) for k in ('estado','inicio','limite','fim','atualizado','tokens_observados','medicao','motivo','pr')},
                          'cartao':m['cartao'],'equipe':m['equipe'],'objetivo':m['objetivo'],
                          'objetivo_gdd':m['gdd']['titulo'],'limites':m['limites']})
        except (OSError,ValueError,KeyError,TypeError,sqlite3.Error):problemas=True
    return {'itens':itens,'problemas':problemas,'limitado':len(arquivos)>200}
