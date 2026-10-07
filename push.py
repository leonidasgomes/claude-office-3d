"""Web Push do escritório: alertas no celular com o escritório fechado (RFC 8030, 8291 e 8292).

  * RFC 8291: o conteúdo vai cifrado de ponta a ponta (aes128gcm; ECDH P-256 + HKDF-SHA256) — o serviço de push do
    Google/Apple/Mozilla só vê o texto cifrado;
  * RFC 8292 (VAPID): o servidor se identifica com um JWT ES256 assinado pela chave gerada UMA vez em dados/push/;
  * RFC 8030: POST ao endpoint da inscrição, com TTL; 404/410 = inscrição morta (é apagada).

Usa a biblioteca `cryptography` (se não estiver instalada, o Web Push fica indisponível com aviso claro e o resto dos
alertas — notificação com a página aberta e toast do Windows — continua) e `urllib`. Nada vai no push além de um título
curto, um corpo de até 120 caracteres e o endereço relativo do painel: NUNCA comando, caminho, código ou token.
Inscrições (dados/push/inscricoes.json) ficam ligadas ao aparelho pareado: revogar o aparelho apaga a inscrição.
"""
import base64
import hashlib
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from pathlib import Path
from urllib.parse import urlparse

try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    CRIPTO_ERRO = ""
except ImportError:   # sem a biblioteca: o Web Push fica indisponível (o resto dos alertas funciona)
    CRIPTO_ERRO = "o Web Push precisa da biblioteca 'cryptography' (pip install cryptography); os outros alertas seguem funcionando"

LIMITE_CORPO = 120          # caracteres do corpo da notificação
LIMITE_TITULO = 60
MAX_INSCRICOES = 12
TAMANHO_REGISTRO = 4096     # rs do cabeçalho aes128gcm: cabe a mensagem inteira em 1 registro
CONTATO_PADRAO = "mailto:alertas@example.com"   # claim "sub" do VAPID (troque em alertas.contato se quiser)
# serviços de push conhecidos (Chrome/Edge/Android, Firefox, Safari/iOS, Windows): o servidor só envia para eles,
# senão uma inscrição forjada transformaria o servidor numa ponte para a rede interna (SSRF)
SERVICOS_PUSH = ("fcm.googleapis.com", "android.googleapis.com", "push.services.mozilla.com", "push.apple.com",
                 "notify.windows.com")
_RX_B64U = re.compile(r"^[A-Za-z0-9_-]+$")


# ---------------------------------------------------------------- utilidades
def b64u(dados):
    return base64.urlsafe_b64encode(dados).rstrip(b"=").decode("ascii")


def b64u_dec(texto):
    texto = str(texto or "")
    if not _RX_B64U.match(texto):
        raise ValueError("base64url inválido")
    return base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4))


def trocar_arquivo(tmp, destino):
    """tmp -> destino de forma atômica; no Windows o antivírus/indexador às vezes segura o arquivo por instantes: tenta de novo."""
    for i in range(10):
        try:
            os.replace(tmp, destino)
            return
        except PermissionError:
            if i == 9:
                raise
            time.sleep(0.05 * (i + 1))


def sanear(texto, limite=LIMITE_CORPO):
    """Texto seguro para o push: sem endereços, caminhos, trechos de código, comandos ou sequências que lembrem token;
    espaços normalizados; no máximo `limite` caracteres."""
    t = str(texto or "")
    t = re.sub(r"`[^`]*`", " ", t)                                   # trecho de código
    t = re.sub(r"\b[a-z][a-z0-9+.-]*://\S+", " ", t, flags=re.I)     # URLs
    t = re.sub(r"\b[A-Za-z]:[\\/]\S*", " ", t)                       # caminho do Windows
    t = re.sub(r"(?<![\w])(?:~|\.{1,2})?/(?:[\w.@-]+/)+[\w.@-]*", " ", t)   # caminho Unix
    t = re.sub(r"\S*[\\/]\S*", " ", t)                               # qualquer coisa com barra
    t = re.sub(r"(?<!\w)--?[A-Za-z][\w-]*=?\S*", " ", t)             # flags de comando
    t = re.sub(r"\b[A-Za-z0-9_+=-]{24,}\b", " ", t)                  # tokens/hashes longos
    t = re.sub(r"[\x00-\x1f\x7f<>{}\[\]$|;]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t if len(t) <= limite else t[:limite - 1].rstrip() + "…"


def url_relativa(u):
    """Endereço do painel dentro do escritório ('/#alerta=prs'); qualquer outra coisa vira '/'."""
    u = str(u or "")
    return u if re.fullmatch(r"/(?:#[A-Za-z0-9=_-]{0,40})?", u) else "/"


def endpoint_valido(url):
    """True se o endpoint é HTTPS de um serviço de push conhecido (sem usuário/senha, porta 443)."""
    try:
        u = urlparse(str(url))
        host = (u.hostname or "").lower()
        if u.scheme != "https" or u.username or u.password or u.port not in (None, 443) or len(str(url)) > 1000:
            return False
    except ValueError:
        return False
    return any(host == s or host.endswith("." + s) for s in SERVICOS_PUSH)


def id_inscricao(endpoint):
    """Identificador curto e estável da inscrição (os 12 primeiros hex do SHA-256 do endpoint)."""
    return hashlib.sha256(str(endpoint).encode("utf-8")).hexdigest()[:12]


# ---------------------------------------------------------------- RFC 8291: cifrar o conteúdo (aes128gcm)
def _chave_publica_bytes(privada):
    return privada.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def _hkdf(tamanho, sal, info, material):
    return HKDF(algorithm=hashes.SHA256(), length=tamanho, salt=sal, info=info).derive(material)


def cifrar(texto, p256dh, auth, privada_as=None, sal=None):
    """Corpo da requisição Web Push (RFC 8291): cabeçalho aes128gcm (sal, rs, idlen, chave pública efêmera) + 1 registro.
    `p256dh` (65 bytes) e `auth` (16 bytes) vêm da inscrição do navegador; `privada_as` e `sal` só para testes."""
    if CRIPTO_ERRO:
        raise RuntimeError(CRIPTO_ERRO)
    if len(auth) != 16 or len(p256dh) != 65 or p256dh[0] != 4:
        raise ValueError("chaves da inscrição inválidas")
    ua_publica = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), p256dh)
    privada_as = privada_as or ec.generate_private_key(ec.SECP256R1())
    as_publica = _chave_publica_bytes(privada_as)
    segredo = privada_as.exchange(ec.ECDH(), ua_publica)
    sal = sal if sal is not None else os.urandom(16)
    if len(sal) != 16:
        raise ValueError("sal deve ter 16 bytes")
    ikm = _hkdf(32, auth, b"WebPush: info\x00" + p256dh + as_publica, segredo)
    cek = _hkdf(16, sal, b"Content-Encoding: aes128gcm\x00", ikm)
    nonce = _hkdf(12, sal, b"Content-Encoding: nonce\x00", ikm)
    if len(texto) + 1 + 16 > TAMANHO_REGISTRO:
        raise ValueError("mensagem grande demais para um registro")
    cifrado = AESGCM(cek).encrypt(nonce, texto + b"\x02", None)   # 0x02 = delimitador do último registro
    return sal + TAMANHO_REGISTRO.to_bytes(4, "big") + bytes([len(as_publica)]) + as_publica + cifrado


# ---------------------------------------------------------------- RFC 8292: VAPID
def nova_chave_vapid():
    return ec.generate_private_key(ec.SECP256R1())


def chave_publica_b64u(privada):
    return b64u(_chave_publica_bytes(privada))


def jwt_vapid(privada, audiencia, contato=CONTATO_PADRAO, agora=None, validade=12 * 3600):
    """JWT ES256 do VAPID: aud = origem do serviço de push, exp (< 24 h), sub = contato. Assinatura r||s de 64 bytes."""
    agora = int(time.time() if agora is None else agora)
    cab = b64u(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
    corpo = b64u(json.dumps({"aud": audiencia, "exp": agora + int(validade), "sub": contato}, separators=(",", ":")).encode())
    msg = f"{cab}.{corpo}".encode("ascii")
    r, s = decode_dss_signature(privada.sign(msg, ec.ECDSA(hashes.SHA256())))
    return f"{cab}.{corpo}.{b64u(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"


def cabecalho_vapid(privada, endpoint, contato=CONTATO_PADRAO, agora=None):
    u = urlparse(endpoint)
    jwt = jwt_vapid(privada, f"{u.scheme}://{u.netloc}", contato, agora)
    return f"vapid t={jwt}, k={chave_publica_b64u(privada)}"


# ---------------------------------------------------------------- envio (RFC 8030)
class _SemRedirecionar(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None   # nunca segue redirecionamento: o endpoint é só o que foi validado


def _postar(endpoint, corpo, cabecalhos, timeout=15):
    """POST ao serviço de push. Devolve o código HTTP (ou 0 se a rede falhou)."""
    req = urllib.request.Request(endpoint, data=corpo, method="POST", headers=cabecalhos)
    try:
        with urllib.request.build_opener(_SemRedirecionar).open(req, timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except (urllib.error.URLError, OSError, ValueError):
        return 0


class Push:
    """Chaves VAPID, inscrições e envio, em `<dados>/push/`. Toda a pasta fica fora do git (dados/)."""

    def __init__(self, pasta_dados, contato=CONTATO_PADRAO, limite_hora=20, enviar_http=None):
        self.pasta = Path(pasta_dados) / "push"
        self.contato = str(contato or CONTATO_PADRAO)
        self.limite_hora = max(1, int(limite_hora))
        self.trava = threading.RLock()
        self._http = enviar_http or _postar
        self._privada = None
        self._envios = deque()   # instantes dos envios da última hora (limite global)
        self.arq_inscricoes = self.pasta / "inscricoes.json"
        self.arq_log = self.pasta / "envios.jsonl"

    # ------------------------------------------------------------ disponibilidade e chaves
    def disponivel(self):
        """(ok, motivo)."""
        return (not CRIPTO_ERRO), CRIPTO_ERRO

    def _vapid(self):
        """Chave VAPID privada; gerada UMA vez (primeiro uso real) e guardada em dados/push/vapid_privada.pem."""
        with self.trava:
            if self._privada is None:
                arq = self.pasta / "vapid_privada.pem"
                try:
                    self._privada = serialization.load_pem_private_key(arq.read_bytes(), password=None)
                except (OSError, ValueError, TypeError):
                    self._privada = nova_chave_vapid()
                    self.pasta.mkdir(parents=True, exist_ok=True)
                    arq.write_bytes(self._privada.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                                serialization.NoEncryption()))
                    try:
                        os.chmod(arq, 0o600)
                    except OSError:
                        pass
            return self._privada

    def chave_publica(self):
        """Chave pública VAPID (base64url, 65 bytes) para o navegador: applicationServerKey."""
        return chave_publica_b64u(self._vapid())

    # ------------------------------------------------------------ inscrições
    def _ler(self):
        try:
            lido = json.loads(self.arq_inscricoes.read_text(encoding="utf-8"))
            return [x for x in lido if isinstance(x, dict) and x.get("endpoint")]
        except (OSError, ValueError):
            return []

    def _gravar(self, lista):
        self.pasta.mkdir(parents=True, exist_ok=True)
        tmp = self.arq_inscricoes.with_suffix(".tmp")
        tmp.write_text(json.dumps(lista, ensure_ascii=False, indent=1), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        trocar_arquivo(tmp, self.arq_inscricoes)

    def inscrever(self, aparelho, nome, assinatura, tipos, validar=True):
        """Guarda a inscrição do navegador deste aparelho. Devolve (ok, erro, id)."""
        if CRIPTO_ERRO:
            return False, CRIPTO_ERRO, ""
        if not isinstance(assinatura, dict) or not isinstance(assinatura.get("keys"), dict):
            return False, "inscrição inválida", ""
        endpoint = assinatura.get("endpoint")
        if not isinstance(endpoint, str) or (validar and not endpoint_valido(endpoint)):
            return False, "o endereço do serviço de push não é de um serviço conhecido (Google, Mozilla, Apple ou Windows)", ""
        try:
            p256dh, auth = b64u_dec(assinatura["keys"].get("p256dh")), b64u_dec(assinatura["keys"].get("auth"))
            if len(auth) != 16 or len(p256dh) != 65 or p256dh[0] != 4:
                raise ValueError("tamanho")
            ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), p256dh)   # ponto válido na curva
        except (ValueError, TypeError, KeyError):
            return False, "chaves da inscrição inválidas", ""
        reg = {"id": id_inscricao(endpoint), "aparelho": str(aparelho), "nome": str(nome)[:40], "endpoint": endpoint,
               "p256dh": b64u(p256dh), "auth": b64u(auth), "tipos": self.limpar_tipos(tipos), "criado": time.time()}
        with self.trava:
            lista = [x for x in self._ler() if x.get("id") != reg["id"]]
            proprios = [x for x in lista if x.get("aparelho") == reg["aparelho"]]
            if len(proprios) >= 4:   # no máximo 4 navegadores por aparelho: o mais antigo sai
                lista.remove(min(proprios, key=lambda x: x.get("criado", 0)))
            if len(lista) >= MAX_INSCRICOES:
                return False, "inscrições demais; remova alguma antes", ""
            lista.append(reg)
            self._gravar(lista)
        return True, "", reg["id"]

    @staticmethod
    def limpar_tipos(tipos):
        """{tipo: bool} só com chaves seguras; None = sem preferência (vale o padrão do servidor)."""
        if not isinstance(tipos, dict):
            return None
        return {str(k)[:30]: bool(v) for k, v in list(tipos.items())[:20] if re.fullmatch(r"[a-z_]{1,30}", str(k))}

    def sair(self, aparelho, endpoint):
        """Apaga a inscrição (só do próprio aparelho; o PC pode apagar as do PC). True se apagou."""
        i = id_inscricao(endpoint)
        with self.trava:
            lista = self._ler()
            resto = [x for x in lista if not (x.get("id") == i and x.get("aparelho") == str(aparelho))]
            if len(resto) != len(lista):
                self._gravar(resto)
                return True
        return False

    def estado(self, aparelho, id_):
        """Inscrição do aparelho com esse id curto, ou None."""
        for x in self._ler():
            if x.get("id") == id_ and x.get("aparelho") == str(aparelho):
                return {"id": x["id"], "tipos": x.get("tipos"), "nome": x.get("nome", "")}
        return None

    def atualizar_tipos(self, aparelho, id_, tipos):
        with self.trava:
            lista = self._ler()
            achou = False
            for x in lista:
                if x.get("id") == id_ and x.get("aparelho") == str(aparelho):
                    x["tipos"], achou = self.limpar_tipos(tipos), True
            if achou:
                self._gravar(lista)
        return achou

    def remover_aparelhos(self, ids):
        """Apaga as inscrições dos aparelhos (aparelho revogado). Devolve quantas foram apagadas."""
        ids = {str(i) for i in ids}
        with self.trava:
            lista = self._ler()
            resto = [x for x in lista if x.get("aparelho") not in ids]
            if len(resto) != len(lista):
                self._gravar(resto)
            return len(lista) - len(resto)

    def podar(self, ids_validos):
        """Apaga inscrições de aparelhos que não existem mais (sessão expirada/revogada com o servidor fora do ar)."""
        validos = {str(i) for i in ids_validos} | {"pc"}
        with self.trava:
            lista = self._ler()
            if any(x.get("aparelho") not in validos for x in lista):
                return self.remover_aparelhos({x.get("aparelho") for x in lista} - validos)
        return 0

    def quantas(self):
        return len(self._ler())

    # ------------------------------------------------------------ envio
    def _pode_enviar(self):
        """Limite global de envios por hora (padrão 20)."""
        agora = time.time()
        with self.trava:
            while self._envios and agora - self._envios[0] > 3600:
                self._envios.popleft()
            if len(self._envios) >= self.limite_hora:
                return False
            self._envios.append(agora)
            return True

    def _registrar(self, linha):
        try:
            self.pasta.mkdir(parents=True, exist_ok=True)
            with open(self.arq_log, "a", encoding="utf-8") as f:
                f.write(json.dumps(linha, ensure_ascii=False) + "\n")
        except OSError:
            pass

    @staticmethod
    def _quer(sub, tipo, padroes):
        tipos = sub.get("tipos")
        if isinstance(tipos, dict) and tipo in tipos:
            return bool(tipos[tipo])
        return bool((padroes or {}).get(tipo, True))

    def enviar(self, alerta, so_aparelho=None, padroes=None, ignorar_tipos=False, validar=True):
        """Envia o alerta às inscrições que querem esse tipo. Devolve {"enviados", "falhas", "limitados", "removidos"}.
        O conteúdo é só título, corpo e o painel (sanitizados); `so_aparelho` restringe a um aparelho (alerta de teste)."""
        res = {"enviados": 0, "falhas": 0, "limitados": 0, "removidos": 0, "motivo": ""}
        if CRIPTO_ERRO:
            res["motivo"] = CRIPTO_ERRO
            return res
        carga = json.dumps({"t": sanear(alerta.get("titulo"), LIMITE_TITULO), "c": sanear(alerta.get("corpo"), LIMITE_CORPO),
                            "u": url_relativa(alerta.get("url")), "k": str(alerta.get("tipo", ""))[:30],
                            "i": int(alerta.get("id") or 0)}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        for sub in self._ler():
            if so_aparelho is not None and sub.get("aparelho") != str(so_aparelho):
                continue
            # o push de resumo leva `tipos` (os avisos agrupados): vai a quem quer pelo menos um deles
            if not ignorar_tipos and not any(self._quer(sub, t, padroes) for t in (alerta.get("tipos") or [alerta.get("tipo")])):
                continue
            if validar and not endpoint_valido(sub["endpoint"]):
                continue
            if not self._pode_enviar():
                res["limitados"] += 1
                self._registrar({"ts": time.time(), "aparelho": sub.get("nome"), "tipo": alerta.get("tipo"), "codigo": 0,
                                 "resultado": "limite por hora"})
                continue
            try:
                corpo = cifrar(carga, b64u_dec(sub["p256dh"]), b64u_dec(sub["auth"]))
                cab = {"TTL": "3600", "Urgency": "normal", "Content-Encoding": "aes128gcm",
                       "Content-Type": "application/octet-stream", "User-Agent": "OfficeAlertas/1",
                       "Authorization": cabecalho_vapid(self._vapid(), sub["endpoint"], self.contato)}
                codigo = self._http(sub["endpoint"], corpo, cab)
            except (ValueError, RuntimeError, KeyError) as e:
                codigo, res["motivo"] = 0, str(e)[:100]
            if codigo in (404, 410):   # inscrição morta (app desinstalado, permissão revogada): apaga
                with self.trava:
                    self._gravar([x for x in self._ler() if x.get("id") != sub.get("id")])
                res["removidos"] += 1
            if 200 <= codigo < 300:
                res["enviados"] += 1
            else:
                res["falhas"] += 1
            self._registrar({"ts": time.time(), "aparelho": sub.get("nome"), "tipo": alerta.get("tipo"), "codigo": codigo,
                             "resultado": "ok" if 200 <= codigo < 300 else ("removida" if codigo in (404, 410) else "falhou")})
        return res
