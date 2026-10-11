"""SSE de leitura do diário existente; sem modelos, despacho ou presença inferida."""
from contextlib import closing
import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path

CLIENTES = threading.BoundedSemaphore(8)


def lote(arquivo, desde, maximo=200):
    """Cursor crescente: nunca salta eventos ao exceder uma página."""
    if not Path(arquivo).is_file():
        return 0, []
    with closing(sqlite3.connect(Path(arquivo).resolve().as_uri() + '?mode=ro', uri=True, timeout=2)) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='evento'").fetchone():
            return 0, []
        total = db.execute('SELECT COALESCE(MAX(id),0) FROM evento').fetchone()[0]
        rows = db.execute('SELECT id,dados FROM evento WHERE id>? ORDER BY id LIMIT ?',
                          (desde, max(1, min(200, maximo)))).fetchall()
    eventos = []
    for ident, dados in rows:
        try:
            valor = json.loads(dados)
            if not isinstance(valor, dict):
                valor = {}
        except (ValueError, TypeError):
            valor = {}
        # Mesmo um registro inválido avança o cursor, sem criar atividade.
        eventos.append((ident, valor))
    return total, eventos


def versao_gestao(raiz):
    fotos = []
    for pasta in sorted((Path(raiz) / 'dados' / 'gestao').glob('*'))[:100]:
        if pasta.is_symlink() or not pasta.is_dir():
            continue
        for nome in ('ciclo.json', 'tarefas.db', 'tarefas.db-wal'):
            try:
                st = (pasta / nome).stat()
                fotos.append((pasta.name, nome, st.st_mtime_ns, st.st_size))
            except OSError:
                pass
    return hashlib.sha256(json.dumps(fotos).encode()).hexdigest()


def servir(handler, arquivo, desde, raiz, duracao=120):
    if not CLIENTES.acquire(blocking=False):
        return handler.responder({'erro': 'Limite de conexões ao vivo; usando consultas'}, codigo=503)
    try:
        handler.connection.settimeout(10)
        handler.send_response(200)
        handler.send_header('Content-Type', 'text/event-stream; charset=utf-8')
        handler.send_header('Cache-Control', 'no-cache, no-store')
        handler.send_header('X-Accel-Buffering', 'no')
        handler.send_header('Connection', 'close')
        handler.end_headers()
        handler.close_connection = True
        def enviar(tipo, dados, ident=None):
            texto = (f'id: {ident}\n' if ident is not None else '')
            texto += f'event: {tipo}\ndata: {json.dumps(dados, ensure_ascii=False)}\n\n'
            handler.wfile.write(texto.encode('utf-8')); handler.wfile.flush()
        limite = time.monotonic() + duracao
        batida = 0
        versao = None
        while time.monotonic() < limite:
            total, eventos = lote(arquivo, desde)
            if total < desde:
                enviar('reiniciar', {'total': total})
                return
            for ident, evento in eventos:
                enviar('evento', evento, ident)
                desde = ident
            agora = time.monotonic()
            if agora >= batida:
                nova = versao_gestao(raiz)
                if nova != versao:
                    enviar('gestao', {'versao': nova}); versao = nova
                enviar('batida', {'cursor': desde})
                batida = agora + 15
            if len(eventos) < 200:
                time.sleep(1)
    except (OSError, sqlite3.Error):
        pass  # Desconexão/DB ocupado: EventSource reconecta; REST continua disponível.
    finally:
        CLIENTES.release()
