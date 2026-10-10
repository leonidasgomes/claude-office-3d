"""Verificação do pacote (roda no CI e localmente): sintaxe e varredura de vazamento.

Uso: python ferramentas/verificar.py [--termos arquivo.txt]
  --termos: lista extra de termos proibidos (um por linha), guardada FORA deste repositório — por exemplo,
            nomes, empresa ou projeto do mantenedor. Assim os termos pessoais nunca entram no repositório público.
            Linha com "!" na frente é exceção exata permitida (ex.: "!usuario-publico-do-github").
Sai com código 1 se encontrar problema.
"""
import ast
import re
import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
IGNORAR = {".git", ".venv", "dist", "vendor", "dados", "__pycache__", "node_modules"}
TEXTO = {".py", ".js", ".mjs", ".css", ".html", ".md", ".json", ".bat", ".ps1", ".sh", ".txt", ".yml", ".yaml", ""}

# Padrões genéricos de vazamento (sem nada pessoal aqui dentro)
PADROES = {
    "e-mail": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+\.[A-Za-z]{2,}"),
    "caminho de usuário Windows": re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+(?!<|\{|%|USUARIO|SeuUsuario|voce)[A-Za-z0-9._-]+", re.I),
    "caminho de usuário Unix": re.compile(r"/(?:home|Users)/(?!<|\$|usuario|voce|you)[a-z0-9._-]+/", re.I),
    "token do GitHub": re.compile(r"\b(?:gh[opsru]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"),
    "chave de API": re.compile(r"\b(?:sk-ant-[A-Za-z0-9_-]{10,}|sk-[A-Za-z0-9]{32,}|AKIA[0-9A-Z]{16})"),
    "ID do GitHub Projects": re.compile(r"\bPV(?:T|TI|TSSF|TF)_[A-Za-z0-9_]{8,}"),
    "chave privada": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
}
# e-mails permitidos (exemplos e o noreply do GitHub)
EMAIL_OK = re.compile(r"(@example\.(com|org)|@users\.noreply\.github\.com|noreply@anthropic\.com)$", re.I)


def arquivos():
    for p in sorted(RAIZ.rglob("*")):
        if p.is_file() and not (set(p.relative_to(RAIZ).parts) & IGNORAR) and p.suffix.lower() in TEXTO:
            yield p


def verificar_sintaxe(erros):
    for p in arquivos():
        if p.suffix == ".py":
            try:
                ast.parse(p.read_text(encoding="utf-8"), str(p))
            except SyntaxError as e:
                erros.append(f"sintaxe Python: {p.relative_to(RAIZ)}:{e.lineno}: {e.msg}")
        elif p.suffix in (".js", ".mjs") and shutil.which("node"):
            r = subprocess.run(["node", "--check", str(p)], capture_output=True, text=True)
            if r.returncode:
                erros.append(f"sintaxe JS: {p.relative_to(RAIZ)}: {r.stderr.strip().splitlines()[-1] if r.stderr else 'erro'}")


def verificar_vazamento(erros, termos, permitidos=()):
    eu = Path(__file__).resolve()
    for p in arquivos():
        if p.resolve() == eu:
            continue
        texto = p.read_text(encoding="utf-8", errors="replace")
        for n, linha in enumerate(texto.splitlines(), 1):
            for nome, rx in PADROES.items():
                for m in rx.finditer(linha):
                    if nome == "e-mail" and EMAIL_OK.search(m.group(0)):
                        continue
                    erros.append(f"vazamento ({nome}): {p.relative_to(RAIZ)}:{n}: {m.group(0)[:60]}")
            baixa = linha.lower()
            for ok in permitidos:  # ex.: o usuário público do GitHub, que já está na URL do repositório
                baixa = baixa.replace(ok, "")
            for t in termos:
                if t in baixa:
                    erros.append(f"vazamento (termo privado): {p.relative_to(RAIZ)}:{n}")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    termos, permitidos = [], []
    if "--termos" in sys.argv:
        arq = Path(sys.argv[sys.argv.index("--termos") + 1])
        linhas = [t.strip().lower() for t in arq.read_text(encoding="utf-8").splitlines()
                  if t.strip() and not t.startswith("#")]
        termos = [t for t in linhas if not t.startswith("!")]
        permitidos = [t[1:] for t in linhas if t.startswith("!")]
    erros = []
    verificar_sintaxe(erros)
    verificar_vazamento(erros, termos, permitidos)
    for e in erros:
        print("✗", e)
    print(f"{'OK' if not erros else 'FALHOU'}: {len(list(arquivos()))} arquivos, {len(erros)} problema(s)"
          + (f", {len(termos)} termos privados" if termos else ""))
    sys.exit(1 if erros else 0)


if __name__ == "__main__":
    main()
