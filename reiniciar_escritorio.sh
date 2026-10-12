#!/usr/bin/env sh
# Reinicia somente o servidor desta instalação; preserva as opções recebidas.
cd "$(dirname "$0")" || exit 1
if [ -x .venv/bin/python ]; then
    PY=.venv/bin/python
elif command -v python3 >/dev/null 2>&1; then
    PY=python3
elif command -v python >/dev/null 2>&1; then
    PY=python
else
    echo "Python 3.9+ não encontrado. Instale Python e execute novamente." >&2
    exit 1
fi
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' || {
    echo "É necessário Python 3.9+; confira o Python do PATH ou .venv." >&2
    exit 1
}
if [ "${1:-}" = "celular" ]; then shift; set -- --rede-local "$@"; fi
exec "$PY" reiniciar_posix.py "$@"
