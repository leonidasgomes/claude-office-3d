"""Edição de equipes e funcionários, sem iniciar agentes nem alterar o Kanban."""
import copy
import json
import sqlite3
from contextlib import closing
from pathlib import Path

import funcionarios
from gestao_projeto import validar
from politica_painel import Conflito, snapshot, gravar


def conferir_politica(projeto, versao):
    cfg, atual, bruto = snapshot(projeto)
    if not versao or versao != atual:
        raise Conflito('A configuração mudou. Atualize a Gestão e tente novamente.')
    if not cfg['ativo']:
        raise ValueError('Habilite a gestão do projeto antes de editar cadastros.')
    return cfg, atual, bruto


def conferir_tarefas(projeto, cfg, equipe=None, funcionario=None):
    from gestao_cli import pasta_dados
    banco = pasta_dados(projeto) / 'tarefas.db'
    if not banco.exists():
        return
    with closing(sqlite3.connect(banco.resolve().as_uri()+'?mode=ro', uri=True, timeout=5)) as db:
        for time, pacote in db.execute("SELECT equipe,pacote FROM reserva WHERE projeto=? AND estado NOT IN ('cancelado','concluido')", (cfg['kanban']['repo'],)):
            membro = (json.loads(pacote).get('funcionario') or {}).get('id')
            if (equipe is not None and time == equipe) or (funcionario is not None and membro == funcionario):
                raise ValueError('Há tarefa pendente vinculada a este cadastro. Conclua ou concilie a tarefa antes de alterar ou excluir.')


def equipe(projeto, dados):
    cfg, atual, bruto = conferir_politica(projeto, dados['versao'])
    acao = dados['acao']
    novo = copy.deepcopy(cfg)
    if acao == 'criar':
        item = dados.get('equipe')
        novo['equipes'].append(item)
    elif acao in ('editar', 'excluir'):
        nome = dados.get('nome')
        item = next((e for e in novo['equipes'] if e['nome'] == nome), None)
        if item is None:
            raise ValueError('Equipe não encontrada neste projeto.')
        conferir_tarefas(projeto, cfg, equipe=nome)
        if acao == 'editar':
            substituto = dados.get('equipe')
            if not isinstance(substituto, dict) or substituto.get('nome') != nome:
                raise ValueError('O nome da equipe é usado no Kanban e deve ser preservado.')
            novo['equipes'][novo['equipes'].index(item)] = substituto
        else:
            if any(f['equipe'] == nome for f in funcionarios.listar(projeto)):
                raise ValueError('Transfira ou exclua os funcionários desta equipe primeiro.')
            if cfg['kanban']['repo']:
                from kanban_gestao import Kanban
                from gestao_cli import pasta_dados
                k = Kanban(cfg, pasta_dados(projeto)/'kanban.json', sem_escrita=True)
                if any(c['equipe'] == nome and c['status'] != cfg['kanban']['feito'] for c in k.cartoes(ao_vivo=True)):
                    raise ValueError('Existem cartões pendentes desta equipe no Kanban. Resolva os vínculos antes de excluir.')
            novo['equipes'].remove(item)
    else:
        raise ValueError('Ação de equipe inválida.')
    novo = validar(novo)
    for e in novo['equipes']:
        if len(e['nome']) > 64 or len(e['especialidade']) > 2000 or len(e['executor'].get('modelo','')) > 200:
            raise ValueError('Nome, especialidade ou modelo excede o limite.')
        if e['executor'].get('execucao','cloud') == 'local' and not novo['local']['ativo']:
            raise ValueError('Execução local está desativada neste projeto.')
        if e['executor'].get('execucao','cloud') == 'local' and e['executor']['console'] == 'gemini':
            raise ValueError('Gemini não oferece adapter local neste escritório.')
    return gravar(Path(projeto).resolve(), cfg, atual, bruto, novo)


def funcionario(projeto, dados):
    cfg, versao, _ = conferir_politica(projeto, dados['versao'])
    ident = dados.get('id')
    anterior = dados.get('anterior')
    if isinstance(anterior,dict):
        # O painel acrescenta esta projeção de leitura; ela não pertence ao cadastro.
        anterior = {k:v for k,v in anterior.items() if k != 'perfil_nativo'}
    conferir_tarefas(projeto, cfg, funcionario=ident)
    if dados['acao'] == 'editar':
        novo = {**funcionarios.validar_cadastro(projeto, dados.get('funcionario')), 'id':ident}
    elif dados['acao'] == 'excluir':
        if not isinstance(anterior,dict):
            raise ValueError('Cadastro anterior ausente. Atualize a Gestão.')
        novo = {**anterior, 'arquivado':True}
    else:
        raise ValueError('Ação de funcionário inválida.')
    arq = funcionarios.arquivo(projeto)
    if not arq.exists():
        raise ValueError('Funcionário não encontrado neste projeto.')
    with closing(sqlite3.connect(arq, timeout=5)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT dados FROM funcionario WHERE id=?', (ident,)).fetchone()
        if not row or json.loads(row[0]).get('arquivado'):
            raise ValueError('Funcionário não encontrado neste projeto.')
        if json.loads(row[0]) != anterior:
            raise Conflito('O funcionário foi alterado. Atualize a Gestão antes de salvar.')
        conferir_politica(projeto, versao)
        conferir_tarefas(projeto, cfg, funcionario=ident)
        db.execute('CREATE TABLE IF NOT EXISTS funcionario_historico (id INTEGER PRIMARY KEY, funcionario TEXT NOT NULL, anterior TEXT NOT NULL, acao TEXT NOT NULL)')
        db.execute('INSERT INTO funcionario_historico (funcionario,anterior,acao) VALUES (?,?,?)', (ident,row[0],dados['acao']))
        try:
            chave_nome = 'arquivado:'+ident if dados['acao']=='excluir' else novo['nome'].casefold()
            db.execute('UPDATE funcionario SET nome=?,dados=? WHERE id=?', (chave_nome,json.dumps(novo,ensure_ascii=False),ident))
        except sqlite3.IntegrityError as exc:
            raise ValueError('Já existe funcionário com este nome. Escolha outro nome.') from exc
    return {'alterado':True, 'funcionario':novo}


def api(projetos, dados, ident):
    if ident.get('permissao') != 'pc':
        return 403, {'erro':'Cadastros podem ser alterados somente no PC.'}
    if not isinstance(dados,dict) or set(dados)-{'projeto_id','versao','tipo','acao','nome','equipe','id','anterior','funcionario'}:
        return 400, {'erro':'Pedido de cadastro inválido.'}
    projeto = next((p for p in projetos if funcionarios.id_projeto(p) == dados.get('projeto_id')), None)
    if projeto is None:
        return 400, {'erro':'Projeto não configurado no escritório.'}
    try:
        if dados.get('tipo') not in ('equipe','funcionario'):
            raise ValueError('Tipo de cadastro inválido.')
        return 200, (equipe if dados['tipo']=='equipe' else funcionario)(projeto,dados)
    except Conflito as exc:
        return 409, {'erro':str(exc)}
    except ValueError as exc:
        return 400, {'erro':str(exc)}
    except (OSError, sqlite3.Error, TypeError, KeyError):
        return 400, {'erro':'Não foi possível salvar. Atualize a Gestão e confira a configuração no PC.'}
