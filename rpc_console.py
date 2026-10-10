"""Cliente JSON-RPC por stdio para os protocolos oficiais dos consoles.

Sem porta aberta, shell ou impressão de mensagens de autenticação. Requisições
do servidor não autorizadas são rejeitadas; aprovações não são aceitas implicitamente.
"""
import json
import queue
import subprocess
import threading
import time


class Rpc:
    def __init__(self, comando, cwd=None, notificar=None, aprovar=None):
        self.processo = subprocess.Popen(comando, cwd=cwd, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            encoding="utf-8", errors="replace", bufsize=1)
        self.fila = queue.Queue()
        self.id = 0
        self.notificar, self.aprovar = notificar, aprovar
        self.trava = threading.Lock()
        self.thread = threading.Thread(target=self._ler, daemon=True)
        self.thread.start()

    def _ler(self):
        try:
            for linha in self.processo.stdout:
                try:
                    msg = json.loads(linha)
                    if isinstance(msg, dict):
                        self.fila.put(msg)
                except ValueError:
                    pass
        finally:
            self.fila.put(None)

    def enviar(self, mensagem):
        with self.trava:
            self.processo.stdin.write(json.dumps(mensagem, ensure_ascii=False) + "\n")
            self.processo.stdin.flush()

    def notificar_servidor(self, metodo, params=None):
        self.enviar({"method": metodo, "params": params or {}})

    def receber(self, timeout=30):
        try:
            msg = self.fila.get(timeout=timeout)
        except queue.Empty as exc:
            raise TimeoutError("Console não respondeu no prazo") from exc
        if msg is None:
            raise RuntimeError("Console encerrou o protocolo")
        if "method" in msg and "id" in msg:
            if self.aprovar:
                resultado = self.aprovar(msg)
                self.enviar({"id": msg["id"], "result": resultado})
            else:
                self.enviar({"id": msg["id"], "error": {"code": -32601, "message": "Ação requer autorização do cliente"}})
        elif "method" in msg and self.notificar:
            self.notificar(msg)
        return msg

    def chamar(self, metodo, params=None, timeout=30):
        self.id += 1
        id_ = self.id
        mensagem = {"id": id_, "method": metodo}
        if params is not None:
            mensagem["params"] = params
        self.enviar(mensagem)
        fim = time.monotonic() + timeout
        while True:
            restante = fim - time.monotonic()
            if restante <= 0:
                raise TimeoutError("Console não respondeu no prazo")
            msg = self.receber(restante)
            if msg.get("id") == id_ and "method" not in msg:
                if "error" in msg:
                    raise RuntimeError(f"Console rejeitou {metodo}")
                return msg.get("result")

    def fechar(self):
        self.processo.stdin.close()
        try:
            self.processo.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.processo.terminate()
            try:
                self.processo.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.processo.kill()
                self.processo.wait(timeout=5)
        self.thread.join(timeout=2)
        self.processo.stdout.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.fechar()
