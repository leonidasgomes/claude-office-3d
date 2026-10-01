---
name: {{nome}}
description: Descreva em 3ª pessoa o que a skill faz e QUANDO usar (ex.: "Roda a validação de X. Use quando o cartão pedir Y ou o PR alterar Z.").
autor: {{autor}}
criado: {{criado}}
estado: candidato
usos:
evidencia: Cartão/PR de onde saiu o padrão (ex.: PR #230, cartão #212) e por que se repete.
---
# {{nome}}

## Passos
1. Primeiro passo, concreto e curto.
2. Segundo passo.
3. Terceiro passo.

## Verificação
Comando que prova que deu certo (código de saída), por exemplo `python scripts/x.py --check`.

<!--
Regras do modelo (apague este bloco):
- name: minúsculas, números e hífen, até 64 caracteres.
- description: 3ª pessoa, diz O QUE faz e QUANDO usar, até 1024 caracteres, uma linha.
- Corpo: curto (o limite oficial é 500 linhas, mire em 30). Sem dados secretos.
- usos: não edite à mão; use `python skills.py usar <nome> --agente X --cartao N --resultado ok|falhou`.
- Estados: candidato -> quarentena (houve falha) -> pronto-ab (2 usos ok em cartões diferentes)
  -> aprovado (promovido por você com `python skills.py promover`) | rejeitado | aposentado (sem uso há 30 dias).
-->
