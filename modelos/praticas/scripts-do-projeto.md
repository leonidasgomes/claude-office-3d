# Scripts do projeto: comando repetido vira script

- Comando que você monta de novo e de novo (o mesmo `cd`, as mesmas variáveis, o mesmo caminho longo do Python ou da
  ferramenta) vira um script do projeto, com nome curto: `scripts/testar.sh`, `scripts/testar.ps1`, um alvo no `Makefile`,
  um `npm run <nome>` ou um `[project.scripts]` no `pyproject.toml`.
- Caminho que muda de máquina para máquina (Python, SDK, pasta de dados) vai numa variável de ambiente lida pelo script, com
  um padrão razoável; nunca um caminho absoluto de uma máquina só dentro do script.
- O script roda a partir da raiz do projeto sozinho (não depende de um `cd` antes) e devolve o código de saída do comando.
- Antes de criar um script, procure um que já faça isso (`scripts/`, `Makefile`, `package.json`, `pyproject.toml`).
- Script novo entra no commit e é citado no CLAUDE.md (ou nesta regra), para os colegas usarem o mesmo nome.
