"""Especialistas por projeto. Cadastro não inicia modelos nem sobrescreve agentes nativos."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import uuid

from gestao_projeto import carregar, validar


def id_projeto(projeto):
    return hashlib.sha256(str(Path(projeto).resolve()).encode()).hexdigest()[:20]


def nome_eventos(item):
    """Identidade estável evita colisão com Dev/CEO e com outro projeto."""
    if not re.fullmatch('[0-9a-f]{32}',item.get('id','')): raise ValueError('ID de funcionário inválido')
    return 'Office_'+item['id']


def arquivo(projeto):
    raiz=Path(projeto).resolve(); pasta=(raiz/'.office').resolve()
    if not pasta.is_relative_to(raiz): raise ValueError('Pasta de gestão fora do projeto')
    destino=pasta/'funcionarios.db'
    if destino.is_symlink(): raise ValueError('Banco do cadastro não pode ser link')
    return destino


def skills(projeto, cfg):
    from skills_compartilhados import catalogo
    from compatibilidade_skills import diagnostico
    return [{'nome':s['nome'],'descricao':s['descricao'],
             'compatibilidade':{**{p:diagnostico(s,p) for p in ('claude','codex','opencode','gemini')},
                                **{p+'_local':diagnostico(s,p,True) for p in ('claude','codex','opencode','gemini')}}} for s in catalogo(projeto,cfg)
            if not s['problemas']]


def listar(projeto):
    arq=arquivo(projeto)
    if not arq.is_file(): return []
    with closing(sqlite3.connect(arq.as_uri()+'?mode=ro',uri=True,timeout=5)) as db:
        return [json.loads(x[0]) for x in db.execute('SELECT dados FROM funcionario ORDER BY nome')]


def cadastrar(projeto, dados):
    cfg=carregar(projeto)
    if not cfg['ativo']: raise ValueError('Habilite a política do projeto antes de cadastrar especialistas')
    if not isinstance(dados,dict) or set(dados) != {'nome','funcao','equipe','executor','skills'}:
        raise ValueError('Informe nome, função, equipe, executor e skills')
    for campo,limite in (('nome',64),('funcao',2000),('equipe',64)):
        valor=dados[campo]
        if not isinstance(valor,str) or not valor.strip() or len(valor)>limite or '\x00' in valor:
            raise ValueError('Campo de cadastro inválido: '+campo)
    if dados['equipe'] not in {e['nome'] for e in cfg['equipes']}:
        raise ValueError('Equipe não existe na política do projeto')
    normal=validar({'diretor':dados['executor']})['diretor']
    if normal['execucao'] == 'local' and normal['console'] == 'gemini':
        raise ValueError('Gemini não oferece adapter local neste escritório')
    if normal.get('execucao','cloud') == 'local' and not cfg['local']['ativo']:
        raise ValueError('Execução local está desativada no projeto')
    disponiveis={s['nome'] for s in skills(projeto,cfg)}
    if not isinstance(dados['skills'],list) or any(not isinstance(s,str) or s not in disponiveis for s in dados['skills']):
        raise ValueError('Skill desconhecida na fonte compartilhada')
    from skills_compartilhados import resolver
    resolver(projeto,dados['skills'],cfg,normal['console'],normal['execucao']=='local')
    item={**dados,'id':uuid.uuid4().hex,'nome':dados['nome'].strip(),'executor':normal,'skills':sorted(set(dados['skills']))}
    arq=arquivo(projeto); arq.parent.mkdir(parents=True,exist_ok=True)
    with closing(sqlite3.connect(arq,timeout=5)) as db,db:
        db.execute('CREATE TABLE IF NOT EXISTS funcionario (id TEXT PRIMARY KEY,nome TEXT UNIQUE,dados TEXT NOT NULL)')
        try:
            db.execute('INSERT INTO funcionario VALUES (?,?,?)',(item['id'],item['nome'].casefold(),json.dumps(item,ensure_ascii=False)))
        except sqlite3.IntegrityError as exc:
            raise ValueError('Já existe funcionário com este nome no projeto') from exc
    return item


def obter(projeto, ident):
    item=next((x for x in listar(projeto) if x['id']==ident),None)
    if not item: raise ValueError('Funcionário não encontrado neste projeto')
    cfg=carregar(projeto)
    item['executor']=validar({'diretor':item['executor']})['diretor']
    if item['executor']['execucao'] == 'local' and not cfg['local']['ativo']:
        raise ValueError('Execução local está desativada no projeto')
    if not cfg['ativo'] or item['equipe'] not in {e['nome'] for e in cfg['equipes']}:
        raise ValueError('Projeto/equipe não está habilitado')
    if set(item['skills'])-{s['nome'] for s in skills(projeto,cfg)}:
        raise ValueError('Uma skill do funcionário não está mais disponível')
    from skills_compartilhados import resolver
    resolver(projeto,item['skills'],cfg,item['executor']['console'],item['executor']['execucao']=='local')
    return item


def contexto(projeto, item):
    from gestao_projeto import contexto as regras
    from skills_compartilhados import resolver, instrucoes_ativacao
    cfg=carregar(projeto)
    refs=resolver(projeto,item['skills'],cfg,item['executor']['console'],item['executor']['execucao']=='local')
    caminhos=[str(Path(cfg['fontes']['skills'])/s/'SKILL.md') for s in item['skills']]
    return (regras(projeto,cfg,equipe=item['equipe'])+'\n\nEspecialista: '+item['nome']+
            '\nFunção: '+item['funcao']+'\nSkills da fonte compartilhada: '+', '.join(caminhos)+
            instrucoes_ativacao(refs)+
            '\nRespeite as permissões nativas do console e a política do projeto. Não faça merge direto.')


def executor(projeto, ident, equipe, escopo):
    """Resolve membro na fonte canônica; escopos locais mantêm as mesmas restrições."""
    from gestao_projeto import executor as rota_projeto
    item=obter(projeto,ident)
    if item['equipe'] != equipe:
        raise ValueError('Funcionário pertence a outra equipe')
    cfg=carregar(projeto)
    # Valida equipe, política ativa e capacidades do escopo com o executor escolhido.
    configuracao={**cfg,'rotas':{**cfg['rotas'],escopo:item['executor']}}
    return item,rota_projeto(configuracao,equipe=equipe,escopo=escopo)


def api_cadastrar(projetos,dados,ident):
    if ident.get('permissao') != 'pc': return 403,{'erro':'Cadastro permitido somente no PC'}
    projeto=next((p for p in projetos if id_projeto(p)==dados.get('projeto_id')),None)
    if projeto is None: return 400,{'erro':'Projeto não configurado no escritório'}
    try:
        return 201,{'funcionario':cadastrar(projeto,dados.get('funcionario'))}
    except (ValueError,OSError,sqlite3.Error) as exc:
        return 400,{'erro':str(exc) if isinstance(exc,ValueError) else 'Não foi possível salvar o cadastro'}


def rotular_consumo(projetos, consumo):
    nomes={}
    for projeto in projetos:
        try:
            for f in listar(projeto): nomes[nome_eventos(f)]=f['nome']+' · '+Path(projeto).name
        except (ValueError,OSError,sqlite3.Error,TypeError,KeyError): continue
    for grupo in consumo.get('grupos',[]):
        if grupo.get('agente') in nomes: grupo['agente_nome']=nomes[grupo['agente']]
    return consumo
