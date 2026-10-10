"""Atalho Windows no Desktop real (inclusive redirecionado para OneDrive)."""
import json
import os
import subprocess
from pathlib import Path


SCRIPT = r'''
$ErrorActionPreference = 'Stop'
$dados = $env:ESCRITORIO_ATALHO_JSON | ConvertFrom-Json
$desktop = [Environment]::GetFolderPath('DesktopDirectory')
if (!$desktop -or !(Test-Path -LiteralPath $desktop)) { throw 'Area de trabalho indisponivel.' }
$caminho = Join-Path $desktop ($dados.nome + '.lnk')
$shell = New-Object -ComObject WScript.Shell
$atalho = $shell.CreateShortcut($caminho)
if ((Test-Path -LiteralPath $caminho) -and $atalho.TargetPath -ne $dados.alvo) {
    throw 'Ja existe um atalho com esse nome para outro programa; ele foi preservado.'
}
$atalho.TargetPath = $dados.alvo
$atalho.WorkingDirectory = $dados.pasta
$atalho.IconLocation = $dados.icone + ',0'
$atalho.Description = $dados.descricao
$atalho.Save()
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding
Write-Output $caminho
'''


def criar(destino, nome='Office Multi-provider', iniciador='abrir_escritorio.bat',
          descricao='Abrir o escritorio de agentes'):
    """Retorna o .lnk criado; fora do Windows não altera o Desktop."""
    if os.name != 'nt':
        return None
    pasta = Path(destino).resolve()
    alvo = (pasta / iniciador).resolve()
    icone = pasta / 'icone-office.ico'
    if not alvo.is_relative_to(pasta) or not alvo.is_file() or not icone.is_file():
        raise ValueError('Iniciador ou icone ausente na instalacao')
    if not nome or any(c in nome for c in '\\/:*?"<>|'):
        raise ValueError('Nome de atalho invalido')
    ambiente = dict(os.environ)
    ambiente['ESCRITORIO_ATALHO_JSON'] = json.dumps(dict(
        nome=nome, alvo=str(alvo), pasta=str(pasta), icone=str(icone), descricao=descricao))
    resultado = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', SCRIPT],
                               env=ambiente, capture_output=True, encoding='utf-8', errors='replace',
                               timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
    if resultado.returncode:
        raise OSError(resultado.stderr.strip() or 'Nao foi possivel criar o atalho')
    return Path(resultado.stdout.strip())
