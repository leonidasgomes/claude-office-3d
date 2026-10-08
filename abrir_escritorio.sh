#!/usr/bin/env sh
# Abre o Claude Office 3D: sobe o servidor local (porta do config.json) e abre o navegador.
#   ./abrir_escritorio.sh           -> só neste PC (127.0.0.1)
#   ./abrir_escritorio.sh celular   -> liga o acesso pelo celular na rede local (QR code no botão Celular)
cd "$(dirname "$0")" || exit 1
echo "Iniciando o Claude Office 3D..."
if [ "$1" = "celular" ]; then shift; set -- --rede-local "$@"; fi
PY=python3
[ -x .venv/bin/python ] && PY=.venv/bin/python   # Python do .venv do escritório, se existir
exec "$PY" servidor.py "$@"
