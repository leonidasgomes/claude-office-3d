"""Teste do bloqueio de arquivos estáticos (Handler.caminho_bloqueado + rede.HandlerSeguro.servir_estatico/do_HEAD).

Uso: python -W error ferramentas/testar_estaticos.py
Sobe o Handler do servidor em 127.0.0.1, porta aleatória, servindo uma pasta TEMPORÁRIA com dados/ (sessões, tokens),
scripts, documentos, pastas ocultas e arquivos legítimos (js, css, png, sw.js, vendor/three/..., nomes com vários pontos).
Pedidos crus por socket (sem a validação do http.client), em GET e HEAD: nenhum contorno pode servir dados/, scripts,
documentos ou pastas ocultas (codificação %xx, %5c, //, /./, /x/../, "dados.", "dados ", ::$DATA, NUL, maiúsculas,
UTF-8 inválido, URL absoluta, query/fragmento, junção/symlink para dados/ ou para fora); os arquivos legítimos e as rotas
que não passam pelo servir_estatico (/manifest.webmanifest, /eventos) continuam funcionando. Não toca em dados/ de verdade.
"""
import inspect
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent   # pasta do servidor.py (público: raiz; privado: "office one")
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ.parent))
import banco  # noqa: E402
import rede  # noqa: E402
import servidor  # noqa: E402

feitos, falhas = [], []
SEGREDO = b"SEGREDO-NAO-SERVIR"
LEGITIMO = b"LEGITIMO-OK"


def checar(nome, cond, info=""):
    if cond:
        feitos.append(nome)
        print("  ok:", nome)
    else:
        falhas.append(nome)
        print("  FALHOU:", nome, str(info)[:300])


def montar(pasta):
    """Pasta servida: segredos (dados/, scripts, docs, ocultos) e arquivos legítimos."""
    for rel in ["dados/dispositivos.json", "dados/saude.json", "dados/acoes.jsonl", "dados/grafo/base/src/fonte.cpp",
                "servidor.py", "LEIAME.md", "notas.txt", "abrir.sh", "abrir.bat", ".git/config", ".env",
                "vendor/.oculto/x.js", "fora/segredo.js"]:
        p = pasta / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(SEGREDO)
    for rel in ["escritorio.js", "estilo.css", "icone-192.png", "sw.js", "vendor/three/build/three.module.js",
                "vendor/three/examples/jsm/controls/OrbitControls.js", "a.b.c.min.js", "manifest.webmanifest.js",
                "ícone ação.css", "dadosx/ok.js", "x.dados/ok.js"]:
        p = pasta / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(LEGITIMO)


def criar_juncao(link, alvo):
    """Junção (Windows, sem privilégio) ou symlink (Linux/macOS). False se o sistema não deixar."""
    try:
        if os.name == "nt":
            r = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(alvo)], capture_output=True)
            return r.returncode == 0
        os.symlink(alvo, link, target_is_directory=True)
        return True
    except OSError:
        return False


def pedir(porta, metodo, alvo):
    """Pedido HTTP cru (o alvo vai como está na linha de pedido). Devolve (status, corpo)."""
    with socket.create_connection(("127.0.0.1", porta), timeout=10) as s:
        s.sendall(metodo.encode() + b" " + alvo + b" HTTP/1.1\r\nHost: 127.0.0.1:" + str(porta).encode()
                  + b"\r\nConnection: close\r\n\r\n")
        dados = b""
        while True:
            pedaco = s.recv(65536)
            if not pedaco:
                break
            dados += pedaco
    cab, _, corpo = dados.partition(b"\r\n\r\n")
    try:
        status = int(cab.split(b" ", 2)[1])
    except (IndexError, ValueError):
        status = 0
    return status, corpo


def main():
    bloqueia_json = "'.json'" in inspect.getsource(servidor.Handler.caminho_bloqueado) or \
        '".json"' in inspect.getsource(servidor.Handler.caminho_bloqueado)
    guardar = servidor.Handler.rede
    nomes_banco = [n for n in ("ARQ", "ARQ_ANTIGO", "EVENTOS_JSONL") if hasattr(banco, n)]
    guardar_banco = {n: getattr(banco, n) for n in nomes_banco}
    srv = None
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        pasta, fora = base / "site", base / "fora_do_site"
        pasta.mkdir()
        fora.mkdir()
        (fora / "segredo.js").write_bytes(SEGREDO)
        montar(pasta)
        juncao_dados = criar_juncao(pasta / "atalho", pasta / "dados")
        juncao_fora = criar_juncao(pasta / "saida", fora)
        for n in nomes_banco:   # /eventos sem tocar no banco de verdade
            setattr(banco, n, base / f"banco_{n.lower()}")
        try:
            r = rede.Rede(pasta, False, False)
            r.arq_acoes = base / "acoes.jsonl"
            servidor.Handler.rede = r
            srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(servidor.Handler, directory=str(pasta)))
            porta = srv.server_address[1]
            threading.Thread(target=srv.serve_forever, daemon=True).start()

            print("contornos que NÃO podem servir nada sensível (GET e HEAD)")
            ataques = [
                b"/dados/dispositivos.json", b"/dados/", b"/dados", b"/DADOS/saude.json", b"/Dados/acoes.jsonl",
                b"/%64ados/dispositivos.json", b"/%44ADOS/dispositivos.json", b"/dados%2fdispositivos.json",
                b"/dados%5cdispositivos.json", b"/%5cdados%5cdispositivos.json", b"//dados/dispositivos.json",
                b"///dados/dispositivos.json", b"/./dados/dispositivos.json", b"/x/../dados/dispositivos.json",
                b"/%2e/dados/dispositivos.json", b"/%2e%2e/dados/dispositivos.json", b"/vendor/../dados/saude.json",
                b"/vendor/%2e%2e/dados/saude.json", b"/dados./dispositivos.json", b"/dados%2e/dispositivos.json",
                b"/dados%20/dispositivos.json", b"/dados.%20./dispositivos.json", b"/dados::$DATA/dispositivos.json",
                b"/dados%3a%3a$DATA/dispositivos.json", b"/dados%00/dispositivos.json", b"/dados/dispositivos.json%00.js",
                b"/dados/grafo/base/src/fonte.cpp", b"/%64ados/grafo/base/src/fonte.cpp",
                b"/x/..%2fdados/saude.json", b"/x/..%5cdados/saude.json", b"/%ff/../dados/saude.json",
                b"http://127.0.0.1/dados/dispositivos.json", b"/dados/dispositivos.json?x=1", b"/dados/dispositivos.json#a",
                b"/x?/../dados/saude.json", b"/dado%C5%BF/saude.json",
                b"/servidor.py", b"/SERVIDOR.PY", b"/servidor%2epy", b"/servidor.p%79", b"/servidor.py.", b"/servidor.py%20",
                b"/servidor.py%20.", b"/servidor.py::$DATA", b"/servidor.py/.", b"/servidor.py/x/..", b"/vendor/../servidor.py",
                b"/LEIAME.md", b"/LEIAME.MD", b"/notas.txt", b"/abrir.sh", b"/abrir.bat",
                b"/.git/config", b"/%2egit/config", b"/.env", b"/vendor/.oculto/x.js", b"/vendor/%2eoculto/x.js",
                b"/../fora_do_site/segredo.js", b"/%2e%2e/fora_do_site/segredo.js", b"/C:/Windows/win.ini",
                b"/fora/segredo.js",   # fora/ existe DENTRO da pasta só para conferir abaixo que /fora/ não é bloqueada por engano
            ]
            if juncao_dados:
                ataques += [b"/atalho/dispositivos.json", b"/atalho/grafo/base/src/fonte.cpp"]
            else:
                print("  (sem junção/symlink neste sistema: pula atalho -> dados/)")
            if juncao_fora:
                ataques += [b"/saida/segredo.js"]
            if bloqueia_json:
                ataques += [b"/config.json"]
            for alvo in ataques:
                if alvo == b"/fora/segredo.js":
                    continue
                for metodo in ("GET", "HEAD"):
                    st, corpo = pedir(porta, metodo, alvo)
                    checar(f"{metodo} {alvo.decode('latin-1')} não serve", st != 200 and SEGREDO not in corpo, (st, corpo[:80]))

            print("arquivos legítimos e rotas continuam funcionando")
            legitimos = [b"/escritorio.js", b"/estilo.css", b"/icone-192.png", b"/sw.js", b"/vendor/three/build/three.module.js",
                         b"/vendor/three/examples/jsm/controls/OrbitControls.js", b"/a.b.c.min.js", b"/manifest.webmanifest.js",
                         b"/%C3%ADcone%20a%C3%A7%C3%A3o.css", b"/dadosx/ok.js", b"/x.dados/ok.js", b"/escritorio.js?v=123",
                         b"/escritorio.js#topo", b"/vendor/three/build/../build/three.module.js"]
            for alvo in legitimos:
                for metodo in ("GET", "HEAD"):
                    st, corpo = pedir(porta, metodo, alvo)
                    esperado = LEGITIMO in corpo if metodo == "GET" else True
                    checar(f"{metodo} {alvo.decode('latin-1')} servido", st == 200 and esperado, (st, corpo[:80]))
            st, corpo = pedir(porta, "GET", b"/manifest.webmanifest")
            checar("GET /manifest.webmanifest (rota) 200", st == 200 and b"{" in corpo, (st, corpo[:80]))
            st, corpo = pedir(porta, "GET", b"/eventos?ultimos=1")
            checar("GET /eventos (rota, fora do servir_estatico) responde", st in (200, 503) and b"eventos" in corpo, (st, corpo[:80]))
            st, corpo = pedir(porta, "GET", b"/fora/segredo.js")
            checar("pasta comum chamada fora/ dentro do site não é bloqueada por engano", st == 200, st)
        finally:
            if srv is not None:
                srv.shutdown()
                srv.server_close()
            servidor.Handler.rede = guardar
            for n, v in guardar_banco.items():
                setattr(banco, n, v)
            for link in (pasta / "atalho", pasta / "saida"):   # remove a junção sem apagar o alvo
                try:
                    os.rmdir(link) if os.name == "nt" else os.unlink(link)
                except OSError:
                    pass
            shutil.rmtree(pasta, ignore_errors=True)
    print(f"\n{len(feitos)} ok, {len(falhas)} falha(s)")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
