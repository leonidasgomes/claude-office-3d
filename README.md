# Office Multi-provider — 2.0.0-dev

Nova linha independente em desenvolvimento. Instalações da edição Claude 1.x
continuam em suas pastas; instale a edição 2.x em um destino separado.
Esta distribuição não inclui dados, contas ou configuração pessoal.
Consulte [a separação e o Claude padronizado](docs/VERSOES.md) antes de migrar.

## Começar em uma instalação nova

Para começar com Codex e OpenCode, escolha esses consoles no preparador. O
assistente recomenda Codex como CEO quando o CLI está instalado; diretor e
equipes podem usar Codex ou um modelo cloud gratuito escolhido no OpenCode.
Isso não exige chamadas a Claude ou Gemini e não migra políticas existentes.
O catálogo gratuito informa preços declarados; confirme uma resposta aceita
antes de usar o modelo. Dois consoles não comprovam dois fornecedores distintos.
Revisão independente continua exigindo fornecedores identificados e os gates
do projeto; não desative a revisão para contornar indisponibilidade.

Extraia o pacote novo e execute na pasta extraída:

No Windows sem Python ou consoles, comece por `preparar_maquina.bat`.
Escolha os consoles e uma pasta vazia para as ferramentas; confira o plano antes
de confirmar. O preparador instala apenas componentes ausentes. Login e modelos
continuam sendo configurados nos próprios consoles. Veja [instalação](INSTALACAO.md).

```powershell
python iniciar_projeto.py --projeto D:/projetos/meu-jogo --destino D:/escritorios/meu-jogo --porta 8766
```

A prévia mostra requisitos locais e links oficiais para o que estiver faltando.
Acrescente `--exigir-requisitos` para bloquear aplicação com requisitos ausentes.
Só os consoles escolhidos na política são obrigatórios; login, modelo disponível
e acesso ao Kanban não são comprovados por encontrar um executável no PATH.

O assistente pergunta CEO, diretor, equipes, Kanban e revisores de clouds diferentes,
e mostra a prévia. Repita com `--aplicar` para criar. Para usar uma política já
revisada, acrescente `--politica caminho/projeto.json`. Depois abra
`abrir_escritorio.bat` no destino (Linux/macOS: `abrir_escritorio.sh`).

A primeira instalação exige destino vazio e separado da pasta do projeto.
O comando copia o aplicativo, cria config e atalhos, cadastra o projeto e cria
somente os arquivos de política/instruções ainda ausentes. Repetir com a mesma
política, projeto e porta preserva config, dados e instruções. Não sobrescreve
outra edição. Para acrescentar outro projeto a uma instalação nova existente,
use `--cadastrar-projeto`, a mesma porta e uma política própria do novo projeto:

```powershell
python iniciar_projeto.py --projeto D:/projetos/outro-app --destino D:/escritorios/meu-jogo --porta 8766 --politica politica-outro.json --cadastrar-projeto
```

Confira a prévia e repita com `--aplicar`. Preserva projetos anteriores e todos
os outros campos do config, com backup exato em `dados/historico-config`.
Edição concorrente bloqueia o cadastro. O painel relê a configuração quando
ela muda; a cena 3D precisa de atualização da página. Cada projeto conserva
sua própria política de executores, revisão e merge. Não migra a edição legada.

Python deve estar instalado para executar o assistente. Ele usa esse Python,
detecta consoles no PATH e não instala CLIs, baixa modelos, autentica contas,
instala hooks/statusline, inicia agentes ou faz alterações no GitHub. Esses passos
continuam separados: consulte PROVIDERS para o console escolhido e o instalador
guiado para hooks Claude. Arquivos existentes CLAUDE.md/AGENTS.md/GEMINI.md são
preservados; divergências nesses arquivos precisam ser conciliadas na migração.
Local fica desativado e merge manual por padrão; uma política revisada pode escolher
auto-merge por projeto. Falha parcial pode deixar arquivos no destino: confira o
relato, refaça a prévia e preserve os dados antes de repetir.

Um escritório 3D (three.js) no navegador com gestão por projeto e adapters de Claude,
Codex, OpenCode e Gemini. O núcleo preservado permite **ver os agentes do Claude Code trabalhando**: cada agente tem uma
mesa, o monitor acende quando ele usa uma ferramenta, ele anda até a mesa do colega para conversar, o time vai para a
sala de vidro nas reuniões, e quem fica ocioso vai tomar café, jogar ping-pong ou assistir TV.

O fluxo Claude funciona com sessão simples, subagentes e **times de agentes** (agent teams).
Os outros consoles usam adapters com capacidades próprias; paridade nativa integral
de teams, ferramentas, permissões e skills ainda precisa de validação. O escritório roda na
sua máquina (servidor em `127.0.0.1`), com Python 3.9+ e nada além da biblioteca padrão.

## Integração de hooks Claude

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

Com gestão ativa, [GESTAO](docs/GESTAO.md) define papéis, fontes e gates por projeto.
Os recursos globais e a integração específica Claude abaixo seguem o guia de compatibilidade.

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
  painel mostra camadas, violações, ciclos e quem está mexendo onde. Veja a seção 16 do [guia de compatibilidade](docs/CLAUDE-COMPATIBILIDADE.md).
- **Boas práticas do projeto**: `python boas_praticas.py validar` confere git, `.gitignore` (segredos e pastas geradas),
  CLAUDE.md, a definição de cada agente, o `.venv` do Python e o comando de teste; `corrigir --aplicar` faz só o que é
  seguro (nunca sobrescreve) e o painel 🩺 Saúde mostra o que falta. O escritório roda no próprio `.venv`. Seção 17 do
  [guia de compatibilidade](docs/CLAUDE-COMPATIBILIDADE.md).
- **Revisão de PR (líder + revisor)**: o instalador põe o agente Revisor no time e cria o `.claude/agents/revisor.md`;
  o líder cria um revisor por PR, que roda os testes e publica P0/P1/P2 no PR com `gh pr review --comment`, e o merge
  continua seu. Numa instalação existente: `python instalar.py --revisao <projeto>`. Seção 18 do
  [guia de compatibilidade](docs/CLAUDE-COMPATIBILIDADE.md).
- **⏪ Replay do dia** acelerado na própria cena, com marcas de falha, fala, círculo e merge, e **filtros** por agente e
  tipo de evento no feed e na cena.
- **Kanban** do GitHub Projects e painel de **PRs** acompanhando revisão e merge conforme o projeto (opcionais, via GitHub CLI `gh`).
- **XP e níveis** (opcional): pontos por PR mergeado com resultado verificado, nível no crachá da mesa, painel
  **Placar** cooperativo e auditoria anti-trapaça nos testes (`python xp.py`).
- **Skills**: ciclo candidata -> promovida com `python skills.py`, A/B com o skill-creator e registro de quem usa
  cada skill. Veja a seção "XP, níveis e skills" do [guia de compatibilidade](docs/CLAUDE-COMPATIBILIDADE.md).
- **Sala da diretoria** (opcional): marque um agente com `"sala": "diretoria"` no config e ele ganha uma sala fechada com
  a mesa dele; em `modelos/` há um prompt genérico de Diretor e um exemplo de briefing semanal (`briefing_diretor.py`).
- **Acesso pelo celular** (opcional, desligado por padrão): `abrir_escritorio.bat celular` liga o servidor na rede local
  com HTTPS (CA própria que só vale para IPs privados), pareamento por QR code de uso único, uma sessão por aparelho,
  permissões "só ver" ou "ver e conferir", histórico de ações e revogação. Veja a seção 9 do [guia de compatibilidade](docs/CLAUDE-COMPATIBILIDADE.md).
- **Alertas** (🔔): avisa quando há algo esperando por você (PR pronto para o merge, PR com conflito ou reprovado, auditoria
  vermelha nova, pergunta do Diretor, lembrete de 24 h) com toast e notificação com a página aberta e **Web Push** com o
  celular fechado (cifrado, sem comando nem código no aviso, 20 por hora no máximo). Veja a seção 10 do [guia de compatibilidade](docs/CLAUDE-COMPATIBILIDADE.md).
- **Sugestões do bot de revisão** (opcional): junta os comentários dos bots de revisão (Codex, CodeRabbit, Copilot...) dos PRs
  abertos numa caixa local, com triagem barata opcional (Haiku, sem ferramentas), selo "🤖 3 (1 P1)" no painel PRs, botões
  Encaminhar/Ignorar/Resolvido no PC e entrega ao líder do time. Só REST com ETag (resposta 304 não gasta a cota do GitHub).
  Veja a seção 11 do [guia de compatibilidade](docs/CLAUDE-COMPATIBILIDADE.md) e `modelos/sugestoes_lider.md`. O `vigia_lider.py` (na ferramenta Monitor)
  acorda o líder só quando há novidade.
- **Time de agentes enxuto**: `modelos/GUIA-TIME-ENXUTO.md` reúne o que a documentação do Claude Code confirma para gastar
  menos com um time de agentes (leitura em dobro, regras por pasta, skills, cache dos colegas, uma tarefa por colega).
- **Responsivo no celular**: gaveta inferior arrastável com a lista de agentes, menu ☰, painéis em tela cheia, Kanban por colunas
  com "snap", toque para abrir a ficha do boneco; o painel 📱 Celular ajuda a resolver "não abre no celular" (Firewall e rede).
- Temas: `neutro` (escritório genérico) ou `sao-paulo` (maquete de SP, placas de rua, orelhão, ipês, coxinha…).
- Apelidos divertidos só na tela (brasileiros, de cinema ou desligados).
- Modo **Demo** para ver o escritório funcionando sem nenhum agente rodando.


## Gestão e consoles adicionais

O launcher adicional `console_provider.py` seleciona Claude, Codex, OpenCode ou Gemini e envia os eventos observáveis ao escritório. O fluxo Claude existente permanece disponível. Veja [providers, execução e skills compartilhadas](docs/PROVIDERS.md) e `console.exemplo.json`.

A configuração de gestão pertence a cada projeto. Consulte [gestão e fontes oficiais](docs/GESTAO.md) para CEO, diretor, equipes, Kanban, revisão, local e opção de merge.
## Preço por token no painel

Na nova edição, copie `precos_tokens.exemplo.json` para `dados/precos_tokens.json` e preencha `tarifas` depois de conferir os preços do fornecedor. O exemplo é vazio para evitar tarifas inventadas ou vencidas. Cada tarifa exige `provider` (`codex` ou `gemini`), `modelo` exato, `desde`/`ate` no formato `AAAA-MM-DD`, `fonte` HTTPS e `entrada_usd_milhao`, `cache_usd_milhao`, `saida_usd_milhao` como textos decimais. `ate` é exclusivo; não sobreponha intervalos do mesmo modelo.

O painel mostra o equivalente teórico de API e a cobertura por modelo/agente. Isso compara tokens observados com uma tarifa configurada; não representa quanto uma assinatura cobrou. Modelos sem identidade informada ou contadores completos ficam sem cálculo. Cotas semanais continuam separadas por fornecedor. OpenCode, Claude e modelos locais ainda não recebem este cálculo comum. Consulte [preços da OpenAI](https://developers.openai.com/api/docs/pricing) e [Zen do OpenCode](https://opencode.ai/docs/zen/) para a tabela do serviço utilizado; o console e o fornecedor do modelo são identidades diferentes.
