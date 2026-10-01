#!/usr/bin/env sh
# Assistente de instalação do Claude Office 3D (macOS/Linux). Repassa as opções: ./instalar.sh --desinstalar
cd "$(dirname "$0")" || exit 1
if command -v python3 >/dev/null 2>&1; then PY=python3; else PY=python; fi
exec "$PY" instalar.py "$@"
