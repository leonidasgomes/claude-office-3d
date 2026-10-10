"""Edição explícita de executores/merge na fonte única, sem executar agentes ou GitHub."""
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from funcionarios import id_projeto
from gestao_projeto import carregar, validar


class Conflito(ValueError): pass


def snapshot(projeto):
    raiz=Path(projeto).resolve(); caminho=raiz/'.office/projeto.json'
    if not caminho.exists(): return carregar(raiz),None,None
    if caminho.is_symlink() or not caminho.resolve().is_relative_to(raiz):
        raise ValueError('Política deve ser arquivo próprio dentro do projeto')
    with caminho.open('rb') as f: bruto=f.read(131073)
    if len(bruto)>131072: raise ValueError('Política excede 128 KiB')
    cfg=validar(json.loads(bruto.decode('utf-8-sig')))
    return cfg,hashlib.sha256(bruto).hexdigest(),bruto


def atualizar(projeto,versao,alteracoes):
    raiz=Path(projeto).resolve();cfg,hash_atual,bruto=snapshot(raiz)
    if not isinstance(versao,str) or not re.fullmatch('[0-9a-f]{64}',versao) or versao!=hash_atual:
        raise Conflito('Política mudou; recarregue o painel antes de salvar')
    if not cfg['ativo']: raise ValueError('Adote a gestão pelo assistente antes de editar executores')
    if not isinstance(alteracoes,dict) or set(alteracoes)!={'ceo','diretor','equipes'}:
        raise ValueError('Informe apenas CEO, diretor e executores das equipes')
    novo=copy.deepcopy(cfg)
    for papel in ('ceo','diretor'):
        e=alteracoes[papel]
        if not isinstance(e,dict) or set(e)-{'console','modelo','execucao','cloud'}:
            raise ValueError('Executor de papel inválido')
        if e.get('execucao','cloud')!='cloud': raise ValueError('CEO e diretor devem usar cloud no painel')
        novo[papel]={**e,**({'autonomia':'limites_aprovados'} if papel=='ceo' else {})}
    equipes=alteracoes['equipes']
    if not isinstance(equipes,list) or len(equipes)!=len(cfg['equipes']):
        raise ValueError('O formulário deve preservar as equipes existentes')
    vistos=set()
    for item in equipes:
        if not isinstance(item,dict) or set(item)!={'nome','executor'} or not isinstance(item['nome'],str):
            raise ValueError('Equipe inválida')
        equipe=next((e for e in novo['equipes'] if e['nome']==item['nome']),None)
        if equipe is None or item['nome'] in vistos: raise ValueError('Equipe desconhecida ou repetida')
        vistos.add(item['nome']);equipe['executor']=copy.deepcopy(item['executor'])
    novo=validar(novo)
    for e in [novo['ceo'],novo['diretor']]+[x['executor'] for x in novo['equipes']]:
        if e.get('execucao','cloud')=='local':
            if not novo['local']['ativo']: raise ValueError('Execução local está desativada')
        if len(e.get('modelo',''))>200: raise ValueError('Modelo excede 200 caracteres')
    return gravar(raiz,cfg,hash_atual,bruto,novo)


def gravar(raiz,cfg,hash_atual,bruto,novo):
    if novo==cfg: return {'versao':hash_atual,'alterado':False}
    conteudo=(json.dumps(novo,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    if len(conteudo)>131072:raise ValueError('Política excede 128 KiB após edição')
    pasta=raiz/'.office';lock=pasta/'politica.edicao.lock';tmp=None
    try:
        with lock.open('x',encoding='utf-8') as f: f.write(str(os.getpid()))
    except FileExistsError as exc: raise Conflito('Outra edição está em andamento; confira no PC') from exc
    try:
        if snapshot(raiz)[1]!=hash_atual: raise Conflito('Política mudou antes da gravação; recarregue')
        historico=pasta/'historico-politica'
        if not historico.resolve().is_relative_to(raiz): raise ValueError('Histórico fora do projeto')
        historico.mkdir(exist_ok=True)
        backup=historico/(hash_atual+'.json')
        try:
            with backup.open('xb') as f: f.write(bruto)
        except FileExistsError:
            if backup.is_symlink() or backup.read_bytes()!=bruto: raise ValueError('Cópia anterior inconsistente')
        with tempfile.NamedTemporaryFile(dir=pasta,prefix='politica-',suffix='.tmp',delete=False) as f:
            tmp=Path(f.name);f.write(conteudo);f.flush();os.fsync(f.fileno())
        if snapshot(raiz)[1]!=hash_atual: raise Conflito('Política mudou durante a edição; recarregue')
        os.replace(tmp,pasta/'projeto.json');tmp=None
        return {'versao':hashlib.sha256(conteudo).hexdigest(),'alterado':True}
    finally:
        if tmp: tmp.unlink(missing_ok=True)
        lock.unlink(missing_ok=True)


def api_atualizar(projetos,dados,ident):
    if ident.get('permissao')!='pc': return 403,{'erro':'Política editável somente no PC'}
    if not isinstance(dados,dict) or set(dados)-{'projeto_id','versao','executores'}:
        return 400,{'erro':'Pedido inválido'}
    projeto=next((p for p in projetos if id_projeto(p)==dados.get('projeto_id')),None)
    if projeto is None: return 400,{'erro':'Projeto não configurado no escritório'}
    try: return 200,atualizar(projeto,dados.get('versao'),dados.get('executores'))
    except Conflito as exc: return 409,{'erro':str(exc)}
    except (ValueError,OSError,TypeError,KeyError): return 400,{'erro':'Não foi possível validar/salvar a política; confira no PC'}


def atualizar_merge(projeto,versao,merge):
    raiz=Path(projeto).resolve();cfg,atual,bruto=snapshot(raiz)
    if not isinstance(versao,str) or not re.fullmatch('[0-9a-f]{64}',versao) or versao!=atual:
        raise Conflito('Política mudou; recarregue o painel antes de salvar')
    if not cfg['ativo']:raise ValueError('Adote a gestão antes de editar o merge')
    if not isinstance(merge,dict) or set(merge)!={'modo','checks','rotulos_manuais'}:
        raise ValueError('Informe somente a política de merge')
    for chave in ('checks','rotulos_manuais'):
        valores=merge[chave]
        if (not isinstance(valores,list) or len(valores)>100 or any(not isinstance(v,str) or not v.strip() or len(v)>200 for v in valores)
            or len(set(valores))!=len(valores)):
            raise ValueError('Nomes de checks/rótulos inválidos ou repetidos')
    novo=copy.deepcopy(cfg);novo['merge']=copy.deepcopy(merge);novo=validar(novo)
    return gravar(raiz,cfg,atual,bruto,novo)


def api_merge(projetos,dados,ident):
    if ident.get('permissao')!='pc':return 403,{'erro':'Política editável somente no PC'}
    if not isinstance(dados,dict) or set(dados)!={'projeto_id','versao','merge'}:return 400,{'erro':'Pedido inválido'}
    projeto=next((p for p in projetos if id_projeto(p)==dados['projeto_id']),None)
    if projeto is None:return 400,{'erro':'Projeto não configurado no escritório'}
    try:return 200,atualizar_merge(projeto,dados['versao'],dados['merge'])
    except Conflito as exc:return 409,{'erro':str(exc)}
    except (ValueError,OSError,TypeError,KeyError):return 400,{'erro':'Não foi possível validar/salvar o merge; confira modo, checks e rótulos no PC'}
