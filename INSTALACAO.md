# Claude Office 3D — guia de instalação e uso

## 1. O que é

O Claude Office 3D é um escritório em 3D, aberto no navegador, que mostra em tempo real o que os agentes do
[Claude Code](https://docs.claude.com/claude-code) estão fazendo:

- cada agente do time tem uma **mesa** com a cor dele; o monitor acende e aparece um balão quando ele usa uma
  ferramenta (lê um arquivo, roda um comando, edita código…);
- quando um agente manda mensagem para outro (`SendMessage`), ele **anda até a mesa** do colega;
- **reuniões** (mensagem para todos, para vários colegas, ou com palavras como "Reunião:", "alinhamento",
  "daily") levam o time para a **sala de vidro**;
- **subagentes** avulsos aparecem como bonequinhos temporários ao lado de quem os chamou;
- quem fica **ocioso** vai para as áreas de pausa: sofá e TV, fliperama, ping-pong, refeitório e banheiro;
- painéis opcionais de **Kanban** (GitHub Projects) e **PRs** abertos esperando o seu merge.

## 2. Requisitos

| Item | Obrigatório? | Para quê |
|---|---|---|
| Python 3.9 ou mais novo | sim | servidor local, hook e instalador (só biblioteca padrão, nada de `pip install`) |
| Claude Code | sim | é ele que gera os eventos (via hook) |
| Navegador moderno com WebGL | sim | Chrome, Edge, Firefox ou Safari atuais |
| Internet na primeira carga | não | o three.js vem do CDN jsDelivr — ou baixe para `vendor/` no instalador e funcione offline |
| GitHub CLI (`gh`) logado | não | só para os painéis de Kanban e PRs (`gh auth login`; para o Kanban, `gh auth refresh -s project`) |

Windows, macOS e Linux. No Windows o comando do hook usa `python`; no macOS/Linux, `python3`.

## 3. Instalação com o assistente (recomendado)

Na pasta do Claude Office 3D:

- **Windows:** duplo clique em `instalar.bat` (ou `python instalar.py`)
- **macOS/Linux:** `./instalar.sh` (ou `python3 instalar.py`)

O assistente tem 7 passos. Em cada pergunta o valor padrão aparece entre colchetes e **Enter aceita**. Nada é gravado
até a confirmação final; Ctrl+C cancela.

1. **Boas-vindas e checagens** — versão do Python, `claude --version`, `gh` e `gh auth status`.
2. **Onde instalar** — padrão: a própria pasta. Se escolher outra, os arquivos são copiados para lá.
3. **Pastas de projeto** — uma ou mais. O hook só registra sessões abertas dentro delas (e subpastas).
4. **Agentes do time** — time genérico (Líder, Dev, Designer, Pesquisa), importar dos `.claude/agents/*.md`
   encontrados nos projetos (o nome é o campo `name`) ou digitar um a um. Título, função e cor são sugeridos.
5. **GitHub (opcional)** — repositório para os PRs (sugere o `git remote get-url origin` do projeto), quadro do
   GitHub Projects para o Kanban (lista os projects do dono com `gh project list`) e o nome do status check que
   significa "aprovado pela revisão".
6. **Aparência e servidor** — título, tema, apelidos, XP, porta, **"Permitir acesso pelo celular na rede local? [s/N]"**
   (padrão **não**; se sim, "Usar HTTPS (recomendado)? [S/n]", veja a seção 9) e se quer baixar o three.js para usar offline.
7. **Hook do Claude Code** — escopo **usuário** (`~/.claude/settings.json`, vale para todos os projetos; o filtro
   de pastas do passo 3 continua valendo) ou **projeto** (`<projeto>/.claude/settings.local.json`). O assistente mostra
   o bloco JSON, faz **backup com data** do arquivo, acrescenta sem apagar os hooks que você já tem e não duplica se
   rodar de novo.

No fim ele grava o `config.json`, cria os atalhos `abrir_escritorio` e `reiniciar_escritorio` (`.bat` e `.sh`) e
pergunta se você quer abrir o escritório agora.

### Exemplo de sessão

```
================================================================
 Passo 1 de 7 — Boas-vindas e checagens
================================================================
  [ok] Python 3.12.4
  [ok] Claude Code: 2.1.0 (Claude Code)
  [ok] GitHub CLI: /usr/local/bin/gh  —  login: ok

================================================================
 Passo 2 de 7 — Onde instalar
================================================================
  Pasta atual do pacote: /home/voce/ferramentas/claude-office-3d
  Pasta de instalação [/home/voce/ferramentas/claude-office-3d]:

================================================================
 Passo 3 de 7 — Pastas de projeto a monitorar
================================================================
  O hook só registra sessões do Claude Code abertas DENTRO destas pastas (e subpastas).
  Pasta 1 [/home/voce/projetos/loja]:
    + /home/voce/projetos/loja
  Pasta 2 (Enter vazio = terminar):

================================================================
 Passo 4 de 7 — Agentes do time
================================================================
  1) Time genérico (Líder, Dev, Designer, Pesquisa)
  2) Importar 3 agente(s) de .claude/agents/*.md: backend, frontend, revisor
  3) Digitar os agentes
  Escolha [1]: 2
  Nome do líder (sessão principal) [Lider]:
  Time:
     1. Lider                  Líder              #e5484d  mesa lider    Coordena o time  (líder: sessão principal)
     2. backend                backend            #3b82f6  mesa dev      API e banco de dados
     3. frontend               frontend           #f59e0b  mesa design   Telas em React
     4. revisor                revisor            #22c55e  mesa pesquisa Revisa os PRs

================================================================
 Passo 5 de 7 — GitHub (opcional): painel de PRs e Kanban
================================================================
  Configurar o GitHub? [S/n]:
  Repositório para o painel de PRs (owner/nome, vazio = sem PRs) [ana/loja]:
  Dono do GitHub Projects para o Kanban (vazio = sem Kanban) [ana]:
  Projects de ana:
  1) #2 — Loja: roadmap
  2) nenhum (sem Kanban)
  Qual quadro? [1]:
  Campo do Projects que diz o time do cartão [time]:
  Status check que significa "aprovado pela revisão" (ex.: o nome de um job do CI).
  Nome do check (vazio = usar a aprovação de review do GitHub) []:

================================================================
 Passo 6 de 7 — Aparência e servidor
================================================================
  Título do escritório [Claude Office 3D]: Escritório da Loja
  1) neutro (escritório genérico)
  2) sao-paulo (maquete de SP, placas de rua, orelhão, ipês, coxinha…)
  Tema [1]:
  Ativar XP e níveis? (pontos por PR mergeado e skills; mostra o nível de cada agente na mesa) [S/n]:
  ...
  Porta do servidor local [8765]:
  Permitir acesso pelo celular na rede local? (protegido por QR code; só redes privadas) [s/N]:
  Baixar o three.js 0.160.0 para vendor/ (funciona sem internet)? [s/N]: s

================================================================
 Passo 7 de 7 — Hook do Claude Code
================================================================
  1) usuário — /home/voce/.claude/settings.json (vale para todas as sessões; ...)
  2) projeto — <projeto>/.claude/settings.local.json de cada pasta do passo 3
  3) não instalar agora (instalação manual, veja INSTALACAO.md)
  Onde instalar o hook? [1]:
  Bloco que será ACRESCENTADO (os hooks que você já tem são mantidos; antes é feito um backup):
  ...
  Gravar tudo isso agora? [S/n]:
  ...
  Instalação concluída!
  Abrir o escritório agora? [S/n]:
```

### Instalação silenciosa (para automatizar)

```bash
python instalar.py --sem-perguntas --config minha-config.json
```

O arquivo tem o formato do `config.json` e pode trazer um bloco extra `instalacao`:

```json
{
  "projetos": ["/home/voce/projetos/loja"],
  "tema": "neutro",
  "instalacao": {"destino": "/home/voce/ferramentas/claude-office-3d", "hook": "usuario", "three_offline": false, "abrir": false}
}
```

Opções úteis: `--hook usuario|projeto|nenhum`, `--destino PASTA`, `--settings-usuario CAMINHO` (usa outro
`settings.json` no lugar de `~/.claude/settings.json` — bom para testar), `--sem-abrir`.

## 4. Instalação manual

1. Copie `config.exemplo.json` para `config.json` e ajuste (veja a seção 5).
2. Acrescente ao `settings.json` do Claude Code (do usuário ou `<projeto>/.claude/settings.local.json`), trocando o
   caminho pelo da sua pasta (no macOS/Linux use `python3`):

```json
{
  "hooks": {
    "PostToolUse":  [{"matcher": "*", "hooks": [{"type": "command", "command": "python \"C:/ferramentas/claude-office-3d/registrar_evento.py\"", "timeout": 5}]}],
    "TeammateIdle": [{"hooks": [{"type": "command", "command": "python \"C:/ferramentas/claude-office-3d/registrar_evento.py\"", "timeout": 5}]}],
    "Stop":         [{"hooks": [{"type": "command", "command": "python \"C:/ferramentas/claude-office-3d/registrar_evento.py\"", "timeout": 5}]}],
    "SubagentStop": [{"hooks": [{"type": "command", "command": "python \"C:/ferramentas/claude-office-3d/registrar_evento.py\"", "timeout": 5}]}]
  }
}
```

   Se já houver uma chave `"hooks"`, acrescente os itens dentro das listas existentes — não substitua.
3. Reinicie as sessões do Claude Code e abra o escritório com `python servidor.py` (ou o atalho `abrir_escritorio`).

## 5. Configuração (`config.json`)

O `config.json` fica na pasta instalada (o servidor e o hook o leem dali; a variável de ambiente `OFFICE_CONFIG`
aponta outro arquivo). Toda chave ausente recebe o valor padrão. O servidor relê o arquivo quando ele muda — basta
recarregar a página (a porta só muda reiniciando o servidor).

```jsonc
{
  "porta": 8765,                      // porta do servidor local (em 127.0.0.1; com o celular ligado, veja a seção 9)
  "rede_local": false,                // true = acesso pelo celular na rede local (seção 9); padrão: desligado
  "rede_https": true,                 // com rede_local: HTTPS com CA local (porta+1) e certificado público em porta+2
  "rede_tailscale": false,            // com rede_local: aceita também 100.64.0.0/10 (Tailscale)
  "titulo": "Claude Office 3D",       // nome no painel, na aba do navegador e no quadro da parede (tema neutro)
  "projetos": ["C:/projetos/loja"],   // pastas monitoradas: o hook só registra sessões com cwd dentro delas
                                      // (lista vazia = registra TODAS as sessões)
  "agentes": [                        // o time; cada um ganha uma mesa (até 10). Os demais aparecem quando surgirem
    {
      "nome": "Lider",                // como aparece nos eventos (nome do colega no time / do subagente)
      "titulo": "Líder",              // nome de exibição
      "funcao": "Coordena o time",    // linha de baixo do crachá
      "cor": "#e5484d",               // cor da mesa, do boneco e dos cartões no Kanban/PRs
      "apelido_br": "Lia",            // apelido no modo "brasileiros"
      "apelido_cinema": "Morpheus",   // apelido no modo "cinema" (personagens de filme)
      "cargo": "",                    // opcional: prefixo do apelido ("Dev João")
      "mesa": "lider",                // lider | dev | design | pesquisa | padrao (formato da mesa)
      "lider": true,                  // sessão principal do Claude Code; convoca reuniões (padrão: o 1º da lista)
      "auxiliar": false,              // true = não vai às reuniões
      "sala": "diretoria",            // opcional: sala fechada própria com a mesa grande (veja abaixo); omita nos demais
      "outros_nomes": ["main", "lead", "team-lead"]  // outros nomes que significam este agente
    }
  ],
  "github": {                         // opcional — precisa do gh instalado e logado
    "repo": "ana/loja",               // owner/nome: painel de PRs
    "projeto_owner": "ana",           // dono (usuário ou organização) do GitHub Projects: Kanban
    "projeto_numero": 2,              // número do project (na URL .../projects/2)
    "check_revisao": "",              // status check que significa "aprovado pela revisão";
                                      // vazio = usa a aprovação de review (APPROVED) do GitHub
    "campo_time": "time",             // campo do Projects que diz o time/agente do cartão
    "campo_prioridade": "prioridade", // campo de prioridade (P0/P1/P2 ou high/medium/low ganham cor)
    "times": {"Time Back": "backend", "team:front": "frontend"},
                                      // valor do campo_time (Kanban) ou rótulo do PR -> nome do agente
    "colunas": ["Todo", "In Progress", "Done"]  // ordem das colunas; vazio = na ordem em que aparecem
  },
  "xp": {                             // opcional — veja a seção 8
    "ativo": true,                    // false/ausente = sem placar, sem níveis (padrão: desligado)
    "desde": "2026-09-01",            // só PRs mergeados desde esta data (vazio = últimos 30 dias)
    "pesos": {"aprovado_de_primeira": 3, "sem_conflito_com_testes": 2, "cartao_fechado": 2, "bug_nao_voltou_14d": 2,
              "retrabalho": -2, "regressao": -3, "skill_reusada_por_outro": 5, "skill_promovida": 3},
    "niveis": [{"nivel": 1, "titulo": "Estagiário", "xp": 0}, {"nivel": 2, "titulo": "Júnior", "xp": 20}],
    "padroes_teste": ["(^|/)tests?/", "\\.(test|spec)\\.[a-z]+$"],   // regex dos caminhos que são arquivo de teste
    "padroes_avaliacao": ["(^|/)evals?/", "(^|/)benchmark\\.json$"],  // regex dos arquivos de avaliação (mexer neles = auditoria)
    "amostra_1_em": 10,               // 1 em cada N PRs vai para conferência humana mesmo sem suspeita (0 desliga)
    "atribuicao": {"prefixos_branch": {"research/": "Pesquisa"}, "padrao": "Dev"}   // PR sem cartão: por prefixo do branch
  },
  "alertas": {"ativo": true, "limite_push_hora": 20, "lembrete_horas": 24},   // push/notificação quando algo espera por você (seção 10)
  "tema": "neutro",                   // "neutro" ou "sao-paulo"
  "apelidos": "desligado",            // modo inicial: "brasileiros" | "cinema" | "desligado"
  "palavras_reuniao": ["reunião", "alinhamento", "daily", "stand-up", "meeting", "retrospectiva"]
                                      // SendMessage com uma destas palavras vira reunião
}
```

(O `config.json` de verdade é JSON puro, sem comentários — veja `config.exemplo.json`.)

**Agente de exemplo "Diretor".** O `config.exemplo.json` traz, como quinto agente, um **Diretor** (função "Prioriza e resolve casos difíceis", `"sala": "diretoria"`): quem tem `"sala": "diretoria"` ganha uma sala fechada à direita da sala de reunião, com a mesa grande dele lá dentro. O prompt de exemplo desse agente (revisão semanal e caso difícil, com 3 chapéus) está em `modelos/diretor.md`. Sem nenhum agente assim o escritório fica como sempre foi.

## 6. Como funciona

```
Claude Code ──hook──> registrar_evento.py ──1 linha JSON──> dados/eventos.jsonl
                                                                   │
navegador <──GET /eventos a cada 2 s── servidor.py (127.0.0.1) <───┘
          <──GET /config, /kanban, /prs (gh, em cache)
```

1. A cada ferramenta usada (`PostToolUse`), quando um colega fica ocioso (`TeammateIdle`) ou uma sessão/subagente
   termina (`Stop`, `SubagentStop`), o Claude Code chama `registrar_evento.py` com um JSON no stdin.
2. O hook descobre **quem** gerou o evento (nome do colega, id `nome@time`, metadados do subagente, tipo do
   subagente; sem nada disso, é a sessão principal = líder), resume o que foi feito e acrescenta uma linha em
   `dados/eventos.jsonl`. Ele nunca bloqueia o agente: qualquer erro sai em silêncio. Acima de 4 MB o arquivo é
   guardado como `eventos.antigo.jsonl` e recomeça.
3. O `servidor.py` serve a página e entrega os eventos novos; a página anima cada um.

Tipos de evento: `trabalho` (monitor acende + balão), `fala` (anda até a mesa do destinatário), `reuniao` (sala de
vidro), `subagente` (bonequinho temporário, ou tarefa para a mesa do agente se ele for do time) e `ocioso`.

## 7. Uso

- **Painel de agentes** — estado de cada um (trabalhando, conversando, em reunião, em pausa, ocioso) e a hora do
  último evento. Clique num agente (no painel ou no boneco) para focar a câmera e abrir a **ficha**: abas "O que
  está fazendo" (comandos, arquivos) e "O que está falando" (mensagens completas).
- **Kanban** — o quadro do GitHub Projects, com filtro por time; o cartão leva ao GitHub.
- **PRs** — pull requests abertos, ordenados: prontos para o seu merge, aguardando revisão, bloqueados (conflito ou
  reprovados). O número no botão mostra quantos estão prontos. O escritório só mostra: o merge é sempre seu.
- **Placar** — (com `xp.ativo`) XP e nível de cada agente, aprovação de primeira, retrabalho, auditorias abertas (vermelho)
  e PRs para conferir (amarelo), com os botões **✓ Conferido** / **Liberar pontos** / **Desfazer**; o nível também aparece
  no crachá da mesa e na aba "XP" da ficha. Veja a seção 8.
- **📱 Celular** — (só no PC, quando ligado) QR para instalar o certificado e parear o celular; lista e revoga aparelhos.
  Veja a seção 9.
- **Visão geral** — volta a câmera. Arraste para girar, roda do mouse para zoom.
- **Apelidos** — alterna brasileiros / cinema / desligado (só na tela; a escolha fica no navegador).
- **Demo** — eventos de mentira para ver tudo funcionando. Sem servidor (abrindo o `index.html` direto do disco),
  a página entra sozinha em modo demonstração.
- `reiniciar_escritorio` (`.bat`/`.sh`) encerra o servidor da porta configurada e sobe de novo; a página aberta
  reconecta sozinha.

**No celular** (tela abaixo de 760 px de largura ou paisagem baixa) a página muda de layout: a cena 3D ocupa a tela e a lista de
agentes e eventos vira uma **gaveta inferior** (arraste a alça ou toque nela: recolhida com o resumo "4 agentes · 2 trabalhando",
meio, cheia); os botões ficam no menu **☰**; Placar, PRs, Kanban, ficha e Celular abrem em tela cheia com botão de fechar
grande (o Kanban mostra uma coluna por vez: deslize para o lado). Um dedo gira a câmera, dois dão zoom e arrastam, e um toque
no boneco abre a ficha. A animação pausa e a consulta ao servidor fica mais lenta quando a aba está oculta.

## 8. XP, níveis e skills

Opcional (`"xp": {"ativo": true}`; o assistente pergunta no passo 6). O escritório mostra o **nível** de cada
agente no crachá da mesa (estrelas, título e barra até o próximo nível), um painel **Placar** (botão no cabeçalho)
e a aba **XP** na ficha do agente. Quando alguém sobe de nível, o boneco comemora com confete. O placar é
**cooperativo**: ordena só por nome ou nível, sem medalhas nem pódio. Sem dados reais, o botão Demo mostra pontos de
mentira.

O XP é calculado por `xp.py`, sem gastar nenhum token de agente. Ele lê, via `gh`, os PRs mergeados do `github.repo`
desde `xp.desde` (padrão: últimos 30 dias), o Kanban (se configurado) e o diff de cada PR, e grava
`dados/xp/placar.json`, que o servidor entrega em `GET /xp`. PR já analisado fica em cache (`dados/xp/estado.json`);
a pontuação é refeita a cada execução. Rode `python xp.py` à mão ou agende (cron, Agendador de Tarefas) a cada
poucos minutos; a página relê o placar a cada 60 s. Se o repositório ou o gh não estiverem disponíveis, o placar
sai com um aviso e só as skills pontuam.

### Regras de pontuação

Pesos em `xp.pesos` (os padrões estão abaixo). A pontuação é só por **resultado verificado**, nunca por volume
de código ou de mensagens.

| Regra | Pontos | Quando |
|---|---|---|
| `aprovado_de_primeira` | +3 | nenhum commit do PR reprovado pela revisão (o `github.check_revisao`, como status ou check-run; sem check, nenhuma review pediu mudanças) |
| `sem_conflito_com_testes` | +2 | nenhum merge da base no meio do PR **e** o corpo do PR cita teste/validação |
| `cartao_fechado` | +2 | o cartão do Kanban atribuído ao PR está na coluna final (Done/Feito/…, ou a última de `github.colunas`) |
| `bug_nao_voltou_14d` | +2 | PR de correção (`fix`/`hotfix`) que, passados 14 dias, nenhum PR novo corrigiu ou reverteu citando-o |
| `retrabalho` | -2 | reprovado pela revisão, ou um PR de `fix` posterior cita este em até 14 dias |
| `regressao` | -3 | um PR posterior com `revert`/`regress` cita este em até 14 dias |
| `skill_reusada_por_outro` | +5 | outro agente usou uma skill de que você é autor (por uso registrado ou pelo evento da ferramenta Skill) |
| `skill_promovida` | +3 | uma skill candidata sua foi promovida |

O XP nunca fica negativo. Os níveis (`xp.niveis`) padrão: 1 Estagiário (0), 2 Júnior (20), 3 Pleno (60), 4 Sênior
(150), 5 Mestre (300). Você pode trocar títulos e limites; o primeiro nível precisa começar em 0.

### Quem recebe o PR

Na ordem: (a) o cartão que o PR fecha (`Closes #n`) ou que ele cita (`#n` no título, no branch `feat/225-x` ou no
corpo), pelo campo `github.campo_time` mapeado em `github.times` (valor mapeado para `""` = cartão de humano, o PR é
ignorado); (b) um rótulo do PR que seja chave de `github.times`; (c) o prefixo do branch em
`xp.atribuicao.prefixos_branch` (ex.: `"research/": "Pesquisa"`; sem essa chave, os padrões saem das mesas
`pesquisa` e `design` do time); (d) `xp.atribuicao.padrao` (sem ele: o agente da mesa `dev`, senão o líder).

### Anti-trapaça em três faixas

O `xp.py` olha o diff de cada PR (só arquivos que casam com `xp.padroes_teste` e `xp.padroes_avaliacao`) e classifica:

| Faixa | O que acontece | Quando |
|---|---|---|
| 🟢 Verde | pontos normais | nada suspeito |
| 🟡 Amarelo ("para conferir") | **pontos normais**; o PR entra na lista `conferir` | skip **condicional** acrescentado em teste (`skipUnless`/`skipIf`, `pytest.mark.skipif`, `skipTest`/`pytest.skip` dentro de um `if`); **consolidação** (apagou arquivo de teste, mas criou teste(s) com pelo menos as mesmas linhas); **teste enfraquecido** (nos arquivos de teste que continuam existindo, o PR acrescenta menos asserções do que remove: linhas com `assert`, `expect(`, `check(`, `EXPECT_*`/`ASSERT_*`); **amostra** aleatória e determinística de 1 em cada `xp.amostra_1_em` PRs (padrão 10; conferência humana mesmo com tudo verde) |
| 🔴 Vermelho (auditoria) | **pontos zerados**; o PR entra em `auditoria` | skip/xfail **incondicional** (`@unittest.skip(`, `pytest.mark.skip`/`xfail`, `pytest.skip(` fora de `if`, `it.skip`, `#if 0`, `return  # skip`...); apagar teste **sem** substituto equivalente; **qualquer mudança em arquivo de avaliação** (`xp.padroes_avaliacao`: por padrão `evals/`, `*evals.json`, `grading`, `benchmark.json`) |

Cada item guarda o motivo legível e os arquivos ("skip condicional em tests/test_x.py", "teste enfraquecido: −3
asserções em test_y.py", "amostra aleatória 1/10"). Eles aparecem no **Placar** (tile vermelho "auditorias abertas",
tile amarelo "para conferir" e as listas "🔴 Auditoria" e "🟡 Para conferir", com link para o PR em
`https://github.com/<github.repo>/pull/N`), na aba XP da ficha (cada item com a cor da faixa), no selo do botão Placar
(vermelho se houver auditoria, amarelo se só houver itens para conferir) e na saída do `xp.py`. No `placar.json`:
`time.auditorias_abertas`, `time.conferir_abertos` e, por agente, `auditoria` e `conferir` (`[{pr, motivo, arquivos}]`).

Depois de **conferir** o PR (a decisão é sempre sua: agentes não resolvem os próprios itens), use os **botões do Placar**
(em cada item amarelo "✓ Conferido", em cada vermelho "Liberar pontos" com confirmação, e "Desfazer" nos já resolvidos; o
resultado aparece na hora, com um aviso de 10 s para desfazer) ou os comandos abaixo, que fazem a mesma coisa. Os botões
chamam `POST /api/xp/...` e recalculam o placar só a partir do cache (`xp.py ... --so-placar`), sem consultar o GitHub;
só funcionam no PC (e, no celular pareado com "ver e conferir", só o "✓ Conferido" e o "Desfazer" do que foi conferido):

```bash
python xp.py --liberar 123     # vermelho: PR #123 deixa de ser auditado e pontua normalmente
python xp.py --conferido 123   # amarelo: PR #123 sai da lista "para conferir"
python xp.py --desfazer 123    # volta a auditar/conferir
```

As listas ficam em `dados/xp/auditorias_resolvidas.json` (liberados) e `dados/xp/conferidos.json` (conferidos). A regra
tem versão (`regra` no `dados/xp/estado.json`): quando ela muda, o `xp.py` reanalisa o diff de cada PR em cache uma
vez, reaproveitando o resto (commits, revisão).

### Ciclo de vida das skills

Skill é um procedimento que se repete e vale guardar. O fluxo, com `python skills.py`:

1. `novo <nome> --autor <agente>` cria o candidato em `dados/skills/<nome>.md` a partir de `skills-candidatos/MODELO.md`
   (nome em minúsculas e hífen; `description` em 3ª pessoa dizendo **o que faz e quando usar**; `evidencia` com o
   PR/cartão de onde saiu o padrão). Estado: `candidato`.
2. `usar <nome> --agente <quem> --cartao N --resultado ok|falhou` registra cada uso. Falhou -> `quarentena`;
   2 usos `ok` em cartões diferentes (e nenhuma falha pendente) -> `pronto-ab`.
3. **A/B com o skill-creator** (veja abaixo) decide se a skill melhora o resultado.
4. `promover <nome>` valida e gera `dados/skills-promover/<nome>/SKILL.md` (frontmatter `name`/`description`, corpo
   com menos de 500 linhas); o estado vira `aprovado`. Copie a pasta para `.claude/skills/<nome>/` do seu projeto
   (ou `~/.claude/skills/<nome>/`) e faça commit/PR; **você** revisa e dá o merge.
5. `contar-uso` lê os eventos do escritório (o hook registra a ferramenta Skill como "usa a skill `<nome>`"), grava
   `dados/skills/uso.json` e sugere revisar/aposentar skills promovidas **sem uso há 30 dias**.

`listar` mostra todos os candidatos. Estados: `candidato`, `quarentena`, `pronto-ab`, `aprovado`, `rejeitado`,
`aposentado` (os dois últimos você marca editando o campo `estado` do arquivo).

**Como usar o skill-creator para o A/B.** Com a skill `skill-creator` do Claude Code disponível, peça ao agente
líder (ou faça você mesmo) algo como: *"use o skill-creator para avaliar o candidato `<nome>`: rode 3 a 5 tarefas
reais com e sem a skill, compare o resultado (testes passando, retrabalho, tempo) e otimize a `description` para o
gatilho certo"*. Se a versão com a skill ganhar de forma consistente, rode `skills.py promover`; se não, marque
`rejeitado`. Recomenda-se um A/B por semana, só para candidatos em `pronto-ab`.

## 9. Acesso pelo celular (rede local)

Opcional e **desligado por padrão**: sem nada disso o servidor só escuta em `127.0.0.1` e o celular não alcança o
escritório. Ligado, dá para ver o escritório (e, se você permitir, marcar PRs como conferidos) pelo celular no mesmo Wi-Fi,
com sessão própria por aparelho, HTTPS com uma autoridade certificadora (CA) local gerada no seu PC (grátis, sem conta) e
uma lista de regras bem fechada (resumo no fim da seção).

### Ligar

- Windows: `abrir_escritorio.bat celular` (ou `reiniciar_escritorio.bat celular` para reiniciar já ligado). Linux/macOS:
  `./abrir_escritorio.sh celular`. Também vale `python servidor.py --rede-local` ou `"rede_local": true` no `config.json`.
- O assistente de instalação pergunta no passo 6 "Permitir acesso pelo celular na rede local? [s/N]" (padrão **não**) e, se
  você disser que sim, "Usar HTTPS (recomendado)? [S/n]".
- Chaves do `config.json`: `rede_local` (padrão `false`), `rede_https` (padrão `true`) e `rede_tailscale` (padrão `false`,
  veja "Fora de casa").
- Portas (com HTTPS, `porta` = a do config, padrão 8765):

| Porta | Protocolo | Escuta em | Para quê |
|---|---|---|---|
| `porta` (8765) | HTTP | só `127.0.0.1` | o seu PC, como sempre |
| `porta + 1` (8766) | HTTPS (TLS 1.2+) | `0.0.0.0` | o celular |
| `porta + 2` (8767) | HTTP | `0.0.0.0` | **só** o certificado público da CA (`/ca.crt`, `/ca.mobileconfig` e uma página de instruções); o resto é 404 |

  Sem como gerar o certificado (nem a biblioteca `cryptography` nem o `openssl`), o servidor avisa e cai para **HTTP em
  `0.0.0.0:porta`**, ainda com sessão por aparelho, mas sem criptografia (veja os riscos). `--sem-https` força esse modo.
- Instalar a biblioteca ajuda: `pip install cryptography` (no Windows o `openssl` que vem com o Git também serve).

### Firewall do Windows (faça você mesmo: o escritório nunca mexe nele)

1. Na primeira vez que o Python escutar na rede o Windows mostra "O Firewall do Windows Defender bloqueou alguns recursos
   deste aplicativo". Marque **somente "Redes privadas"** e desmarque "Redes públicas". Clique em "Permitir acesso".
2. Confira se o seu Wi-Fi está como rede **Privada**: Configurações > Rede e Internet > Wi-Fi > (sua rede) >
   Perfil de rede = **Privada** (em PowerShell: `Get-NetConnectionProfile`). Em rede Pública o Windows bloqueia a entrada,
   e isso é o desejado em café/hotel/aeroporto.
3. Se a caixa não apareceu ou você marcou errado: Painel de Controle > Sistema e Segurança > Firewall do Windows Defender
   > "Permitir um aplicativo..." > Python > marque só "Privada".

### Não abre no celular? (Firewall e rede)

Sintoma típico: o QR ou o link dá **tempo esgotado** no celular, mas o celular abre normalmente a página do roteador.
O painel **📱 Celular** (no PC) traz um bloco "Não abriu no celular?" com estes passos e o comando abaixo já pronto para
copiar (com o caminho do Python e as portas deste servidor). Confira **nesta ordem**:

1. **Mesma sub-rede.** No celular: Configurações → Wi-Fi → detalhes da rede. O IP do celular deve ter os **3 primeiros
   números iguais** aos do PC (PC `192.168.1.10` → celular `192.168.1.x`). Repetidor Wi-Fi em modo *roteador* cria uma
   sub-rede separada: ponha-o em modo repetidor/ponto de acesso ou ligue o PC e o celular na mesma rede. Use o IP da
   **placa real** do PC e ignore adaptadores virtuais (vEthernet, WSL, Hyper-V; costumam ser `172.x`): o painel marca esses
   como "(virtual — não use)" e usa a placa com gateway padrão no QR.
2. **Rede do Windows como Privada.** No PowerShell: `Get-NetConnectionProfile` deve mostrar `NetworkCategory : Private`
   (se estiver `Public`, mude em Configurações → Rede e Internet → propriedades da rede → Perfil de rede = Privada).
3. **Falta a regra de entrada no Firewall.** Uma regra antiga "Python" só no perfil **Público** não vale na rede **Privada**
   (e ainda é um risco: libera qualquer Python em rede pública). Crie uma regra só para o Python que roda o servidor, só na
   rede Privada. PowerShell **como Administrador**:

   ```powershell
   New-NetFirewallRule -DisplayName "Claude Office 3D (celular)" -Direction Inbound -Program "<caminho do python.exe>" `
     -Protocol TCP -LocalPort <porta+1>,<porta+2> -Profile Private -Action Allow
   ```

   - `<caminho do python.exe>`: o Python que roda o `servidor.py`. Descubra com `(Get-Command python).Source` ou
     `python -c "import sys;print(sys.executable)"`.
   - `<porta+1>,<porta+2>`: com a porta padrão 8765, `8766,8767` (HTTPS e página do certificado). Com `--sem-https`, só a própria `porta`.
   - Pela tela, se preferir: Firewall do Windows com Segurança Avançada → Regras de Entrada → Nova Regra → Programa →
     caminho do `python.exe` → Permitir a conexão → marque **só Particular** → dê um nome.
   - Recomendado: desative a regra antiga pública, se existir: `Disable-NetFirewallRule -DisplayName "Python"`
     (para religar: `Enable-NetFirewallRule -DisplayName "Python"`).
   - Conferir (funciona numa sessão normal; `Get-NetFirewallRule` pode não listar sem administrador):
     `netsh advfirewall firewall show rule name="Claude Office 3D (celular)" verbose`.
4. **Isolamento de AP/clientes** ligado no repetidor ou roteador (o Wi-Fi não "enxerga" o cabo e vice-versa): desligue
   ("AP isolation", "client isolation" ou "isolamento de clientes" na página do roteador).

**Teste:** no celular, abra `http://<IP do PC>:<porta+2>` (padrão `8767`). Se aparecer a página do certificado, a rede e o
Firewall estão certos e o resto é o pareamento. O `instalar.py`, quando você ativa o celular no passo 6, mostra no final
esse comando com o seu caminho do Python e as suas portas (só mostra; nunca executa nem altera o Firewall).

### Instalar o certificado (uma vez por celular) e parear

No PC, abra o escritório em `http://127.0.0.1:8765/` e clique em **📱 Celular** (o botão só existe no PC, em `localhost`):

1. **Instalar o certificado**: leia o primeiro QR (aponta para `http://<ip do PC>:8767/`).
   - iPhone (Safari): baixe o perfil; Ajustes > Geral > VPN e Gerenciamento de Dispositivos > instalar; depois Ajustes >
     Geral > Sobre > Ajustes de Certificados Confiáveis > ativar o "Claude Office 3D".
   - Android: Configurações > Segurança > Criptografia e credenciais > Instalar um certificado > Certificado de CA (o
     Chrome confia em CA instalada pelo usuário).
   - Alternativa sem instalar: abra o endereço seguro, aceite o aviso do navegador uma vez e **confira a impressão digital
     SHA-256** do certificado com a mostrada no painel (CA e servidor).
   - A CA só vale para **IPs privados** (`10/8`, `172.16/12`, `192.168/16`, e `100.64/10` se `rede_tailscale`) e para
     `localhost`/`*.local` (NameConstraints, marcado como crítico): instalá-la no celular **não** permite falsificar
     nenhum site da internet. Validade: CA 3 anos; certificado do servidor 390 dias (limite do iOS: 397), refeito
     sozinho quando os IPs da máquina mudam ou faltam menos de 30 dias. Tudo fica em `dados/tls/` (fora do git);
     `ca.key` nunca é servida.
2. **Parear**: escolha a permissão ("Só ver" ou "Ver e conferir"), clique em "Gerar QR code" e leia o QR com o celular. O
   código é de **uso único**, vale **10 minutos** e só o hash dele fica guardado. O celular mostra uma página pedindo o
   **nome do aparelho** ("Celular do Leo"); ao tocar em "Parear" ele ganha uma sessão própria (cookie `HttpOnly`,
   `Secure`, `SameSite=Strict`, 30 dias). Em `dados/dispositivos.json` ficam só o **hash (sha256)** da sessão, o nome, a
   permissão, quando foi pareado e o último acesso/IP.

### Permissões

| | PC (localhost) | Celular "ver e conferir" | Celular "ver" |
|---|---|---|---|
| Ver escritório, placar, Kanban, PRs | sim | sim | sim |
| `✓ Conferido` (amarelo) | sim | sim | não (403) |
| `Desfazer` | tudo | só o que foi **conferido** | não |
| `Liberar pontos` (vermelho) | sim | **não**: só pelo PC | não |
| Gerar código, revogar, recriar certificados | sim | não | não |

As ações de XP (`POST /api/xp/conferido`, `/liberar`, `/desfazer`, corpo `{"pr": N}`) exigem `Content-Type: application/json`,
`X-Office-Acao: 1`, `Origin` igual ao host acessado e, no celular, também o token anti-CSRF da sessão (`X-Office-Csrf`,
entregue em `GET /api/sessao`). O celular tem no máximo **10 ações por minuto** (429 depois disso).

### Revogar, histórico e recriar

- **Revogar**: no painel 📱 Celular há a lista de aparelhos (nome, permissão, quando foi pareado, último acesso e IP) com
  **Revogar** por aparelho e **Revogar todos**. A sessão some do `dados/dispositivos.json` e o aparelho recebe 401 na
  próxima requisição. Apagar a linha do arquivo também revoga.
- **Histórico**: toda ação (do PC ou do celular), pareamento e revogação vai para `dados/acoes.jsonl` (quando, o quê, PR,
  origem, IP). `GET /api/acoes` devolve as últimas 50; o **Placar** mostra a seção "Histórico de ações" e cada
  "conferido" tem um link para **desfazer**. Tudo é reversível.
- **Recriar certificados**: botão no painel (só no PC); apaga `dados/tls/` e gera de novo. Os celulares precisam instalar a
  CA de novo.
- Força bruta: 5 códigos errados em 10 minutos bloqueiam aquele IP por 15 minutos (429). O console do servidor registra
  as tentativas negadas (IP e rota, nunca códigos ou cookies).

### Riscos e limites

- Só IPs de rede privada entram (`192.168/16`, `10/8`, `172.16/12`, `fd00::/8`, mais `100.64/10` do Tailscale);
  qualquer outro IP recebe 403 e quem não tem sessão recebe 401 em tudo, com uma página que não revela nada.
- **Com HTTPS** (padrão) o tráfego na rede local é criptografado. **Sem HTTPS** (modo de queda para HTTP) a conexão não é
  criptografada: quem estiver no mesmo Wi-Fi poderia ver o tráfego e **copiar o cookie** do celular pareado. O impacto é
  limitado: com o cookie dá para ver o escritório e, se o aparelho for "ver e conferir", marcar/desfazer "conferido" (no
  máximo 10 vezes por minuto, e ainda assim com o token anti-CSRF da sessão); tudo fica registrado e é reversível; liberar
  pontos, gerar código e revogar são só do PC.
- O servidor só aceita GET/HEAD, exceto o pareamento, as ações de XP e as rotas `/rede/` (só do PC); respostas levam
  `X-Content-Type-Options`, `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY`, `Cache-Control: no-store`, uma
  `Content-Security-Policy` própria e, no HTTPS, `Strict-Transport-Security`.
- Quem tem acesso físico ao PC, ou à conta dele, tem acesso a tudo (`ca.key`, `dispositivos.json` etc.): proteja o PC.

### Fora de casa: Tailscale

Nada aqui deve ser exposto à internet (nada de redirecionar porta no roteador). Fora de casa use o
[Tailscale](https://tailscale.com) (grátis para uso pessoal): instale no PC e no celular, ponha `"rede_tailscale": true` no
`config.json` e reinicie com `celular`. O servidor passa a aceitar também a faixa `100.64.0.0/10` e a CA é refeita com essa
faixa permitida (reinstale-a no celular). Abra `https://<IP do Tailscale do PC>:8766/` (o painel 📱 Celular lista os dois
endereços). Os nomes MagicDNS não entram na CA (ela só permite `localhost` e `*.local`): use o IP.

## 10. Alertas no celular

O escritório avisa quando **há algo esperando por você**, mesmo com o celular no bolso e a página fechada. Cada tipo liga e
desliga no botão **🔔 Alertas** (no topo da página, ou no menu ☰ do celular):

| Tipo | Quando avisa | Padrão |
|---|---|---|
| PR pronto para o seu merge | PR novo, ou que ficou pronto, com o check de revisão em SUCCESS, sem conflito e fora de rascunho | ligado |
| PR com conflito ou reprovado | PR que passou a ter conflito ou foi reprovado na revisão | ligado |
| Auditoria vermelha nova | item novo na lista 🔴 do Placar de XP (precisa de `xp.ativo`) | ligado |
| Item novo para conferir | item novo na lista 🟡 do Placar | **desligado** |
| Escalonamento aberto/fechado | registro de escalonamentos do Diretor (opcional, veja abaixo) | ligado |
| Pergunta de escopo do Diretor | mensagem (`SendMessage`) cujo texto começa com `PERGUNTA` ou contém "pergunta ao desenvolvedor" | ligado |
| Lembrete | PR pronto esperando há mais de 24 h (no máximo 1 lembrete por dia) | ligado |

### Como funciona

Uma thread do servidor olha, a cada 60 s, os dados que ele já tem (PRs em cache, placar de XP, eventos) e compara com o
estado em `dados/alertas_estado.json`, para **não repetir** o mesmo alerta. Na primeira leitura de cada fonte só se anota o
que já existia (nada de enxurrada). Os alertas vão para a fila `dados/alertas.jsonl` (os últimos 200) e saem em camadas:

1. **Web Push** (RFC 8030/8291/8292, VAPID, conteúdo cifrado aes128gcm): chega com o celular **e o escritório fechados**.
2. **Com o escritório aberto**: toast na página, Notification API (aba em segundo plano) e selo no botão 🔔, lendo
   `GET /api/alertas?desde=<id>` junto com o resto.
3. **No PC, opcional**: toast do Windows (`"toast_windows": true`; usa o PowerShell, sem instalar nada).

### Ligar no PC

Abra `http://localhost:<porta>/` (localhost conta como contexto seguro), clique em **🔔 Alertas → Ativar alertas neste aparelho**,
aceite a permissão do navegador e use **Enviar alerta de teste**. O Web Push precisa da biblioteca `cryptography`
(`pip install cryptography`); sem ela o painel avisa e as camadas 2 e 3 continuam funcionando.

### Ligar no celular

1. Deixe o acesso pelo celular funcionando **com HTTPS** (seção 9): o Web Push só existe em contexto seguro, ou seja, o
   endereço `https://<ip>:<porta+1>/` com a CA local instalada no celular.
2. Pareie o celular (QR code). Qualquer permissão serve ("só ver" também recebe alertas).
3. No celular: menu ☰ → **🔔 Alertas → Ativar alertas neste aparelho** → permitir → **Enviar alerta de teste**.
4. **iPhone/iPad (iOS 16.4 ou mais novo):** o push só funciona com o escritório na Tela de Início. No Safari, toque em
   Compartilhar → **Adicionar à Tela de Início**, abra o escritório por esse ícone e ative os alertas lá (a página mostra
   esta instrução quando detecta iOS fora do modo "app"). O ícone abre em tela cheia pelo `manifest.webmanifest` do servidor.
   Se o ícone pedir o QR code de novo, o iOS guardou a sessão só no Safari: gere outro QR e pareie de dentro do ícone.

Tocar na notificação abre o escritório já no painel certo (PRs ou Placar).

### O que vai (e o que não vai) no push

- Só um **título curto** (até 60 caracteres), um **corpo de até 120 caracteres** (ex.: "PR #303 foi aprovado e está sem
  conflito") e o painel a abrir. **Nunca** comando, caminho, código, token ou o texto da mensagem do agente (a pergunta do
  Diretor aparece só dentro da página). O texto passa por uma limpeza que remove endereços, caminhos, trechos de código,
  flags de comando e sequências longas que lembrem token.
- O push passa pelo serviço do navegador (Google, Mozilla, Apple ou Microsoft), mas vai **cifrado de ponta a ponta**: eles só
  veem texto cifrado, sem o conteúdo.
- Só um aparelho **pareado** (ou o próprio PC) se inscreve, com sessão e token anti-CSRF; o servidor só envia para endereços
  de serviços de push conhecidos (nada de enviar para a rede interna).
- **Revogar o aparelho apaga a inscrição** dele. Máximo de **20 envios por hora** (`limite_push_hora`); o excedente fica
  só na fila/página. Inscrição que o serviço diz estar morta (404/410) é apagada.
- As chaves VAPID e as inscrições ficam em `dados/push/` (fora do git; a chave privada nunca sai do PC). O histórico de
  envios (sem conteúdo) fica em `dados/push/envios.jsonl`; inscrever, sair e testar entram em `dados/acoes.jsonl`.

### Configuração (bloco `alertas` do `config.json`)

```jsonc
"alertas": {
  "ativo": true,                      // false desliga tudo (detector, fila e push)
  "tipos": {"pr_pronto": true, "pr_problema": true, "auditoria": true, "conferir": false,
            "escalonamento": true, "pergunta": true, "lembrete": true},   // padrão inicial de cada aparelho
  "lembrete_horas": 24,               // PR pronto esperando há mais que isso gera o lembrete diário
  "limite_push_hora": 20,             // máximo de pushes por hora (todos os aparelhos)
  "toast_windows": false,             // true: também um toast do Windows no PC (PowerShell, sem dependências)
  "contato": "mailto:alertas@example.com",   // identificação do servidor no VAPID (opcional; troque pelo seu e-mail)
  "escalonamentos": "",               // caminho de um JSON de escalonamentos (opcional, veja abaixo)
  "agentes_pergunta": ["Diretor"]     // só estes agentes disparam "pergunta de escopo" (vazio = qualquer um)
}
```

Cada aparelho ainda escolhe os seus tipos no painel 🔔 (o `tipos` do config é só o ponto de partida).

**Escalonamentos (opcional).** Se `alertas.escalonamentos` apontar para um JSON no formato
`{"2026-W40": [{"cartao": 86, "motivo": "...", "aberto": "2026-10-01", "fechado": null, "resultado": ""}]}`, o escritório
avisa quando um escalonamento abre e quando fecha. Arquivo ausente: essa fonte é ignorada.

### Testar

- Botão **Enviar alerta de teste** do painel (vai para a fila e, se este navegador estiver inscrito, para o push dele).
- `python -W error ferramentas/testar_alertas.py`: detector com dados simulados, fila, cifra do push decifrada de volta
  por uma implementação de referência (inclui o exemplo oficial do apêndice A da RFC 8291), assinatura VAPID verificada
  com a chave pública e envio a um "serviço de push" local de mentira.

### Não chegou?

| Sintoma | O que fazer |
|---|---|
| "As notificações deste site estão bloqueadas" | Libere as notificações do site nas configurações do navegador e ative de novo no painel. |
| O botão diz que exige conexão segura | Use `https://<ip>:<porta+1>/` (com a CA instalada) no celular, ou `localhost` no PC. |
| Android: só chega com o escritório aberto | Tire o navegador da economia de bateria e do "Não perturbe"; o Chrome precisa poder rodar em segundo plano. |
| iPhone: nada acontece | Precisa de iOS 16.4+, do escritório na Tela de Início e da permissão pedida de dentro do ícone. |
| "Web Push indisponível no servidor" | `pip install cryptography` e reinicie o escritório. |
| Parou de chegar depois de meses | A inscrição pode ter expirado: **Desligar push** e **Ativar** de novo. |

## 11. Times de agentes do Claude Code — dicas

- **Nomes**: o hook usa o nome que o Claude Code informa (nome do colega no time, `name` do subagente ou o
  `agent_type` de um `.claude/agents/<nome>.md`). Para cair na mesa certa, o `nome` no config precisa ser igual a esse
  nome — ou estar em `outros_nomes`. Sufixos numéricos (`Dev_235`, um por tarefa) são removidos.
- **Líder**: a sessão principal (quem cria o time) não tem nome de colega; ela aparece na mesa do agente com
  `"lider": true`. `main`, `lead`, `leader` e `team-lead` também significam o líder.
- **Reuniões**: mensagem para `"*"` (todos), para vários destinatários, com uma das `palavras_reuniao`
  (ex.: começar com "Reunião: …") ou o líder falando com 2+ colegas em 20 segundos.
- **Subagentes** (`Task`/`Agent`): sem nome do time, aparecem como "Assistente", "Explorador", "Planejador"… por
  ~20 s ao lado de quem os chamou. Com o nome de um agente do time, a tarefa vai para a mesa dele.
- **Outra sessão**: mensagens vindas de outra janela do Claude Code aparecem numa mesa "Outra sessão".
- Rótulos de PR e o campo "time" do Kanban viram cores de agente pelo mapa `github.times`.
- Para forçar o nome de quem roda uma sessão, defina a variável de ambiente `OFFICE_AGENTE=<nome>` antes de abrir o
  Claude Code.

## 12. Solução de problemas

| Sintoma | O que fazer |
|---|---|
| "Porta 8765 ocupada" | O escritório provavelmente já está rodando: o script só abre o navegador. Se for outro programa, mude `porta` no `config.json` ou use `reiniciar_escritorio`. |
| Kanban/PRs: "GitHub CLI (gh) não encontrado" | Instale o gh (https://cli.github.com) e rode `gh auth login`. O resto do escritório funciona sem ele. |
| Kanban: erro de permissão | `gh auth refresh -s project` (o Projects pede o escopo `project`). Confira `projeto_owner` e `projeto_numero`. |
| Kanban/PRs: "não configurado" | Preencha a chave `github` do `config.json` ou rode o `instalar.py` de novo. |
| O hook não registra nada | 1) Reinicie a sessão do Claude Code (hooks são lidos ao abrir). 2) A sessão precisa estar com o diretório de trabalho (`cwd`) dentro de uma das pastas de `projetos` — compare o caminho exato. 3) Rode `/hooks` no Claude Code para ver se os 4 eventos aparecem. 4) Teste à mão: `echo {"hook_event_name":"Stop","cwd":"<sua pasta>"} \| python registrar_evento.py` e veja `dados/eventos.jsonl`. 5) O `python`/`python3` do comando precisa existir no PATH. |
| Eventos caem na mesa errada / mesas a mais | Ajuste `nome` e `outros_nomes` dos agentes para os nomes que aparecem no feed. |
| Página em branco ou "WebGL indisponível" | Use um navegador atual com aceleração de hardware. Sem internet, o three.js do CDN não carrega: rode o `instalar.py` e responda "s" para baixar o three.js para `vendor/` (o servidor passa a usar a cópia local automaticamente). |
| QR/link não abre no celular (tempo esgotado), mas o celular abre o roteador | Quase sempre é sub-rede diferente, rede do Windows como Pública ou falta de regra de entrada no Firewall. Siga "Não abre no celular? (Firewall e rede)" na seção 9. |
| Alerta não chega no celular | Veja "Não chegou?" na seção 10 (permissão do navegador, HTTPS, iPhone na Tela de Início, `cryptography`). |
| Escritório em "demonstração" sozinho | A página não alcança o servidor: abra pelo `abrir_escritorio` e acesse `http://127.0.0.1:<porta>/`, não o arquivo direto. |

## 13. Desinstalar

```bash
python instalar.py --desinstalar
```

Remove **só** os hooks que chamam o `registrar_evento.py` desta pasta, do `~/.claude/settings.json` (ou o de
`--settings-usuario`) e dos `.claude/settings.local.json` dos projetos do config, sempre com backup
(`settings.json.bak-AAAAMMDD-HHMMSS`). Os outros hooks ficam intactos. Depois disso, apague a pasta do escritório
se quiser remover tudo.

## 14. Privacidade

- Tudo é local: o servidor escuta só em `127.0.0.1` e não envia nada para fora (a não ser que você ligue o acesso pelo
  celular, seção 9: aí ele também escuta na rede local, só para IPs privados com sessão pareada).
- Os eventos ficam em `dados/eventos.jsonl` na pasta instalada (resumos, comandos e trechos de mensagens entre
  agentes, até alguns KB por evento). Apague a pasta `dados/` quando quiser.
- O servidor não entrega `config.json`, `dados/` nem os scripts pela web.
- Alertas (seção 10): se você ativar o Web Push, o aviso passa pelo serviço do navegador (Google, Mozilla, Apple ou
  Microsoft), **cifrado**, com título e corpo curtos e sem comando, caminho, código ou token. Desativar o push neste
  aparelho (ou revogá-lo) apaga a inscrição.
- A única comunicação externa é opcional: o `gh` consultando o GitHub (Kanban/PRs) com a sua conta, e o three.js
  baixado do CDN jsDelivr (ou uma vez só, no instalador, se você escolher a cópia local).
