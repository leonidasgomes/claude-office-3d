"""Pré-requisitos locais; não inicia consoles, consulta contas ou instala software."""
import shutil
import socket
import sys
from providers_console import PROVIDERS, comando_nativo
from gestao_projeto import validar

FONTES={
    'python':'https://www.python.org/downloads/',
    'git':'https://git-scm.com/downloads',
    'gh':'https://cli.github.com/',
    'claude':'https://code.claude.com/docs/en/quickstart',
    'codex':'https://developers.openai.com/codex/cli/',
    'gemini':'https://geminicli.com/docs/get-started/installation/',
    'opencode':'https://opencode.ai/docs/',
    'ollama':'https://ollama.com/download',
}


def porta_disponivel(porta):
    try:
        with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as s:
            if hasattr(socket,'SO_EXCLUSIVEADDRUSE'):s.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
            s.bind(('127.0.0.1',porta))
        return True
    except OSError:return False


def verificar(politica,porta=8765):
    cfg=validar(politica)
    if type(porta) is not int or not 1024<=porta<=65535:raise ValueError('Porta inválida')
    itens=[]
    def adicionar(nome,ok,obrigatorio,motivo):
        itens.append({'nome':nome,'disponivel':bool(ok),'obrigatorio':obrigatorio,
                      'evidencia':motivo,'documentacao':FONTES.get(nome,'')})
    adicionar('python',sys.version_info>=(3,9),True,'Versão do interpretador atual: '+'.'.join(map(str,sys.version_info[:3])))
    for nome in ('sqlite3','ssl'):
        try:__import__(nome);ok=True
        except ImportError:ok=False
        adicionar(nome,ok,True,'Importação da biblioteca padrão; não consulta rede ou arquivos de conta')
    adicionar('porta',porta_disponivel(porta),True,f'Bind temporário em 127.0.0.1:{porta}; disponibilidade pode mudar')
    for nome in ('git','gh'):
        adicionar(nome,shutil.which(nome) is not None,cfg['ativo'],'Executável no PATH; versão, login e acesso ao repo não verificados')
    rotas=[cfg['ceo'],cfg['diretor']]+[e['executor'] for e in cfg['equipes']]+list(cfg['rotas'].values())
    if cfg['revisao']['ativo']:rotas+=[r['executor'] for r in cfg['revisao']['revisores'] if r.get('ativo',True)]
    usados={e['console'] for e in rotas} if cfg['ativo'] else set()
    for nome in PROVIDERS:
        caminho=shutil.which(nome);ok=False;motivo='Executável ausente no PATH'
        if caminho:
            try:comando_nativo(caminho,nome);ok=True;motivo='Executável/adapter local resolvido; comando não executado'
            except ValueError:motivo='Shim encontrado, mas adapter não resolve executável nativo; confira instalação e Node no PATH'
        adicionar(nome,ok,nome in usados,motivo)
    if cfg['ativo'] and any(e.get('execucao')=='local' for e in rotas):
        adicionar('ollama',shutil.which('ollama') is not None,True,
                  'Executável no PATH; serviço, modelo instalado e recursos não verificados')
    faltam=[i['nome'] for i in itens if i['obrigatorio'] and not i['disponivel']]
    return {'requisitos_locais_disponiveis':not faltam,'faltam':faltam,'itens':itens,
            'autenticacao':'não verificada','inferencias':'não executadas',
            'limite':'Não comprova versão/capacidades nativas, login, cotas, modelo cloud gratuito ou acesso ao Kanban. Não instala software nem baixa modelos.'}
