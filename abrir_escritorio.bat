@echo off
rem Abre o Claude Office 3D: sobe o servidor local (porta do config.json) e abre o navegador.
rem   abrir_escritorio.bat           -> so neste PC (127.0.0.1)
rem   abrir_escritorio.bat celular   -> liga o acesso pelo celular na rede local (QR code no botao Celular)
chcp 65001 >nul
cd /d "%~dp0"
set EXTRA=
if /i "%~1"=="celular" set EXTRA=--rede-local
echo Iniciando o Claude Office 3D...
where python >nul 2>nul
if %errorlevel%==0 (python "servidor.py" %EXTRA%) else (py -3 "servidor.py" %EXTRA%)
pause
