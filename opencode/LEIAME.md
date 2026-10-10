# Escritório 3D no OpenCode (plugin `opencode/office.js`)

O plugin traduz os hooks de ferramenta do OpenCode (`tool.execute.before/after`) para o
evento neutro do escritório (`emit_evento.py --evento`). A cena, os painéis e a Saúde não
mudam: o agente do OpenCode vira um boneco como qualquer outro, com `fonte: opencode`.

## Instalar

1. Copie `office.js` para `.opencode/plugins/office.js` do projeto (é de lá que o OpenCode
   carrega plugins locais; o array `plugin` do `opencode.json` é só para pacotes npm).
   O `importar_opencode.py --aplicar` já faz essa cópia.
2. Defina no ambiente **antes** de abrir o opencode:

| Variável | Obrigatória | Para quê |
|---|---|---|
| `OFFICE_EMIT` | sim | caminho do `emit_evento.py` (sem ela o plugin não faz nada) |
| `OFFICE_AGENTE` | não | mesa do escritório (`Dev`, `Lider`…; padrão: `OpenCode`) |
| `OFFICE_PROJETOS` | não | só emite dentro destas pastas, separadas por vírgula (padrão: todas) |
| `OFFICE_PYTHON` | não | Python que roda o emit (padrão: `python`) |

3. Abra o escritório (`iniciar_time.bat escritorio`) e use o OpenCode: cada ferramenta
   aparece na ficha do agente em ~2 s.

## O que chega

- `bash` → `trabalho` com `inicio: true` no começo + `trabalho` no fim (igual ao
  Pre/PostToolUse do Claude Code).
- Demais ferramentas → um `trabalho` com `resumo`/`detalhe` no fim.
- `resumo` segue a mesma ordem do hook do Claude (`skill`, `description`, `filePath`…).
- A tool `skill` vira ferramenta `Skill` (`skill: <nome>`): conta no `skills.py contar-uso` e no XP, igual ao Claude.

## Capacidades do adapter V1

- `ok`/`codigo` quando há saída explícita; erros de ferramenta via `message.part.updated`.
- `session.idle` vira `ocioso`; `task` vira `subagente`. Mensagens/reuniões entre colegas não são equivalentes ao Claude team.
- Sessão principal usa OFFICE_AGENTE; filhos observados têm mesa própria e vínculo com parentID.

O launcher `console_provider.py --provider opencode` configura o ambiente e evita eventos duplicados em `run --format json`. O after lê `input.args`, preserva a ordem início/fim e trata falhas assíncronas do Python. Mais detalhes em [PROVIDERS.md](../docs/PROVIDERS.md).

Consumo da TUI/filhos e atualização da cópia do plugin: [GESTAO.md](../docs/GESTAO.md#contadores-da-tui-e-dos-filhos-opencode). A ponte consumo_providers.py registra apenas contadores; mensagem/cost não viram cobrança.

Modelos cloud gratuitos: consulte [seleção explícita e limites](../docs/PROVIDERS.md#opencode-com-modelos-cloud-gratuitos). Não confunda o provider local da máquina com o gateway cloud `opencode`.

Para tarefas gerenciadas em worktrees, o launcher define `OFFICE_CONSUMO_PROJETO` com a raiz cadastrada. A ponte de tokens usa essa raiz; `OFFICE_PROJETOS` continua limitando os eventos ao worktree. Sem essa variável, consumo mantém `directory`. Reinstale/atualize a cópia do plugin para receber a mudança; não há migração automática de registros antigos.
