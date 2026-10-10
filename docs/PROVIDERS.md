# Consoles e skills compartilhadas

Para regras de gestão e autoridade das fontes, consulte [GESTAO.md](GESTAO.md).
Este guia descreve os adapters e sua compatibilidade nativa.

## Inventário e arquitetura

O escritório recebe eventos `trabalho`, `fala`, `reuniao`, `subagente`, `ocioso` no SQLite
da instalação. O servidor entrega esses dados à cena e aos painéis. Nesta nova
linha, Claude com prompt usa stream JSON, assim como os outros adapters. A TUI e
os teams nativos continuam disponíveis; hooks existentes não são desativados.
Os contratos SQLite e a compatibilidade explícita com o hook legado permanecem.
Consulte [VERSOES.md](VERSOES.md) para limites e migração entre instalações.

`providers_console.py` define capacidades, seleção, comandos e tradução de eventos.
`console_provider.py` é um launcher adicional. `emit_evento.py` já existente grava os
eventos na mesma tabela e mantém a fila de reserva. O campo opcional `sessao` identifica
a sessão nativa sem migrar seus dados nem alterar o esquema do SQLite.

| Provider | Team | Ferramentas no escritório | Skills |
|---|---|---|---|
| Claude | agent teams existente | `-p --verbose --output-format stream-json`; TUI pelos hooks | `.claude/skills` e catálogo comum |
| Codex/GPT | recursos nativos do CLI, sem equivalência garantida ao team Claude | `exec --json`; TUI por observação passiva dos rollouts | links `.agents/skills` + catálogo dos caminhos originais |
| OpenCode 1.x | subagentes por `task`, sem team Claude | plugin V1 na TUI; `run --format json` pelo launcher | `.claude/skills` ou links da fonte configurada |
| Gemini | execução pelo adapter, sem team Claude | `--output-format stream-json` | referências ao catálogo original; sem converter hooks/permissões |

O padrão é Claude. Precedência: `--provider`, `OFFICE_PROVIDER`, `provider` do JSON, Claude.
`auto` detecta na ordem Claude, Codex, OpenCode, Gemini. Escolha explícita ausente retorna erro;
nunca muda silenciosamente de conta/backend. Não há fallback após uma execução começar.
Nenhum comando acrescenta flags para ignorar permissões ou aprovações.

Codex aceita `--sandbox read-only` ou `--sandbox workspace-write` no launcher.
Sem essa opção, conserva o padrão nativo. No modo gestão, selecione o campo
`sandbox` do executor na política `.office/projeto.json` ou no formulário do
CEO/diretor/equipes. Um argumento explícito deve coincidir com essa política.
`workspace-write` permite ao Codex editar a workspace da tarefa; as aprovações e
regras nativas continuam valendo. Outros consoles não aceitam esse campo e
revisores Codex continuam isolados em `read-only`. Nenhuma opção altera a
configuração global do CLI.

Consultas isoladas OpenCode distinguem HTTP 403 como acesso recusado, HTTP 401
como autenticação indisponível e HTTP 429 como limite/crédito indisponível.
403 sozinho não determina falta de crédito ou de chave. O diagnóstico não
expõe corpo, headers ou credenciais, não troca o modelo e mantém a revisão
bloqueada. A presença de um modelo free no catálogo não comprova acesso.

## Executar

Execute na pasta `office-multi-provider`; abra o servidor pelo launcher atual.
Use um checkout/worktree apropriado às regras do seu projeto, especialmente com agentes simultâneos.

```powershell
python console_provider.py --provider claude --projeto D:/projetos/meu-app --mesa Dev
python console_provider.py --provider codex --projeto D:/projetos/meu-app --mesa Dev --prompt "Descreva o estado do projeto sem editar arquivos"
python console_provider.py --provider opencode --projeto D:/projetos/meu-app --mesa Dev --prompt "Descreva o estado do projeto sem editar arquivos"
python console_provider.py --provider opencode --projeto D:/projetos/meu-app --mesa Lider --agente orquestrador
python console_provider.py --provider codex --projeto D:/projetos/meu-app --mesa Dev --sessao ID --prompt "Continue a tarefa"
python console_provider.py --config console.exemplo.json --detectar
```

`--modelo` seleciona um modelo nativo; OpenCode exige `provider/model`. Sem ele, o CLI
mantém sua configuração. `--sessao` recebe o ID do próprio provider. Credenciais, modelos,
aprovações e persistência de sessão permanecem sob responsabilidade do CLI. A saída JSONL
é mostrada no terminal e alimenta o escritório; `--banco` permite validar em SQLite isolado.

Sem prompt, o launcher Claude abre a TUI nativa. Com prompt, executa um turno gerenciado com sessão e eventos padronizados; para **agent teams** continue usando o
launcher de time existente, que contém os prompts e a configuração específica da instalação.

## Consultas isoladas do Codex

Revisão, auditoria, triagem e consultas de CEO/diretor pelo adapter isolado exigem
um `thread.started` válido, um `turn.started`, itens completos e `turn.completed`
na mesma consulta. Só mensagens e raciocínio são aceitos; ferramenta, item/evento
desconhecido, sessão repetida, texto vazio e eventos após conclusão bloqueiam a
resposta antes de normalizar a decisão. O protocolo segue a
[documentação oficial do modo não interativo](https://learn.chatgpt.com/docs/non-interactive-mode).
Os controles de isolamento e a autenticação existente permanecem nativos.

Na prova de 10/10/2026, uma consulta Codex real detectou um erro P1 em diff
sintético, com sessão/turno completos e 13.939 tokens informados. Sem modelo
informado no stream, o indicador conserva essa ausência; não estima cobrança.
Essa prova não é revisão do jogo nem comprova diversidade de dois fornecedores.

## OpenCode com modelos cloud gratuitos

No painel Gestão, abra “Escolher consoles do CEO, diretor e equipes”, escolha
OpenCode/cloud e clique “Consultar modelos free do OpenCode”. A consulta usa o
CLI instalado (`models opencode --verbose --pure`) e mostra modelos Zen ativos
com ferramentas e custos declarados zero em entrada, saída e cache. Não considera
apenas o sufixo `free`, não faz inferência ou substitui um modelo automaticamente.
Escolher uma opção preenche o ID e limpa a declaração de cloud para você conferir
o fornecedor real; gateway/modelo anônimo não comprova diversidade de revisores.
Salvar continua sendo uma ação separada na política única do projeto.

Catálogo tem cache local de cinco minutos e timestamp; não comprova tarifa atual,
login, quota ou disponibilidade. Se consulta falhar, mantém o modelo preenchido;
não troca para pago, local ou outro console. A API de consulta exige PC e a guarda
normal de ações. Não modifica autenticação/configuração do OpenCode. Custos vindos
de endpoints diferentes de Zen ou com dimensões extras não recebem classificação
zero. A configuração local pode alterar metadados mesmo usando o endpoint Zen;
a classificação é declaração do CLI, sem atestação da tabela oficial de preços.

Use `opencode models opencode` para listar os modelos disponíveis no console instalado.
Selecione um ID gratuito explicitamente; a lista e a disponibilidade mudam no serviço.
Exemplo, quando esse ID estiver disponível:

```powershell
python console_provider.py --provider opencode --projeto D:/projetos/meu-app --mesa Pesquisa --modelo opencode/space-bunny-free --prompt "Descreva o estado do projeto sem editar arquivos"
```

Na política `.office/projeto.json`, o executor dessa equipe usa `console: "opencode"`,
`execucao: "cloud"` e o mesmo ID em `modelo`. Gratuito cloud não é execução local.
CEO, diretor, equipe e especialistas aceitam fornecedor do modelo não informado:
omita `cloud` quando ele não for conhecido. Isso não atribui ao Zen uma cloud real.
Revisão cruzada continua exigindo fornecedor declarado para revisor e autor;
um modelo sem essa identidade não comprova diversidade ou separação do autor.
A ausência de credencial Zen em `opencode auth list` não basta para concluir que os
modelos gratuitos estão indisponíveis: o cliente nativo pode oferecer modelos sem chave.
Listar um modelo também não comprova que uma inferência será aceita.

Se o serviço responder HTTP 403/429 ou outro erro, a execução falha e a tarefa continua
sujeita aos gates. O escritório não troca para modelo pago, outra conta ou backend.
Tokens só entram no histórico quando forem recebidos contadores válidos; falha sem
contadores não vira custo zero nem tarefa concluída. Não há promessa de cota semanal
comum: disponibilidade/limites do free tier pertencem ao serviço.

Consultas isoladas OpenCode também leem os envelopes JSON `error` para o diagnóstico:
HTTP 429 indica limite/crédito, 401 indica autenticação; 403 sozinho permanece falha
genérica. O motivo enumerado não expõe corpo, headers, metadata ou credenciais.
Um envelope de erro bloqueia a consulta mesmo com exit zero; códigos nativos não
zero são preservados. Texto de resposta normal não é usado para classificar falhas.

Em 10/10/2026, `opencode/nemotron-3.5-lightning-free` constava no catálogo local
com custo declarado zero, mas a prova isolada retornou erro e nenhuma revisão ou
contagem de tokens aceita. A documentação Zen identifica os endpoints gratuitos
Nemotron como NVIDIA; isso é declaração documental, não atestação da resposta nem
garantia de disponibilidade. A política de equipes não foi alterada pela prova.

Na prova isolada de 10/10/2026, o adapter comum rejeitava controles presentes
porque o OpenCode escreve `run --help` em stderr com exit 0. Corrigido em
revisores_console.rodar: somente comandos de ajuda combinam stdout/stderr;
resposta de inferência continua exclusivamente stdout JSON, e exit não zero
continua falhando. Ajuda grande demais também falha. Os controles não foram
relaxados. Prova com Big Pickle passou por ajuda/configuração efetiva isolada,
mas não produziu resposta aceita ou contadores. Registro nativo mais recente
compatível informa HTTP 403/restrição free tier; não determina a causa exata.

Na verificação posterior de 10/10/2026, Space Bunny Free respondeu pelo adapter
isolado: consulta JSON aceita (2.069 tokens), revisão de código sintético com
bug P1 detectado (2.179 tokens), CEO (3.243) e diretor (3.144) numa fixture de
Kanban. A coordenação selecionou somente o cartão 42, sem despacho ou escrita
GitHub. O parser de revisão agora exige uma etapa, sessão/mensagem/partes
coerentes e conclusão stop; erro, ferramenta, duplicação ou fim incompleto falham.
IDs/modelo são solicitados/configurados; o backend real não foi atestado.
Não comprova toda a TUI/team, cobrança real, disponibilidade futura ou os outros
modelos free. Os erros históricos continuam válidos para aquelas tentativas,
mas não descrevem indisponibilidade de todo OpenCode gratuito. O exemplo usa
esse ID explicitamente; o escritório não o escolhe como fallback automático.

O CLI desta máquina listou onze IDs opencode gratuitos. Modelo listado não
comprova inferência disponível. A [documentação oficial Zen](https://opencode.ai/docs/zen/)
fornece preços e o [catálogo público atual](https://opencode.ai/zen/v1/models).
Não fixe listas/preços como permanentes. O [cliente oficial v1.18.35](https://github.com/anomalyco/opencode/blob/v1.18.35/packages/opencode/src/provider/provider.ts)
carrega modelos de entrada gratuita mesmo sem chave; ausência de autenticação
não comprova indisponibilidade nem obriga compra. Guias externos de depósito não
substituem o comportamento documentado/oficial ou diagnóstico do serviço.
Nenhuma autenticação, chave, compra, header de identificação ou configuração
global foi alterada nesta prova. Cloud gratuita continua explicitamente escolhida.

Referências oficiais: [CLI](https://opencode.ai/docs/cli/),
[modelos](https://docs.opencode.ai/docs/models/) e
[carregamento Zen sem chave no cliente 1.18.35](https://github.com/anomalyco/opencode/blob/v1.18.35/packages/opencode/src/provider/provider.ts).

## Compartilhar skills

```powershell
python console_provider.py --projeto D:/projetos/meu-app --preparar-skills
python console_provider.py --projeto D:/projetos/meu-app --preparar-skills --aplicar
python importar_opencode.py --projeto D:/projetos/meu-app
python importar_opencode.py --projeto D:/projetos/meu-app --aplicar
```

O plano não escreve. Cada skill válida de instruções comuns recebe symlink (ou junction no Windows)
apontando para a pasta original de cada skill. A fonte padrão é `.claude/skills`;
quando existe `.office/projeto.json`, o catálogo, cadastro e links Codex usam
`fontes.skills`. A pasta `.agents/skills` também é um alias de descoberta Gemini
e é reconhecida pelo OpenCode. Descoberta real depende do CLI, confiança e
permissões nativas; criar link não comprova ativação. Assets, scripts e referências continuam juntos;
editar o original atualiza todos os consoles. Diretórios existentes divergentes são
preservados. Se links não forem possíveis, o catálogo no prompt de `exec` oferece os caminhos
originais, sem copiar o conteúdo. Remova somente os links criados para desinstalar, nunca a fonte.

O catálogo lê `name`/`description`, incluindo strings entre aspas e blocos YAML simples;
valida nome/pasta e descrição e rejeita campos repetidos/cabeçalho fora do subconjunto.
Não é um parser YAML completo. Scripts com dependências
externas continuam exigindo seus runtimes. Hooks, `allowed-tools`, `context: fork`, agentes,
permissões e modelos do Claude não ganham execução equivalente automaticamente. O relatório
de preparação lista esses limites; regras de segurança continuam sendo as do console.
Campos de runtime são lidos somente do cabeçalho; menções a hooks/allowed-tools
no corpo de um manual não são controles. Injeção dinâmica e substituições Claude
no corpo exigem mapeamento. Skills com esses recursos não ganham links novos
automaticamente. Links antigos/conflitantes ficam preservados e exigem conciliação.
O despacho e o cadastro validam skills explicitamente escolhidas contra o executor
antes de reservar tarefa/gravar funcionário. Claude cloud pode delegar recursos
conhecidos ao runtime nativo quando a fonte está na sua pasta `.claude/skills`;
isso não comprova que settings/permissões permitam ativação. Fonte personalizada
não é declarada registrada no Claude por apenas existir. Local não herda runtime
de skills dos consoles. O formulário desmarca/desabilita seleções incompatíveis
ao trocar console/execução e limpa o modelo ao trocar console.

Essa validação cobre seleções explícitas do escritório. Não remove skills nativas,
links antigos, redefine permissões ou impede descoberta implícita fora do despacho.
O OpenCode ignora campos extras de SKILL.md; suas permissões devem ser configuradas
no console, sem presumir que allowed-tools do Claude virou controle OpenCode.

Fontes: [Claude skills](https://code.claude.com/docs/en/skills),
[Codex skills](https://learn.chatgpt.com/docs/build-skills),
[OpenCode skills](https://opencode.ai/docs/skills/) e
[Gemini skills](https://geminicli.com/docs/cli/skills/).

Sem política, o prompt Codex/Gemini referencia `AGENTS.md`, `CLAUDE.md` e `PRODUTO.md`
quando presentes. Com política, referencia somente as fontes configuradas de
regras, produto e arquitetura e inclui o catálogo da pasta configurada.
O Codex lê o contexto por stdin para não ultrapassar a linha de comando do Windows.
OpenCode `run` também recebe contexto compartilhado e tarefa por stdin no launcher:
regras/fontes e skills pertinentes ao provider deixam de depender apenas de configuração
manual de `instructions`. O argumento posicional é uma orientação curta; modelo, sessão
e agente continuam selecionados pelas flags nativas. A TUI não recebe essa injeção.
No perfil local, o pipe transporta a tarefa simples já preparada pelo adapter local,
sem acrescentar o catálogo cloud ou ampliar o limite de contexto local.
Agentes `.claude/agents` não são importados como agentes nativos Codex; `--agente` rejeita
esse uso. OpenCode usa o importador existente e herda o modelo quando não há mapa explícito.
Com política, o importador usa a fonte oficial de regras em `instructions` e o
catálogo configurado de skills. Fontes personalizadas recebem links em
`.agents/skills`, descobertos nativamente pelo OpenCode, sem copiar conteúdo.
Conflitos de links são preservados/informados, inclusive com `--forcar`; links
indisponíveis exigem consultar o original. As demais instruções, modelos e
permissões existentes continuam no JSON. Revise entradas próprias que ainda
tenham regras divergentes: o importador não reescreve seus AGENTS.md/CLAUDE.md.

Referências oficiais: [regras](https://opencode.ai/docs/rules/) e
[skills](https://opencode.ai/docs/skills/). A descoberta por links foi confirmada
com `opencode debug skill` na versão instalada, sem inferência.
Listas `tools` são convertidas em permissões com negação padrão; revise ferramentas sem equivalente.

## OpenCode: correções e limites

O plugin V1 corrigido obtém argumentos de `input.args` no after (ou do before), preserva
ordem de gravação, trata erros assíncronos do Python, registra `session.idle` e erros de
ferramentas. Registra resultado de comandos somente quando há código explícito nos metadados;
não inventa sucesso. `skill` usa o formato `Skill`/`skill: nome`, compatível com XP de skills.
`task` emite subagente. `OFFICE_STREAM_OWNER=launcher` evita duplicar os eventos de `run`.
O plugin usa `OFFICE_EMIT`, `OFFICE_PYTHON`, `OFFICE_AGENTE`, `OFFICE_PROJETOS`, `OFFICE_BANCO`
e opcionalmente `OFFICE_FONTE`. Não use V1 em OpenCode V2 sem adapter novo.

Para atualizar um plugin já instalado, preserve sua cópia e substitua **somente**
`.opencode/plugins/office.js` pela versão desta instalação. `--forcar` do importador também
substitui agentes, então não o use indiscriminadamente em agentes personalizados.
Modelos fixos em agentes personalizados continuam prevalecendo sobre o padrão da sessão;
revise-os se apontarem para IDs indisponíveis. O nome para `--agente` é o nome do arquivo
sem `.md`, respeitando maiúsculas/minúsculas.

Limites reais: mensagens entre colegas, reuniões e despacho automático do Claude não são
reproduzidos pelo OpenCode; o plugin registra somente sinais observáveis. TUI Codex usa `codex_observador.py` para ler ferramentas, mensagens e ociosidade dos rollouts locais. A seleção de sessão exige caminho de projeto e identidade inequívoca; resume usa `--sessao` e não repete o histórico. Formatos desconhecidos são ignorados sem interromper o console.
Custos/cotas dos novos providers não são convertidos em dólares nem somados ao plano Claude.
Testes reais de leitura passaram com OpenCode 1.18.35 e Codex 0.158.0 (`gpt-6-sol`), incluindo a TUI Codex. O modelo global `gpt-6.1-sol` desta máquina foi rejeitado pelo CLI; use um modelo permitido explicitamente, sem mudar silenciosamente de modelo/conta.

## Validação

Skills Claude explicitamente selecionadas com recursos nativos recebem
`ativacao_nativa: Skill` no snapshot. O prompt pede ativação pela ferramenta Skill
e interrupção se indisponível; somente ler o arquivo não ativa hooks/contexto.
O launcher confere init com Skill disponível, chamada com nome exato e resultado
sem erro correlacionado por tool_use_id na sessão principal, seguido de result
sem erro. Filho, outra sessão, leitura do arquivo e saída zero isolada não bastam.
O despacho persiste nomes/estado/sessão no pacote da reserva e exige a evidência
antes de liberar entrega. Falta de evidência bloqueia o cartão; não impede efeitos
já executados pelo console. Isso comprova chamada e retorno observados, não cada
efeito interno de hooks/contexto/permissões. Formatos desconhecidos ficam pendentes.
Permissões e configuração do Claude continuam prevalecendo.

Testes Python de providers: seleção, ausência/fallback, comandos, resume, contrato original
Claude, eventos Codex/OpenCode, skills sem cópia, colisões, YAML e execução fake com SQLite.
Teste Node do plugin: hooks V1 reais simulados, ordem/falha/Skill/sessão/filtro/ENOENT.
Execute `python -W error ferramentas/testar_providers.py` e `node ferramentas/testar_plugin_opencode.mjs`
na versão dev; na pública, use `ferramentas/` no lugar de `testes/`.


## Verificação da integração

`testar_codex_observador.py` cobre descoberta, resume sem replay, JSONL parcial, isolamento e ambiguidade. `testar_providers_http.py` comprova que Claude, Codex, OpenCode e a TUI Codex chegam ao mesmo endpoint HTTP do escritório. Na versão dev, `iniciar_time_codex.bat` abre o escritório e o Codex interativo; `OFFICE_PROJETO`, `OFFICE_AGENTE` e `OFFICE_CODEX_MODEL` configuram a sessão local (padrão de modelo desta instalação: `gpt-6-sol`).


### Sessões de subagentes

O observador Codex (TUI e filhos de exec --json) reconhece descendentes por `source.subagent.thread_spawn.parent_thread_id`, inclusive worktrees dos filhos. Sessões sem ancestralidade da sessão selecionada são ignoradas. Cada filho recebe uma identidade própria; resume não repete o histórico anterior. Os eventos preservam `sessao_pai`, `agente_pai` e `sessao_filho` como campos opcionais, sem migração SQLite.

O plugin OpenCode registra `session.created/updated` e `task.metadata.sessionId`. Os filhos mantêm mesas próprias. Com `OFFICE_STREAM_OWNER=launcher`, somente a telemetria da sessão principal é suprimida no plugin; os filhos continuam observados. A cena usa a mesa do filho quando existe `sessao_filho`, preservando a representação anterior de tarefas Claude.

Isso observa a coordenação nativa; não implementa o protocolo de mensagens/teams Claude nos outros consoles.


### Verificação com delegação real

Codex 0.158.0 (`gpt-6-sol`) e OpenCode 1.18.35 completaram uma delegação somente de leitura de `AGENTS.md`: filho retornou `OFFICE_CHILD_OK`, pai retornou `OFFICE_PARENT_OK`. O OpenCode registrou `read` na mesa do filho e `task` no pai, com a mesma identidade de filho. Os rollouts Codex incluem histórico herdado: o observador usa `subagent_history_start_ordinal` para ignorá-lo e mantém o ID próprio do filho, mesmo diante de metadados herdados do pai. Em exec JSON, o observador aguarda `thread.started` antes de selecionar o pai e observa somente descendentes, evitando duplicação do stream principal. Operações `wait`/`close` não criam mesas de subagentes.

Mensagens nativas criptografadas não são decifradas pelo escritório; somente sinais e textos observáveis são registrados. A integração não cria um novo protocolo de agent teams nem converte custos de outras contas. A distribuição pública inclui os adapters tanto no ZIP quanto em `instalar.PACOTE`.

Consumo OpenCode do launcher JSON e seus limites estão em [GESTAO.md](GESTAO.md#consumo-opencode-pelo-launcher-json). O plugin atualizado coleta TUI/filhos pela ponte Python; veja a seção de contadores da TUI no mesmo guia.


### Conclusão dos novos consoles e prova da skill compartilhada

O executor comum valida o encerramento do fluxo principal de Codex, OpenCode
e Gemini por `retorno_console.py`. Exit code zero sem sessão e conclusão
bem-sucedida, erro nativo ou fluxo truncado retorna erro ao controlador, que
bloqueia a tarefa antes de revisão/entrega. Eventos desconhecidos não comprovam
sucesso. Falha recuperável de uma ferramenta pode ser seguida por conclusão
válida; no OpenCode, etapas `tool-calls` precisam de uma etapa final `stop`.
O contrato Claude e a TUI sem prompt permanecem nos caminhos existentes.
Essa validação não aprova código nem comprova conclusão de processos filhos.

Uma prova nativa em projeto Git temporário executou OpenCode Space Bunny Free
pelo despacho comum: ativou uma skill com nome/description/corpo compatível
com Claude, acessada por link compartilhado, e leu seu arquivo auxiliar.
Registrou sessão e 11.592 tokens em três etapas. A fonte da skill permaneceu
inalterada. Kanban foi simulado; sem PR, a reserva ficou bloqueada, sem revisão
ou merge. A prova usou permissões restritas e configuração somente do processo
filho; não alterou conta, projeto de validação ou instalações anteriores.
Não comprova paridade integral de skills/permissões/teams nem identidade da cloud.
