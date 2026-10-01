@echo off
rem Assistente de instalacao do Claude Office 3D (Windows). Repassa as opcoes: instalar.bat --desinstalar
chcp 65001 >nul
cd /d "%~dp0"
where python >nul 2>nul
if %errorlevel%==0 (python instalar.py %*) else (py -3 instalar.py %*)
pause
