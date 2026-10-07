"""Confere se o docs/SDD.md acompanha o código (somente biblioteca padrão). Usado no CI e localmente.

Uso: python ferramentas/verificar_docs.py
Falha (código 1) listando o que falta no SDD:
  * toda rota HTTP de servidor.py e rede.py (comparações `rota ==`/`url.path ==`/`in (...)` e as constantes
    ROTAS_PUBLICAS, PERMISSAO_ROTA, ACOES_XP) — tem de aparecer na seção 5.1;
  * toda tabela de banco.ESQUEMA (`CREATE TABLE IF NOT EXISTS <nome>`) — seção 4.1;
  * todo script .py da raiz com `if __name__ == "__main__"` (e os de SCRIPTS_EXTRAS) — numa linha da tabela da seção 5.3;
    e cada flag `--xxx` que ele lê (argparse ou sys.argv) — na(s) linha(s) desse script na seção 5.3;
  * toda chave de primeiro nível de configuracao.PADRAO — seção 5.4;
  * toda variável de ambiente OFFICE_* lida ou passada pelos scripts — em qualquer lugar do SDD.
Exclusões intencionais ficam em IGNORAR (com o motivo).
"""
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SDD = RAIZ / "docs" / "SDD.md"
SCRIPTS_EXTRAS = ["modelos/briefing_diretor.py", "grafo/grafo.py", "grafo/claude/instalar_grafo.py",
                  "grafo/claude/hooks/grafo_hook.py"]   # CLIs fora da raiz que o SDD também descreve
# exclusões intencionais: "tipo:valor" -> motivo
IGNORAR = {
    "script:registrar_evento.py": "hook do Claude Code (JSON no stdin, sem flags); descrito na seção 5.2",
}

RX_LITERAL_ROTA = re.compile(r'"(/[A-Za-z0-9_.\-/]*)"')
RX_CONTEXTO_ROTA = re.compile(r'\b(?:rota|url\.path|caminho|p)\s*(?:==|!=|(?:not\s+)?in)\s*(.+)')
RX_CONSTANTE_ROTA = re.compile(r'^(ROTAS_PUBLICAS|PERMISSAO_ROTA|ACOES_XP)\s*=\s*(.+?)(?=^\S)', re.M | re.S)
RX_TABELA = re.compile(r'CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+(\w+)', re.I)
RX_FLAG = [
    re.compile(r'add_argument\(\s*"(--[\w-]+)"'),
    re.compile(r'"(--[\w-]+)"\s+(?:not\s+)?in\s+(?:sys\.argv|argv|args|a)\b'),
    re.compile(r'\.index\(\s*"(--[\w-]+)"\s*\)'),
    re.compile(r'_arg\(\s*\w+\s*,\s*"(--[\w-]+)"'),
]
RX_TUPLA_FLAGS = re.compile(r'\(\s*("--[\w-]+"(?:\s*,\s*"--[\w-]+")+)\s*\)')
RX_AMBIENTE = re.compile(r'\b(OFFICE_[A-Z_]+)\b')


def ler(caminho):
    return Path(caminho).read_text(encoding="utf-8")


def secao(texto, numero):
    """Texto da seção '### <numero> ...' até o próximo título ## ou ###; '' se não existir."""
    m = re.search(r'^###\s+' + re.escape(numero) + r'\b.*?$(.*?)(?=^##)', texto + "\n## fim", re.M | re.S)
    return m.group(1) if m else ""


def citado(token, texto):
    """True se o token aparece sozinho (não como pedaço de outro caminho, nome ou flag)."""
    return re.search(r'(?<![\w/.\-])' + re.escape(token) + r'(?![\w/\-]|\.\w)', texto) is not None


# ---------------------------------------------------------------- extração do código
def rotas():
    achadas = set()
    for nome in ("servidor.py", "rede.py"):
        fonte = ler(RAIZ / nome)
        for linha in fonte.splitlines():
            if linha.lstrip().startswith("#") or "startswith" in linha:
                continue
            m = RX_CONTEXTO_ROTA.search(linha)
            if m:
                achadas.update(RX_LITERAL_ROTA.findall(m.group(1)))
        for _, corpo in RX_CONSTANTE_ROTA.findall(fonte):
            achadas.update(RX_LITERAL_ROTA.findall(corpo))
    # prefixos ("/api/", "/rede/") e caminhos de arquivo bloqueados não são rotas
    return sorted(r for r in achadas if r == "/" or not r.endswith("/"))


def tabelas():
    return sorted(set(RX_TABELA.findall(ler(RAIZ / "banco.py"))))


def scripts():
    """{script: [flags]} dos scripts com CLI."""
    lista = sorted(p.name for p in RAIZ.glob("*.py")) + SCRIPTS_EXTRAS
    saida = {}
    for rel in lista:
        fonte = ler(RAIZ / rel)
        if '__name__ == "__main__"' not in fonte and "__name__ == '__main__'" not in fonte:
            continue
        flags = set()
        for rx in RX_FLAG:
            flags.update(rx.findall(fonte))
        for linha in fonte.splitlines():
            if "argv" in linha:
                for grupo in RX_TUPLA_FLAGS.findall(linha):
                    flags.update(re.findall(r'"(--[\w-]+)"', grupo))
        saida[rel] = sorted(flags)
    return saida


def chaves_config():
    sys.path.insert(0, str(RAIZ))
    import configuracao   # só biblioteca padrão; não lê nada na importação
    return sorted(configuracao.PADRAO)


def variaveis_ambiente():
    achadas = set()
    for p in sorted(RAIZ.glob("*.py")):
        achadas.update(RX_AMBIENTE.findall(ler(p)))
    return sorted(achadas)


# ---------------------------------------------------------------- conferência
def linhas_do_script(tabela, script):
    """Linhas da tabela da seção 5.3 cuja primeira coluna cita o script."""
    nome = Path(script).name
    out = []
    for linha in tabela.splitlines():
        if linha.startswith("|"):
            primeira = linha.split("|")[1] if linha.count("|") >= 2 else ""
            if citado(nome, primeira) or citado(script, primeira):
                out.append(linha)
    return "\n".join(out)


def faltas():
    if not SDD.is_file():
        return [f"{SDD.relative_to(RAIZ)} não existe"]
    texto = ler(SDD)
    s41, s51, s53, s54 = secao(texto, "4.1"), secao(texto, "5.1"), secao(texto, "5.3"), secao(texto, "5.4")
    erros = [f"seção {n} não encontrada no SDD" for n, s in (("4.1", s41), ("5.1", s51), ("5.3", s53), ("5.4", s54)) if not s]
    if erros:
        return erros
    for r in rotas():
        if f"rota:{r}" not in IGNORAR and not citado(r, s51):
            erros.append(f"rota HTTP {r} (servidor.py/rede.py) não está na seção 5.1")
    for t in tabelas():
        if f"tabela:{t}" not in IGNORAR and not citado(f"`{t}`", s41) and not citado(t, s41):
            erros.append(f"tabela {t} (banco.ESQUEMA) não está na seção 4.1")
    for script, flags in scripts().items():
        if f"script:{Path(script).name}" in IGNORAR:
            continue
        linhas = linhas_do_script(s53, script)
        if not linhas:
            erros.append(f"script {script} (tem CLI) não tem linha na tabela da seção 5.3")
            continue
        for f in flags:
            if f"flag:{Path(script).name}:{f}" not in IGNORAR and not citado(f, linhas):
                erros.append(f"flag {f} de {script} não está na linha dele na seção 5.3")
    for k in chaves_config():
        if f"config:{k}" not in IGNORAR and not citado(k, s54):
            erros.append(f"chave {k} de configuracao.PADRAO não está na seção 5.4")
    for v in variaveis_ambiente():
        if f"ambiente:{v}" not in IGNORAR and not citado(v, texto):
            erros.append(f"variável de ambiente {v} não está no SDD")
    return erros


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    erros = faltas()
    if erros:
        print(f"docs/SDD.md desatualizado ({len(erros)} item(ns)):")
        for e in erros:
            print("  -", e)
        print("Regra: rota, tabela, script, flag ou chave de config nova entra no SDD na mesma mudança (seção 13).")
        sys.exit(1)
    n = (len(rotas()), len(tabelas()), len(scripts()), sum(len(f) for f in scripts().values()), len(chaves_config()))
    print(f"OK: SDD cobre {n[0]} rotas, {n[1]} tabelas, {n[2]} scripts com {n[3]} flags e {n[4]} chaves de config")


if __name__ == "__main__":
    main()
