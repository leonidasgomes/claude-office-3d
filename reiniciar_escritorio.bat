@echo off
rem Reinicia o Claude Office 3D: encerra o servidor da porta configurada (se estiver rodando) e sobe de novo, minimizado.
chcp 65001 >nul
cd /d "%~dp0"
set PY=python
where python >nul 2>nul || set PY=py -3
for /f "usebackq delims=" %%p in (`%PY% configuracao.py --porta`) do set PORTA=%%p
if "%PORTA%"=="" set PORTA=8765
echo Encerrando o servidor antigo do escritorio (porta %PORTA%)...
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort %PORTA% -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue; Write-Host ('  processo ' + $_ + ' encerrado') }"
powershell -NoProfile -Command "Start-Sleep -Seconds 1"
echo Subindo o escritorio de novo...
start "Claude Office 3D" /min /D "%~dp0" cmd /c %PY% servidor.py --sem-navegador
echo Pronto: http://127.0.0.1:%PORTA%/  (a pagina aberta reconecta sozinha)
