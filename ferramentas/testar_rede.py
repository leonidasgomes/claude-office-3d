"""Teste do filtro de origem do acesso pelo celular (rede.ip_permitido). Roda sem rede e sem dependências.

Uso: python ferramentas/testar_rede.py
Confere: IP privado entra; 100.64.0.0/10 (Tailscale/CGNAT) só entra com "rede_tailscale" ligado; IP público, loopback
alheio, link-local, multicast e reservado nunca entram; o Rede guarda o flag recebido do servidor.
"""
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
import rede  # noqa: E402

feitos = []


def ok(nome):
    feitos.append(nome)
    print("  ok:", nome)


def testar_ip_permitido():
    for ip in ("192.168.0.10", "10.1.2.3", "172.16.5.4", "fd00::1", "::ffff:192.168.1.7"):
        assert rede.ip_permitido(ip), ip
        assert rede.ip_permitido(ip, tailscale=True), ip
    ok("IP privado entra (com e sem tailscale)")
    for ip in ("100.64.0.1", "100.100.100.100", "100.127.255.254"):
        assert not rede.ip_permitido(ip), ip
        assert not rede.ip_permitido(ip, tailscale=False), ip
    ok("100.64/10 recusado com rede_tailscale desligado")
    for ip in ("100.64.0.1", "100.100.100.100", "100.127.255.254"):
        assert rede.ip_permitido(ip, tailscale=True), ip
    assert not rede.ip_permitido("100.128.0.1", tailscale=True)   # fora da /10
    ok("100.64/10 aceito com rede_tailscale ligado")
    for ip in ("8.8.8.8", "1.1.1.1", "2001:4860:4860::8888", "100.63.255.255"):
        assert not rede.ip_permitido(ip), ip
        assert not rede.ip_permitido(ip, tailscale=True), ip
    ok("IP público recusado")
    for ip in ("127.0.0.2", "169.254.1.1", "fe80::1", "224.0.0.1", "240.0.0.1", "0.0.0.0", "lixo", ""):
        assert not rede.ip_permitido(ip, tailscale=True), ip
    ok("loopback alheio, link-local, multicast, reservado e inválido recusados")


def testar_rede_guarda_flag():
    with tempfile.TemporaryDirectory() as tmp:
        assert rede.Rede(tmp, True).tailscale is False
        assert rede.Rede(tmp, True, tailscale=True).tailscale is True
    ok("Rede guarda o flag rede_tailscale (também sem HTTPS)")


def main():
    print("testar_rede:")
    testar_ip_permitido()
    testar_rede_guarda_flag()
    print(f"OK: {len(feitos)} verificações")


if __name__ == "__main__":
    main()
