"""Reservas transacionais locais por cartão; Kanban continua sendo a fonte do trabalho.

Esta projeção não publica status no GitHub. Identidades de sessão permanecem
específicas do console. Reservas vencidas exigem conciliação, nunca roubo automático.
"""
import json
import math
import os
import sqlite3
import time
import uuid
from contextlib import closing, contextmanager
from pathlib import Path


@contextmanager
def ocupar_worktree(banco, trabalho):
    """Trava local compartilhada: nunca rouba ocupação antiga por prazo/PID.

    O PID é evidência para conciliação, não autorização de retomada: o console
    e ferramentas filhas podem sobreviver ao controlador. Falha abrupta mantém
    a trava; saída normal libera exclusivamente o identificador desta execução.
    """
    caminho=Path(banco); caminho.parent.mkdir(parents=True,exist_ok=True)
    recurso=os.path.normcase(str(Path(trabalho).resolve()))
    dono=uuid.uuid4().hex
    with closing(sqlite3.connect(caminho,timeout=10)) as db,db:
        db.execute('CREATE TABLE IF NOT EXISTS worktree_ocupado '
                   '(recurso TEXT PRIMARY KEY,dono TEXT NOT NULL,pid INTEGER NOT NULL,inicio REAL NOT NULL)')
        db.execute('BEGIN IMMEDIATE')
        if db.execute('SELECT 1 FROM worktree_ocupado WHERE recurso=?',(recurso,)).fetchone():
            raise ValueError('Worktree já ocupado por um despacho; concilie a execução anterior')
        db.execute('INSERT INTO worktree_ocupado VALUES (?,?,?,?)',(recurso,dono,os.getpid(),time.time()))
    try:
        yield dono
    except BaseException:
        # Não há prova de que o console/ferramentas terminaram nessa saída.
        # A conciliação deverá conferir processos e alterações antes de liberar.
        raise
    else:
        with closing(sqlite3.connect(caminho,timeout=10)) as db,db:
            db.execute('DELETE FROM worktree_ocupado WHERE recurso=? AND dono=?',(recurso,dono))


class Controle:
    def __init__(self, banco):
        self.banco = Path(banco)
        self.banco.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._abrir()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            db.execute("""CREATE TABLE IF NOT EXISTS reserva (
                projeto TEXT NOT NULL, cartao TEXT NOT NULL, token TEXT NOT NULL,
                equipe TEXT NOT NULL, console TEXT NOT NULL, estado TEXT NOT NULL,
                atualizado REAL NOT NULL, sessao TEXT, pacote TEXT NOT NULL,
                PRIMARY KEY (projeto, cartao))""")
            db.execute('''CREATE TABLE IF NOT EXISTS entrega (
                token TEXT PRIMARY KEY, sha TEXT NOT NULL, pr INTEGER NOT NULL,
                aprovado INTEGER NOT NULL, relatorio TEXT NOT NULL, atualizado REAL NOT NULL)''')
            db.execute('''CREATE TABLE IF NOT EXISTS conclusao (
                token TEXT PRIMARY KEY, evidencia TEXT NOT NULL, atualizado REAL NOT NULL)''')
            db.execute("""CREATE TABLE IF NOT EXISTS execucao_tarefa (
                id TEXT PRIMARY KEY,token TEXT NOT NULL,console TEXT NOT NULL,
                modelo TEXT NOT NULL,origem_modelo TEXT NOT NULL,execucao TEXT NOT NULL,
                inicio REAL NOT NULL,fim REAL,duracao_seg REAL,codigo INTEGER)""")
            db.execute('CREATE INDEX IF NOT EXISTS execucao_por_token ON execucao_tarefa(token,inicio)')
            db.execute('''CREATE TABLE IF NOT EXISTS execucao_resultado (
                execucao TEXT PRIMARY KEY,equipe TEXT NOT NULL,tipo TEXT NOT NULL,
                resultado TEXT,atualizado REAL NOT NULL)''')
            db.execute('''CREATE TABLE IF NOT EXISTS execucao_contexto (
                token TEXT PRIMARY KEY,projeto TEXT NOT NULL,cartao TEXT NOT NULL)''')
            # Recupera somente vínculos ainda comprováveis em bancos anteriores.
            # Nunca adivinha a origem de tentativas cujo token já foi substituído.
            db.execute('''INSERT OR IGNORE INTO execucao_contexto
                SELECT DISTINCT r.token,r.projeto,r.cartao FROM reserva r
                JOIN execucao_tarefa e ON e.token=r.token''')
            if db.execute('''SELECT 1 FROM execucao_contexto h JOIN reserva r ON h.token=r.token
                WHERE h.projeto!=r.projeto OR h.cartao!=r.cartao LIMIT 1''').fetchone():
                raise ValueError('Contexto de execução diverge da reserva')

    def _abrir(self):
        db = sqlite3.connect(self.banco, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def reservar(self, projeto, cartao, equipe, console, pacote, quadro_atual=False):
        from providers_console import PROVIDERS
        if not quadro_atual:
            raise ValueError("Despacho exige Kanban atualizado e reconciliado")
        if console not in PROVIDERS:
            raise ValueError("Console ainda não habilitado para execução")
        if not all(isinstance(x, str) and x.strip() for x in (projeto, cartao, equipe)):
            raise ValueError("Projeto, cartão e equipe são obrigatórios")
        if not isinstance(pacote, dict) or not pacote.get("objetivo") or not pacote.get("aceite"):
            raise ValueError("Despacho exige objetivo e aceite")
        token = uuid.uuid4().hex
        with closing(self._abrir()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            atual = db.execute("SELECT estado FROM reserva WHERE projeto=? AND cartao=?",
                               (projeto, cartao)).fetchone()
            if atual and atual["estado"] not in ("cancelado", "concluido"):
                raise ValueError("Cartão já reservado; concilie a execução anterior")
            db.execute("INSERT OR REPLACE INTO reserva VALUES (?,?,?,?,?,?,?,?,?)",
                       (projeto, cartao, token, equipe, console, "reservado", time.time(), None,
                        json.dumps(pacote, ensure_ascii=False)))
        return token

    def iniciar_execucao(self, token, tipo='despacho'):
        """Tentativa do controlador, não comprovação de PID ou modelo efetivo."""
        if tipo not in ('despacho','retomada'):raise ValueError('Tipo de tentativa inválido')
        ident=uuid.uuid4().hex
        with closing(self._abrir()) as db,db:
            db.execute('BEGIN IMMEDIATE')
            tarefa=db.execute('SELECT estado,console,pacote,projeto,cartao,equipe FROM reserva WHERE token=?',(token,)).fetchone()
            if not tarefa or tarefa['estado']!='executando':
                raise ValueError('Medição exige tarefa em execução')
            if not isinstance(tarefa['equipe'],str) or not tarefa['equipe'].strip() or len(tarefa['equipe'])>200:
                raise ValueError('Equipe inválida na atribuição')
            if db.execute('SELECT 1 FROM execucao_tarefa WHERE token=? AND fim IS NULL',(token,)).fetchone():
                raise ValueError('Tentativa anterior sem retorno; concilie antes de medir outra')
            executor=json.loads(tarefa['pacote']).get('executor') or {}
            modelo=executor.get('modelo') or 'não informado'
            origem='configurado' if executor.get('modelo') else 'não informado'
            modo=executor.get('execucao','cloud')
            if not isinstance(modelo,str) or modo not in ('cloud','local'):
                raise ValueError('Executor inválido na reserva')
            db.execute('INSERT OR IGNORE INTO execucao_contexto VALUES (?,?,?)',
                       (token,tarefa['projeto'],tarefa['cartao']))
            contexto=db.execute('SELECT projeto,cartao FROM execucao_contexto WHERE token=?',(token,)).fetchone()
            if tuple(contexto)!=(tarefa['projeto'],tarefa['cartao']):
                raise ValueError('Contexto de execução diverge da reserva')
            db.execute('INSERT INTO execucao_tarefa VALUES (?,?,?,?,?,?,?,NULL,NULL,NULL)',
                (ident,token,tarefa['console'],modelo,origem,modo,time.time()))
            db.execute('INSERT INTO execucao_resultado VALUES (?,?,?,NULL,?)',
                (ident,tarefa['equipe'],tipo,time.time()))
        return ident

    def registrar_resultado(self, ident, resultado):
        """Resultado do despacho terminado; não é aceite/merge ou qualidade do código."""
        if resultado not in ('falha_console','sem_entrega','revisao_aprovada',
                             'revisao_desativada','revisao_reprovada','gate_bloqueado'):
            raise ValueError('Resultado de tentativa inválido')
        with closing(self._abrir()) as db,db:
            db.execute('BEGIN IMMEDIATE')
            t=db.execute('SELECT e.fim,e.codigo,a.resultado FROM execucao_tarefa e '
                'JOIN execucao_resultado a ON a.execucao=e.id WHERE e.id=?',(ident,)).fetchone()
            if not t or t['fim'] is None or t['codigo'] is None:
                raise ValueError('Resultado exige retorno e atribuição registrados')
            if (t['codigo']!=0)!=(resultado=='falha_console'):
                raise ValueError('Resultado diverge do retorno do console')
            if t['resultado'] is not None:
                if t['resultado']!=resultado:raise ValueError('Tentativa já tem outro resultado')
                return
            db.execute('UPDATE execucao_resultado SET resultado=?,atualizado=? WHERE execucao=?',
                (resultado,time.time(),ident))

    def retomar(self, esperado):
        """Claim da reserva conferida; conserva sessão/pacote e todas as tentativas."""
        with closing(self._abrir()) as db,db:
            db.execute('BEGIN IMMEDIATE')
            linha=db.execute('SELECT * FROM reserva WHERE token=?',(esperado['token'],)).fetchone()
            atual=dict(linha,pacote=json.loads(linha['pacote'])) if linha else None
            if atual!=esperado or atual['estado']!='bloqueado' or not atual['sessao']:
                raise ValueError('Reserva mudou desde a prévia de retomada')
            if db.execute('SELECT 1 FROM execucao_tarefa WHERE token=? AND fim IS NULL',(esperado['token'],)).fetchone():
                raise ValueError('Tentativa sem retorno; retomada bloqueada')
            db.execute('UPDATE reserva SET estado=?,atualizado=? WHERE token=?',
                ('executando',time.time(),esperado['token']))

    def terminar_execucao(self, ident, codigo, duracao_seg):
        if (type(codigo) is not int or type(duracao_seg) not in (int,float)
            or not math.isfinite(duracao_seg) or duracao_seg<0):
            raise ValueError('Retorno/intervalo de execução inválido')
        with closing(self._abrir()) as db,db:
            db.execute('BEGIN IMMEDIATE')
            atual=db.execute('SELECT fim,codigo,duracao_seg FROM execucao_tarefa WHERE id=?',(ident,)).fetchone()
            if not atual: raise ValueError('Tentativa não encontrada')
            if atual['fim'] is not None:
                if atual['codigo']!=codigo or atual['duracao_seg']!=duracao_seg:
                    raise ValueError('Tentativa já tem outro retorno registrado')
                return
            db.execute('UPDATE execucao_tarefa SET fim=?,duracao_seg=?,codigo=? WHERE id=?',
                (time.time(),duracao_seg,codigo,ident))


    def transicao(self, token, estado, sessao=None):
        permitidas = {"reservado": {"executando", "cancelado", "bloqueado"},
                     "executando": {"revisao", "bloqueado", "cancelado"},
                     "bloqueado": {"executando", "cancelado"},
                     "revisao": {"executando", "concluido", "bloqueado", "cancelado"}}
        with closing(self._abrir()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            atual = db.execute("SELECT * FROM reserva WHERE token=?", (token,)).fetchone()
            if not atual or estado not in permitidas.get(atual["estado"], set()):
                raise ValueError("Transição de tarefa inválida")
            if sessao is not None and (not isinstance(sessao, str) or not sessao.strip()):
                raise ValueError("Sessão inválida")
            if sessao and atual["sessao"] and sessao != atual["sessao"]:
                raise ValueError("Sessão já vinculada; concilie antes de trocar")
            db.execute("UPDATE reserva SET estado=?, atualizado=?, sessao=COALESCE(?,sessao) WHERE token=?",
                       (estado, time.time(), sessao, token))

    def listar(self, projeto):
        with closing(self._abrir()) as db:
            linhas = db.execute("SELECT * FROM reserva WHERE projeto=? ORDER BY atualizado", (projeto,)).fetchall()
        return [dict(x, pacote=json.loads(x["pacote"])) for x in linhas]

    def vincular_sessao(self, token, console, sessao):
        """ID observado no console da reserva; vínculo imutável, sem transição de tarefa."""
        import re
        if not isinstance(sessao,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,256}',sessao):
            raise ValueError('ID de sessão nativa inválido')
        with closing(self._abrir()) as db,db:
            db.execute('BEGIN IMMEDIATE')
            atual=db.execute('SELECT console,sessao,estado FROM reserva WHERE token=?',(token,)).fetchone()
            if not atual or atual['console'] != console or atual['estado'] != 'executando':
                raise ValueError('Sessão não pertence ao console/tarefa em execução')
            if atual['sessao'] and atual['sessao'] != sessao:
                raise ValueError('Console informou outra sessão; concilie antes de trocar')
            db.execute('UPDATE reserva SET sessao=?,atualizado=? WHERE token=?',(sessao,time.time(),token))

    def registrar_skills(self, token, evidencia):
        with closing(self._abrir()) as db,db:
            db.execute('BEGIN IMMEDIATE')
            linha=db.execute('SELECT estado,console,sessao,pacote FROM reserva WHERE token=?',(token,)).fetchone()
            if not linha or linha['estado']!='executando' or linha['console']!='claude':
                raise ValueError('Evidência de skills exige tarefa Claude em execução')
            pacote=json.loads(linha['pacote'])
            nomes=sorted({r['nome'] for r in pacote.get('skills_resolvidas',[]) if r.get('ativacao_nativa')=='Skill'})
            if (not isinstance(evidencia,dict) or set(evidencia)!={'console','sessao','solicitadas','confirmadas','pendentes','valida'}
                    or evidencia['console']!='claude' or not linha['sessao'] or evidencia['sessao']!=linha['sessao']
                    or evidencia['solicitadas']!=nomes or type(evidencia['valida']) is not bool
                    or not isinstance(evidencia['confirmadas'],list) or not isinstance(evidencia['pendentes'],list)
                    or any(n not in nomes for n in evidencia['confirmadas']+evidencia['pendentes'])
                    or sorted(set(evidencia['confirmadas'])|set(evidencia['pendentes']))!=nomes
                    or set(evidencia['confirmadas'])&set(evidencia['pendentes'])
                    or (evidencia['valida'] and evidencia['pendentes'])):
                raise ValueError('Evidência de skills diverge da tarefa/sessão')
            if 'skills_verificadas' in pacote and pacote['skills_verificadas']!=evidencia:
                raise ValueError('Evidência de skills já registrada; concilie divergência')
            pacote['skills_verificadas']=evidencia
            db.execute('UPDATE reserva SET pacote=?,atualizado=? WHERE token=?',
                       (json.dumps(pacote,ensure_ascii=False),time.time(),token))

    def skills(self, token):
        with closing(self._abrir()) as db:
            linha=db.execute('SELECT pacote FROM reserva WHERE token=?',(token,)).fetchone()
            return json.loads(linha['pacote']).get('skills_verificadas',{}) if linha else {}

    def registrar_dependencias(self, token, fase, evidencia):
        if fase not in ('antes_execucao','entrega','apos_revisao'):
            raise ValueError('Fase de verificação inválida')
        ts = evidencia.get('verificadas_em') if isinstance(evidencia, dict) else None
        if (type(ts) not in (float,int) or not math.isfinite(ts) or ts <= 0
                or not isinstance(evidencia.get('itens'),list)):
            raise ValueError('Evidência de dependências inválida')
        with closing(self._abrir()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            linha = db.execute('SELECT estado,pacote FROM reserva WHERE token=?',(token,)).fetchone()
            if not linha or linha['estado'] not in ('reservado','executando'):
                raise ValueError('Tarefa não admite nova verificação de dependências')
            pacote = json.loads(linha['pacote'])
            pacote.setdefault('dependencias_verificadas',{})[fase] = evidencia
            db.execute('UPDATE reserva SET pacote=?,atualizado=? WHERE token=?',
                       (json.dumps(pacote,ensure_ascii=False),time.time(),token))

    def registrar_revisao(self, token, pr, relatorio, cfg):
        from revisao_cruzada import conferir
        import re
        sha = relatorio.get('sha')
        if type(pr) is not int or pr < 1 or not re.fullmatch('[0-9a-f]{40}', sha or ''):
            raise ValueError('Entrega exige PR e commit exato')
        aprovado = conferir(cfg, relatorio, sha)
        with closing(self._abrir()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            atual = db.execute('SELECT estado FROM reserva WHERE token=?', (token,)).fetchone()
            if not atual or atual['estado'] not in ('executando', 'revisao'):
                raise ValueError('Tarefa não está em execução/revisão')
            db.execute('INSERT INTO entrega VALUES (?,?,?,?,?,?) ON CONFLICT(token) DO UPDATE SET '
                       'sha=excluded.sha,pr=excluded.pr,aprovado=excluded.aprovado,relatorio=excluded.relatorio,atualizado=excluded.atualizado',
                       (token, sha, pr, int(aprovado), json.dumps(relatorio, ensure_ascii=False), time.time()))
        return aprovado

    def revisao(self, token):
        with closing(self._abrir()) as db:
            linha = db.execute('SELECT * FROM entrega WHERE token=?', (token,)).fetchone()
        return dict(linha, relatorio=json.loads(linha['relatorio'])) if linha else None

    def registrar_conclusao(self, token, evidencia):
        """Diário local anterior à escrita remota; permite conciliar uma falha posterior."""
        texto=json.dumps(evidencia,ensure_ascii=False,sort_keys=True)
        with closing(self._abrir()) as db,db:
            db.execute('BEGIN IMMEDIATE')
            linha=db.execute('SELECT estado FROM reserva WHERE token=?',(token,)).fetchone()
            if not linha or linha['estado']!='revisao':
                raise ValueError('Conclusão exige reserva em revisão')
            anterior=db.execute('SELECT evidencia FROM conclusao WHERE token=?',(token,)).fetchone()
            if anterior and anterior['evidencia']!=texto:
                raise ValueError('Evidência de conclusão diverge da registrada')
            db.execute('INSERT OR IGNORE INTO conclusao VALUES (?,?,?)',(token,texto,time.time()))

    def concluir(self, token):
        with closing(self._abrir()) as db,db:
            db.execute('BEGIN IMMEDIATE')
            linha=db.execute('SELECT estado FROM reserva WHERE token=?',(token,)).fetchone()
            if not linha or linha['estado'] not in ('revisao','concluido'):
                raise ValueError('Reserva não admite conclusão')
            if not db.execute('SELECT 1 FROM conclusao WHERE token=?',(token,)).fetchone():
                raise ValueError('Conclusão sem evidência persistida')
            if linha['estado']=='revisao':
                db.execute('UPDATE reserva SET estado=?,atualizado=? WHERE token=?',('concluido',time.time(),token))
