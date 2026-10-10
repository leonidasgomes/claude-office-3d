"""Ollama local explícito. Não baixa modelos, não modifica perfil e não troca para cloud."""
import json
from pathlib import Path
import re
import urllib.request
from memoria_local import URL_OLLAMA

URL = URL_OLLAMA
MODELO = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}\Z')


def mostrar_modelo(modelo):
    req = urllib.request.Request(URL+'/api/show', data=json.dumps({'model':modelo}).encode(),
                                 headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=5) as resposta:
        return json.load(resposta)


def validar_modelo(rota, consultar=mostrar_modelo):
    if rota['console'] not in ('claude','codex','opencode'):
        raise ValueError('Este console ainda não tem adapter Ollama local; nenhum cloud será usado')
    modelo = rota.get('modelo') or ''
    if not MODELO.fullmatch(modelo) or 'cloud' in modelo.lower():
        raise ValueError('Informe modelo Ollama instalado e local, sem prefixo de fornecedor')
    dados = consultar(modelo)
    if (not isinstance(dados,dict) or dados.get('remote_host') or dados.get('remote_model')
        or (dados.get('details') or {}).get('format') != 'gguf'):
        raise ValueError('Modelo remoto ou não identificado não pode usar a rota local')
    if 'completion' not in dados.get('capabilities',[]):
        raise ValueError('Modelo local não informa capacidade de geração')
    return modelo


def preparar_comando(provider, args, modelo, env):
    args = list(args)
    env['OLLAMA_HOST'] = URL
    env['OLLAMA_BASE_URL'] = URL
    if provider.nome == 'codex':
        if 'exec' not in args:
            raise ValueError('Codex local gerenciado exige tarefa estruturada; TUI local ainda não conectada')
        args.insert(args.index('exec')+1, '--ignore-user-config')
        # Flags globais antes do subcomando; configuram só esta execução.
        inicio = next((i for i,a in enumerate(args) if a in ('exec','resume')),len(args))
        args[inicio:inicio] = ['--oss','--local-provider','ollama','-c','web_search="disabled"',
                               '--disable','multi_agent','--disable','multi_agent_v2']
    elif provider.nome == 'opencode':
        nome = 'office_ollama'
        cfg = {'provider':{nome:{'npm':'@ai-sdk/openai-compatible','name':'Ollama local',
                'options':{'baseURL':URL+'/v1','apiKey':'ollama'},'models':{modelo:{'name':modelo}}}},
               'enabled_providers':[nome]}
        env['OPENCODE_CONFIG_CONTENT'] = json.dumps(cfg)
        i = args.index('--model'); args[i+1] = nome+'/'+modelo
    else:
        env.update(ANTHROPIC_BASE_URL=URL, ANTHROPIC_AUTH_TOKEN='ollama', ANTHROPIC_API_KEY='',
                   ANTHROPIC_MODEL=modelo, CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS='0')
        for chave in ('ANTHROPIC_DEFAULT_OPUS_MODEL','ANTHROPIC_DEFAULT_SONNET_MODEL','ANTHROPIC_DEFAULT_HAIKU_MODEL'):
            env[chave] = modelo
        args += ['--bare','--strict-mcp-config']
    return args


def executar(rota, politica, provider, exe, projeto, mesa, prompt=None, sessao=None, agente=None, banco=None, ao_sessao=None, ao_processo=None,projeto_consumo=None,ao_evento=None,tentativa_consumo=None):
    from console_provider import executar as console
    from recursos_local import reservar
    modelo = validar_modelo(rota)
    if prompt is not None:
        prompt = 'Skills compartilhados: leia somente o SKILL.md pertinente na fonte de skills definida pela política do projeto.\n'+prompt
    # Mantém prompts simples pequenos nesta primeira integração; não trunca instruções.
    if not politica['local']['team'] and prompt is not None and len(prompt)>16000:
        raise ValueError('Contexto grande demais para o perfil local simples; use uma rota cloud')
    raiz = Path(__file__).resolve().parent
    with reservar(raiz/'dados/local_reservas.db',politica):
        return console(provider,exe,projeto,mesa,prompt,modelo,sessao,agente,banco,
                       adaptar_local=lambda args,env:preparar_comando(provider,args,modelo,env),
                       politica_local=politica,ao_sessao=ao_sessao,ao_processo=ao_processo,projeto_consumo=projeto_consumo,ao_evento=ao_evento,tentativa_consumo=tentativa_consumo)
