"""Gera o pacote distribuível: dist/claude-office-3d-v<VERSION>.zip (+ .sha256).

Uso: python ferramentas/build.py
Leva só os arquivos versionados pelo git (git ls-files), então eventos, config.json pessoal, backups e
vendor/ baixado nunca entram. Roda antes a verificação (sintaxe + vazamento).
"""
import hashlib
import subprocess
import sys
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
FORA_DO_ZIP = (".github/", "ferramentas/")  # coisa de desenvolvimento do pacote


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    versao = (RAIZ / "VERSION").read_text(encoding="utf-8").strip()
    if subprocess.run([sys.executable, str(RAIZ / "ferramentas" / "verificar.py")], cwd=RAIZ).returncode:
        sys.exit("build cancelado: a verificação falhou")
    lista = subprocess.run(["git", "ls-files"], cwd=RAIZ, capture_output=True, text=True, check=True).stdout.split("\n")
    arquivos = [f for f in lista if f and not f.startswith(FORA_DO_ZIP)]
    dist = RAIZ / "dist"
    dist.mkdir(exist_ok=True)
    nome = f"claude-office-3d-v{versao}"
    zip_path = dist / f"{nome}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for f in arquivos:
            z.write(RAIZ / f, f"{nome}/{f}")
    soma = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    (dist / f"{nome}.zip.sha256").write_text(f"{soma}  {zip_path.name}\n", encoding="utf-8")
    print(f"pronto: {zip_path.relative_to(RAIZ)} ({len(arquivos)} arquivos, {zip_path.stat().st_size // 1024} KB)")
    print(f"sha256: {soma}")


if __name__ == "__main__":
    main()
