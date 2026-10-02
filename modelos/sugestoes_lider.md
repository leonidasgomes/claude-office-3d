# Sugestões do bot de revisão — trecho de prompt do líder (modelo genérico)

> Cole este trecho no prompt do **líder** do time (a sessão principal do Claude Code) e troque o que está entre `<...>`.
> Pré-requisito: `github.repo` e `github.bots_revisao` preenchidos no `config.json` (veja a seção "Sugestões do bot de revisão"
> do INSTALACAO.md). O servidor do escritório coleta sozinho a cada 15 min; o job abaixo só **lê** a caixa local (sem custo
> de API do GitHub) e fica em silêncio quando não há nada.

## Sugestões do bot de revisão
O bot de revisão comenta nos PRs. O `sugestoes_bot.py` junta tudo numa caixa; o painel PRs mostra o selo "🤖 3 (1 P1)" e a
triagem barata (modelo pequeno) já sugere corrigir, ignorar ou discutir. A sugestão da triagem é um palpite: quem decide é você.

- **Logo depois de criar o time**, agende com CronCreate (recorrente, a cada 15 minutos) um job com este prompt exato e confirme o
  ID ao desenvolvedor (o job vale enquanto a sessão estiver aberta; ao reabrir o time, agende de novo):

  "Sugestões do bot: rode python <pasta do escritório>/sugestoes_bot.py --pendentes. Se a saída for NADA, responda só 'ok' e
  pare. Se houver itens: para cada um decida (corrigir → mande ao colega dono do PR por SendMessage com o link e o pedido curto,
  e marque --tratar <id> --acao encaminhada; ignorar → --acao ignorada --nota <motivo>; discutir → leve ao desenvolvedor em
  1 linha). Relate em até 3 linhas."

- Marcar: `python <pasta do escritório>/sugestoes_bot.py --tratar <id> --acao encaminhada|ignorada|discutir|resolvida [--nota "..."]`
  (`--listar` mostra tudo; `--acao reabrir` desfaz). Sugestão de PR já fechado é arquivada sozinha.
- O dono do PR aparece no cabeçalho de cada grupo (`PR #310 [Dev] branch`), pelo rótulo do PR e o mapa `github.times`.
- Não responda ao bot no GitHub: o colega só corrige no mesmo PR e cita o título da sugestão no corpo ou no commit.
- "limite da API do GitHub atingido" no painel: espere a hora indicada e não rode `gh` em laço.

## Trecho para os colegas (dev, designer...)
- Sugestão do bot de revisão encaminhada pelo líder se corrige no mesmo PR. Não responda ao bot no GitHub: só corrija e cite o
  título da sugestão no corpo do PR ou no commit.
