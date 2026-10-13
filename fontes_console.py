"""Importação passiva, opt-in, de arquivos JSONL explicitamente vinculados.

Não descobre sessões, inicia CLIs ou lê configurações globais. Cada origem fixa
um arquivo, projeto, provider e sessão. O primeiro registro deve comprovar esse
vínculo; streams sem cwd podem começar com um envelope office_session explícito.
"""
import argparse
from contextlib import closing
import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path

import banco as esquema
from emit_evento import normalizar
from providers_console import Eventos, sessao_nativa
from codex_observador import Transcrito
from funcionarios import id_projeto
from hooks_providers import binding, prefer_hooks

MAX_LEITURA = 1024 * 1024
MAX_LINHA = 256 * 1024


def _empacotar(v):
    if isinstance(v, set): return {'$set': [_empacotar(x) for x in v]}
    if isinstance(v, tuple): return {'$tuple': [_empacotar(x) for x in v]}
    if isinstance(v, dict): return {k: _empacotar(x) for k, x in v.items()}
    if isinstance(v, list): return [_empacotar(x) for x in v]
    return v


def _desempacotar(v):
    if isinstance(v, dict):
        if set(v) == {'$set'}: return set(_desempacotar(x) for x in v['$set'])
        if set(v) == {'$tuple'}: return tuple(_desempacotar(x) for x in v['$tuple'])
        return {k: _desempacotar(x) for k, x in v.items()}
    if isinstance(v, list): return [_desempacotar(x) for x in v]
    return v


def _fonte(f):
    if not isinstance(f, dict): raise ValueError('Fonte deve ser objeto')
    nomes = ('origem', 'provider', 'projeto', 'sessao', 'mesa', 'arquivo', 'formato')
    if any(not isinstance(f.get(k), str) or not f[k] for k in nomes):
        raise ValueError('Fonte exige origem, provider, projeto, sessao, mesa, arquivo e formato')
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,31}', f['origem']): raise ValueError('Origem inválida')
    if f['provider'] not in ('claude', 'codex', 'opencode'): raise ValueError('Provider inválido')
    if f['formato'] not in ('native', 'codex_rollout', 'hooks'): raise ValueError('Formato inválido')
    if f['formato'] == 'codex_rollout' and f['provider'] != 'codex': raise ValueError('Rollout exige Codex')
    if type(f.get('historico', False)) is not bool: raise ValueError('Historico deve ser booleano')
    for k in ('projeto', 'arquivo'):
        if not Path(f[k]).is_absolute(): raise ValueError(k + ' deve ser absoluto')
    arquivo = Path(f['arquivo'])
    if arquivo.is_symlink() or getattr(arquivo, 'is_junction', lambda: False)(): raise ValueError('Fonte por link recusada')
    if not arquivo.is_file(): raise ValueError('Arquivo da fonte não existe')
    if not Path(f['projeto']).is_dir(): raise ValueError('Projeto não existe')
    out = {**f, 'projeto': str(Path(f['projeto']).resolve()), 'arquivo': str(arquivo.resolve())}
    out['projeto_id'] = id_projeto(out['projeto'])
    if 'projeto_id' in f and f['projeto_id'] != out['projeto_id']: raise ValueError('Projeto ID divergente')
    if 'binding' in f:
        b = binding(f['binding'])
        if (b['provider'], b['project'], b['session_id'], b['project_id']) != (out['provider'], out['projeto'], out['sessao'], out['projeto_id']):
            raise ValueError('Binding divergente da fonte')
        out['binding'] = b
    if f.get('autoridade') not in (None, 'hooks', 'native', 'codex_rollout'): raise ValueError('Autoridade inválida')
    return out


def _validar(r, f, inicial=False):
    if not isinstance(r, dict): raise ValueError('Registro deve ser objeto')
    p = r.get('payload') if r.get('type') == 'session_meta' else r
    if not isinstance(p, dict): raise ValueError('Metadados inválidos')
    sid = p.get('sessao') or p.get('session_id') or p.get('sessionID') or p.get('thread_id')
    if r.get('type') == 'session_meta': sid = p.get('id') or sid
    sid = sid or sessao_nativa(f['provider'], r)
    projeto = p.get('projeto') or p.get('cwd') or p.get('directory')
    provider = p.get('provider') or p.get('fonte')
    projeto_id = p.get('projeto_id') or p.get('project_id')
    if projeto_id is not None and projeto_id != f['projeto_id']: raise ValueError('Projeto ID divergente')
    if f['formato'] == 'native':
        for outro in ('claude', 'codex', 'opencode'):
            if outro != f['provider'] and sessao_nativa(outro, r): raise ValueError('Envelope de outro provider')
    if sid is not None and sid != f['sessao']: raise ValueError('Sessão divergente')
    if provider is not None and provider != f['provider']: raise ValueError('Provider divergente')
    if projeto is not None and (not isinstance(projeto, str) or not Path(projeto).is_absolute() or
                               str(Path(projeto).resolve()) != f['projeto']): raise ValueError('Projeto divergente')
    if inicial and (sid != f['sessao'] or projeto is None): raise ValueError('Primeiro registro não comprova sessão/projeto')
    if f['formato'] == 'hooks' and (sid != f['sessao'] or projeto is None or provider != f['provider']):
        raise ValueError('Hook exige identidade completa por evento')


def _identidade(s):
    if not s.st_ino: raise ValueError('Identidade de arquivo indisponível')
    return str(s.st_dev) + ':' + str(s.st_ino)


def _sincronizar(f, d):
    arquivo = Path(f['arquivo'])
    assinatura = json.dumps({k: f.get(k) for k in ('provider', 'projeto', 'sessao', 'mesa', 'arquivo', 'formato', 'autoridade', 'binding', 'capability')}, sort_keys=True)
    antigo = d.execute('SELECT assinatura,identidade,cursor,ancora,tamanho_ancora,estado FROM fontes_console WHERE origem=?', (f['origem'],)).fetchone()
    eventos = []
    adapter = Transcrito(f['mesa'], eventos.append) if f['formato'] == 'codex_rollout' else Eventos(f['provider'], f['mesa'], inicio_vinculado=True)
    with arquivo.open('rb') as h:
        import os
        st = os.fstat(h.fileno()); identidade = _identidade(st)
        if antigo and (antigo[0] != assinatura or antigo[1] != identidade or st.st_size < antigo[2]):
            raise ValueError('Fonte alterada, substituída ou truncada')
        if antigo:
            cursor, ancora, n, estado = antigo[2:]
            if hashlib.sha256(h.read(n)).hexdigest() != ancora: raise ValueError('Cabeçalho da fonte alterado')
            carregado = _desempacotar(json.loads(estado))
            h.seek(max(0, cursor - 4096))
            if hashlib.sha256(h.read(min(cursor, 4096))).hexdigest() != carregado.pop('_checkpoint'):
                raise ValueError('Conteúdo anterior ao cursor alterado')
            for k, v in carregado.items(): setattr(adapter, k, v)
        else:
            primeira = h.readline(MAX_LINHA + 1)
            if not primeira.endswith(b'\n') or len(primeira) > MAX_LINHA: raise ValueError('Cabeçalho incompleto ou acima do limite')
            r = json.loads(primeira); _validar(r, f, inicial=True)
            n = len(primeira); ancora = hashlib.sha256(primeira).hexdigest()
            # Vínculo é emitido mesmo no attach em tail, sem inventar trabalho passado.
            adapter.sessao = f['sessao']
            eventos.append({'tipo': 'ocioso', 'fonte': f['provider'], 'agente': f['mesa'], 'sessao': f['sessao'],
                            'ferramenta': 'Console', 'resumo': 'fonte externa vinculada'})
            cursor = 0 if f.get('historico', False) else st.st_size
            if cursor and not primeira.endswith(b'\n'): raise ValueError('Cabeçalho incompleto')
            # Não comece no meio de linha escrita ao anexar.
            if cursor:
                h.seek(cursor - 1)
                if h.read(1) != b'\n':
                    h.seek(max(n, cursor - MAX_LINHA))
                    trecho = h.read(cursor - h.tell())
                    indice = trecho.rfind(b'\n')
                    cursor = max(n, cursor - len(trecho) + indice + 1) if indice >= 0 else n
        h.seek(cursor); trecho = h.read(MAX_LEITURA)
        limite = trecho.rfind(b'\n') + 1
        if not limite and len(trecho) > MAX_LINHA: raise ValueError('Linha acima do limite')
        for linha in trecho[:limite].splitlines():
            if len(linha) > MAX_LINHA: raise ValueError('Linha acima do limite')
            r = json.loads(linha); _validar(r, f)
            if r.get('type') == 'office_session': continue
            inicio_eventos = len(eventos)
            if f['formato'] == 'hooks':
                if not isinstance(r.get('evento_id'), str) or not r['evento_id']: raise ValueError('Hook exige evento_id')
                eventos.append({**r, 'agente': f['mesa']})
            elif f['formato'] == 'codex_rollout': adapter.consumir(r)
            else: eventos.extend(adapter.converter(r))
            for ev in eventos[inicio_eventos:]:
                if r.get('timestamp') or r.get('ts'): ev['ts'] = r.get('timestamp') or r.get('ts')
                if f.get('historico', False) and antigo is None:
                    ev['historico'] = True
                    ev.setdefault('ts', '1970-01-01T00:00:00+00:00')
        cursor += limite
        atual = arquivo.stat()
        if _identidade(atual) != identidade or atual.st_size < cursor: raise ValueError('Arquivo trocado durante leitura')
        h.seek(max(0, cursor - 4096))
        checkpoint = hashlib.sha256(h.read(min(cursor, 4096))).hexdigest()
    importados = 0
    for ev in eventos:
        ev = {**ev, 'fonte': f['provider'], 'sessao': f['sessao'], 'projeto': f['projeto'], 'projeto_id': f['projeto_id'], 'origem': f['origem']}
        fase = ev.get('hook_fase') or ev.get('fase')
        if not fase and ev.get('operacao_id'):
            fase = ('start' if ev.get('ferramenta') == 'Console' else 'tool_start') if ev.get('inicio') else 'tool_end' if ev.get('operacao_estado') == 'concluido' else None
        if not fase and ev.get('tipo') == 'ocioso' and ev.get('ferramenta') != 'Console': fase = 'stop'
        if fase and f.get('autoridade') and f['formato'] != f['autoridade']:
            if f['autoridade'] != 'hooks' or prefer_hooks(f.get('binding', {}), f.get('capability', {}), {'hook_fase': fase}): continue
        out = normalizar(ev)
        for k in ('projeto', 'projeto_id', 'origem', 'evento_id', 'historico', 'hook_fase'):
            if k in ev: out[k] = ev[k]
        # IDs nativos compartilhados permitem dedup entre hook e stream.
        chave = ev.get('evento_id') or (ev.get('operacao_id'), ev.get('operacao_estado'), ev.get('tipo'))
        if not ev.get('evento_id') and not ev.get('operacao_id'):
            chave = hashlib.sha256(json.dumps(ev, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        chave = json.dumps([f['provider'], f['projeto'], f['sessao'], chave], sort_keys=True)
        anterior = d.execute('SELECT evento_id FROM fontes_console_dedup WHERE chave=?', (chave,)).fetchone()
        if anterior:
            if not anterior[0]: continue  # Legacy ledger without a provable event binding.
            linha = d.execute('SELECT dados FROM evento WHERE id=?', anterior).fetchone()
            if not linha: raise ValueError('Ledger perdeu evento vinculado')
            previo = json.loads(linha[0])
            if fase != 'tool_end' or out.get('ok') is not False or previo.get('ok') is False: continue
            # Append a correction for SSE clients; never downgrade a recorded failure.
            previo.update({k: out[k] for k in ('ok', 'codigo', 'erro') if k in out})
            previo.update(ts=out['ts'], fonte_correction=True)
            out = previo
        cur = d.execute('INSERT INTO evento(ts,agente,ferramenta,dados) VALUES (?,?,?,?)',
                        (out['ts'], out['agente'], out['ferramenta'], json.dumps(out, ensure_ascii=False)))
        d.execute('INSERT INTO fontes_console_dedup(chave,evento_id) VALUES (?,?) ON CONFLICT(chave) DO UPDATE SET evento_id=excluded.evento_id',
                  (chave, cur.lastrowid))
        importados += 1
    estado = {k: v for k, v in adapter.__dict__.items() if k not in ('emitir', 'consumo', 'claude', 'resto')}
    estado['_checkpoint'] = checkpoint
    d.execute('INSERT INTO fontes_console VALUES (?,?,?,?,?,?,?) ON CONFLICT(origem) DO UPDATE SET cursor=excluded.cursor,estado=excluded.estado',
              (f['origem'], assinatura, identidade, cursor, ancora, n, json.dumps(_empacotar(estado))))
    return {'origem': f['origem'], 'importados': importados, 'cursor': cursor, 'mais': cursor < st.st_size}


def sincronizar(config, banco):
    """Uma rodada atômica para todas as fontes; erro não avança nenhum cursor."""
    if not isinstance(config, dict) or not isinstance(config.get('fontes'), list) or len(config['fontes']) > 32:
        raise ValueError('Config exige lista fontes (máximo 32)')
    fontes = [_fonte(f) for f in config['fontes']]
    if len({f['origem'] for f in fontes}) != len(fontes): raise ValueError('Origem duplicada')
    if len({f['arquivo'] for f in fontes}) != len(fontes): raise ValueError('Arquivo duplicado')
    grupos = {}
    for f in fontes: grupos.setdefault((f['provider'], f['projeto'], f['sessao']), []).append(f)
    for grupo in grupos.values():
        if len(grupo) < 2: continue
        autoridades = {f.get('autoridade') for f in grupo}
        if len(autoridades) != 1 or None in autoridades: raise ValueError('Transportes concorrentes exigem autoridade explícita')
        autoridade = next(iter(autoridades))
        if sum(f['formato'] == autoridade for f in grupo) != 1: raise ValueError('Autoridade deve selecionar exatamente uma fonte')
        if autoridade == 'hooks':
            for f in grupo:
                if not f.get('binding') or not f.get('capability'): raise ValueError('Autoridade hooks exige binding/capability verificados')
                if not prefer_hooks(f['binding'], f['capability'], {'hook_fase': 'start'}): raise ValueError('Hooks não ativos/verificados para a versão')
    with closing(sqlite3.connect(banco, timeout=5)) as d, d:
        d.executescript(esquema.ESQUEMA)
        d.executescript('CREATE TABLE IF NOT EXISTS fontes_console(origem TEXT PRIMARY KEY, assinatura TEXT, identidade TEXT, cursor INTEGER, ancora TEXT, tamanho_ancora INTEGER, estado TEXT); CREATE TABLE IF NOT EXISTS fontes_console_dedup(chave TEXT PRIMARY KEY, evento_id INTEGER);')
        if 'evento_id' not in {r[1] for r in d.execute('PRAGMA table_info(fontes_console_dedup)')}:
            d.execute('ALTER TABLE fontes_console_dedup ADD COLUMN evento_id INTEGER')
            d.commit()
        d.execute('BEGIN IMMEDIATE')
        return [_sincronizar(f, d) for f in fontes]


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config', required=True, type=Path); p.add_argument('--banco', required=True, type=Path)
    a = p.parse_args(argv)
    try:
        if a.config.stat().st_size > 65536: raise ValueError('Config acima do limite')
        print(json.dumps(sincronizar(json.loads(a.config.read_text(encoding='utf-8')), a.banco), ensure_ascii=False))
        return 0
    except (OSError, ValueError, TypeError, sqlite3.Error) as erro:
        print('Observação interrompida: ' + str(erro), file=sys.stderr)
        return 2


if __name__ == '__main__': raise SystemExit(main())
