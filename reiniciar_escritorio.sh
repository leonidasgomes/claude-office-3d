#!/usr/bin/env sh
# Reinicia o Claude Office 3D: encerra o servidor da porta configurada (se estiver rodando) e sobe de novo em segundo plano.
#   ./reiniciar_escritorio.sh celular   -> sobe com o acesso pelo celular na rede local (--rede-local)
cd "$(dirname "$0")" || exit 1
EXTRA=""
[ "$1" = "celular" ] && EXTRA="--rede-local"
PORTA=$(python3 configuracao.py --porta 2>/dev/null || echo 8765)
echo "Encerrando o servidor antigo do escritório (porta $PORTA)..."
PIDS=$(lsof -ti tcp:"$PORTA" -sTCP:LISTEN 2>/dev/null)
if [ -n "$PIDS" ]; then kill $PIDS 2>/dev/null; echo "  processo(s) $PIDS encerrado(s)"; sleep 1; fi
echo "Subindo o escritório de novo..."
nohup python3 servidor.py --sem-navegador $EXTRA >/dev/null 2>&1 &
echo "Pronto: http://127.0.0.1:$PORTA/"
