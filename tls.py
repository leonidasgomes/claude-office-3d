"""HTTPS local para o acesso pelo celular: autoridade certificadora (CA) própria, grátis e sem conta.

Gera em dados/tls/ (fora do git): ca.key (NUNCA é servida), ca.crt, servidor.key, servidor.crt, meta.json.
  * A CA só vale para IPs privados (NameConstraints: 10/8, 172.16/12, 192.168/16, opcional 100.64/10 do Tailscale)
    e para os nomes "localhost" e ".local": instalar essa CA no celular NÃO permite falsificar nenhum site da internet.
    Basic constraints CA:TRUE pathlen:0; uso de chave keyCertSign + cRLSign; validade de 3 anos.
  * O certificado do servidor vale 390 dias (o iOS aceita até 397), com SAN dos IPv4 privados atuais da máquina,
    "localhost" e "<hostname>.local", e é refeito quando os IPs mudam ou faltam menos de 30 dias.
Usa a biblioteca `cryptography` se estiver instalada; senão o `openssl` do PATH (ou do Git for Windows); se nenhum
existir, levanta TLSIndisponivel e o servidor cai para HTTP com aviso.
"""
import datetime
import hashlib
import ipaddress
import json
import os
import plistlib
import re
import shutil
import socket
import ssl
import subprocess
import tempfile
import uuid
from pathlib import Path

VALIDADE_CA_DIAS = 1095
VALIDADE_SERVIDOR_DIAS = 390
RENOVAR_FALTANDO_DIAS = 30
REDES_PRIVADAS = ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"]
TAILSCALE_REDE = "100.64.0.0/10"


class TLSIndisponivel(Exception):
    pass


def pasta_tls(pasta):
    return Path(pasta) / "dados" / "tls"


def _nome_host():
    return re.sub(r"[^A-Za-z0-9-]", "", socket.gethostname()).lower()


def nome_ca():
    return f"Claude Office 3D — CA local ({socket.gethostname()})"


def _redes(tailscale):
    return REDES_PRIVADAS + ([TAILSCALE_REDE] if tailscale else [])


def _sans(ips):
    """Nomes e IPs do certificado do servidor (127.0.0.1 fica de fora: não está nas sub-árvores permitidas da CA)."""
    nomes = ["localhost"] + ([f"{_nome_host()}.local"] if _nome_host() else [])
    return nomes, [i for i in ips if i != "127.0.0.1"]


def achar_openssl():
    candidatos = [shutil.which("openssl")]
    git = shutil.which("git")
    if git:   # git.exe fica em <raiz>/cmd: o Git for Windows traz o openssl em <raiz>/usr/bin e <raiz>/mingw64/bin
        raiz = Path(git).resolve().parent.parent
        candidatos += [raiz / "usr" / "bin" / "openssl.exe", raiz / "mingw64" / "bin" / "openssl.exe"]
    candidatos += [r"C:\Program Files\Git\usr\bin\openssl.exe", r"C:\Program Files\Git\mingw64\bin\openssl.exe",
                   "/mingw64/bin/openssl", "/usr/bin/openssl", "/opt/homebrew/bin/openssl", "/usr/local/bin/openssl"]
    for c in candidatos:
        if c and Path(c).is_file():
            return str(c)
    return None


def metodo_disponivel():
    try:
        import cryptography  # noqa: F401
        return "cryptography"
    except ImportError:
        return "openssl" if achar_openssl() else None


# ---------------------------------------------------------------- geração com a biblioteca cryptography
def _gerar_cryptography(d, ips, tailscale, so_servidor):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    def chave():
        return rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def pem_chave(k):
        return k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())

    agora = datetime.datetime.now(datetime.timezone.utc)
    if so_servidor:
        ca_key = serialization.load_pem_private_key((d / "ca.key").read_bytes(), None)
        ca_cert = x509.load_pem_x509_certificate((d / "ca.crt").read_bytes())
    else:
        ca_key = chave()
        nome = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, nome_ca())])
        permitidos = [x509.IPAddress(ipaddress.ip_network(r)) for r in _redes(tailscale)]
        permitidos += [x509.DNSName("localhost"), x509.DNSName(".local")]
        ca_cert = (x509.CertificateBuilder().subject_name(nome).issuer_name(nome).public_key(ca_key.public_key())
                   .serial_number(x509.random_serial_number()).not_valid_before(agora - datetime.timedelta(hours=1))
                   .not_valid_after(agora + datetime.timedelta(days=VALIDADE_CA_DIAS))
                   .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
                   .add_extension(x509.KeyUsage(digital_signature=False, content_commitment=False, key_encipherment=False,
                                                data_encipherment=False, key_agreement=False, key_cert_sign=True, crl_sign=True,
                                                encipher_only=False, decipher_only=False), critical=True)
                   .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
                   .add_extension(x509.NameConstraints(permitted_subtrees=permitidos, excluded_subtrees=None), critical=True)
                   .sign(ca_key, hashes.SHA256()))
        (d / "ca.key").write_bytes(pem_chave(ca_key))
        (d / "ca.crt").write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
    nomes, ips_san = _sans(ips)
    k = chave()
    san = [x509.DNSName(n) for n in nomes] + [x509.IPAddress(ipaddress.ip_address(i)) for i in ips_san]
    cert = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")]))
            .issuer_name(ca_cert.subject).public_key(k.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(agora - datetime.timedelta(hours=1))
            .not_valid_after(agora + datetime.timedelta(days=VALIDADE_SERVIDOR_DIAS))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False, key_encipherment=True,
                                         data_encipherment=False, key_agreement=False, key_cert_sign=False, crl_sign=False,
                                         encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.SubjectAlternativeName(san), critical=False)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(k.public_key()), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256()))
    (d / "servidor.key").write_bytes(pem_chave(k))
    (d / "servidor.crt").write_bytes(cert.public_bytes(serialization.Encoding.PEM))


# ---------------------------------------------------------------- geração com o openssl
def _rodar(exe, args, cwd):
    r = subprocess.run([exe, *args], cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    if r.returncode:
        raise TLSIndisponivel("openssl falhou: " + (r.stderr or r.stdout).strip().splitlines()[-1][:200])


def _gerar_openssl(d, ips, tailscale, so_servidor):
    exe = achar_openssl()
    if not exe:
        raise TLSIndisponivel("nem a biblioteca 'cryptography' nem o openssl foram encontrados")
    nomes, ips_san = _sans(ips)
    with tempfile.TemporaryDirectory(prefix="office-tls") as t:
        t = Path(t)
        if not so_servidor:
            nc = []
            for i, r in enumerate(_redes(tailscale), 1):
                rede = ipaddress.ip_network(r)
                nc.append(f"permitted;IP.{i} = {rede.network_address}/{rede.netmask}")
            nc += ["permitted;DNS.1 = localhost", "permitted;DNS.2 = .local"]
            (t / "ca.cnf").write_text(
                "[req]\ndistinguished_name = dn\nprompt = no\nutf8 = yes\nstring_mask = utf8only\nx509_extensions = v3_ca\n"
                f"[dn]\nCN = {nome_ca()}\n"
                "[v3_ca]\nbasicConstraints = critical,CA:TRUE,pathlen:0\nkeyUsage = critical,keyCertSign,cRLSign\n"
                "subjectKeyIdentifier = hash\nnameConstraints = critical,@nc\n[nc]\n" + "\n".join(nc) + "\n", encoding="utf-8")
            _rodar(exe, ["req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", "ca.key", "-out", "ca.crt", "-days",
                         str(VALIDADE_CA_DIAS), "-sha256", "-config", "ca.cnf"], t)
            shutil.copy(t / "ca.key", d / "ca.key")
            shutil.copy(t / "ca.crt", d / "ca.crt")
        else:
            shutil.copy(d / "ca.key", t / "ca.key")
            shutil.copy(d / "ca.crt", t / "ca.crt")
        alt = [f"DNS.{i} = {n}" for i, n in enumerate(nomes, 1)] + [f"IP.{i} = {ip}" for i, ip in enumerate(ips_san, 1)]
        (t / "srv.cnf").write_text(
            "[req]\ndistinguished_name = dn\nprompt = no\n[dn]\nCN = localhost\n"
            "[srv]\nbasicConstraints = critical,CA:FALSE\nkeyUsage = critical,digitalSignature,keyEncipherment\n"
            "extendedKeyUsage = serverAuth\nsubjectAltName = @alt\nsubjectKeyIdentifier = hash\nauthorityKeyIdentifier = keyid\n"
            "[alt]\n" + "\n".join(alt) + "\n", encoding="utf-8")
        _rodar(exe, ["req", "-new", "-newkey", "rsa:2048", "-nodes", "-keyout", "servidor.key", "-out", "servidor.csr",
                     "-config", "srv.cnf"], t)
        _rodar(exe, ["x509", "-req", "-in", "servidor.csr", "-CA", "ca.crt", "-CAkey", "ca.key", "-CAcreateserial", "-out",
                     "servidor.crt", "-days", str(VALIDADE_SERVIDOR_DIAS), "-sha256", "-extfile", "srv.cnf", "-extensions", "srv"], t)
        shutil.copy(t / "servidor.key", d / "servidor.key")
        shutil.copy(t / "servidor.crt", d / "servidor.crt")


# ---------------------------------------------------------------- API
def impressao(arq):
    """SHA-256 do certificado (DER) no formato AA:BB:..., para conferir no celular."""
    try:
        der = ssl.PEM_cert_to_DER_cert(Path(arq).read_text(encoding="ascii"))
    except (OSError, ValueError):
        return ""
    h = hashlib.sha256(der).hexdigest().upper()
    return ":".join(h[i:i + 2] for i in range(0, len(h), 2))


def _meta(d):
    try:
        return json.loads((d / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def garantir(pasta, ips, tailscale=False, forcar_metodo=None):
    """Cria (1ª vez) ou renova a CA/o certificado do servidor. Devolve o dicionário de informações.

    ips: IPv4 privados atuais da máquina. Levanta TLSIndisponivel se não houver como gerar."""
    import time
    d = pasta_tls(pasta)
    d.mkdir(parents=True, exist_ok=True)
    ips = sorted(set(ips))
    meta = _meta(d)
    agora = time.time()
    ca_ok = (d / "ca.key").is_file() and (d / "ca.crt").is_file() and meta.get("tailscale") == bool(tailscale) \
        and meta.get("ca_expira", 0) - agora > 60 * 86400
    srv_ok = ca_ok and (d / "servidor.crt").is_file() and (d / "servidor.key").is_file() and meta.get("ips") == ips \
        and meta.get("servidor_expira", 0) - agora > RENOVAR_FALTANDO_DIAS * 86400
    metodo = meta.get("metodo")
    if not srv_ok:
        metodo = forcar_metodo or metodo_disponivel()
        if not metodo:
            raise TLSIndisponivel("instale a biblioteca 'cryptography' (pip install cryptography) ou o OpenSSL para ter HTTPS")
        gerar = _gerar_cryptography if metodo == "cryptography" else _gerar_openssl
        try:
            gerar(d, ips, bool(tailscale), so_servidor=ca_ok)
        except TLSIndisponivel:
            raise
        except Exception as e:  # noqa: BLE001 — qualquer falha da biblioteca vira "HTTPS indisponível"
            raise TLSIndisponivel(f"não consegui gerar os certificados ({metodo}): {str(e)[:200]}")
        for arq in ("ca.key", "servidor.key"):
            try:
                os.chmod(d / arq, 0o600)
            except OSError:
                pass
        meta = {"tailscale": bool(tailscale), "ips": ips, "metodo": metodo, "hostname": socket.gethostname(),
                "gerado": agora, "servidor_expira": agora + VALIDADE_SERVIDOR_DIAS * 86400,
                "ca_expira": meta.get("ca_expira") if ca_ok else agora + VALIDADE_CA_DIAS * 86400}
        (d / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    return informacoes(pasta)


def informacoes(pasta):
    d = pasta_tls(pasta)
    meta = _meta(d)
    return {"ok": True, "metodo": meta.get("metodo", ""), "ips": meta.get("ips", []),
            "ca_sha256": impressao(d / "ca.crt"), "servidor_sha256": impressao(d / "servidor.crt"),
            "ca_expira": meta.get("ca_expira", 0), "servidor_expira": meta.get("servidor_expira", 0), "erro": ""}


def recriar(pasta, ips, tailscale=False, forcar_metodo=None):
    """Apaga dados/tls e gera tudo de novo (exige reinstalar a CA nos celulares)."""
    d = pasta_tls(pasta)
    if d.exists():
        shutil.rmtree(d)
    return garantir(pasta, ips, tailscale, forcar_metodo)


def contexto(pasta):
    """SSLContext do servidor: TLS 1.2 no mínimo, certificado do servidor (a chave da CA nunca é carregada)."""
    d = pasta_tls(pasta)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(str(d / "servidor.crt"), str(d / "servidor.key"))
    return ctx


def ca_pem(pasta):
    return (pasta_tls(pasta) / "ca.crt").read_bytes()


def ca_mobileconfig(pasta):
    """Perfil do iOS que instala a CA (o iOS ainda pede para ativar a confiança em Ajustes)."""
    der = ssl.PEM_cert_to_DER_cert(ca_pem(pasta).decode("ascii"))
    base = uuid.uuid5(uuid.NAMESPACE_URL, "claude-office-3d-ca:" + impressao(pasta_tls(pasta) / "ca.crt"))
    perfil = {
        "PayloadContent": [{"PayloadType": "com.apple.security.root", "PayloadVersion": 1,
                            "PayloadIdentifier": "local.claudeoffice3d.ca.cert", "PayloadUUID": str(uuid.uuid5(base, "cert")).upper(),
                            "PayloadDisplayName": nome_ca(), "PayloadContent": der}],
        "PayloadType": "Configuration", "PayloadVersion": 1, "PayloadIdentifier": "local.claudeoffice3d.ca",
        "PayloadUUID": str(base).upper(), "PayloadDisplayName": nome_ca(), "PayloadOrganization": "Claude Office 3D",
        "PayloadDescription": "Instala a autoridade certificadora local do Claude Office 3D (só vale para IPs privados).",
    }
    return plistlib.dumps(perfil)
