# Claude Office 3D

Um escritório 3D (three.js) no navegador onde você **vê os agentes do Claude Code trabalhando**: cada agente tem uma
mesa, o monitor acende quando ele usa uma ferramenta, ele anda até a mesa do colega para conversar, o time vai para a
sala de vidro nas reuniões, e quem fica ocioso vai tomar café, jogar ping-pong ou assistir TV.

Funciona com uma sessão simples, com subagentes e com **times de agentes** (agent teams) do Claude Code. Tudo roda na
sua máquina (servidor em `127.0.0.1`), com Python 3.9+ e nada além da biblioteca padrão.

## Instalação rápida

```bash
python instalar.py        # Windows: duplo clique em instalar.bat · macOS/Linux: ./instalar.sh
```

O assistente pergunta, passo a passo, quais pastas monitorar, quem é o time, o GitHub (opcional), o tema e onde
instalar o hook do Claude Code. Depois é só abrir com `abrir_escritorio.bat` (ou `./abrir_escritorio.sh`).

- Guia completo: [INSTALACAO.md](INSTALACAO.md)
- Documento de projeto (arquitetura, rotas, dados, segurança, decisões): [docs/SDD.md](docs/SDD.md)
- Exemplo de configuração: [config.exemplo.json](config.exemplo.json)
- Desinstalar os hooks: `python instalar.py --desinstalar`

## Recursos

- Painel lateral com os agentes, o estado de cada um e os últimos eventos; clique num agente para ver a **ficha**
  (o que está fazendo e o que está falando).
- **Escritório 3D que se lê de relance**: ícone e anel de estado visíveis de longe, ✔/✖ no fim de cada comando (⚠️ com 3
  falhas seguidas), relógio do comando longo, agente em círculos com seta laranja, PRs parados na mesa do líder, tela de
  PRs na parede, festa no merge, gaveteiro que evolui com o nível, fio vermelho quando dois agentes editam o mesmo
  arquivo, gato, dia e noite, sons opcionais, animações reduzidas e modo leve para PC sem placa de vídeo.
- **🩺 Saúde do time** (sem tokens): trabalho duplicado, agentes andando em círculos, PRs parados e risco dos PRs, cartões
  rascunho do Kanban em coluna de trabalho (com o comando que os converte em issue) e comandos repetidos (dica: vire script), com
  Ignorar e **Avisar o líder** (entregue pelo `vigia_lider.py` como informação, nunca como ordem); um modelo barato
  (até 30 chamadas por dia, desligável) faz a triagem de cada item novo: avisa o líder do problema real e silencia o falso
  positivo até ele se resolver.
- **🗺️ Arquitetura**: a ferramenta `grafo/` mantém um grafo de arquitetura do seu projeto conferido contra os imports
  reais (`python grafo/grafo.py init` / `validate` / `slice` / `impact`, hooks do Claude Code por projeto, sem tokens) e o
  painel mostra camadas, violações, ciclos e quem está mexendo onde. Veja a seção 16 do [INSTALACAO.md](INSTALACAO.md).
- **Boas práticas do projeto**: `python boas_praticas.py validar` confere git, `.gitignore` (segredos e pastas geradas),
  CLAUDE.md, a definição de cada agente, o `.venv` do Python e o comando de teste; `corrigir --aplicar` faz só o que é
  seguro (nunca sobrescreve) e o painel 🩺 Saúde mostra o que falta. O escritório roda no próprio `.venv`. Seção 17 do
  [INSTALACAO.md](INSTALACAO.md).
- **Revisão de PR (líder + revisor)**: o instalador põe o agente Revisor no time e cria o `.claude/agents/revisor.md`;
  o líder cria um revisor por PR, que roda os testes e publica P0/P1/P2 no PR com `gh pr review --comment`, e o merge
  continua seu. Numa instalação existente: `python instalar.py --revisao <projeto>`. Seção 18 do
  [INSTALACAO.md](INSTALACAO.md).
- **⏪ Replay do dia** acelerado na própria cena, com marcas de falha, fala, círculo e merge, e **filtros** por agente e
  tipo de evento no feed e na cena.
- **Kanban** do GitHub Projects e painel de **PRs** esperando o seu merge (opcionais, via GitHub CLI `gh`).
- **XP e níveis** (opcional): pontos por PR mergeado com resultado verificado, nível no crachá da mesa, painel
  **Placar** cooperativo e auditoria anti-trapaça nos testes (`python xp.py`).
- **Skills**: ciclo candidata -> promovida com `python skills.py`, A/B com o skill-creator e registro de quem usa
  cada skill. Veja a seção "XP, níveis e skills" do [INSTALACAO.md](INSTALACAO.md).
- **Sala da diretoria** (opcional): marque um agente com `"sala": "diretoria"` no config e ele ganha uma sala fechada com
  a mesa dele; em `modelos/` há um prompt genérico de Diretor e um exemplo de briefing semanal (`briefing_diretor.py`).
- **Acesso pelo celular** (opcional, desligado por padrão): `abrir_escritorio.bat celular` liga o servidor na rede local
  com HTTPS (CA própria que só vale para IPs privados), pareamento por QR code de uso único, uma sessão por aparelho,
  permissões "só ver" ou "ver e conferir", histórico de ações e revogação. Veja a seção 9 do [INSTALACAO.md](INSTALACAO.md).
- **Alertas** (🔔): avisa quando há algo esperando por você (PR pronto para o merge, PR com conflito ou reprovado, auditoria
  vermelha nova, pergunta do Diretor, lembrete de 24 h) com toast e notificação com a página aberta e **Web Push** com o
  celular fechado (cifrado, sem comando nem código no aviso, 20 por hora no máximo). Veja a seção 10 do [INSTALACAO.md](INSTALACAO.md).
- **Sugestões do bot de revisão** (opcional): junta os comentários dos bots de revisão (Codex, CodeRabbit, Copilot...) dos PRs
  abertos numa caixa local, com triagem barata opcional (Haiku, sem ferramentas), selo "🤖 3 (1 P1)" no painel PRs, botões
  Encaminhar/Ignorar/Resolvido no PC e entrega ao líder do time. Só REST com ETag (resposta 304 não gasta a cota do GitHub).
  Veja a seção 11 do [INSTALACAO.md](INSTALACAO.md) e `modelos/sugestoes_lider.md`. O `vigia_lider.py` (na ferramenta Monitor)
  acorda o líder só quando há novidade.
- **Time de agentes enxuto**: `modelos/GUIA-TIME-ENXUTO.md` reúne o que a documentação do Claude Code confirma para gastar
  menos com um time de agentes (leitura em dobro, regras por pasta, skills, cache dos colegas, uma tarefa por colega).
- **Responsivo no celular**: gaveta inferior arrastável com a lista de agentes, menu ☰, painéis em tela cheia, Kanban por colunas
  com "snap", toque para abrir a ficha do boneco; o painel 📱 Celular ajuda a resolver "não abre no celular" (Firewall e rede).
- Temas: `neutro` (escritório genérico) ou `sao-paulo` (maquete de SP, placas de rua, orelhão, ipês, coxinha…).
- Apelidos divertidos só na tela (brasileiros, de cinema ou desligados).
- Modo **Demo** para ver o escritório funcionando sem nenhum agente rodando.
