"""Perfis derivados do cadastro; prévia e criação explícita, sem iniciar modelos."""
import argparse
import hashlib
import json
import os
import sqlite3
from pathlib import Path
import tempfile

import funcionarios
from gestao_projeto import carregar
from politica_painel import Conflito

PASTAS={'claude':('.claude/agents','md'),'codex':('.codex/agents','toml'),
        'opencode':('.opencode/agents','md'),'gemini':('.gemini/agents','md')}


def seguro(raiz,relativo):
    destino=raiz
    for parte in Path(relativo).parts:
        destino=destino/parte
        if destino.is_symlink() or getattr(destino,'is_junction',lambda:False)():
            raise ValueError('Perfil nativo não aceita links ou junctions')
        if not destino.resolve().is_relative_to(raiz):raise ValueError('Perfil fora do projeto')
    return destino


def preparar(projeto,ident):
    raiz=Path(projeto).resolve();item=funcionarios.obter(raiz,ident);cfg=carregar(raiz)
    rota=item['executor'];console=rota['console']
    if rota['execucao']!='cloud':raise ValueError('Perfil local nativo contornaria a proteção de recursos; use o despacho gerenciado')
    if console=='opencode' and not rota.get('modelo'):
        raise ValueError('Selecione modelo OpenCode explícito antes de gerar o perfil')
    from skills_compartilhados import resolver
    refs=resolver(raiz,item['skills'],cfg,console)
    origem=hashlib.sha256(json.dumps([item,cfg,refs],ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    nome='office-'+item['id'];pasta,ext=PASTAS[console];relativo=pasta+'/'+nome+'.'+ext
    destino=seguro(raiz,relativo)
    descricao=(item['nome']+' · '+item['equipe']+' · '+item['funcao'].replace('\n',' '))[:240]
    comando=f'python "{Path(__file__).resolve()}" --projeto "{raiz}" --funcionario {item["id"]} --contexto'
    corpo=('Perfil derivado do cadastro do escritório. Fonte: .office/funcionarios.db e .office/projeto.json.\n'
        'Antes de trabalhar, obtenha o contexto vigente do projeto cadastrado pelo comando abaixo. '
        'Se falhar, pare e informe o bloqueio; não use instruções antigas.\n\n'+comando+'\n\n'
        'Use o contexto retornado, as regras por escopo e as skills da fonte compartilhada. '
        'Respeite as permissões do console. Não altere o Kanban ou faça merge por conta própria.\n'
        'Versão das fontes: '+origem+'\n')
    valores={'name':nome,'description':descricao}
    if rota.get('modelo'):valores['model']=rota['modelo']
    if console=='codex':
        conteudo='\n'.join(k+' = '+json.dumps(v,ensure_ascii=False) for k,v in {**valores,'developer_instructions':corpo}.items())+'\n'
    else:
        if console=='opencode':valores.pop('name');valores['mode']='all'
        if console=='gemini':valores['kind']='local' # execução do agente no CLI; modelo continua cloud
        conteudo='---\n'+'\n'.join(k+': '+json.dumps(v,ensure_ascii=False) for k,v in valores.items())+'\n---\n\n'+corpo
    bruto=conteudo.encode('utf-8');anterior=None
    if destino.exists():
        if not destino.is_file() or destino.stat().st_size>131072:raise ValueError('Arquivo de perfil inválido ou acima de 128 KiB')
        anterior=destino.read_bytes()
    estado='ausente' if anterior is None else 'atual' if anterior==bruto else 'divergente'
    versao=hashlib.sha256(json.dumps([str(raiz),relativo,origem,hashlib.sha256(bruto).hexdigest(),
        None if anterior is None else hashlib.sha256(anterior).hexdigest()],ensure_ascii=False).encode()).hexdigest()
    return {'console':console,'nome':nome,'arquivo':relativo,'conteudo':conteudo,'estado':estado,
            'confirmacao':versao,'limite':'Perfil não inicia inferência, não altera permissões e não comprova descoberta pela versão instalada.'}


def resumo(projeto,ident):
    """Estado derivado, sem conteúdo/comandos e sem criar arquivos ou chamar CLI."""
    try:
        item=funcionarios.obter(projeto,ident)
        if item['executor']['execucao']=='local':
            return {'estado':'gerenciado'}
        plano=preparar(projeto,ident)
        return {k:plano[k] for k in ('estado','console','arquivo')}
    except (ValueError,OSError,TypeError,KeyError,sqlite3.Error):
        return {'estado':'indisponivel'}


def aplicar(projeto,ident,confirmacao):
    raiz=Path(projeto).resolve();plano=preparar(raiz,ident)
    if not isinstance(confirmacao,str) or confirmacao!=plano['confirmacao']:raise Conflito('Prévia mudou; confira novamente')
    if plano['estado']=='divergente':raise Conflito('Perfil existente diverge; arquivo preservado')
    if plano['estado']=='atual':return {**plano,'criado':False}
    lock=seguro(raiz,'.office/perfis-nativos.lock');temporario=None
    try:
        with lock.open('x',encoding='utf-8') as f:f.write(str(os.getpid()))
    except FileExistsError as exc:raise Conflito('Outra geração está em andamento; confira no PC') from exc
    try:
        if preparar(raiz,ident)!=plano:raise Conflito('Fontes mudaram antes da geração')
        destino=seguro(raiz,plano['arquivo']);destino.parent.mkdir(parents=True,exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=destino.parent,prefix='.office-native-',suffix='.tmp',delete=False) as f:
            temporario=Path(f.name);f.write(plano['conteudo'].encode('utf-8'));f.flush();os.fsync(f.fileno())
        if preparar(raiz,ident)!=plano:raise Conflito('Fontes mudaram durante a geração')
        destino=seguro(raiz,plano['arquivo'])
        try:os.link(temporario,destino) # publicação exclusiva: nunca substitui arquivo existente
        except FileExistsError as exc:raise Conflito('Perfil apareceu durante a geração; arquivo preservado') from exc
        return {**plano,'estado':'atual','criado':True}
    finally:
        if temporario is not None:temporario.unlink(missing_ok=True)
        lock.unlink()


def contexto(projeto,ident):
    plano=preparar(projeto,ident)
    if plano['estado']!='atual':raise Conflito('Perfil ausente ou desatualizado; confira a prévia no escritório')
    texto=funcionarios.contexto(projeto,funcionarios.obter(projeto,ident))
    if preparar(projeto,ident)!=plano:raise Conflito('Fontes mudaram durante a leitura do contexto')
    return texto


def api(projetos,dados,identidade):
    if identidade.get('permissao')!='pc':return 403,{'erro':'Geração de perfil permitida somente no PC'}
    projeto=next((p for p in projetos if funcionarios.id_projeto(p)==dados.get('projeto_id')),None)
    if projeto is None:return 400,{'erro':'Projeto não cadastrado'}
    if set(dados)-{'projeto_id','funcionario_id','confirmacao','aplicar'} or type(dados.get('aplicar',False)) is not bool:
        return 400,{'erro':'Pedido de perfil inválido'}
    try:
        if dados.get('aplicar'):return 200,aplicar(projeto,dados.get('funcionario_id'),dados.get('confirmacao'))
        return 200,preparar(projeto,dados.get('funcionario_id'))
    except Conflito as exc:return 409,{'erro':str(exc)}
    except (ValueError,OSError,TypeError,sqlite3.Error):return 400,{'erro':'Não foi possível preparar/criar o perfil; confira cadastro, fontes e arquivos no PC'}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--projeto',type=Path,required=True);p.add_argument('--funcionario',required=True)
    p.add_argument('--confirmacao');acao=p.add_mutually_exclusive_group()
    acao.add_argument('--aplicar',action='store_true');acao.add_argument('--contexto',action='store_true')
    a=p.parse_args(argv)
    try:
        if a.contexto:print(contexto(a.projeto,a.funcionario))
        else:print(json.dumps(aplicar(a.projeto,a.funcionario,a.confirmacao) if a.aplicar else preparar(a.projeto,a.funcionario),ensure_ascii=False,indent=2))
        return 0
    except (ValueError,OSError,TypeError,sqlite3.Error) as exc:print(str(exc));return 1


if __name__ == "__main__":raise SystemExit(main())
