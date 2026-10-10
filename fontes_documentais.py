"""Inventário limitado de fontes/referências; não interpreta nem executa instruções."""
from pathlib import Path
import re
from gestao_projeto import validar

LIMITE=131072

def arquivo(raiz,relativo):
    caminho=raiz/relativo
    if not caminho.resolve().is_relative_to(raiz) or caminho.is_symlink():return 'fora_projeto',None
    if not caminho.exists():return 'ausente',None
    if not caminho.is_file():return 'tipo_invalido',None
    try:
        with caminho.open('rb') as f:bruto=f.read(LIMITE+1)
        if len(bruto)>LIMITE:return 'acima_limite',None
        return 'presente',bruto.decode('utf-8-sig')
    except (OSError,UnicodeError):return 'ilegivel',None

def resumo(projeto,cfg):
    raiz=Path(projeto).resolve();cfg=validar(cfg);fontes=[];wrappers=[]
    for papel in ('regras','produto','arquitetura'):
        relativo=cfg['fontes'][papel]
        try:estado,_=arquivo(raiz,relativo)
        except OSError:estado='ilegivel'
        fontes.append({'papel':papel,'caminho':relativo,'estado':estado})
    rotas=[cfg['ceo'],cfg['diretor']]+[e['executor'] for e in cfg['equipes']]+list(cfg['rotas'].values())
    if cfg['revisao']['ativo']:rotas += [r['executor'] for r in cfg['revisao']['revisores'] if r.get('ativo',True)]
    usados={e['console'] for e in rotas} if cfg['ativo'] else set()
    regra=cfg['fontes']['regras'].replace('\\','/')
    for nome,consoles in [('CLAUDE.md',['claude']),('AGENTS.md',['codex','opencode']),('GEMINI.md',['gemini'])]:
        try:estado,texto=arquivo(raiz,nome)
        except OSError:estado,texto='ilegivel',None
        autoridade=nome==regra
        # Menção literal limitada: nunca equivale a importação efetiva ou consenso.
        citado=bool(texto is not None and re.search(r'(?<![\w./-])(?:@?\./)?'+re.escape(regra)+r'(?![\w./-])',texto.replace('\\','/')))
        wrappers.append({'arquivo':nome,'consoles':consoles,'necessario':bool(usados.intersection(consoles)),
                         'estado':estado,'fonte_regras':autoridade,'cita_regras':citado})
    return {'fontes':fontes,'instrucoes_consoles':wrappers,'semantica':'não verificada',
            'limite':'Presença e menção textual não comprovam concordância das regras nem carregamento pelo console. Skills têm diagnóstico separado.'}
