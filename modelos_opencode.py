"""Catálogo consultivo local: metadados zero, sem inferência ou fallback."""
from pathlib import Path
import copy,json,math,re,shutil,subprocess,tempfile,threading,time
from providers_console import comando_nativo

LIMITE=2*1024*1024


def pares_unicos(pares):
    obj={}
    for chave,valor in pares:
        if chave in obj:raise ValueError('Campo duplicado no catálogo')
        obj[chave]=valor
    return obj


def normalizar(texto):
    if not isinstance(texto,str) or len(texto.encode('utf-8'))>LIMITE:raise ValueError('Catálogo excede limite')
    pos=0;modelos=[];vistos=set();decoder=json.JSONDecoder(object_pairs_hook=pares_unicos)
    while texto[pos:].strip():
        pos+=len(texto[pos:])-len(texto[pos:].lstrip())
        cab=re.match(r'opencode/([A-Za-z0-9_.-]{1,150})\r?\n',texto[pos:])
        if not cab:raise ValueError('Formato de catálogo desconhecido')
        ident=cab.group(1);pos+=cab.end()
        obj,fim=decoder.raw_decode(texto,pos);pos=fim
        if not isinstance(obj,dict) or obj.get('id')!=ident or obj.get('providerID')!='opencode' or ident in vistos:
            raise ValueError('Identidade de modelo inconsistente')
        vistos.add(ident)
        if len(vistos)>500:raise ValueError('Catálogo excede limite')
        # Metadados de extensões/provedores personalizados não são Zen oficial.
        api=obj.get('api') or {}
        if not isinstance(api,dict):raise ValueError('Metadados de API inválidos')
        if api.get('url')!='https://opencode.ai/zen/v1' or obj.get('status')!='active':continue
        custo=obj.get('cost')
        if not isinstance(custo,dict):continue
        cache=custo.get('cache')
        if (not isinstance(cache,dict)
            or set(custo)!={'input','output','cache'} or set(cache)!={'read','write'}):continue
        valores=[custo.get('input'),custo.get('output'),cache.get('read'),cache.get('write')]
        if not all(type(v) in (int,float) and math.isfinite(v) and v==0 for v in valores):continue
        capacidades=obj.get('capabilities') or {}
        if not isinstance(capacidades,dict):raise ValueError('Capacidades inválidas')
        if capacidades.get('toolcall') is not True:continue
        nome=obj.get('name')
        if not isinstance(nome,str) or not 1<=len(nome)<=200:raise ValueError('Nome de modelo inválido')
        modelos.append({'id':'opencode/'+ident,'nome':nome,'custo_declarado_zero':True,
                        'toolcall_declarado':True,'fornecedor_real':'não atestado'})
    return sorted(modelos,key=lambda m:m['id'])


def consultar():
    exe=shutil.which('opencode')
    if not exe:raise ValueError('OpenCode não encontrado')
    comando=comando_nativo(exe,'opencode')+['models','opencode','--verbose','--pure']
    with tempfile.TemporaryFile() as saida,tempfile.TemporaryFile() as erro:
        r=subprocess.run(comando,cwd=Path(__file__).resolve().parent,stdout=saida,stderr=erro,timeout=20)
        if r.returncode:raise ValueError('Consulta nativa de modelos falhou')
        saida.seek(0);dados=saida.read(LIMITE+1)
        if len(dados)>LIMITE:raise ValueError('Catálogo excede limite')
        return normalizar(dados.decode('utf-8'))


class Catalogo:
    def __init__(self):self.lock=threading.Lock();self.valor=None;self.validade=0
    def obter(self):
        if not self.lock.acquire(blocking=False):
            return {'ok':False,'erro':'Consulta de modelos já em andamento; tente novamente','modelos':[]}
        try:
            if self.valor is not None and time.monotonic()<self.validade:return copy.deepcopy(self.valor)
            try:
                modelos=consultar()
                self.valor={'ok':True,'console':'opencode','fonte':'CLI models opencode --verbose --pure',
                    'consultado_em':time.time(),'modelos':modelos,
                    'limite':'Custos declarados pelo CLI/cache local, sem garantia da tarifa atual, disponibilidade, login ou fornecedor real. Sem inferência e sem fallback.'}
                self.validade=time.monotonic()+300
                return copy.deepcopy(self.valor)
            except (OSError,ValueError,TypeError,AttributeError,subprocess.SubprocessError):
                return {'ok':False,'erro':'Catálogo OpenCode indisponível; confira o CLI no PC','modelos':[]}
        finally:self.lock.release()


CATALOGO=Catalogo()


def api(dados,ident):
    if ident.get('permissao')!='pc':return 403,{'ok':False,'erro':'Consulta de catálogo exige o PC'}
    if not isinstance(dados,dict) or dados!={'console':'opencode'}:
        return 400,{'ok':False,'erro':'Escolha o catálogo OpenCode'}
    resultado=CATALOGO.obter()
    return (200 if resultado['ok'] else 503),resultado
