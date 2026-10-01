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
