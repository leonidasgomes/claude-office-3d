# Legado e nova versão

## Qual versão baixar?

- **Codex e OpenCode, gestão de equipes e funcionários:** use a
  [prévia atual 2.0.0-dev.7](https://github.com/leonidasgomes/claude-office-3d/releases/tag/v2.0.0-dev.7).
  O pacote inclui Gestão, metas, checkpoints e recuperação assistida com saldo
  preservado, além do zoom e atalho do instalador Windows. A instalação não
  inicia tarefas nem retoma reservas bloqueadas automaticamente.
- **Continuar no Claude legado:** use
  [1.19.1 estável](https://github.com/leonidasgomes/claude-office-3d/releases/tag/v1.19.1).
- As prévias anteriores permanecem no histórico; seus ZIPs não recebem as
  correções das versões seguintes. Baixe o ZIP `office-multi-provider-...zip`
  em Assets da versão escolhida; Source code é o código-fonte.

O selo **Latest** do GitHub indica a versão estável do legado. A prévia 2.x
fica marcada **Pre-release** e deve ser instalada em uma pasta separada.

| Linha | Instalação | Situação |
|---|---|---|
| Claude 1.x | Pasta existente do usuário | Legado preservado, sem atualização automática para outra edição |
| Office Multi-provider 2.x | Pasta nova escolhida no instalador | Adapters e gestão por projeto, com dados e porta próprios |

O legado histórico não é backup dos dados/configurações da instalação atual.
A distribuição nova não copia bancos, credenciais ou config pessoal. Projetos
e hooks existentes não são migrados automaticamente.
Escolha apenas uma instalação para operar um mesmo banco/servidor. Antes de migrar,
faça backup, configure portas/bancos separados e revise os caminhos dos hooks.
Hooks apontando para a instalação anterior continuam escrevendo nela. Na nova
linha, o launcher informa ao hook deste escritório o caminho e a sessão que observa.
Esse hook deixa de repetir ferramentas comuns e Stop da sessão principal; filhos,
mensagens e relações Agent/Task continuam no hook nativo. O filtro exige caminho
e sessão iguais, e não afeta scripts de proteção como Guardian. Hooks antigos
ainda não conhecem esse protocolo: devem ser revistos na migração para evitar
misturar as duas instalações. A TUI não herda a propriedade do stream.

O pacote novo inclui `EDICAO.json`, identificando a linha Office Multi-provider.
O instalador recusa copiar, revisar ou remover hooks de uma instalação antiga
ou ambígua. Marcador inválido e VERSION fora de 2.x também bloqueiam a operação.
Não acrescente esse marcador ao legado para forçar atualização. Essa identificação
separa as edições; não é uma assinatura de integridade ou backup. O build novo usa
`office-multi-provider-v<VERSION>.zip`, com a versão também na pasta dentro do ZIP.

Para começar um projeto em instalação nova, use `iniciar_projeto.py` conforme
README. Ele prepara tanto a pasta do escritório quanto a política do projeto,
com prévia por padrão, preservando arquivos existentes de instruções e contas.

## Limites desta prévia

A dev.7 inclui a qualificação da release no commit exato, atualização conservadora
e a jornada instalada determinística. Atualizar uma instalação existente está
qualificado somente em Linux com permissões comuns; ACLs e metadados especiais
bloqueiam a troca. Instalação nova permanece portátil. Veja
[atualização e recuperação](ATUALIZACAO.md) antes de aplicar e preserve um backup.

No Linux, novos corpos de snapshots da galeria ficam fora do SQLite; Windows e
macOS mantêm o armazenamento inline anterior. Bancos antigos acima do limite
não são migrados nem compactados. Transportar snapshots externos entre sistemas
operacionais ainda não é suportado. Veja [galeria](GALERIA_ENTREGAS.md).

A jornada instalada usa aplicativo, HTTP, processos, SQLite e worktree reais em
ambiente controlado, mas simula as fronteiras externas de provider e GitHub.
Ela não comprova a operação integral com contas/modelos reais. Gates nativos
Linux em produção permanecem indisponíveis; o fluxo bloqueia sua execução/publicação.

## Claude novo

O painel da nova linha usa o título padrão `Office Multi-provider`; um `titulo`
personalizado na configuração continua tendo prioridade. Claude, Codex, Gemini
e OpenCode pertencem à mesma edição e seguem a política comum do projeto.

O revisor isolado Claude usa `--safe-mode` com ferramentas vazias e MCP estrito,
sem persistência de sessão. Isso preserva autenticação normal; `--bare` não lê
OAuth e deixou de ser usado por esse adapter na nova linha. Requer suporte às
flags verificadas no CLI; não usa fallback sem isolamento. Políticas gerenciadas
administrativas continuam aplicáveis. A execução normal do launcher mantém seus
hooks e skills; safe-mode é específico do revisor sem ferramentas.

```powershell
cd D:/escritorios/meu-app
python console_provider.py --provider claude --projeto D:/projetos/meu-app --detectar
python console_provider.py --provider claude --projeto D:/projetos/meu-app --mesa Dev
python console_provider.py --provider claude --projeto D:/projetos/meu-app --mesa Dev --prompt "Examine o estado sem editar arquivos"
```

Sem prompt, abre a TUI. Com prompt, usa `-p --verbose --output-format stream-json`,
envia tarefa e referências compartilhadas por stdin e recebe sessão principal,
mensagens, início/fim de ferramentas e resultado pelo adapter comum. `--sessao`,
`--modelo` e `--agente` continuam nativos. Não acrescenta bypass de permissões nem
`--bare`. Uma sessão nova gerenciada recebe UUID por `--session-id`; a identidade
real para gestão continua sendo confirmada pelo envelope init. Skills nativas
continuam descobertas pelo Claude; o catálogo aponta para
as fontes configuradas, sem copiar seu conteúdo. Hooks/permissões de skills não são
convertidos automaticamente para outros providers.

Tipos desconhecidos, pensamento e envelopes filhos são ignorados pelo adapter do
pai. Teams interativos ainda dependem de sua configuração e telemetria nativas.
Um `result` principal com `is_error: true` retorna falha ao despacho mesmo se o
processo devolver zero; códigos nativos diferentes de zero são preservados.
Falha de vínculo/persistência ou outra exceção do launcher encerra e recolhe o
processo iniciado, preservando a exceção. A coleta não enumera todos os processos
descendentes cloud: antes de retomar uma execução interrompida, concilie sessões
e agentes nativos. Isso não autoriza concluir cartão, revisar ou fazer merge.
O custo Claude acumulado de conversa não é lançado como custo de cada execução.
Os contadores disponíveis entram no ledger comum por incremento, com vínculo
às novas tentativas gerenciadas; histórico sem vínculo não é reatribuído. Preço
teórico de API depende de tarifa/modelo compatíveis e não representa a fatura
ou o limite semanal da assinatura. Testes locais usam um subprocesso
e SQLite reais com envelopes sintéticos; não comprovam uma inferência cloud autenticada.

Contrato oficial: [Claude headless](https://code.claude.com/docs/en/headless),
[hooks](https://code.claude.com/docs/en/hooks) e
[CLI](https://code.claude.com/docs/en/cli-reference).
Para os outros consoles, veja [PROVIDERS.md](PROVIDERS.md); as regras de projeto
continuam em [GESTAO.md](GESTAO.md). A versão permanece uma prévia pública,
sem migração automática dos projetos existentes.

### Confirmação de conclusão na nova linha

Claude estruturado agora exige init e result principal success/is_error false da mesma sessão antes de devolver sucesso. Processo zero sem result, resultado de filho ou sessão diferente bloqueia a entrega. Trabalho principal que segue um resultado exige novo resultado final. Isso alinha a confirmação aos outros providers; não comprova que todos os filhos terminaram, nem aprova revisão/merge. TUI, hooks/team e edição legada permanecem preservados.

## Qualificação da publicação

A publicação de uma nova tag `v2.x.y-<prévia>` chama o mesmo workflow de CI
usado pelos PRs, no commit exato da tag. Os testes principais, a preparação
Windows e toda a matriz Python precisam terminar com sucesso. Resultado
ausente, falho, cancelado ou ignorado bloqueia a publicação; um CI antigo de
outra branch não serve como aprovação. Os testes de WebGL e isolamento Linux
continuam experimentais e separados, sem promessa de validação da máquina real.

Antes de publicar, o job confere `VERSION`, `EDICAO.json`, commit qualificado,
conteúdo integral do manifesto no ZIP e SHA-256, e inicia a API a partir do ZIP
extraído em diretório temporário. Só a linha 2.x com sufixo de prévia é aceita.
A tag remota precisa ser uma **tag leve**, apontando diretamente ao mesmo commit;
tags anotadas são recusadas explicitamente. A tag é conferida novamente antes
da escrita. Não mova tags durante uma publicação; a verificação não substitui
as permissões e proteções do repositório.

A release nova fica como **Pre-release**, com `latest=false`. Uma release já
existente só pode ser completada se for a pré-release pública da mesma tag e
estiver sem assets. Assets existentes nunca são substituídos. Falhas de rede,
permissão ou rate limit não são interpretadas como release inexistente. Se um
upload terminar parcialmente, o próximo disparo bloqueia; revise os assets
manualmente em vez de sobrescrevê-los. A linha estável 1.19.1 permanece separada.

Apenas o job de publicação tem permissão `contents: write`; o CI usa leitura.
Não há cache, upload de artifacts de CI, segredo novo ou executor pago adicional.
A qualificação local usa `python -W error ferramentas/testar_qualificacao_release.py`
e `python -W error ferramentas/testar_build.py`, sem publicar tags ou releases.
A criação de uma tag real continua sendo uma decisão explícita de lançamento.
