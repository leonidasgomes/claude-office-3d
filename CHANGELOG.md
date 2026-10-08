# Changelog

## 1.18.0
- **O escritório no próprio .venv** (`instalar.py`, `abrir_escritorio.*`, `reiniciar_escritorio.*`, `.gitignore`,
  `ferramentas/verificar.py`): o instalador ganhou o passo "Python do escritório (.venv)", que cria `<destino>/.venv` sem
  pip (o escritório só usa a biblioteca padrão) ou reaproveita um que já funcione; uma pasta `.venv` que não seja um venv
  nunca é mexida, e um `.venv` cujo Python não roda só é recriado se você confirmar no assistente (no modo silencioso,
  aviso e nada apagado). Reinstalar com o mesmo `config.json` não grava nem faz backup dele (backup só quando muda). O hook e a statusline chamam o Python do `.venv`, **entre aspas** (`"…/.venv/Scripts/python.exe"` no
  Windows, `"…/.venv/bin/python"` no macOS/Linux); reinstalar troca o comando antigo no lugar, sem duplicar. Os atalhos
  preferem o `.venv`. `--sem-venv` (ou `"venv": false` no bloco `instalacao`) mantém o `python` do PATH. `.venv/` fora do
  git e da varredura do `verificar.py`.
- **Boas práticas do projeto** (`boas_praticas.py`, novo; `modelos/praticas/python-venv.md`, `modelos/time/*.md`,
  novos): `python boas_praticas.py validar [PROJETO] [--json]` confere em cada pasta de `projetos` o básico do time de
  agentes — git, `.gitignore` cobrindo segredos (`.env`, `*.pem`, `*.key`), `.claude/settings.local.json` e as pastas
  geradas da tecnologia (`.venv/`, `node_modules/`, `Binaries/`…, `bin/`/`obj/`; só as regras do projeto, `.gitignore`
  e `.git/info/exclude`, contam: o ignore global do usuário não vale para quem clona), `.env` versionado, CLAUDE.md,
  `.claude/agents/<nome>.md` de cada agente do `config.json`, hook do escritório, comando de teste, grafo, CI e, em
  projeto Python, `.venv`, dependências declaradas, a regra `.claude/rules/python-venv.md`, hooks e agentes usando o
  Python do `.venv`. Níveis erro/aviso/dica; sai com 1 se algum erro falhar. `corrigir` mostra o plano e, com
  `--aplicar` (`--so ids`, `--instalar-deps`), faz só o seguro: cria o `.venv`, acrescenta ao `.gitignore` (CRLF
  preservado), grava a regra e as definições de agente que faltam (modelos no formato do time enxuto) e troca o python dos
  hooks do grafo pelo do `.venv` (com backup do settings do projeto). Nunca sobrescreve arquivo e nunca escreve no
  settings do usuário. Veja `INSTALACAO.md` §17.
- **Instalador: passo "Projeto: boas práticas"** (`instalar.py`, `configuracao.py`): mostra o relatório de cada projeto e
  pergunta se aplica as correções (padrão não). No modo silencioso o relatório sai sempre e as correções rodam com o novo
  bloco `"praticas": {"corrigir": true, "instalar_deps": false}` do `config.json`.
- **Painel 🩺 Saúde: seção "Boas práticas do projeto"** (`servidor.py`, `saude_painel.js`, `saude_painel.css`): nova rota
  `GET /api/praticas` (validação numa thread, cache de 10 min, espera no máximo 3 s; o celular recebe só o nome da pasta,
  e os caminhos absolutos no detalhe e no erro viram `…/<nome>`) e a seção com o que falta em cada projeto, ERRO primeiro, o "como corrigir" e o comando da CLI.
- **Testes** (`ferramentas/testar_praticas.py`, novo; `ferramentas/testar_instalacao.py`, `.github/workflows/ci.yml`):
  detecção, cada checagem (com repositório git temporário), plano sem efeito, aplicar idempotente, backup, CRLF, caminho
  do `.venv` no Windows e no POSIX, CLI e códigos de saída e a rota com o servidor numa thread; a instalação confere o
  `.venv`, o comando do hook entre aspas, `--sem-venv` e `"praticas": {"corrigir": true}`.
- **Revisão de PR (líder + revisor)** (`instalar.py`, `boas_praticas.py`, `modelos/time/lider.md`,
  `modelos/time/revisor.md`): novo passo do assistente, padrão sim (o assistente passou a ter 10 passos): põe o agente
  **Revisor** no time do `config.json` e cria `.claude/agents/revisor.md` em cada projeto (nunca sobrescreve; um revisor
  de outro nome, como `code-reviewer.md`, também conta; o nome casa por palavra — revisor, reviewer, revisao —, então
  "previsao" e "preview" não contam) e, com repositório configurado, oferece o revisor-ia explicando o
  custo por commit. O modelo do líder ganhou a seção "Fluxo de PR" (revisor numa vida nova por PR, só com o número; P0/P1
  voltam ao autor; aprovado, o líder avisa o desenvolvedor, que faz o merge) e o do revisor publica a revisão no PR com
  `gh pr review <n> --comment` (1ª linha `[revisor]`; nunca `--approve`, nunca merge). Um líder existente sem a seção
  não é alterado: o instalador mostra o texto. Sem `.claude/agents/lider.md` (a sessão principal faz o papel de líder),
  o instalador avisa e mostra a seção para colar no `CLAUDE.md` do projeto, sem mexer nele. O modo silencioso faz o mesmo; `--sem-revisao` (ou `"revisao": false` em
  `instalacao`) pula. `python instalar.py --revisao <projeto>` aplica só isso numa instalação existente, com o diff do
  `config.json`, confirmação e backup. `boas_praticas.py` ganhou a checagem `revisao-pr` (agente revisor, revisor-ia,
  `bots_revisao` ou `check_revisao`), corrigível criando o `revisor.md`. Testes em `ferramentas/testar_praticas.py` e
  `ferramentas/testar_instalacao.py`. Veja `INSTALACAO.md` §18.
- **Versão no painel** (`servidor.py`, `opcoes.js`, `index.html`, `estilo.css`): nova rota `GET /api/versao`
  (`{"local": "<conteúdo do VERSION>"}`, sem consultar o GitHub) e "Versão 1.18.0" no pé do menu ⚙️ (no celular, na seção
  de opções do menu ☰); sem servidor, a linha não aparece.
- **grafo** (`grafo/grafo.py`, `grafo/claude/instalar_grafo.py`): a busca pontua o "id citado" no texto; o índice de
  eventos usa caller/callee antes de producer/consumers; as regras geradas por `sync-rules` citam a cópia do projeto
  (`.claude/grafo/grafo.py`) quando ela existe, seja qual for o `grafo.py` que rodou; `instalar_grafo --copiar` gera hooks
  com guarda: se `.claude/grafo/grafo_hook.py` faltar no clone, o hook sai com 0 em vez de bloquear Edit/Write.

### Correções
- **Servidor: POST recusado** (`rede.py`): o corpo é descartado antes da resposta; no Windows a conexão era encerrada com
  RST e o cliente via "conexão anulada" no lugar do 403. O teste de `--pendentes` (`ferramentas/testar_saude.py`) não
  depende mais do milissegundo.
- **Servidor: prazo de 15 s no socket do `HandlerSeguro`** (`rede.py`): um cliente lento não prende mais a thread lendo
  o cabeçalho ou o corpo.

## 1.17.1
- **Menu ⚙️ Opções** (`opcoes.js`, novo; `index.html`, `estilo.css`, `escritorio.js`): no cabeçalho do painel ficam só os
  painéis (PRs, Kanban, Placar, Alertas, Saúde, Arquitetura, Replay); Visão geral, Apelidos, Animações, Som, Demo e
  📱 Celular (só no PC) foram para o menu do botão ⚙️, e cada opção mostra o estado atual ("Animações: auto", "Som:
  desligado", "Demo: ligado"). Teclado: Enter/Espaço/↓ abrem, ↑/↓/Home/End andam, Tab circula dentro, Esc fecha e devolve
  o foco ao ⚙️; clique fora fecha. No celular as opções viram a seção "⚙️ Opções" do menu ☰. Os botões e ids são os
  mesmos de antes (links diretos, `__office` e atalhos continuam iguais).

## 1.17.0
- **Grafo de arquitetura para agentes** (`grafo/`, nova; copiada pelo instalador): `python grafo/grafo.py` mantém um grafo
  de arquitetura do seu projeto **conferido contra o código** (imports/includes reais de Python, C/C++, JS/TS, C# e
  scripts) e responde barato o que um agente pergunta antes de mexer: `init` (propõe um grafo; nunca sobrescreve),
  `validate` (esquema, cobertura, camadas, ciclos e imports reais que o grafo não declara), `owner`/`suggest` (dono de um
  arquivo), `slice` (recorte de um sistema em ~250–600 tokens), `impact` (o que a mudança afeta e que testes rodar),
  `find`, `drift`, `index` e `sync-rules`. Nada chama modelo. Hooks opcionais do Claude Code **por projeto**
  (`python grafo/claude/instalar_grafo.py --projeto <pasta> --aplicar`): contexto do sistema na 1ª edição, dono para
  arquivo novo e `validate` no fim da tarefa. Manual em `grafo/LEIAME.md`.
- **Painel 🗺️ Arquitetura** (`grafo_painel.py`, `arquitetura.js`, `arquitetura.css`, novos; `servidor.py`): sistemas em
  colunas por camada, dependências declaradas, imports reais não declarados, camadas violadas e ciclos; ficha de cada
  sistema; ao vivo, quem está lendo/editando cada sistema, ✖ de teste/build que falhou e 🔁 de quem anda em círculos; a
  ficha do agente mostra o "sistema atual". O servidor lê o grafo **só leitura** pelo git, na ref `grafo.ref` (padrão
  `origin/main`) da 1ª pasta de `projetos`, a cada `grafo.intervalo_min` (60). Sem grafo no projeto, o painel mostra como
  criar um. Novo bloco `"grafo"` no `config.json` (`ativo`, `ref`, `arquivo`, `intervalo_min`; veja `INSTALACAO.md` §16).
  Nova rota `GET /grafo`.
- **Segurança e robustez do grafo** (verificação independente): o `instalar_grafo.py` recusa (código 2) quando o alvo
  seria o `~/.claude/settings.json` do usuário (rodado na home, `--projeto ~` ou num repositório de dotfiles na home) e,
  com `--copiar`, grava `python` no comando (o arquivo vai para o git do time) e avisa sobre `--python python3`; `includes`
  que saem da raiz do projeto não são lidos; `name: 2024`/`status: true` no YAML viram texto (não quebram o índice nem o
  painel); o painel não mostra o índice de outra configuração depois de mudar `grafo.ref`/`grafo.arquivo`/projeto; YAML
  do grafo acima de 10 MB é recusado.
- **Eventos do NotebookEdit** (`registrar_evento.py`): o caminho do notebook (`notebook_path`) entra no detalhe do evento.
- **Testes** (`grafo/testes/testar_grafo.py`, `ferramentas/testar_grafo_painel.py`, novos; no CI).

## 1.16.2
- **Segurança — arquivos internos não são mais servidos por URL disfarçada** (`servidor.py`): o bloqueio de `dados/`,
  scripts e `.json` olhava o caminho como chegava; com `%64ados`, `/x/../dados`, `dados.`, `dados::$DATA` (Windows) ou
  `/servidor.py/.` dava para baixar `dados/` (inclusive sessões e tokens anti-CSRF dos outros aparelhos) e os scripts —
  só para quem já tinha acesso (PC ou aparelho pareado). Agora o caminho é decodificado e normalizado como o servidor o
  resolve, o arquivo real precisa ficar dentro da pasta do escritório e fora de `dados/`, e o sufixo é conferido no nome
  normalizado e no nome real (cobre o nome curto 8.3). Novo `ferramentas/testar_estaticos.py` (no CI).
  **Atualize** se usa o acesso pelo celular.

## 1.16.1
- **A triagem das sugestões dos bots voltou a rodar** (`sugestoes_bot.py`): a thread `pronto` do servidor coleta a cada
  3 min sem triagem e pegava as sugestões novas antes da coleta com triagem, que então achava 0 novas e nunca chamava o
  modelo. Agora a coleta tria tudo o que estiver `nova` na caixa.
- **No máximo 2 tentativas por item**: a tentativa é contada antes de chamar o modelo; um item que o modelo não
  classificou (ou que falhou) em 2 chamadas fica `nova` para o líder, sem novo custo. Reabrir o item zera a contagem.
- Novo teste `ferramentas/testar_sugestoes_triagem.py` (sem rede e sem modelo), no CI.

## 1.16.0
- **Atenção ao atualizar:** a triagem vem LIGADA por padrão (até 30 chamadas por dia do modelo barato no seu plano).
  Para desligar: `"sugestoes": {"saude_triagem": ""}` no `config.json`.
- **Triagem do painel 🩺 Saúde por um modelo barato** (`saude_triagem.py`, novo; `saude.py`, `servidor.py`): cada item NOVO
  (trabalho duplicado, agente em círculos, PR parado) é avaliado uma vez pelo modelo de `sugestoes.saude_triagem` no
  `config.json` (sem essa chave, o mesmo de `sugestoes.triagem_modelo`, o Haiku), pelo seu Claude Code (`claude -p` sem
  ferramentas, sem MCP e sem sessão, a partir da pasta do escritório).
  - **Problema real** → o líder é avisado automaticamente uma vez pelo vigia: `[vigia saude] triagem (modelo barato): ...`,
    com o aviso de que é um palpite e nada destrutivo deve ser feito sem você (`vigia_lider.AVISO_TRIAGEM`). **Acrescente
    ao prompt do líder** a regra nova de `INSTALACAO.md` §11.
  - **Falso positivo** → o item não alerta nem acorda o líder até se resolver; aparece em "Silenciados pela triagem" com o
    motivo e o botão **↩️ Desfazer falso positivo** (só no PC). Gravidade "alta" nunca é silenciada.
  - Um duplicado ou círculo novo espera o veredicto até 15 min antes de alertar (PR parado não espera). Se a triagem falhar (sem `claude`, resposta inválida,
    tempo esgotado), tudo funciona como antes.
  - **Custo**: no máximo 3 chamadas a cada 5 min e **30 por dia** (a mesma ocorrência nunca é reavaliada; um item que vai e
    volta, no máximo 2 vezes por dia), cada uma com o contexto curto de um item. O gasto fica em
    `dados/saude_triagem.json` (`custo_usd`) e a contagem do dia no painel.
  - **Para desligar**: `"sugestoes": {"saude_triagem": ""}` no `config.json`. Nome de modelo inválido também desliga.
  - Segurança: branch, título de PR e comando vão ao modelo marcados como dado e escapados; a resposta é validada
    (enums e tamanho) e a linha ao líder sai de um modelo fixo, com só o motivo (saneado e marcado como dado) em texto livre.
    No Windows só o `claude.exe` é usado (`claude.cmd`/`.bat` passariam os argumentos pelo `cmd.exe`); no Linux/macOS, o
    `claude` de sempre.
- **Ignorar vale só para a ocorrência** (`saude.py`): quando o problema some (numa rodada com o GitHub e o git
  respondendo), o item vai para **Resolvidos (24 h)**, o "Ignorar" e o veredicto da triagem expiram e o pedido ao líder
  ainda não entregue é cancelado. Se o problema voltar, alerta de novo.
- **Painel Saúde** (`saude_painel.js`, `saude_painel.css`): veredicto 🤖 em cada item, seções "Silenciados pela triagem" e
  "Resolvidos (24 h)", pedido "cancelado: resolvido". Nova rota `POST /api/saude/triagem` (só do PC, com os mesmos
  cabeçalhos de navegador das outras ações do painel).
- **Testes** (`ferramentas/testar_saude.py`): triagem com modelo falso (nunca chama o modelo de verdade), injeção no dado e
  na resposta, teto do dia, oscilação, resolvidos e cancelamento.


## 1.15.0
**Rode `instalar.py` de novo** (ou `instalar.bat` / `instalar.sh`) para ganhar o hook `PostToolUseFailure`: sem ele o
escritório não fica sabendo quando um comando falha (o ✖ e o ⚠️ abaixo não aparecem). O instalador só acrescenta o que
falta, sem duplicar os hooks que você já tem.

- **Escritório 3D mais legível de longe** (`escritorio.js`, `estilo.css`): anel no chão na cor do estado de cada agente e,
  de longe, um ícone do que ele faz no lugar do nome; pose sentada conforme a ferramenta (lendo, editando, delegando,
  esperando um comando); comando longo com um relógio que enche até o limite (`espera_s`) e ⚙️ em build/teste; quem está
  ocioso há mais de 10 min mostra 💤.
- **Saúde do time na cena**: agente "andando em círculos" ganha anel e seta laranja, coça a cabeça e diz quantas vezes
  editou o arquivo; PRs parados viram uma pilha de papéis na mesa do líder (o agente com `"lider": true`).
- **✔/✖ dos comandos** (`registrar_evento.py`, `instalar.py`): o fim de cada comando Bash/PowerShell leva `ok`; o boneco
  comemora (✔) ou põe as mãos na cabeça (✖), a ficha diz "último comando falhou (exit N)" e 3 falhas seguidas deixam o anel
  âmbar com ⚠️. O sucesso chega no `PostToolUse` e a falha só no novo hook `PostToolUseFailure` (só Bash/PowerShell);
  comando em segundo plano e evento antigo, sem `ok`, ficam neutros. Do erro, só a 1ª linha (até 120 caracteres) é
  guardada.
- **Tela de PRs na parede e sino do líder** (com `github.repo`): ao lado do quadro Kanban, prontos, aguardando, com
  problema e parados; a moldura brilha com PR pronto e um sino na mesa do líder toca quando surge um novo. Clique abre o
  painel PRs.
- **Festa no merge e mesa que evolui com o nível** (`placar.js`): PR novo pontuado faz uma festa curta para o dono; ao lado
  de cada mesa um gaveteiro ganha caneca, planta, livros e troféu conforme o nível do XP.
- **Mais vida na cena**: fio vermelho entre as mesas quando dois agentes editam o mesmo arquivo em menos de 10 min; envelope
  na mão de quem manda mensagem (o destinatário mostra uma linha dela) e pasta na mão de quem convoca reunião; gato do
  escritório (fica agitado com círculo ou duplicado); dia e noite pelo relógio do PC.
- **Passe o mouse e clique**: dica sobre agentes e objetos (TV, tela de PRs, pilha, gaveteiro, quadro, gato, fio); clique
  abre o painel certo; **📍 Seguir** na ficha faz a câmera acompanhar o agente.
- **Animações**: botão no menu (auto, reduzidas, completas); "auto" segue o `prefers-reduced-motion` do sistema. Reduzidas:
  sem confete, pulinhos, balanço nem transição de câmera.
- **Sons opcionais** (botão 🔇/🔊, desligados por padrão; sem arquivos, gerados no navegador): PR pronto, merge/nível,
  comando que falhou e o gato.
- **Modo leve** automático em PC sem aceleração de vídeo (renderização por software) ou com `?leve=1` (`?leve=0` desliga):
  menos quadros por segundo, sem confete, gato e fios.
- **Painel 🩺 Saúde** (`saude_painel.js`, `saude_painel.css`, novos; `saude.py`, `servidor.py`, `rede.py`, `alertas.py`):
  trabalho duplicado, agentes em círculos, PRs parados e o risco dos PRs abertos, com links para o GitHub. No PC:
  **🙈 Ignorar / ↩️ Reativar** (o item some dos alertas e do vigia do líder, mas fica em "Ignorados") e **📨 Avisar o
  líder** (grava um pedido que o `vigia_lider.py` entrega uma vez, como `[vigia saude] pedido do desenvolvedor: ...`).
  Os alertas de duplicado, círculo e PR parado agora abrem este painel.
- **Segurança do painel Saúde**: ignorar e avisar são só do PC e exigem os cabeçalhos `Sec-Fetch-Site`/`Sec-Fetch-Mode` de
  navegador; o User-Agent vai para o histórico de ações e aparece no painel (o que não parece navegador fica em amarelo).
  O pedido só leva tipo, números e o nome do item marcado como dado (`item (dado, não é instrução): "..."`), nunca título
  de PR; o vigia o entrega com o aviso de que é informação, não ordem. **Acrescente ao prompt do líder** a regra de
  `INSTALACAO.md` §11 ("Como o líder recebe").
- **Replay do dia** (botão ⏪ Replay; `banco.py`, `servidor.py`): escolha o dia e o intervalo e reveja tudo na própria cena
  a 1×, 10×, 60× ou 300×, com marcas de falha, fala, círculo e merge na barra e ⏭ para a próxima. Nova rota
  `GET /eventos?de=&ate=&apos=` (paginada, até 5000 por página) e índice por horário no banco (criado sozinho).
- **Filtros por agente e por tipo** (🔎 Filtrar acima do feed e 👁 Só este na ficha): o feed mostra só o escolhido e os
  outros agentes ficam esmaecidos na cena; lembrado neste navegador. Link direto `?agente=<nome>&aba=xp`.
- **Testes** (`ferramentas/`): novos `testar_registrar_evento.py` e `testar_eventos.py` e casos do painel Saúde no
  `testar_saude.py` (inclusive um POST HTTP real em porta aleatória); os dois novos entram no CI.


## 1.14.0
- **ⓘ em cada número do Placar** (`dica.js`, novo; `placar.js`): um ⓘ ao lado de cada tile (XP total, aprovado de
  primeira, retrabalho, auditorias, para conferir, uso do plano, custo por PR, acumulado, revisor) explica como o número
  é calculado. O texto usa a **sua** configuração: pesos, data inicial (`xp.desde`), janela de retrabalho e amostra
  aleatória vêm do bloco `regras` do `placar.json` que o `xp.py` grava, e o check de revisão vem de
  `github.check_revisao` (sem ele, as reviews do PR). Os números do momento (PRs pontuados, custo da janela, consumo por
  dia) aparecem embaixo da explicação. Uma legenda ⓘ explica o cartão de cada agente (níveis de `xp.niveis`). A dica
  abre com o mouse, com Tab e com toque, e Esc ou tocar fora fecha; o leitor de tela lê o texto sem depender do balão.
- **ⓘ no selo de risco do PR** (`prs.js`): explica linhas, arquivos, os limites de médio/grande (os mesmos de
  `saude.RISCO`) e o que conta como check falhando; a sugestão ("dividir em PRs menores") entra no mesmo texto.
- **Lista de agentes diz o que cada um faz e há quanto tempo** (`escritorio.js`): no lugar de só a hora do último
  evento, a linha mostra o resumo do que o agente está fazendo e "rodando há 9 min" (comando longo), "ocioso há 20 min",
  "há 3 min" ou "sem eventos recentes"; a hora exata fica no `title` (passe o mouse) e no leitor de tela. O texto se
  renova a cada 30 s sem recriar a lista. A ficha do agente mostra o mesmo. Cada linha também abre a ficha pelo teclado
  (Tab + Enter).
- **Alertas recentes no topo** (`alertas.js`, `alertas.css`): o painel 🔔 abre direto na lista; ativar o push, o teste e
  os tipos ficam num bloco recolhido **⚙️ Tipos de alerta e push**, que mostra o estado ("push ligado · 9 de 12 tipos")
  e é lembrado neste navegador. Alerta que abre o painel PRs ou Placar também responde ao teclado.
- **Responsividade e acessibilidade** (`estilo.css`, `placar.css`, `prs.css`, `kanban.css`, `index.html`): sem rolagem
  lateral de 360 a 1366 px; o cabeçalho do painel lateral quebra linha no PC em vez de esconder botões; foco visível no
  teclado; `aria-label` nos botões ×; número do PR sem quebrar dígito a dígito; cartões do Kanban sem cortar o título e
  textos fracos com contraste AA; tiles do Placar com valores longos (US$ 1279,04) sem cobrir o ⓘ.
- **Instalador** (`instalar.py`): `dica.js` entra no pacote copiado.
- **Aviso do iPhone no topo dos Alertas** (`alertas.js`): a instrução "Adicionar à Tela de Início" (sem ela o iPhone não
  recebe push) fica visível mesmo com o bloco de configuração recolhido.
- **Servidor aceita mais conexões ao mesmo tempo** (`servidor.py`): a fila de conexões passou de 5 para 64; no Windows a
  página às vezes recebia "conexão recusada" ao carregar vários módulos de uma vez.

## 1.13.0
- **Saúde do time, sem tokens** (`saude.py`, novo; `servidor.py`, `alertas.py`): três alertas novos a partir de uma
  pesquisa sobre por que PRs de agentes falham ("Where Do AI Coding Agents Fail?", arXiv 2601.15195; MAST, arXiv
  2503.13657; "The Observability Gap", arXiv 2603.26942):
  - `duplicado`: a mesma tarefa em duas branches ou PRs ativos (mesmo nome com números de issue diferentes, ou dois PRs
    abertos para a mesma issue). PR duplicado é a 2ª causa de PR de agente rejeitado (23%).
  - `circulo`: o mesmo agente editou o mesmo arquivo 6 vezes e rodou o mesmo comando 4 vezes em 45 min (o ciclo
    editar → rodar → editar que trata o sintoma em vez da causa).
  - `pr_parado`: PR aberto, fora rascunho e pronto, sem atualização há mais de `alertas.parado_horas` (24 h).
  `GET /saude` mostra tudo (inclusive os duplicados "fracos": duas branches ativas da mesma issue) e o servidor grava
  `dados/saude.json` a cada 5 min (mesmo com os alertas desligados; com o GitHub fora, só os círculos).
- **Selo de risco no painel PRs** (`prs.js`, `servidor.py`): linhas alteradas, arquivos e checks falhando de cada PR,
  amarelo/vermelho quando grande (cada check que falha tira ~15% da chance de merge; PR maior entra 17% menos). O tamanho
  vem do mesmo `GET /pulls/{n}` que o servidor já fazia para o conflito: nenhuma chamada a mais ao GitHub.
- **Orçamento de atenção** (`alertas.py`, `push.py`, `alertas.js`): só os tipos de `alertas.imediatos` (PR pronto, PR com
  problema, pergunta, escalonamento, auditoria, cota) avisam na hora; os de rotina entram na lista sem toast e saem num
  único push de resumo `alertas.resumo_horas` (3 h) depois do primeiro aviso. O painel mostra quantos avisos saíram hoje. Base: "Oversight
  Has a Capacity" (arXiv 2606.08919). **Muda o comportamento:** `lembrete` e `sugestao` deixam de chegar na hora; para
  voltar ao antigo, ponha os dois em `alertas.imediatos`.
- **Vigia do líder avisa duplicado e círculo** (`vigia_lider.py`, `configuracao.py`): passo `saude` (`vigia.saude`,
  ligado por padrão) roda `saude.py --pendentes`.

## 1.12.0
- **Segurança — faixa do Tailscale só com `rede_tailscale`** (`rede.py`, `servidor.py`): com o acesso pelo celular
  ligado, `rede.ip_permitido` aceitava sempre a faixa `100.64.0.0/10` (Tailscale/CGNAT), mesmo com
  `"rede_tailscale": false`; fora do Tailscale essa faixa é o CGNAT da operadora, compartilhado com outros clientes.
  Agora ela só entra com `"rede_tailscale": true` (o servidor passa o flag ao `rede.Rede`, valendo com ou sem HTTPS e na
  porta do certificado). Novo `ferramentas/testar_rede.py` (IP privado entra; `100.64.x` recusado com o flag desligado e
  aceito com ele ligado; IP público recusado).
  **Atenção ao atualizar:** quem acessa pelo Tailscale precisa de `"rede_tailscale": true` no `config.json`, senão o
  celular passa a receber 403.
- **Alerta "PR pronto" com a mesma regra do painel PRs** (`alertas.py`, `servidor.py`): desde a 1.8.0 o painel só fica
  verde com o `--pronto` OK no commit atual, mas o alerta olhava só a revisão e podia sair antes. A fonte `sugestoes` do
  detector agora leva o `PRONTO` da thread de validações, e `situacao_pr` exige o mesmo que o `prs.js`: nenhuma sugestão
  segurando o merge e, com bots/revisor configurados, o `--pronto` OK para o `sha` atual. Sem sugestões configuradas,
  vale só a revisão, como antes. Ao reiniciar o servidor, o detector espera a 1ª rodada da thread `pronto` antes de ler
  os PRs (`pronto_carregado`), e a thread troca o `PRONTO` sem esvaziá-lo: antes, todo PR já pronto repetia o alerta a
  cada reinício e o lembrete de 24 h recomeçava. Com bots/revisor configurados, se a caixa de sugestões não puder ser
  lida numa rodada, o detector pula os PRs em vez de usar só a revisão. `ferramentas/testar_alertas.py` cobre os casos,
  incluindo o reinício.
- **Agente esperando comando longo aparece trabalhando** (`registrar_evento.py`, `instalar.py`, `escritorio.js`): o hook
  só gravava o evento no fim da ferramenta, e o painel apagava o "trabalhando" 60 s depois; quem esperava um build ou
  teste de vários minutos aparecia ocioso. O instalador agora liga também o `PreToolUse` (só `Bash|PowerShell`), que
  grava o início do comando com `espera_s` (o timeout dele), e o painel mantém o agente trabalhando até o comando acabar
  (até o timeout do comando, no máximo 10 min). Rode `instalar.py` de novo para ganhar o hook.
- **Pacote do instalador completo** (`instalar.PACOTE`): passa a copiar `modelos/` (citado no README e no guia),
  `skills-candidatos/externo/README.md`, `docs/SDD.md`, `VERSION`, `CHANGELOG.md` e `LICENSE`. O
  `ferramentas/testar_instalacao.py` falha se um arquivo versionado ficar fora da lista.
- **Documento de projeto** (`docs/SDD.md`, novo): arquitetura, componentes, modelo de dados, rotas, CLI, configuração,
  variáveis de ambiente, fluxos, segurança, limites, testes e decisões, com a fonte de cada afirmação. Link no README.
- **SDD conferido no CI** (`ferramentas/verificar_docs.py`, novo, só biblioteca padrão): falha listando toda rota HTTP,
  tabela do banco, script com CLI e flag, chave de primeiro nível do config ou variável `OFFICE_*` que não esteja no
  SDD. Regra: o que é novo entra no SDD na mesma mudança (seção 13 do SDD).
- **CI** (`ci.yml`): instala `cryptography` e roda também `testar_alertas.py`, `testar_rede.py` e `verificar_docs.py`.
- **Textos corrigidos**: docstring do `sugestoes_bot.py` (as reviews são lidas de todo PR aberto, não só dos que tiveram
  comentário novo); docstring do `servidor.py` (o celular com permissão "conferir" marca e desfaz conferidos); docstring
  do `pronto_laco` (custo real: ~3 chamadas REST sem ETag por PR aberto + 1 lista); `INSTALACAO.md` §9 (o
  `dados/dispositivos.json` também guarda o token anti-CSRF da sessão, em texto puro; Tailscale só com o flag) e §10
  (regra do alerta "PR pronto"); exemplo de nome do aparelho na página de pareamento ("Meu celular").

## 1.11.0
- **Uso do plano no Placar** (`statusline_uso.py`, novo): o Claude Code passa à statusline, pelo stdin, os limites do plano
  (`rate_limits.five_hour` e `rate_limits.seven_day`: percentual usado e hora do reinício). A statusline mostra uma linha
  curta (`5h 42% ↻18:30 · semana 61% ↻qui 09:00`) e grava a leitura no banco local (tabela `uso_plano` do
  `dados/escritorio.db`; no máximo uma por minuto, só quando muda). Só planos de assinatura; com API key não grava nada.
  O campo ainda não está na documentação pública do Claude Code (visto na 2.1.292).
- **Placar**: tiles do uso na janela de 5 h e na semana (amarelo a partir de 70%, vermelho a partir de 90%), pontos da
  semana gastos hoje (dica com os últimos 8 dias e o ritmo das últimas 24 h) e projeção no reinício semanal no ritmo
  atual (amarelo a partir de 85%, vermelho a partir de 100%). `GET /xp` ganha o bloco `uso` (`banco.uso_resumo()`).
- **Instalador**: passo opcional que liga a statusline no `~/.claude/settings.json` (assistente, passo 7, ou
  `--statusline` / `"instalacao": {"statusline": true}` no modo silencioso). Nunca substitui uma statusline que já
  exista: avisa e mostra como encadear com `statusline_uso.py --so-gravar`. O `--desinstalar` só a remove se for a do
  escritório. O `ferramentas/testar_instalacao.py` cobre os dois casos.

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
