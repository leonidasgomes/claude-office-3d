"""Admissão e reservas locais da máquina, sem baixar/carregar modelos.

Falta de medição bloqueia a execução. A reserva é global para a instalação,
independente do projeto; processos mortos são conferidos antes de liberar vagas.
"""
import csv
import ctypes
import io
import math
import os
from pathlib import Path
import sqlite3
import subprocess
import time
import uuid
from contextlib import closing, contextmanager
from memoria_local import medir_ollama, medir_gpu, verificar_memoria

PESADOS = {"unrealeditor.exe", "unrealeditor-cmd.exe", "unrealbuildtool.exe",
           "shadercompileworker.exe", "cl.exe", "link.exe", "blender.exe"}


def contadores_cpu():
    """Idle/total acumulados; não presume CPU livre quando a leitura falha."""
    if os.name=='nt':
        kernel=ctypes.windll.kernel32
        processadores=kernel.GetActiveProcessorCount(0xffff)
        if not 1<=processadores<=64:
            raise OSError('Medição CPU entre grupos de processadores ainda indisponível')
        class Tempo(ctypes.Structure):
            _fields_=[('baixo',ctypes.c_uint32),('alto',ctypes.c_uint32)]
        idle,nucleo,usuario=Tempo(),Tempo(),Tempo()
        if not kernel.GetSystemTimes(ctypes.byref(idle),ctypes.byref(nucleo),ctypes.byref(usuario)):
            raise OSError('Não foi possível medir CPU')
        ticks=lambda t:(t.alto<<32)|t.baixo
        return ticks(idle),ticks(nucleo)+ticks(usuario)
    arquivo=Path('/proc/stat')
    if not arquivo.is_file():raise OSError('Medição CPU indisponível neste sistema')
    with arquivo.open() as f:campos=f.readline().split()
    if not campos or campos[0]!='cpu' or len(campos)<9:raise OSError('Contadores CPU inválidos')
    valores=[int(x) for x in campos[1:9]]  # guest já está incluído em user/nice
    return valores[3]+valores[4],sum(valores)


def percentual_cpu(antes,depois):
    if any(type(x) is not int or x<0 for x in (*antes,*depois)):
        raise OSError('Contadores CPU inválidos')
    idle=depois[0]-antes[0];total=depois[1]-antes[1]
    if total<=0 or idle<0 or idle>total:raise OSError('Intervalo CPU indisponível ou inconsistente')
    return 100*(total-idle)/total


def medir_cpu(intervalo=0.25):
    antes=contadores_cpu();time.sleep(intervalo)
    return percentual_cpu(antes,contadores_cpu())


def medir_host():
    cpu=medir_cpu()
    if os.name == "nt":
        class Mem(ctypes.Structure):
            _fields_ = [("tamanho", ctypes.c_ulong), ("carga", ctypes.c_ulong),
                        ("total", ctypes.c_ulonglong), ("livre", ctypes.c_ulonglong),
                        ("page", ctypes.c_ulonglong), ("page_livre", ctypes.c_ulonglong),
                        ("virtual", ctypes.c_ulonglong), ("virtual_livre", ctypes.c_ulonglong),
                        ("extendido", ctypes.c_ulonglong)]
        m = Mem()
        m.tamanho = ctypes.sizeof(Mem)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
            raise OSError("Não foi possível medir RAM")
        r = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True,
                           text=True, errors="replace", timeout=10, check=True)
        processos = [linha[0].lower() for linha in csv.reader(io.StringIO(r.stdout)) if linha]
        return {"ram_livre_gb": m.livre / 2**30, "pesados": sorted(set(processos) & PESADOS), 'cpu_uso_pct':cpu}
    memoria = Path("/proc/meminfo")
    if not memoria.is_file():
        raise OSError("Medição automática indisponível neste sistema")
    campos = {linha.split(":", 1)[0]: linha.split(":", 1)[1].strip().split()[0]
              for linha in memoria.read_text().splitlines()}
    r = subprocess.run(["ps", "-eo", "comm="], capture_output=True, text=True, timeout=10, check=True)
    pesados = {x.removesuffix(".exe").lower() for x in PESADOS}
    processos = {Path(x.strip()).name.lower() for x in r.stdout.splitlines()}
    return {"ram_livre_gb": int(campos["MemAvailable"]) / 2**20,
            "pesados": sorted(processos & pesados), 'cpu_uso_pct':cpu}


def medir():
    estado=medir_host()
    estado['ollama']=medir_ollama()
    estado['gpu']=medir_gpu()
    return estado


def verificar(politica, estado=None):
    local = politica["local"]
    if not local["ativo"]:
        raise ValueError("Modelo local desativado no projeto")
    estado = medir() if estado is None else estado
    ram = estado.get("ram_livre_gb")
    if not isinstance(ram, (int, float)) or isinstance(ram, bool) or not math.isfinite(ram) or not ram >= local["ram_livre_min_gb"]:
        raise ValueError("RAM livre insuficiente ou desconhecida para inferência local")
    pesados = estado.get("pesados")
    if not isinstance(pesados, list):
        raise ValueError("Estado dos processos pesados desconhecido")
    if local["bloquear_pesados"] and pesados:
        raise ValueError("Máquina ocupada: " + ", ".join(pesados))
    cpu=estado.get('cpu_uso_pct')
    if (not isinstance(cpu,(int,float)) or isinstance(cpu,bool) or not math.isfinite(cpu)
            or not 0<=cpu<=local['cpu_uso_max_pct']):
        raise ValueError('CPU ocupada ou medição desconhecida para inferência local')
    verificar_memoria(local, estado)
    return estado


def pid_vivo(pid):
    if os.name == "nt":
        kernel = ctypes.windll.kernel32
        kernel.OpenProcess.restype = ctypes.c_void_p
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            # Acesso negado não é prova de que morreu.
            return kernel.GetLastError() == 5
        codigo = ctypes.c_ulong()
        try:
            if not kernel.GetExitCodeProcess(ctypes.c_void_p(handle), ctypes.byref(codigo)):
                return True
            return codigo.value == 259
        finally:
            kernel.CloseHandle(ctypes.c_void_p(handle))
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


@contextmanager
def reservar(banco, politica, medidor=medir, vivo=pid_vivo):
    verificar(politica, medidor())
    caminho = Path(banco)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    with closing(sqlite3.connect(caminho, timeout=10)) as db, db:
        db.execute("CREATE TABLE IF NOT EXISTS local_reserva (token TEXT PRIMARY KEY, pid INTEGER, inicio REAL)")
        db.execute("BEGIN IMMEDIATE")
        if 'limite' not in {x[1] for x in db.execute('PRAGMA table_info(local_reserva)')}:
            db.execute('ALTER TABLE local_reserva ADD COLUMN limite INTEGER NOT NULL DEFAULT 1')
        for linha in db.execute("SELECT token,pid FROM local_reserva").fetchall():
            if not vivo(linha[1]):
                db.execute("DELETE FROM local_reserva WHERE token=?", (linha[0],))
        ativos, menor_limite = db.execute("SELECT count(*),min(limite) FROM local_reserva").fetchone()
        limite = min(politica['local']['max_paralelo'], menor_limite or politica['local']['max_paralelo'])
        if ativos >= limite:
            raise ValueError("Limite de inferências locais simultâneas atingido")
        verificar(politica, medidor())
        db.execute("INSERT INTO local_reserva (token,pid,inicio,limite) VALUES (?,?,?,?)",
                   (token, os.getpid(), time.time(), politica['local']['max_paralelo']))
    try:
        yield token
    finally:
        with closing(sqlite3.connect(caminho, timeout=10)) as db, db:
            db.execute("DELETE FROM local_reserva WHERE token=?", (token,))


@contextmanager
def vigiar(processo, politica, medidor=medir, intervalo=2):
    """Interrompe apenas a árvore deste console quando a medição deixa de permitir local."""
    import signal
    import threading
    parar = threading.Event()
    falhas = []
    def monitor():
        while not parar.wait(intervalo):
            if processo.poll() is not None:
                return
            try:
                verificar(politica, medidor())
            except (ValueError, OSError, subprocess.SubprocessError):
                falhas.append('Execução local interrompida: recursos insuficientes, trabalho pesado ou medição indisponível')
                if processo.poll() is None:
                    if os.name == 'nt':
                        try:
                            resultado = subprocess.run(['taskkill','/PID',str(processo.pid),'/T','/F'], capture_output=True, timeout=10)
                            if resultado.returncode and processo.poll() is None:
                                processo.terminate()
                        except (OSError, subprocess.SubprocessError):
                            if processo.poll() is None:
                                processo.terminate()
                    else:
                        os.killpg(processo.pid, signal.SIGTERM)
                return
    thread = threading.Thread(target=monitor, daemon=True); thread.start()
    try:
        yield falhas
    finally:
        parar.set(); thread.join(timeout=12)
        if falhas:
            raise ValueError(falhas[0])
