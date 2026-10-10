"""Inferência isolada sem ferramentas; revisão padrão ou resposta normalizada pelo chamador."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import uuid

from providers_console import selecionar, comando_nativo
from revisao_cruzada import normalizar

MOTIVOS_FALHA={
    'cliente_nao_suportado':'O fornecedor recusou este cliente. Confira os clientes e métodos de autenticação suportados.',
    'workspace_nao_confiavel':'O console recusou o contexto da revisão por falta de confiança.',
    'limite_ou_credito':'O fornecedor informou limite ou crédito indisponível.',
    'autenticacao_indisponivel':'O console não conseguiu autenticar a revisão.',
    'acesso_recusado':'O servidor recusou acesso ao modelo (HTTP 403). Confira disponibilidade e permissões no console; presença no catálogo gratuito não comprova acesso.',
    'console_falhou':'O console não completou a revisão.',
}


class FalhaRevisor(RuntimeError):
    """Diagnóstico enumerado, sem stderr, credenciais ou caminhos do console."""
    def __init__(self,codigo,motivo):
        if type(codigo) is not int or motivo not in MOTIVOS_FALHA:
            raise ValueError('Diagnóstico de console inválido')
        self.codigo=codigo;self.motivo=motivo
        super().__init__(MOTIVOS_FALHA[motivo])


def motivo_falha(stderr,codigo):
    texto=stderr.lower()
    if 'ineligibletiererror' in texto and 'unsupported_client' in texto:return 'cliente_nao_suportado'
    if codigo==55 and ('trust' in texto or 'confi' in texto):return 'workspace_nao_confiavel'
    if '429' in texto or 'quota' in texto or 'insufficient_credit' in texto:return 'limite_ou_credito'
    if 'fatalauthenticationerror' in texto or 'invalid_api_key' in texto:return 'autenticacao_indisponivel'
    return 'console_falhou'


def motivo_opencode(fluxo):
    """Diagnóstico somente de envelopes error; textos/modelos não são atestação."""
    motivos=[]
    def unico(pares):
        obj={}
        for chave,valor in pares:
            if chave in obj:raise ValueError('Campo repetido no diagnóstico')
            obj[chave]=valor
        return obj
    for linha in fluxo.splitlines():
        if not linha.strip() or len(linha)>65536:continue
        try:ev=json.loads(linha,object_pairs_hook=unico)
        except (ValueError,RecursionError):continue
        if not isinstance(ev,dict) or ev.get('type')!='error':continue
        erro=ev.get('error');dados=erro.get('data') if isinstance(erro,dict) else None
        motivo='console_falhou'
        if isinstance(dados,dict):
            status=dados.get('statusCode')
            mensagem=dados.get('message')
            if type(status) is int and status==429:motivo='limite_ou_credito'
            elif type(status) is int and status==401:motivo='autenticacao_indisponivel'
            elif erro.get('name')=='ProviderAuthError':motivo='autenticacao_indisponivel'
            elif isinstance(mensagem,str) and len(mensagem)<=4096:
                # Headers, responseBody, metadata e texto de sucesso não entram no diagnóstico.
                motivo=motivo_falha(mensagem,1)
            if motivo=='console_falhou' and type(status) is int and status==403:
                motivo='acesso_recusado'
        motivos.append(motivo)
    if not motivos:return None
    return motivos[0] if len(set(motivos))==1 else 'console_falhou'


def rodar(args, pasta, env, entrada=None, timeout=600, ao_saida=None):
    try:
        r = subprocess.run(args, cwd=pasta, env=env, input=entrada,
                           capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout)
    except subprocess.SubprocessError as exc:
        raise RuntimeError('Revisor não terminou corretamente') from exc
    if len(r.stdout) > 8*1024*1024:
        raise RuntimeError('Revisor falhou ou excedeu o limite de resposta')
    if ao_saida is not None:
        try:ao_saida(r.stdout)
        except Exception:
            import sys
            print('Consumo da consulta indisponível; nenhuma cobrança presumida.',file=sys.stderr)
    opencode_json=('run' in args and '--pure' in args and '--format' in args
                   and args[args.index('--format')+1:args.index('--format')+2]==['json'])
    motivo=motivo_opencode(r.stdout) if opencode_json else None
    if r.returncode or motivo is not None:
        raise FalhaRevisor(r.returncode or 1,motivo or motivo_falha(r.stderr,r.returncode))
    if args and args[-1]=='--help':
        # OpenCode/yargs imprime ajuda em stderr mesmo com exit 0.
        ajuda=r.stdout+'\n'+r.stderr
        if len(ajuda)>8*1024*1024:raise RuntimeError('Ajuda do console excedeu o limite')
        return ajuda
    return r.stdout


def verificar_flags(comando, pasta, env, flags):
    ajuda = rodar(comando + ['--help'], pasta, env, timeout=30)
    if any(flag not in ajuda for flag in flags):
        raise ValueError('Versão do console sem os controles necessários para revisão isolada')


def resposta_gemini(fluxo):
    """Uma sessão e uma conclusão; erro/ferramenta/stream incompleto não aprova."""
    sessao=None; texto=[]; terminou=False
    for linha in fluxo.splitlines():
        if not linha.strip():continue
        ev=json.loads(linha)
        if not isinstance(ev,dict):raise RuntimeError('Gemini retornou envelope inválido')
        tipo=ev.get('type')
        if terminou:raise RuntimeError('Gemini retornou eventos após a conclusão')
        if tipo=='init':
            if (sessao is not None or not isinstance(ev.get('session_id'),str) or not ev['session_id']
                    or not isinstance(ev.get('model'),str) or not ev['model']):
                raise RuntimeError('Gemini não comprovou sessão nova e modelo')
            sessao=ev['session_id'];continue
        if not sessao or (ev.get('session_id') is not None and ev['session_id']!=sessao):
            raise RuntimeError('Gemini diverge da sessão da revisão')
        if tipo in ('tool_use','tool_result','error'):
            raise RuntimeError('Gemini tentou ferramenta ou informou erro')
        if tipo=='message':
            if ev.get('role') not in ('user','assistant') or not isinstance(ev.get('content'),str):
                raise RuntimeError('Gemini retornou mensagem inválida')
            if ev['role']=='assistant':texto.append(ev['content'])
        elif tipo=='result':
            if ev.get('status')!='success' or ev.get('error') is not None or not texto:
                raise RuntimeError('Gemini sem conclusão bem-sucedida')
            terminou=True
        else:raise RuntimeError('Gemini retornou evento desconhecido')
    if not terminou:raise RuntimeError('Gemini sem conclusão bem-sucedida')
    return ''.join(texto)


def resposta_codex(fluxo):
    """Um thread/turno completo; só mensagens e raciocínio sem ferramentas."""
    from retorno_console import Retorno
    retorno=Retorno('codex'); textos=[]; concluidos=set(); tipos={}
    eventos={'thread.started','turn.started','turn.completed',
             'item.started','item.updated','item.completed'}
    for linha in fluxo.splitlines():
        if not linha.strip():continue
        ev=json.loads(linha)
        if not isinstance(ev,dict) or ev.get('type') not in eventos:
            raise RuntimeError('Codex informou erro ou evento desconhecido')
        tipo=ev['type']
        if retorno.terminou or (tipo=='thread.started' and retorno.sessao is not None):
            raise RuntimeError('Codex retornou outra sessão ou eventos após a conclusão')
        if ev.get('thread_id') is not None and tipo!='thread.started' and ev['thread_id']!=retorno.sessao:
            raise RuntimeError('Codex diverge da sessão da consulta')
        retorno.consumir(ev)
        if retorno.falhou:raise RuntimeError('Codex não comprovou início e conclusão do turno')
        if tipo.startswith('item.'):
            item=ev.get('item')
            if (not isinstance(item,dict) or not Retorno.ident(item.get('id'))
                or item.get('type') not in ('agent_message','reasoning')):
                raise RuntimeError('Codex tentou ferramenta ou retornou item inválido')
            ident=item['id']
            if ident in concluidos or (ident in tipos and tipos[ident]!=item['type']):
                raise RuntimeError('Codex repetiu ou alterou item concluído')
            tipos[ident]=item['type']
            if 'text' in item and not isinstance(item['text'],str):
                raise RuntimeError('Codex retornou texto inválido')
            if tipo=='item.completed':
                concluidos.add(ident)
                if item['type']=='agent_message':
                    if not isinstance(item.get('text'),str) or not item['text'].strip():
                        raise RuntimeError('Codex retornou mensagem vazia')
                    textos.append(item['text'])
        elif tipo=='turn.completed' and (not textos or set(tipos)!=concluidos):
            raise RuntimeError('Codex não concluiu todos os itens da consulta')
    if not retorno.sucesso() or not textos:raise RuntimeError('Codex sem resultado final')
    return textos[-1]


def resposta_opencode(fluxo):
    """Uma etapa sem ferramentas, na mesma sessão/mensagem e com fim explícito."""
    sessao=None;mensagem=None;textos=[];partes=set();terminou=False
    tipos={'step_start':'step-start','text':'text','reasoning':'reasoning','step_finish':'step-finish'}
    for linha in fluxo.splitlines():
        if not linha.strip():continue
        ev=json.loads(linha)
        if not isinstance(ev,dict):raise RuntimeError('OpenCode retornou envelope inválido')
        tipo=ev.get('type');part=ev.get('part')
        if terminou:raise RuntimeError('OpenCode retornou eventos após a conclusão')
        if tipo not in tipos:raise RuntimeError('OpenCode informou erro, ferramenta ou evento desconhecido')
        if (not isinstance(part,dict) or part.get('type')!=tipos[tipo]
            or any(not isinstance(v,str) or not 1<=len(v)<=256
                   for v in (ev.get('sessionID'),part.get('sessionID'),part.get('messageID'),part.get('id')))
            or part['sessionID']!=ev['sessionID'] or part['id'] in partes):
            raise RuntimeError('OpenCode não comprovou identidade da resposta')
        partes.add(part['id'])
        if tipo=='step_start':
            if sessao is not None:raise RuntimeError('OpenCode retornou outra etapa de revisão')
            sessao=ev['sessionID'];mensagem=part['messageID'];continue
        if sessao is None or ev['sessionID']!=sessao or part['messageID']!=mensagem:
            raise RuntimeError('OpenCode diverge da sessão ou mensagem da revisão')
        if tipo in ('text','reasoning'):
            if not isinstance(part.get('text'),str):raise RuntimeError('OpenCode retornou texto inválido')
            if tipo=='text':textos.append(part['text'])
        else:
            if part.get('reason')!='stop':raise RuntimeError('OpenCode não terminou a revisão')
            terminou=True
    if not terminou or not ''.join(textos).strip():raise RuntimeError('OpenCode sem conclusão ou resposta')
    return ''.join(textos)


def chamar(executor, prompt, normalizador=normalizar, ao_evento=None):
    if executor.get('execucao', 'cloud') != 'cloud':
        raise ValueError('Revisão cruzada exige executor cloud')
    provider, exe = selecionar(executor['console'])
    cmd = comando_nativo(exe, provider.nome)
    modelo = executor.get('modelo')
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 250000:
        raise ValueError('Contexto vazio ou grande demais; não será truncado silenciosamente')
    sessao_contabilizada=None
    def observar(texto):
        falhou=False
        for linha in texto.splitlines():
            try:ev=json.loads(linha)
            except (ValueError,TypeError):continue
            if isinstance(ev,dict):
                if sessao_contabilizada is not None and ev.get('session_id')!=sessao_contabilizada:continue
                try:ao_evento(ev)
                except Exception:falhou=True
        if falhou:
            import sys
            print('Parte do consumo da consulta ficou indisponível; nenhuma cobrança presumida.',file=sys.stderr)
    def inferir(args,pasta,env,entrada):
        if ao_evento is None:return rodar(args,pasta,env,entrada)
        return rodar(args,pasta,env,entrada,ao_saida=observar)
    with tempfile.TemporaryDirectory(prefix='office-review-') as tmp:
        pasta = Path(tmp)
        env = os.environ.copy()
        if provider.nome == 'claude':
            verificar_flags(cmd, pasta, env, ['--safe-mode', '--tools', '--strict-mcp-config', '--no-session-persistence', '--verbose'])
            if ao_evento is not None:
                verificar_flags(cmd,pasta,env,['--session-id'])
                sessao_contabilizada=str(uuid.uuid4())
            mcp = pasta/'mcp.json'; mcp.write_text('{"mcpServers":{}}', encoding='utf-8')
            args = cmd + ['-p', '--safe-mode', '--tools', '', '--strict-mcp-config', '--mcp-config', str(mcp),
                          '--disable-slash-commands', '--no-session-persistence', '--verbose', '--output-format', 'stream-json']
            if modelo: args += ['--model', modelo]
            if sessao_contabilizada is not None:args+=['--session-id',sessao_contabilizada]
            sessao=None; resposta=None
            for linha in inferir(args,pasta,env,prompt).splitlines():
                ev=json.loads(linha)
                if not isinstance(ev,dict): raise RuntimeError('Claude retornou envelope inválido')
                if ev.get('type')=='system' and ev.get('subtype')=='init':
                    if ev.get('tools')!=[] or not isinstance(ev.get('session_id'),str) or not ev['session_id']:
                        raise RuntimeError('Claude não comprovou sessão sem ferramentas')
                    if sessao_contabilizada is not None and ev['session_id']!=sessao_contabilizada:
                        raise RuntimeError('Claude diverge da sessão nova contabilizada')
                    if sessao and sessao!=ev['session_id']: raise RuntimeError('Claude mudou a sessão da revisão')
                    sessao=ev['session_id']
                if ev.get('type')=='assistant':
                    mensagem=ev.get('message')
                    if not isinstance(mensagem,dict) or not isinstance(mensagem.get('content'),list):
                        raise RuntimeError('Claude retornou mensagem inválida')
                    conteudo=mensagem['content']
                    if any(isinstance(c,dict) and c.get('type')=='tool_use' for c in conteudo):
                        raise RuntimeError('Revisor tentou usar uma ferramenta')
                if ev.get('type') in ('error','tool_use'):
                    raise RuntimeError('Claude informou erro ou tentou ferramenta')
                if ev.get('type')=='result':
                    if (not sessao or ev.get('session_id')!=sessao or ev.get('parent_tool_use_id')
                            or ev.get('is_error') is not False or resposta is not None):
                        raise RuntimeError('Claude não completou uma revisão principal válida')
                    resposta=ev.get('result')
            if resposta is None: raise RuntimeError('Claude sem resultado final')
            return normalizador(resposta)
        if provider.nome == 'codex':
            verificar_flags(cmd+['exec'], pasta, env, ['--ignore-user-config', '--ignore-rules', '--sandbox', '--ephemeral'])
            args = cmd + ['exec', '--ignore-user-config', '--ignore-rules', '--sandbox', 'read-only',
                          '--skip-git-repo-check', '--ephemeral', '--json', '-c', 'web_search="disabled"']
            for feature in ('hooks', 'plugins', 'apps', 'multi_agent', 'multi_agent_v2', 'shell_tool',
                            'unified_exec', 'browser_use', 'computer_use', 'image_generation'):
                args += ['--disable', feature]
            if modelo: args += ['--model', modelo]
            args += ['-']
            return normalizador(resposta_codex(inferir(args,pasta,env,prompt)))
        if provider.nome == 'gemini':
            verificar_flags(cmd, pasta, env, ['--admin-policy', '--extensions', '--output-format'])
            settings = pasta/'settings.json'
            settings.write_text(json.dumps({'admin': {'mcp': {'enabled': False}, 'extensions': {'enabled': False},
                                                      'skills': {'enabled': False}}, 'hooksConfig': {'enabled': False},
                                            'context':{'fileName':'review-context-'+uuid.uuid4().hex+'.md',
                                                       'includeDirectories':[], 'loadFromIncludeDirectories':False,
                                                       'includeDirectoryTree':False},
                                            # Só este processo, em pasta temporária própria e sem ferramentas.
                                            # Não adiciona Temp ou projetos à lista global de confiança.
                                            'security':{'folderTrust':{'enabled':False}},
                                            'tools': {'discoveryCommand': '', 'callCommand': ''}}), encoding='utf-8')
            env['GEMINI_CLI_SYSTEM_SETTINGS_PATH'] = str(settings)
            for chave in ('GEMINI_SYSTEM_MD','GEMINI_APPEND_SYSTEM_MD'):
                env.pop(chave,None)
            policy = pasta/'review.toml'
            policy.write_text('[[rule]]\ntoolName = "*"\ndecision = "deny"\npriority = 999\n', encoding='utf-8')
            args = cmd + ['--admin-policy', str(policy), '--extensions', 'none', '--output-format', 'stream-json',
                          '--prompt', 'Analise somente os dados recebidos em stdin e siga o formato solicitado. Não use ferramentas.']
            if modelo: args += ['--model', modelo]
            return normalizador(resposta_gemini(inferir(args,pasta,env,prompt)))
        if provider.nome == 'opencode':
            verificar_flags(cmd+['run'], pasta, env, ['--pure', '--format', '--agent'])
            nome = 'office_review_' + uuid.uuid4().hex
            config = {'permission': 'deny', 'share': 'disabled', 'autoupdate': False,
                      'agent': {nome: {'description': 'Revisão sem ferramentas', 'mode': 'primary', 'permission': 'deny'}}}
            env['OPENCODE_CONFIG_CONTENT'] = json.dumps(config)
            # Ler configuração efetiva não executa inferência. Desliga os MCP globais por nome.
            efetivo = json.loads(rodar(cmd+['debug', 'config', '--pure'], pasta, env, timeout=30))
            config['mcp'] = {n: {'enabled': False} for n in efetivo.get('mcp', {})}
            env['OPENCODE_CONFIG_CONTENT'] = json.dumps(config)
            efetivo = json.loads(rodar(cmd+['debug', 'config', '--pure'], pasta, env, timeout=30))
            if (efetivo.get('permission') not in ('deny', {'*': 'deny'}) or efetivo.get('agent', {}).get(nome, {}).get('permission') not in ('deny', {'*': 'deny'})
                or any(s.get('enabled') is not False for s in efetivo.get('mcp', {}).values())):
                raise ValueError('Configuração gerenciada não permite isolamento do OpenCode')
            args = cmd+['run', '--pure', '--format', 'json', '--agent', nome]
            if modelo: args += ['--model', modelo]
            args += ['Analise somente o contexto recebido em stdin e siga o formato solicitado; não use ferramentas.']
            return normalizador(resposta_opencode(inferir(args, pasta, env, prompt)))
        raise ValueError('Console sem adapter de revisão isolada')
