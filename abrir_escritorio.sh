#!/usr/bin/env sh
# Abre o Claude Office 3D: sobe o servidor local (porta do config.json) e abre o navegador.
cd "$(dirname "$0")" || exit 1
echo "Iniciando o Claude Office 3D..."
exec python3 servidor.py "$@"
