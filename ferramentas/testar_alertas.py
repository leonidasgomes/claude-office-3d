"""Teste dos alertas (detector, fila, Web Push cifrado, VAPID, limite de envio). Roda sem rede e sem navegador.

Uso: python -W error ferramentas/testar_alertas.py
Cifra com a implementação do push.py e DECIFRA de volta com uma implementação de referência escrita aqui, só com
HMAC/AES (RFC 8291), e também confere o exemplo oficial do apêndice A da RFC 8291. O "serviço de push" é um servidor
HTTP local de mentira: o teste vê os cabeçalhos reais que sairiam para o Google/Apple/Mozilla.
"""
import hashlib
import hmac
import json
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
import alertas  # noqa: E402
import cota  # noqa: E402
import push  # noqa: E402

if push.CRIPTO_ERRO:
    sys.exit("SEM 'cryptography': " + push.CRIPTO_ERRO)
from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature  # noqa: E402
from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: E402

feitos = []


def ok(nome):
    feitos.append(nome)
    print("  ok:", nome)


def pub_bytes(privada):
    return privada.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


# ---------------------------------------------------------------- referência RFC 8291 (só HMAC + AES-GCM)
def _extract(sal, ikm):
    return hmac.new(sal, ikm, hashlib.sha256).digest()


def _expand(prk, info, n):
    saida, t, i = b"", b"", 1
    while len(saida) < n:
        t = hmac.new(prk, t + info + bytes([i]), hashlib.sha256).digest()
        saida, i = saida + t, i + 1
    return saida[:n]


def decifrar_referencia(corpo, ua_privada, auth):
    """Decifra um corpo aes128gcm como o navegador faz (RFC 8188 + RFC 8291 seção 3.4)."""
    sal, rs, idlen = corpo[:16], int.from_bytes(corpo[16:20], "big"), corpo[20]
    as_publica, cifrado = corpo[21:21 + idlen], corpo[21 + idlen:]
    assert idlen == 65 and rs >= len(cifrado), "cabeçalho aes128gcm inconsistente"
    segredo = ua_privada.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_publica))
    ikm = _expand(_extract(auth, segredo), b"WebPush: info\x00" + pub_bytes(ua_privada) + as_publica, 32)
    prk = _extract(sal, ikm)
    cek, nonce = _expand(prk, b"Content-Encoding: aes128gcm\x00", 16), _expand(prk, b"Content-Encoding: nonce\x00", 12)
    claro = AESGCM(cek).decrypt(nonce, cifrado, None).rstrip(b"\x00")
    assert claro[-1:] == b"\x02", "delimitador do último registro ausente"
    return claro[:-1]


def b64(s):
    return push.b64u_dec(s)


def testar_rfc8291():
    # RFC 8291, apêndice A (exemplo de teste)
    claro = b"When I grow up, I want to be a watermelon"
    ua_priv = ec.derive_private_key(int.from_bytes(b64("q1dXpw3UpT5VOmu_cf_v6ih07Aems3njxI-JWgLcM94"), "big"), ec.SECP256R1())
    as_priv = ec.derive_private_key(int.from_bytes(b64("yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw"), "big"), ec.SECP256R1())
    auth, sal = b64("BTBZMqHH6r4Tts7J_aSIgg"), b64("DGv6ra1nlYgDCS1FRnbzlw")
    ua_pub = pub_bytes(ua_priv)
    assert push.b64u(ua_pub) == "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4", "chave pública do navegador do exemplo"
    esperado = ("DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A"
                "_yl95bQpu6cVPTpK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN")
    corpo = push.cifrar(claro, ua_pub, auth, privada_as=as_priv, sal=sal)
    assert push.b64u(corpo) == esperado, "o corpo cifrado não bate com o exemplo da RFC 8291"
    ok("RFC 8291 apêndice A: o push.py gera exatamente o corpo cifrado do exemplo oficial")
    assert decifrar_referencia(b64(esperado), ua_priv, auth) == claro
    ok("RFC 8291 apêndice A: a referência decifra o exemplo oficial de volta para o texto original")


def testar_roundtrip():
    for i in range(20):
        ua_priv = ec.generate_private_key(ec.SECP256R1())
        auth = hashlib.sha256(bytes([i])).digest()[:16]
        claro = json.dumps({"t": "Título ção", "c": "x" * (i * 5), "u": "/#alerta=prs", "k": "pr_pronto", "i": i}, ensure_ascii=False).encode()
        corpo = push.cifrar(claro, pub_bytes(ua_priv), auth)
        assert decifrar_referencia(corpo, ua_priv, auth) == claro
        falhou = False
        try:
            decifrar_referencia(corpo, ec.generate_private_key(ec.SECP256R1()), auth)
        except Exception:
            falhou = True
        assert falhou, "outra chave não deveria decifrar"
    ok("cifra e decifra de volta com pares de chaves aleatórios (20 mensagens); chave errada não decifra")


def testar_vapid():
    priv = push.nova_chave_vapid()
    jwt = push.jwt_vapid(priv, "https://fcm.googleapis.com", "mailto:alertas@example.com", agora=1_000_000)
    cab, corpo, sig = jwt.split(".")
    assert json.loads(b64(cab)) == {"typ": "JWT", "alg": "ES256"}
    cl = json.loads(b64(corpo))
    assert cl == {"aud": "https://fcm.googleapis.com", "exp": 1_000_000 + 12 * 3600, "sub": "mailto:alertas@example.com"}
    assert cl["exp"] - 1_000_000 < 86400
    bruta = b64(sig)
    assert len(bruta) == 64
    der = encode_dss_signature(int.from_bytes(bruta[:32], "big"), int.from_bytes(bruta[32:], "big"))
    priv.public_key().verify(der, f"{cab}.{corpo}".encode(), ec.ECDSA(hashes.SHA256()))
    ok("JWT VAPID: cabeçalho, aud/exp/sub e assinatura ES256 verificada com a chave pública")
    h = push.cabecalho_vapid(priv, "https://updates.push.services.mozilla.com/wpush/v2/abc", agora=1_000_000)
    assert h.startswith("vapid t=") and h.endswith(", k=" + push.chave_publica_b64u(priv))
    assert json.loads(b64(h.split("t=")[1].split(".")[1]))["aud"] == "https://updates.push.services.mozilla.com"
    ok("cabeçalho Authorization: vapid t=..., k=... com a origem do serviço como aud")


def testar_sanear_e_endpoints():
    perigosos = ["rode `rm -rf /` agora", "veja C:\\Users\\voce\\segredo.txt", "abra /home/voce/y/z.py", "https://x.example/p?token=abc",
                 "python xp.py --liberar 12", "tok " + "A" * 40]
    for p in perigosos:
        s = push.sanear(p)
        assert not any(x in s for x in ("rm -rf", "C:\\", "/home", "http", "--liberar", "A" * 20, "`")), (p, s)
    assert push.sanear("palavra " * 60).endswith("…") and len(push.sanear("palavra " * 60)) <= push.LIMITE_CORPO
    assert push.sanear("PR #303 aprovado, sem conflito.") == "PR #303 aprovado, sem conflito."
    assert push.url_relativa("/#alerta=prs") == "/#alerta=prs" and push.url_relativa("https://x.com") == "/" and push.url_relativa("//x.com") == "/"
    ok("sanear remove comando, caminho, URL, código e token; corpo ≤ 120; URL do painel só relativa")
    for e in ("https://fcm.googleapis.com/fcm/send/abc", "https://updates.push.services.mozilla.com/wpush/v2/x",
              "https://web.push.apple.com/Q", "https://wns2-par02p.notify.windows.com/?token=x"):
        assert push.endpoint_valido(e), e
    for e in ("http://fcm.googleapis.com/x", "https://127.0.0.1/x", "https://localhost/x", "https://evil.com/fcm.googleapis.com",
              "https://fcm.googleapis.com.evil.com/x", "https://user:pw" + "@fcm.googleapis.com/x", "https://fcm.googleapis.com:8443/x",
              "https://192.168.1.1/x", "file:///etc/passwd"):
        assert not push.endpoint_valido(e), e
    ok("endpoint só de serviço de push conhecido (https, sem IP/localhost/porta/usuário): sem SSRF")


# ---------------------------------------------------------------- serviço de push de mentira
class ServicoFalso:
    def __init__(self):
        self.recebidos, self.codigo = [], 201
        dono = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                dono.recebidos.append({"caminho": self.path, "cab": {k.lower(): v for k, v in self.headers.items()}, "corpo": self.rfile.read(n)})
                self.send_response(dono.codigo)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *a):
                pass
        self.srv = HTTPServer(("127.0.0.1", 0), H)
        self.porta = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def parar(self):
        self.srv.shutdown()
        self.srv.server_close()


def nova_assinatura(servico, caminho="/push/1"):
    priv = ec.generate_private_key(ec.SECP256R1())
    auth = hashlib.sha256(caminho.encode()).digest()[:16]
    return priv, auth, {"endpoint": f"http://127.0.0.1:{servico.porta}{caminho}", "keys": {"p256dh": push.b64u(pub_bytes(priv)), "auth": push.b64u(auth)}}


def testar_envio():
    srv = ServicoFalso()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            p = push.Push(tmp, "mailto:alertas@example.com", limite_hora=3)
            priv, auth, sub = nova_assinatura(srv)
            assert p.inscrever("aparelho1", "Celular", sub, {"conferir": True}, validar=True)[0] is False   # http://127.0.0.1 é recusado
            ok_, erro, id_ = p.inscrever("aparelho1", "Celular", sub, {"conferir": True}, validar=False)
            assert ok_ and id_ == push.id_inscricao(sub["endpoint"]), erro
            assert p.inscrever("a", "x", {"endpoint": sub["endpoint"], "keys": {"p256dh": "AAAA", "auth": "AAAA"}}, None, validar=False)[0] is False
            alerta = {"id": 7, "tipo": "pr_pronto", "titulo": "Office: PR pronto para o seu merge", "url": "/#alerta=prs",
                      "corpo": "PR #303 aprovado. Rode `git merge x` em C:\\Users\\voce\\repo", "detalhe": "SEGREDO-detalhe-nao-vai"}
            r = p.enviar(alerta, validar=False)
            assert r["enviados"] == 1 and len(srv.recebidos) == 1, r
            req = srv.recebidos[0]
            cab = req["cab"]
            assert cab["ttl"] == "3600" and cab["content-encoding"] == "aes128gcm" and cab["content-type"] == "application/octet-stream"
            assert cab["authorization"].startswith("vapid t=") and ", k=" + p.chave_publica() in cab["authorization"]
            c, cl, sg = cab["authorization"].split("t=")[1].split(",")[0].split(".")
            bruta = b64(sg)
            p._vapid().public_key().verify(encode_dss_signature(int.from_bytes(bruta[:32], "big"), int.from_bytes(bruta[32:], "big")),
                                           f"{c}.{cl}".encode(), ec.ECDSA(hashes.SHA256()))
            assert json.loads(b64(cl))["aud"] == f"http://127.0.0.1:{srv.porta}"
            carga = json.loads(decifrar_referencia(req["corpo"], priv, auth))
            assert carga["c"].startswith("PR #303 aprovado.") and not any(x in carga["c"] for x in ("`", "git merge", "C:", "Users")), carga
            assert {k: v for k, v in carga.items() if k != "c"} == {"t": "Office: PR pronto para o seu merge", "u": "/#alerta=prs", "k": "pr_pronto", "i": 7}, carga
            assert b"SEGREDO" not in req["corpo"] and len(json.dumps(carga)) < 300
            ok("envio ponta a ponta: TTL, aes128gcm, Authorization vapid verificada; o corpo decifrado é só título/corpo/painel, sem comando nem caminho")
            # preferência por tipo: "conferir" está ligado nesta inscrição; tipo desligado no padrão não envia
            assert p.enviar({"id": 8, "tipo": "conferir", "titulo": "t", "corpo": "c"}, validar=False)["enviados"] == 1
            n = len(srv.recebidos)
            assert p.enviar({"id": 9, "tipo": "lembrete", "titulo": "t", "corpo": "c"}, padroes={"lembrete": False}, validar=False)["enviados"] == 0
            assert len(srv.recebidos) == n
            ok("cada tipo liga/desliga por inscrição (e pelo padrão do servidor)")
            # limite por hora: 2 envios feitos -> o 3º passa, o 4º é limitado
            assert p.enviar({"id": 10, "tipo": "pr_pronto", "titulo": "t", "corpo": "c"}, validar=False)["enviados"] == 1
            r = p.enviar({"id": 11, "tipo": "pr_pronto", "titulo": "t", "corpo": "c"}, validar=False)
            assert r["enviados"] == 0 and r["limitados"] == 1
            ok("limite de envios por hora (3 no teste; 20 no padrão): o excedente é limitado e registrado")
            # 410 -> inscrição apagada
            p2 = push.Push(tmp + "/outro", limite_hora=20)
            p2.inscrever("aparelho1", "Celular", sub, None, validar=False)
            srv.codigo = 410
            r = p2.enviar({"id": 1, "tipo": "pr_pronto", "titulo": "t", "corpo": "c"}, validar=False)
            assert r["removidos"] == 1 and p2.quantas() == 0
            srv.codigo = 201
            ok("resposta 410 do serviço apaga a inscrição")
            # aparelho revogado / podar / sair
            sub2 = nova_assinatura(srv, "/push/2")[2]
            p2.inscrever("a1", "A", sub, None, validar=False)
            p2.inscrever("a2", "B", sub2, None, validar=False)
            assert p2.quantas() == 2 and p2.remover_aparelhos(["a1"]) == 1 and p2.quantas() == 1
            assert p2.podar(["zzz"]) == 1 and p2.quantas() == 0
            p2.inscrever("a2", "B", sub2, None, validar=False)
            assert p2.sair("outro", sub2["endpoint"]) is False and p2.sair("a2", sub2["endpoint"]) is True and p2.quantas() == 0
            ok("revogar o aparelho apaga a inscrição; sair só apaga a do próprio aparelho; podar remove órfãs")
            pem = Path(tmp) / "push" / "vapid_privada.pem"
            assert pem.is_file() and b"PRIVATE KEY" in pem.read_bytes()
            assert push.Push(tmp).chave_publica() == p.chave_publica()
            ok("chave VAPID gerada uma vez em dados/push/ e reaproveitada")
    finally:
        srv.parar()


# ---------------------------------------------------------------- detector
def pr(n, **k):
    return dict({"numero": n, "titulo": f"titulo {n}", "rascunho": False, "conflito": False, "guardiao": "", "revisao": ""}, **k)


def testar_detector():
    H = 3600
    t0 = 1_800_000_000
    with tempfile.TemporaryDirectory() as tmp:
        estado = {"prs": {"prs": [pr(10, guardiao="SUCCESS"), pr(11, guardiao="PENDING")], "erro": ""},
                  "placar": {"agentes": {"A": {"auditoria": [{"pr": 5}], "conferir": [{"pr": 6}]}}},
                  "esc": {}, "eventos": [],
                  "sug": {"ativo": True, "itens": [{"id": "1", "pr": 10, "prioridade": "P1", "titulo": "antiga"}, {"id": "2", "pr": 10, "prioridade": "P2", "titulo": "menor"}]}}
        fontes = {"prs": lambda: estado["prs"], "placar": lambda: estado["placar"], "escalonamentos": lambda: estado["esc"],
                  "eventos": lambda desde: (len(estado["eventos"]), estado["eventos"][desde:]),   # como o ler_eventos do servidor
                  "sugestoes": lambda: estado["sug"]}
        a = alertas.Alertas(tmp, fontes, {"limite_push_hora": 20})
        assert a.passo(t0) == [], "a primeira leitura é só baseline"
        assert a.passo(t0 + 60) == []
        ok("primeira leitura só registra o que já existia (sem enxurrada de alertas)")
        d = estado["prs"]
        d["prs"][1] = pr(11, guardiao="SUCCESS")        # PR que fica pronto
        r = a.passo(t0 + 120)
        assert [x["tipo"] for x in r] == ["pr_pronto"] and "#11" in r[0]["corpo"] and r[0]["id"] == 1, r
        assert a.passo(t0 + 180) == [] and a.passo(t0 + 240) == []
        ok("PR que vira pronto gera 1 alerta e não repete nas leituras seguintes")
        d["prs"][1] = pr(11, guardiao="PENDING")        # check piscando: volta a pronto em minutos -> não repete
        a.passo(t0 + 300)
        d["prs"][1] = pr(11, guardiao="SUCCESS")
        assert a.passo(t0 + 360) == []
        ok("check que pisca (pronto, espera, pronto em minutos) não gera alerta repetido")
        d["prs"] += [pr(12, guardiao="SUCCESS"), pr(13, conflito=True), pr(14, guardiao="FAILURE"), pr(15, rascunho=True, guardiao="SUCCESS")]
        r = a.passo(t0 + 420)
        assert sorted(x["tipo"] for x in r) == ["pr_problema", "pr_pronto"], r
        assert "#12" in [x for x in r if x["tipo"] == "pr_pronto"][0]["corpo"] and "#15" not in json.dumps(r)
        pb = [x for x in r if x["tipo"] == "pr_problema"][0]["corpo"]
        assert "#13" in pb and "#14" in pb
        ok("PR novo pronto, com conflito e reprovado: 1 alerta de pronto e 1 de problema (rascunho não conta)")
        estado["prs"] = {"erro": "gh falhou", "prs": []}
        assert a.passo(t0 + 480) == []
        estado["prs"] = d
        assert a.passo(t0 + 540) == []
        ok("falha do gh (lista vazia com erro) não apaga o estado nem gera alerta falso depois")
        # lembrete: PR 10 pronto desde t0 (baseline) -> há mais de 24 h
        assert [x for x in a.passo(t0 + 23 * H) if x["tipo"] == "lembrete"] == []
        r = a.passo(t0 + 25 * H)
        lem = [x for x in r if x["tipo"] == "lembrete"]
        assert len(lem) == 1 and "#10" in lem[0]["corpo"] and "24" in lem[0]["corpo"], r
        assert [x for x in a.passo(t0 + 26 * H) if x["tipo"] == "lembrete"] == []
        assert [x for x in a.passo(t0 + 48 * H) if x["tipo"] == "lembrete"] == []
        assert len([x for x in a.passo(t0 + 50 * H) if x["tipo"] == "lembrete"]) == 1
        ok("lembrete de PR pronto há mais de 24 h: 1 vez por dia, não repete no mesmo dia")
        # placar
        estado["placar"] = {"agentes": {"A": {"auditoria": [{"pr": 5}, {"pr": 21}], "conferir": [{"pr": 6}, {"pr": 22}]}}}
        r = a.passo(t0 + 51 * H)
        assert sorted(x["tipo"] for x in r) == ["auditoria", "conferir"] and "#21" in r[0]["corpo"] + r[1]["corpo"]
        assert a.passo(t0 + 51 * H + 60) == []
        ok("auditoria vermelha nova e item novo para conferir geram 1 alerta cada, sem repetir")
        # eventos: pergunta
        evs = [{"ts": "x", "agente": "Diretor", "tipo": "fala", "texto": "PERGUNTA: escopo do #5 inclui o mapa?"},
               {"ts": "y", "agente": "Dev", "tipo": "fala", "texto": "Tenho uma pergunta ao desenvolvedor sobre X"},
               {"ts": "z", "agente": "Dev", "tipo": "fala", "texto": "fiz o commit"}, {"ts": "w", "agente": "Dev", "tipo": "trabalho", "texto": "PERGUNTA"}]
        estado["eventos"] = evs
        r = a.passo(t0 + 52 * H)
        assert [x["tipo"] for x in r] == ["pergunta", "pergunta"], r
        assert a.passo(t0 + 52 * H + 60) == []
        ok("pergunta de escopo (texto começa com PERGUNTA ou contém 'pergunta ao desenvolvedor'): 1 alerta cada, só evento 'fala'")
        # escalonamento
        estado["esc"] = {"2026-W40": [{"cartao": 86, "motivo": "x", "aberto": "2026-10-01", "fechado": None, "resultado": ""}]}
        r = a.passo(t0 + 53 * H)
        assert [x["titulo"] for x in r] == ["Escalonamento aberto"]
        estado["esc"]["2026-W40"][0].update(fechado="2026-10-02", resultado="resolvido")
        r = a.passo(t0 + 54 * H)
        assert [x["titulo"] for x in r] == ["Escalonamento fechado"] and a.passo(t0 + 54 * H + 60) == []
        ok("escalonamento aberto e depois fechado: 1 alerta de cada")
        # sugestões do bot de revisão: só P0/P1 novas alertam; as que já existiam na 1ª leitura não
        estado["sug"]["itens"] += [{"id": "3", "pr": 11, "prioridade": "P2", "titulo": "pequena"},
                                   {"id": "4", "pr": 11, "prioridade": "P1", "titulo": "grave"}]
        r = a.passo(t0 + 53 * H + 1800)
        assert [x["tipo"] for x in r] == ["sugestao"] and "#11" in r[0]["corpo"] and "P1" in r[0]["titulo"] and "grave" in r[0]["detalhe"], r
        assert a.passo(t0 + 53 * H + 1860) == []
        estado["sug"] = {"ativo": True, "erro": "x", "itens": []}   # tratadas/PR fechado: some sem alerta
        assert a.passo(t0 + 53 * H + 1920) == []
        estado["sug"]["itens"] = [{"id": "4", "pr": 11, "prioridade": "P1", "titulo": "grave"}]   # reaberta: alerta de novo
        assert [x["tipo"] for x in a.passo(t0 + 53 * H + 1980)] == ["sugestao"]
        ok("sugestão P0/P1 nova do bot de revisão: 1 alerta, P2 e as já existentes não alertam, sem repetir")
        # estado persistido: outro Alertas na mesma pasta não repete nada
        b = alertas.Alertas(tmp, fontes)
        assert b.passo(t0 + 55 * H) == [], "o estado em disco evita repetir alertas depois de reiniciar o servidor"
        ok("estado em dados/alertas_estado.json: reiniciar o servidor não repete alertas")
        # fila: ids crescentes e limite de 200
        fila, ultimo = b.listar(0)
        assert [x["id"] for x in fila] == list(range(1, len(fila) + 1)) and ultimo == len(fila)
        for i in range(230):
            b._entrar_na_fila({"tipo": "pr_pronto", "titulo": "t", "corpo": f"c{i}", "chave": "k", "url": "/"}, t0)
        fila, ultimo = b.listar(0)
        assert len(fila) == 200 and fila[-1]["id"] == ultimo and fila[0]["id"] == ultimo - 199
        assert [x["id"] for x in b.listar(ultimo - 3)[0]] == [ultimo - 2, ultimo - 1, ultimo]
        ok("fila dados/alertas.jsonl: ids crescentes, guarda os últimos 200, ?desde= devolve só os novos")
    o = alertas.normalizar_opcoes({"ativo": False, "lembrete_horas": "x", "limite_push_hora": 5, "tipos": {"conferir": True, "pr_pronto": False, "zzz": True},
                                   "contato": "javascript:1"})
    assert o["ativo"] is False and o["lembrete_horas"] == 24 and o["limite_push_hora"] == 5 and o["tipos"]["conferir"] is True \
        and o["tipos"]["pr_pronto"] is False and "zzz" not in o["tipos"] and o["contato"].startswith("mailto:")
    ok("opções do config normalizadas (valor ruim cai no padrão)")


# ---------------------------------------------------------------- vigia da cota do GitHub
def testar_cota():
    agora = time.time()
    reset = int(agora + 1500)

    def rec(gq_restante, core_restante=5000, reset_=reset):
        return {"graphql": {"limit": 5000, "remaining": gq_restante, "used": 5000 - gq_restante, "reset": reset_},
                "core": {"limit": 5000, "remaining": core_restante, "used": 5000 - core_restante, "reset": reset_}}
    bruto = {"resources": {k: {"limit": 5000, "remaining": 1800, "used": 3200, "reset": reset} for k in ("graphql", "core", "search")}}
    n = cota.normalizar(bruto)
    assert n["graphql"]["used"] == 3200 and cota.normalizar({"resources": {}}) is None and cota.normalizar(None) is None
    t = cota.texto(rec(1800))
    assert t == f"GraphQL: 3.200/5.000 (volta {cota.hora(reset)})", t
    assert "REST" not in t and "REST: 4.900/5.000" in cota.texto(rec(1800, 100))
    g = cota.normalizar_gql({"data": {"rateLimit": {"limit": 5000, "remaining": 4788, "used": 212, "resetAt": "2026-10-02T12:19:20Z"}}})
    assert g == {"limit": 5000, "remaining": 4788, "used": 212, "reset": 1790943560} and cota.normalizar_gql({"errors": []}) is None
    assert cota.baixa(rec(900)) and not cota.baixa(rec(1800)) and not cota.baixa(rec(10, reset_=int(agora - 5)))
    ok("cota.py: rodapé 'GraphQL: 3.200/5.000 (volta HH:MM)', REST só quando baixo, 'baixa' < 20% e só na janela atual")
    with tempfile.TemporaryDirectory() as tmp:
        leituras = [rec(4000), rec(3000), rec(2000)]
        v = cota.Vigia(tmp, "gh-falso", leitor=lambda: leituras.pop(0) if leituras else None)
        assert v.ultimo() is None and v.resumo() is None
        for i in range(3):
            assert v.passo(agora - 600 + i * 300)["graphql"]["remaining"] == [4000, 3000, 2000][i]
        assert v.passo(agora) is None, "gh falhou: nada é gravado"
        linhas = (Path(tmp) / "github_cota.jsonl").read_text(encoding="utf-8").splitlines()
        assert len(linhas) == 3 and json.loads(linhas[0])["graphql"]["used"] == 1000
        r = v.resumo()
        assert r["graphql"]["remaining"] == 2000 and not r["baixa"] and r["ritmo_hora"] == 12000, r   # 2000 pontos em 10 min
        v2 = cota.Vigia(tmp, "gh-falso", leitor=lambda: None)
        assert v2.ultimo()["graphql"]["remaining"] == 2000, "servidor reiniciado lê o último do arquivo"
        ok("Vigia: histórico em github_cota.jsonl (1 linha por leitura), ritmo em pontos/hora, sobrevive a reinício")
    with tempfile.TemporaryDirectory() as tmp:
        estado = {"cota": rec(4000)}
        a = alertas.Alertas(tmp, {"cota": lambda: estado["cota"]}, {"limite_push_hora": 20})
        assert a.passo(agora) == []
        estado["cota"] = rec(900)
        r = a.passo(agora + 300)
        assert [x["tipo"] for x in r] == ["cota"] and "GraphQL" in r[0]["titulo"] and "900" in r[0]["corpo"], r
        assert a.passo(agora + 600) == [] and a.passo(agora + 900) == [], "mesma janela: não repete"
        estado["cota"] = rec(0, 100)
        r = a.passo(agora + 1200)
        assert [x["tipo"] for x in r] == ["cota"] and "REST" in r[0]["titulo"], "REST baixo é outro alerta (GraphQL já avisado)"
        estado["cota"] = rec(800, reset_=reset + 3600)
        assert [x["tipo"] for x in a.passo(agora + 4000)] == ["cota"], "nova janela com cota baixa alerta de novo"
        estado["cota"] = None
        assert a.passo(agora + 4300) == []
        assert next(t for t in alertas.TIPOS if t["id"] == "cota")["padrao"] is True
        ok("alerta 'Cota do GitHub baixa': < 20% alerta uma vez por janela e por recurso; fonte ausente não alerta")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    t = time.time()
    testar_rfc8291()
    testar_roundtrip()
    testar_vapid()
    testar_sanear_e_endpoints()
    testar_envio()
    testar_detector()
    testar_cota()
    print(f"OK: {len(feitos)} verificações em {time.time() - t:.1f} s")


if __name__ == "__main__":
    main()
