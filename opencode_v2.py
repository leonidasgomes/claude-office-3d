"""Compatibilidade V2: processo privado e confirmação local do término textual ausente.

Não considera exit 0/texto como conclusão. O export nativo deve vincular sessão,
projeto, mensagens e usuário novos desta execução; ferramentas continuam exigindo
os eventos terminais originais. Falha de leitura/versionamento fecha o gate.
"""
import json
import math
import re
import subprocess
from pathlib import Path


def consultar(args, projeto, env, timeout, limite):
    """Leitura nativa limitada; também recolhe descendentes em timeout/interrupção."""
    import tempfile
    with tempfile.TemporaryFile() as saida:
        p = subprocess.Popen(args, cwd=str(projeto), env=env, stdout=saida,
                             stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                             start_new_session=True)
        try:
            p.wait(timeout=timeout)
        except BaseException:
            from console_provider import encerrar_processo
            encerrar_processo(p, grupo_isolado=True)
            raise
        if p.returncode or saida.tell() > limite:
            return None
        saida.seek(0)
        return saida.read().decode('utf-8')


def versao(exe, projeto, env):
    from providers_console import comando_nativo
    try:
        texto = consultar(comando_nativo(exe, 'opencode') + ['--version'],
                          projeto, env, 5, 1024)
        return texto is not None and re.fullmatch(r'(?:opencode v)?2\.\d+\.\d+(?:[-+][\w.-]+)?', texto.strip()) is not None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return False


def _ordem(tempos):
    return (all(type(t) in (int, float) and math.isfinite(t) for t in tempos)
            and tempos == sorted(tempos))


def _etapa(resposta, registros, sessao, modelo, anterior, final):
    """Confronta uma etapa inteira; ferramentas exigem término nativo e no stream."""
    if (resposta['type'] != 'assistant' or resposta.get('error') is not None
        or resposta['finish'] != ('stop' if final else 'tool-calls')
        or not _ordem([anterior, resposta['time']['created'], resposta['time']['completed']])
        or (modelo and resposta['model']['providerID'] + '/' + resposta['model']['id'] != modelo)):
        return False
    if (not registros or registros[0]['type'] != 'step_start'
        or any(r['sessionID'] != sessao or r['part']['sessionID'] != sessao
               or r['part']['messageID'] != resposta['id'] for r in registros)):
        return False
    tipos = [r['type'] for r in registros]
    if (tipos.count('step_start') != 1
        or tipos.count('step_finish') != (0 if final else 1)
        or (not final and tipos[-1] != 'step_finish')):
        return False
    conteudo = resposta['content']
    if any(c['type'] not in ('text', 'reasoning', 'tool') for c in conteudo):
        return False
    texto = ''.join(c['text'] for c in conteudo if c['type'] == 'text')
    observado = ''.join(r['part']['text'] for r in registros if r['type'] == 'text')
    if texto != observado or (final and not texto.strip()):
        return False
    pensamentos = [r['part']['text'] for r in registros if r['type'] == 'reasoning']
    if pensamentos and ''.join(pensamentos) != ''.join(c['text'] for c in conteudo if c['type'] == 'reasoning'):
        return False
    ferramentas = [c for c in conteudo if c['type'] == 'tool']
    vistas = [r['part'] for r in registros if r['type'] == 'tool_use']
    if final:
        return not ferramentas and not vistas
    fim = registros[-1]['part']
    if (not ferramentas or len(ferramentas) != len(vistas)
        or len({f['id'] for f in ferramentas}) != len(ferramentas)
        or fim['reason'] != 'tool-calls'
        or fim.get('cost') != resposta.get('cost') or fim.get('tokens') != resposta.get('tokens')):
        return False
    for nativa, vista in zip(ferramentas, vistas):
        # Escopo validado: somente ferramentas de arquivo. Outros formatos fecham o gate.
        if (nativa['name'] not in ('read', 'write', 'edit')
            or nativa['name'] != vista['tool'] or nativa['id'] != vista['id']
            or nativa.get('executed') is not False
            or vista['state']['metadata']['providerCall'].get('executed') is not False
            or vista['state']['metadata']['providerResult'].get('executed') is not False
            or not isinstance(nativa['state']['input'], dict)
            or not isinstance(nativa['state']['content'], list)
            or any(c.get('type') != 'text' or not isinstance(c.get('text'), str)
                   for c in nativa['state']['content'])
            or nativa['state']['status'] != 'completed' or vista['state']['status'] != 'completed'
            or nativa['state'].get('error') is not None or vista['state'].get('error') is not None
            or nativa['state']['input'] != vista['state']['input']
            or nativa['state']['content'] != vista['state']['metadata']['content']
            or nativa['state'].get('metadata') != vista['state']['metadata'].get('metadata')
            or not _ordem([resposta['time']['created'], nativa['time']['created'],
                           nativa['time']['ran'], nativa['time']['completed'], resposta['time']['completed']])
            or vista['state']['time']['start'] != nativa['time']['created']
            or vista['state']['time']['end'] != nativa['time']['completed']):
            return False
    return True


def validar_export(dados, retorno, projeto, inicio_ms, prompt, modelo, registros):
    """Recupera apenas o fim textual ausente, sem inventar conclusão de ferramenta."""
    if (retorno.console != 'opencode' or retorno.falhou or not retorno.ativo
        or retorno.terminou or not retorno.sessao or not retorno.mensagem):
        return None
    try:
        from retorno_console import Retorno
        replay = Retorno('opencode')
        grupos = []
        for registro in registros:
            if registro['type'] not in ('step_start', 'step_finish', 'text', 'reasoning', 'tool_use'):
                return None
            if registro['type'] == 'step_start':
                grupos.append([])
            if not grupos:
                return None
            grupos[-1].append(registro)
            replay.consumir(registro)
        if (replay.falhou or not replay.ativo or replay.terminou
            or replay.sessao != retorno.sessao or replay.mensagem != retorno.mensagem):
            return None
        terminais = [r['part']['id'] for r in registros if r['type'] == 'step_finish']
        if (not Retorno.ident(retorno.mensagem + '_office_verified')
            or any(not Retorno.ident(t) for t in terminais)
            or len(set(terminais)) != len(terminais)
            or retorno.mensagem + '_office_verified' in terminais):
            return None
        info = dados['info']; mensagens = dados['messages']
        if (info['id'] != retorno.sessao or info['outcome'] != 'succeeded'
            or info.get('error') is not None
            or Path(info['location']['directory']).resolve() != Path(projeto).resolve()):
            return None
        # Último usuário, nunca um turno anterior de uma sessão retomada.
        indice = max(i for i, m in enumerate(mensagens) if m['type'] == 'user')
        usuario = mensagens[indice]; respostas = mensagens[indice + 1:-1]; fim = mensagens[-1]
        if (not respostas or len(respostas) != len(grupos)
            or len({r['id'] for r in respostas}) != len(respostas)
            or fim['type'] != 'idle' or fim['outcome'] != 'succeeded'
            or fim.get('error') is not None
            or respostas[-1]['id'] != retorno.mensagem
            or not usuario['text'].endswith('\n' + prompt)
            or not _ordem([inicio_ms, usuario['time']['created']])):
            return None
        anterior = usuario['time']['created']
        for i, (resposta, grupo) in enumerate(zip(respostas, grupos)):
            if not _etapa(resposta, grupo, retorno.sessao, modelo, anterior, i == len(respostas) - 1):
                return None
            anterior = resposta['time']['completed']
        if not _ordem([anterior, fim['time']['created']]):
            return None
        resposta = respostas[-1]
        return {'type': 'step_finish', 'sessionID': retorno.sessao,
                'source': 'opencode.v2.session.export',
                'part': {'type': 'step-finish', 'sessionID': retorno.sessao,
                         'messageID': retorno.mensagem, 'id': retorno.mensagem + '_office_verified',
                         'reason': 'stop', 'cost': resposta.get('cost'), 'tokens': resposta.get('tokens')}}
    except (KeyError, TypeError, ValueError, AttributeError, IndexError):
        return None


def confirmar(exe, projeto, env, retorno, inicio_ms, prompt, modelo, registros):
    from providers_console import comando_nativo
    if not retorno.sessao or not re.fullmatch(r'[A-Za-z0-9_-]{1,256}', retorno.sessao):
        return None
    try:
        texto = consultar(comando_nativo(exe, 'opencode') +
                          ['session', 'export', '--standalone', retorno.sessao],
                          projeto, env, 15, 8 * 1024 * 1024)
        if texto is None:
            return None
        dados = json.loads(texto)
        return validar_export(dados, retorno, projeto, inicio_ms, prompt, modelo, registros)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None
