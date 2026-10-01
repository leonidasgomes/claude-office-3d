"""Imprime a seção da versão no CHANGELOG.md e confere se a tag bate com o VERSION.

Uso: python ferramentas/notas_versao.py v1.0.0
"""
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    tag = sys.argv[1] if len(sys.argv) > 1 else ""
    versao = (RAIZ / "VERSION").read_text(encoding="utf-8").strip()
    if tag and tag.lstrip("v") != versao:
        sys.exit(f"tag {tag} diferente do VERSION ({versao})")
    texto = (RAIZ / "CHANGELOG.md").read_text(encoding="utf-8")
    m = re.search(r"^## " + re.escape(versao) + r"\s*$(.*?)(?=^## |\Z)", texto, re.S | re.M)
    print(m.group(1).strip() if m else f"Versão {versao}")


if __name__ == "__main__":
    main()
