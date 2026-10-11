# Usar os controles de Gestão

## Trabalho automático pelo GDD

A política `ciclo` em `.office/projeto.json` habilita explicitamente a coordenação:
`ativo`, `duracao_min` (120), `max_cartoes` (2), `intervalo_seg` (300),
`base` (`origin/branch` do projeto) e `criar_subtarefas` (opcional).
O padrão público é desligado. Configure `kanban.prioridades` na ordem desejada;
por exemplo P0/P1/P2/P3. O GDD define o objetivo, o Kanban o estado vivo,
e a passagem de turno fornece contexto histórico.

O atalho com `iniciar_equipe.py` inicia o ciclo pelo host e abre um console de
acompanhamento. O CEO não duplica o lote que o host está conduzindo.
Se o ciclo já estiver ativo, o atalho verifica o processo, projeto e sessão e
abre seu acompanhamento, sem novo despacho ou extensão do prazo. PID ausente,
reutilizado, identidade divergente ou estado incerto continuam exigindo conciliação.
A área Trabalho e indicadores mostra estado, objetivo, cartões, causa e próxima ação.
Após duas horas, nenhuma tarefa nova começa; o despacho em curso termina.
Sem mudança no quadro, PRs, fontes, reservas ou disponibilidade da bancada,
a espera de cinco minutos não chama IA.

O diretor recebe fontes com hash, candidatos completos e inventário de evidências.
Recebe também as reservas, sem presumir que uma sessão antiga continua ativa.
Dependências Markdown aceitam `Dependências` e o nome legado `Depende`;
referências ambíguas bloqueiam a preparação e precisam ser esclarecidas.
Decide executar, desbloquear ou aguardar. Uma investigação pode virar sub-issue
com aceite próprio, sem alterar o aceite do pai. A criação grava intenção antes
de escrever no GitHub: falhas parciais exigem conciliação e não são repetidas.
Reservas antigas e cartões em andamento não são retomados automaticamente.
Se uma equipe deste ciclo encerrar com retorno confirmado, mas sem PR, o bloqueio
volta ao diretor para avaliar preparação vinculada. Essa consulta não retoma o
cartão bloqueado. Falha do console ou tentativa incerta exige conciliação; a
exceção de preparação não se aplica a reservas antigas. Gestão mostra os últimos
resultados e seus motivos, sem transformar retorno 0 em entrega aprovada.
Criações Git usam `GIT_LFS_SKIP_SMUDGE=1`; conteúdo binário necessário exige
preparação da equipe, sem download automático para um cartão de documentação.
Um recibo parcial permanece bloqueado até conciliação explícita. Se for
comprovado que não houve despacho nem reserva e os processos próprios acabaram,
o operador pode registrar `cancelado_antes_despacho` com a justificativa em
`conciliacao`, preservando o branch/worktree parcial. O próximo início cria
outro destino; não reaproveita nem limpa o anterior.
Na conciliação explícita de um coordenador encerrado, `preservar_janela: true`
em `conciliacao` do estado pausado limita o novo coordenador ao prazo anterior.
Isso não retoma tarefas: permite um novo início após conferir os recibos, sem
estender a janela aprovada. Um prazo já vencido continua bloqueado.

O controlador aceita `--acao ciclo --arquivo` com `{}` e `--projeto` canônico.
Para publicação limitada, `--acao publicar` recebe cartão, worktree, título e
corpo do PR. Exige recibo de criação, branch próprio e reserva em execução;
preserva hooks, recusa alterações de regras/política e não executa merge.
Falha após commit/push fica no recibo, sem repetir publicação automaticamente.
O pedido JSON deve ficar em `dados/controlador`, fora do worktree. Se for salvo
por engano como arquivo novo da entrega, o host exclui somente envelopes JSON
idênticos ao pedido atual, registra os nomes e preserva o arquivo no disco.
Arquivos JSON de produto permanecem na entrega. Pedido já indexado/versionado
bloqueia antes do commit: retire-o da entrega e confira novamente.
Despachos Codex novos do ciclo recebem `GIT_OBJECT_DIRECTORY` apontando para um
cache novo por tentativa em `dados/controlador/git-objetos-ID`, já dentro da
área autorizada. `GIT_ALTERNATE_OBJECT_DIRECTORIES` aponta para os objetos
existentes do worktree, usados somente para leitura. Isso permite ao gate
executar `git merge-tree --write-tree` sem escrever no `.git` protegido.
Refs, índice, hooks e permissões permanecem nos locais anteriores; commit/push
continuam exclusivos da publicação limitada pelo host. Cache existente ou fora
da área autorizada bloqueia o lançamento. Retomadas e outros consoles não
recebem essa configuração. O cache não é uma entrega nem substitui testes,
aprovação de arquitetura, revisões e checks do commit atual.
Claude legado continua com suas sessões e instruções específicas.

Abra **⚙️ → Gestão das equipes** e escolha uma das áreas do seu projeto:

- **CEO e diretor:** console/modelo da liderança, revisão opcional e merge.
- **Equipes:** cadastrar equipe, editar especialidade e executor ou excluir.
- **Funcionários:** cadastrar, editar ou excluir funcionários e seus skills.
- **Trabalho e indicadores:** tarefas, retomadas, consultas e consumo.

Salvar não inicia agentes. Equipes novas precisam do mesmo nome no campo Time
do Kanban quando forem receber cartões. O nome de uma equipe existente é
preservado; especialidade e executor podem mudar. Exclusão pede confirmação,
preserva o histórico e é bloqueada quando há vínculos pendentes. Funcionários
excluídos são arquivados. Após mudar o cadastro, use **Atualizar cena 3D** para
recarregar os assentos. Se a configuração mudou em outra janela, atualize a
Gestão antes de salvar novamente.

# Gestão do escritório por projeto

Consoles podem implementar e testar dentro do sandbox sem conseguir publicar Git
ou acessar a API do GitHub. Nesse caso o escritório registra bloqueio por falta
de entrega, conservando sessão e alterações. Publique a entrega no host autorizado
após revisar/testar, depois use a retomada explícita com a mesma sessão. Confira
processos/ferramentas antes de declarar agentes conciliados. A retomada não amplia
permissões nem muda contas; o controlador confere o PR real antes de encaminhar
à revisão. A publicação no host continua sendo uma etapa explícita.

A revisão por IA é opcional por projeto. Configure no painel Gestão, em
**Configurar revisão deste projeto**: ativação, quantidade de fornecedores e
separação do autor. Desativar preserva revisores e checks/merge. Consulte
[Revisão opcional](REVISAO-OPCIONAL.md) para detalhes e limites do auditor.

Cada item de `revisao.revisores` aceita `ativo: false` para suspender um revisor
indisponível, conservando nome e executor. O campo omitido conserva o comportamento
anterior. Suspender um revisor não desativa a revisão nem reduz `clouds_distintas`:
a seleção considera somente os habilitados e bloqueia antes de chamar qualquer
modelo quando faltam fornecedores independentes do autor. Reative explicitamente
com `ativo: true` após conferir acesso no console. Alterar a política invalida
relatórios anteriores; não autentica, não troca modelo e não inicia agentes.

O painel Gestão mostra a exigência de diversidade e os revisores habilitados ou
suspensos pela política. Essa contagem não confirma login, cota nem disponibilidade.

## Desempenho e resultado das tentativas

Gestão agrupa as execuções dos últimos sete dias por equipe, console, modelo
configurado e modo, junto de duração e consumo vinculado. Novas tentativas guardam
a equipe e o tipo (despacho/retomada) no início. O resultado distingue falha do
console, ausência de entrega, encaminhamento com revisão aprovada ou desativada,
reprovação na revisão e bloqueio nos gates após retorno. Esses fatos são históricos:
nova reserva ou mudança de equipe não reatribui as tentativas anteriores.

Tentativa sem retorno ou resultado não recebe sucesso presumido. Dados anteriores
sem essa atribuição aparecem como não informados, mesmo com saída zero. Resultado
de revisão refere-se aos gates do despacho naquele momento; não comprova merge,
aceite final, qualidade do modelo ou retrabalho. Retomada é um comando explícito
de continuidade da sessão. Consumo continua parcial quando faltam contadores ou
vínculos; quotas e cobrança de assinatura permanecem separadas por fornecedor.

A conferência comum do cartão relê a política antes e depois das consultas ao
Kanban, skills e fontes. Se ela divergir do snapshot do despacho, a entrega é
bloqueada, inclusive quando a revisão estiver desativada. Mudança durante a
consulta do PR não autoriza encaminhar o cartão com a política antiga. Retorno
e consumo já registrados permanecem no histórico; falha após retorno fica como
bloqueio nos gates, sem sucesso presumido. As releituras não são uma transação
atômica com o GitHub nem encerram agentes nativos que ainda estejam trabalhando.

## Caixa de sugestões por projeto

O bloco opcional `"sugestoes": {"ativo": false, "bots": [], "triagem": false}` em .office/projeto.json
controla a coleta. Para habilitar, informe ativo=true e os logins dos bots de
revisão daquele projeto. São identidades de comentários, não atestação da cloud
ou aprovação de revisores independentes. Omitir o bloco conserva o padrão desligado.
Exemplo: `"sugestoes": {"ativo": true, "bots": ["copilot-pull-request-reviewer[bot]"]}`.

O servidor coleta cada projeto habilitado no intervalo da instalação; também
é possível usar `python sugestoes_bot.py --projeto D:/projetos/meu-jogo --coletar`.
Repo/equipes vêm da política comum e caixa/cursor ficam em
dados/gestao/<id>/sugestoes/<hash-repo>/. Números de PR e IDs de comentários iguais
em outros projetos não compartilham decisões. A CLI exige --projeto com gestão ativa.
A lista de PRs abertos é paginada. Falha/formato inesperado ou dez páginas
completas interrompem a coleta antes de arquivar sugestões; lista parcial não
prova que um PR fechou. Comentários com URL de outro repo não entram na caixa.

No painel de PRs, a seleção também determina GET /api/sugestoes?projeto=ID.
Encaminhar/Ignorar/Resolvido enviam projeto e versão da política; leitura não
inicia inferência ou coleta. Política alterada impede gravar a decisão antiga.
Respostas fora de ordem ou de outro repo não substituem a caixa selecionada.
Sem política de gestão, os contratos/triagem do legado permanecem iguais.

A coleta nova não herda bots, triagem/modelo Claude, revisor automático ou
publicação de status globais. Só lê o GitHub e grava a caixa local; tratar não
responde ao bot no GitHub nem executa merge. Prontidão
completa de PRs e publicação de evidências ainda
precisam de integração. O painel mantém a validação final como pendente.
Uma trava antiga da caixa nova não é roubada por prazo; exige inspeção no PC.

Para propostas automáticas, habilite `sugestoes.triagem=true`: o diretor definido
na mesma política faz uma consulta cloud isolada pelos adapters comuns de Claude,
Codex, Gemini ou OpenCode. Não herda o modelo Claude global. OpenCode exige modelo
cloud explícito `provider/modelo`; escolha um modelo free disponível na sua conta.
Erro nativo não troca fornecedor, conta ou modelo. Local fica fora desta triagem.
`--sem-triagem` suspende a consulta naquela coleta.

Os documentos canônicos do projeto fornecem contexto; comentários/documentos não
autorizam ferramentas ou comandos. Até 30 itens por chamada, duas tentativas por
item, contadas antes da consulta. IDs/equipes/ações fora do formato rejeitam toda
a resposta. Política/fontes alteradas ou item tratado/reaberto/editado durante a
consulta impedem aplicar a proposta antiga. O resultado apenas muda nova para
triada: encaminhar, ignorar, resolver, despachar e merge continuam explícitos.
Consumo informado pelo console entra no ledger comum como papel Triagem; modelo
configurado e informado permanecem distintos. Ausência de uso/cobrança não vira
zero; recibo da consulta não presume USD. Claude usa sessão nova sem ferramentas.
Testes simulam os quatro roteamentos e mantêm regressões do fluxo legado; isso
não comprova disponibilidade cloud de todos os consoles nesta máquina.

## XP no mesmo projeto do Kanban

Na gestão ativa, calcule com `python xp.py --projeto D:/projetos/meu-jogo`.
Projeto precisa estar cadastrado no escritório. Repo, quadro, campos, equipes e
coluna final vêm da política .office/projeto.json. Cache e decisões ficam em
dados/gestao/<id>/xp/<hash-repo>/, separados inclusive após trocar de repositório.
Decisões globais antigas não são importadas por número de PR.

O Placar tem seletor de projeto. Conferido/Liberar/Desfazer enviam projeto e versão
da política; o servidor valida o placar e executa XP em processo separado.
Mais de um projeto exige seleção; erro de política não volta ao repo global.
Para conferir pelo terminal: `python xp.py --projeto D:/projetos/meu-jogo
--conferido 42 --so-placar`. A opção --versao-politica HASH é usada como pré-condição
pelo painel. Pesos/níveis ainda vêm do config da instalação.

XP por projeto não mistura custos globais, eventos de skills sem vínculo ou
histórico geral de ações; esses dados não têm atribuição suficiente aqui.
Indicadores por fornecedor permanecem no componente próprio do Placar.
Sem gestão configurada, o XP legado conserva seu funcionamento. Auditor
automático tem parecer consultivo por projeto; alertas de saúde/atividade ainda
precisam de integração por projeto.

## Auditor consultivo dos itens para conferir

Ative `"auditor": {"ativo": true, "max_diff": 60000, "max_prs": 3}` na política
do projeto. Exige revisão ativa, pelo menos duas clouds distintas e separação
do autor. Usa a lista existente `revisao.revisores`, sem outra fonte de modelos.
O autor é inferido da equipe/rota configurada, não atestado pelo GitHub. Cloud
é declarada pelo executor; mudar console não comprova diversidade. OpenCode
exige modelo cloud explícito. Padrão desativado; XP precisa estar ativo.

Na seleção dos revisores, aliases conhecidos são tratados como um fornecedor:
OpenAI/Open AI/OpenAI API; Anthropic/Anthropic API; Google/Google AI/Google Cloud/
Vertex AI; NVIDIA/NVIDIA NIM. Espaços, hífens, underscores e caracteres de largura
alternativa desses nomes não criam diversidade. Zen, OpenCode e OpenRouter são
gateways/consoles e não podem identificar, por si só, o fornecedor real do modelo.
Outros fornecedores explicitamente declarados continuam aceitos. Essa normalização
não atesta a origem da inferência; identidade configurada e identidade comprovada
continuam distintas. Relatórios antigos que dependiam de diversidade artificial
de aliases deixam de satisfazer o gate ao serem conferidos.

`python auditor_xp.py --projeto D:/projetos/meu-jogo --seco` mostra candidatos
locais sem inferência/GitHub. Omitir `--seco` consulta e grava os pareceres.
O servidor faz a rodada no intervalo de sugestões, mesmo sem coleta de bots
habilitada, somente com opt-in do auditor. Sem gestão, auditor antigo permanece.
Gestão ativa/inválida exige --projeto na CLI, sem cair no auditor global.

Lê Placar com versão exata e apenas amarelos ainda não conferidos. Obtém PR e
todos os arquivos pela REST, exige patches e contagens completas de linhas.
Diff ausente/binário/truncado ou acima do limite bloqueia consulta; não presume
que testes intactos foram revisados. Documentos canônicos compõem o contexto.
Cada revisor recebe contexto novo idêntico, sem conversa do autor ou respostas
dos outros revisores, pelos adapters isolados sem ferramentas. JSON estrito
exige veredito/motivo/evidência; suspeita exige evidência não vazia.

Registro em dados/gestao/<id>/xp/<hash-repo>/auditor.json guarda SHA/hash do diff,
versão, tentativas/estado e respostas limitadas. Conta antes de consultar, até
duas tentativas por contexto; concluídos não são consultados outra vez. Trava
sem expiração automática impede consultas concorrentes; crash exige inspeção
no PC. Mudança de política/fontes/commit/diff ou conferência humana durante a
consulta impede conclusão válida. Consulta iniciada e interrompida pode exigir
inspeção; recuperação automática do processo ainda não está implementada.

Placar mostra pareceres históricos e o SHA de cada um. Não afirma que o PR
continua nesse commit. Uso informado vai ao ledger como Auditor; cobrança
ausente continua desconhecida. Nenhum parecer marca Conferido, libera vermelho,
cria issue/Kanban ou autoriza merge. São propostas para a conferência humana:
autoria/clouds e evidência nativa ainda precisam ser atestadas para automação
de decisões. Testes simulam clouds e GitHub; não comprovam operação nativa ampla.

## Alertas com identidade do projeto

O detector lê a caixa de sugestões e o Placar locais dos projetos cadastrados
com gestão ativa. Não inicia coleta, GitHub ou inferência. Estado de comparação
é separado por ID do projeto e hash do repo: dois PRs/comentários iguais não
compartilham deduplicação. A primeira leitura só estabelece a base; reiniciar
preserva o estado e não repete avisos. Mudar repo estabelece outra base.

Sugestões P0/P1 e itens novos para conferir/auditoria do Placar entram na fila
existente, com projeto/repo/versão e título identificando o projeto. Placar
exige versão exata da política. Falha de coleta, JSON corrompido ou fonte
indisponível não apagam o estado anterior. Caixa/estado inválidos na gestão
agora falham explicitamente; leitores legados conservam o comportamento antigo.

Clique na fila, toast, notificação ou push seleciona o projeto correspondente
nos PRs/Placar. URL aceita apenas ID opaco de 20 dígitos hex nesses dois painéis.
Filtros por tipo, orçamento de atenção e resumo continuam compartilhados pela
instalação. Fila anterior é preservada como histórico. Cota do GitHub é da conta,
sem atribuição presumida a um projeto.

Com gestão ativa ou política inválida, fontes globais de PRs/XP/eventos/saúde/
escalonamentos não geram novos alertas. Sem gestão, fluxo legacy permanece.
Este passo não implementa alerta de pronto/merge, saúde de agentes, perguntas
ou escalonamentos por projeto; esses exigem evidências específicas ainda pendentes.
Também não liga auditor automático. Alertas do Placar apenas refletem dados já
calculados e válidos. Testes usam entrega simulada e módulos JS reais em VM;
push em aparelho/navegador real continua sem validação nesta etapa.

## Fonte única e compatibilidade

A configuração de gestão pertence ao projeto: `.office/projeto.json`. Use
`projeto.exemplo.json` como ponto de partida, configure o Kanban e habilite `ativo`.
Projetos sem esse arquivo continuam no fluxo existente. O arquivo não altera
workflows, branch protection, conta, assinatura ou configuração nativa dos consoles.

`fontes` referencia as regras, o documento de produto, a arquitetura e as skills.
Cada assunto permanece na sua fonte; entradas dos consoles devem referenciá-la,
sem manter cópias de regras. O nome do arquivo de regras é configurável, podendo
continuar sendo `CLAUDE.md` em projetos existentes. O conteúdo vale para todos os
consoles. `PRODUTO.md` continua sendo a verdade do jogo e o grafo a verdade da arquitetura.

O catálogo comum, a lista de skills do formulário e os links de descoberta Codex
consultam `fontes.skills`, usando a mesma validação de nome/pasta/descrição. Uma
skill inválida não é oferecida como selecionável. Sem política, a fonte permanece
`.claude/skills`. O contexto Codex/Gemini usa as referências configuradas, sem
adicionar arquivos de regras concorrentes como fontes oficiais.

O usuário define objetivos, escopo e limites. O CEO acompanha e delega; o diretor
organiza aceite, dependências e qualidade; equipes representam especialidades.
Console, modelo e localização de execução são atributos separados da equipe.
CEO e diretor não podem modificar a política por conta própria.

## Onde cada informação é oficial

| Assunto | Fonte | Como as demais entradas usam |
|---|---|---|
| Objetivos, aceite e limites aprovados | Usuário e cartão do Kanban configurado | CEO/diretor/equipes respeitam esses limites; registros locais não criam autorização |
| Regras do projeto | Arquivo indicado por `fontes.regras` | AGENTS.md/GEMINI.md e instructions do OpenCode referenciam a fonte; não mantêm outra política |
| Produto e arquitetura | `fontes.produto` e `fontes.arquitetura` | Planos e relatórios citam os documentos; não substituem GDD ou grafo |
| Configuração de gestão | `.office/projeto.json` daquele projeto | Define papéis, executores, rotas, Kanban, revisão, local e opção de merge |
| Configuração nativa | Arquivos e conta de cada console | Permissões/hooks/modelos do Claude não são portados apenas por compartilhar um prompt |
| Skills | Diretório `fontes.skills` | Catálogo e links apontam para os originais, incluindo assets e scripts |
| Operação de gestão | Este guia GESTAO.md | PROVIDERS.md explica os adapters; README encaminha para os guias |
| Contratos técnicos do escritório | SDD.md da versão em uso e código correspondente | Rotas, persistência e flags acompanham a implementação; histórico de versão fica identificado |
| Estado vivo de trabalho | GitHub/Kanban configurado, PR e SHA atual | Reservas e recibos locais comprovam apenas suas etapas, sem substituir aceite/merge |

Relatórios datados, estudos e capturas são evidências históricas. Não devem ser
lidos como uma configuração ativa nem reescritos para fingir que o passado já
seguia a política atual. Uma divergência entre regras vigentes exige conciliação;
nenhum console escolhe sozinho a versão mais conveniente.

A política de gestão não habilita auto-merge no GitHub: workflow, checks e
proteções reais continuam sendo os mecanismos que o executam. Em projeto sem
política de gestão, preserve as regras já vigentes; o padrão manual é para a
configuração nova, não uma migração silenciosa do projeto existente. O projeto de validação
mantém seu auto-merge e exceções merge-manual na fonte de regras do jogo.

Os prompts nativos e launchers Claude do projeto de validação são o fluxo legado específico
da instalação. Sua escolha de nomes/modelos não redefine os papéis configurados
na gestão multi-provider. O usuário continua sendo a autoridade final, mesmo
quando atribui o papel operacional de CEO a um console.

## Selecionar executor

O campo `console` aceita `claude`, `codex`, `opencode` e `gemini`. Um modelo vazio
preserva o padrão do console; fixe um ID permitido na sua conta para uma seleção
reproduzível. OpenCode exige `provider/model`. Rotas por escopo, quando presentes,
prevalecem sobre o executor da equipe. CEO/diretor usam suas próprias configurações.
Escolha indisponível causa erro; não há troca silenciosa de conta/modelo.

```powershell
python console_provider.py --projeto D:/projetos/meu-app --papel ceo --prompt "Avalie os bloqueios atuais"
python console_provider.py --projeto D:/projetos/meu-app --papel diretor --prompt "Prepare o trabalho do próximo marco"
python console_provider.py --projeto D:/projetos/meu-app --equipe Dev --escopo implementacao --prompt "Leia o cartão indicado"
python gestao_cli.py --projeto D:/projetos/meu-app estado
python gestao_cli.py --projeto D:/projetos/meu-app planejar --max-cartoes 10
```

O caminho por CLI do Gemini usa `--output-format stream-json`, conserva permissões
e envia o contexto por stdin para evitar limites da linha de comando no Windows.
O launcher nativo de equipes Claude continua sendo o caminho para teams interativos;
selecionar um papel não converte uma sessão em team. Protocolos de controle mais
completos ainda estão em implementação. O botão Gestão abre a projeção do projeto:
CEO, diretor, equipes, merge, configuração local e tarefas do controle comum. A API
`GET /api/gestao` não retorna prompts, tokens de reserva ou caminhos locais. O painel
consulta somente quando aberto e visível, sem chamadas a modelos.

## Despacho pelo Kanban

### CEO e diretor no fluxo de coordenação

`coordenar` liga os executores CEO/diretor ao lote comum. Forneça uma solicitação
UTF-8 e um plano de candidatos no mesmo formato de `lote`, com cartões existentes
e worktrees próprios já criados. Os modelos podem selecionar/reduzir esses cartões;
não podem acrescentar caminhos, trocar executor, escopo, especialista ou política.
CEO seleciona primeiro; diretor pode reduzir a seleção. Bloqueios ou lista vazia
suspendem o despacho. Prioridade/ordem seguem a política do projeto.

```powershell
# Prévia: valida candidatos e fontes, sem consultar modelos ou mudar cartões.
python gestao_cli.py --projeto D:/projetos/meu-app coordenar --plano lote.json --solicitacao objetivo.txt
# Consulta os modelos configurados nos papéis, sem despacho.
python gestao_cli.py --projeto D:/projetos/meu-app coordenar --plano lote.json --solicitacao objetivo.txt --consultar
# Consulta e despacha somente a seleção pelos gates comuns de lote/revisão.
python gestao_cli.py --projeto D:/projetos/meu-app coordenar --plano lote.json --solicitacao objetivo.txt --executar
```

Cada consulta usa contexto novo e ferramentas negadas pelo adapter isolado. Não é
sessão de team nem permissão de shell para o CEO. Claude/Codex/Gemini/OpenCode
mantêm controles próprios; versão/conta/modelo incompatível causa erro sem fallback.
CEO/diretor locais continuam pelo launcher; esta coordenação estruturada exige cloud.
O normalizador de revisão continua sendo o padrão; coordenação usa outro schema
JSON estrito, sem interpretar resposta como código ou aprovação de revisão.

As fontes regras/produto/arquitetura são lidas da raiz canônica, com limite de
200 mil bytes por arquivo e 250 mil caracteres por prompt; excesso causa erro,
sem truncamento. Ausências são identificadas no contexto. Cartões mantêm aceite,
dependências e skills canônicos; a consulta não ativa skills de execução. O estado
é reconsultado após cada modelo e antes do lote. Mudança em policy/Kanban/branch/HEAD,
fontes ou pacote suspende o fluxo. Gates/travas/revisores comuns continuam na execução.

Consulta produz diagnóstico/seleção em stdout e um `recibo_id` persistente em
`dados/gestao/<identidade>/coordenacao.db`. Guarda hash do contexto, executores
configurados, candidatos, decisões, fases e vínculo com o lote. Não guarda prompts,
corpos dos cartões/documentos ou caminhos de worktrees. Motivos/bloqueios textuais
ficam somente no recibo local; a projeção `coordenacoes` de GET /api/gestao omite
esses textos e o hash, mostrando seleções e contagens no painel Gestão.

Prévia não cria recibo/banco. Consulta registra cada fase antes de chamar o modelo.
Transições e decisões fora de fase são rejeitadas; erro/interrupção registra incerto
quando possível. Falha de persistência impede avanço, e falha no registro final
mantém o último estado para conciliação. Consulta registrada não comprova processo
vivo. Não retoma/reexecuta automaticamente um recibo, e `processado` significa
seleção encaminhada à revisão, sem comprovar aceite ou merge. A leitura mostra dez
recibos recentes por repositório/projeto, é somente leitura e não cria bancos.

No PC, o formulário “Consultar CEO e diretor” recebe o objetivo do marco e os
cartões/worktrees candidatos. POST /api/gestao/coordenar exige projeto registrado,
versão da política, permissão PC e proteção CSRF existente. Retorna 202 com pedido_id;
consulta roda em worker de segundo plano, sem despachar a seleção. O usuário pode
fechar o formulário e atualizar Gestão para ver pedidos e recibos. Custo/cota da
consulta depende dos modelos configurados, e falhas não trocam conta/modelo.

Pedidos ficam em pedidos_coordenacao.db próprio por projeto, sem objetivo
ou caminhos. A seleção organizada também guarda um plano privado em
planos_coordenacao/<recibo_id>.json, com caminhos e snapshots dos candidatos
selecionados. Esse arquivo não é servido pelo painel nem incluído no pacote.
Um pedido do painel por vez neste processo; pedido persistente
recebida/consultando/executando/incerto impede outro
consulta do painel naquele projeto/repo. Após reiniciar, sem thread acompanhada,
pedido pendente é exibido como incerto, sem inferir que o modelo terminou. Exige
conciliação no PC, sem limpar/retomar automaticamente. CLI permanece independente.
Concluída indica retorno do worker; confira a fase do recibo e o resultado do lote.

No PC, uma seleção organizada com plano persistido oferece “Executar seleção”.
POST /api/gestao/coordenacao/executar recebe somente projeto_id, versao, recibo_id
e plano_sha256. O worker verifica hash, política, Kanban, aceite e worktrees,
obtém o claim transacional e usa o lote comum. Não reconsulta CEO/diretor.
Recibos históricos sem plano continuam visíveis, sem botão de execução.
Alteração de qualquer snapshot exige nova consulta; não executa um plano editado
pelo navegador. O lote pode mover cartões para revisão; processado não significa
aprovação, Feito ou merge. Não cria issues, equipes ou worktrees.
Pedidos incertos oferecem “Conferir retorno” no PC. A prévia de
POST /api/gestao/coordenacao/conciliar só permite confirmar se a consulta tem
decisão conclusiva, ou se o despacho tem recibo e lote finais correspondentes,
sem cartões pendentes no lote. A confirmação revalida a evidência/hash e encerra
somente o acompanhamento do pedido. Não libera reservas, mata processos,
reexecuta modelos ou muda Kanban. O vínculo da consulta é gravado antes da
primeira inferência; erros o preservam. Pedidos históricos sem tipo/vínculo,
recibos incertos e execuções sem retorno continuam bloqueados para inspeção no PC.
Retomada de agentes, conciliação de reservas/processos e cobrança real continuam
em implementação. Nenhuma ausência de thread/PID ou prazo autoriza liberar reserva.

Consultas nativas do CEO/diretor, pela CLI ou painel, alimentam consumo_providers.db
da instalação nos papéis CEO e Diretor. Codex/Gemini/OpenCode usam seus contadores
normalizados existentes. O transporte observa envelopes antes de rejeitar exit
não zero ou resposta inválida; contadores disponíveis permanecem observados, sem
aprovar o plano. Timeout/conexão sem stdout válido ficam sem observação, não zero.
Falha de telemetria não modifica a resposta do modelo.

Claude dessas consultas exige UUID novo explícito, sem resume/continuação e sem
ferramentas. Só modelUsage do result principal da sessão esperada entra, por modelo
informado. Entrada inclui inputTokens + cacheReadInputTokens + cacheCreationInputTokens;
cache mostra somente leitura, já incluída na entrada. Saída usa outputTokens final,
sem somar placeholders dos assistant. Snapshot repetido não duplica, snapshot menor
não rebaixa e erro com contadores zerados não vira gasto zero. Falta de campos fica
sem observação. O launcher Claude/team anterior não recebe essa regra, pois resultados
retomados podem acumular histórico: [contrato oficial](https://code.claude.com/docs/en/agent-sdk/cost-tracking).

Claude e OpenCode continuam sem cálculo monetário por token nesta integração;
criação de cache tem preço próprio não normalizado separadamente aqui. Codex/Gemini
só recebem equivalente teórico quando há modelo informado pelo console, tarifa
válida e cobertura completa. Modelo configurado não é automaticamente informado.
Não utiliza total_cost_usd/costUSD como fatura nem converte tokens em cota semanal.
No OpenCode, CEO/diretor exigem modelo cloud explícito; nomes local/ollama/lmstudio
e declaração cloud=local são recusados, sem iniciar o padrão local fora dos gates.
Isso não atesta o backend de providers personalizados; essa verificação permanece
pendente.

```powershell
# Prepara o pacote e consulta o quadro; não despacha nem muda o status.
python gestao_cli.py --projeto D:/projetos/meu-app despachar --cartao 42 --equipe Dev
# Executa em worktree limpa, no mesmo repositório e em branch próprio.
python gestao_cli.py --projeto D:/projetos/meu-app despachar --cartao 42 --equipe Dev --worktree D:/worktrees/tarefa-42 --executar
```

O cartão deve ser uma issue aberta no Backlog, com Time correspondente à equipe
e **Aceite:** no corpo. **Objetivo:**, **Escopo:** e **Skills:** refinam o pacote.
O gate consulta também as relações nativas **blocked by** do GitHub e o campo
opcional `**Dependências:**`. Liste `#41`, `owner/repo#41` ou URLs de issue/PR no
github.com, separados por vírgula, ponto e vírgula ou linhas. Checkbox é apenas
formatação, não prova conclusão; use `nenhuma` quando não houver referência textual.
Referências nativas continuam sendo verificadas mesmo com `nenhuma` no corpo.
Texto ambíguo, campo vazio/duplicado, autodependência ou referência transferida
exigem conciliação. URLs arbitrárias não são consultadas.

Uma issue dependente deve estar fechada com `state_reason=completed`. Cancelamento
(`not_planned`) ou motivo ausente não liberam trabalho. PR dependente exige merge
confirmado e SHA de merge completo; fechar um PR não basta. A evidência e a data
de consulta ficam no pacote da reserva, sem copiar corpos de dependências. As
releituras aprovadas ficam em `dependencias_verificadas`, por fase: antes da execução,
entrega e após revisão. Falhas não são registradas como verificação aprovada. Esse
estado do GitHub comprova encerramento declarado, não a qualidade do código.
O gate reconsulta antes de mover o cartão/iniciar o executor, na entrega e depois
da revisão cruzada. Reabertura ou mudança de referências bloqueia o fluxo. Falha
na leitura de dependências não é interpretada como lista vazia. O endpoint exige
acesso de leitura a Issues, além de Projects:
[API oficial de dependências](https://docs.github.com/en/rest/issues/issue-dependencies).
O despacho exige leitura atual por REST; falha de rede não libera trabalho a partir
de cache velho. Consultas de diagnóstico usam cache de até dez minutos. Não usa
GraphQL nem cria campos/projetos automaticamente.

`controle_tarefas.py` mantém reservas transacionais em SQLite separado do banco
de telemetria: `reservado → executando → revisao → concluido`, com estados
`bloqueado` e `cancelado`. Um segundo despacho do mesmo cartão é rejeitado.
Reservas não expiram automaticamente. IDs de sessão pertencem ao console original.
O banco fica em `dados/gestao/<identidade-do-projeto>/tarefas.db` na instalação.
Esta exclusão é local à instalação: outra máquina precisa usar a mesma autoridade
de despacho; o GitHub Projects não fornece uma operação compare-and-swap de cartão.

Saída zero do console não comprova entrega. Só passa a revisão quando existe PR
aberto, não rascunho, do branch da execução e com `Closes #42` ou `Parte de #42`.
Sem isso, ou diante de falha, a reserva fica bloqueada para conciliação. O fluxo
não fecha a issue nem marca Feito automaticamente; revisão/merge devem ser verificados.
O vínculo de sessões está descrito na seção de sessões nativas; retomada automática ainda está pendente. A verificação de dependências
está ligada ao despacho; sua conciliação e o controle distribuído continuam pendentes.

### Diagnóstico do diretor

`planejar` lê o Backlog do Kanban atual, as reservas locais e as dependências,
retornando `preparavel` ou um bloqueio por cartão, além dos executores de CEO/diretor.
Não chama modelos, reserva, altera cartões ou rouba tarefas em andamento. Usa uma
fotografia atual do board e consulta issues/dependências ao vivo. Avalia até dez
cartões por padrão (limite de vinte); `nao_avaliados` e `proximo_cartao` indicam a
cobertura restante. Continue com `--apos-cartao <proximo_cartao>`. Sem ordem
configurada, mantém a ordem por número de issue. Com `kanban.prioridades`, usa
a lista aprovada do projeto, desempata pelo número e continua depois do cartão
na ordem atual, inclusive quando o próximo número é menor. Não decide novas
prioridades em nome do CEO.
Uma indicação preparável é diagnóstica, não autorização ou reserva: o despacho
revalida tudo e exige uma worktree separada. Alteração concorrente depois da última
leitura não é uma transação atômica com GitHub; Projects não oferece esse contrato.

É possível passar o diagnóstico ao console definido para o CEO ou diretor:

```powershell
python gestao_cli.py --projeto D:/projetos/meu-app planejar --max-cartoes 10 | Set-Content -Encoding utf8 ./diagnostico.json
python console_provider.py --projeto D:/projetos/meu-app --papel diretor --prompt-arquivo ./diagnostico.json
```

`--prompt-arquivo` lê UTF-8/BOM e aceita até 128 mil caracteres, sem truncar nem
interpretar o conteúdo pelo shell. Substitui `--prompt`; os dois não se combinam.
Enviar ao console inicia inferência e preserva suas permissões nativas. O relatório
nunca inicia esse passo por conta própria. Controle completo de CEO/diretor,
mudanças de prioridade pelo CEO e retomada continuam em desenvolvimento. Lotes explícitos sequenciais e paralelos são descritos nas seções de lotes abaixo.
Testes: `testar_dependencias_tarefas.py`, `testar_diretor_tarefas.py`,
`testar_gestao_kanban.py`, `testar_despacho_revisao.py` e `testar_providers.py`.

## Merge e recursos locais

### Revisão cruzada entre clouds

`revisao` configura revisores separados por fornecedor real do modelo. Por padrão,
quando habilitada, exige dois fornecedores distintos entre si e diferentes do autor.
Trocar Claude por OpenCode usando um modelo Anthropic não conta como diversidade:
para OpenCode, declare `cloud` do modelo. Os consoles nativos inferem Anthropic,
OpenAI ou Google; a configuração declara a origem e deve refletir o backend real.

Cada revisor recebe o mesmo commit, diff, aceite e regras, em contexto novo, sem
a conversa do autor e sem os achados do outro revisor. A execução de revisão deve
ser somente leitura. Falha, resposta inválida, divergência ou P0/P1 bloqueiam o gate;
maioria de aprovações não descarta achado grave. O relatório só vale para o SHA
completo e a política que o produziram. Novo commit ou mudança de política exige
nova revisão. Isso complementa testes e portões de arquitetura, sem garantir a
eliminação de alucinações ou de erros correlacionados.

O coordenador `revisao_cruzada.py` e o gate de elegibilidade estão implementados;
os executores nativos isolados agora estão conectados via gestao_cli.py revisar. A publicação no fluxo de checks ainda será
conectada. O check `revisor-ia` existente e o auto-merge dos projetos legados permanecem
intactos durante essa integração. Teste: `testar_revisao_cruzada.py`.

Merge manual é o padrão de projeto novo. `merge.modo: automatico` exige lista
explícita de checks; `merge-manual` força tratamento humano. A decisão de elegibilidade
não executa merge nem substitui a proteção do GitHub. O projeto legado mantém seu workflow
atual; checks condicionais, como o build C++, permanecem responsabilidade dele.

O foco é cloud. Local vem desativado. No perfil simples, somente o escopo `simples`
é elegível e há uma execução por vez; `team: true` permite configurar paralelismo
para máquinas capazes. `recursos_local.py` mede CPU, RAM, processos, modelos residentes
Ollama e GPU NVIDIA quando disponível, e reserva vagas
globalmente na instalação. Unreal, compilação, shaders e qualquer Blender bloqueiam
admissão quando `bloquear_pesados` está ligado. Falta de medição também bloqueia.
O executor local está conectado ao launcher com admissão e watchdog. CEO/diretor
locais exigem local ativo e Team local explícito; não usam o perfil simples.
Validação de inferência local real e suporte de medição para outras GPUs ainda estão pendentes.

## Pesquisa usada e validação

### Limite semanal GPT/Codex

O Placar existente inclui uma seção de cotas por fornecedor (`indicadores_providers.mjs`), consultada apenas com o painel aberto e a aba visível. Consulta `GET /api/uso/providers`: o App Server do Codex fornece
`account/rateLimits/read` por stdio, com a autenticação existente do CLI. A leitura
não executa modelos, não inicia login, não consome reset e não solicita compra de
créditos. Cache de cinco minutos evita consultar em cada atualização do painel.
O transporte genérico é `rpc_console.py`; a normalização/cache é `uso_providers.py`.
Validação real somente de leitura passou com Codex 0.158.0 nesta instalação.

Múltiplas cotas são preservadas. A janela é identificada como semanal pela duração
de 10080 minutos; não se presume que `primary` e `secondary` têm duração fixa.
O painel mostra usado, restante, renovação e data da coleta. Campo ausente fica
indisponível; reset passado não vira uso zero. Falha de atualização mantém a leitura
anterior explicitamente desatualizada. A conta do CLI pode diferir da conta do app.

Percentual da assinatura é separado de dinheiro. Métricas por token/modelo e preços
com origem e data ainda serão integrados; valores estimados deverão ser identificados,
sem apresentar equivalência de API como cobrança real da assinatura.

### Kanban único no painel e no despacho

Com a gestão ativa, `GET /kanban` consulta `.office/projeto.json` dos projetos
registrados no escritório. Um único projeto é selecionado automaticamente;
havendo vários, o painel exige selecionar um, usando seu ID público em
`GET /kanban?projeto=<id>`. A seleção é desta página, sem modificar configuração
global. O servidor só aceita projetos registrados; não aceita caminhos do navegador.
Status, Time e colunas vêm da política. Issues/PRs de outros repositórios em um
board compartilhado não aparecem nessa vista; rascunhos pertencem ao board.

Painel e despacho usam o mesmo `dados/gestao/<id>/kanban.json`; uma mudança de
status pelo despacho invalida esse cache. A leitura REST solicita explicitamente
os IDs dos campos (sem isso, o GitHub retorna apenas o título) e usa `gh api
--paginate --slurp` para seguir os cursores no Link, conforme a
[API oficial de itens de Projects](https://docs.github.com/en/rest/projects/items).
Política inválida, seleção desconhecida ou erro de acesso não redirecionam a
consulta ao board legado. Projetos sem gestão ativa mantêm o fluxo anterior.
Na dev, a Saúde usa somente cache válido, sem aguardar a rede; o laço do Kanban
renova a projeção ativa. Os caches legados ficam separados. Na pública, a Saúde
só combina os cartões da política com PRs legados quando o repositório coincide.

O painel de PRs, checks legados, XP e ações de saúde ainda usam sua configuração
anterior; a seleção do Kanban não muda esses serviços nem as regras de auto-merge.
A adoção da política no jogo e a gestão completa desses serviços por projeto
continuam pendentes. Testes: `testar_kanban_painel.py`, `testar_kanban_projetos.mjs`
e `testar_gestao_kanban.py`, nas pastas de testes de cada edição.

### Requisitos adicionais aprovados

- Formulário no escritório para cadastrar funcionários/especialistas, especialidade,
  equipe, console, modelo, skills e permissões; gerar agentes compatíveis sem duplicar
  as regras e sem substituir agentes personalizados existentes.
- Instalador guiado para detectar consoles, runtimes e recursos; configurar novos
  projetos e explicar autenticação/dependências faltantes; conservar instalações existentes.
- Painel por modelo/console/agente/tarefa com tokens, custos informados ou estimados,
  preços com fonte/data, uso semanal e métricas de qualidade/tempo/retrabalho.
- Revisores em clouds diferentes do autor e entre si, com contextos independentes,
  achados verificáveis e gates vinculados ao commit exato.

Estes requisitos fazem parte da entrega em andamento, não são recursos concluídos
apenas pela presença da política ou do painel de leitura.

Capacidades são verificadas por versão, não presumidas por marca ou preço. Paridade
de modelos será calibrada por planejamento, implementação, revisão e tarefas simples,
medindo qualidade, retrabalho, duração e consumo. Não há equivalência automática
entre famílias nem teto financeiro presumido como aprovado.

Fontes oficiais: [Claude teams](https://code.claude.com/docs/en/agent-teams),
[Codex App Server](https://developers.openai.com/codex/app-server),
[OpenCode server](https://opencode.ai/docs/server/),
[Gemini ACP](https://geminicli.com/docs/cli/acp-mode/),
[Gemini headless](https://geminicli.com/docs/cli/headless/) e
[OpenCode com Ollama](https://docs.ollama.com/integrations/opencode).

Testes sem modelos/rede: `testar_gestao_projeto.py`, `testar_controle_tarefas.py`,
`testar_gestao_execucao.py` e `testar_gestao_kanban.py`. Execute em `ferramentas/`
na edição pública ou `testes/` na dev. Cobrem política por projeto, merge, reservas
concorrentes, persistência, roteamento, Gemini, recursos, REST/cache e evidência de PR.

### Consumo observado por modelo

`consumo_providers.py` recebe a saída JSON do launcher comum, sem executar modelos
adicionais. Persiste em `consumo_providers.db`, ao lado do banco do feed, sem prompts
nem credenciais. A tabela `consumo` contém chave idempotente, data, console, modelo,
origem do modelo, agente, hash do projeto, sessão, fonte e contadores. O painel recebe
somente agregados dos últimos sete dias por console/modelo/agente; IDs de sessão e
hashes/caminhos dos projetos não são expostos.

Codex `turn.completed/usage`: entrada inclui cache, total é entrada + saída;
modelo indicado por flag fica rotulado como configurado, não confirmado pelo evento.
Gemini `result/stats.models`: cada modelo informado tem sua própria amostra; o total
reportado é preservado (pode incluir pensamento) e o agregado geral não é somado
novamente. Registro repetido na mesma execução atualiza a mesma amostra; retomada
em nova execução registra novo consumo. Uma execução Codex exec fornece um turno.
Campos inválidos/ausentes são desconhecidos, com cobertura parcial explícita.

A visão geral do Placar soma somente tokens observados na mesma janela de sete
dias, separando cloud e local, e mostra quantas amostras forneceram cada contador.
O detalhamento por console/modelo/agente permanece disponível. Cache já incluído
na entrada não é somado novamente; ausência não vira zero. Esses totais não
representam todo o consumo das contas nem medem eficiência: cada modelo pode
usar um tokenizador diferente. Percentuais e renovação dos planos continuam em
seções próprias de cada fornecedor; não há percentual consolidado entre contas.
Custo monetário real e tempo por tarefa ainda não estão disponíveis nesta visão.

Coleta estruturada Codex/Gemini e OpenCode via `console_provider.py`, plugin
OpenCode e observação Codex estão descritos abaixo. A união com custos históricos
do Claude ainda precisa de ledger incremental validado. Cobrança real permanece
indisponível; o detalhamento agora calcula equivalente teórico de API opcional para
Codex/Gemini com modelo informado e contadores completos. Configure tarifas em
`dados/precos_tokens.json` conforme README e SDD. Sem tarifa válida para a data da
amostra, o valor fica desconhecido. A assinatura não é precificada como API.
Teste: `testar_consumo_providers.py`; o teste HTTP verifica também a exposição sanitizada.
Fontes: [Codex JSONL](https://learn.chatgpt.com/docs/non-interactive-mode),
[Gemini headless](https://geminicli.com/docs/cli/headless/) e o formatter da instalação
Gemini CLI 0.59 (`convertToStreamStats`, validado sem executar inferência).
Codex TUI e filhos iniciados pelo launcher também são medidos pelo observador passivo. Usa turn_context/model e event_msg/token_count/info.total_token_usage, verificados em transcritos desta instalação. A tabela saldo_codex guarda referência por projeto/sessão; transação atômica grava apenas incrementos, mesmo com observadores concorrentes. Na retomada, até 16 MB da cauda existente prepara a referência sem republicar eventos ou cobrar histórico. Se não encontrar referência válida, o primeiro contador futuro vira baseline. Contadores regredidos/correções inconsistentes não geram consumo negativo. No modo JSON, o pai é medido pelo stream e só os filhos pelos rollouts, evitando dupla contagem. O consumo mostra apenas períodos observados; coleta não é importação retroativa de todas as sessões do PC.

### Executar revisão independente de commit

```
python gestao_cli.py --projeto D:/projetos/meu-app revisar --worktree D:/worktrees/tarefa-42 --base origin/main --equipe Dev --aceite D:/projetos/meu-app/aceite.txt
python gestao_cli.py --projeto D:/projetos/meu-app revisar --worktree D:/worktrees/tarefa-42 --base origin/main --equipe Dev --aceite D:/projetos/meu-app/aceite.txt --executar
```

Sem `--executar`, apenas prepara diff/aceite/regras e revisores da política. Execução
usa commit íntegro numa branch de trabalho limpa, compara base e HEAD, e exige linhas
dos achados no lado novo do diff. Não trunca diff/contexto grande: a rodada falha.
Cada console recebe stdin em pasta temporária nova, sem retomada de conversa.
Na nova versão, Claude usa safe-mode/sem ferramentas/MCP estrito; Codex ignora config e regras do usuário,
usa sandbox read-only e desliga hooks/plugins/apps/delegação/shell/browser.
Gemini desliga MCP/extensions/skills/hooks por configuração de sistema temporária e
nega ferramentas por política Admin. A memória usa nome de arquivo exclusivo,
sem diretórios adicionais; variáveis de override de system prompt são removidas
somente do ambiente do revisor. A checagem de confiança da pasta é desativada
somente nesse processo, na pasta temporária vazia criada pelo adapter: isso evita
que uma revisão sem ferramentas exija cadastrar Temp como confiável. Não altera
trustedFolders.json, autenticação, configurações globais ou o launcher normal.
Exige init com sessão/modelo, mensagens da mesma sessão quando identificadas e
um único result success sem erro. Ferramenta, evento desconhecido, conclusão
repetida/ausente ou evento após conclusão bloqueia. OpenCode usa pure/agente temporário com deny,
desliga MCP por nome e verifica a configuração resolvida antes de inferência.
Flags ausentes, erro, JSON inválido ou tentativa de ferramenta invalidam o resultado.
Não há bypass de aprovação/sandbox. Os CLIs ainda mantêm suas autenticações e estado
próprios; esta camada não cria login nem replica credenciais.

`revisao_execucao.py` salva o relatório por SHA em dados/gestao/<projeto>/revisoes;
confere novamente commit/contexto/política antes de salvar. Relatório reprovado sai
com código 1 no CLI. Não publica comentários/status no GitHub nem executa merge.
A revisão está conectada ao despacho quando revisao.ativo é true. A publicação em checks GitHub permanece pendente; o auto-merge existente é preservado.

Validação: adapters dos quatro consoles simulados e Git temporário real (aprovação,
linha inventada, alteração concorrente). Preflight real OpenCode confirmou negação
normalizada de permissões. Codex gpt-6-sol executou revisão real do exemplo com bug
aritmético, sem ferramentas, e apontou corretamente o P1. Claude bare anteriormente
retornou “Not logged in” porque esse modo não carrega OAuth. O adapter novo exige
safe-mode, disponível no CLI 2.1.296 validado, e preserva a autenticação normal.
O teste nativo confirmou login claude.ai, tools vazio e zero MCP; a chamada terminou
com erro (429/credit), sem revisão aprovada. Revisão aceita pelo Claude e inferência
real Gemini/OpenCode continuam pendentes. Não troca conta/modelo para contornar falhas.
Na tentativa Gemini mais recente, o contexto temporário inicialmente foi recusado
com exit 55 (FatalUntrustedWorkspaceError no CLI instalado). Após a correção
limitada ao contexto de revisão, a autenticação atual retornou IneligibleTierError
com UNSUPPORTED_CLIENT para Gemini Code Assist individual; nenhuma resposta/modelo
ou contagem de tokens foi aceita. Isso descreve a tentativa nesta máquina, não
prova indisponibilidade de todos os métodos/contas Gemini. Não migrou conta,
cliente, tier ou credenciais automaticamente. Disponibilidade de outros métodos
deve ser conferida no console pelo usuário, conforme sua conta e política de custo.

FalhaRevisor expõe somente motivo enumerado e exit code, sem stderr, credenciais
ou paths. O relatório cruzado conserva esse diagnóstico e permanece reprovado:
cliente_nao_suportado, workspace_nao_confiavel, limite_ou_credito,
autenticacao_indisponivel ou console_falhou. Ausência de estatística continua
desconhecida; não vira custo zero. conferir rejeita registros com erro/falha_console
ou aprovado diferente de true, mesmo que contenham uma resposta JSON positiva.
Políticas administrativas gerenciadas ainda se aplicam em safe-mode. Versão sem
safe-mode bloqueia revisão em vez de reduzir o isolamento. O stream exige init com
tools vazio e resultado principal bem-sucedido da mesma sessão; tentativa de
ferramenta, resultado repetido ou ausência de conclusão bloqueia aprovação.
Fontes Claude: [CLI](https://code.claude.com/docs/en/cli-reference) e
[headless](https://code.claude.com/docs/en/headless).
Fontes: [Gemini Policy Engine](https://geminicli.com/docs/reference/policy-engine/),
[configuração Gemini](https://geminicli.com/docs/reference/configuration/) e
[stream headless](https://geminicli.com/docs/cli/headless/),
[OpenCode permissions](https://opencode.ai/docs/permissions/) e
[OpenCode config](https://opencode.ai/docs/config/).
### Revisão no despacho e projeção do escritório

Com `revisao.ativo: true`, a entrega do despacho precisa ter PR aberto e não rascunho,
head igual ao HEAD local e base SHA disponível no Git local. A revisão usa o merge-base
para representar o diff do PR. Depois das chamadas, revalida head/base/número do PR,
HEAD/branch/status local limpo, política, Time/Status do Kanban e as instruções da issue aberta (objetivo, aceite, escopo e skills).
Mudanças invalidam a rodada. Reprovação/erro dos revisores mantém estado local bloqueado
(o cartão não é movido para Em revisão). Aprovação salva a evidência na tabela `entrega`
do banco de tarefas e move para Em revisão; nunca marca Feito, publica comentário ou faz merge.
O CLI retorna 1 para entrega bloqueada, mesmo se o implementador terminou com zero.

Após merge real, `python gestao_cli.py --projeto PROJETO concluir --cartao N --pr N`
mostra a prévia sem escrever. Repetir com `--executar` exige reserva em revisão,
PR fechado e mergeado no repositório e branch vinculados, vínculo `Closes`/`Fixes`/
`Resolves` ao cartão inteiro, política e instruções preservadas e
checks obrigatórios aprovados no head exato. Com revisão ativa exige a entrega
aprovada e vinculada ao mesmo PR/head; com revisão desativada não exige revisores.
O comando registra evidência local, fecha a issue se ela ainda estiver aberta,
move para Feito e marca a reserva concluída. O fechamento explícito é necessário
quando o GitHub não aplica `Closes` por a base não ser a branch padrão. Não fecha
cartão-pai com vínculo parcial `Parte de`.
Se a escrita local falhar após o movimento remoto, a próxima execução concilia
a evidência já registrada. Não realiza merge nem publica checks.

**Entrega concluída exige merge confirmado.** PR aberto, autor encerrado e revisão
aprovada são etapas intermediárias. No ciclo com merge automático, a coordenação
confere os PRs dos despachos confirmados da própria sessão antes de replanejar.
Só encaminha a conclusão pelo mesmo comando e seus gates após comprovar o merge.
O vínculo ao token e worktree novo é privado; não entra no resumo público nem
altera recibos dos lotes. Reservas históricas, bloqueadas ou sem vínculo desta
sessão ficam fora. Falha de conclusão fica registrada para intervenção, sem
repetição automática; PR ainda aberto permanece em revisão. Projetos com merge
manual preservam a conclusão explícita pelo comando acima.

O painel Gestão mostra a última revisão, PR e SHA, sem expor relatório/prompt/token da
reserva. Isso é histórico do commit exibido, não autorização atual de merge. Nenhum
percentual da conta e nenhum bool enviado pelo revisor substitui o gate de commit/política.
Bancos antigos sem a tabela entrega continuam legíveis. A reserva/transação é local a
esta instalação; ainda não constitui trava distribuída entre computadores. Os checks
GitHub e a retomada/conciliação das tarefas continuam parte da implementação pendente.
Testes: `testar_despacho_revisao.py` (aprovação, reprovação, head divergente, mudança de
PR/aceite e projeção sanitizada), além dos testes de Git/revisores e regressão do despacho.
### Rotas locais com proteção de recursos

`executor_local.py` conecta as rotas `execucao: local` a Ollama no endereço fixo
127.0.0.1:11434. Exige nome explícito de modelo já instalado, geração e formato GGUF
identificado por /api/show. Recusa nomes cloud e metadados remote_host/remote_model.
Não baixa modelo, inicia servidor, altera configuração do usuário ou usa cloud como
fallback. Gemini local ainda é recusado; esta camada não presume suporte Ollama nele.

Exemplo de rota no projeto (mesclar na política existente):

```json
{"local":{"ativo":true,"team":false,"max_paralelo":1,"ram_livre_min_gb":8,"bloquear_pesados":true,"cpu_uso_max_pct":75,"ollama_memoria_max_gb":4,"vram_livre_min_gb":2,"gpu_uso_max_pct":75},
 "rotas":{"simples":{"console":"codex","modelo":"qwen3.5:4b","execucao":"local"}}}
```

```
python console_provider.py --projeto D:/projetos/meu-app --escopo simples --prompt "Resuma o critério de aceite informado"
```

Codex usa --oss/local-provider ollama e configuração ignorada só nesta execução;
subagentes nativos ficam desligados e TUI local gerenciada ainda não está conectada.
OpenCode recebe provider OpenAI-compatible exclusivo via config inline, sem escrever
opencode.json. Claude recebe endpoint/token local e bare, preservando permissões;
seus hooks nativos não rodam nesse modo. Claude local com prompt usa os eventos
do stream comum; a TUI local gerenciada e o observador do console_local legado
ainda não foram unificados. Claude cloud usa o adapter padronizado da nova linha.

A reserva SQLite é comum a todos os projetos desta instalação; respeita o menor
limite das reservas ativas. CPU/RAM/processos são medidos antes e a cada dois segundos
na execução. CPU acima de local.cpu_uso_max_pct (75 por padrão), Unreal/Blender/build
ou medição inválida interrompem somente a árvore
deste console. Não mata o servidor Ollama global nem descarrega modelos usados por
outros clientes. Modelos residentes no Ollama podem manter RAM/VRAM ocupada após
a interrupção. `memoria_local.py` consulta GET /api/ps no loopback, sem proxy ou
redirecionamento: soma a memória de todos os modelos residentes, inclusive os de
outros clientes, e bloqueia acima de `ollama_memoria_max_gb` (4 GiB por padrão).
Não desconta esse total novamente da RAM livre: a medição do sistema já considera
os residentes. `size_vram` é parte de `size`, não um custo adicional somado.

GPU NVIDIA é medida por nvidia-smi, somente leitura, sem instalar driver ou ajustar
a placa. Todas as placas reportadas precisam ter ao menos `vram_livre_min_gb`
(2 GiB) e uso de até `gpu_uso_max_pct` (75). Ausência de nvidia-smi só permite
admissão enquanto /api/ps informa zero VRAM residente; uma execução que passe a
usar VRAM sem medição será interrompida na próxima amostra. AMD, Intel, Apple e
memória unificada ainda não têm medição dedicada. Erro de driver, N/A ou dados
inconsistentes bloqueiam a execução. Sem Ollama acessível ou sem memória declarada
por /api/ps também não há admissão. Os três limites novos são inteiros positivos
na política do projeto; os limites de memória aceitam de 1 a 1024 GiB e o de uso
de GPU de 1 a 100 por cento. Não há seleção automática da placa mais livre.

Essas leituras não estimam antecipadamente a alocação do próximo modelo ou de seu
contexto; a carga pode ultrapassar um teto entre amostras. Não garantem liberação
de memória pelo Ollama após encerrar o console. A CPU usa duas leituras separadas
por 250 ms; não prevê carga futura. Windows com mais de 64 processadores bloqueia local
por medição CPU ainda incompleta entre grupos. Não é garantia de memória disponível para
um jogo após a interrupção. Team local permite trabalhadores gerenciados em paralelo
quando explicitamente habilitado; não promete equivalência de teams nativos entre CLIs.

O perfil simples rejeita prompts maiores que 16 mil caracteres, sem truncar regras.
Codex local não recebe automaticamente o catálogo inteiro de skills: lê somente a
skill pertinente indicada pela fonte da política. Os eventos/consumo local ficam
identificados com sufixo _local, separados de consumo cloud e de cotas da assinatura.
Contextos longos de Codex/OpenCode normalmente exigem 64k+, conforme documentação
Ollama; isso pode inviabilizar esses consoles na máquina fraca. Priorize cloud para
o jogo e mantenha local opt-in para tarefas pequenas.

Fontes: [modelos residentes Ollama](https://docs.ollama.com/api/ps) e
[consulta GPU NVIDIA](https://docs.nvidia.com/deploy/nvidia-smi/index.html).

Testes simulam configuração, modelos remotos, RAM, exclusão entre projetos e
interrupção da árvore correta. O preflight real nesta máquina retornou Ollama
indisponível (URLError); não foi iniciada inferência nem servidor para contornar isso.
Fontes: [Ollama/Claude](https://docs.ollama.com/integrations/claude-code),
[Ollama/Codex](https://docs.ollama.com/integrations/codex) e
[Ollama/OpenCode](https://docs.ollama.com/integrations/opencode).

## Cadastro de especialistas

Em Gestão → Cadastrar especialista, escolha nome, função, equipe existente na
política, console, modelo e skills da fonte compartilhada. Para OpenCode cloud,
declare o fornecedor real do modelo; o console não identifica a cloud. Local
exige habilitação na política e modelo instalado. Gemini local não tem adapter.
O cadastro é permitido somente no PC, não inicia inferência e não muda os agentes
nativos existentes. Permissões são herdadas do console e da política do projeto.

O registro fica em `.office/funcionarios.db`, separado da política e da persistência
legada. Skills continuam referenciados, sem cópia. O painel mostra o identificador
para executar a função cadastrada:

```
python console_provider.py --projeto D:/projetos/meu-app --funcionario ID --prompt "Tarefa com critério de aceite"
```

O launcher valida equipe/skills ainda disponíveis, política ativa e console/modelo
consistentes. Uma identidade estável separa seus eventos e consumo dos agentes
legados e de funcionários com nome igual em outros projetos; a interface mostra
o nome do cadastro. Cadastro e execução são separados da geração explícita de perfis nativos descrita abaixo. Cadastro e execução
são etapas distintas. Para trabalhar em um cartão do Kanban com o especialista:

```
python gestao_cli.py --projeto D:/projetos/meu-app despachar --cartao 42 --equipe Dev --funcionario ID
python gestao_cli.py --projeto D:/projetos/meu-app despachar --cartao 42 --equipe Dev --funcionario ID --worktree D:/worktrees/tarefa-42 --executar
```

O primeiro comando prepara; o segundo reserva o cartão e executa no worktree limpo.
A raiz do worktree deve ser um checkout separado do projeto principal, no mesmo
repositório. Mesmo que esteja limpo e em branch de feature, o checkout principal
não é aceito para novos despachos/revisões; subpastas não contornam essa regra.
Além da reserva por cartão, o despacho ocupa o worktree de forma transacional
antes de reservar/mover/executar. A trava fica em `office-execucoes.db` no diretório
Git compartilhado, fora dos arquivos versionados; instalações pública/dev e
worktrees do mesmo repositório compartilham essa trava. Um segundo cartão não
pode iniciar no checkout ocupado. O despacho confere novamente se o worktree está
limpo após adquirir a trava. Saída normal libera somente a própria ocupação;
queda/erro inesperado mantém a trava para conciliação. Prazo vencido ou PID ausente
não autoriza roubar a ocupação: o console e suas ferramentas podem sobreviver ao
controlador. A conciliação/retomada completa com prova dos processos ainda está
em implementação; não apague o banco para contornar uma execução incerta.

Em despacho estruturado, a sessão principal observada de Codex, Gemini ou
OpenCode é vinculada à reserva e aparece no painel de tarefas. A identificação
é comum à telemetria e ao controle: `thread.started` no Codex, `init` no Gemini
e `sessionID` externo dos envelopes conhecidos do OpenCode. IDs de filhos e
tipos desconhecidos não substituem o vínculo. Uma nova sessão divergente ou
console diferente bloqueia o vínculo; falha de persistência não é ignorada como
falha opcional de telemetria. O caminho local usa o mesmo vínculo quando há stream.
Na versão nova, Claude com prompt usa `-p --verbose --output-format stream-json`.
A sessão principal é vinculada pelo envelope `system/init`; envelopes de filhos
não substituem essa identidade. Mensagens e ferramentas completas são convertidas
para os eventos comuns, com deduplicação e identificação do funcionário responsável.
Sem prompt, a TUI mantém o comando nativo. O observador passivo permanece disponível
para compatibilidade histórica, mas não concorre com o stream gerenciado.
Ausência de ID não cria um ID fictício nem autoriza retomar outra sessão. Este registro ainda não oferece
retomada automática de cartão: exige conciliar execução, branch, aceite e quadro.
Formato do Gemini: [modo headless](https://geminicli.com/docs/cli/headless/).

A equipe deve coincidir com o cadastro e com o campo Time. A reserva guarda o membro
escolhido, e o painel mostra o responsável. Revisores são escolhidos pela cloud do
executor do funcionário, não pelo executor padrão da equipe. Alterações no cadastro
durante a revisão descartam a aprovação. Revisão avulsa do mesmo trabalho exige
`revisar --funcionario ID` para identificar o autor corretamente. Não escreve
assignee GitHub (agentes não são contas GitHub) nem altera o Time automaticamente.
Local mantém a restrição ao escopo simples quando Team local está desativado.

Na cena 3D, use **Atualizar cena 3D** depois de cadastrar. Os especialistas recebem
assentos na extensão à esquerda; os dez assentos legados não mudam e a diretoria
permanece separada. A cena carrega até 30 especialistas por página para limitar
geometrias; todos os cadastros continuam no painel Gestão. Falha ao ler o cadastro
mantém a cena legada. Os especialistas não entram automaticamente nas reuniões `*`
do Claude: essas mensagens continuam dirigidas ao time nativo existente.
Funcionários Claude cloud recebem eventos do stream principal associados à mesa
do cadastro. Teammates nativos não são renomeados: sua telemetria detalhada ainda
depende dos hooks próprios. Essa integração não promete paridade total de teams.


## Assistente para novos projetos

Depois de instalar o escritório, use o assistente de gestão na pasta pública:

```
python instalar.py --gestao D:/projetos/meu-app --aplicar
```

O assistente detecta CLIs pelo PATH sem inferência nem login, pergunta CEO, diretor,
equipes/modelos, repo e número do Kanban e revisores de clouds diferentes. Uma
cloud declarada no OpenCode identifica o backend escolhido. CLI encontrado não
comprova autenticação, modelo disponível nem permissão GitHub. O primeiro despacho
faz suas verificações de disponibilidade e lê o cartão ao vivo.

Novos projetos começam com merge manual e local desativado. A política permanece
`.office/projeto.json`. Se CLAUDE.md/AGENTS.md já existe, o assistente pode referenciá-lo;
se nenhum existe, cria `.office/REGRAS.md`, sem duplicar regras do Claude. Não altera
documentos existentes. Quando faltam, cria CLAUDE.md, AGENTS.md e GEMINI.md apenas
como referências à fonte escolhida, para descoberta nos consoles nativos. Não altera
arquivos existentes. GEMINI.md novo inclui importação nativa da regra oficial
quando o caminho usa letras ASCII, números, ponto, barra, hífen ou sublinhado;
outros caminhos mantêm a instrução explícita de leitura, sem prometer importação
automática. Referência: [Gemini CLI](https://geminicli.com/docs/cli/gemini-md/).
O assistente não altera
settings, hooks, credenciais, configuração de modelos, workflows ou arquivos de
agentes existentes. A adoção de uma política diferente em projeto já configurado
exige revisar o arquivo existente; o instalador não o sobrescreve. O projeto legado mantém
seus controles de auto-merge. `.office/.gitignore` novo exclui somente o banco local
de funcionários; caso já exista, é preservado e deve conter essa exclusão.

Para preparar uma política JSON revisada sem perguntas (inclusive auto-merge ou
local opt-in), use o módulo comum disponível nas versões pública e dev:

```
python configurar_gestao.py --projeto D:/projetos/meu-app --politica projeto.json
python configurar_gestao.py --projeto D:/projetos/meu-app --politica projeto.json --aplicar
```

Sem --aplicar só imprime a prévia. Repetir a mesma política não altera arquivos.
O assistente não cria o board GitHub, valida autenticação, instala CLIs ou baixa
modelos Ollama; essas etapas e o teste de execução real continuam explícitos.

### Instruções canônicas do cartão

Preparação e gates de despacho usam a mesma projeção de Objetivo, Aceite, Escopo
e Skills da issue. Quando Objetivo está ausente, o título é o objetivo; Escopo
ausente usa o limite padrão. A gestão reconsulta essas instruções e Time/Status
ao vivo antes da execução, após a execução e antes de enviar a entrega à revisão.
Também confere após os revisores. Mudanças bloqueiam a tarefa e impedem a nova
transição; não alteram a issue para restaurar uma cópia antiga. O gate funciona
mesmo com revisão cruzada desativada. Alterações de texto fora desses campos não
inventam novas instruções. GitHub não oferece transação entre todas essas leituras
e a mutação de campo; a conferência reduz a janela, sem prometer atomicidade remota.

### Skills solicitadas pelo cartão

**Skills:** recebe nomes do catálogo compartilhado, separados por vírgula, ponto
e vírgula ou linhas; aceita lista Markdown e nomes entre crases. Por exemplo:
`**Skills:** sp-project-architecture-guardian, outra-skill`. Use somente nomes
existentes, com name válido no SKILL.md. Um campo ausente não exige skills.

O pacote resolve a união dos nomes do cartão e do funcionário pela fonte
fontes.skills, sem duplicar o conteúdo. Cada referência registra caminho relativo,
SHA-256 do SKILL.md e limites conhecidos de portabilidade. Uma skill ausente ou
incompatível impede a reserva e o modelo; mudança no SKILL.md durante a tarefa
impede a entrega à revisão até conciliação. Isso não comprova que o modelo leu ou
seguiu o skill, nem congela scripts/assets referenciados por ele. Hooks, allowed-tools
e contextos Claude continuam sujeitos às capacidades e permissões do console.

### Ordem de prioridades do diretor

No bloco kanban da política, configure `"prioridades": ["P0", "P1", "P2"]`
para ordenar o diagnóstico nessa sequência. A lista usa os nomes exatos do campo
campo_prioridade e não modifica o Kanban. Nome repetido, vazio ou inválido é erro
de política. A lista vazia preserva o diagnóstico legado por número.

Com uma lista configurada, prioridades ausentes/desconhecidas aparecem ao final
como bloqueio no diagnóstico, sem inferir sua posição. O relatório inclui
prioridade, etapa e a ordem usada. Dependências e reservas continuam impedindo
preparação, independentemente da prioridade. Um despacho explícito é uma decisão
separada do usuário/controlador; esta ordenação não o autoriza nem força lote.

As páginas são consultas atuais, não um snapshot persistente. Se o cartão do
cursor sair do Backlog, reinicie o diagnóstico. Mudanças de prioridade entre
páginas podem reordenar itens; antes de decidir um lote, consulte novamente o
quadro desde o início. Coordenação transacional de lotes ainda está pendente.

### Despacho de lote pelo diretor

O usuário ou diretor entrega um plano JSON explícito com 1 a 20 cartões e um
worktree absoluto distinto por cartão. A equipe vem do Time do Kanban; console
e modelo vêm da política ou do funcionário cadastrado. Não existe override de
console/modelo no plano. Escopo é opcional (implementacao por padrão); funcionario
é um ID opcional do cadastro.

```json
{
  "cartoes": [
    {"cartao": 42, "worktree": "D:/worktrees/tarefa-42"},
    {"cartao": 43, "worktree": "D:/worktrees/tarefa-43", "escopo": "simples"}
  ]
}
```

```powershell
python gestao_cli.py --projeto D:/projetos/meu-app lote --plano D:/planos/lote.json
python gestao_cli.py --projeto D:/projetos/meu-app lote --plano D:/planos/lote.json --executar
```

Sem --executar, valida todos os cartões, instruções, dependências, skills, CLIs,
reservas e worktrees limpos do mesmo repositório, sem criar reserva ou inferir.
Cada cartão exige branch distinto. A ordem segue prioridades configuradas e
número. Cartão/worktree repetido ou qualquer entrada inválida impede o lote inteiro.

Com --executar, faz a mesma preparação completa e despacha pelo fluxo comum, com trava compartilhada, sessão e revisão configurada. Reconfere
política, pacote e branch/HEAD antes de iniciar cada modelo. Uma consulta nova
de dependências pode atualizar o horário da evidência, mas precisa comprovar os
mesmos itens. Mudança do pacote/commit exige preparar novamente.

O relatório local dados/gestao/<projeto>/lotes/<id>.json é gravado atomicamente
antes de cada despacho e depois de cada retorno. Contém números, estado e código,
sem prompts, tokens de reserva ou credenciais. processado significa que o lote
retornou todos os cartões para revisão; não significa Feito, merge ou aceite final.
Um bloqueio interrompe os cartões restantes; exceção/interrupção registra incerto.
Não há retry automático, rollback de alterações GitHub, retomada automática nem
prova de morte de processos filhos. Uma queda abrupta pode deixar executando no
relatório; esse estado requer conciliação.

Pré-validação não reserva o lote inteiro nem torna mutações GitHub transacionais.
Outro controlador pode ocupar um recurso depois dela; o despacho comum continua
responsável pelos gates por cartão. Paralelismo coordenado é explícito, conforme a seção abaixo; retomada e conciliação automática continuam pendentes. A projeção de relatórios
locais está disponível no painel de Gestão, conforme a seção abaixo.

### Equipes em paralelo

O plano aceita `"paralelismo": 2` (inteiro de 1 a 4). Ausente ou 1 mantém o fluxo
sequencial existente. O limite conta cartões despachados pelo controlador, incluindo
as revisões configuradas de cada cartão; não limita subagentes internos do console.
Todos os cartões são pré-validados, com branches/worktrees distintos. As vagas são
preenchidas na ordem de prioridade do plano preparado. Cada execução continua
revalidando política, instruções, dependências, cadastro, skills e HEAD nos gates.

Uma falha ou bloqueio interrompe a admissão de novos cartões. Os que já iniciaram
são aguardados e seus retornos registrados; não há cancelamento forçado ou retry.
Uma exceção deixa o cartão em `cartoes_em_execucao` para conciliação e marca o lote
incerto, mesmo se outros cartões chegarem à revisão. O controlador é o único gravador
do relatório; resultados ficam ordenados pelo plano, independentemente da ordem dos
retornos. Queda do controlador não comprova término dos consoles.

O paralelismo vale para equipes de consoles diferentes ou iguais, selecionados na
política. Não cria equivalência com o team nativo Claude. A rota local mantém seus
limites próprios de recursos/vagas e pode bloquear um cartão mesmo quando houver
vaga no lote. O relatório registra o limite e os cartões pendentes de retorno;
esta lista não é uma consulta de processos vivos. O Kanban permanece a fonte das
tarefas e não há transação distribuída ou rollback de mutações GitHub.

### Lotes no painel de Gestão

A API /api/gestao projeta somente os números dos cartões, estados, códigos de
saída e horário dos relatórios locais do diretor. O painel exibe até dez relatórios
válidos recentes, com aviso de cobertura limitada ou arquivos indisponíveis.
Não expõe prompts, credenciais, tokens de reserva ou caminhos locais. Campos
extras do arquivo são ignorados na projeção. Relatórios corrompidos, de outro
repositório, incompletos marcados como processado ou links fora da pasta não
são apresentados como lotes válidos. A leitura é limitada a 500 entradas e 40
arquivos por consulta, com limite de 64 mil bytes por arquivo.

O estado executando é um registro do controlador, não prova de processo vivo.
O painel explica isso e mostra o último cartão iniciado; incerto exige conciliação.
Processado significa retorno à revisão, não conclusão do projeto ou merge.
A projeção é somente leitura e atualiza junto com o painel aberto. Não inicia
agentes, retoma tarefas nem libera ocupações. Comandos operacionais permanecem
no PC; recuperação automática continua pendente.

### Fontes canônicas fora do diretório de execução

O prompt de gestão identifica explicitamente a raiz canônica e os caminhos
absolutos das fontes configuradas, inclusive a política. Isso vale para CEO,
diretor e equipes; o worktree continua sendo o destino das alterações da tarefa.
Os documentos são referências de leitura, sem cópia de corpo no prompt ou no
estado. O escritório não sobrescreve arquivos divergentes do branch nem muda
configurações/permissões nativas para conseguir ler a raiz. Falta de acesso deve
ser tratada como bloqueio pelo agente, não como autorização para usar outra fonte.

O pacote registra caminho declarado, destino resolvido, presença e SHA-256 de
regras/produto/arquitetura. Os gates antes/depois da execução e da revisão
reconferem esses valores; criação, remoção ou edição da fonte canônica invalida
a preparação. Lotes também comparam o snapshot antes de cada despacho. O horário
de arquivo não é usado como prova de conteúdo. Fonte fora do projeto é erro, e
a leitura para hash é limitada a 8 MiB por documento, sem truncar.

Uma fonte ausente é registrada como ausente; projetos genéricos não são obrigados
a possuir GDD ou grafo por essa camada. Isso não afirma que sua documentação
está completa. Os hashes cobrem os arquivos configurados, não todos os documentos
que eles importam ou referenciam. O envio da referência e a detecção de mudanças
não provam obediência do modelo. Regras carregadas automaticamente pelo console
a partir do worktree ainda podem exigir conciliação; os testes desta etapa usam
CLIs simulados. Validação real de cada console continua necessária.

### Intervalos observados por tarefa e modelo

O despacho comum registra cada tentativa na tabela independente `execucao_tarefa`
do banco de tarefas: id privado, token de reserva, console, modelo configurado,
origem do modelo, cloud/local, início/fim, duração em segundos e código de saída.
`execucao_contexto` conserva token/projeto/cartão, sem prompts ou sessão, para
atribuir tentativas anteriores mesmo após outra reserva do mesmo cartão. Esse
vínculo é gravado na mesma transação da tentativa e nunca substituído.
Ao abrir o controlador, bancos anteriores recuperam apenas vínculos ainda
comprováveis nas reservas atuais. Tentativas já órfãs não recebem projeto
inventado: ficam excluídas e geram aviso de histórico incompleto neste banco.
O painel não migra o banco ao consultar. Agregados incluem tentativas históricas
com vínculo; a última execução exibida no cartão pertence apenas à reserva atual.
Não altera as tabelas históricas do Claude. Bancos antigos continuam legíveis
pelo painel em modo somente leitura, sem criação de tabela nessa consulta.

A duração usa relógio monotônico entre início e retorno do executor; inclui
inicialização do CLI, ferramentas e esperas, e exclui a revisão posterior.
Exceção ou interrupção sem retorno deixa duração final indisponível. Isso não
prova processo vivo nem libera reserva para repetir a tarefa automaticamente.
Um encerramento idêntico é idempotente; resultados conflitantes são recusados.

GET /api/gestao apresenta a última tentativa por cartão e agregados dos últimos
sete dias por console/modelo configurado/cloud ou local, com média e cobertura,
contagens de saída zero, saída diferente de zero e tentativas sem retorno.
Leitura limitada às mil tentativas mais recentes, com aviso de cobertura.
O aviso só aparece quando existe uma tentativa adicional. Retorno parcial ou
inconsistente (fim sem código/duração, código/duração sem fim, intervalo inválido)
torna a projeção indisponível; não entra como sucesso nem altera as médias.
Sem medições, média e soma permanecem indisponíveis. IDs e tokens privados não
são publicados. Execuções fora do despacho comum não entram nesse registro.

O painel não comprova o modelo efetivamente servido, velocidade ou qualidade
intrínseca do modelo. Saída zero não comprova aceite. Tokens e cotas permanecem
no Placar, separados por fornecedor; intervalos não são valores de cobrança.
Custos monetários por tarefa, aceite e retrabalho continuam pendentes.

### Consumo OpenCode pelo launcher JSON

O coletor comum aceita `step_finish` com `part.type=step-finish`, ID de parte e
sessão explícitos/coincidentes. Cada parte tem chave persistente por projeto,
sessão e ID: replay/retomada do mesmo registro não soma uma segunda amostra.
Etapas distintas são somadas; não importa automaticamente o histórico anterior.
Os filhos/TUI observados pelo plugin usam a ponte descrita abaixo. Não exige alteração nativa
nos prompts, modelos ou permissões do console.

Na forma V1 validada com OpenCode 1.18.35, tokens.input exclui cache e
 tokens.output exclui raciocínio. Entrada normalizada = input + cache.read +
cache.write; saída normalizada = output + reasoning. Total nativo, quando
informado, é preservado; sem total, a soma só é calculada quando todos os
componentes necessários são válidos. Ausente/inválido permanece indisponível,
sem preencher zero. Cache não é somado outra vez na visão comum. Contadores
não negativos inteiros até o limite exato JSON são aceitos, inclusive no total;
formato sem identidade ou com sessão divergente não entra no histórico.

Modelo e namespace provider/model são os configurados no launcher JSON; no
plugin, são os informados nos metadados do assistente. A origem é explícita
no Placar. O namespace não comprova fornecedor/backend efetivo; sem modelo,
ambos permanecem não informados. Cloud/local são separados. O campo cost nativo
não é registrado como cobrança real nem como estimativa validada nesta seção.
Os cálculos herdados do console não substituem fatura ou uma tabela de preços
identificada. Claude/statusline e cotas semanais Codex continuam separados.

Fontes da versão instalada: [StepFinishPart](https://github.com/anomalyco/opencode/blob/v1.18.35/packages/schema/src/v1/session.ts)
e [getUsage](https://github.com/anomalyco/opencode/blob/v1.18.35/packages/opencode/src/session/session.ts).
Prova local somente de leitura sobre contadores de um registro nativo confirmou
a normalização e replay idempotente; não foi uma captura de nova execução.

### Contadores da TUI e dos filhos OpenCode

O plugin V1 observa message.updated apenas para IDs e providerID/modelID do
assistente; não armazena conteúdo de mensagens. Em message.part.updated de
step-finish envia somente identidade e tokens à ponte consumo_providers.py
--opencode, por stdin limitado a 128 KiB. --banco permite consumo isolado para
testes. Banco padrão é consumo_providers.db ao lado do banco do escritório;
nenhuma tabela/evento Claude recebe esses contadores. Falha da ponte é ignorada
pela telemetria, e processo da ponte que excede dez segundos é encerrado.

Na TUI, o plugin coleta pai e filhos observados. Em run com stream pertencente
ao launcher, o plugin ignora o pai e mantém os filhos identificados por parentID.
O ID persistente da etapa torna replay idempotente também entre processos.
Modelos associados ao messageID têm origem informado pelo console; ausência ou
metadado de outra sessão mantém o modelo indisponível. O namespace informado
não é comprovação independente do backend/cloud ou da fatura. O índice em
memória retém no máximo 4096 associações de modelos. Históricos anteriores à
instalação do plugin não são importados automaticamente.

A rota local do launcher propaga OFFICE_FONTE=opencode_local para os filhos;
fora dessa rota, o valor existente é preservado. Uma TUI aberta diretamente
precisa configurar seu rótulo local explicitamente; o plugin não descobre nem
comprova o local da execução por si só. OFFICE_PROJETOS continua filtrando.
Atualize a cópia do plugin pelo importador para habilitar esta coleta; uma cópia
antiga não ganha o novo comportamento só por atualizar o escritório.



### PRs do repositório canônico

O painel `/prs?projeto=<id>` usa a mesma seleção de projetos registrados do Kanban
e `kanban.repo` da política. Com múltiplos projetos, exige seleção explícita; ID
não é caminho. Política inválida/indisponível nunca cai no repositório legado.
A consulta REST segue paginação, exibe até 1.000 PRs abertos e informa limitação.
A política é revalidada após a consulta. Texto/caminhos/credenciais do projeto não
entram na resposta; o servidor não grava reviews/checks no GitHub ou executa merge.

PRs de gestão mostram título, branch e SHA observados, mas ficam aguardando
validação dos gates/revisões desse projeto. Não herdam aprovação, sugestões ou
botões de tratamento do serviço legado. O seletor dos PRs é independente do
seletor visual do Kanban; ambos usam o mesmo catálogo/política. Respostas antigas
não substituem a seleção atual da tela. Sem gestão ativa, o painel e os consumidores
internos mantêm o serviço/cache legado. XP, sugestões e alertas de sugestões/Placar
têm fontes próprias por projeto descritas acima. Histórico global de custos/ações,
saúde e atividade não é atribuído automaticamente aos PRs de gestão.

## Escolher executores pelo painel da nova versão

Em Gestão, abra Escolher consoles do CEO, diretor e equipes. Selecione Claude, Codex, OpenCode ou Gemini, informe o modelo quando necessário e salve. Trocar console limpa o modelo anterior para evitar enviar um ID incompatível. Fornecedor real OpenCode pode ficar não informado nesses papéis; sem essa identidade, não comprova diversidade ou separação do autor na revisão cruzada. CEO e diretor usam cloud neste formulário; equipes podem escolher local quando a política já permite, com as proteções e limites existentes.

A edição é exclusiva do PC e de projetos já registrados/adotados. Salva em .office/projeto.json, preserva regras, Kanban, merge, rotas por escopo, revisores e especialistas e não inicia agentes. Rotas por escopo prevalecem sobre equipes; especialistas mantêm seus executores cadastrados. A revisão continua sendo validada pelo despacho, incluindo a diversidade necessária, e mudar o executor da equipe não escolhe novos revisores automaticamente.

O hash da política acompanha o formulário; edição antiga retorna conflito e exige recarregar. Um lock exclusivo protege edições simultâneas do painel e a política anterior fica em .office/historico-politica. Editores externos podem ignorar esse lock: não edite JSON durante o salvamento. A substituição do arquivo é atômica, mas ainda não há recuperação automática de um lock após queda; confirme que nenhuma edição está em curso antes de removê-lo. Alterar política durante execução invalida gates e exige conciliação.

O assistente novo inclui historico-politica/, politica.edicao.lock e politica-*.tmp no .office/.gitignore. Em projetos adotados anteriormente, acrescente essas exclusões ao arquivo existente antes de usar o formulário, preservando demais entradas. A política continua compartilhada pelo Git; salvar não faz commit/push. Autenticação/disponibilidade dos modelos e execução real de CEO/diretor ainda dependem dos consoles; o formulário não configura contas nem altera auto-merge no GitHub.

## Conferir evidências de revisão por commit

Na nova edição, abra “Conferir checks e revisões deste commit” em um PR do projeto.
O detalhe consulta `/api/gestao/pr` com ID do projeto, número e SHA da lista.
Mostra checks/statuses e eventos de reviews, distinguindo commit atual e antigo.
Os nomes exigidos por merge.checks aparecem com estado observado, ausente ou
ambíguo; neutral/skipped não viram success. Dois checks/Apps com mesmo nome não
são confundidos. O status mais recente por contexto prevalece sobre versões antigas.
Consulta só ao abrir detalhes ou pedir nova leitura; a lista não consulta todos
os PRs em massa. Mudança de projeto/commit/atualização descarta a resposta anterior.

GitHub é consultado por GET para PR antes/depois, check-runs paginados do SHA,
statuses, reviews e rulesets. A query GraphQL complementar é enviada por POST,
somente leitura, sem mutation. Coleções incompletas, identidade divergente e falhas
ficam indisponíveis, sem reusar aprovação anterior. Não são publicados textos de
reviews/output, caminhos locais ou URLs auxiliares. Uma revisão GitHub registrada
não comprova a cloud do revisor e os eventos não substituem a decisão efetiva das
proteções do GitHub. A leitura adicional de rulesets ativos usa a branch de base,
com nome codificado na URL, e pagina todas as regras de repositório/organização.
Exibe checks exigidos pelo GitHub separadamente dos declarados na política;
quando integration_id é informado, confere também o App do check. Mostra número
de aprovações exigidas, exigência de CODEOWNERS/último push/threads e parâmetros
adicionais ainda não avaliados, sem presumir cumprimento. Rulesets são lidos antes
e depois: mudança descarta a consulta inteira, assim como troca da base ou de seu
SHA. Falha nesta leitura conserva os checks/reviews observados e marca rulesets
indisponíveis; nunca equivale a lista vazia de regras.

A consulta de rulesets retorna somente suas regras ativas. Lista vazia não comprova
ausência de proteção clássica. A query complementar `prs_pendencias.py` coleta
reviewDecision, as conversas de revisão e branchProtectionRule da base. Distingue
decisão não informada de aprovação e erro de acesso de proteção clássica ausente.
Não lê bodies, comentários, caminhos de arquivo ou nomes de quem resolveu conversas.
Mostra contagens totais/pendentes/desatualizadas; desatualizada não significa resolvida.
Checks declarados na proteção clássica também são comparados por nome/App.

Duas coletas completas devem concordar em IDs/estados de conversas, decisão e
proteção. Paginação de até 20 páginas/2.000 conversas por coleta, com cursores
distintos e total estável; contagem incompleta ou erro parcial nunca vira zero.
O prazo de 60 segundos é conferido antes/depois de cada chamada; a chamada gh em
curso tem seu próprio timeout de 30 segundos. Mudança de PR/head/base/ref/decisão/
proteção/threads descarta a consulta; formato/acesso indisponível marca a seção
complementar desconhecida, preservando evidências REST válidas. Leitores injetados
offline precisam fornecer também o reader GraphQL para habilitar essa consulta.

A decisão informada pelo GitHub não comprova identidade cloud, revisão independente
nem todos os gates de CODEOWNERS/bypass/merge queue. Os endpoints não formam
transação GitHub: não garantem que
o estado continuará igual depois da consulta. Nenhuma aprovação, check,
merge ou conclusão de cartão é publicada por essa leitura.

Fontes: [check runs](https://docs.github.com/en/rest/checks/runs),
[commit statuses](https://docs.github.com/en/rest/commits/statuses) e
[reviews](https://docs.github.com/en/rest/pulls/reviews) e
[regras ativas da branch](https://docs.github.com/en/rest/repos/rules#get-rules-for-a-branch),
[conversas e decisão de revisão](https://docs.github.com/en/graphql/reference/pulls) e
[proteção clássica](https://docs.github.com/en/graphql/reference/branches).

## Pendências operacionais das tarefas

Antes de instalar em outro projeto, a prévia de `iniciar_projeto.py` mostra
requisitos locais por política: Python 3.9+, sqlite3/ssl, porta disponível,
Git/GitHub CLI para gestão ativa e consoles de CEO/diretor/equipes/rotas/revisores.
Ollama é exigido apenas quando uma rota local está escolhida; não baixa modelos.
`--exigir-requisitos` retorna código 3 sem aplicar quando algo obrigatório falta.
Sem a flag, pode preparar configuração para depois instalar os requisitos.
Verifica PATH/adapter e bind temporário da porta; não executa CLIs, autentica,
confere versões nativas, acessa GitHub ou garante disponibilidade cloud. Referências
oficiais de instalação estão no relatório da prévia; não executa seus instaladores.

O painel Gestão mostra, por projeto/repositório, tarefas bloqueadas, última
tentativa com saída diferente de zero, tentativas sem retorno e execuções sem
medição. Inclui reservas anteriores aos sete dias das métricas de desempenho.
Considera apenas a tentativa mais recente da reserva atual; nova reserva do
mesmo cartão não herda falhas da anterior. A cobertura é limitada às 200 reservas
mais recentes e o painel informa quando existem outras.

Cancelar uma reserva não comprova que o processo terminou: tentativa sem retorno
continua exigindo conferência. Os registros não são heartbeat nem comprovam
qualidade ou aceite. A leitura não libera reservas, retoma agentes, conclui
cartões nem publica estado no GitHub. Saúde de processos e recuperação ainda
exigem integração adicional.

O tipo de alerta `tarefa_pendente` acompanha esses sinais nos projetos ativos.
Primeira leitura estabelece uma base sem avisar sobre pendências antigas; depois
avisa sobre novidades, sem repetir o mesmo registro. Tentativas sem retorno ou
sem medição aguardam 30 minutos antes do aviso; isso não declara processo morto.
As preferências de tipo e o orçamento de atenção continuam aplicáveis: por
padrão, é aviso de rotina incluído no resumo. Link abre Gestão no projeto correto.
Falha de leitura do banco preserva a base; cobertura parcial não declara resolvida
uma pendência fora da janela. Esse alerta não substitui conciliação.

Despachos pelo controle comum registram sinais a cada 15 segundos numa tabela
local `atividade_execucao`. O launcher vincula o objeto do processo principal
que acabou de iniciar; o acompanhamento consulta esse processo, sem localizar ou
controlar processos por PID reaproveitado. Gestão mostra o último sinal e o
retorno observado. Sinal com até 60 segundos indica observação recente, não
progresso ou aceite. Acompanhamento do controlador não abrange filhos/agentes
nativos nem sessões iniciadas fora desse despacho. Sinal antigo requer conferência,
sem declarar o processo morto. O alerta sem retorno aguarda enquanto o processo
principal foi observado em execução por um acompanhamento recente.

Ao sair ou falhar, o acompanhamento registra encerramento/interrupção. Não libera
reserva ou worktree. Falha de persistência impede entrega normal; falha de vínculo
no launcher recolhe o processo que iniciou. Registro existente não é reocupado
automaticamente; conciliação e recuperação de agentes ainda estão pendentes.

### OpenCode gratuito e identidade do fornecedor

Cadastro de especialistas, configuração inicial e edição de CEO/diretor/equipes
permitem OpenCode cloud sem cloud declarada. Os formulários omitem o campo quando
vazio; não preenchem fornecedor por dedução do nome Zen ou sufixo free. Cloud
presente, mas vazia/inválida, continua recusada. Revisores e separação do autor
continuam usando cloud_executor e exigindo fornecedor declarado: esta mudança
não flexibiliza os gates de revisão/merge. O modelo explícito de coordenação
continua obrigatório; namespaces locais continuam recusados nesse fluxo cloud.

Revisão isolada OpenCode exige step_start, texto e step_finish reason=stop, uma
sessão externa/da parte coerente, uma mensagem e IDs de partes não repetidos.
Texto/parte inválidos, ferramenta, erro, evento desconhecido, outra etapa,
mensagem/sessão divergente, fim ausente/repetido ou evento posterior bloqueiam a
resposta. Reasoning validado pode ser ignorado na decisão, sem entrar no JSON.
O normalizador do chamador continua impondo o schema da revisão ou coordenação.

Space Bunny Free foi listado com custos zero no CLI e na documentação oficial
Zen em 10/10/2026. Quatro respostas nativas aceitas: prova JSON, revisão sintética
que detectou subtração no lugar de soma como P1, CEO e diretor selecionando
somente o cartão 42 numa fixture de Kanban. Contadores observados: 2.069, 2.179,
3.243 e 3.144 tokens, separados pelos papéis. Não enviou dados do jogo ou fez
login/compra/alteração de autenticação, não usou modelo pago ou fallback, não
executou despacho nem alterou GitHub. Consulta e revisão ocorreram sem ferramentas
em diretórios temporários novos, conforme os controles do adapter comum.

Isto comprova esses fluxos nessa amostra. Não atesta backend real, TUI/Team,
execução de todas as skills, diversidade de clouds ou cobrança/fatura. Modelo
permanece configurado nos contadores; gratuitidade e disponibilidade podem mudar.
Selecione explicitamente um ID disponível, confirme a tarifa e mantenha os gates.
Erros 403 de outras tentativas/modelos não provam indisponibilidade de todo Zen.
Referências: [Zen](https://opencode.ai/docs/zen/) e
[stream do CLI oficial](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/cli/cmd/run.ts).


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


### Retomada explícita de cartão bloqueado

`gestao_cli.py retomar` faz prévia sem inferência e, com `--executar`, reutiliza
a reserva e a sessão nativa, acrescentando tentativa ao histórico. Exige o mesmo
executor cloud, política, fontes, skills, cadastro, worktree e branch, checkout
limpo e cartão ainda em andamento com instruções/equipe/prioridade preservadas.
Todas as tentativas anteriores precisam ter retorno e o processo principal da
última deve ter encerramento registrado. Uma nova reserva inclui o contexto de
execução; reservas anteriores sem esse vínculo não são migradas por suposição.

```powershell
python gestao_cli.py --projeto D:/projetos/meu-app retomar --cartao 42 --worktree D:/worktrees/card-42
python gestao_cli.py --projeto D:/projetos/meu-app retomar --cartao 42 --worktree D:/worktrees/card-42 --confirmacao HASH_DA_PREVIA --agentes-conciliados --executar
```

O hash confere a reserva, última tentativa/atividade e branch/HEAD da prévia.
Mudança exige nova prévia. `--agentes-conciliados` declara a conferência manual
dos agentes/ferramentas no console: encerramento do pai não prova filhos.
O claim da reserva é transacional; a ocupação Git compartilhada impede dupla
execução. Trava antiga não é roubada; ausência de PID/prazo não libera trabalho.
Falha da prévia não deixa nova trava, pois ainda não houve lançamento.
O quadro não volta ao Backlog nem recebe novo PATCH de andamento. Revisão e
entrega passam pelos mesmos gates; sem PR ou com falha, permanece bloqueado.
Retomada local, recuperação de quedas sem retorno, conciliação automática dos
filhos permanecem pendentes; a retomada explícita também está disponível no painel Gestão. Testes usam Git,
SQLite e subprocessos reais com streams sintéticos dos quatro consoles; não
comprovam retomada cloud autenticada.


### Retomada pelo painel Gestão

Cartões bloqueados oferecem "Conferir retomada" no PC. Prévia consulta os
mesmos gates da CLI; sessão/worktree são resolvidos da reserva no servidor.
O formulário não recebe paths nem permite trocar sessão/modelo. Após declarar
a conferência dos agentes/ferramentas anteriores, "Retomar sessão" envia o hash
e agenda o worker. Fechando o formulário, Gestão acompanha pedidos e tarefas.
Reserva, sessão e histórico são preservados; sem PR continua bloqueado.

retomada_painel.py implementa POST /api/gestao/retomar, restrito ao PC e ao CSRF
existente. Ledger separado pedidos_retomada.db por projeto/repo/cartão impede
pedido duplicado pendente; ocupação compartilhada e claim da reserva continuam
no controlador. Não copia stdout, erros nativos, paths ou IDs de sessão para
o resumo do pedido. `recebida`/`executando` só são mostrados assim enquanto
o handle local está vivo; sem handle, ficam incertos na projeção, sem mudar
o banco na leitura. Erro/interrupção preserva incerto, sem retry automático.

Pedidos incertos ainda exigem inspeção/conciliação no PC e impedem novo pedido
do mesmo cartão. Recuperação de quedas sem retorno, liberação segura de travas,
retomada local e recuperação de pedidos sem vínculo continuam pendentes. A conciliação de retorno vinculado está descrita abaixo. Isso não é
prova de encerramento de filhos nem validação cloud autenticada. Testes cobrem
API/worker real com Git/SQLite/subprocessos e Kanban/modelos sintéticos, HTTP
com CSRF, módulo do formulário e integração real do painel em VM JavaScript.


### Conciliação do acompanhamento da retomada

O pedido passa a guardar em retomada_contexto um vínculo privado e imutável
com reserva/tentativa. O callback ao_execucao de gestao_cli.retomar é chamado depois de registrar a tentativa e antes de iniciar o launcher. Falha ao
vincular impede o lançamento. Não deduz vínculos de pedidos históricos.

Pedidos incertos oferecem "Conferir retorno da retomada" no PC. Prévia confere
a tentativa vinculada, última na mesma reserva, retorno/duração registrados,
processo principal encerrado e tarefa bloqueada ou em revisão. Outra reserva,
nova tentativa, vínculo ausente, handle vivo ou retorno pendente impedem a
conciliação. Confirmação exige hash atual e reavalia os registros/política.
Apenas pedido/sha de conciliação mudam; não libera trava/reserva, reinicia
console, altera GitHub ou aprova cartão por exit zero.

O banco de tarefas é lido em transação mantida até o commit do ledger, para
impedir que outro escritor mude a evidência durante a aplicação. Esse gate
exige journal delete/truncate/persist; WAL ou outro modo não comprovam essa
trava entre os dois bancos e são recusados, sem mudar o modo/configuração.
Encerramento de filhos, quedas sem retorno, liberação de ocupação antiga e
recuperação de pedidos sem vínculo continuam pendentes.

### Merge opcional no painel

No PC, abra Gestão → Configurar merge deste projeto. Escolha Manual ou Automático, informe os nomes exatos dos checks obrigatórios e os rótulos que exigem intervenção manual, e salve. Projetos novos começam em modo manual; nenhuma escolha é herdada de outro projeto. A edição usa `.office/projeto.json`, preserva revisores, executores e regras e guarda a versão anterior em `.office/historico-politica`. Conflitos exigem recarregar.

Salvar não faz merge nem configura workflows ou permissões do GitHub. O controlador continua verificando checks, revisão configurada e o commit correspondente; gates externos ainda precisam estar completos. Mudanças invalidam a conferência de execuções ligada à política anterior. O auto-merge autorizado para o jogo deve ser adotado no fluxo do projeto, sem alterar o legado.

### Consumo por projeto

Abra Gestão e consulte Consumo deste projeto. O painel mostra tokens observados nos últimos sete dias, separados por console, modelo e agente, com cobertura dos contadores. A janela é móvel, não o ciclo semanal de cobrança. Consultas observadas do CEO e diretor aparecem em seus papéis. Tarifas configuradas podem fornecer equivalente teórico de API, sempre identificado como estimativa parcial; não é fatura.

Cada resumo filtra a identidade já registrada pelos coletores do projeto. Registros antigos sem vínculo compatível não são atribuídos por suposição. Renomear/mover uma pasta pode impedir o vínculo com seu histórico; não há migração automática. Cotas de Claude/Codex e outros fornecedores pertencem à conta, ficam no Placar e não são divididas ou somadas entre projetos. O Placar mantém o histórico global do escritório, inclusive de projetos removidos da configuração.

### Consumo Claude no launcher

Sessões Claude cloud do launcher registram incrementos de `modelUsage` do `result` principal, por modelo informado. A sessão nova parte de saldo zero; a retomada usa o saldo persistido por projeto/sessão/modelo. A identidade criada ou solicitada pelo launcher precisa coincidir com `system/init` e resultados. O agregado inclui os descendentes informados pelo runtime e pertence ao papel da sessão principal; resultados filhos não são contados separadamente. Snapshots repetidos não somam novamente e reduções não substituem o saldo observado. Entrada inclui input, cache lido e cache criado; cache não é somado de novo ao total.

Na retomada sem saldo prévio para o modelo, o primeiro agregado estabelece somente a referência. Não se pode separar seu gasto novo do histórico anterior; ele fica fora do total observado e há lacuna de cobertura. Leituras seguintes registram somente os incrementos no papel atual. Isso também vale para um modelo ainda sem saldo na sessão retomada. Saldos antigos não são derivados por suposição dos registros anteriores à implantação deste mecanismo. TUI e perfil local não usam esse agregado. Falta de `modelUsage` ou de seus campos não vira zero. Erro com contadores positivos preserva o consumo; erro de crash com zeros não rebaixa o registro. Isso não altera o gate de entrega nem comprova conclusão de filhos. Não representa todo o uso Claude/team e não atribui o agregado aos funcionários filhos.

Saldo e incremento são gravados juntos em transação SQLite. Cada execução/modelo tem uma amostra de seus incrementos, datada na primeira gravação; não é uma série temporal de cada token e pode cruzar a janela de sete dias durante uma execução longa. Incrementos de uma retomada nova não trazem ao período o gasto de execuções antigas. Consultar o painel continua sendo leitura e não cria saldo.

Consultas isoladas de CEO/diretor/triagem/auditor conservam a exigência de sessão nova sem ferramentas e usam o mesmo normalizador. Valores `costUSD`/`total_cost_usd` do runtime não são convertidos em cobrança: a [documentação oficial de consumo](https://code.claude.com/docs/en/agent-sdk/cost-tracking) distingue estimativas do cliente e faturamento. Preços teóricos do catálogo continuam sujeitos aos providers/modelos já elegíveis; não foi acrescentada precificação automática do Claude.

### Conferir fontes comuns

Entradas novas `CLAUDE.md`, `AGENTS.md` e `GEMINI.md` orientam a consultar `.claude/rules/`: regras sem `paths` são gerais; regras com esse frontmatter precisam corresponder aos arquivos da tarefa. O contexto compartilhado do launcher também inclui essa orientação quando a pasta existe dentro do projeto. Não copia o corpo das regras, calcula globs ou comprova leitura. A carga condicional nativa do Claude e seus hooks permanecem próprios; os outros consoles precisam ler e respeitar o escopo. Fonte/regra ilegível ou escopo indeterminado deve ser informado antes de editar.

O `CLAUDE.md` novo importa a fonte principal por `@./caminho`, assim como o `GEMINI.md`, quando o caminho usa caracteres simples sem espaços. Arquivo existente nunca é alterado nem recebe importação automática; se `CLAUDE.md` já é a fonte, não há autoimportação. Para caminhos com espaços/caracteres não normalizados, o wrapper mantém a referência textual e a leitura precisa ser feita pelo console. `AGENTS.md` mantém referências textuais. Não se presume que OpenCode expanda imports `@`; sua configuração `instructions` e entrada AGENTS são tratadas separadamente.

Referências oficiais: [memória/regras do Claude](https://code.claude.com/docs/en/memory) e [instruções do OpenCode](https://opencode.ai/docs/rules/). Instruções orientam o modelo; não substituem validações de execução e aprovação do escritório.

Repetir `configurar_gestao.py` ou `iniciar_projeto.py` com a mesma política prepara as entradas de console ausentes, mesmo quando `.office/projeto.json` já existe. A prévia lista os arquivos novos; `--aplicar` os cria sem regravar a política ou instruções existentes. Se outro editor criar uma entrada entre prévia e aplicação, refaça a prévia. Fonte de regras ausente em política existente exige restauração/revisão pelo usuário, inclusive `.office/REGRAS.md`; o assistente não substitui regras perdidas pelo texto inicial. Esta reparação não resolve divergências em arquivos existentes.

Gestão mostra os caminhos relativos de regras/produto/arquitetura configurados e a presença de CLAUDE.md, AGENTS.md e GEMINI.md. Indica quais arquivos correspondem aos consoles escolhidos e se citam literalmente a fonte de regras, ou são essa fonte. Funciona também antes da gestão ser habilitada. Leitura limitada a 128 KiB por arquivo, UTF-8, sem seguir links simbólicos de arquivo ou caminhos fora do projeto.

Este inventário não interpreta instruções, não resolve divergências e não prova que o console carregou os arquivos. Texto em comentários ou exemplos também pode ser uma menção. A concordância semântica precisa de revisão; nunca use presença/referência como gate de aprovação. Não mostra corpos dos documentos nem caminhos absolutos. Skills usam seu catálogo e diagnóstico separados.

### Consumo das tarefas em worktrees

O controlador fornece ao launcher `projeto_consumo`, a raiz cadastrada e validada do projeto. O console continua executando no worktree da tarefa. Coletores do stream e rollouts Codex usam essa raiz apenas para identidade do consumo, permitindo que o painel do projeto reúna os registros. Despachos cloud, locais e retomadas seguem o mesmo vínculo; isso não adiciona coleta onde o runtime ainda não fornece contadores.

No OpenCode, `OFFICE_CONSUMO_PROJETO` transmite essa identidade ao plugin para etapas acompanhadas por ele. `OFFICE_PROJETOS` continua filtrando eventos pela pasta de execução. Atualize a cópia instalada do plugin pelo instalador/importador da nova versão para receber esse comportamento. Fora do controlador, sem identidade explícita, o launcher/plugin conserva a pasta de execução como projeto de consumo. Não há inferência automática pela pasta principal do Git nem migração de registros históricos atribuídos a worktrees.

### Eventos observados por tentativa

Além do sinal periódico do controlador, Gestão mostra quantos eventos normalizados foram recebidos do console na tentativa atual e o horário/tipo do último. O callback do launcher abrange streams Claude/Codex/OpenCode/Gemini e eventos dos rollouts acompanhados pelo observador Codex. Início/encerramento sintéticos do launcher não entram nessa contagem. O encaminhamento local utiliza o mesmo callback quando o adapter fornece eventos.

`atividade_eventos` guarda somente identidade da tentativa, horário, quantidade, tipo e quantidade de eventos que tinham vínculo de filho. Não guarda texto, comandos ou sessões. Contadores são acumulados em memória e persistidos junto ao sinal a cada 15 segundos e no encerramento, evitando uma escrita extra por delta do console. Uma queda antes da persistência pode perder eventos desse intervalo; registros não são importados retroativamente. Banco antigo sem essa tabela continua legível e não recebe alteração pela leitura do painel.

Eventos comprovam comunicação recebida, sem provar avanço do código, qualidade, aceite, conclusão ou vida de agentes filhos. Claude TUI/hook e filhos acompanhados exclusivamente pelo plugin OpenCode não estão vinculados a esse contador; o feed existente continua funcionando. Tentativa nova não herda eventos anteriores. Ausência ou silêncio de eventos não declara inatividade. Os alertas de tarefa mantêm seus critérios; não foi introduzido encerramento, retomada ou escalonamento automático por silêncio. Falha da persistência do acompanhamento continua impedindo entrega normal, sem interromper o trabalho do console no callback.

### Acompanhamento de instalação Claude existente

O servidor da edição nova inicia a ponte quando `dados/ponte_eventos.json` contém configuração local válida com ativo=true. Ausência/ativo=false mantém desligada e não cria banco ou thread da ponte. Configure explicitamente, antes de abrir o escritório:

```json
{"ativo":true,"fontes":[{"origem":"claude-legado","provider":"claude","fonte":"D:/instalacao-anterior/dados/escritorio.db"}]}
```

Até quatro fontes, nomes únicos e caminhos absolutos; arquivo até 16 KiB, dentro dos dados privados da instalação. O servidor acompanha apenas novos eventos por padrão; recorte inicial continua sendo ação CLI separada. Estado aparece no início de Gestão, com última consulta/importados/descartados desta execução, sem caminhos ou conteúdos. Configuração alterada durante a execução interrompe a ponte até conferência/reinício. Falha de uma fonte não oculta outras fontes válidas. O encerramento do servidor solicita parada e espera a thread; não encerra consoles nativos.

Para preservar os hooks da instalação anterior, ponte_eventos.py lê seu SQLite em mode=ro/query_only e acrescenta eventos normalizados ao banco separado da edição nova. É uma ação explícita, sem alterar a fonte ou recabear hooks. O marcador EDICAO.json do destino deve identificar a edição nova. Nunca escolha o banco da fonte como destino. Não importa custos, cotas, sessões, reservas ou decisões. Os IDs do destino permanecem próprios; origem_escritorio identifica origem/ID de leitura.

```powershell
python ponte_eventos.py --origem claude-legado --provider claude --fonte "D:/instalacao-anterior/dados/escritorio.db" --destino "D:/escritorio-novo" --ultimos 200
python ponte_eventos.py --origem claude-legado --provider claude --fonte "D:/instalacao-anterior/dados/escritorio.db" --destino "D:/escritorio-novo" --acompanhar
```

Sem --ultimos, a primeira execução registra o ponto atual e acompanha só novos eventos. --ultimos aceita até 200 na inicialização; não reimporta o passado quando já existe cursor. Lotes futuros são de até 200, em ordem da fonte. --acompanhar repete a cada dois segundos; Ctrl+C encerra esse CLI independente. O servidor usa o acompanhamento opt-in descrito acima; instalador não habilita fontes automaticamente. Nenhum processo nativo é encerrado. Eventos inválidos/acima do limite são descartados com contagem; não viram atividade fictícia.

Cursor e inserções são uma transação no destino; leitores concorrentes da mesma origem não duplicam eventos. Uma fonte física só pode ter um vínculo no destino. Identidade do arquivo, âncora e sequência são conferidas; fonte substituída, reiniciada ou histórico alterado exige revisão e uma nova origem explícita, sem apagar os eventos já registrados. Ausência/erro interrompe a ponte; não troca de fonte. WAL confirmado é lido com o escritor aberto. Histórico anterior ao recorte continua no banco original; replay novo cobre somente eventos importados. A origem não comprova vínculo de projeto/tarefa, conclusão ou equivalência Team.

### Estado dos perfis nativos

O painel consulta o estado derivado de cada funcionário ao atualizar Gestão: ausente, atual, divergente ou indisponível. Atual significa apenas que o arquivo corresponde ao cadastro/política/skills consultados, não descoberta nem execução no console. Divergente inclui perfil personalizado ou desatualizado; o arquivo é preservado. Problemas de um perfil não ocultam os demais funcionários. Modelo local aparece como gerenciado e continua no despacho com proteção de recursos. A consulta não cria arquivos, não retorna conteúdo/comandos de perfis e não chama consoles. A prévia explícita continua obrigatória para criar. Uma mudança depois da consulta exige nova conferência.

Instalações novas incluem perfis-nativos.lock no .office/.gitignore. Arquivos .gitignore existentes são preservados; neles, confira essa entrada ao atualizar. Temporários .office-native-*.tmp ficam na pasta nativa durante a publicação e são removidos no fluxo normal; após uma interrupção do processo, confira temporários remanescentes antes de versionar o projeto.

Em Gestão, cada especialista tem uma ação **Perfil nativo**. **Conferir perfil** apresenta caminho, conteúdo e estado sem gravar; **Criar perfil conferido** cria somente um arquivo ausente, após conferir o hash das fontes e do destino. Perfis divergentes/personalizados não são substituídos. Lock, publicação exclusiva e repetição idempotente protegem criações concorrentes. Erros de arquivos/fontes exigem nova conferência. Não há início automático de agentes ou alteração de config.json, contas, settings, permissões, hooks ou modelos globais.

| Console | Definição por projeto | Particularidade |
|---|---|---|
| Claude | .claude/agents/office-ID.md | name/description, modelo explicitamente cadastrado quando presente; ferramentas/permissões não são ampliadas |
| Codex | .codex/agents/office-ID.toml | name/description/developer_instructions; não configura sandbox, MCP ou habilita multi-agent |
| OpenCode | .opencode/agents/office-ID.md | mode=all para uso principal/subagente; modelo cadastrado precisa ser explícito |
| Gemini | .gemini/agents/office-ID.md | kind=local significa agente executado pelo CLI, com modelo cloud do cadastro; não significa inferência Ollama |

O cadastro/política continuam canônicos. Perfil contém descrição curta derivada, hash de origem e comando para obter o contexto vigente pelo escritório, sem copiar o corpo de skills ou as regras comuns. O comando --contexto só retorna instruções quando perfil e fontes estão atuais. Regras por escopo e permissões continuam valendo; isso exige que o agente siga a instrução de consultar o contexto, não impõe um sandbox adicional. Se o console não puder executar Python ou acessar o aplicativo/projeto cadastrado, deve informar bloqueio. Configurações experimentais/descoberta dependem da versão do console, não são habilitadas pelo gerador. Reinicie/recarregue agentes para conferir descoberta. Perfis gerados referenciam os caminhos desta instalação; ao mover/clonar aplicativo/projeto, regenere com conferência. Arquivos do projeto principal não aparecem automaticamente em outros worktrees.

```powershell
python agentes_nativos.py --projeto D:/projetos/meu-app --funcionario ID
python agentes_nativos.py --projeto D:/projetos/meu-app --funcionario ID --confirmacao HASH_DA_PREVIA --aplicar
python agentes_nativos.py --projeto D:/projetos/meu-app --funcionario ID --contexto
```

A geração é cloud apenas. Perfil nativo local poderia iniciar subagentes fora do controle de RAM/CPU/slots/watchdog; use o despacho local gerenciado existente. Claude/Codex/Gemini sem modelo cadastrado herdam o padrão nativo. OpenCode sem modelo explícito é recusado, para não selecionar outro modelo por suposição. Selecionar perfil nativo manualmente não passa pelos gates/reservas/revisores do controlador nem comprova equivalência Team; despachos gerenciados continuam usando o contexto canônico e não selecionam estes arquivos automaticamente. Não exporte perfis de um cloud para outro nem use isso como prova de revisão independente.

Fontes oficiais consultadas: [Claude subagents](https://code.claude.com/docs/en/sub-agents), [Codex subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents), [OpenCode agents](https://opencode.ai/docs/agents), [Gemini subagents](https://geminicli.com/docs/core/subagents/). O formato foi testado nos quatro adapters. OpenCode 1.18.35 confirmou descoberta por agent list --pure em fixture, sem inferência; descoberta/execução nativa das outras três integrações e Team completo continuam pendentes.

### Consumo ligado às tentativas

Novos despachos e retomadas gerenciados encaminham o ID da tentativa ao coletor do launcher cloud/local. O ledger separado grava consumo e vínculo na mesma transação. Uma amostra já ligada a outra tentativa ou um registro antigo sem vínculo não são reatribuídos. Ausência de contadores continua desconhecida. Claude incremental, Codex exec/rollouts, Gemini e OpenCode run seguem os normalizadores existentes; plugin OpenCode externo ao launcher e consultas isoladas CEO/diretor/auditor não recebem vínculo de tarefa nesta etapa.

Gestão mostra quantas tentativas têm consumo observado, totais com cobertura por amostra e equivalente teórico de API quando as tarifas válidas e a identidade informada permitem. Na última tentativa há um detalhamento com os modelos observados. O modelo do grupo de duração continua sendo o configurado no despacho. Leitura é por projeto, em lote e somente leitura; IDs internos não aparecem na API. Erro do ledger não oculta as durações ou tarefas.

A janela é móvel de sete dias: despachos selecionados por início e amostras por data de registro. Uma tentativa longa pode ter parte do consumo fora dessa janela; contadores cumulativos seguem a data da primeira gravação. Esses números não medem qualidade, aceite, velocidade do modelo ou toda a atividade de filhos, e não autorizam merge. Equivalente de API não é fatura ou custo da assinatura; cotas permanecem por conta/fornecedor. Não há divisão de tokens por segundos ou por saídas zero para sugerir eficiência sem cobertura comprovada.


### Iniciar a equipe Codex com trabalho

`python iniciar_equipe.py --projeto CAMINHO --base origin/BRANCH --max-cartoes 2`
abre o CEO interativo com uma tarefa inicial: consultar o Kanban e o diretor, dividir
até dois cartões preparáveis e delegar pelo controlador `gestao_cli.py lote`.
A base é explícita e depende das regras de cada projeto. `--verificar` mostra
a tarefa sem consumir modelo. O padrão é um cartão; execução sequencial.

A sessão usa `workspace-write`, acrescenta a pasta do escritório e a pasta
irmã `worktrees` às permissões de escrita, e continua aberta depois do lote. O CEO precisa
conseguir executar Git, Python e GitHub CLI; permissões/login pendentes aparecem
no próprio console. Não é uma garantia de execução autônoma: bloqueios, falta
de cartões preparáveis ou erro do modelo interrompem o lote. Reservas antigas
não são retomadas automaticamente. Equipes são processos geridos pelo escritório;
não se pressupõe o recurso nativo de Agent Teams do Claude.

Na cena gerenciada, CEO e diretor ocupam mesas separadas na mesma diretoria.


No Windows, a versão 0.162.x do Codex pode falhar antes do comando com
`setup refresh had errors` e erro 32 ao validar `node_repl.exe` em uso.
Diagnostique pelo log `.sandbox/sandbox.*.log` do CODEX_HOME. Uma instalação
separada do CLI 0.160.1 permite testar compatibilidade mantendo o sandbox:
`codex sandbox -P :workspace -C CAMINHO powershell -NoProfile -Command Get-Location`.
A correção upstream está sendo acompanhada em https://github.com/openai/codex/issues/51601.
Não há downgrade automático no instalador. Ao usar uma instalação isolada,
selecione seu binário pelo PATH e defina `OFFICE_CODEX_SEM_DAEMON=1` para não
reutilizar o daemon de outra versão; modelos, política e credenciais permanecem
as configuradas. Verifique com `codex --version` e um comando real antes de despachar.

Para operação autorizada sem perguntas do Codex, defina `OFFICE_CODEX_AUTONOMO=1` no ambiente do launcher. Ele usa aprovação `never` e permite rede no `workspace-write` (necessária para GitHub), mantendo os limites de escrita. Comandos fora desses limites falham; não são escalados. Política do projeto, reservas, aceite, revisores e merge continuam passando pelos gates existentes. Não altera a configuração global do Codex. Reabra a sessão para aplicar.


### Acompanhamento ao vivo e pausas na cena

O acompanhamento fica na lateral do escritório 3D, junto à lista de agentes. Atualiza a cada dois segundos pelo estado local do projeto selecionado, sem chamadas de IA ou GitHub. Mostra somente a etapa do host e o tempo restante. Entregas e revisões ficam na aba PRs; avisos ficam em Alertas; detalhes de coordenação e bloqueios ficam na Gestão. O atalho abre apenas o CEO no console. `acompanhamento_ciclo.py` continua disponível para diagnóstico manual, sem abertura automática de janela.

A etapa permanece em **preparando** durante a validação do lote, do worktree e da reserva. Só muda para **implementando** ou **investigando** quando o controlador registra a tentativa de execução desse cartão. Essa etapa não comprova que o processo nativo já iniciou: a atividade do console é conferida separadamente nos registros da Gestão. Uma falha antes do registro não anuncia trabalho da equipe.

Os personagens livres usam as áreas existentes de café/refeitório, banheiro e diversão, com as mesmas rotas e animações do Claude. Não cria eventos, sessões, tarefas ou consumo de IA. Reservas em execução, preparação ou estado desconhecido impedem pausas; revisão e bloqueio continuam visíveis durante o lazer. Eventos reais ou um despacho pedem retorno à mesa. CEO e diretor ficam na diretoria enquanto o ciclo está em andamento. Dados indisponíveis ou vencidos interrompem o lazer e exigem conferência; não liberam reservas. Pausas visuais não comprovam console ativo, ausência de bloqueio, implementação ou entrega.

O modo legado sem projeto gerenciado mantém as regras anteriores. Replay e demonstração não recebem projeções do ciclo atual. Fechar o navegador ou o CEO não encerra o controlador nem equipes. Não há retomada ou novo lote pelo acompanhamento.


### Duração e revisão configuradas no painel

Em Engrenagem → Gestão → CEO e diretor, **Configurar duração do ciclo** salva entre 1 e 240 minutos para o próximo início, na política única do projeto. Não inicia nem estende sessão atual; o host mantém o limite persistido mesmo após essa edição. Ciclos abertos antes desta atualização precisam terminar antes de salvar uma duração diferente. Outras mudanças de política continuam exigindo conferência entre ciclos.

**Configurar revisão deste projeto** mostra revisores habilitados. Revisores suspensos não contam para fornecedores disponíveis. Ao salvar, confere quantidade, separação do autor para as equipes e requisitos do auditor; falha não grava e informa a causa. Erro de gravação é distinto de configuração inválida. Checks e merge permanecem obrigatórios.


### Metas por cartão: tempo e tokens

Despachos cloud Codex, OpenCode e Gemini recebem descrições somente das skills
selecionadas e validadas no cartão, consultadas na raiz canônica. As demais
skills continuam disponíveis para exigências das regras, sem inserir todo o
catálogo no prompt de cada tentativa. Instruções canônicas, hashes, limites e
ativação obrigatória permanecem. Consoles sem despacho e Claude preservam o
contexto anterior.

Em Engrenagem → Gestão → CEO e diretor → **Configurar metas por cartão**, habilite as metas e escolha o tempo por tentativa do agente (1..240 minutos) e os tokens observados (1.000..10.000.000). Salve com ciclo e tarefas parados. A política `metas` é única em `.office/projeto.json`, desligada por padrão no instalador; não inicia trabalho ao salvar. Limites valem para novos despachos, sem modificar reservas ou tentativas anteriores. Revisão independente preserva seus gates e não utiliza a janela do agente autor.

O cartão mantém objetivo, escopo, aceite, Time e dependências. A fonte `fontes.produto` deve conter seções `#### Objetivo N — descrição` e referências `#numero` aos cartões; um cartão novo pode declarar `**Objetivo GDD:** N` (ou `Objetivo N`, ou o título exato da seção). Vínculo ausente, ambíguo ou divergente bloqueia a preparação: o diretor deve esclarecer o cartão, sem inventar metas. O despacho guarda hashes do cartão/GDD e o trecho do objetivo; mudanças passam pela conferência existente.

Em **Trabalho e indicadores → Metas por cartão**, consulte os recibos por tentativa: objetivo GDD, limites, consumo observado, revisão e motivo de bloqueio. Os arquivos locais ficam em `dados/gestao/ID/metas/TENTATIVA.json`. São metas do controlador, compatíveis com Claude, Codex, OpenCode e Gemini, sem exigir recurso nativo de meta. Modelos locais passam pela mesma vigilância quando o perfil permite execução.

Tempo atingido interrompe a árvore do console iniciado pelo launcher. Tokens são entrada (incluindo cache) e saída conforme o ledger observado, sem somar cache novamente. O monitor confere a cada segundo e também ao retorno; orçamento atingido impede encaminhar entrega, mesmo com saída zero. Não retoma automaticamente. Ausência de contador permanece não informada; contagem parcial é identificada. O limite de tokens não garante teto de cobrança nem cobre trabalho não observado de filhos: Em uma execução Codex nova com metas, o host lê os `token_count` incrementais do rollout da identidade exata recebida em `thread.started`, sem republicar os eventos do stream. O saldo final de `turn.completed` compartilha o contador e acrescenta somente diferenças, inclusive quando o transcrito não está disponível. Retomadas e execuções sem metas preservam o fluxo anterior. Se o transcrito não fornecer contadores válidos, Codex pode informar uso apenas no `turn.completed`; OpenCode informa em `step_finish`. Uma chamada pode ultrapassar o limite antes da informação chegar. Referências: [eventos oficiais do Codex](https://github.com/openai/codex/blob/main/sdk/typescript/src/events.ts) e [CLI oficial do OpenCode](https://opencode.ai/v2/docs/cli/commands/).

Uma tentativa com PR vai para revisão, sem declarar aceite ou merge. A meta só aparece como entregue quando o controle existente registra a conclusão após os gates. Falha de monitor/persistência é incerta e exige conciliação. Desabilitar não remove histórico nem modifica os gates. Veja [decisão de arquitetura](ADR-METAS-CARTAO.md).

### Recuperar a coordenação interrompida

Um ciclo em erro não é reiniciado pelo atalho. Após conferir tarefas e recibos,
o host aceita `controlador_local.py --projeto <raiz> --acao conciliar-ciclo
--arquivo <pedido.json>`. O pedido UTF-8 contém `{"versao":"<SHA256 dos bytes
atuais de dados/gestao/<id>/ciclo.json>","nova_janela":false}`. O host recusa
processos ainda presentes, inventário indisponível, reservas em execução,
tentativas sem retorno, ocupações e lotes sem encerramento confirmado.
Preserva tarefas, reservas, PRs e uma cópia imutável do estado anterior em
`dados/gestao/<id>/ciclos`. A conciliação apenas pausa a coordenação; não despacha
equipes. `nova_janela:false` mantém o prazo anterior. `true` autoriza um próximo
início com a duração configurada, inclusive quando a janela anterior expirou.
Depois da conciliação, abrir o atalho ou enviar a ação `ciclo` inicia uma nova
coordenação pelo quadro vivo, sem retomar reservas antigas.

### Operação contínua

Em Gestão → CEO e diretor → Configurar operação automática, habilite o modo
contínuo para o próximo ciclo. Exige metas por cartão habilitadas. A política
`ciclo.continuo` tem padrão `false`, inclusive nas instalações existentes.
Quando habilitada, o próximo início não tem prazo global; cada tentativa mantém
seus limites de tempo e tokens. São até dois cartões por seleção e execução
sequencial. Sem mudanças no quadro, PRs, reservas, documentos ou recursos, o host
espera sem chamar modelos. Falha de provider, autenticação, consulta ou execução
incerta encerra a coordenação com a causa registrada; não repete trabalho.

O botão **Pausar após o despacho atual** registra um pedido para a sessão exibida.
O cartão em execução termina pelo controlador, com seus gates, antes de pausar
novos despachos. Na espera, a pausa é percebida em até cinco segundos. Consultas
já em curso terminam antes dessa conferência. O acompanhamento mostra etapa e
“Operação contínua”, sem prazo fictício. Alterar modo/duração vale para o próximo
início; não transforma uma sessão limitada em contínua nem a reinicia.

### Planejamento de vínculos ainda incertos

Uma implementação continua exigindo um objetivo numerado existente no GDD.
Para resolver vínculos incertos, a subtarefa de classificação criada pelo host
pode ter uma meta de planejamento: recebe os objetivos canônicos com origem e
hash, sem presumir um número. Exige o recibo local concluído de criação, o mesmo
cartão, pai, equipe, título, objetivo, aceite, skills e escopo de investigação.
Um marcador colado numa issue comum não habilita essa exceção. A entrega é uma
decisão documentada com evidências e PR, pelos mesmos gates. Não implementa nem
encerra o pai e não altera seu aceite. Nos campos de skills, a declaração inteira
`nenhuma` significa ausência de skill adicional; nomes desconhecidos numa lista
continuam sendo recusados. As regras canônicas do projeto continuam aplicáveis.

Quando uma decisão prepara uma subtarefa leve, o ciclo consulta imediatamente
seu cartão no quadro vivo e pede sua classificação ao diretor, antes de continuar
a varredura. Ela precisa estar no Backlog, manter a prioridade do pai e passar
pela preparação comum, incluindo reservas, recursos, skills e meta. A resposta
é validada e registrada separadamente. Só entra no despacho se o diretor aceitar
executar com recurso leve; usa os mesmos worktrees, lote, limite de dois cartões
e gates. Não encadeia criação de subtarefas nem retoma reservas bloqueadas.
Investigações despachadas aparecem com essa etapa real no acompanhamento.

### Proteção contra orçamento insuficiente

No ciclo automático, um primeiro despacho encerrado por limite de tempo ou tokens
pode ser seguido por trabalho independente. Dois despachos consecutivos com
retorno confirmado `124` e motivo `limite_tempo` ou `limite_tokens` encerram o
ciclo em erro, com os recibos preservados e uma ação para ajustar as metas no
painel. Um retorno diferente zera essa sequência. A proteção não muda o orçamento,
não cria sub-issues para contorná-lo e não retoma reservas. Depois de conferir a
causa, salve a configuração com tarefas paradas e inicie explicitamente outro
ciclo. Tokens de entrada em cache também contam: contexto grande pode consumir
o orçamento em poucas chamadas, mesmo com pouca saída.

### Publicação da revisão dos providers

O gate obrigatório `sugestoes` também é conferido por projeto, a cada três
minutos, no commit e base atuais. O verificador consulta todos os comentários
e revisões do PR com paginação, sem janela de dias nem chamada de modelo.
Comentários `[revisor-ia]` e bots habilitados na política entram na caixa de
sugestões já existente; decisões do líder são preservadas. Cabeçalhos de cobertura
sem achados não viram pendência; os achados da revisão ficam nos comentários
em linha. Pendências publicam `pending`; ausência de pendências após conferência
publica `success`. Falha de API, mudança de política/commit/base ou PR rascunho
impede a publicação. Os recibos ficam na caixa isolada do projeto (`gate-N.json`).

Comentários ou revisões editados têm a evidência novamente conferida: mudança
de conteúdo reabre a sugestão, sem reaproveitar uma decisão tomada sobre outro
achado. Conteúdo inalterado preserva a decisão e não duplica itens.

Essa conferência decorre de `merge.checks` exigir `sugestoes`: desligar bots extras
e triagem paga não dispensa o gate nem desativa a leitura das revisões internas.
Projetos sem esse check e o fluxo legado preservam o comportamento anterior.
Não resolve ou ignora achados automaticamente, não faz merge e não substitui
revisão por IA, arquitetura, build ou outros gates.

Quando o projeto usa merge automático e exige `revisor-ia`, o despacho publica
a revisão independente aprovada antes de encaminhar o cartão para revisão no
Kanban. Usa o relatório já produzido pelos revisores cadastrados, sem uma nova
chamada de modelo. Exige recibo local, cobertura da política atual, commit e base
exatos, PR aberto sem rascunho e repositório do projeto. Publica um comentário
de revisão com os achados e o status `revisor-ia` somente após essas conferências.
Não faz merge nem substitui outros checks obrigatórios.

O recibo fica em `dados/gestao/ID/revisoes_github`. Mudança de commit, base,
política ou relatório interrompe a publicação. Falha depois de iniciar uma
operação externa deixa o recibo incerto e bloqueia o despacho; confira no GitHub
antes de conciliar, sem repetir automaticamente. Uma publicação confirmada não
duplica comentários. Revisão desativada não publica sucesso. Projetos com merge
manual ou sem esse check preservam o fluxo anterior, assim como o revisor Claude
legado configurado em `config.json`. Reservas antigas não são retomadas.


### Devolutiva de revisão para a equipe

Uma revisão reprovada retorna `motivo: revisao_reprovada` e uma `devolutiva` com
PR, commit, equipe, ação e achados completos. Achados verificados levam à ação
`corrigir`; indisponibilidade, cobertura incompleta ou falta de achado verificável
levam a `conferir_revisao`. Falha do revisor não deve gerar uma implementação fictícia.

O publicador do host aceita atualizar o mesmo PR: o pedido habitual
(`cartao`, `worktree`, `titulo`, `corpo`) recebe `pr` e `head_sha`. A reserva precisa
estar em execução, com contexto da política atual e entrega registrada nesse commit.
PR fechado, rascunho, commit divergente ou outro branch/repositório são recusados
antes do commit. O push é normal, sem force; o recibo original fica preservado e
a atualização recebe recibo próprio. Sem confirmação remota, não repetir.

Esses mecanismos não autorizam retomar reservas históricas nem dispensam nova
revisão do commit corrigido. Em Gestão → Configurar operação automática, `Correções automáticas por cartão`
permite de 0 (desligado, padrão) a 2. Configure com o ciclo pausado. Para novos
despachos Codex/OpenCode com metas ativas, uma revisão reprovada com achados
verificados pode acionar a mesma equipe em contexto novo, no mesmo worktree e PR.
O processo anterior precisa ter retorno confirmado e nenhum agente filho observado.
Cada tentativa fica registrada; tempo e tokens somam todas as tentativas, sem novo
orçamento. Medição incompleta, erro do revisor ou limite atingido deixam bloqueio
para conciliação. Reservas anteriores ao novo ciclo não são retomadas automaticamente.


### Fila de PRs, referências seletivas e recuperação

Em Gestão → CEO/diretor → Configurar operação automática, `max_prs_pendentes`
limita todos os PRs abertos do projeto antes de selecionar outro cartão, inclusive
rascunhos e PRs de ciclos anteriores. Zero desativa; de 1 a 20 habilita. A espera consulta conclusão pelo
mecanismo existente, sem inferência nem despacho. Merge confirmado libera a
fila. A consulta REST existente confere a fila do projeto sem chamar o diretor
ou criar novos worktrees enquanto atingir o limite. Conclusão recusada fica pendente para conferência em PRs/Alertas; não
reduz gates. PRs históricos e externos não são adotados nem retomados por essa
fila, mas também impedem acumular novas entregas: exigem conciliação explícita.
Alterar o limite exige ciclo pausado.

Ao atingir a fila, o diretor classifica cada PR no commit atual: revisar provas,
corrigir o PR, propor etapa vinculada ou aguardar. O pacote contém corpos dos
PRs/cartões e diagnósticos do mesmo commit. Também recebe checks e statuses
remotos do head atual, com cobertura conferida:
o relato antigo do corpo do PR não substitui esses estados. Check de build
aprovado não comprova automaticamente benchmark, Drive ou Validate locais.
O recibo em dados/fila_prs guarda a classificação por hash do contexto;
sem mudanças, não há nova inferência.
Consulta interrompida exige conferir o recibo, sem repetição automática.
A classificação é preparação: não aprova merge, não muda o aceite do pai,
não cria cartão nem retoma reserva histórica. Etapas vinculadas ainda exigem
vínculo formal, validação de recursos e despacho próprio pelo controlador.
Na aba PRs, cada PR pode mostrar o encaminhamento da última classificação
do diretor: equipe, ação, objetivo, aceite e evidências faltantes. Só aparece
para o mesmo commit e política; mudança de commit ou política exige nova
classificação. É proposta de preparação, sem comprovar despacho ou aprovação.
Os checks continuam sendo conferidos na seção de evidências do PR.

Com criação de subtarefas habilitada, uma fila cheia pode receber uma preparação
independente para um PR parcial com encaminhamento `etapa`. O diretor recebe
fontes completas e precisa aprovar uma entrega útil com aceite próprio; pode
dispensá-la. O host só cria se houver um pai inequívoco no Kanban, prioridade
válida, autor com retorno/encerramento registrados e nenhuma sub-issue aberta.
O cartão usa o criador e as reservas existentes, menciona PR/pai e preserva o
aceite original. Só essa preparação leve pode passar pela fila; o backlog
normal permanece em espera. Há nova classificação do diretor antes do lote.
O despacho usa escopo planejamento, worktree novo, metas e gates normais.
Quando o GDD já comprova o objetivo do pai/prioridade, a preparação preserva
esse número. O marcador de classificação pendente só é usado para vínculo incerto.
Não implementa nem regenera o pai, não retoma sua sessão, não troca seu orçamento
e não aprova o PR parcial. A etapa real continua exigindo validação própria.
Consulta/criação incerta não é repetida; um recibo criado precisa continuar
compatível com o cartão, PR e política. Não há criação em cascata nessa passagem.
Mudanças incidentais no envelope REST do Kanban não invalidam uma preparação
já criada. Equipe, prioridade, etapa, status, corpo/aceite do pai, commit,
política e fontes continuam sendo conferidos antes de reconhecer o mesmo filho.

`memoria_referencias` (0 desativa, até 5) inclui nos novos despachos Codex/OpenCode
referências estruturadas a entregas com conclusão registrada por merge, do
mesmo projeto, objetivo e hash do GDD, com ao menos um gate registrado e todos
os gates aprovados. Inclui origem, PR, commits e hash da
prova; texto longo permanece na fonte, sem carregar transcritos ou inventar
lições. Não altera skills, regras ou aceite, não comprova a tarefa atual e não
faz chamadas de modelo para indexação. Alterar exige ciclo pausado. Essa é uma
memória inicial de entregas; aprendizado de decisões e promoção de skills
continuam dependendo de evidências e validação.

Em Trabalho, cada tarefa mostra um resumo de recuperação derivado do diário:
branch e vínculo do worktree, última tentativa/retorno, PR/commit registrado,
compatibilidade da política e próxima ação. Não lê o checkout principal,
retoma processos ou publica novamente. Caminhos absolutos, sessões e tokens
privados não são expostos. A prévia e a confirmação de retomada existentes
continuam obrigatórias, assim como a conferência de agentes/ferramentas.
Correções de revisão aparecem separadamente nas métricas de tentativas.

Na ficha da mesa, a aba Trabalho também apresenta esses cartões e checkpoints.
O vínculo segue o projeto selecionado e a equipe ou ID cadastrado do funcionário.
A consulta é compartilhada, com cache de 30 segundos, somente enquanto houver
ficha aberta. Estado da reserva e console observado aparecem separadamente;
consulta indisponível não interrompe equipes nem reaproveita dados antigos como
estado vivo. O botão abre a Gestão existente para conferência assistida.


### Entregas em revisão após reiniciar

Iniciar outro ciclo preserva os vínculos privados das entregas com retorno único
confirmado (revisão, código zero). O registro completo anterior fica em
`dados/gestao/<projeto>/checkpoints/<ciclo>.json`. Isso conserva o acompanhamento
do merge, sem retomar autores, reservas bloqueadas ou publicação. O limite de PRs
pendentes considera essas entregas antes de permitir novos despachos. A conclusão
continua exigindo merge confirmado, política compatível, vínculo e gates atuais.
Checkpoint divergente ou sem retorno confirmado impede o novo início e pede
conferência na Gestão. Os arquivos privados não são expostos no painel.

A caixa de sugestões por projeto usa exclusão do sistema operacional: uma queda
do processo libera a trava. O arquivo `.trava-so` persistente não significa
processo ativo. Marcadores `.trava` de instalações anteriores continuam bloqueando
até recuperação assistida: parar os serviços, verificar que não há processo
usando a caixa, preservar o marcador para diagnóstico e só então removê-lo.
Nunca remover uma trava apenas pela idade. O protocolo do Claude legado permanece.

O motivo mostrado pertence à etapa atual. Ao sair da espera para consultar, preparar ou executar, o motivo antigo é removido; bloqueios novos continuam explícitos. A criação de worktree aparece como preparação, antes de validar e registrar a execução.

No ciclo, uma entrega de planejamento também exige registro versionado e PR do cartão. Comentários e sub-issues são evidências úteis, mas não substituem a entrega por merge. O registro documenta fontes, decisões, limites e próximos cartões, sem implementar o pai ou alterar seu aceite. Se a publicação falhar, os registros existentes são preservados e a reserva fica bloqueada para recuperação assistida.

Próximos cartões criados durante planejamento devem usar os campos canônicos de objetivo, aceite, escopo, skills, dependências explícitas e objetivo GDD, além de equipe, prioridade e etapa no Kanban. Dependência escrita apenas em prosa não deve substituir a declaração processável. O controlador não presume aceite ou classificação ausentes.

A classificação dos PRs recebe a preparação vinculada já registrada pelo host e as sub-issues reais do pai. Uma preparação concluída por merge é contexto histórico; não comprova o aceite do pai, mapa ou benchmark. Reservas bloqueadas e campos canônicos ausentes aparecem como lacunas, sem autorizar retomada. Vínculo, política, fonte ou head divergentes não são reaproveitados como prova.

Quando há prova de entrega da preparação, seus documentos Markdown em docs/ são lidos no commit exato, com origem e hash. Conteúdo, tamanho e blob Git são conferidos; arquivos sem extrato são inventariados. O limite exige seleção explícita em vez de truncar evidências.
