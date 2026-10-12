# Jornada integrada instalada, sem serviços reais

Execute `python ferramentas/testar_jornada_instalada.py --evidence /tmp/office-e2e-evidence` em Linux.
Python e Git locais são os únicos pré-requisitos. O teste usa biblioteca padrão,
cria seu próprio ambiente temporário e não precisa de tokens, login, rede ou créditos.
Os arquivos de evidência não são publicados automaticamente.

## O que a jornada comprova

- Instalação real do pacote em pasta vazia, `.venv`, segunda instalação idempotente
  e preservação de um arquivo de configurações alheio.
- Configuração de projeto pelo assistente real; criação de worktree pelo controlador,
  com recibo real; branch/base e remoto Git bare exclusivamente locais.
- Despacho real, subprocesso OpenCode **sintético** versão 2, escrita de arquivo,
  stream e confirmação de export pelo código de produção.
- SIGINT real no launcher após checkpoint commitado; encerramento do grupo de
  processos lançado; reserva bloqueada, tentativa original preservada.
- Retomada por prévia/confirmação real: mesma reserva e sessão, **nova tentativa**.
- Publicação pelo host enquanto a tentativa está ativa: commit/push Git locais,
  criação de PR pelo executável `gh` **sintético**, recibo com token/tentativa/SHA.
- Captura de entrega imutável a partir do objeto Git, recuperação de falha real de
  SQLite e deduplicação sem novo push/PR.
- Revisão real do diff/contexto pelo controlador, com respostas **sintéticas** na
  fronteira de inferência. Nunca executa Claude/Codex reais.
- Gate nativo Linux permanece indisponível. O teste alcança sua verificação real
  de elegibilidade e exige bloqueio visível, nenhum worker e nenhum recibo de gate.
  Não altera `sys.platform`, regras, política de produção ou implementação do gate.
- Consumo por tentativa, deduplicação de eventos e preservação do resultado da tentativa interrompida. As mensagens 401/429
  originais ficam no stdout capturado pelo teste, sem alegar diagnóstico remoto real.

Um pedido JSON em disco passa pelo despachante real do controlador. Uma cópia
exata e não rastreada dentro do worktree deve ser excluída do commit pelo host;
o recibo e a árvore Git comprovam essa exclusão.

A publicação é chamada pelo invólucro de teste depois do retorno comprovado do
launcher, antes do retorno ao controlador de despacho. Isso testa o host real,
mas não prova que um modelo decide invocá-lo corretamente. O modo OpenCode não
recebe atualmente o mesmo prompt de publicação do host que o modo Codex.

O autor declara `cloud=synthetic-author` apenas no projeto sintético. O catálogo
zero-preço não atesta fornecedor real: esta identidade nunca deve ser copiada
para a configuração de um modelo real nem usada para afirmar diversidade real.

## Limites e segurança

PATH contém apenas Python/Git e os executáveis de fronteira sintéticos. HOME/XDG,
settings e Git config são isolados; credenciais, proxies, configurações do usuário
não são herdados. Um audit hook bloqueia conexões/resolução de nomes em todos
os processos Python da suíte. Git aceita somente protocolo `file`; o `gh` falso rejeita qualquer
rota não listada e duplicação de PR. A suíte não instala software, não modifica
contas, não cria repositório externo e não toca projetos pessoais existentes.
As pastas temporárias são removidas somente após o teste; `--evidence` conserva
logs, fronteiras executadas e resumo de aceitação, com as três faixas de resultado
separadas. O manifesto inclui todos os arquivos do pacote na origem e na
instalação, atalhos gerados, hashes do teste/CLI/documentação e módulos carregados
até o fim da suíte. Metadados Git de uma cópia local não substituem esses hashes.
Timeouts/falhas recolhem somente grupos próprios identificados por PID/PGID e
tempo de início, antes de remover as pastas temporárias.

O teste não usa mocks de funções de produção. A falha de captura é induzida por
um trigger SQLite que aborta INSERT no manifesto; remover apenas esse trigger
permite recuperar a mesma tentativa/PR/SHA pelo comando real de registro.

Há três resultados independentes:

1. **Jornada determinística instalada:** passa/falha, processos/Git/SQLite reais e
   respostas externas sintéticas.
2. **Provider real:** não executado; requer verificação atual de modelo declarado
   zero-preço, disponibilidade e permissão limitada. Sem fallback.
3. **Publicação GitHub real:** não executada; exige autorização específica para
   issue/cartão, branch, PR não-rascunho e eventuais notificações/reviews/status.

A suíte não altera o comportamento de PRs para forçar sucesso. O host atualmente
cria PR não-rascunho, e revisão/gates não adotam rascunhos. Não faz merge.
Uma revisão sintética aprovada não é aprovação humana/visual nem aceite do usuário.
Um bloqueio Linux esperado não é aceitação de um gate Linux de produção.

## Lacunas deliberadas

Não há navegador, screenshot, download de instalador publicado, autenticidade de
release, provedor real, conectividade GitHub real, gate Linux executável, merge
ou deploy. Essas provas não podem ser inferidas de um resultado verde desta suíte.
Falhas de API/provedor são estímulos sintéticos, não incidentes reproduzidos em
serviços reais. A revisão independente e o CI do SHA final continuam obrigatórios.

Depois da atualização de instalação/rollback ser incorporada ao main, execute a
suíte novamente no SHA final e conserve `source-manifest.json`, `acceptance.json`,
`install.log` e `tests.log`. Não trate a execução em uma base anterior como prova
integrada da atualização posterior.

A etapa principal Linux do CI executa esta suíte após os testes de instalação,
com falhas propagadas pelo código de saída. Não há novos runners ou permissões.
