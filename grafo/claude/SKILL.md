---
name: grafo
description: Grafo de arquitetura do projeto — use antes de procurar código com grep, ao criar arquivo, ao mudar interface entre sistemas e antes de concluir (dono, recorte, impacto e validação baratos).
---

# Grafo de arquitetura (consulta barata)

Rode da raiz do projeto (`python <caminho>/grafo.py <comando>`; com `--copiar`, `python .claude/grafo/grafo.py`).

| Pergunta | Comando |
|---|---|
| Onde está X? (classe, função, arquivo, assunto) | `grafo.py find "X"` — lista os ARQUIVOS que casaram, por relevância |
| De quem é este arquivo? | `grafo.py owner <arquivo>` |
| Arquivo novo: em que sistema registro? | `grafo.py suggest <arquivo>` |
| Contexto de um sistema antes de editar | `grafo.py slice <sistema> [--budget 400]` |
| O que minha mudança afeta e que testes rodo? | `grafo.py impact <arquivos...>` ou `grafo.py impact --diff origin/main` |
| Terminei: quebrei a arquitetura? | `grafo.py validate --base origin/main` |

Regras:
- Prefira `find`/`slice` a ler o YAML do grafo inteiro (o recorte cabe no orçamento; o YAML não).
- Import/include de outro sistema precisa estar em `depends_on` (ou num evento `call`) e respeitar as camadas;
  o `validate` acusa a aresta real não declarada, o ciclo real e a camada violada no código.
- Todo arquivo de código novo precisa de um dono (`paths:` de um sistema); `suggest` diz qual.
- Não edite à mão arquivos gerados (`.grafo/`, `.claude/rules/arq-*.md`): edite o grafo e rode `index`/`sync-rules`.
