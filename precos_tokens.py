"""Equivalente teórico de API. Não estima fatura nem converte cota de plano."""
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path


def carregar(arquivo):
    arquivo = Path(arquivo)
    if not arquivo.exists():
        return []
    if arquivo.stat().st_size > 65536:
        raise ValueError('Catálogo de preços excede o limite')
    def pares(itens):
        d = {}
        for k, v in itens:
            if k in d:
                raise ValueError('Campo repetido no catálogo')
            d[k] = v
        return d
    d = json.loads(arquivo.read_text(encoding='utf-8'), object_pairs_hook=pares)
    if (not isinstance(d, dict) or set(d) != {'versao', 'tarifas'} or
        type(d['versao']) is not int or d['versao'] != 1 or
        not isinstance(d['tarifas'], list) or len(d['tarifas']) > 200):
        raise ValueError('Formato de catálogo inválido')
    tarifas = []
    for t in d['tarifas']:
        campos = {'provider', 'modelo', 'desde', 'ate', 'fonte',
                  'entrada_usd_milhao', 'cache_usd_milhao', 'saida_usd_milhao'}
        if not isinstance(t, dict) or set(t) != campos:
            raise ValueError('Tarifa inválida')
        if (t['provider'] not in ('codex', 'gemini') or
            not isinstance(t['modelo'], str) or not 1 <= len(t['modelo']) <= 200 or
            not isinstance(t['fonte'], str) or not t['fonte'].startswith('https://') or
            len(t['fonte']) > 1000):
            raise ValueError('Identidade/fonte da tarifa inválida')
        try:
            inicio, fim = (date.fromisoformat(t[k]) for k in ('desde', 'ate'))
            if inicio >= fim:
                raise ValueError('Intervalo de tarifa inválido')
            precos = []
            for k in ('entrada_usd_milhao', 'cache_usd_milhao', 'saida_usd_milhao'):
                if not isinstance(t[k], str) or len(t[k]) > 30:
                    raise ValueError('Preço deve ser decimal em texto')
                valor = Decimal(t[k])
                if not valor.is_finite() or not 0 <= valor <= 100000:
                    raise ValueError('Preço fora do limite')
                precos.append(valor)
        except (TypeError, InvalidOperation) as exc:
            raise ValueError('Preço/data inválidos') from exc
        for a in tarifas:
            if (a['provider'], a['modelo']) == (t['provider'], t['modelo']) and inicio < a['fim'] and a['inicio'] < fim:
                raise ValueError('Intervalos de tarifa sobrepostos')
        tarifas.append(dict(t, inicio=inicio, fim=fim, precos=precos))
    return tarifas


def equivalente(tarifas, provider, modelo, origem, ts, entrada, cache, saida, fonte):
    # OpenCode inclui escrita de cache na entrada sem contador normalizado próprio.
    # Não precificar isso como entrada comum. Claude não tem ledger incremental aqui.
    if provider not in ('codex', 'gemini') or origem != 'informado':
        return None
    if fonte not in ('codex.rollout/token_count.delta', 'codex.exec/turn.completed', 'gemini.result/stats'):
        return None
    if any(type(v) is not int or not 0 <= v <= 2**53 - 1 for v in (entrada, cache, saida)) or cache > entrada:
        return None
    dia = datetime.fromtimestamp(ts, timezone.utc).date()
    for t in tarifas:
        if t['provider'] == provider and t['modelo'] == modelo and t['inicio'] <= dia < t['fim']:
            a, c, s = t['precos']
            valor = (Decimal(entrada-cache)*a + Decimal(cache)*c + Decimal(saida)*s) / Decimal(1000000)
            return valor
    return None


def aplicar(db, base, arquivo,projeto_hash=None,tentativas=None):
    """Consulta por amostra: nunca aplica tarifa atual a histórico fora da validade."""
    base['precos'] = {'estado': 'sem catálogo', 'tipo': 'equivalente teórico de API', 'amostras': 0}
    try:
        tarifas = carregar(arquivo)
    except (OSError, ValueError, OverflowError):
        base['precos']['estado'] = 'catálogo inválido'
        return
    if not tarifas:
        return
    base['precos']['estado'] = 'configurado'
    grupos = {(g['provider'], g['modelo'], g['origem_modelo'], g['agente']): g for g in base['grupos']}
    for g in grupos.values():
        g.update(equivalente_api_usd=None, com_preco=0)
    somas = {}
    from consumo_providers import filtro_periodo
    where,parametros=filtro_periodo(base['desde'],base['desde']+7*86400,projeto_hash,tentativas)
    for p, m, o, a, ts, i, c, s, f in db.execute(
        'SELECT provider,modelo,origem_modelo,agente,ts,entrada,cache,saida,fonte FROM consumo WHERE '+where,
        parametros):
        valor = equivalente(tarifas, p, m, o, ts, i, c, s, f)
        if valor is not None:
            chave = (p, m, o, a)
            somas[chave] = somas.get(chave, Decimal(0)) + valor
            grupos[chave]['com_preco'] += 1
            base['precos']['amostras'] += 1
    for chave, valor in somas.items():
        grupos[chave]['equivalente_api_usd'] = format(valor, 'f')
