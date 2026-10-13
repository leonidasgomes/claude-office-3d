# Hooks e observação multi-provider por escopo

Hooks nativos têm prioridade nas fases cobertas quando estão instalados e ativos por escolha explícita. JSON e rollouts são alternativas para fases sem cobertura ou versões não verificadas. O Office não instala hooks globais, não muda confiança, autenticação, sandbox ou permissões para observar sessões.

| Provedor | Capacidade verificada | Configuração de projeto | Limite |
|---|---|---|---|
| Claude Code 2.1.296 | SessionStart/SessionEnd, PreToolUse/PostToolUse/PostToolUseFailure, Stop | `.claude/settings.local.json` | Teste real isolado comprovou leitura e lifecycle, sem provar todos os eventos |
| Codex CLI 0.162.1 | SessionStart/SessionEnd, PreToolUse/PostToolUse, Stop/Interrupt | `.codex/hooks.json` | Não oferece PostToolUseFailure; resultado depende da ferramenta; confiança explícita requerida |
| OpenCode | Callbacks `tool.execute.before/after`, eventos de sessão/erro, plugin existente | `.opencode/plugins/office.js` | Schema documental; versão local e inferência real não comprovadas |

Fontes oficiais: [Claude hooks](https://code.claude.com/docs/en/hooks), [Codex schema 0.162.1](https://raw.githubusercontent.com/openai/codex/rust-v0.162.1/codex-rs/core/config.schema.json), [Codex hooks](https://learn.chatgpt.com/docs/hooks), [OpenCode plugins](https://opencode.ai/docs/plugins/). Capacidades de outra versão precisam ser verificadas; não usar a versão da tabela como detecção automática.

Codex 0.162.1 é o piso **verificado nesta entrega**, não uma afirmação de que hooks foram introduzidos nessa versão. Para versões anteriores, conferir seu schema antes de habilitar cobertura nativa. Nenhuma confiança foi concedida automaticamente para fazer um teste.

## Preparar um vínculo

`hooks_providers.binding` valida um objeto com `enabled: true`, `provider`, versão semântica exata `version`, `project` absoluto existente, `project_id` calculado por `funcionarios.id_projeto`, `session_id`, `origin` e `agent`. Para uma sessão nova, somente `allow_new_session: true` e `session_id: null` permitem fixar o primeiro SessionStart atomicamente; uma nova reserva deve ter outra origem. Sessões concorrentes usam vínculos separados. Não adivinhar a sessão pelo nome da mesa.

O receptor lê JSON nativo por stdin e grava somente identidade, fase, operação e resultado explícito; não persiste corpo de arquivo, comando completo ou resultado de ferramenta. Exemplo de chamada, usando caminhos de arquivos revisados:

```text
python hooks_providers.py --binding vinculo.json --database office-teste.db
python hooks_providers.py --binding vinculo.json --plan --capability capacidade.json --command "python hooks_providers.py --binding vinculo.json --database office-teste.db"
```

`capacidade.json` declara `version`, `version_verified: true`, `mechanism` (`hooks` ou `plugin`) e lista `events`, depois de conferir a versão instalada e o contrato oficial. O plano é puro: gera a configuração de projeto sem escrevê-la. `merge_hooks` preserva grupos existentes e é idempotente. Revisar o plano antes de mesclar a configuração de projeto; nunca substituir configurações existentes ou copiar credenciais. O processo de revisão/confiança dos hooks do Codex deve acontecer no cliente nativo (`/hooks`); gerar o plano não comprova confiança. Não há bypass ou instalação automática de confiança.

O shell do hook também deve ser verificado. `receiver_command` gera o comando com caminhos absolutos e cotação específica para `bash`, `powershell` ou `cmd`. Não infere o shell pelo sistema: no teste Claude Windows, o hook chamou Bash, e cotação cmd.exe com barras invertidas perdeu os separadores. Caminhos com `/` e cotação Bash preservam a chamada; não mudar configurações globais de shell para resolver isso.

## Execução gerenciada e deduplicação

O launcher aceita `--hook-binding` e `--hook-capability`; isso **não instala** hooks. Declarar `hooks_active: true` somente após configurar e verificar a fonte nativa. Para Codex, `hooks_trusted: true` também deve refletir a revisão já realizada no cliente. Sem essa confirmação a execução opt-in é bloqueada. O início JSON passa a ter vínculo nativo; um init de outra sessão não troca a identidade do adapter. IDs de ferramentas Claude/OpenCode e falhas Codex são preservados.

Na 0.162.1, `tool_use_id` do hook Codex não equivale a `item_N` no JSON. O [processor oficial](https://raw.githubusercontent.com/openai/codex/rust-v0.162.1/codex-rs/exec/src/event_processor_with_jsonl_output.rs) remapeia IDs. Por isso escolhemos um produtor por fase coberta, sem correlação por nome/tempo. O ledger deduplica apenas IDs no mesmo esquema, provedor, projeto e sessão. A falta de eventos nativos esperados é um diagnóstico e bloqueia sucesso do launcher opt-in; nunca vira atividade inventada.

O plugin OpenCode usa o mesmo receptor quando o launcher fornece `OFFICE_HOOK_BINDING`, além do banco explícito. As outras instalações continuam com seu caminho existente. Callbacks cobrem ferramentas não shell também; `session.idle` vira Stop/ociosidade, não SessionEnd. Somente `session.deleted` representa encerramento de sessão. Erros sem código explícito não viram sucesso. Uma falha posterior ao resultado desconhecido gera evento de correção para SSE; não é apagada por um sucesso posterior. Stop sem ID nativo de turno não é colapsado entre turnos.

## Sessões externas: leitura passiva e explícita

`fontes_console.py --config fontes.json --banco office-teste.db` executa uma rodada de leitura, sem abrir/resumir CLIs. O arquivo de configuração contém `fontes`, cada uma com `origem`, `provider`, `projeto`, `sessao`, `mesa`, `arquivo` e `formato` (`native`, `codex_rollout`, `hooks`). Projeto e arquivo são absolutos; ID de sessão é exato. Não há glob ou varredura de diretório de sessões. A fonte deve comprovar o vínculo em seu cabeçalho; streams sem cwd usam um envelope explícito `office_session` com provedor, sessão e cwd, produzido por uma origem autorizada. Um caminho configurado não autoriza acesso a arquivos proibidos.

Tail é padrão. `historico: true` habilita replay explicitamente e conserva timestamp histórico, usando epoch quando não há timestamp. Attach sozinho registra vínculo ocioso, sem afirmar sessão ativa. Cursor, identidade do arquivo, checkpoint e estado do adapter persistem na mesma transação; substituição, truncamento ou sessão/projeto divergente interrompem sem avançar cursor. Vários transportes da mesma sessão exigem autoridade explícita, evitando mistura de esquemas de IDs.

## Provas e limites

Claude 2.1.296 foi exercitado em projeto artificial com apenas Read, configurações temporárias explícitas e fontes user/project/local desabilitadas para esse processo. O resultado nativo terminou success/is_error=false, a resposta veio do arquivo e cinco fases chegaram ao mesmo banco/sessão: start, tool_start, tool_end, stop, end. Isso comprova o caminho real dessa leitura, não toda a matriz ou configuração de produção. As instalações existentes não foram alteradas.

Regressões sintéticas dos três provedores cobrem concorrência, reinício, falhas, confiança, fonte parcial e escopo. O subprocesso de teste do plugin usa seu callback real e SQLite, sem modelo externo. Isso não valida uma versão OpenCode desconhecida ou todos os hooks reais.

A resposta fixa real do Codex passou. A leitura artificial falhou antes do shell com código -1: setup do sandbox tentou validar um runtime já aberto por outro processo (erro Windows 32). O Office registrou e exibiu a falha corretamente. Turno com código zero não prova que a ferramenta funcionou. Nenhuma alteração de ACL, encerramento de processo ou troca de sandbox está incluída nesta correção. Esse diagnóstico de runtime permanece separado.
