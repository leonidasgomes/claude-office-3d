@echo off
rem Abre o Claude Office 3D: sobe o servidor local (porta do config.json) e abre o navegador.
rem   abrir_escritorio.bat           -> so neste PC (127.0.0.1)
rem   abrir_escritorio.bat celular   -> liga o acesso pelo celular na rede local (QR code no botao Celular)
chcp 65001 >nul
cd /d "%~dp0"
set EXTRA=
if /i "%~1"=="celular" set EXTRA=--rede-local
echo Iniciando o Office Multi-provider...
rem Python do .venv do escritorio, se existir; senao o do PATH
set PY=python
where python >nul 2>nul || set PY=py -3
if exist ".venv\Scripts\python.exe" set PY=.venv\Scripts\python.exe
%PY% "servidor.py" %EXTRA%
pause
