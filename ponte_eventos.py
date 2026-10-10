"""Ponte explícita de eventos: fonte SQLite somente leitura, destino da edição nova."""
import argparse
from contextlib import closing
import copy,hashlib,json,os,re,sqlite3,threading,time
from pathlib import Path
import banco
from emit_evento import normalizar


def identidade(arquivo):
    s=arquivo.stat()
    if not s.st_ino:raise ValueError('Sistema de arquivos não informa identidade da fonte')
    return f'{s.st_dev}:{s.st_ino}'


def sincronizar(origem,fonte,destino,provider,ultimos=0):
    if not isinstance(origem,str) or not re.fullmatch('[a-z0-9][a-z0-9_-]{0,31}',origem):raise ValueError('Origem inválida')
    if provider not in ('claude','codex','opencode','gemini'):raise ValueError('Provider inválido')
    if type(ultimos) is not int or not 0<=ultimos<=200:raise ValueError('Últimos precisa estar entre 0 e 200')
    fonte=Path(fonte).resolve();destino=Path(destino).resolve()
    if not fonte.is_file():raise ValueError('Fonte não existe')
    marcador=destino/'EDICAO.json'
    if not marcador.is_file() or marcador.is_symlink() or marcador.stat().st_size>1024:raise ValueError('Identificação do destino inválida')
    edicao=json.loads(marcador.read_text(encoding='utf-8'))
    if edicao!={'edicao':'office-multi-provider','formato':1} or type(edicao.get('formato')) is not int:
        raise ValueError('Destino deve ser instalação identificada da edição nova')
    pasta=destino/'dados';alvo=pasta/'escritorio.db'
    if pasta.is_symlink() or getattr(pasta,'is_junction',lambda:False)() or alvo.is_symlink():raise ValueError('Destino por link não permitido')
    if alvo.exists() and os.path.samefile(fonte,alvo):raise ValueError('Fonte e destino devem ser separados')
    arquivo_id=identidade(fonte);pasta.mkdir(exist_ok=True)
    with closing(sqlite3.connect(alvo,timeout=5)) as d:
        d.executescript(banco.ESQUEMA)
        d.execute('CREATE TABLE IF NOT EXISTS ponte_eventos (origem TEXT PRIMARY KEY, caminho TEXT NOT NULL, arquivo_id TEXT NOT NULL UNIQUE, provider TEXT NOT NULL, ancora_id INTEGER, ancora_sha TEXT, cursor INTEGER NOT NULL)')
        d.commit();d.execute('BEGIN IMMEDIATE')
        try:
            anterior=d.execute('SELECT caminho,arquivo_id,provider,ancora_id,ancora_sha,cursor FROM ponte_eventos WHERE origem=?',(origem,)).fetchone()
            if anterior and anterior[:3]!=(str(fonte),arquivo_id,provider):raise ValueError('Fonte ou provider mudou; confira uma nova origem explícita')
            with closing(sqlite3.connect(fonte.as_uri()+'?mode=ro',uri=True,timeout=2)) as s:
                s.execute('PRAGMA query_only=ON');s.execute('BEGIN')
                total=s.execute('SELECT COALESCE(MAX(id),0) FROM evento').fetchone()[0]
                if type(total) is not int or total<0:raise ValueError('Sequência da fonte inválida')
                ancora=s.execute('SELECT id,CASE WHEN length(dados)<=65536 THEN dados END FROM evento ORDER BY id LIMIT 1').fetchone()
                if ancora and (type(ancora[0]) is not int or not isinstance(ancora[1],str) or len(ancora[1])>65536):raise ValueError('Âncora inválida')
                aid=ancora[0] if ancora else None
                ash=hashlib.sha256(ancora[1].encode()).hexdigest() if ancora else None
                cursor=anterior[5] if anterior else total
                if anterior and (total<cursor or (anterior[3] is not None and anterior[3:5]!=(aid,ash))):raise ValueError('Fonte reiniciada ou histórico alterado; origem preservada')
                if not anterior and ultimos:
                    linhas=list(reversed(s.execute('SELECT id,CASE WHEN length(dados)<=65536 THEN dados END FROM evento ORDER BY id DESC LIMIT ?',(ultimos,)).fetchall()))
                else:linhas=s.execute('SELECT id,CASE WHEN length(dados)<=65536 THEN dados END FROM evento WHERE id>? ORDER BY id LIMIT 200',(cursor,)).fetchall()
                importados=descartados=0
                for linha,dados in linhas:
                    if type(linha) is not int or linha<=0:raise ValueError('ID de evento inválido')
                    cursor=linha
                    try:
                        if not isinstance(dados,str) or len(dados)>65536:raise ValueError('Evento acima do limite')
                        objeto=json.loads(dados)
                        if not isinstance(objeto,dict):raise ValueError('Evento inválido')
                        evento=normalizar({**objeto,'fonte':objeto.get('fonte') or provider})
                    except (ValueError,TypeError):descartados+=1;continue
                    evento['origem_escritorio']={'nome':origem,'id':linha}
                    d.execute('INSERT INTO evento (ts,agente,ferramenta,dados) VALUES (?,?,?,?)',
                        (evento['ts'],evento['agente'],evento['ferramenta'],json.dumps(evento,ensure_ascii=False)))
                    importados+=1
                if identidade(fonte)!=arquivo_id:raise ValueError('Arquivo da fonte mudou durante leitura')
            d.execute('INSERT INTO ponte_eventos VALUES (?,?,?,?,?,?,?) ON CONFLICT(origem) DO UPDATE SET ancora_id=excluded.ancora_id,ancora_sha=excluded.ancora_sha,cursor=excluded.cursor',
                (origem,str(fonte),arquivo_id,provider,aid,ash,cursor))
            d.commit()
            return {'origem':origem,'importados':importados,'descartados':descartados,'cursor':cursor,'total_fonte':total,'inicializada':anterior is None,'mais':cursor<total}
        except Exception:d.rollback();raise


def configuracao(destino):
    arquivo=Path(destino)/'dados/ponte_eventos.json'
    if not arquivo.exists():return None,None
    if arquivo.is_symlink() or getattr(arquivo.parent,'is_junction',lambda:False)() or arquivo.parent.is_symlink():raise ValueError('Configuração por link recusada')
    if not arquivo.is_file() or arquivo.stat().st_size>16384:raise ValueError('Configuração inválida')
    bruto=arquivo.read_bytes();dados=json.loads(bruto.decode('utf-8'))
    if not isinstance(dados,dict) or set(dados)!={'ativo','fontes'} or type(dados['ativo']) is not bool:raise ValueError('Configuração inválida')
    fontes=dados['fontes']
    if not isinstance(fontes,list) or len(fontes)>4 or (dados['ativo'] and not fontes):raise ValueError('Configure de uma a quatro fontes')
    nomes=set()
    for f in fontes:
        if not isinstance(f,dict) or set(f)!={'origem','fonte','provider'}:raise ValueError('Fonte inválida')
        if not isinstance(f['origem'],str) or not re.fullmatch('[a-z0-9][a-z0-9_-]{0,31}',f['origem']) or f['origem'] in nomes:raise ValueError('Origem inválida ou duplicada')
        nomes.add(f['origem'])
        if f['provider'] not in ('claude','codex','opencode','gemini'):raise ValueError('Provider inválido')
        if not isinstance(f['fonte'],str) or not 1<=len(f['fonte'])<=1024 or '\x00' in f['fonte'] or not Path(f['fonte']).is_absolute():raise ValueError('Fonte exige caminho absoluto')
    return dados,hashlib.sha256(bruto).hexdigest()


class Acompanhamento:
    def __init__(self,destino,intervalo=2):
        self.destino=Path(destino).resolve();self.intervalo=intervalo
        self.parada=threading.Event();self.lock=threading.Lock();self.thread=None
        self.dados={'estado':'desligada','fontes':[]}
        try:self.config,self.versao=configuracao(self.destino)
        except (ValueError,OSError,UnicodeError):
            self.config=None;self.versao=None;self.dados['estado']='configuracao_invalida'
        if self.config and self.config['ativo']:
            self.dados={'estado':'preparada','fontes':[{'origem':f['origem'],'estado':'aguardando','importados':0,'descartados':0} for f in self.config['fontes']]}
    def estado(self):
        with self.lock:return copy.deepcopy(self.dados)
    def iniciar(self):
        if self.thread is not None:return self
        if self.dados['estado']!='preparada':return self
        self.thread=threading.Thread(target=self._laco,daemon=True,name='ponte-eventos');self.thread.start();return self
    def _laco(self):
        ativas=set(range(len(self.config['fontes'])))
        while not self.parada.is_set() and ativas:
            try:
                _,versao=configuracao(self.destino)
                if versao!=self.versao:raise ValueError('Configuração mudou')
            except (ValueError,OSError,UnicodeError):
                with self.lock:
                    self.dados['estado']='configuracao_alterada'
                    for f in self.dados['fontes']:f['estado']='interrompida'
                return
            for i in sorted(ativas):
                if self.parada.is_set():break
                f=self.config['fontes'][i]
                try:
                    r=sincronizar(f['origem'],f['fonte'],self.destino,f['provider'])
                    with self.lock:
                        registro=self.dados['fontes'][i]
                        registro.update(estado='acompanhando',ultima_consulta=time.time(),cursor=r['cursor'])
                        registro['importados']+=r['importados'];registro['descartados']+=r['descartados']
                except (ValueError,OSError,sqlite3.Error,TypeError):
                    ativas.remove(i)
                    with self.lock:self.dados['fontes'][i]['estado']='interrompida'
            with self.lock:
                self.dados['estado']='acompanhando' if len(ativas)==len(self.config['fontes']) else 'parcial' if ativas else 'interrompida'
            self.parada.wait(self.intervalo)
        if self.parada.is_set():
            with self.lock:
                self.dados['estado']='encerrada'
                for f in self.dados['fontes']:
                    if f['estado'] in ('acompanhando','aguardando'):f['estado']='encerrada'
    def parar(self):
        self.parada.set()
        if self.thread:self.thread.join(timeout=10)
        return self.thread is None or not self.thread.is_alive()


_acompanhamento=None
def iniciar(destino):
    global _acompanhamento
    if _acompanhamento and _acompanhamento.thread and _acompanhamento.thread.is_alive():raise ValueError('Ponte já iniciada')
    _acompanhamento=Acompanhamento(destino).iniciar()
    return _acompanhamento


def estado():
    return _acompanhamento.estado() if _acompanhamento else {'estado':'nao_iniciada','fontes':[]}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--origem',required=True);p.add_argument('--fonte',required=True,type=Path)
    p.add_argument('--destino',required=True,type=Path);p.add_argument('--provider',required=True,choices=['claude','codex','opencode','gemini'])
    p.add_argument('--ultimos',type=int,default=0,help='inicializa com até 200 eventos recentes; padrão só acompanha eventos novos')
    p.add_argument('--acompanhar',action='store_true',help='repete a cada dois segundos; Ctrl+C encerra a ponte')
    a=p.parse_args(argv)
    try:
        while True:
            print(json.dumps(sincronizar(a.origem,a.fonte,a.destino,a.provider,a.ultimos),ensure_ascii=False),flush=True)
            if not a.acompanhar:return 0
            time.sleep(2)
    except KeyboardInterrupt:return 0
    except (ValueError,OSError,sqlite3.Error,TypeError):
        print('Ponte interrompida; confira origem, identidade do banco e destino. O cursor não avança se a transação falhar.')
        return 2


if __name__ == "__main__":raise SystemExit(main())
