"""Gera o pacote distribuível: dist/office-multi-provider-v<VERSION>.zip (+ .sha256).

Uso: python ferramentas/build.py
Leva a lista explícita instalar.PACOTE, inclusive módulos novos ainda não rastreados.
Dados, credenciais, config pessoal, backups e vendor baixado nunca entram.
Confere a lista com os arquivos versionados e roda a verificação antes de gerar.
"""
import hashlib
import os
import subprocess
import sys
import zipfile
import uuid
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0,str(RAIZ))
FORA_DO_ZIP = (".github/", "ferramentas/")


def arquivos_pacote(raiz=RAIZ, manifesto=None, versionados=None):
    if manifesto is None:
        from instalar import PACOTE
        manifesto=PACOTE
    proibidos={'dados','.git','.venv','.office','node_modules','dist','vendor'}
    vistos=set(); arquivos=[]
    for nome in manifesto:
        p=Path(nome)
        if (p.is_absolute() or p.drive or '..' in p.parts or set(p.parts)&proibidos
            or p.name=='config.json' or p.name.startswith('.env') or '.bak' in p.name
            or p.suffix.lower() in ('.db','.sqlite','.jsonl','.pem','.key')):
            raise ValueError('Arquivo privado ou caminho inválido no manifesto: '+nome)
        if nome.casefold() in vistos: raise ValueError('Arquivo duplicado no manifesto: '+nome)
        vistos.add(nome.casefold())
        alvo=(raiz/p).resolve()
        if not alvo.is_relative_to(raiz.resolve()) or not alvo.is_file():
            raise ValueError('Arquivo ausente ou fora do pacote: '+nome)
        arquivos.append(nome)
    if versionados is None:
        r=subprocess.run(['git','ls-files','-z'],cwd=raiz,capture_output=True,text=True,check=True)
        versionados=r.stdout.split('\0')
    fora=[f for f in versionados if f and f not in arquivos and f!='.gitattributes' and not f.startswith(FORA_DO_ZIP)]
    if fora: raise ValueError('Arquivos versionados sem classificação no manifesto: '+', '.join(fora))
    return sorted(arquivos)


def gerar(raiz, arquivos, destino, nome):
    destino=Path(destino); destino.mkdir(parents=True,exist_ok=True)
    tmp=destino/(uuid.uuid4().hex+'.tmp')
    zip_path=destino/(nome+'.zip')
    try:
        with zipfile.ZipFile(tmp,'w',zipfile.ZIP_DEFLATED) as z:
            for f in arquivos: z.write(raiz/f,nome+'/'+f)
        with zipfile.ZipFile(tmp) as z:
            if z.testzip() is not None: raise ValueError('Falha na integridade do ZIP')
        soma=hashlib.sha256(tmp.read_bytes()).hexdigest()
        os.replace(tmp,zip_path)
        (destino/(nome+'.zip.sha256')).write_text(f'{soma}  {zip_path.name}\n',encoding='utf-8')
        return zip_path,soma
    finally: tmp.unlink(missing_ok=True)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    versao = (RAIZ / "VERSION").read_text(encoding="utf-8").strip()
    import re
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+(?:-[a-zA-Z0-9.-]+)?',versao):
        sys.exit('Versão inválida para o nome do pacote')
    try: arquivos=arquivos_pacote()
    except (ValueError,subprocess.SubprocessError) as exc: sys.exit(str(exc))
    if subprocess.run([sys.executable, str(RAIZ / "ferramentas" / "verificar.py")], cwd=RAIZ).returncode:
        sys.exit("build cancelado: a verificação falhou")
    dist = RAIZ / "dist"
    nome = f"office-multi-provider-v{versao}"
    zip_path,soma=gerar(RAIZ,arquivos,dist,nome)
    print(f"pronto: {zip_path.relative_to(RAIZ)} ({len(arquivos)} arquivos, {zip_path.stat().st_size // 1024} KB)")
    print(f"sha256: {soma}")


if __name__ == "__main__":
    main()
