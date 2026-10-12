"""Compatibilidade V2: processo privado e confirmação local de turno somente textual.

Não considera exit 0/texto como conclusão. O export nativo deve vincular sessão,
projeto, mensagem e usuário novos desta execução; ferramentas continuam exigindo
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


def validar_export(dados, retorno, projeto, inicio_ms, prompt, modelo, registros):
    """Retorna fim normalizado somente com prova nativa exata, nunca por heurística."""
    if (retorno.console != 'opencode' or retorno.falhou or not retorno.ativo
        or retorno.terminou or not retorno.sessao or not retorno.mensagem):
        return None
    # Limite conservador: um turno textual, sem ferramentas/etapas perdidas.
    if ([r.get('type') for r in registros].count('step_start') != 1
        or any(r.get('type') not in ('step_start', 'text', 'reasoning') for r in registros)
        or not any(r.get('type') == 'text' and (r.get('part') or {}).get('text', '').strip() for r in registros)):
        return None
    try:
        info = dados['info']; mensagens = dados['messages']
        if (info['id'] != retorno.sessao or info['outcome'] != 'succeeded'
            or Path(info['location']['directory']).resolve() != Path(projeto).resolve()
            or len(mensagens) < 3):
            return None
        usuario, resposta, fim = mensagens[-3:]
        if (usuario['type'] != 'user' or resposta['type'] != 'assistant'
            or fim['type'] != 'idle' or fim['outcome'] != 'succeeded'
            or resposta['id'] != retorno.mensagem or resposta['finish'] != 'stop'
            or resposta.get('error') is not None or info.get('error') is not None
            or not usuario['text'].endswith('\n' + prompt)):
            return None
        tempos = [inicio_ms, usuario['time']['created'], resposta['time']['created'],
                  resposta['time']['completed'], fim['time']['created']]
        if any(type(t) not in (int, float) or not math.isfinite(t) for t in tempos) or tempos != sorted(tempos):
            return None
        if modelo and resposta['model']['providerID'] + '/' + resposta['model']['id'] != modelo:
            return None
        conteudo = resposta['content']
        if any(c.get('type') not in ('text', 'reasoning') for c in conteudo):
            return None
        texto = ''.join(c['text'] for c in conteudo if c['type'] == 'text')
        observado = ''.join(r['part']['text'] for r in registros if r['type'] == 'text')
        if not texto.strip() or texto != observado:
            return None
        return {'type': 'step_finish', 'sessionID': retorno.sessao,
                'source': 'opencode.v2.session.export',
                'part': {'type': 'step-finish', 'sessionID': retorno.sessao,
                         'messageID': retorno.mensagem, 'id': retorno.mensagem + '_office_verified',
                         'reason': 'stop', 'cost': resposta.get('cost'), 'tokens': resposta.get('tokens')}}
    except (KeyError, TypeError, ValueError, AttributeError):
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
