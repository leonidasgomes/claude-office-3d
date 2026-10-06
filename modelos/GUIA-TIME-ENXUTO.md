# Time de agentes enxuto (agent teams do Claude Code) — o que medimos e o que a documentação confirma

Guia para quem usa o Claude Office 3D com um time de agentes (líder + colegas). Saiu de um time real com 5 agentes, em que
**78% do custo era o modelo relendo o contexto acumulado** a cada resposta. Cada item diz de onde veio: **[DOC]** documentação
do Claude Code (code.claude.com/docs), **[MED]** medido nos transcritos com o `custo_time.py`. O pacote não muda nada disso
sozinho: são ajustes no seu projeto e no jeito de abrir o time.

## 1. Não leia em dobro o que já carrega sozinho
- **O `CLAUDE.md` carrega em toda sessão, inclusive nos colegas** [DOC agent-teams, "Context and communication"; memory].
  Prompt que manda "leia o CLAUDE.md" faz o agente ler duas vezes. Tire essa linha dos prompts e das definições.
- **O corpo da definição do agente (`.claude/agents/<nome>.md`) entra no prompt de sistema do colega** [DOC agent-teams, "Use
  subagent definitions for teammates"]. Ponha o papel do colega ali e mande na criação só a tarefa. Se o líder também manda
  ler um `team_dev.md` com o mesmo papel, o colega lê duas vezes. Para a sessão solta, use a mesma definição com
  `claude --agent <nome>` [DOC cli-reference].
- **O prompt do líder pode ir direto para o prompt de sistema**: `claude --append-system-prompt-file <arquivo>` [DOC
  cli-reference]. Junte os arquivos do líder num só ao abrir o time (no Windows, `copy /b a.md + b.md saida.md`), em vez de uma
  cadeia de "leia o arquivo X" que vira turno a mais no histórico.
- **`CLAUDE.md` curto**: a doc recomenda menos de 200 linhas [DOC memory]. Detalhe de configuração (hooks, plugins, env) vai
  para um documento que só quem configura lê.

- **Abra a sessão do time numa worktree sempre na base**, não na bancada de quem roda o motor do jogo. O Claude Code lê
  `.claude/` (definições de agente, regras por pasta, hooks) e o `CLAUDE.md` **da pasta onde a sessão abre** [DOC agent-teams,
  memory]. No nosso time a sessão abria no checkout principal, que ficava num branch antigo: os colegas nasceram com
  definições velhas e as regras por pasta não existiam [MED]. Hoje o lançador põe uma worktree na base a cada partida
  (`git worktree add --detach … origin/<base>` ou `checkout --detach` nela) e abre a sessão ali, com a bancada no `--add-dir`.
  Deixe essa worktree fora da pasta do projeto, para não carregar também o `CLAUDE.md` velho da bancada.

## 2. Carregue só quando precisar
- **Regras por pasta**: `.claude/rules/<tema>.md` com `paths:` no cabeçalho só entra no contexto quando o agente lê ou edita um
  arquivo que casa com o padrão [DOC memory, "Path-specific rules"]. Bom para regras de motor de jogo, de Blender, de front-end.
  Comece o padrão com `**/` para valer também dentro dos worktrees. Atenção: o gatilho é Read/Write/Edit, não o Bash — o que
  vale mesmo sem abrir arquivo (ex.: limites de CPU/GPU ao rodar um programa) fica no texto comum.
- **Procedimento raro vira skill**: antes do uso, só a `description` fica no contexto; o resto carrega quando é usado [DOC
  skills]. Skills de uma pasta passada com `--add-dir` também carregam. O `modelos/sugestoes_lider.md` deste pacote já vem
  nesse formato.

## 3. Contexto do colega: uma tarefa por vida
- **Colega não roda `/compact`**: `/compact`, `/clear` e `/rewind` agem na conversa do líder [DOC agent-teams]. O contexto do
  colega só cresce [MED: mediana de 143 mil tokens e máximo de 520 mil num colega de código].
- Ao entregar, o colega grava um handoff curto em arquivo (estado, branch/PR, o que ficou aberto) e o líder o encerra
  (`shutdown_request`) e cria de novo, com o mesmo nome, tipo e modelo, para a próxima tarefa [DOC costs: "Shut down
  teammates when their work is done"].
- Para o líder, a janela de compactação automática (`CLAUDE_CODE_AUTO_COMPACT_WINDOW`, de 100 mil a 1 M [DOC model-config])
  mais baixa corta releitura; com o cache quente, compactar lê do cache e custa pouco [DOC prompt-caching].

## 4. Cache e gatilhos
- **Colegas e subagentes usam cache de 5 min por padrão**, mesmo na assinatura; o líder usa 1 h [DOC prompt-caching, "Which TTL
  each request gets"]. Com esperas longas (build, testes de 15–60 min) o cache do colega expira e é reescrito.
  `CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL=1h` (ou `subagentPromptCacheTtl`) resolve [DOC]. O `custo_time.py` mostra o cache
  escrito de 1 h × 5 min por agente para você medir antes e depois.
- **Cron acorda o líder mesmo sem nada a fazer** e manda o contexto inteiro a cada disparo [DOC costs, "Why usage climbs"]. Use
  o `vigia_lider.py` deste pacote dentro da ferramenta Monitor: ele roda comandos sem tokens e só imprime (acorda o líder)
  quando há novidade. Configure no bloco `vigia` do `config.json`.
- **Espera de comando longo**: `run_in_background` ou Monitor com filtro, nunca `sleep 600; tail` em laço (cada consulta relê o
  contexto) [MED: 22 consultas assim num cartão].

## 5. Recursos que mudaram nas versões novas
- **Lista de tarefas compartilhada** (TaskCreate, `blockedBy`): no Sonnet/Opus 5.x só existe com `CLAUDE_CODE_ENABLE_TODO_TOOLS=1`
  antes de abrir o Claude Code [DOC tools-reference, "Task tool availability"]. Sem ele, o líder não cria tarefa nenhuma.
- **Hooks `TeammateIdle` e `TaskCompleted` não aceitam `additionalContext`** [DOC hooks]; o texto deles não chega ao líder. A
  notificação de ocioso chega sozinha ao líder; use o hook só para registrar (`systemMessage` aparece para o humano).
- **Colega fica limitado ao `tools` da definição** [DOC agent-teams]: se ele precisa chamar subagentes, a lista precisa ter
  `Agent`. As `skills` da definição **não** valem para colega (valem para subagente) [DOC].
- **Difusão para todos (`"*"`) não existe**: uma mensagem por destinatário [DOC agent-teams].
- **Hooks do escritório em segundo plano** (`"async": true`) não travam cada chamada de ferramenta [DOC hooks]; o instalador
  deste pacote já grava assim desde a 1.5.0.

## 6. Delegação (artigos da Anthropic sobre agentes)
- Cada delegação com **objetivo, formato de saída, ferramentas/fontes e limites claros**; sem isso os agentes duplicam trabalho
  ou deixam lacunas (anthropic.com/engineering/multi-agent-research-system).
- **Esforço proporcional à tarefa**: regra explícita no prompt (tarefa pequena = um agente, sem plano); **condição de parada**
  (orçamento por tarefa) para não continuar quando já tem o suficiente (mesmo artigo; building-effective-agents).
- **Avaliador-otimizador com critério claro**: o `revisor_ia.py` confere o aceite da issue citada no PR e para de apontar
  detalhe a partir da 4ª revisão (building-effective-agents: "stopping conditions such as a maximum number of iterations").

## 7. Documento de design não é changelog (o que medimos no GDD)
- No nosso time o GDD fazia quatro papéis: design, **changelog** (uma revisão nova a cada PR), **quadro de estado** ("Próximo")
  e **registro de entregas** escrito por script. Resultado medido: 41 edições e 37 commits em 7 dias, quase tudo reescrita de
  estado, 12 contradições (o mesmo número copiado em vários lugares e envelhecendo) e PRs só para corrigir o próprio documento.
  Nos achados dos revisores, porém, ele era só 2%: o custo estava no retrabalho e na informação velha, não em bugs.
- O que resolveu: o documento fica só com o que muda pouco (visão, objetivos com **critério de pronto verificável**, escopo,
  orçamento); histórico, decisões e registros vão para arquivos próprios; estado vai para o quadro; número medido fica no
  CSV/manifesto e o documento **aponta para a fonte**; PR de código não edita o documento; a revisão nova sai no fechamento de
  um objetivo. Uma checagem no revisor de arquitetura avisa quando um PR de código o edita e reprova acima de um teto de tamanho.

## 8. Revisar antes de abrir o PR
- `python <pasta do escritório>/revisor_ia.py --local <worktree>` roda o mesmo revisor do PR sobre o diff contra a base, sem
  comentar nada (~US$ 0,07). Achado resolvido ali não vira mais uma rodada de PR. Ponha no prompt dos colegas: "antes de abrir
  o PR, rode o --local e corrija P0/P1".
- Ponha as **causas que mais voltam** nos achados no arquivo de padrões de código que o revisor lê (`revisor.contexto`): cada
  regra vira conferência automática em todo PR. As nossas, de 155 achados: chave de cache completa, gravação atômica,
  geometria degenerada, validador que reprova na ausência de entrada, teste que prova, sem caminho absoluto versionado,
  documentação no mesmo commit e gerador conferindo a especificação.
