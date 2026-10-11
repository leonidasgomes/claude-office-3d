"""Estado local para a cena; não consulta modelos/GitHub nem despacha trabalho."""
from contextlib import closing
import json
import sqlite3
import time

from gestao_cli import pasta_dados
from kanban_painel import escolher


def vista(projetos, ident):
    selecao = escolher(projetos, ident, 'acompanhamento')
    if not selecao or selecao[2]:
        return {'ok': False, 'erro': 'Projeto desconhecido ou desativado'}
    raiz, cfg, publico = selecao[0]
    pasta = pasta_dados(raiz)
    agora = time.time()
    saida = {'ok': True, 'projeto_id': publico['id'], 'ts': agora,
             'ciclo': {'estado': 'desligado'}, 'tarefas': [], 'publicacoes': []}
    try:
        arquivo = pasta/'ciclo.json'
        if arquivo.exists():
            r = json.loads(arquivo.read_text(encoding='utf-8'))
            saida['ciclo'] = {k:r.get(k) for k in (
                'estado','inicio','limite','continuo','atualizado','objetivo','cartoes','motivo','proxima_acao')}
        banco = pasta/'tarefas.db'
        if banco.exists():
            with closing(sqlite3.connect(banco.resolve().as_uri()+'?mode=ro', uri=True, timeout=2)) as db:
                db.row_factory = sqlite3.Row
                saida['tarefas'] = [dict(r) for r in db.execute(
                    'SELECT cartao,equipe,estado FROM reserva ORDER BY cartao')]
        for arquivo in sorted((pasta/'publicacoes').glob('*.json')):
            r = json.loads(arquivo.read_text(encoding='utf-8'))
            numero = str(r.get('pr','')).rsplit('/',1)[-1]
            esperado = f'https://github.com/{cfg["kanban"]["repo"]}/pull/{numero}'
            if r.get('estado')=='publicado' and numero.isdigit() and r.get('pr')==esperado:
                saida['publicacoes'].append({'cartao':r['cartao'],'pr':esperado})
        return saida
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error):
        return {'ok':False, 'projeto_id':publico['id'], 'erro':'Estado local indisponível; confira Gestão'}
