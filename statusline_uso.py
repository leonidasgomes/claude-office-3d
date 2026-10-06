# -*- coding: utf-8 -*-
"""Statusline do Claude Code: mostra o uso do plano e grava no banco do escritório (uso diário e semanal no Placar).

O Claude Code passa à statusline, pelo stdin, um JSON com `rate_limits` (só planos de assinatura, depois da primeira
resposta da API):
  rate_limits.five_hour.used_percentage / resets_at   (janela de 5 h; resets_at em segundos desde 1970)
  rate_limits.seven_day.used_percentage / resets_at   (semana)
Esquema visto no Claude Code 2.1.292; a documentação pública ainda não lista o campo. Sem `rate_limits` (API key,
Bedrock/Vertex, antes da primeira resposta) só mostra o modelo e não grava nada.

Ligada em ~/.claude/settings.json pelo instalar.py (passo opcional) ou à mão:
  "statusLine": {"type": "command", "command": "python \"<pasta do escritório>/statusline_uso.py\""}
Se você já tem uma statusline, encadeie com --so-gravar (grava e não imprime nada), passando o mesmo stdin:
  entrada=$(cat); printf '%s' "$entrada" | python ".../statusline_uso.py" --so-gravar; printf '%s' "$entrada" | seu_comando
Nunca falha: qualquer erro vira uma linha curta (a statusline não pode quebrar a sessão).
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _hora(epoch):
    if not epoch:
        return ""
    t = time.localtime(epoch)
    hoje = time.localtime()
    if t.tm_yday == hoje.tm_yday and t.tm_year == hoje.tm_year:
        return time.strftime("%H:%M", t)
    return ("seg", "ter", "qua", "qui", "sex", "sáb", "dom")[t.tm_wday] + time.strftime(" %H:%M", t)


def main():
    so_gravar = "--so-gravar" in sys.argv[1:]
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        d = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace") or "{}")
        if not isinstance(d, dict):
            raise ValueError("não é um objeto")
    except Exception:
        if not so_gravar:
            print("statusline: entrada inválida")
        return 0
    modelo = ((d.get("model") or {}).get("display_name")) or ""
    rl = d.get("rate_limits") or {}
    five, seven = rl.get("five_hour") or {}, rl.get("seven_day") or {}
    partes = [modelo] if modelo else []
    try:
        if five.get("used_percentage") is not None:
            partes.append(f"5h {float(five['used_percentage']):.0f}% ↻{_hora(five.get('resets_at'))}")
        if seven.get("used_percentage") is not None:
            partes.append(f"semana {float(seven['used_percentage']):.0f}% ↻{_hora(seven.get('resets_at'))}")
    except (TypeError, ValueError, OverflowError, OSError):
        pass   # formato inesperado: mostra só o que deu
    if five or seven:
        try:
            import banco
            banco.gravar_uso(five.get("used_percentage"), five.get("resets_at"),
                             seven.get("used_percentage"), seven.get("resets_at"))
        except Exception:
            pass   # banco ocupado: a próxima atualização grava
    if not so_gravar:
        print(" · ".join(partes) or "Claude Code")
    return 0


if __name__ == "__main__":
    sys.exit(main())
