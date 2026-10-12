# Gate Linux: validação nativa experimental

O gate de produção permanece bloqueado no Linux e informa o motivo na lista de
pendências. Este diretório prepara um executor supervisionado e provas nativas,
mas ainda **não habilita** execução/publicação de scripts de projetos no Linux.
O fluxo Windows e a exigência de status novo compatível não foram alterados.

A suíte usa o CLI oficial Codex 0.159.2, sem modelo, conta ou autenticação, em um
runner padrão `ubuntu-22.04` de repositório público. O pacote exato é instalado
via npm ci e lockfile com integridade, em diretório efêmero, com scripts de
instalação desativados. A evidência inclui hashes do launcher e binário nativo. Não altera
AppArmor, sysctl, sockets, permissões do sistema ou configuração persistente.
Não usa cache nem armazenamento de artifacts. O job tem `contents: read`,
checkout sem credenciais persistidas e limite de dez minutos. Nenhum script de
projeto real ou publicação de relatório/status é executado.

`adapter.py` usa o sandbox oficial com perfil explícito, sem herdar `:workspace`:
- leitura `:minimal` do runtime Linux e dos caminhos explícitos do Python/CLI/probe;
- escrita somente no worktree, temporário e objetos sintéticos separados;
- metadados Git e diretórios de regras em leitura;
- proxy ativo para `api.github.com` e `github.com`, sem SOCKS/UDP/upstream,
  acesso local, Unix sockets adicionais ou listener não-loopback;
- ambiente construído por lista, sem copiar tokens/credenciais da conta.

`:minimal` inclui diretórios de sistema como `/etc`; isto NÃO é uma garantia de
sigilo para qualquer host. A fixture usa HOME e CODEX_HOME vazios e recusa arquivos
de configuração externos conhecidos. Não se deve copiar essa técnica para uma
conta de produção: trocar CODEX_HOME pode omitir requisitos gerenciados ligados
à conta. Além disso, overrides de configuração do CLI são mesclados; eles não
apagam automaticamente permissões herdadas. Não há atestado de perfil efetivo
na saída do comando sandbox. A permissão de rede para GitHub não restringe
o script a endpoints de status: um script autenticado poderia usar toda a
autoridade GitHub disponível para ele. Essas fronteiras ainda precisam de solução revisada
antes de habilitar o gate real. Uma configuração nominal ou um recibo editável
não autoriza ativação.

O probe exige namespaces distintos de PID/rede/usuário, no_new_privs e seccomp,
escrita permitida, escrita/leitura negadas fora do perfil, Git somente leitura
com objetos novos isolados, HTTPS permitido com certificado validado, bloqueio
explícito do proxy (`x-proxy-error: blocked-by-allowlist`) e negação de socket
direto. Falha de DNS, resposta genérica ou timeout não atestam o filtro. Outro
processo é iniciado em sessão separada; após timeout, seu heartbeat precisa parar.
O supervisor limita a saída a 8 MiB, mata o grupo de processos e marca falhas como
incertas. A limpeza dos filhos depende também do namespace oficial, não apenas
de killpg. Nenhuma dessas provas equivale à aprovação de um gate de projeto.

Os testes locais unitários NÃO executam o sandbox:

```sh
python -W error ferramentas/gate_linux/test_adapter.py
python -W error ferramentas/testar_gates_projeto.py
python -W error ferramentas/testar_revisao_execucao.py
```

A validação nativa deve rodar somente em ambiente aprovado e preparado, pelo
workflow `gate-linux.yml`. Não há fallback sem sandbox, tentativa de remediar
segurança automaticamente ou skip considerado sucesso. O resultado aprovado
aparece em `OFFICE_LINUX_GATE_VALIDATION`, vinculado ao commit, runtime, hash do
perfil e evidência real. Ainda falta o aceite da configuração/credenciais de
produção, além de provar o contrato de publicação do script autorizado.

Fontes oficiais:
- https://github.com/openai/codex/releases/tag/rust-v0.159.2
- https://raw.githubusercontent.com/openai/codex/rust-v0.159.2/codex-rs/linux-sandbox/README.md
- https://learn.chatgpt.com/docs/permissions
- https://learn.chatgpt.com/docs/developer-commands?surface=cli
