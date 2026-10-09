"""Execução de tarefas por CLIs, com eventos no escritório e ambiente isolado por chamada."""
import atexit
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import threading
import uuid
from datetime import datetime

import banco

import configuracao

RAIZ = Path(__file__).resolve().parent


def configurados():
    cfg = configuracao.carregar()
    projetos = cfg.get('projetos') or []
    projeto = Path(projetos[0]).expanduser().resolve() if projetos else None
    mesas = tuple(a['nome'] for a in cfg['agentes'])
    return projeto, mesas


CATALOGO = {'claude': ('Claude Code', 'claude'), 'ollama': ('Ollama local · Claude Code', 'claude'),
            'codex': ('OpenAI · Codex', 'codex'), 'gemini': ('Gemini CLI', 'gemini'),
            'opencode': ('OpenCode · vários provedores', 'opencode')}
TRAVA = threading.Lock()
TAREFAS = {}
PROCESSOS = {}


def achar(cli):
    return shutil.which(cli) or shutil.which(cli + '.cmd') or shutil.which(cli + '.ps1')


def catalogo():
    projeto, mesas = configurados()
    return {'ok': True, 'mesas': mesas, 'projeto_configurado': projeto is not None, 'provedores': [
        {'id': k, 'nome': nome, 'instalado': bool(achar(cli)) and (k != 'ollama' or bool(achar('ollama')))}
        for k, (nome, cli) in CATALOGO.items()]}


def preparar(dados):
    projeto, mesas = configurados()
    if projeto is None or not projeto.is_dir():
        raise ValueError('Configure uma pasta existente em projetos no config.json.')
    provedor = dados.get('provedor')
    mesa = dados.get('mesa')
    modelo = dados.get('modelo', '')
    prompt = dados.get('prompt')
    if provedor not in CATALOGO or mesa not in mesas:
        raise ValueError('Escolha uma ferramenta e uma mesa válidas.')
    if not isinstance(modelo, str) or (modelo and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_./:@+-]{0,159}', modelo)):
        raise ValueError('Nome de modelo inválido.')
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 12000 or '\x00' in prompt:
        raise ValueError('Informe uma tarefa de até 12000 caracteres.')
    if provedor == 'ollama' and not modelo:
        raise ValueError('Informe o modelo instalado no Ollama.')
    if provedor == 'opencode' and modelo and '/' not in modelo:
        raise ValueError('No OpenCode, use provedor/modelo ou deixe vazio para o padrão.')
    exe = achar(CATALOGO[provedor][1])
    if not exe:
        raise ValueError('CLI não encontrada. Instale e autentique a ferramenta; reinicie o servidor depois.')
    env = os.environ.copy()
    # Não altera o servidor, os bots nem as sessões existentes.
    for key in ('ANTHROPIC_BASE_URL', 'ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_API_KEY'):
        if provedor == 'ollama':
            env.pop(key, None)
    if provedor == 'ollama':
        env.update(ANTHROPIC_BASE_URL='http://127.0.0.1:11434', ANTHROPIC_AUTH_TOKEN='ollama', ANTHROPIC_API_KEY='')
        env.update({k: modelo for k in ('ANTHROPIC_DEFAULT_OPUS_MODEL', 'ANTHROPIC_DEFAULT_SONNET_MODEL',
                                       'ANTHROPIC_DEFAULT_HAIKU_MODEL', 'CLAUDE_CODE_SUBAGENT_MODEL')})
    env['CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS'] = '0'
    env['OFFICE_AGENTE'] = mesa
    env['OFFICE_TASK_PROJECT'] = str(projeto)
    temp = RAIZ / 'dados' / 'tmp' / 'provedores'
    temp.mkdir(parents=True, exist_ok=True)
    env.update(TEMP=str(temp), TMP=str(temp), PYTHONUTF8='1')
    tarefa = (f'Você ocupa a mesa {mesa} no escritório do projeto. Responda em português. '
              'Leia AGENTS.md e CLAUDE.md antes de agir e siga as regras do projeto, arquitetura, branches e PRs. '
              'Leia tamb\u00e9m GEMINI.md se existir. Execute somente a tarefa abaixo, sem criar colegas ou delegar. Nunca faça merge.\n\n' + prompt)
    if provedor in ('claude', 'ollama'):
        args = ['-p', '--verbose', '--output-format', 'stream-json']
    elif provedor == 'codex':
        args = ['exec', '--json']
    elif provedor == 'gemini':
        args = ['--output-format', 'stream-json', '-p']
    else:
        args = ['run', '--format', 'json']
    # Gemini -p recebe o prompt imediatamente após a opção.
    if provedor == 'gemini':
        args.append(tarefa)
        if modelo:
            args += ['--model', modelo]
    else:
        if modelo:
            args += ['--model', modelo]
        args += [tarefa]
    return provedor, mesa, modelo, [exe, *args], env


def comando_arquivo(argv, pasta):
    """Resolve o wrapper npm para node, sem shell e sem interpolar o prompt."""
    exe = Path(argv[0])
    if os.name != 'nt' or exe.suffix.lower() not in ('.cmd', '.bat', '.ps1'):
        return argv, None
    wrapper = exe.with_suffix('.cmd')
    if not wrapper.is_file():
        raise ValueError('Use o executavel nativo ou o launcher npm padrao da CLI.')
    texto = wrapper.read_text(encoding='utf-8', errors='replace')
    match = re.search(r'"%dp0%[\\/]([^"\r\n]+\.js)"', texto)
    if not match:
        raise ValueError('Launcher nao reconhecido. Use a instalacao nativa ou npm da CLI.')
    alvo = (wrapper.parent / match.group(1).replace('\\', '/')).resolve()
    alvo.relative_to((wrapper.parent / 'node_modules').resolve())
    node = wrapper.parent / 'node.exe'
    executavel = str(node) if node.is_file() else shutil.which('node')
    if not executavel or not alvo.is_file():
        raise ValueError('Instalacao npm incompleta: node ou entrada da CLI ausente.')
    return [executavel, str(alvo), *argv[1:]], None


def evento(mesa, tipo, resumo, texto='', ferramenta=''):
    banco.gravar_evento({'ts': datetime.now().isoformat(timespec='seconds'), 'agente': mesa,
                        'tipo': tipo, 'resumo': resumo[:90], 'texto': texto[:12000],
                        'detalhe': texto[:400], 'ferramenta': ferramenta, 'para': []})


def interpretar(d):
    """Normaliza os envelopes JSON de Claude, Codex, Gemini e OpenCode."""
    if not isinstance(d, dict):
        return '', ''
    item = d.get('item') or d.get('part') or d
    if not isinstance(item, dict):
        return '', ''
    texto = item.get('text') or d.get('result') or (d.get('content') if isinstance(d.get('content'), str) else '')
    msg = d.get('message', {})
    if isinstance(msg, dict):
        conteudo = msg.get('content', [])
        if isinstance(conteudo, list):
            texto = '\n'.join(x.get('text', '') for x in conteudo if isinstance(x, dict) and x.get('type') == 'text') or texto
            tools = [x.get('name', '') for x in conteudo if isinstance(x, dict) and x.get('type') == 'tool_use']
            if tools:
                return 'trabalho', ', '.join(tools)
    if item.get('type') in ('command_execution', 'tool') or d.get('type') == 'tool_use':
        return 'trabalho', str(item.get('command') or d.get('tool_name') or 'Ferramenta')
    return ('fala', texto) if isinstance(texto, str) and texto else ('', '')


def executar(id_, argv, env):
    with TRAVA:
        t = TAREFAS[id_]
    arquivo = None
    limite = None
    p = None
    try:
        evento(t['mesa'], 'trabalho', 'Iniciando ' + t['provedor'], ferramenta='Provedor')
        comando, arquivo = comando_arquivo(argv, env['TEMP'])
        p = subprocess.Popen(comando, cwd=env['OFFICE_TASK_PROJECT'], env=env, stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8',
                             errors='replace', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                             start_new_session=os.name != 'nt')
        with TRAVA:
            PROCESSOS[id_] = p
            cancelada = t['estado'] == 'cancelando'
        if cancelada:
            parar_processo(p)
        limite = threading.Timer(1800, lambda: cancelar({'id': id_}))
        limite.daemon = True
        limite.start()
        # CLI mantém suas próprias permissões; nenhuma opção de aprovação automática é passada.
        for linha in p.stdout:
            try:
                tipo, texto = interpretar(json.loads(linha))
            except ValueError:
                tipo, texto = '', ''
            if tipo and texto:
                with TRAVA:
                    t['resultado'] = (t['resultado'] + '\n' + texto)[-12000:]
                evento(t['mesa'], tipo, texto, texto, 'Provedor' if tipo == 'trabalho' else '')
        p.stdout.close()
        codigo = p.wait()
        limite.cancel()
        with TRAVA:
            t['estado'] = 'cancelada' if t['estado'] == 'cancelando' else ('concluida' if codigo == 0 else 'erro')
            t['codigo'] = codigo
            if t['estado'] == 'erro':
                t['erro'] = 'A CLI falhou. Confira login, modelo, permissões e configuração na ferramenta.'
    except Exception:
        if p and p.poll() is None:
            parar_processo(p)
        if p and p.stdout:
            p.stdout.close()
        with TRAVA:
            t['estado'], t['erro'] = 'erro', 'Não foi possível executar a CLI.'
    finally:
        if limite:
            limite.cancel()
        if arquivo:
            arquivo.unlink(missing_ok=True)
        with TRAVA:
            PROCESSOS.pop(id_, None)
        evento(t['mesa'], 'ocioso', 'Tarefa ' + t['estado'])


def parar_processo(p):
    if p.poll() is not None:
        return
    if os.name == 'nt':
        subprocess.run(['taskkill.exe', '/PID', str(p.pid), '/T', '/F'], capture_output=True,
                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), timeout=15)
    else:
        os.killpg(p.pid, signal.SIGTERM)


def encerrar():
    with TRAVA:
        processos = list(PROCESSOS.values())
    for p in processos:
        try:
            parar_processo(p)
        except (OSError, subprocess.SubprocessError):
            pass


atexit.register(encerrar)


def cancelar(dados):
    id_ = dados.get('id')
    if not isinstance(id_, str):
        return 400, {'ok': False, 'erro': 'Identificador inválido.'}
    with TRAVA:
        t = TAREFAS.get(id_)
        if not t:
            return 404, {'ok': False, 'erro': 'Tarefa não encontrada.'}
        if t['estado'] not in ('executando', 'cancelando'):
            return 200, {'ok': True}
        t['estado'] = 'cancelando'
        p = PROCESSOS.get(id_)
    if p:
        try:
            parar_processo(p)
        except (OSError, subprocess.SubprocessError):
            return 500, {'ok': False, 'erro': 'Não foi possível parar a tarefa.'}
    return 200, {'ok': True}


def iniciar(dados):
    try:
        provedor, mesa, modelo, argv, env = preparar(dados)
    except ValueError as e:
        return 400, {'ok': False, 'erro': str(e)}
    with TRAVA:
        ativos = [t for t in TAREFAS.values() if t['estado'] in ('executando', 'cancelando')]
        if any(t['mesa'] == mesa for t in ativos) or (provedor == 'ollama' and any(t['provedor'] == 'ollama' for t in ativos)):
            return 409, {'ok': False, 'erro': 'Esta mesa ou o Ollama já tem uma tarefa em execução.'}
        if len(ativos) >= 3:
            return 409, {'ok': False, 'erro': 'Limite de três tarefas simultâneas atingido.'}
        # Histórico limitado em memória; eventos completos seguem no banco existente.
        for chave in list(TAREFAS)[:-49]:
            if TAREFAS[chave]['estado'] not in ('executando', 'cancelando'):
                del TAREFAS[chave]
        id_ = uuid.uuid4().hex
        TAREFAS[id_] = {'id': id_, 'provedor': provedor, 'mesa': mesa, 'modelo': modelo,
                       'estado': 'executando', 'resultado': '', 'erro': ''}
    threading.Thread(target=executar, args=(id_, argv, env), daemon=True).start()
    return 200, {'ok': True, 'id': id_}


def estado():
    with TRAVA:
        return {'ok': True, 'tarefas': [dict(t) for t in TAREFAS.values()]}
