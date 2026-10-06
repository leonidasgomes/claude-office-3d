Copie para glossario_triagem.md (fica fora do git) e escreva o que um bot de revisão costuma confundir no SEU projeto.
A triagem das sugestões (sugestoes_bot.py) lê este arquivo e as últimas 20 sugestões que o líder ignorou com motivo.
Uma linha por regra, curta. Exemplos:
- "reprocessar" é o termo do projeto para rodar o pipeline de novo; não é erro de ortografia.
- A base dos PRs é `develop`, não `main`.
- Caminho de dados sempre pela variável de ambiente DADOS_DIR, nunca fixo: sugestão que pede isso é real.
- Comentários e textos de interface em português do Brasil são o padrão.
