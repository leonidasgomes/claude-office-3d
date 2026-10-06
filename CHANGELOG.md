# Changelog

## 1.10.0
- **Eventos do escritório no banco SQLite local** (`banco.py`, tabela `evento`): o hook (`registrar_evento.py`) grava uma
  linha no banco em vez de acrescentar ao `dados/eventos.jsonl`, e o `GET /eventos` consulta pelo id; antes o servidor
  relia o arquivo inteiro a cada consulta (a cada 2 s) e o arquivo era separado aos 4 MB. Se o banco estiver ocupado ou
  quebrado, o hook grava em `dados/eventos.falha.jsonl` (continua sem bloquear nem imprimir). A contagem de uso das
  skills (`skills.py`) lê o banco (e o `eventos.antigo.jsonl` antigo, se existir).
- **Decisões do XP e vereditos do auditor no banco** (tabelas `decisao_xp` e `auditoria_ia`): "conferido" e "liberado"
  guardam quando, quem decidiu (`--origem`: botão do escritório no PC ou no celular, `auditor_xp`, linha de comando) e por
  quê (`--motivo`; o auditor grava o veredito e o modelo). Substituem `dados/xp/conferidos.json`,
  `dados/xp/auditorias_resolvidas.json` e `dados/xp/auditoria_ia.json`.
- **O banco mudou para `dados/escritorio.db`** (na 1.9 era `dados/xp/escritorio.db`; não é mais só do XP).
- **Migração automática, uma vez**: o banco da 1.9 é movido (com `-wal`/`-shm`); o `dados/eventos.jsonl` vira a tabela
  `evento` com id = número da linha (o escritório aberto continua de onde estava) e fica como `eventos.migrado.jsonl`; as
  listas JSON do XP viram linhas (origem "migrado") e ficam como `*.migrado.json`. Reinicie o escritório depois de
  atualizar.

## 1.9.0
- **Custo da sessão aberta estimado** (`custo_time.py`): o Claude Code só grava o `cost-state` quando a sessão fecha; antes a
  sessão ao vivo ficava de fora e o custo do dia parecia zerar. Agora ela é estimada pelos tokens, com o preço por peso de
  cada modelo calibrado nas sessões fechadas (lê ao menos 7 dias de sessões para isso, com qualquer `--dias`). A saída
  troca `sessoes_sem_custo` por `sessoes_ao_vivo`.
- **Correção do rateio**: o custo de cada sessão é dividido por **todas** as respostas dela e só entra a parte que caiu na
  janela; antes o total inteiro ia para as respostas da janela e inflava sessões longas que atravessam o corte.
- **Acumulado no banco SQLite local** (`banco.py`, novo; `dados/xp/escritorio.db`): o custo de cada sessão e de cada revisão
  do revisor de código fica guardado e o acumulado só cresce, mesmo quando a janela anda ou o Claude Code apaga transcritos
  velhos; uma foto por dia (com `--dias 7`). `dados/xp/custos.json` ganha `acumulado_usd` e `acumulado_desde`, e o
  **Placar** um tile "acumulado desde". `python banco.py` mostra o acumulado e os últimos dias.
- Nome de colega com sufixo `-3` (segundo colega do mesmo time, ex.: `Dev-3`) agora conta para o agente `Dev`, como `_3`.
- **`auditor_xp.py`** (novo, opcional, bloco `auditor` do `config.json`): confere sozinho a lista "para conferir" do Placar.
  Um modelo barato (padrão Haiku) julga o diff de cada amarelo; só o que ele achar suspeito vai à segunda opinião (padrão
  Sonnet). Legítimo é marcado como conferido; suspeita confirmada vira issue para o time do autor (campos opcionais
  `rotulo_issue` e `time_kanban` de cada agente; com o Kanban configurado, entra no quadro). Nunca libera vermelho. Com
  `auditor.ativo` e `xp.ativo`, o servidor roda o auditor a cada coleta das sugestões.

## 1.8.0
- **Painel PRs: verde só depois de todas as validações.** Antes acendia verde com a revisão aprovada e a caixa de sugestões
  vazia, mas antes de os bots e o revisor de código revisarem o commit atual; as sugestões chegavam depois. Agora o servidor
  coleta (sem a triagem paga) e calcula o `--pronto` de cada PR aberto a cada 3 minutos, por commit, e o painel só fica verde
  com a revisão aprovada **e** o pronto OK para o commit atual; fora disso, mostra o motivo da espera.
  `sugestoes_bot.pronto(cfg, n, coletar_antes=True, info=None)` aceita não recoletar e devolve o commit conferido.
- Sugestões contam como ativas também com só o revisor de código (`revisor.ativo`), sem bots do GitHub.
- **Guia de time enxuto**: abrir a sessão do time numa worktree sempre na base (de onde o Claude Code lê `.claude/` e o
  `CLAUDE.md`), não na bancada num branch antigo — o que medimos quando não era assim.

## 1.7.1
- Correção: o painel PRs guardava para sempre o veredito do check de revisão de cada commit. Quando a revisão era republicada
  no mesmo commit (reprovado, corrige o ambiente, aprovado), o painel ficava preso no veredito velho. Agora o veredito final
  fica em cache por 10 minutos.

## 1.7.0
- **`revisor_ia.py --local <worktree> [--base origin/main]`**: o mesmo revisor do PR sobre o diff da worktree contra a base,
  **antes** de abrir o PR, sem comentar no GitHub nem gravar estado (base padrão: o branch padrão do origin). Achado resolvido
  aí não vira mais uma rodada de PR.
- **Revisor mais robusto**: resposta do modelo com JSON mal formado ganha uma nova tentativa em vez de derrubar a revisão.
- **Sugestões**: sugestão **encaminhada** de PR já fechado também é arquivada; antes ficava para sempre contando como
  "segura o merge".
- **Guia de time enxuto** (`modelos/GUIA-TIME-ENXUTO.md`): seções novas "documento de design não é changelog" (o que
  medimos no nosso GDD e o que resolveu) e "revisar antes de abrir o PR" (o `--local` e as causas que mais voltam como regras
  do arquivo de padrões que o revisor lê).

## 1.6.0
- **`vigia_lider.py`** (novo, sem tokens): roda na ferramenta Monitor do líder e só o acorda quando `sugestoes_bot.py
  --pendentes` ou os comandos extras do bloco novo `vigia` do `config.json` têm saída nova (sem repetir a mesma). Substitui o
  `CronCreate` de 15 min, que mandava o contexto inteiro do líder a cada disparo só para responder "ok" (doc costs).
- **`custo_time.py`**: cache escrito de 1 h × 5 min por agente no relatório e em `dados/xp/custos.json`
  (`cache_escrito_mil`), para medir o efeito de `CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL=1h` nos colegas.
- **`modelos/sugestoes_lider.md`** agora é um modelo de **skill** do líder (só a descrição fica no contexto até o uso), com o
  vigia no lugar do cron e o dono do PR tratando as sugestões do próprio PR (`--pendentes --pr <n>`).
- **`modelos/GUIA-TIME-ENXUTO.md`** (novo): o que medimos num time de 5 agentes e o que a documentação do Claude Code confirma
  — não reler o `CLAUDE.md`, papel do colega só na definição do agente, `--append-system-prompt-file` para o líder, regras por
  pasta (`.claude/rules/` com `paths:`), procedimentos raros como skills, uma tarefa por vida de colega, cache de 1 h para
  colegas, `CLAUDE_CODE_ENABLE_TODO_TOOLS=1` para a lista de tarefas no Sonnet/Opus 5.x, hooks de time sem `additionalContext`.

## 1.5.0
- **Revisor de código confere o aceite do cartão**: o `revisor_ia.py` lê os cartões citados no corpo do PR (`Closes #n` /
  `Parte de #n`, no começo da linha) e põe o corpo de cada issue na revisão; o prompt manda verificar primeiro se o diff
  cumpre o aceite e se há prova (teste/comando) — não cumprir é P1. Teto: a partir da 4ª revisão do mesmo PR, só P0/P1.
- **`sugestoes_bot.py --pendentes --pr <n>` e `--listar --pr <n>`**: o dono do PR trata as sugestões do próprio PR antes
  de avisar o líder.
- **Hooks do escritório em segundo plano** (`"async": true`, doc hooks "Run hooks in the background"): o
  `registrar_evento.py` só grava o evento, então não trava mais cada chamada de ferramenta esperando o Python subir.
  Rode o instalador de novo para atualizar os hooks já instalados.
- Dicas para times de agentes, da documentação do Claude Code (não são do pacote, mas valem para quem usa o escritório
  com agent teams): no Sonnet/Opus 5.x a lista de tarefas compartilhada só existe com `CLAUDE_CODE_ENABLE_TODO_TOOLS=1`;
  colegas e subagentes usam cache de 5 min por padrão (`CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL=1h` compensa quando há
  esperas longas); os hooks `TeammateIdle`/`TaskCompleted` não aceitam `additionalContext` (use só `systemMessage`).

## 1.4.2
- **Revisor de código converge na re-revisão**: num commit novo de PR já revisado, o `revisor_ia.py` passa ao modelo as
  conversas anteriores do PR (cada achado e a resposta dada: corrigido, falso positivo e o motivo) com a ordem de não repetir
  nada já respondido, e só aceita P2/P3 em linha adicionada desde o último commit revisado (P0/P1 valem em qualquer lugar).
  Antes, cada commit de correção gerava uma rodada nova de P2/P3 sobre código que não mudou, repetindo inclusive falsos
  positivos já explicados, e o PR nunca ficava pronto. O resumo da revisão diz "Re-revisão" e quantos achados foram
  descartados por estarem fora do que mudou.

## 1.4.1
- **Custo do revisor de código**: `custo_time.py` soma o custo das revisões do `revisor_ia.py` no período (lido de
  `dados/revisor/estado.json`, já que o `claude -p` dele não aparece nos transcritos) ao total e ao custo por PR, e grava
  `revisor` (US$, revisões, achados) em `dados/xp/custos.json`. O Placar mostra um bloco "revisor de código" com esse valor.

## 1.4.0
- **Revisor de código próprio** (`revisor_ia.py`, bloco novo `revisor` no `config.json`, desligado por padrão): a cada commit
  novo de PR aberto, uma chamada `claude -p` (padrão Sonnet, sem ferramentas) lê só o diff e os arquivos de contexto do seu
  projeto (`revisor.contexto` + `glossario_triagem.md`) e comenta no PR pela sua conta do `gh`, com a marca `[revisor-ia]`.
  Procura bug, regressão, caso de borda, cache incompleto, teste faltando, documentação errada e violação das regras do
  projeto; não aponta estilo. Custo medido: ~US$ 0,18 por revisão de ~35–40 mil caracteres de diff. Com `revisor.ativo`, o
  servidor roda `revisor_ia.pendentes()` antes de cada coleta das sugestões. Estado em `dados/revisor/`.
- **Sugestões**: os achados "Previously missed" do índice do Copilot (sem comentário em linha) viram itens (`r<revisão>m<k>`);
  as revisões de **todo** PR aberto são lidas em cada coleta; a revisão "unable to review ... quota" não vira item; a marca
  `[revisor-ia]` é reconhecida (prioridade do título, rodapé limpo, resumo sem achado ignorado).
- **`--pronto` com avisos**: bot que revisou só um commit no PR é "de abertura" (o Codex, por exemplo) e não trava — vira aviso
  sugerindo comentar o comando de nova revisão; bot "por push" sem revisar o commit atual há mais de 30 min vira aviso; cota
  esgotada vira aviso. Com só avisos, imprime `OK` e as linhas `(aviso) ...`.
- **Escritório**: subagente numerado (`Dev_235`, `Dev_66b`) cai na mesa do agente, no hook e na página (antes, o sufixo com
  letra criava uma mesa nova). Nomes do config e `outros_nomes` continuam valendo exatamente como escritos.

## 1.3.1
- Correção: `plugins_projeto.py --projeto <pasta>` mostrava se o plugin estava ligado na pasta atual, não no projeto pedido.
  Agora a lista do `claude plugin list --json` é feita dentro da pasta do projeto.

## 1.3.0
- **`plugins_projeto.py`** (sem tokens): lista os plugins do Claude Code com o peso de cada um no contexto (tokens das
  descrições de skills e comandos, nº de skills e de servidores MCP) e desliga/religa plugins **num projeto só**
  (`--desligar`/`--religar`, grava `enabledPlugins` no `.claude/settings.json` dele). Num time real, plugins sincronizados do
  claude.ai sem relação com o projeto somavam a maior parte de uma lista de 201 skills (~10 mil tokens por sessão).
- **INSTALACAO.md §12 "Plugins e skills: o que carregar"**: plugins oficiais que reduzem exploração e medem custo
  (`pyright-lsp`, `clangd-lsp`, `session-report`), como instalar fora do disco do sistema e limitar os diagnósticos, conferir
  nomes no catálogo, e o caminho seguro para skills de terceiros (ler, varrer, fixar o commit, quarentena em
  `skills-candidatos/externo/`).

## 1.2.0
- **Custo do time** (`custo_time.py`, sem tokens): lê os transcritos do Claude Code das pastas em `projetos` e mostra o custo
  por agente, por cartão e por PR mergeado, o contexto médio por resposta, as sessões abertas por mais de 12 h e a
  exploração de código na mão por agente. O custo de cada sessão é o `cost-state` que o Claude Code grava no transcrito (já
  inclui colegas e subagentes); só a divisão entre as respostas é estimada. Grava `dados/xp/custos.json`.
- **Placar**: bloco "US$ por PR mergeado" e o custo de cada agente (só com dados reais); o servidor regenera o custo em
  segundo plano quando passa de 1 h (`GET /xp` ganha `custos`).
- **INSTALACAO.md §12 "Custo do time e como baixar"**: o que um time real mostrou (78% do custo era reler o contexto) e as
  alavancas `CLAUDE_CODE_SUBAGENT_MODEL` e `CLAUDE_CODE_AUTO_COMPACT_WINDOW` no `env` do projeto.

## 1.1.2
- **Pronto para o merge só com os bots em dia**: `sugestoes_bot.py --pronto <n>` diz OK ou o que ainda segura o PR (sugestão
  sem decisão, sugestão encaminhada e ainda não corrigida, bot que revisou o PR mas não o commit atual, PR novo que nenhum bot
  revisou ainda). O painel PRs segue a mesma regra: aprovado pelo revisor mas com sugestão pendente fica em "aguardando".
- **Triagem que aprende com o projeto**: a triagem (Haiku) recebe o `glossario_triagem.md` do seu projeto (modelo em
  `glossario_triagem.exemplo.md`; fica fora do git) e as últimas 20 sugestões ignoradas com motivo (`--acao ignorada --nota`).
  Termo do projeto que o bot insiste em "corrigir" deixa de voltar como "corrigir".
- Correção: o painel PRs não mostrava qual bot deixou cada sugestão (o resumo não mandava o autor).

## 1.1.1
- **Sugestões do Copilot completas**: o Copilot assina a revisão como `copilot-pull-request-reviewer[bot]`, mas os comentários
  em linha como `Copilot`, e por isso eles não eram coletados. Agora `copilot-pull-request-reviewer[bot]` em
  `github.bots_revisao` também aceita `Copilot`, sem mudar o config.
- A revisão geral do Copilot ("Copilot review overview") é só um índice: não vira item e dá a prioridade de cada comentário
  em linha pela gravidade (Critical/High/Medium/Low = P0/P1/P2/P3); antes ficavam todos como `?`.
- `sugestoes_bot.py --coletar --recoletar`: relê a janela `janela_dias` uma vez (depois de acrescentar um bot), sem duplicar.
- Painel PRs: cada sugestão mostra qual bot a deixou (Codex, Copilot, CodeRabbit…).

## 1.1.0
XP, níveis e ciclo de vida de skills (opcional, `"xp": {"ativo": true}` no config).

- **Quadro Kanban na parede** (com `github.kanban`): quadro branco em cima da mureta do fundo com as colunas do projeto
  (`github.colunas` ou a ordem em que aparecem), a contagem de cada uma e até 6 post-its por coluna (#n na cor do agente do
  cartão, urgentes primeiro, "+N" quando sobra). Clique no quadro abre o painel Kanban.
- **Aba "Cartões" na ficha do agente** (com `github.kanban`): os cartões ativos dele (todas as colunas menos a primeira,
  o backlog, e as concluídas), pelo campo "time" e o mapa `github.times`, com prioridade e link para o GitHub.
- O `kanban.js` lê o `/kanban` em segundo plano a cada minuto (o servidor responde do cache: não gasta a cota do GitHub) e
  avisa a cena com o evento `kanban`.
- Banheiro: o boneco para na frente da cabine, a porta abre e só então ele entra; ao sair a porta abre de novo, inclusive
  quando é chamado de volta no meio da pausa (antes ele atravessava a porta).
- Clique na cena ignora objetos invisíveis (balões e rótulos ocultos tapavam o boneco ou o quadro).

- **Vigia da cota do GitHub** (`cota.py`): a cada 5 min lê a cota (REST `gh api rate_limit` + a consulta GraphQL `{rateLimit}`,
  que o GitHub não cobra), guarda o histórico em `dados/github_cota.jsonl` (uma linha por leitura, 7 dias) e mostra no
  rodapé do Kanban e dos PRs "GraphQL: 3.200/5.000 (volta 11:25)" (pontos usados na hora / limite; REST só quando baixo).
  Restando menos de 20% sai o alerta "Cota do GitHub baixa" (tipo novo `cota`, ligado por padrão, um por janela e por
  recurso). `GET /kanban` e `GET /prs` ganham `cota` e `cota_baixa`.
- **Kanban pelo REST do Projects v2**: `GET /kanban` lê itens e campos por `/users|orgs/<dono>/projectsV2/<n>/fields|items`
  (100 por página) em vez de `gh project item-list`, que gasta ~200 dos 5000 pontos GraphQL por leitura. Sem REST do
  Projects (gh antigo, escopo, projeto), cai no GraphQL como antes.
- Instalador: `cota.py` e `sugestoes_bot.py` entram na lista de arquivos do pacote.

- `xp.py`: pontua os PRs mergeados por resultado verificado (aprovado de primeira, sem conflito com testes, cartão
  fechado, retrabalho, regressão); apagar teste ou acrescentar skip/xfail zera os pontos e abre uma auditoria
  (`xp.py --liberar N`). Atribuição pelo mapa `github.times`, rótulos e prefixos de branch; grava `dados/xp/placar.json`.
- Anti-trapaça em três faixas: 🟢 verde (pontos normais), 🟡 amarelo "para conferir" (pontos normais: skip
  condicional, consolidação de testes, teste enfraquecido com menos asserções acrescentadas que removidas, amostra de
  1 em 10 PRs) e 🔴 vermelho (zera os pontos: skip/xfail incondicional, apagar teste sem substituto, qualquer mudança
  em arquivo de avaliação). `xp.py --conferido N` marca o amarelo como conferido; `--liberar N` libera o vermelho.
  `placar.json` ganha `time.conferir_abertos`, `repo` e, por agente, `conferir`. Placar com tile amarelo, listas
  "🔴 Auditoria" e "🟡 Para conferir" com link para o PR, selo amarelo no botão e itens coloridos na aba XP. Config:
  `xp.padroes_avaliacao` e `xp.amostra_1_em`. PRs em cache são reanalisados uma vez quando a regra muda.
- `skills.py` e `skills-candidatos/MODELO.md`: candidato -> quarentena -> pronto-ab -> aprovado, uso por agente,
  `promover` gera o `SKILL.md` oficial e `contar-uso` sugere aposentar skills sem uso há 30 dias.
- Escritório: nível, estrelas e barra de XP no crachá de cada mesa, painel **Placar** do time (cooperativo, sem
  medalhas), aba **XP** na ficha do agente e comemoração com confete ao subir de nível. `GET /xp` no servidor.
- Hook: a ferramenta Skill vira "usa a skill <nome>" (com a skill e os argumentos no detalhe).
- Config: bloco `xp` (`ativo`, `desde`, `pesos`, `niveis`, `padroes_teste`, `atribuicao`); o assistente pergunta
  "Ativar XP e níveis?" no passo 6. Seção nova "XP, níveis e skills" no INSTALACAO.md.
- Sala da diretoria: um agente com `"sala": "diretoria"` no config ganha uma sala fechada (paredes de madeira e vidro,
  mesa grande, poltrona, estante, quadros e plaquinha) à direita da sala de reunião, com a mesa dele lá dentro; quem
  conversa com ele anda até lá pela porta, e as reuniões continuam na sala normal. Sem agente assim, o escritório
  fica como era.
- `modelos/diretor.md` (prompt genérico de um Diretor com 3 chapéus: revisão semanal e caso difícil) e
  `modelos/briefing_diretor.py` (exemplo: briefing de uma página a partir do config e do `gh`, sem gastar tokens).

- **Acesso pelo celular na rede local** (opcional, desligado por padrão; `--rede-local`, `abrir_escritorio.bat celular`
  ou `"rede_local": true`): HTTP só em `127.0.0.1:porta` para o PC, HTTPS em `porta+1` para a rede e uma porta auxiliar
  `porta+2` só com o certificado público da CA. CA própria gerada em `dados/tls/` (biblioteca `cryptography` ou `openssl`;
  NameConstraints só para IPs privados e `localhost`/`.local`, basic constraints `CA:TRUE, pathlen:0`, certificado do
  servidor de 390 dias renovado sozinho); botão **Recriar certificados**. Se não houver como gerar, cai para HTTP com aviso.
- Pareamento por **código de uso único** (10 min, só o hash guardado) com permissão "ver" ou "conferir"; cada aparelho tem
  sessão própria (cookie `HttpOnly`, `Secure`, `SameSite=Strict`, 30 dias; só o hash em `dados/dispositivos.json`), token
  anti-CSRF, limite de 10 ações por minuto, bloqueio de IP após 5 códigos errados, só IPs privados, só GET/HEAD (exceto as
  ações), cabeçalhos de segurança (CSP por hash, HSTS no HTTPS) e histórico em `dados/acoes.jsonl`.
- Botão **📱 Celular** (só em localhost): QR para instalar o certificado e QR de pareamento, impressões digitais SHA-256,
  lista de aparelhos com Revogar. QR code em JavaScript puro e embutido (`qr.js`), sem internet.
- Modo leve no celular (pixel ratio 1, sem antialias, menos confete, painéis em tela cheia com botões grandes).
- **Botões no Placar** (✓ Conferido, Liberar pontos, Desfazer, histórico de ações) no lugar dos comandos de terminal; o
  `xp.py` ganhou `--so-placar` (recalcula só do cache) e o placar traz a lista `resolvidos`.
- Config: `rede_local`, `rede_https`, `rede_tailscale` e `"sala": "diretoria"` por agente; o assistente pergunta
  "Permitir acesso pelo celular na rede local? [s/N]" e "Usar HTTPS (recomendado)? [S/n]" no passo 6; novos arquivos
  `rede.py`, `tls.py`, `qr.js`, `movel.js`, `celular.js` e `celular.css`. Seção 9 nova no INSTALACAO.md.
- **Não abre no celular? (Firewall e rede)**: subseção nova na seção 9 do INSTALACAO.md com as 4 checagens em ordem (mesma
  sub-rede, rede do Windows como Privada, regra de entrada do Firewall só para o Python do servidor na rede Privada, isolamento
  de AP/clientes) e o comando `New-NetFirewallRule` pronto; o `instalar.py` mostra esse comando (com o seu Python e as suas
  portas) quando o celular é ativado, sem nunca executá-lo. O painel 📱 Celular ganhou o bloco "Não abriu no celular?" com os
  4 passos e o comando para copiar com 1 clique; `GET /rede/status` (só localhost) passou a informar `python`, `portas` e
  `virtuais`; os endereços vêm com a placa do gateway padrão primeiro (o QR usa esse IP) e adaptadores virtuais
  (vEthernet/WSL/Hyper-V, 172.16-31) aparecem como "(virtual — não use)".
- **Layout responsivo no celular** (tela < 760 px ou paisagem baixa): cena 3D em tela cheia com a lista de agentes e eventos numa
  **gaveta inferior** arrastável (recolhida ~58 px com "4 agentes · 2 trabalhando", meio, cheia), botões num menu ☰,
  Placar/PRs/Kanban/ficha/Celular em tela cheia com cabeçalho fixo e botão de fechar grande, Kanban com uma coluna por vez
  (rolagem com snap), alvos de toque de 44 px ou mais, fontes de 14 px ou mais, `env(safe-area-inset-*)`, `100dvh` e
  `viewport-fit=cover`; rótulos e balões 3D maiores; o centro da câmera acompanha a gaveta; toque: um dedo gira, dois dão
  zoom, e o toque no boneco (com tolerância) abre a ficha sem confundir com arrasto ou pinça. Desempenho: a animação pausa e
  a consulta ao servidor desacelera (e as dos painéis param) quando a aba fica oculta.

- **Alertas** (notificação quando algo espera por você): um detector no servidor (a cada 60 s, `alertas.py`) avisa de PR
  pronto para o merge, PR com conflito ou reprovado, auditoria vermelha nova, item novo para conferir (desligado por
  padrão), escalonamento aberto/fechado (opcional), pergunta de escopo do Diretor e lembrete diário de PR pronto há mais de
  24 h, sem repetir (`dados/alertas_estado.json`; fila `dados/alertas.jsonl` com os últimos 200). Cada tipo liga/desliga
  no botão 🔔 Alertas. Entrega em camadas: **Web Push** padrão (RFC 8030/8291/8292, VAPID, aes128gcm; `push.py` com a
  biblioteca `cryptography` e `urllib`; `sw.js` mostra a notificação e abre o painel certo), toast/Notification API com a
  página aberta (`GET /api/alertas?desde=`) e toast do Windows opcional. Segurança: só aparelho pareado ou o PC, com
  sessão e CSRF; revogar o aparelho apaga a inscrição; no máximo 20 pushes por hora; push só com título curto, corpo de
  até 120 caracteres e o painel (nunca comando, caminho, código ou token); envio só para serviços de push conhecidos.
  `manifest.webmanifest` e ícones para o iPhone (precisa do escritório na Tela de Início, iOS 16.4+). Config: bloco
  `alertas`. Teste: `python -W error ferramentas/testar_alertas.py`. Seção "Alertas no celular" no INSTALACAO.md.

## 1.0.0
Primeira versão pública do Claude Office 3D.

- Escritório 3D no navegador (three.js) que mostra os agentes do Claude Code trabalhando: cada agente com mesa,
  nome, função, teclado e mouse; conversas indo até a mesa do outro; reuniões na sala de vidro.
- Ficha do agente: o que está fazendo (ferramenta, comando, arquivo) e o que está falando (mensagens completas).
- Pausas: área de descanso com sofá, TV com canais e ping-pong; refeitório com café e comida na mão; banheiro;
  conversas animadas entre quem está na pausa.
- Painéis do GitHub: Kanban (GitHub Projects) e pull requests esperando merge, com veredito do check de revisão.
- Apelidos só na interface (brasileiros, cinema ou desligado) e temas `neutro` e `sao-paulo`.
- Hook do Claude Code que registra eventos localmente (só das pastas configuradas) e servidor local em 127.0.0.1.
- Assistente de instalação em 7 passos (`instalar.bat` / `instalar.sh`), instalação silenciosa e desinstalação.
- Modo demonstração quando não há eventos.

- **Sugestões do bot de revisão** (opcional, `github.bots_revisao` vazio = desligado): `sugestoes_bot.py` coleta os comentários em
  linha e as revisões dos bots de revisão (id, PR, arquivo, linha, prioridade P0 a P3, título, texto, link) só dos PRs abertos,
  com `ETag` (304 não conta no limite do GitHub) e no máximo 1 chamada de comentários + 1 de PRs abertos + as reviews dos PRs com
  comentário novo. Caixa em `dados/sugestoes/` com situação `nova -> triada -> encaminhada | ignorada | discutir -> resolvida`
  (`--coletar`, `--pendentes`, `--tratar`, `--listar`). **Triagem barata opcional** (`sugestoes.triagem_modelo`, padrão Haiku): uma
  chamada de `claude -p` sem ferramentas por coleta com itens novos, até 30 itens, que sugere corrigir/ignorar/discutir. O servidor
  coleta a cada `sugestoes.intervalo_min` (15) minutos; `GET /api/sugestoes` (o celular pareado lê) e `POST /api/sugestoes/tratar`
  (só o PC, com CSRF). Alerta novo "Sugestão P0/P1 do bot de revisão". Painel PRs: selo "🤖 3 (1 P1)", lista expansível com link e
  botões Encaminhar/Ignorar/Resolvido no PC. `modelos/sugestoes_lider.md`: prompt do job do líder. Seção 11 nova no INSTALACAO.md
  (as seções seguintes foram renumeradas).
- **Menos chamadas à API do GitHub**: o painel PRs passou do GraphQL (`gh pr list`) para REST (lista com `ETag`, status do commit
  e `mergeable` em cache por `sha`, validade de 180 s); o Kanban (GraphQL) passou de 2 para 10 minutos e a URL do projeto é lida
  uma vez só; o exemplo `modelos/briefing_diretor.py` lista as issues por REST. Quando o limite do GitHub estoura, o Kanban e o
  painel PRs mostram "limite da API do GitHub atingido — volta às HH:MM" (`gh api rate_limit`, lido só quando dá erro).
  Diferenças: "fecha #n" vem do texto do PR e, com `check_revisao` vazio, a aprovação vem de `/pulls/{n}/reviews`.
