# Changelog

## 1.1.0
XP, níveis e ciclo de vida de skills (opcional, `"xp": {"ativo": true}` no config).

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
