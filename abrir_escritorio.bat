@echo off
rem Abre o Claude Office 3D: sobe o servidor local (porta do config.json) e abre o navegador.
chcp 65001 >nul
cd /d "%~dp0"
echo Iniciando o Claude Office 3D...
where python >nul 2>nul
if %errorlevel%==0 (python "servidor.py") else (py -3 "servidor.py")
pause
