@echo off
chcp 65001 >nul
powershell.exe -NoProfile -File "%~dp0preparar_maquina.ps1" -Interativo %*
if errorlevel 1 echo Preparacao interrompida. Confira o relato antes de repetir.
pause
