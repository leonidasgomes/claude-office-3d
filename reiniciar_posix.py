"""Reinício POSIX sem lsof: só encerra listeners Linux desta instalação."""
import http.client
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
import warnings

import configuracao

RAIZ = Path(__file__).resolve().parent


def porta_alvo(args):
    porta = configuracao.carregar()["porta"]
    if "--porta" in args:
        try:
            porta = int(args[args.index("--porta") + 1])
        except (IndexError, ValueError) as exc:
            raise ValueError("uso: reiniciar_escritorio.sh [celular] [--porta N] [--sem-https]") from exc
    if not 1 <= int(porta) <= 65535:
        raise ValueError("A porta deve estar entre 1 e 65535.")
    return int(porta)


def ocupada(porta):
    try:
        with socket.create_connection(("127.0.0.1", porta), timeout=0.2):
            return True
    except OSError:
        return False


def identidade(pid):
    """Confirma interpretador, script e pasta, incluindo caminhos com espaços."""
    proc = Path("/proc") / str(pid)
    try:
        comando = (proc / "cmdline").read_bytes().split(b"\0")
        comando = [os.fsdecode(item) for item in comando if item]
        if not (proc / "exe").resolve().name.startswith("python"):
            return None
        pasta = (proc / "cwd").resolve(strict=True)
        if pasta != RAIZ:
            return None
        argumentos = comando[1:]
        while argumentos and argumentos[0] in ("-u", "-B", "-I", "-E", "-s"):
            argumentos.pop(0)
        if not argumentos or (pasta / argumentos[0]).resolve() != RAIZ / "servidor.py":
            return None
        # Campo 22 de /proc/PID/stat: início do processo, para detectar PID reutilizado.
        inicio = (proc / "stat").read_text().rsplit(")", 1)[1].split()[19]
        return inicio
    except (OSError, IndexError):
        return None


def servidores_da_porta(porta):
    if not sys.platform.startswith("linux"):
        raise ValueError("Porta ocupada. Neste sistema, encerre o Office no terminal antes de reiniciar.")
    inodes = set()
    for nome in ("tcp", "tcp6"):
        tabela = Path("/proc/net") / nome
        if not tabela.exists():
            continue
        for linha in tabela.read_text().splitlines()[1:]:
            campos = linha.split()
            if campos[3] == "0A" and int(campos[1].rsplit(":", 1)[1], 16) == porta:
                inodes.add(campos[9])
    encontrados = set()
    processos = {}
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            descriptores = list((proc / "fd").iterdir())
        except OSError:
            continue
        sockets = set()
        for fd in descriptores:
            try:
                sockets.add(os.readlink(fd))
            except OSError:
                continue
        usados = {inode for inode in inodes if "socket:[" + inode + "]" in sockets}
        if not usados:
            continue
        token = identidade(int(proc.name))
        if token is None:
            raise ValueError("Porta ocupada por outro processo; nenhum processo foi encerrado.")
        processos[int(proc.name)] = token
        encontrados.update(usados)
    if not inodes or encontrados != inodes or not processos:
        raise ValueError("Não foi possível confirmar o dono da porta; nenhum processo foi encerrado.")
    return processos


def encerrar(porta):
    if not ocupada(porta):
        return
    processos = servidores_da_porta(porta)
    for pid, token in processos.items():
        if identidade(pid) != token:
            raise ValueError("O processo mudou durante a verificação; reinício cancelado.")
        # pidfd evita sinalizar outro processo caso o PID seja reutilizado.
        if hasattr(os, "pidfd_open") and hasattr(signal, "pidfd_send_signal"):
            fd = os.pidfd_open(pid)
            try:
                if identidade(pid) != token:
                    raise ValueError("O processo mudou durante a verificação; reinício cancelado.")
                signal.pidfd_send_signal(fd, signal.SIGTERM)
            finally:
                os.close(fd)
        else:
            os.kill(pid, signal.SIGTERM)
    prazo = time.monotonic() + 10
    while ocupada(porta) and time.monotonic() < prazo:
        time.sleep(0.1)
    if ocupada(porta):
        raise ValueError("O servidor anterior não liberou a porta; reinício cancelado.")


def iniciar(args, porta):
    log = RAIZ / "dados" / "reinicio.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("ab") as saida:
        processo = subprocess.Popen(
            [sys.executable, "-u", str(RAIZ / "servidor.py"), "--sem-navegador", *args],
            cwd=RAIZ, stdin=subprocess.DEVNULL, stdout=saida, stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    prazo = time.monotonic() + 20
    while processo.poll() is None and time.monotonic() < prazo:
        conexao = http.client.HTTPConnection("127.0.0.1", porta, timeout=0.5)
        try:
            conexao.request("GET", "/")
            resposta = conexao.getresponse()
            resposta.read()
            if resposta.status == 200:
                # Só aceite a resposta se o nosso filho for o listener esperado.
                if sys.platform.startswith("linux"):
                    try:
                        confirmado = processo.pid in servidores_da_porta(porta)
                    except (OSError, ValueError):
                        confirmado = False
                    if not confirmado:
                        break
                if processo.poll() is None:
                    print(f"Pronto: http://127.0.0.1:{porta}/ (PID {processo.pid}; log: {log})")
                    # O filho foi deixado em segundo plano de propósito e não tem
                    # pipes abertos; não aguardar seu término no launcher.
                    with warnings.catch_warnings():
                        warnings.filterwarnings("ignore", category=ResourceWarning,
                                                message="subprocess .* is still running")
                        del processo
                    return
        except (OSError, http.client.HTTPException):
            pass
        finally:
            conexao.close()
        time.sleep(0.1)
    if processo.poll() is None:
        processo.terminate()
        try:
            processo.wait(timeout=5)
        except subprocess.TimeoutExpired:
            processo.kill()
            processo.wait()
    raise ValueError(f"O servidor não iniciou. Confira {log}")


def main(args=None):
    try:
        args = list(sys.argv[1:] if args is None else args)
        porta = porta_alvo(args)
        encerrar(porta)
        iniciar(args, porta)
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
