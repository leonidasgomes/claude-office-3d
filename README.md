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
- Exemplo de configuração: [config.exemplo.json](config.exemplo.json)
- Desinstalar os hooks: `python instalar.py --desinstalar`

## Recursos

- Painel lateral com os agentes, o estado de cada um e os últimos eventos; clique num agente para ver a **ficha**
  (o que está fazendo e o que está falando).
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
- **Responsivo no celular**: gaveta inferior arrastável com a lista de agentes, menu ☰, painéis em tela cheia, Kanban por colunas
  com "snap", toque para abrir a ficha do boneco; o painel 📱 Celular ajuda a resolver "não abre no celular" (Firewall e rede).
- Temas: `neutro` (escritório genérico) ou `sao-paulo` (maquete de SP, placas de rua, orelhão, ipês, coxinha…).
- Apelidos divertidos só na tela (brasileiros, de cinema ou desligados).
- Modo **Demo** para ver o escritório funcionando sem nenhum agente rodando.
