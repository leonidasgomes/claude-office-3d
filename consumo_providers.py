"""Consumo observado, separado da cota e da cobrança. Não guarda prompts nem credenciais."""
import hashlib
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import re
import time
import uuid


def identidade_projeto(projeto):
    return hashlib.sha256(str(Path(projeto).resolve()).encode()).hexdigest()


def filtro_periodo(desde,ate,projeto_hash=None,tentativas=None):
    if projeto_hash is not None and (not isinstance(projeto_hash,str) or not re.fullmatch('[0-9a-f]{64}',projeto_hash)):
        raise ValueError('Identidade de projeto inválida')
    where='ts>=? AND ts<=?'+(' AND projeto=?' if projeto_hash is not None else '')
    parametros=(desde,ate)+( (projeto_hash,) if projeto_hash is not None else ())
    if tentativas is not None:
        if (projeto_hash is None or not isinstance(tentativas,(list,tuple)) or not 1<=len(tentativas)<=1000
            or any(not isinstance(t,str) or not re.fullmatch('[0-9a-f]{32}',t) for t in tentativas)
            or len(set(tentativas))!=len(tentativas)):
            raise ValueError('Vínculos de tentativa inválidos')
        where+=' AND chave IN (SELECT chave FROM consumo_tentativa WHERE projeto=? AND tentativa IN ('+','.join('?' for _ in tentativas)+'))'
        parametros+=(projeto_hash,*tentativas)
    return where,parametros


def contador(valor):
    return valor if type(valor) is int and 0 <= valor <= 2**53 - 1 else None


def tokens_opencode(uso):
    """StepFinishPart V1: input/output excluem cache/reasoning, respectivamente."""
    if not isinstance(uso, dict):
        return {}
    cache = uso.get('cache') if isinstance(uso.get('cache'), dict) else {}
    entrada, leitura, escrita, saida, raciocinio = (
        contador(v) for v in (uso.get('input'), cache.get('read'), cache.get('write'),
                              uso.get('output'), uso.get('reasoning')))
    def soma(*partes):
        return contador(sum(partes)) if all(v is not None for v in partes) else None
    normal_entrada = soma(entrada, leitura, escrita)
    normal_saida = soma(saida, raciocinio)
    # Total nativo pode conter componentes não expostos; não substituí-lo por soma.
    total = contador(uso.get('total')) if 'total' in uso else soma(normal_entrada, normal_saida)
    return {'entrada': normal_entrada, 'cache': leitura, 'saida': normal_saida, 'total': total}


class Registro:
    def __init__(self, arquivo,tentativa=None):
        if tentativa is not None and (not isinstance(tentativa,str) or not re.fullmatch('[0-9a-f]{32}',tentativa)):
            raise ValueError('Identidade de tentativa inválida')
        self.arquivo = Path(arquivo)
        self.tentativa=tentativa

    def _vincular(self,db,chave,projeto):
        if self.tentativa is None:return
        filtro_periodo(0,0,projeto)
        db.execute('''CREATE TABLE IF NOT EXISTS consumo_tentativa (
            chave TEXT PRIMARY KEY,projeto TEXT NOT NULL,tentativa TEXT NOT NULL)''')
        db.execute('CREATE INDEX IF NOT EXISTS consumo_por_tentativa ON consumo_tentativa(projeto,tentativa)')
        anterior=db.execute('SELECT projeto,tentativa FROM consumo_tentativa WHERE chave=?',(chave,)).fetchone()
        if anterior is not None and tuple(anterior)!=(projeto,self.tentativa):
            raise ValueError('Consumo já pertence a outra tentativa')
        if anterior is None and db.execute('SELECT 1 FROM consumo WHERE chave=?',(chave,)).fetchone():
            raise ValueError('Histórico de consumo sem vínculo não pode ser reatribuído')
        db.execute('INSERT OR IGNORE INTO consumo_tentativa VALUES (?,?,?)',(chave,projeto,self.tentativa))

    def gravar(self, chave, provider, modelo, origem_modelo, agente, projeto, sessao, fonte, tokens):
        entrada, cache, saida, total = (contador(tokens.get(k)) for k in ('entrada', 'cache', 'saida', 'total'))
        if entrada is None and saida is None and total is None:
            return False
        if entrada is not None and cache is not None and cache > entrada:
            raise ValueError('Cache maior que entrada')
        self.arquivo.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.arquivo, timeout=5)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('''CREATE TABLE IF NOT EXISTS consumo (
                chave TEXT PRIMARY KEY, ts REAL NOT NULL, provider TEXT NOT NULL,
                modelo TEXT NOT NULL, origem_modelo TEXT NOT NULL, agente TEXT NOT NULL,
                projeto TEXT NOT NULL, sessao TEXT NOT NULL, fonte TEXT NOT NULL,
                entrada INTEGER, cache INTEGER, saida INTEGER, total INTEGER)''')
            self._vincular(db,chave,projeto)
            db.execute('''INSERT INTO consumo VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(chave) DO UPDATE SET entrada=excluded.entrada,
                cache=excluded.cache, saida=excluded.saida, total=excluded.total''',
                (chave, time.time(), provider, modelo, origem_modelo, agente,
                 projeto, sessao, fonte, entrada, cache, saida, total))
        return True

    def cumulativo_codex(self, projeto, sessao, agente, modelo, tokens, base=False, rotulo='codex'):
        valores = [contador(tokens.get(k)) for k in ('input_tokens', 'cached_input_tokens', 'output_tokens', 'total_tokens')]
        if not sessao or any(v is None for v in valores) or valores[1] > valores[0]:
            return False
        self.arquivo.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.arquivo, timeout=5)) as db, db:
            db.execute('''CREATE TABLE IF NOT EXISTS saldo_codex (
                projeto TEXT, sessao TEXT, entrada INTEGER, cache INTEGER, saida INTEGER,
                total INTEGER, PRIMARY KEY(projeto,sessao))''')
            db.execute('BEGIN IMMEDIATE')
            anterior = db.execute('SELECT entrada,cache,saida,total FROM saldo_codex WHERE projeto=? AND sessao=?',
                                  (projeto, sessao)).fetchone()
            if anterior and any(v < a for v, a in zip(valores, anterior)):
                return False  # Replay antigo/reset desconhecido não rebaixa o saldo.
            delta = [v - a for v, a in zip(valores, anterior or [0]*4)]
            if not base and delta[1] > delta[0]:
                return False  # Correção de contador não prova consumo faturável novo.
            if not base and any(delta):
                db.execute('''CREATE TABLE IF NOT EXISTS consumo (
                    chave TEXT PRIMARY KEY, ts REAL NOT NULL, provider TEXT NOT NULL,
                    modelo TEXT NOT NULL, origem_modelo TEXT NOT NULL, agente TEXT NOT NULL,
                    projeto TEXT NOT NULL, sessao TEXT NOT NULL, fonte TEXT NOT NULL,
                    entrada INTEGER, cache INTEGER, saida INTEGER, total INTEGER)''')
                chave = hashlib.sha256(f'rollout|{projeto}|{sessao}|{valores}'.encode()).hexdigest()
                self._vincular(db,chave,projeto)
                db.execute('INSERT OR IGNORE INTO consumo VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                           (chave, time.time(), rotulo, modelo or 'não informado',
                            'informado' if modelo else 'não informado', agente, projeto, sessao,
                            'codex.rollout/token_count.delta', *delta))
            db.execute('INSERT INTO saldo_codex VALUES (?,?,?,?,?,?) ON CONFLICT(projeto,sessao) DO UPDATE SET '
                       'entrada=excluded.entrada,cache=excluded.cache,saida=excluded.saida,total=excluded.total',
                       (projeto, sessao, *valores))
        return True

    def cumulativo_claude(self,projeto,sessao,modelo,agente,execucao,valores,novo=False):
        """Snapshot por modelo: baseline + incremento na mesma transação."""
        if (type(novo) is not bool or not isinstance(valores,(list,tuple)) or len(valores)!=4 or any(contador(v) is None for v in valores)
            or contador(sum(valores)) is None):return False
        self.arquivo.parent.mkdir(parents=True,exist_ok=True)
        with closing(sqlite3.connect(self.arquivo,timeout=5)) as db,db:
            db.execute('''CREATE TABLE IF NOT EXISTS saldo_claude (
                projeto TEXT,sessao TEXT,modelo TEXT,entrada INTEGER,cache INTEGER,
                criacao INTEGER,saida INTEGER,PRIMARY KEY(projeto,sessao,modelo))''')
            db.execute('BEGIN IMMEDIATE')
            anterior=db.execute('SELECT entrada,cache,criacao,saida FROM saldo_claude '
                'WHERE projeto=? AND sessao=? AND modelo=?',(projeto,sessao,modelo)).fetchone()
            if anterior and any(v<a for v,a in zip(valores,anterior)):return False
            base=anterior is None and not novo
            delta=[v-a for v,a in zip(valores,anterior or [0]*4)]
            if not base and (any(delta) or anterior is None):
                tokens=(sum(delta[:3]),delta[1],delta[3],sum(delta))
                db.execute('''CREATE TABLE IF NOT EXISTS consumo (
                    chave TEXT PRIMARY KEY,ts REAL NOT NULL,provider TEXT NOT NULL,
                    modelo TEXT NOT NULL,origem_modelo TEXT NOT NULL,agente TEXT NOT NULL,
                    projeto TEXT NOT NULL,sessao TEXT NOT NULL,fonte TEXT NOT NULL,
                    entrada INTEGER,cache INTEGER,saida INTEGER,total INTEGER)''')
                chave=hashlib.sha256(json.dumps(['claude-delta',projeto,sessao,modelo,execucao],
                    separators=(',',':')).encode()).hexdigest()
                self._vincular(db,chave,projeto)
                db.execute('''INSERT INTO consumo VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(chave) DO UPDATE SET entrada=consumo.entrada+excluded.entrada,
                    cache=consumo.cache+excluded.cache,saida=consumo.saida+excluded.saida,
                    total=consumo.total+excluded.total''',
                    (chave,time.time(),'claude',modelo,'informado',agente,projeto,sessao,
                     'claude.stream/modelUsage.delta',*tokens))
            db.execute('INSERT INTO saldo_claude VALUES (?,?,?,?,?,?,?) '
                'ON CONFLICT(projeto,sessao,modelo) DO UPDATE SET entrada=excluded.entrada,'
                'cache=excluded.cache,criacao=excluded.criacao,saida=excluded.saida',
                (projeto,sessao,modelo,*valores))
        return not base

    def resumo(self, agora=None,projeto_hash=None,tentativas=None):
        agora = time.time() if agora is None else agora
        where,parametros=filtro_periodo(agora-7*86400,agora,projeto_hash,tentativas)
        base = {'dias': 7, 'desde': agora - 7 * 86400, 'grupos': [],
                'cobranca_usd': None, 'estimativa_usd': None,'escopo':'projeto' if projeto_hash is not None else 'escritorio'}
        if not self.arquivo.is_file():
            return base
        # Abrir o painel não cria tabelas/arquivos nem altera o histórico.
        with closing(sqlite3.connect(self.arquivo.resolve().as_uri() + '?mode=ro', uri=True, timeout=5)) as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='consumo'").fetchone():
                return base
            if tentativas is not None and not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='consumo_tentativa'").fetchone():return base
            for row in db.execute('''SELECT provider,modelo,origem_modelo,agente,COUNT(*),
                SUM(entrada),SUM(cache),SUM(saida),SUM(total),COUNT(entrada),COUNT(saida),COUNT(total)
                FROM consumo WHERE '''+where+'''
                GROUP BY provider,modelo,origem_modelo,agente
                ORDER BY provider,modelo,agente''', parametros):
                keys = ('provider', 'modelo', 'origem_modelo', 'agente', 'amostras',
                        'entrada', 'cache', 'saida', 'total', 'com_entrada', 'com_saida', 'com_total')
                grupo = dict(zip(keys, row))
                if grupo['provider'] in ('opencode', 'opencode_local'):
                    modelo = grupo['modelo']
                    grupo['provider_modelo'] = (modelo.split('/', 1)[0]
                        if '/' in modelo and grupo['origem_modelo'] in ('configurado', 'informado') else None)
                    grupo['origem_provider_modelo'] = (grupo['origem_modelo'] if grupo['provider_modelo'] else 'não informado')
                base['grupos'].append(grupo)
            from precos_tokens import aplicar
            aplicar(db, base, self.arquivo.parent / 'precos_tokens.json',projeto_hash=projeto_hash,tentativas=tentativas)
        return base

    def resumos_tentativas(self,tentativas,projeto_hash,agora=None):
        """Uma leitura em lote, com os mesmos contadores/preços do resumo público."""
        agora=time.time() if agora is None else agora
        where,parametros=filtro_periodo(agora-7*86400,agora,projeto_hash,tentativas)
        if not self.arquivo.is_file():return {}
        with closing(sqlite3.connect(self.arquivo.resolve().as_uri()+'?mode=ro',uri=True,timeout=5)) as db:
            if any(not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(t,)).fetchone()
                   for t in ('consumo','consumo_tentativa')):return {}
            # O filtro continua no ledger, e o JOIN só recupera o vínculo já validado.
            sql='FROM consumo WHERE '+where
            itens={};grupos={}
            for row in db.execute('SELECT (SELECT tentativa FROM consumo_tentativa v WHERE v.chave=consumo.chave),'
                'provider,modelo,origem_modelo,agente,COUNT(*),SUM(entrada),SUM(cache),SUM(saida),SUM(total),'
                'COUNT(entrada),COUNT(saida),COUNT(total) '+sql+' GROUP BY 1,provider,modelo,origem_modelo,agente',parametros):
                ident=row[0];g=dict(zip(('provider','modelo','origem_modelo','agente','amostras','entrada','cache','saida','total','com_entrada','com_saida','com_total'),row[1:]))
                if g['provider'] in ('opencode','opencode_local'):
                    g['provider_modelo']=g['modelo'].split('/',1)[0] if '/' in g['modelo'] and g['origem_modelo'] in ('informado','configurado') else None
                    g['origem_provider_modelo']=g['origem_modelo'] if g['provider_modelo'] else 'não informado'
                itens.setdefault(ident,{'dias':7,'desde':agora-7*86400,'escopo':'tentativa','grupos':[]})['grupos'].append(g)
                grupos[(ident,*row[1:5])]=g
            from precos_tokens import carregar,equivalente
            try:tarifas=carregar(self.arquivo.parent/'precos_tokens.json');estado='configurado' if tarifas else 'sem catálogo'
            except (ValueError,OSError,OverflowError):tarifas=[];estado='catálogo inválido'
            for resumo in itens.values():resumo['precos']={'estado':estado,'tipo':'equivalente teórico de API','amostras':0}
            if tarifas:
                from decimal import Decimal
                somas={}
                for g in grupos.values():g.update(equivalente_api_usd=None,com_preco=0)
                for row in db.execute('SELECT (SELECT tentativa FROM consumo_tentativa v WHERE v.chave=consumo.chave),'
                    'provider,modelo,origem_modelo,agente,ts,entrada,cache,saida,fonte '+sql,parametros):
                    ident,p,m,o,a,ts,i,c,s,f=row;valor=equivalente(tarifas,p,m,o,ts,i,c,s,f)
                    if valor is not None:
                        chave=(ident,p,m,o,a);somas[chave]=somas.get(chave,Decimal(0))+valor
                        grupos[chave]['com_preco']+=1;itens[ident]['precos']['amostras']+=1
                for chave,valor in somas.items():grupos[chave]['equivalente_api_usd']=format(valor,'f')
            return itens


class Coletor:
    """Uma execução nova tem ID próprio; snapshots finais usam chave idempotente.

    Codex exec: um turno por execução. Gemini: uma amostra por modelo, sem somar
    o agregado novamente. Outros envelopes ficam sem consumo até terem um
    adapter validado; seus valores ausentes não viram zero. OpenCode V1 usa uma
    amostra por step-finish com identidade persistente (projeto/sessão/part).
    """
    def __init__(self, arquivo, provider, projeto, agente, modelo=None, rotulo=None, origem_modelo=None, sessao_claude_nova=None,sessao_claude_retomada=None,tentativa=None):
        self.registro = Registro(arquivo,tentativa)
        self.provider, self.agente = provider, agente
        self.rotulo = rotulo or provider
        self.modelo = modelo or 'não informado'
        self.origem_modelo = (origem_modelo or 'configurado') if modelo else 'não informado'
        self.projeto = identidade_projeto(projeto)
        self.execucao, self.sessao = uuid.uuid4().hex, ''
        self.claude=None
        if sessao_claude_nova is not None and sessao_claude_retomada is not None:raise ValueError('Sessão Claude nova e retomada são alternativas')
        ident=sessao_claude_nova if sessao_claude_nova is not None else sessao_claude_retomada
        if ident is not None:
            if provider!='claude' or self.rotulo!='claude' or not isinstance(ident,str) or not 1<=len(ident)<=256:
                raise ValueError('Consumo Claude exige identidade cloud da sessão observada pelo launcher')
            from consumo_coordenacao import SnapshotClaude
            self.claude=SnapshotClaude(self,sessao_esperada=ident,novo=sessao_claude_nova is not None)

    def consumir(self, evento):
        if self.provider=='claude':
            if self.claude:return self.claude.consumir(evento)
            return
        tipo = evento.get('type')
        self.sessao = str(evento.get('thread_id') or evento.get('session_id') or evento.get('sessionID') or self.sessao)
        amostras = []
        if self.provider == 'codex' and tipo == 'turn.completed':
            uso = evento.get('usage') or {}
            entrada, saida = contador(uso.get('input_tokens')), contador(uso.get('output_tokens'))
            amostras.append(('turno', self.modelo, self.origem_modelo, 'codex.exec/turn.completed',
                {'entrada': entrada, 'cache': uso.get('cached_input_tokens'), 'saida': saida,
                 'total': entrada + saida if entrada is not None and saida is not None else None}))
        elif self.provider == 'gemini' and tipo == 'result':
            stats = evento.get('stats') or {}
            modelos = stats.get('models')
            if isinstance(modelos, dict) and modelos:
                itens = [(str(m), 'informado', u) for m, u in modelos.items() if isinstance(u, dict)]
            else:
                itens = [(self.modelo, self.origem_modelo, stats)]
            for modelo, origem, uso in itens:
                amostras.append((modelo, modelo, origem, 'gemini.result/stats',
                    {'entrada': uso.get('input_tokens'), 'cache': uso.get('cached'),
                     'saida': uso.get('output_tokens'), 'total': uso.get('total_tokens')}))
        elif self.provider == 'opencode' and tipo == 'step_finish':
            part = evento.get('part')
            if not isinstance(part, dict) or part.get('type') != 'step-finish':
                return
            # Não atribuir contadores sem identidade nem importar sessão divergente.
            ident, sessao_part = part.get('id'), part.get('sessionID')
            if (not isinstance(ident, str) or not ident or len(ident) > 256 or
                not isinstance(sessao_part, str) or not sessao_part or len(sessao_part) > 256 or
                evento.get('sessionID') != sessao_part):
                return
            chave = hashlib.sha256(json.dumps([self.projeto, 'opencode.step', sessao_part, ident],
                ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
            self.registro.gravar(chave, self.rotulo, self.modelo, self.origem_modelo, self.agente,
                                 self.projeto, sessao_part, 'opencode.run/step_finish.v1',
                                 tokens_opencode(part.get('tokens')))
        for unidade, modelo, origem, fonte, tokens in amostras:
            chave = hashlib.sha256(f'{self.projeto}|{self.provider}|{self.execucao}|{unidade}'.encode()).hexdigest()
            self.registro.gravar(chave, self.rotulo, modelo, origem, self.agente,
                                 self.projeto, self.sessao, fonte, tokens)


class ColetorRollout:
    def __init__(self, arquivo, projeto, agente, sessao, novo, rotulo='codex',tentativa=None):
        self.registro = Registro(arquivo,tentativa)
        self.projeto = identidade_projeto(projeto)
        self.agente, self.sessao, self.modelo = agente, sessao, None
        self.precisa_base = not novo
        self.rotulo = rotulo

    def consumir(self, registro, base=False):
        payload = registro.get('payload') or {}
        if registro.get('type') == 'turn_context':
            self.modelo = str(payload.get('model') or '') or None
        elif registro.get('type') == 'event_msg' and payload.get('type') == 'token_count':
            tokens = (payload.get('info') or {}).get('total_token_usage')
            if isinstance(tokens, dict):
                if self.registro.cumulativo_codex(self.projeto, self.sessao, self.agente,
                    self.modelo, tokens, base=base or self.precisa_base, rotulo=self.rotulo):
                    self.precisa_base = False


def main(argv=None):
    """Ponte limitada do plugin; JSON de contadores via stdin, nunca eventos de texto."""
    import argparse
    import sys
    parser = argparse.ArgumentParser(description='Registra contadores observados do plugin OpenCode')
    parser.add_argument('--opencode', action='store_true', required=True)
    parser.add_argument('--banco', help='banco de consumo isolado; padrão ao lado do banco do escritório')
    args = parser.parse_args(argv)
    try:
        bruto = sys.stdin.buffer.read(131073)
        if len(bruto) > 131072:
            raise ValueError('Registro de consumo acima do limite')
        dados = json.loads(bruto)
        if not isinstance(dados,dict) or set(dados)-{'projeto','agente','modelo','rotulo','evento'}:
            raise ValueError('Registro de consumo inválido')
        projeto, agente, modelo = (dados.get(k) for k in ('projeto','agente','modelo'))
        if (not isinstance(projeto,str) or not Path(projeto).is_absolute() or not Path(projeto).is_dir()
            or not isinstance(agente,str) or not 1<=len(agente)<=256
            or (modelo is not None and (not isinstance(modelo,str) or not 1<=len(modelo)<=512))):
            raise ValueError('Identidade de consumo inválida')
        rotulo=dados.get('rotulo','opencode')
        if rotulo not in ('opencode','opencode_local'):
            raise ValueError('Origem de consumo inválida')
        evento=dados.get('evento')
        if not isinstance(evento,dict) or evento.get('type')!='step_finish':
            raise ValueError('Etapa de consumo inválida')
        if args.banco:
            arquivo=Path(args.banco)
        else:
            import banco
            arquivo=banco.ARQ.parent/'consumo_providers.db'
        Coletor(arquivo,'opencode',projeto,agente,modelo,rotulo=rotulo,
                origem_modelo='informado').consumir(evento)
        return 0
    except (ValueError, TypeError, OSError, sqlite3.Error):
        print('Consumo OpenCode indisponível; nenhuma cobrança presumida.',file=sys.stderr)
        return 2


if __name__ == '__main__':
    import sys
    sys.exit(main())
