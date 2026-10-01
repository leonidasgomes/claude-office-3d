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
- Temas: `neutro` (escritório genérico) ou `sao-paulo` (maquete de SP, placas de rua, orelhão, ipês, coxinha…).
- Apelidos divertidos só na tela (brasileiros, de cinema ou desligados).
- Modo **Demo** para ver o escritório funcionando sem nenhum agente rodando.
