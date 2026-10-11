"""Sinais do controlador e do processo lançado; não observa descendentes cloud."""
from contextlib import closing
import os
import sqlite3
import threading
import time
import uuid


class Acompanhamento:
    def __init__(self,banco,execucao,intervalo=15):
        if not 0<intervalo<=60: raise ValueError('Intervalo inválido')
        self.banco=banco;self.execucao=execucao;self.intervalo=intervalo
        self.dono=uuid.uuid4().hex;self.processo=None
        self.parar=threading.Event();self.lock=threading.Lock();self.erro=None
        self.persistencia=threading.Lock()
        self.thread=None
        self.total_eventos=0;self.eventos_filhos=0;self.ultimo_evento=None;self.ultimo_tipo=None
        self.operacoes={}

    def vincular(self,processo):
        if type(processo.pid) is not int or processo.pid<=0 or not callable(processo.poll):
            raise ValueError('Processo lançado inválido')
        with self.lock:
            if self.processo is not None and self.processo is not processo:
                raise ValueError('Acompanhamento já vinculado a outro processo')
            self.processo=processo
        self.registrar('acompanhando')

    def registrar(self,estado):
        with self.persistencia:self._registrar(estado)

    def _registrar(self,estado):
        with self.lock:
            processo=self.processo
            pid=processo.pid if processo else None
            codigo=processo.poll() if processo else None
            evento=(self.ultimo_evento,self.total_eventos,self.ultimo_tipo,self.eventos_filhos)
            operacoes={k:dict(v) for k,v in self.operacoes.items()}
        with closing(sqlite3.connect(self.banco,timeout=2)) as db,db:
            cursor=db.execute('UPDATE atividade_execucao SET pid_console=?,ultimo_sinal=?,estado=?,codigo_console=? '
                'WHERE execucao=? AND controlador=?',(pid,time.time(),estado,codigo,self.execucao,self.dono))
            if cursor.rowcount!=1: raise ValueError('Acompanhamento perdeu vínculo')
            if evento[0] is not None:
                db.execute('''INSERT INTO atividade_eventos VALUES (?,?,?,?,?)
                    ON CONFLICT(execucao) DO UPDATE SET ultimo_evento=excluded.ultimo_evento,
                    total=excluded.total,ultimo_tipo=excluded.ultimo_tipo,eventos_filhos=excluded.eventos_filhos''',
                    (self.execucao,*evento))
            if operacoes:
                from observabilidade_equipes import registrar_operacoes
                registrar_operacoes(db,self.execucao,operacoes)

    def acompanhar(self):
        while not self.parar.wait(self.intervalo):
            try:self.registrar('acompanhando')
            except (OSError,ValueError,sqlite3.Error):
                self.erro='Sinais de atividade indisponíveis';return

    def evento(self,ev):
        """Metadados de eventos normalizados recebidos; não são sinal de processo."""
        from emit_evento import TIPOS
        if not isinstance(ev,dict) or ev.get('tipo') not in TIPOS:return
        filho=bool(ev.get('sessao_pai'))
        with self.lock:
            if self.parar.is_set():
                self.erro='Evento recebido após acompanhamento encerrado';return
            self.total_eventos+=1;self.eventos_filhos+=int(filho)
            self.ultimo_evento=time.time();self.ultimo_tipo=ev['tipo']
            ident=ev.get('operacao_id');estado=ev.get('operacao_estado')
            if ident and estado in ('executando','segundo_plano','concluido'):
                chave=(str(ev.get('sessao') or '')[:128],str(ident)[:128])
                if chave not in self.operacoes and len(self.operacoes)>=100:
                    encerradas=[k for k,v in self.operacoes.items() if v['fim'] is not None]
                    if encerradas:self.operacoes.pop(encerradas[0])
                    else:return
                op=self.operacoes.setdefault(chave,{'ferramenta':str(ev.get('ferramenta') or 'Ferramenta')[:64],
                    'inicio':self.ultimo_evento if estado=='executando' else None,'fim':None,'estado':estado,'codigo':None})
                if ev.get('operacao_nome') in ('Build','Testes','Comando'):
                    op['ferramenta']=ev['operacao_nome']
                if op['fim'] is None:
                    op['estado']=estado
                    if estado=='concluido':
                        op['fim']=self.ultimo_evento
                        op['codigo']=ev.get('codigo') if type(ev.get('codigo')) is int else None

    def __enter__(self):
        with closing(sqlite3.connect(self.banco,timeout=2)) as db,db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('CREATE TABLE IF NOT EXISTS atividade_execucao ('
                'execucao TEXT PRIMARY KEY,controlador TEXT NOT NULL,pid_controlador INTEGER NOT NULL,'
                'pid_console INTEGER,ultimo_sinal REAL NOT NULL,estado TEXT NOT NULL,codigo_console INTEGER)')
            db.execute('CREATE TABLE IF NOT EXISTS atividade_eventos ('
                'execucao TEXT PRIMARY KEY,ultimo_evento REAL NOT NULL,total INTEGER NOT NULL,'
                'ultimo_tipo TEXT NOT NULL,eventos_filhos INTEGER NOT NULL)')
            if not db.execute('SELECT 1 FROM execucao_tarefa WHERE id=? AND fim IS NULL',(self.execucao,)).fetchone():
                raise ValueError('Atividade exige tentativa sem retorno')
            db.execute('INSERT INTO atividade_execucao VALUES (?,?,?,NULL,?,?,NULL)',
                (self.execucao,self.dono,os.getpid(),time.time(),'acompanhando'))
        self.thread=threading.Thread(target=self.acompanhar,daemon=True);self.thread.start()
        return self

    def __exit__(self,tipo,valor,tb):
        self.parar.set();self.thread.join(timeout=5)
        if self.thread.is_alive():self.erro='Acompanhamento não encerrou'
        try:self.registrar('interrompido' if tipo is not None or self.erro else 'encerrado')
        except (OSError,ValueError,sqlite3.Error):self.erro='Sinais de atividade indisponíveis'
        if tipo is None and self.erro:raise RuntimeError(self.erro)
        return False
