"""Acompanhamento local somente leitura; não despacha nem consulta modelos."""
import argparse
from contextlib import closing
from datetime import datetime
import json
import os
from pathlib import Path
import sqlite3
import sys
import time

from ciclo_gdd import coordenador_vivo
from gestao_cli import pasta_dados


def ler(projeto):
    pasta = pasta_dados(projeto)
    estado = json.loads((pasta / 'ciclo.json').read_text(encoding='utf-8'))
    reservas = []
    banco = pasta / 'tarefas.db'
    if banco.exists():
        with closing(sqlite3.connect(banco.resolve().as_uri() + '?mode=ro', uri=True, timeout=2)) as db:
            db.row_factory = sqlite3.Row
            reservas = [dict(r) for r in db.execute(
                'SELECT cartao,equipe,estado FROM reserva ORDER BY cartao')]
    publicacoes = []
    for arquivo in sorted((pasta / 'publicacoes').glob('*.json')):
        r = json.loads(arquivo.read_text(encoding='utf-8'))
        if r.get('estado') == 'publicado' and r.get('pr'):
            publicacoes.append({'cartao': r['cartao'], 'pr': r['pr']})
    return estado, reservas, publicacoes


def texto(projeto, estado, reservas, publicacoes, vivo, agora):
    restante = max(0, int((estado.get('limite', agora) - agora) / 60))
    linhas = [f'Projeto: {projeto}',
              f'Ciclo: {estado.get("estado", "indisponivel")} | janela restante: {restante} min',
              'Coordenador: ' + ('processo confirmado' if vivo else 'não confirmado; conferir Gestão'),
              'Próxima ação: ' + (estado.get('proxima_acao') or 'não registrada')]
    if estado.get('motivo'):
        linhas.append('Último motivo registrado: ' + estado['motivo'])
    cartoes = estado.get('cartoes') or []
    if cartoes:
        titulo = 'Despacho atual' if estado['estado'] == 'implementando' else 'Candidatos em avaliação (não são equipes executando)'
        linhas.append(titulo + ': ' + ', '.join(f'#{c["cartao"]} {c["equipe"]}' for c in cartoes))
    linhas.append('Reservas registradas (estado não comprova processo ativo):')
    linhas.extend(f'  #{r["cartao"]} | {r["equipe"]} | {r["estado"]}' for r in reservas)
    linhas.append('PRs publicados pelo host:')
    linhas.extend(f'  #{r["cartao"]}: {r["pr"]}' for r in publicacoes)
    return '\n'.join(linhas)


def acompanhar(projeto, uma_vez=False):
    anterior = None
    sessao = None
    proxima_verificacao = 0
    vivo = False
    print('ESCRITÓRIO — ACOMPANHAMENTO AO VIVO\n'
          'Atualiza a cada 2 segundos, sem chamadas de IA.\n'
          'Converse na janela do CEO. Fechar esta janela não para as equipes.', flush=True)
    while True:
        agora = time.time()
        try:
            estado, reservas, publicacoes = ler(projeto)
            if sessao is None:
                sessao = estado['id']
            if estado['id'] != sessao:
                print('A sessão mudou. Reabra o acompanhamento para conferir o novo ciclo.', flush=True)
                return 0
            if agora >= proxima_verificacao:
                vivo = coordenador_vivo(projeto, estado)
                proxima_verificacao = agora + 30
            mensagem = texto(projeto, estado, reservas, publicacoes, vivo, agora)
        except (OSError, ValueError, KeyError, sqlite3.Error) as exc:
            mensagem = 'Leitura indisponível; não é prova de parada das equipes: ' + str(exc)
        if mensagem != anterior:
            print('\n[' + datetime.fromtimestamp(agora).strftime('%H:%M:%S') + ']\n' + mensagem, flush=True)
            anterior = mensagem
        if uma_vez:
            return 0
        time.sleep(2)


def abrir(projeto):
    """Janela independente da TUI; falha de exibição não interrompe o host."""
    if os.name != 'nt':
        return
    import subprocess
    try:
        subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--projeto', str(projeto)],
                         cwd=Path(__file__).resolve().parent,
                         creationflags=subprocess.CREATE_NEW_CONSOLE)
    except OSError as exc:
        print('Acompanhamento visual indisponível: ' + str(exc), file=sys.stderr)


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--projeto', required=True, type=Path)
    p.add_argument('--uma-vez', action='store_true')
    a = p.parse_args()
    try:
        return acompanhar(a.projeto.resolve(), a.uma_vez)
    except KeyboardInterrupt:
        return 0


if __name__ == '__main__':
    sys.exit(main())
