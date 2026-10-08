---
name: time-sugestoes
description: Líder do time: tratar as sugestões dos bots de revisão (Copilot, [revisor-ia]) com o sugestoes_bot.py do Claude Office 3D — quem trata, ignorar com motivo, --pronto antes do merge. Use quando o vigia avisar [vigia sugestoes] ou antes de dizer que um PR está pronto.
user-invocable: false
---

# Sugestões dos bots de revisão (modelo de skill do líder)

> **Como usar este modelo:** copie para `<seu projeto>/.claude/skills/time-sugestoes/SKILL.md` e troque o que está entre
> `<...>`. Como skill, só a `description` acima fica no contexto do líder; o texto abaixo só carrega quando ele precisa (doc
> skills). Pré-requisito: `github.repo` e `github.bots_revisao` (ou o bloco `revisor`) no `config.json`. O servidor do
> escritório coleta sozinho; o líder só lê a caixa local.

## Gatilho: o vigia, não um agendamento
No prompt do líder, troque o antigo CronCreate de 15 min por: "Logo depois de criar o time, inicie com a ferramenta **Monitor**
`python <pasta do escritório>/vigia_lider.py`. Cada linha `[vigia sugestoes] ...` é um gatilho; sem linha, nada a fazer."
O vigia roda `sugestoes_bot.py --pendentes` sem tokens e só acorda o líder quando aparece coisa nova (um cron manda o contexto
inteiro do líder a cada disparo, mesmo para responder "ok"). Sem Monitor, use o CronCreate com
"Rode python <pasta>/vigia_lider.py --uma; sem saída, responda só 'ok' e pare; com saída, siga cada linha."

## Quem trata
- **O colega dono do PR trata as do próprio PR** antes de avisar o líder: `sugestoes_bot.py --pendentes --pr <n>`, corrige no
  mesmo PR, responde na conversa do comentário e marca `--tratar <id> --acao resolvida` (ou `--acao ignorada --nota "<por quê>"`
  para falso positivo); só "discutir" vai ao líder. Ponha esta linha no prompt (ou na definição de agente) de cada colega.
- **O líder** trata só os "discutir" (decide ou leva ao desenvolvedor em 1 linha), os PRs de dono ausente e uma amostra das
  ignoradas (falso positivo mal justificado volta ao dono).
- A triagem barata (modelo pequeno) só sugere corrigir, ignorar ou discutir: é palpite, não decisão.
- **Ignorar sempre com motivo**: as últimas ignoradas com motivo e o `glossario_triagem.md` entram na triagem seguinte.

## Antes de dizer "pronto para o merge"
`python <pasta do escritório>/sugestoes_bot.py --pronto <n>`: só com `OK` (nenhuma sugestão sem decisão ou encaminhada sem
correção, e os bots já revisaram o commit atual; cota esgotada vira aviso). O painel PRs do escritório segue a mesma regra.
Com merge automático (`github.publicar_status` no config do escritório), o escritório publica este mesmo resultado como o
status `sugestoes` do commit (a cada 3 min, só quando muda), e o GitHub só faz o merge com ele verde.

## Comandos
`--pendentes [--pr <n>]` · `--listar [--pr <n>] [--todas]` · `--tratar <id> --acao encaminhada|ignorada|discutir|resolvida|reabrir [--nota "..."]` · `--pronto <n>`.
Sugestão de PR já fechado é arquivada sozinha. "limite da API do GitHub atingido" no painel: espere a hora indicada e não rode
`gh` em laço.
