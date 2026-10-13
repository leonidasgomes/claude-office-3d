# Laboratório de backup nativo Windows

Este experimento vive em `ferramentas/backup_windows_nativo.py` e
`ferramentas/testar_backup_windows_nativo.py`. Não faz parte de `PACOTE`, não é
chamado pelo atualizador e **não libera atualização/reversão de instalações
existentes no Windows**. Seu resultado é evidência sobre fixtures, não autorização
para executar com dados reais.

## Fronteira de execução

- Somente o job Windows hospedado e descartável do GitHub: o código exige Windows,
  `GITHUB_ACTIONS=true`, `RUNNER_ENVIRONMENT=github-hosted` e o opt-in
  `OFFICE_NATIVE_BACKUP_PROTOTYPE=1`. O passo de CI se limita ao PR do próprio
  repositório com head `dot/windows-native-backup-prototype`; não passa a rodar
  em todo CI futuro de main ou de outros PRs. Esses marcadores são
  um bloqueio contra execução acidental; não são uma autenticação contra um
  programa hostil que já controle o processo.
- Nenhum argumento recebe uma instalação do usuário. O espaço de trabalho cria
  uma árvore temporária nova e privada. As operações aceitam apenas caminhos
  relativos dentro dessa árvore, recusando travessia, aliases, reparse e hardlinks.
- Primeiro inspeciona o token e exige que `SeBackupPrivilege`,
  `SeRestorePrivilege` e `SeSecurityPrivilege` já existam. Ausência é erro,
  não motivo para alterar política, conta ou configuração do computador.
- Habilita os três privilégios somente durante o contexto de teste; trata também
  `ERROR_NOT_ALL_ASSIGNED` como falha. Restaura e confere o estado anterior em
  sucesso, exceção e falha parcial. Não remove privilégios do token.
- Não executa processos de provider, acessa contas, cria credenciais ou utiliza
  o computador pessoal. Não instala componentes de backup.

## O que o experimento verifica

`BackupRead` e `BackupWrite` transferem os streams nativos com processamento de
segurança e handles com os direitos apropriados. Os contextos são encerrados
mesmo com erro; escrita curta recusa o resultado. A pasta externa da fixture é
privada durante todo o ensaio, e objetos de destino recebem DACL protegida antes
dos primeiros bytes. Isso não prova que um staging fora desse invólucro seria seguro.

A verificação compara conteúdo de cada stream de dados, proprietário, grupo,
DACL, SACL, flags de controle/proteção/herança, atributos comuns e horários de
criação/modificação. A SACL de teste inclui auditoria e rótulo de integridade.
Um segundo leitor por APIs diferentes confere o resultado. `BACKUP_SECURITY_INFORMATION`
consulta o descritor completo; não reduz a comparação a DACL ou remove flags
para aceitar diferenças. Horário de último acesso é restaurado, mas fica fora
da comparação porque a própria leitura pode alterá-lo.

O conjunto é limitado a NTFS local fixo, diretórios e arquivos comuns e ADS de
dados. EAs existentes, EFS, sparse, compressão, offline, reparse, hardlinks e
outros atributos especiais são recusados. Há controles negativos para falhas
de leitura/escrita/segurança, escrita curta e interrupções. Cenários de
renomeação/recuperação são arranjos sintéticos da suíte; não validam o journal,
launcher, processos concorrentes ou rollback do atualizador de produção.

Uma cópia só é aceita quando a fonte continua igual ao snapshot inicial e o
destino confere integralmente. O destino é novo e independente: manter a fonte
intacta ou usar outra referência ao mesmo arquivo não é considerado backup.

## Limites para uma implementação futura

Mesmo um laboratório aprovado não cobre queda de energia, escritores concorrentes,
ameaças de troca de caminho por outro processo, volumes de rede, instalações
grandes, políticas de domínio ou toda combinação de ACE/atributo Windows. Uma
integração real ainda precisa qualificar seu bloqueio de escritores, staging,
journal durável, recuperação, verificação do backup e política de mudanças
posteriores. A elevação de um processo de produção não está autorizada por este
experimento. O atualizador permanece bloqueado até essa qualificação separada.

Referências oficiais:
[BackupRead](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-backupread),
[BackupWrite](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-backupwrite),
[SECURITY_INFORMATION](https://learn.microsoft.com/en-us/windows/win32/secauthz/security-information),
[AdjustTokenPrivileges](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-adjusttokenprivileges).

## Observação nativa dos seletores

No Windows Server 2025 do CI, a consulta `BACKUP_SECURITY_INFORMATION` isolada
(`0x10000`) retornou acesso negado nas duas APIs, apesar dos três privilégios
habilitados. No mesmo objeto e handle, cada componente e as uniões explícitas
passaram. O laboratório exige `BACKUP_SECURITY_INFORMATION | 0x1ff` (`0x101ff`),
mantendo BACKUP, owner, group, DACL, SACL, label, atributos, escopo, trust label e
access filter. Não há fallback para máscara reduzida. A suíte compara também o
descritor binário da união explícita, sem remover ACEs ou normalizar controle.
Essa observação não dispensa a igualdade de metadados da cópia nem prova todos
os tipos de política de uma instalação real.
