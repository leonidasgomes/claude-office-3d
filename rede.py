"""Acesso pelo celular na rede local: camada de segurança do servidor (somente biblioteca padrão).

DESLIGADO por padrão: o servidor só escuta 127.0.0.1. Com `--rede-local` ele escuta 0.0.0.0 e, nesse modo:
  * o PC (127.0.0.1/::1) passa sem sessão e é o único que pode gerar código de pareamento, revogar aparelhos e
    "liberar pontos" (vermelho);
  * qualquer outra origem precisa ser de rede privada (`ipaddress.is_private`: 192.168/16, 10/8, 172.16/12,
    fc00::/7...; a faixa 100.64/10 do Tailscale só com "rede_tailscale": true) e ter o cookie de um aparelho pareado;
  * pareamento: o PC gera um CÓDIGO de uso único (vale 10 min, só o hash fica na memória) com uma permissão
    ("ver" ou "conferir"); o celular abre /parear?c=<código> (QR code), informa o nome do aparelho e ganha uma
    sessão própria; em dados/dispositivos.json ficam o HASH da sessão (sha256), nome, permissão, acessos e o token
    anti-CSRF da sessão (em texto puro: o servidor compara com o X-Office-Csrf);
  * "conferir" pode POST /api/xp/conferido e /api/xp/desfazer (só de ações "conferido"), com token anti-CSRF por
    sessão (X-Office-Csrf), Origin igual ao host acessado e no máximo 10 ações por minuto;
  * 5 erros de código em 10 min bloqueiam o IP por 15 min (429);
  * só GET/HEAD, exceto POST /parear, /api/* e /rede/* (estes, só com os cabeçalhos de ação);
  * toda ação é gravada em dados/acoes.jsonl (quando, o quê, PR, origem, IP).
"""
import hashlib
import hmac
import html
import ipaddress
import json
import os
import re
import secrets
import socket
import ssl
import subprocess
import sys
import threading
import time
from base64 import b64encode
from collections import deque
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tls  # noqa: E402

COOKIE = "office_sessao"
COOKIE_VALIDADE = 30 * 24 * 3600   # s (30 dias)
CODIGO_VALIDADE = 600              # s (10 min)
MAX_ERROS, JANELA_ERROS, BLOQUEIO = 5, 600, 900   # 5 erros em 10 min -> bloqueio de 15 min
ACOES_POR_MINUTO = 10
PERMISSOES = ("ver", "conferir")
PC = {"id": "pc", "nome": "PC", "permissao": "pc", "csrf": ""}
ANONIMO = {"id": "anonimo", "nome": "anônimo", "permissao": "nenhuma", "csrf": ""}
# GET sem sessão (depois do filtro de IP privado): só o que o iPhone busca sem cookie ao adicionar à Tela de Início
ROTAS_PUBLICAS = ("/manifest.webmanifest", "/icone-192.png", "/icone-512.png")
# quem pode o quê nas ações (POST /api/...): "pc" é o próprio computador
PERMISSAO_ROTA = {"/api/xp/conferido": {"pc", "conferir"}, "/api/xp/desfazer": {"pc", "conferir"}, "/api/xp/liberar": {"pc"},
                  # sugestões do bot de revisão: tratar (encaminhar/ignorar/resolver) é só do PC; o celular só lê (GET)
                  "/api/sugestoes/tratar": {"pc"},
                  # painel Saúde: ignorar/reativar um item e avisar o líder (pedido entregue pelo vigia) são só do PC
                  "/api/saude/ignorar": {"pc"}, "/api/saude/avisar": {"pc"}, "/api/saude/triagem": {"pc"},
                  # alertas (push.py): qualquer aparelho pareado (ver ou mais) e o PC inscrevem o próprio navegador
                  "/api/push/inscrever": {"pc", "ver", "conferir"}, "/api/push/sair": {"pc", "ver", "conferir"},
                  "/api/push/prefs": {"pc", "ver", "conferir"}, "/api/push/teste": {"pc", "ver", "conferir"}}
# ações que só fazem sentido pelo navegador (painel Saúde): exigem os cabeçalhos Sec-Fetch-* e gravam o User-Agent
ROTAS_NAVEGADOR = ("/api/saude/",)
TAILSCALE = ipaddress.ip_network("100.64.0.0/10")
_RX_CONTROLE = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]")


def resumo_ua(texto, limite=120):
    """User-Agent numa linha, sem caractere de controle, até `limite` caracteres (vai para o histórico e o painel)."""
    return " ".join(_RX_CONTROLE.sub(" ", str(texto or "")).split())[:limite]
_ESTILO = ("<meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>Claude Office 3D</title>"
           "<body style='font:18px system-ui;background:#0f1419;color:#e6edf3;display:grid;place-items:center;"
           "min-height:100vh;margin:0;text-align:center;padding:16px'>")
PAGINA_401 = ("<!doctype html>" + _ESTILO + "<p>Peça o QR code no escritório do PC.</p>").encode("utf-8")
_RX_SCRIPT_INLINE = re.compile(r"<script(?![^>]*\bsrc\s*=)[^>]*>(.*?)</script>", re.S | re.I)


def _ip(texto):
    """ipaddress do texto (IPv4 mapeado em IPv6 vira IPv4); None se inválido."""
    try:
        ip = ipaddress.ip_address(str(texto).split("%")[0])
    except ValueError:
        return None
    return ip.ipv4_mapped or ip if ip.version == 6 else ip


def eh_local(ip):
    a = _ip(ip)
    return a is not None and a.is_loopback and str(a) in ("127.0.0.1", "::1")


def ip_permitido(ip, tailscale=False):
    """Só rede privada de verdade: nada de IP público, link-local, multicast, loopback alheio ou reservado.
    A faixa 100.64.0.0/10 (Tailscale/CGNAT) só entra com tailscale=True ("rede_tailscale" no config.json): fora do
    Tailscale ela é o CGNAT da operadora, compartilhado com outros clientes."""
    a = _ip(ip)
    if a is None or a.is_loopback or a.is_link_local or a.is_multicast or a.is_unspecified or a.is_reserved:
        return False
    if a.version == 4 and a in TAILSCALE:
        return bool(tailscale)
    return a.is_private


_NOMES_VIRTUAIS = ("vethernet", "wsl", "hyper-v", "vmware", "virtualbox", "vbox", "docker", "npcap", "loopback", "tap-windows", "zerotier")
_cache_adaptadores = {"t": 0.0, "dados": ({}, set())}


def _adaptadores():
    """({ip: nome do adaptador}, {ips de adaptadores com gateway padrão}). Só no Windows (lê o `ipconfig`); noutros
    sistemas devolve vazio e a heurística de faixa (172.16-31) decide. Cache de 30 s: o painel consulta a cada 5 s."""
    agora = time.time()
    if agora - _cache_adaptadores["t"] < 30:
        return _cache_adaptadores["dados"]
    nomes, com_gateway = {}, set()
    if sys.platform == "win32":
        try:
            saida = subprocess.run(["ipconfig"], capture_output=True, timeout=4).stdout.decode("cp850", "replace")
            atual, ips_atual = "", []
            for linha in saida.splitlines():
                if linha and not linha[0].isspace() and linha.rstrip().endswith(":"):
                    atual, ips_atual = linha.strip().rstrip(":"), []
                elif re.search(r"gateway", linha, re.I):
                    if linha.split(":", 1)[-1].strip() and ":" in linha:
                        com_gateway.update(ips_atual)
                elif re.search(r"IPv4", linha, re.I) and ":" in linha:
                    achou = re.findall(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b", linha)
                    if achou:
                        nomes[achou[0]] = atual
                        ips_atual.append(achou[0])
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    _cache_adaptadores.update(t=agora, dados=(nomes, com_gateway))
    return nomes, com_gateway


def _classificar(privados, padrao):
    """(ordenados, virtuais): a placa com a rota padrão (gateway) primeiro, as reais depois, as virtuais por último.
    Virtual = nome de adaptador vEthernet/WSL/Hyper-V/VMware/VirtualBox/Docker ou, sem nome, 172.16-31 fora da rota padrão."""
    nomes, com_gateway = _adaptadores()
    virtuais = set()
    for e in privados:
        nome = nomes.get(e, "").lower()
        if e == padrao or e in com_gateway:
            continue
        if any(v in nome for v in _NOMES_VIRTUAIS) or (not nome and _ip(e) in ipaddress.ip_network("172.16.0.0/12")):
            virtuais.add(e)
    ordem = sorted(privados, key=lambda e: (0 if e == padrao else (1 if e in com_gateway else (3 if e in virtuais else 2))))
    return ordem, virtuais


def _levantar():
    """(privados, tailscale, virtuais): IPv4 da máquina. getaddrinfo do hostname + o truque do UDP connect (nada é
    enviado). Os privados vêm em ordem de preferência: a placa da rota padrão primeiro, adaptadores virtuais por último."""
    achados, padrao = [], None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        try:
            s.connect(("8.8.8.8", 80))   # UDP: só escolhe a interface de saída, nenhum pacote sai
            padrao = s.getsockname()[0]
            achados.append(padrao)
        finally:
            s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            achados.append(info[4][0])
    except OSError:
        pass
    privados, tail = [], []
    for e in dict.fromkeys(achados):
        a = _ip(e)
        if a is None or a.version != 4 or a.is_loopback or a.is_link_local or a.is_unspecified:
            continue
        if a in TAILSCALE:
            tail.append(e)
        elif a.is_private:
            privados.append(e)
    privados, virtuais = _classificar(privados, padrao)
    return privados, tail, virtuais


def enderecos_da_maquina():
    """(privados, tailscale): IPv4 da máquina, o da rede principal primeiro (ver _levantar)."""
    privados, tail, _ = _levantar()
    return privados, tail


def _sha(texto):
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def limpar_nome(texto):
    """Nome do aparelho: sem caracteres de controle, no máximo 40 caracteres."""
    nome = re.sub(r"[\x00-\x1f\x7f<>]", "", str(texto or "")).strip()[:40]
    return nome or "Celular"


class Rede:
    def __init__(self, pasta, ativo=False, tailscale=False):
        self.ativo = bool(ativo)
        dados = Path(pasta) / "dados"
        self.arq_dispositivos = dados / "dispositivos.json"
        self.arq_acoes = dados / "acoes.jsonl"
        self.trava = threading.RLock()
        self._dispositivos, self._mtime, self._gravado = [], None, 0.0
        self._codigos = {}     # sha256(código) -> {"permissao", "expira"}
        self._erros = {}       # ip -> [instantes dos erros]
        self._bloqueados = {}  # ip -> instante em que o bloqueio termina
        self._logados = {}
        self._acoes_rec = {}   # id do aparelho -> instantes das últimas ações
        self.ao_revogar = []   # funções chamadas com a lista de ids de aparelhos revogados (apagam as inscrições de push)
        # HTTPS local (preenchido por iniciar_tls): HTTP em 127.0.0.1:porta, HTTPS em porta+1, certificado público em porta+2
        self.pasta, self.tailscale = Path(pasta), bool(tailscale)   # tailscale: aceita 100.64/10 (ip_permitido)
        self.porta_http = self.porta_https = self.porta_ca = 0
        self.https, self.tls_info, self.tls_ctx = False, {"ok": False, "erro": ""}, None

    # ------------------------------------------------------------------ HTTPS local (CA própria, tls.py)
    def _ips_certificado(self):
        privados, tail = enderecos_da_maquina()
        return privados + (tail if self.tailscale else [])

    def iniciar_tls(self, porta, tailscale=False):
        """Gera/renova a CA e o certificado e prepara o contexto TLS. Sem como gerar, fica em HTTP (tls_info['erro'])."""
        self.porta_http, self.porta_https, self.porta_ca, self.tailscale = porta, porta + 1, porta + 2, bool(tailscale)
        try:
            self.tls_info = tls.garantir(self.pasta, self._ips_certificado(), self.tailscale)
            self.tls_ctx, self.https = tls.contexto(self.pasta), True
        except (tls.TLSIndisponivel, OSError, ssl.SSLError) as e:
            self.tls_info, self.tls_ctx, self.https = {"ok": False, "erro": str(e)[:300]}, None, False
        return self.https

    def renovar_tls(self, recriar=False):
        """Refaz o certificado se os IPs mudaram (ou tudo, com recriar=True) e recarrega no servidor em execução."""
        if not self.https:
            return
        with self.trava:
            if recriar:
                self.tls_info = tls.recriar(self.pasta, self._ips_certificado(), self.tailscale)
            else:
                antes = self.tls_info.get("servidor_sha256")
                self.tls_info = tls.garantir(self.pasta, self._ips_certificado(), self.tailscale)
                if self.tls_info.get("servidor_sha256") == antes:
                    return
            self.tls_ctx.load_cert_chain(str(tls.pasta_tls(self.pasta) / "servidor.crt"), str(tls.pasta_tls(self.pasta) / "servidor.key"))

    # ------------------------------------------------------------------ dispositivos (só o hash da sessão)
    def _carregar(self):
        try:
            mtime = self.arq_dispositivos.stat().st_mtime
        except OSError:
            self._dispositivos, self._mtime = [], None
            return
        if mtime != self._mtime:
            try:
                lido = json.loads(self.arq_dispositivos.read_text(encoding="utf-8"))
                self._dispositivos = [d for d in lido if isinstance(d, dict) and d.get("hash")]
            except (OSError, ValueError):
                self._dispositivos = []
            self._mtime = mtime

    def _salvar(self):
        self.arq_dispositivos.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.arq_dispositivos.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._dispositivos, ensure_ascii=False, indent=1), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        tmp.replace(self.arq_dispositivos)
        self._mtime = self.arq_dispositivos.stat().st_mtime
        self._gravado = time.time()

    def criar_sessao(self, nome, permissao, ip):
        """Nova sessão do aparelho. Devolve (valor_do_cookie, aparelho). O servidor guarda só o hash."""
        cookie = secrets.token_urlsafe(32)
        agora = time.time()
        d = {"id": secrets.token_hex(4), "nome": limpar_nome(nome), "permissao": permissao, "hash": _sha(cookie),
             "csrf": secrets.token_urlsafe(24), "criado": agora, "ultimo_acesso": agora, "ultimo_ip": ip}
        with self.trava:
            self._carregar()
            self._dispositivos.append(d)
            self._salvar()
        return cookie, d

    def sessao_do_cookie(self, cabecalho, ip):
        """Aparelho dono do cookie (None se não houver, expirou ou foi revogado). Atualiza último acesso/IP."""
        try:
            m = SimpleCookie(cabecalho or "").get(COOKIE)
        except Exception:
            return None
        if not m or not m.value:
            return None
        h = _sha(m.value)
        with self.trava:
            self._carregar()
            achado = None
            for d in self._dispositivos:
                if hmac.compare_digest(h.encode(), str(d["hash"]).encode()):
                    achado = d
            if achado is None or time.time() - achado.get("criado", 0) > COOKIE_VALIDADE:
                return None
            mudou_ip = achado.get("ultimo_ip") != ip
            achado["ultimo_acesso"], achado["ultimo_ip"] = time.time(), ip
            if mudou_ip or time.time() - self._gravado > 60:
                self._salvar()
            return achado

    def listar(self):
        with self.trava:
            self._carregar()
            return [{k: d.get(k) for k in ("id", "nome", "permissao", "criado", "ultimo_acesso", "ultimo_ip")}
                    for d in self._dispositivos]

    def revogar(self, id_=None):
        """Revoga um aparelho (ou todos, com id None). Devolve os nomes revogados."""
        with self.trava:
            self._carregar()
            fora = [d for d in self._dispositivos if id_ is None or d.get("id") == id_]
            if fora:
                self._dispositivos = [d for d in self._dispositivos if d not in fora]
                self._salvar()
                for cb in self.ao_revogar:
                    try:
                        cb([d.get("id") for d in fora])
                    except Exception as e:   # um gancho com defeito não impede a revogação
                        print(f"[rede] gancho de revogação falhou: {str(e)[:100]}", flush=True)
            return [d["nome"] for d in fora]

    # ------------------------------------------------------------------ códigos de pareamento (uso único, 10 min)
    def criar_codigo(self, permissao):
        codigo = secrets.token_urlsafe(24)
        agora = time.time()
        with self.trava:
            self._codigos = {h: c for h, c in self._codigos.items() if c["expira"] > agora}
            if len(self._codigos) >= 20:   # nunca guarda códigos demais
                self._codigos.pop(min(self._codigos, key=lambda h: self._codigos[h]["expira"]))
            self._codigos[_sha(codigo)] = {"permissao": permissao, "expira": agora + CODIGO_VALIDADE}
        return codigo, agora + CODIGO_VALIDADE

    def codigo_valido(self, codigo):
        """Permissão do código (sem consumir) ou None se inexistente/expirado/já usado."""
        c = self._codigos.get(_sha(codigo or ""))
        return c["permissao"] if c and c["expira"] > time.time() else None

    def consumir_codigo(self, codigo):
        with self.trava:
            c = self._codigos.pop(_sha(codigo or ""), None)
        return c["permissao"] if c and c["expira"] > time.time() else None

    # ------------------------------------------------------------------ força bruta
    def bloqueado(self, ip):
        with self.trava:
            fim = self._bloqueados.get(ip, 0)
            if fim > time.time():
                return True
            self._bloqueados.pop(ip, None)
            return False

    def registrar_erro(self, ip):
        agora = time.time()
        with self.trava:
            lista = [t for t in self._erros.get(ip, []) if agora - t < JANELA_ERROS] + [agora]
            self._erros[ip] = lista
            if len(lista) >= MAX_ERROS:
                self._bloqueados[ip] = agora + BLOQUEIO
                self._erros.pop(ip, None)
                return True
        return False

    def limite_acoes(self, id_):
        """True se o aparelho ainda pode agir (no máximo 10 ações por minuto)."""
        agora = time.time()
        with self.trava:
            fila = self._acoes_rec.setdefault(id_, deque())
            while fila and agora - fila[0] > 60:
                fila.popleft()
            if len(fila) >= ACOES_POR_MINUTO:
                return False
            fila.append(agora)
            return True

    def log_negado(self, ip, rota, motivo):
        """Console do servidor: IP + rota + motivo (nunca código/cookie), no máximo 1 linha por 30 s por combinação."""
        chave, agora = (ip, rota, motivo), time.time()
        with self.trava:
            if agora - self._logados.get(chave, 0) < 30:
                return
            self._logados[chave] = agora
            if len(self._logados) > 500:
                self._logados.clear()
        print(f"[rede] negado: {ip} {rota} ({motivo})", flush=True)

    # ------------------------------------------------------------------ histórico de ações
    def registrar_acao(self, acao, pr, origem, ip, detalhe=""):
        linha = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "acao": acao, "pr": pr, "origem": origem, "ip": ip}
        if detalhe:
            linha["detalhe"] = detalhe
        with self.trava:
            self.arq_acoes.parent.mkdir(parents=True, exist_ok=True)
            with open(self.arq_acoes, "a", encoding="utf-8") as f:
                f.write(json.dumps(linha, ensure_ascii=False) + "\n")

    def ultimas_acoes(self, n=50, com_ip=False):
        try:
            with open(self.arq_acoes, "rb") as f:
                f.seek(0, os.SEEK_END)
                f.seek(max(0, f.tell() - 200_000))
                linhas = f.read().decode("utf-8", errors="replace").splitlines()
        except OSError:
            return []
        saida = []
        for t in reversed(linhas):
            try:
                x = json.loads(t)
            except ValueError:
                continue
            if isinstance(x, dict):
                if not com_ip:
                    x.pop("ip", None)
                saida.append(x)
            if len(saida) >= n:
                break
        return saida

    # ------------------------------------------------------------------ status (só para o PC)
    def status(self, porta):
        privados, tail, virtuais = _levantar()
        info = {k: v for k, v in self.tls_info.items() if k in ("ok", "erro", "metodo", "ca_sha256", "servidor_sha256", "ca_expira", "servidor_expira")}
        return {"ativo": self.ativo, "porta": self.porta_http or porta, "enderecos": privados, "tailscale": tail,
                "https": self.https, "porta_https": self.porta_https, "porta_ca": self.porta_ca, "tls": info,
                "virtuais": sorted(virtuais), "python": sys.executable,
                "portas": [self.porta_https, self.porta_ca] if self.https else [self.porta_http or porta],
                "dispositivos": self.listar() if self.ativo else [], "validade_codigo": CODIGO_VALIDADE}


def csp(html_texto=None):
    """Content-Security-Policy; scripts inline da página entram por hash (sem 'unsafe-inline')."""
    hashes = ""
    if html_texto:
        for m in _RX_SCRIPT_INLINE.finditer(html_texto):
            h = b64encode(hashlib.sha256(m.group(1).encode("utf-8")).digest()).decode()
            hashes += f" 'sha256-{h}'"
    return ("default-src 'self'; script-src 'self' https://cdn.jsdelivr.net" + hashes +
            "; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; "
            "connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'")


class _Mudo:
    @staticmethod
    def log_negado(ip, rota, motivo):
        print(f"[rede] negado: {ip} {rota} ({motivo})", flush=True)


class HandlerSeguro(SimpleHTTPRequestHandler):
    """Base dos handlers do servidor: guarda de acesso, só leitura e cabeçalhos de segurança.

    O servidor herda desta classe, atribui `rede` (instância de Rede) e implementa `rotas_get()` e `api_post()`."""
    rede = None
    server_version = "ClaudeOffice3D"   # não anuncia a versão do Python
    sys_version = ""
    csp_html = None   # texto do HTML servido nesta resposta (para o hash do script inline)
    ident = PC        # quem está pedindo: o PC ou um aparelho pareado (preenchido pela guarda)

    def log_message(self, formato, *args):
        pass  # silencioso

    @property
    def _https(self):
        return bool(getattr(self.server, "https", False))

    @property
    def _esquema(self):
        return "https" if self._https else "http"

    def setup(self):
        if self._https:   # aperto de mão TLS aqui (na thread da conexão), não no accept do servidor
            self.request.do_handshake()
        super().setup()

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", csp(self.csp_html))
        if self._https:
            self.send_header("Strict-Transport-Security", "max-age=31536000")
        super().end_headers()

    # ------------------------------------------------------------------ respostas
    def responder(self, corpo, tipo="application/json; charset=utf-8", codigo=200, extras=()):
        if not isinstance(corpo, bytes):
            corpo = json.dumps(corpo, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        for k, v in extras:
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(corpo)

    def _negar(self, codigo, corpo=PAGINA_401, extras=()):
        self.responder(corpo, "text/html; charset=utf-8", codigo, extras)

    def _json_erro(self, codigo, erro):
        self.responder({"ok": False, "erro": erro}, codigo=codigo)

    def _ler_corpo(self, limite=4096):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            return self.rfile.read(n) if 0 < n <= limite else None
        except (ValueError, OSError):
            return None

    # ------------------------------------------------------------------ guarda
    def _host_local(self):
        h = (self.headers.get("Host") or "").strip().lower()
        if h.startswith("[") and "]" in h:
            return h[1:h.index("]")] == "::1"
        return (h.rsplit(":", 1)[0] if ":" in h else h) in ("localhost", "127.0.0.1")

    def _guarda(self):
        """True se a requisição pode seguir (e define self.ident); senão já respondeu (403/429/401/pareamento)."""
        ip, url = self.client_address[0], urlparse(self.path)
        rota = url.path
        if eh_local(ip):
            self.ident = PC
            return True
        rede = self.rede or _Mudo
        if self.rede is None or not self.rede.ativo or not ip_permitido(ip, self.rede.tailscale):
            rede.log_negado(ip, rota, "origem não permitida")
            self._negar(403, b"Acesso negado.")
            return False
        if self.rede.bloqueado(ip):
            rede.log_negado(ip, rota, "IP bloqueado por tentativas erradas")
            self._negar(429, b"Muitas tentativas. Tente de novo mais tarde.", [("Retry-After", str(BLOQUEIO))])
            return False
        if rota == "/parear":
            self._parear(ip, url)
            return False
        if rota.startswith("/rede/"):
            rede.log_negado(ip, rota, "rota só do PC")
            self._negar(403, b"Acesso negado.")
            return False
        if rota in ROTAS_PUBLICAS and self.command in ("GET", "HEAD"):
            self.ident = ANONIMO
            return True
        d = self.rede.sessao_do_cookie(self.headers.get("Cookie"), ip)
        if d is None:
            rede.log_negado(ip, rota, "sem sessão válida")
            self._negar(401)
            return False
        self.ident = d
        return True

    # ------------------------------------------------------------------ pareamento (celular)
    def _erro_codigo(self, ip, rota):
        bloqueou = self.rede.registrar_erro(ip)
        self.rede.log_negado(ip, rota, "código de pareamento inválido" + (" — IP bloqueado por 15 min" if bloqueou else ""))
        self._negar(401)

    def _parear(self, ip, url):
        if self.command in ("GET", "HEAD"):
            codigo = parse_qs(url.query).get("c", [""])[0]
            perm = self.rede.codigo_valido(codigo)
            if not perm:
                return self._erro_codigo(ip, "/parear")
            quem = "ver o escritório" if perm == "ver" else "ver o escritório e marcar PRs como conferidos"
            # meta referrer: com "no-referrer" o navegador manda "Origin: null" no POST do formulário e a checagem de Origin falharia
            pagina = ("<!doctype html><meta name=referrer content=same-origin>" + _ESTILO + "<form method=post action=/parear style='display:grid;gap:14px;"
                      "max-width:340px;width:100%'><h2 style='margin:0'>Parear este aparelho</h2>"
                      f"<p style='margin:0;color:#9aa7b6'>Ele poderá {html.escape(quem)}.</p>"
                      f"<input type=hidden name=c value=\"{html.escape(codigo, quote=True)}\">"
                      "<input name=nome maxlength=40 required autofocus placeholder='Nome do aparelho (ex.: Meu celular)' "
                      "style='font:18px system-ui;padding:12px;border-radius:8px;border:1px solid #3a4756;"
                      "background:#161c24;color:#e6edf3'>"
                      "<button style='font:700 18px system-ui;padding:14px;border-radius:8px;border:0;background:#16a34a;"
                      "color:#fff'>Parear</button></form>").encode("utf-8")
            return self._negar(200, pagina)
        if self.command != "POST":
            return self.nao_permitido()
        host = self.headers.get("Host") or ""
        if (self.headers.get("Origin") or "").lower() != f"{self._esquema}://{host}".lower() or not host or \
                (self.headers.get("Content-Type") or "").split(";")[0].strip().lower() != "application/x-www-form-urlencoded":
            self.rede.log_negado(ip, "/parear", "Origin/Content-Type inválidos")
            return self._negar(403, b"Acesso negado.")
        corpo = self._ler_corpo(2048)
        campos = parse_qs((corpo or b"").decode("utf-8", errors="replace"))
        perm = self.rede.consumir_codigo(campos.get("c", [""])[0])
        if not perm:
            return self._erro_codigo(ip, "/parear")
        cookie, d = self.rede.criar_sessao(campos.get("nome", [""])[0], perm, ip)
        self.rede.registrar_acao("parear", None, d["nome"], ip, detalhe=perm)
        print(f"[rede] aparelho pareado: {d['nome']} ({perm}) {ip}", flush=True)
        self.send_response(303)
        self.send_header("Location", "/")
        self.send_header("Set-Cookie", f"{COOKIE}={cookie}; HttpOnly; SameSite=Strict; Path=/; Max-Age={COOKIE_VALIDADE}"
                         + ("; Secure" if self._https else ""))
        self.send_header("Content-Length", "0")
        self.end_headers()

    # ------------------------------------------------------------------ métodos
    def do_GET(self):
        if not self._guarda() or self._rotas_rede():
            return
        if urlparse(self.path).path.startswith(("/api/", "/rede/")):
            return self.nao_permitido()   # as demais rotas em /api/ e /rede/ só aceitam POST
        self.rotas_get()

    def do_HEAD(self):
        if self._guarda() and not self._rotas_rede():
            if self.caminho_bloqueado():
                return self.send_error(404)
            SimpleHTTPRequestHandler.do_HEAD(self)

    def do_POST(self):
        if not self._guarda():
            return
        if urlparse(self.path).path.startswith(("/api/", "/rede/")):
            return self._api()
        self.nao_permitido()

    def nao_permitido(self):
        self.responder(b"Metodo nao permitido.", "text/plain; charset=utf-8", 405, [("Allow", "GET, HEAD")])

    def __getattr__(self, nome):
        # PUT, DELETE, PATCH, OPTIONS... qualquer outro método: 405 (depois da guarda de acesso)
        if nome.startswith("do_"):
            return lambda: self._guarda() and self.nao_permitido()
        raise AttributeError(nome)

    # ------------------------------------------------------------------ rotas de rede (GET)
    def _rotas_rede(self):
        """GET /rede/status (só o PC), /api/sessao e /api/acoes. True se tratou a requisição."""
        rota = urlparse(self.path).path
        local = self.ident is PC
        if rota == "/rede/status":
            if not local or not self._host_local() or self.headers.get("Sec-Fetch-Site", "same-origin") not in ("same-origin", "none"):
                self._negar(403, b"Acesso negado.")
            else:
                self.responder((self.rede or Rede(Path(__file__).resolve().parent)).status(self.server.server_address[1]))
            return True
        if rota == "/api/sessao":
            self.responder({"nome": self.ident["nome"], "permissao": self.ident["permissao"], "csrf": self.ident["csrf"]})
            return True
        if rota == "/api/acoes":
            r = self.rede or Rede(Path(__file__).resolve().parent)
            self.responder({"acoes": r.ultimas_acoes(50, com_ip=local)})
            return True
        if rota.startswith("/api/"):   # demais GETs de API do servidor (alertas, push); None = não existe
            resposta = self.api_get(rota, parse_qs(urlparse(self.path).query), self.ident)
            if resposta is not None:
                self.responder(resposta[1], codigo=resposta[0])
                return True
        return False

    # ------------------------------------------------------------------ ações (POST /api/... e /rede/...)
    def _origem_segura(self):
        """Proteção CSRF: Content-Type JSON, X-Office-Acao, e Origin/Host de localhost (PC) ou do host acessado (celular)."""
        host = (self.headers.get("Host") or "").lower()
        origem = (self.headers.get("Origin") or "").lower()
        if (self.headers.get("Content-Type") or "").split(";")[0].strip().lower() != "application/json" \
                or self.headers.get("X-Office-Acao") != "1" or not host or origem != f"{self._esquema}://{host}":
            return False
        if self.headers.get("Sec-Fetch-Site", "same-origin") not in ("same-origin", "none"):
            return False
        if self.ident is PC:   # no PC só vale localhost/127.0.0.1/[::1] (contra DNS rebinding)
            return self._host_local()
        return hmac.compare_digest((self.headers.get("X-Office-Csrf") or "").encode(), str(self.ident["csrf"]).encode())

    def _api(self):
        ip, rota, ident = self.client_address[0], urlparse(self.path).path, self.ident
        rede = self.rede or _Mudo
        if rota.startswith("/rede/") and ident is not PC:
            rede.log_negado(ip, rota, "ação só do PC")
            return self._negar(403, b"Acesso negado.")
        if not self._origem_segura():
            rede.log_negado(ip, rota, "CSRF: cabeçalhos/Origin/token inválidos")
            return self._negar(403, b"Acesso negado.")
        # painel Saúde: além da guarda acima, exige Sec-Fetch-Site same-origin e Sec-Fetch-Mode PRESENTES (o navegador sempre
        # manda; curl e scripts não, por padrão). Não impede um processo local decidido, mas eleva a barreira; o User-Agent
        # vai para o histórico e para o painel.
        if rota.startswith(ROTAS_NAVEGADOR) and (self.headers.get("Sec-Fetch-Site") != "same-origin"
                                                 or not self.headers.get("Sec-Fetch-Mode")):
            rede.log_negado(ip, rota, "sem Sec-Fetch-Site/Sec-Fetch-Mode de navegador")
            return self._negar(403, b"Acesso negado.")
        if rota.startswith("/api/") and ident["permissao"] not in PERMISSAO_ROTA.get(rota, ()):
            if rota in PERMISSAO_ROTA:
                rede.log_negado(ip, rota, f"sem permissão ({ident['permissao']})")
                return self._json_erro(403, "sem permissão: esta ação só pode ser feita pelo PC" if ident is not PC else "negado")
        if ident is not PC and not self.rede.limite_acoes(ident["id"]):
            rede.log_negado(ip, rota, "limite de 10 ações por minuto")
            return self._json_erro(429, "muitas ações em 1 minuto; espere um pouco")
        corpo = self._ler_corpo()
        try:
            dados = json.loads(corpo.decode("utf-8")) if corpo else None
        except ValueError:
            dados = None
        if not isinstance(dados, dict):
            return self._json_erro(400, "corpo JSON inválido")
        ua = resumo_ua(self.headers.get("User-Agent"))
        dados["_ua"] = ua   # sempre o do cabeçalho (o do corpo, se veio, é descartado)
        if rota.startswith("/rede/"):
            return self._rede_post(rota, dados, ip)
        resposta = self.api_post(rota, dados, ident)
        if resposta is None:
            return self._json_erro(404, "ação desconhecida")
        if resposta[0] == 200 and self.rede is not None:
            detalhe = str(dados.get("_detalhe") or "")[:200]
            if rota.startswith(ROTAS_NAVEGADOR):
                detalhe = (detalhe + " · UA: " + ua).strip(" ·")
            self.rede.registrar_acao(rota.rsplit("/", 1)[1], dados.get("pr"), ident["nome"], ip, detalhe=detalhe)
        self.responder(resposta[1], codigo=resposta[0])

    def _rede_post(self, rota, dados, ip):
        """POST /rede/codigo e /rede/revogar: só do PC."""
        r = self.rede
        if r is None or not r.ativo:
            return self._json_erro(400, "acesso pelo celular desligado (abra com --rede-local)")
        if rota == "/rede/codigo":
            perm = dados.get("permissao")
            if perm not in PERMISSOES:
                return self._json_erro(400, "permissao deve ser 'ver' ou 'conferir'")
            try:
                r.renovar_tls()   # IPs mudaram desde que o servidor subiu: refaz o certificado do servidor
            except (tls.TLSIndisponivel, OSError, ssl.SSLError) as e:
                return self._json_erro(500, "não consegui renovar o certificado: " + str(e)[:200])
            codigo, expira = r.criar_codigo(perm)
            privados, tail = enderecos_da_maquina()
            ips = privados + tail
            if r.https:
                urls = [f"https://{e}:{r.porta_https}/parear?c={codigo}" for e in ips]
                urls_ca = [f"http://{e}:{r.porta_ca}/" for e in ips]
            else:
                urls = [f"http://{e}:{r.porta_http or self.server.server_address[1]}/parear?c={codigo}" for e in ips]
                urls_ca = []
            return self.responder({"ok": True, "expira_em": expira, "validade": CODIGO_VALIDADE, "permissao": perm,
                                   "urls_pareamento": urls, "urls_ca": urls_ca, "https": r.https, "enderecos": ips})
        if rota == "/rede/tls/recriar":
            if not r.https:
                return self._json_erro(400, "HTTPS não está ligado")
            try:
                r.renovar_tls(recriar=True)
            except (tls.TLSIndisponivel, OSError, ssl.SSLError) as e:
                return self._json_erro(500, "não consegui recriar os certificados: " + str(e)[:200])
            r.registrar_acao("tls-recriar", None, "PC", ip)
            print("[rede] certificados recriados: reinstale a CA nos celulares", flush=True)
            return self.responder({"ok": True, "tls": {k: v for k, v in r.tls_info.items() if k.endswith("sha256") or k.endswith("expira")}})
        if rota == "/rede/revogar":
            alvo = dados.get("id")
            if dados.get("todos") is True:
                nomes = r.revogar(None)
            elif isinstance(alvo, str) and alvo:
                nomes = r.revogar(alvo)
            else:
                return self._json_erro(400, "informe id ou todos: true")
            r.registrar_acao("revogar", None, "PC", ip, detalhe=", ".join(nomes))
            print(f"[rede] aparelhos revogados: {', '.join(nomes) or 'nenhum'}", flush=True)
            return self.responder({"ok": True, "revogados": nomes})
        self._json_erro(404, "ação desconhecida")

    # ------------------------------------------------------------------ ganchos do servidor
    def api_post(self, rota, dados, ident):
        """Gancho do servidor: devolve (código, dict) ou None se a rota não existe."""
        return None

    def api_get(self, rota, qs, ident):
        """Gancho do servidor para GET /api/...: devolve (código, dict) ou None se a rota não existe."""
        return None

    def caminho_bloqueado(self):
        return False

    def rotas_get(self):
        self.servir_estatico()

    def servir_estatico(self):
        if self.caminho_bloqueado():
            return self.send_error(404)
        SimpleHTTPRequestHandler.do_GET(self)


class ServidorHTTPS(ThreadingHTTPServer):
    """Servidor HTTPS (TLS 1.2+): o aperto de mão é feito na thread da conexão (HandlerSeguro.setup)."""
    https = True

    def __init__(self, endereco, handler, ctx):
        super().__init__(endereco, handler)
        self.ctx = ctx

    def get_request(self):
        sock, addr = self.socket.accept()
        sock.settimeout(15)
        return self.ctx.wrap_socket(sock, server_side=True, do_handshake_on_connect=False), addr

    def handle_error(self, request, client_address):
        if isinstance(sys.exc_info()[1], OSError):   # SSLError, cliente que desistiu, HTTP puro na porta HTTPS...
            return
        super().handle_error(request, client_address)


class HandlerCA(BaseHTTPRequestHandler):
    """Porta auxiliar SÓ para o certificado público da CA: GET /, /ca.crt e /ca.mobileconfig; o resto é 404.

    Mesmas regras de IP (PC ou rede privada); sem sessão, porque o certificado é público (a chave da CA nunca sai do PC)."""
    rede = None
    server_version = "ClaudeOffice3D"
    sys_version = ""

    def log_message(self, formato, *args):
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", csp())
        super().end_headers()

    def _resp(self, codigo, corpo, tipo, extras=()):
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        for k, v in extras:
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(corpo)

    def _servir(self):
        ip, rota = self.client_address[0], urlparse(self.path).path
        r = self.rede
        if not (eh_local(ip) or ip_permitido(ip, r is not None and r.tailscale)):
            (r or _Mudo).log_negado(ip, rota, "origem não permitida (porta do certificado)")
            return self._resp(403, b"Acesso negado.", "text/plain; charset=utf-8")
        if r is None or not r.https:
            return self._resp(404, b"Nao encontrado.", "text/plain; charset=utf-8")
        d = tls.pasta_tls(r.pasta)
        if rota == "/ca.crt":
            return self._resp(200, tls.ca_pem(r.pasta), "application/x-x509-ca-cert", [("Content-Disposition", 'attachment; filename="claude-office-3d-ca.crt"')])
        if rota == "/ca.mobileconfig":
            return self._resp(200, tls.ca_mobileconfig(r.pasta), "application/x-apple-aspen-config",
                              [("Content-Disposition", 'attachment; filename="claude-office-3d-ca.mobileconfig"')])
        if rota == "/":
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
            alvo = html.escape(f"https://{host}:{r.porta_https}/", quote=True)
            impr = html.escape(tls.impressao(d / "ca.crt"))
            pagina = ("<!doctype html>" + _ESTILO.replace("display:grid;place-items:center;", "").replace("text-align:center", "text-align:left;line-height:1.45") +
                      "<div style='max-width:560px;margin:auto'><h2>Claude Office 3D — instalar o certificado</h2>"
                      "<p>Faça isto <b>uma vez</b> em cada celular. A autoridade certificadora é só sua e só vale para endereços da "
                      "rede local (IPs privados): ela não consegue assinar sites da internet.</p>"
                      "<h3>iPhone (Safari)</h3><ol><li><a href='/ca.mobileconfig' style='color:#8ab4ff'>Baixar o perfil</a> e tocar em Permitir.</li>"
                      "<li>Ajustes &gt; Geral &gt; VPN e Gerenciamento de Dispositivos &gt; Claude Office 3D &gt; Instalar.</li>"
                      "<li>Ajustes &gt; Geral &gt; Sobre &gt; Ajustes de Certificados Confiáveis &gt; ativar o Claude Office 3D.</li></ol>"
                      "<h3>Android</h3><ol><li><a href='/ca.crt' style='color:#8ab4ff'>Baixar o certificado</a>.</li>"
                      "<li>Configurações &gt; Segurança &gt; Criptografia e credenciais &gt; Instalar um certificado &gt; Certificado de CA.</li></ol>"
                      f"<p>Impressão digital SHA-256 (confira com a do painel Celular no PC):<br><code style='word-break:break-all'>{impr}</code></p>"
                      f"<p>Depois, volte ao PC e leia o QR de <b>Parear</b>. Endereço seguro: <a href=\"{alvo}\" style='color:#8ab4ff'>{alvo}</a></p>"
                      "<p style='color:#9aa7b6'>Sem instalar: abra o endereço seguro, aceite o aviso do navegador uma vez e confira a impressão digital "
                      "do certificado do servidor com a do painel.</p></div>").encode("utf-8")
            return self._resp(200, pagina, "text/html; charset=utf-8")
        (r or _Mudo).log_negado(ip, rota, "rota inexistente (porta do certificado)")
        self._resp(404, b"Nao encontrado.", "text/plain; charset=utf-8")

    def do_GET(self):
        self._servir()

    do_HEAD = do_GET

    def __getattr__(self, nome):
        if nome.startswith("do_"):
            return lambda: self._resp(405, b"Metodo nao permitido.", "text/plain; charset=utf-8", [("Allow", "GET, HEAD")])
        raise AttributeError(nome)
