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
