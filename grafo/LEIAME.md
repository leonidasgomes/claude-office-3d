# grafo — grafo de arquitetura para agentes de IA

Ferramenta de linha de comando (Python 3.10+; roda no 3.9 com uma diferença: sem `sys.stdlib_module_names`, um
`import json` pode casar um `json.py` do repositório que esteja no `sys.path` do arquivo; só biblioteca padrão) que mantém um grafo de arquitetura **conferido contra
o código** e responde, barato, às perguntas que um agente faz antes de mexer no projeto: *de quem é este arquivo?*, *o
que preciso saber deste sistema?*, *o que minha mudança afeta e que testes rodo?*, *onde está X?*, *quebrei a
arquitetura?*. Funciona em qualquer repositório. No Claude Office 3D, o painel 🗺️ Arquitetura mostra o grafo do seu
projeto (seção "Grafo de arquitetura" do `INSTALACAO.md`).

Ideia central: **arestas estruturais são derivadas do código** (imports/includes reais), **intenção é declarada** (camadas,
`depends_on`, eventos, invariantes, ADRs), e o `validate` mostra a diferença entre os dois. O agente recebe **recortes
pequenos sob demanda** (dono, recorte, impacto) em vez de o grafo inteiro no contexto.

## Instalar

1. Copie a pasta `grafo/` (ou só `grafo.py`) para onde quiser. PyYAML é opcional: com ele (`pip install pyyaml`) o YAML
   é lido pelo PyYAML com recusa de chave repetida; sem ele (ou com `GRAFO_SEM_PYYAML=1`) entra um leitor próprio do
   subconjunto usado pelo formato (mapas e listas em bloco, `[a, b]`/`{a: b}` inclusive em várias linhas, aspas,
   blocos `>`/`|` com `-`/`+`, comentários, null/bool/números; datas ficam texto). Âncoras, aliases e tags não são
   aceitos sem PyYAML. A gravação (`init`) é sempre a do próprio `grafo.py` (saída determinística). Os testes conferem
   que os dois leitores dão o mesmo resultado nos YAML de teste.
2. No projeto: se ainda não há grafo, `python grafo.py init --saida docs/grafo.yaml` (propõe sistemas por pasta com
   `status: proposto`, `depends_on` derivado dos imports, camada vazia e testes por pasta; **nunca sobrescreve**). Revise
   nomes, camadas e descrições (ou rode `init --llm` e cole o prompt num modelo barato) e troque `status` para `active`.
3. Hooks do Claude Code (opcional, recomendado): `python grafo/claude/instalar_grafo.py --projeto <raiz>` mostra o que
   faria; `--aplicar` grava no `.claude/settings.json` **do projeto** (nunca no do usuário). `--copiar` põe `grafo.py` e
   o hook em `.claude/grafo/` do projeto (o time recebe pelo git) e `--skill` copia a `SKILL.md` para
   `.claude/skills/grafo/`. `--desinstalar --aplicar` remove só as entradas do grafo. Os comandos usam o caminho
   absoluto do Python que rodou o instalador (no macOS/Linux pode não existir `python` no PATH); `--python` troca. Com
   `--copiar` o padrão é `python` (o `settings.json` vai para o git do time; o instalador avisa para usar
   `--python python3` se for o caso). Fora de um repositório (pasta atual ou `--projeto` na home, ou um repositório de
   dotfiles na home) o alvo seria o `~/.claude/settings.json` do usuário: o instalador recusa com código 2.
   `settings.json` com forma inesperada (JSON inválido, `hooks` que não é objeto de listas) aborta com código 2 sem
   alterar nada.
4. Opcional: `.grafo/` no `.gitignore` (artefatos derivados do `index`).

Configuração opcional na raiz: `grafo.json` (ou `.grafo.json`/`.grafo.toml`):

```json
{"grafo": "docs/ARCHITECTURE_GRAPH.yaml", "raizes": ["src"], "extensoes": [".py", ".ts"], "ignorar": ["src/gerado/**"],
 "raizes_python": ["src"], "saida": ".grafo", "regras": ".claude/rules", "base": "origin/main", "orcamento": 600}
```

`saida` e `regras` vindos da configuração precisam ficar dentro do projeto (pela linha de comando, `--saida` é livre).
Toda ref do git (`--base`, `--diff`, `base`) que comece com `-` é recusada, e só o SHA verificado por
`git rev-parse --verify --end-of-options REF^{commit}` chega ao git.

Sem configuração, o grafo é procurado em `docs/ARCHITECTURE_GRAPH.yaml`, `ARCHITECTURE_GRAPH.yaml`, `docs/grafo.yaml`,
`grafo.yaml`, `.grafo.yaml`, `docs/architecture.yaml`, `architecture.yaml`; `--grafo` vale em todos os comandos. A raiz é
o topo do git (`--raiz` para outra).

## Comandos

| Comando | O que faz |
|---|---|
| `init [--saida A] [--llm] [--ext .py,.ts] [--raizes src,lib] [--max-arquivos 40]` | propõe um grafo (pasta grande se divide nas subpastas; arquivos diretos viram `pasta/*`); `--llm` só imprime o prompt para um modelo barato nomear/descrever (não chama modelo) |
| `validate [--base REF] [--strict] [--json]` | esquema, ids, enums, referências, duplicidades (id, símbolo, dono), ciclos e camadas **declarados**, caminhos inexistentes, código órfão (com sugestão), `classes` existentes no C/C++, documentos citados; **e o novo**: aresta real não declarada (aviso), dependência declarada sem uso (aviso), **ciclo real** e **camada violada no código** (erros, com arquivo:linha). `--base` olha só o que mudou desde REF (diff + não rastreados); as checagens do YAML só rodam se o YAML mudou |
| `owner <arquivo> [--json]` | dono: caminho exato > pasta (ou padrão) mais longa; empate: o último declarado vence (como CODEOWNERS); um padrão que casa uma pasta (`src/Foo*`) é dono do que está dentro dela. Aceita absoluto, `\` do Windows, worktrees (`.claude/worktrees/<n>/`, outro clone) e maiúsculas diferentes. Código 1 se não tem dono (com sugestão) |
| `suggest <arquivo> [--json]` | dono provável de um arquivo sem dono: vizinhos da mesma pasta (subindo até achar) + maioria dos imports |
| `slice <sistema\|arquivo> [--budget N] [--reais] [--json]` | recorte: resumo, paths compactados, invariantes/armadilhas/entradas, vizinhos de 1 salto nos dois sentidos, eventos, testes, ADRs (por título); corta pelo orçamento (~4 caracteres/token; padrão 600) e diz o que cortou. `--reais` acrescenta imports não declarados |
| `impact <arquivos...> \| --diff REF [--json]` | sistemas tocados; impactados (fecho reverso de `depends_on` + arestas reais, com a distância); testes (`*` = cobrem o tocado ou o arquivo); ADRs; arquivos que importam os mudados |
| `find <texto> [--max 8] [--arquivos 12] [--json]` | casa ids, nomes, descrições, classes, caminhos, **símbolos extraídos** (def/class, class/struct/enum/UCLASS, `Classe::Metodo`, function/class/interface, métodos C#, funções PowerShell/shell) e conteúdo; pontua por especificidade e lista **os arquivos que casaram** (motivo e linha) |
| `drift [--json]` | % de arquivos com dono, órfãos, arestas reais / não declaradas / declaradas sem uso, ciclos e camadas violadas no código, paths quebrados, dias desde `updated`, sistemas sem descrição curta, propostos |
| `index [--saida DIR]` | `index.json` (arquivo → sistema; sistemas com camada, status, cor sugerida por camada, paths, deps, eventos, testes, ADRs; arestas declaradas, reais com tipo `declarada`/`evento`/`nao_declarada` e exemplo; eventos; testes; ADRs; assinatura do grafo) e `resumo.txt` (1 linha por sistema: `id \| camada \| paths \| deps \| eventos produz>consome`, com abreviações de pasta `@n/`); determinísticos, padrão `.grafo/` |
| `sync-rules [--saida .claude/rules] [--escrever]` | gera `arq-<sistema>.md` com front matter `paths:` (pasta vira `pasta/**`) e 5–10 linhas (o que é, depende de, usado por, invariantes/armadilhas, testes, ADRs). Sem `--escrever` só mostra. Remove só regras geradas (marca no arquivo) de sistemas que sumiram |

Saída: 0 ok; 1 achado (validate reprovado, sem dono, nada encontrado); 2 erro de uso/leitura (grafo ausente, ref inválida).

## Formato

Dois estilos, lidos pelo mesmo código:

- **Com includes**: `ARCHITECTURE_GRAPH.yaml` com `schema_version`, `project`, `updated`, `layers`
  (`may_depend_on`), `coverage` (`roots`, `extensions`, `ignore`), `data_sources`, `tests`, `decisions` e
  `includes: {systems: SYSTEMS.yaml, events: EVENTS.yaml, features: FEATURES.yaml}` (caminhos relativos ao grafo; include que
  sai da raiz do projeto não é lido e vira erro de leitura). Campo de texto que vem como número/booleano no YAML (`name:
  2024`) vira texto. O validador próprio do projeto
  continua valendo (Mermaid, quase-duplicidades por nome, símbolos de evento); o `grafo validate` o complementa.
- **Arquivo único** (projetos novos; é o que o `init` grava): as mesmas seções (`systems`, `events`, `tests`,
  `decisions`, `features`, `data_sources`) direto no YAML.

Nós e campos obrigatórios são os do formato com includes (ids `sys.`/`evt.`/`feat.`/`ds.`/`test.`/`adr.` em
snake_case). `status: proposto` é aceito para sistemas (vira aviso, e camada/descrição vazias também). Campos opcionais
reconhecidos (nenhum é obrigatório):

| Onde | Campo | Uso |
|---|---|---|
| sistema | `summary` | descrição curta (≤ 200 caracteres) usada por slice/hook/regras; sem ela, a 1ª frase de `description` |
| sistema | `entrypoints`, `invariants`, `pitfalls`/`lessons`, `extension_points` | entram no slice e nas regras |
| sistema | `test_cmd` | comando de teste do sistema (slice, impact, hook) |
| sistema | `produces`, `consumes` | eventos (ou fontes de dados) que o sistema produz/consome |
| evento | `caller`, `callee` | sentido explícito da chamada (explica o import `caller -> callee`) |
| teste | `command` | comando para rodar (impact, slice, regras) |

### Como as arestas reais são achadas (heurísticas, sem tree-sitter)

- Python: `ast` (imports no módulo e dentro de funções/try), com regex de reserva; relativo pelo pacote; absoluto, nesta
  ordem: mesma pasta; biblioteca padrão é ignorada; pacote do próprio repositório pela raiz; por fim, o arquivo cujo
  caminho termina no módulo, **só se** a pasta dele aparece no `sys.path.insert/append` do arquivo (seguindo as
  variáveis e o `for p in (...)` usados ali) **ou de um módulo do repositório que ele importa** (até 2 níveis, com
  cache: "importar X também põe Scripts/World no sys.path"), sobe a partir do arquivo (`parent`, `..`) ou está em
  `raizes_python` da configuração (ex.: `["src"]`). Nada do repositório casou: import externo, ignorado (um
  `tools/yaml.py` não vira dono do `import yaml` se ninguém põe `tools/` no `sys.path`). O que está instalado na máquina
  (pip) não é consultado: o `index.json` é o mesmo em qualquer máquina.
- C/C++: `#include "x"`/`<x>` relativo à pasta ou pelo sufixo do caminho (headers da engine ficam de fora por não
  existirem no repositório).
- JS/TS: `import ... from`, `export ... from`, `require()`, `import()` relativos (com `.ts/.tsx/.js/...`, `index.*`
  e `.js` → `.ts`). Aliases de `tsconfig` não são resolvidos.
- C#: `using X.Y;` → arquivos que declaram `namespace X.Y`.
- Scripts (`.ps1 .psm1 .sh .bat .cmd`): caminhos de scripts citados **numa linha de chamada** (`&`, `.`, `python`,
  `call`, `source`, `Join-Path`, `Start-Process`, `Invoke-Expression`, `-File`...), fora de comentários (`#`, `REM`,
  `::`, `//`, `<# #>`) e de textos de `throw`/`Write-Host`/`echo`/`print`.
- Aresta entre sistemas = arquivo de A referencia arquivo de B. É **declarada** se B está em `A.depends_on`; é
  **evento** se um evento de código (`kind` call/input/delegate, ou com `caller`/`callee`) a explica: o sentido é
  `caller -> callee`, ou, sem eles, "quem chama o dono da classe do símbolo" (`Classe::Metodo` + `classes` dos
  sistemas); delegate vale nos dois sentidos. Eventos `file`/`log`/`config` são troca de dados e não explicam import.
  Ciclos e camadas reais usam as arestas declaradas e não declaradas (as de evento ficam fora, como manda a convenção
  "chamada para cima é evento").

## Integração com o Claude Code

Arquivos em `grafo/claude/`: `SKILL.md` (curta: qual comando para qual pergunta), `hooks/grafo_hook.py` e
`instalar_grafo.py`. Os hooks nunca derrubam o agente: qualquer falha sai com código 0 e sem saída; a saída é JSON em
ASCII (o Claude Code lê a saída do hook fora de UTF-8 no Windows); `additionalContext`/`systemMessage` ficam abaixo de
10.000 caracteres.

| Evento | Comando | O que faz |
|---|---|---|
| `PreToolUse` `Edit\|Write\|MultiEdit` | `grafo_hook.py pre` | na **1ª vez por sessão** que o agente toca um sistema, injeta ~150–250 tokens: "arquivo do sistema X; resumo; depende de; usado por; invariantes; testes; ADRs; mais: slice". Estado por sessão em `<temp>/grafo-claude/` (`GRAFO_ESTADO` muda a pasta; limpo após 3 dias). Modelo do grafo em cache na mesma pasta, refeito quando muda o conteúdo do YAML ou de `grafo.json`/`.grafo.json`/`.grafo.toml` |
| `PostToolUse` `Write` | `grafo_hook.py post` | arquivo de código novo (dentro da cobertura) sem dono → `additionalContext` com a sugestão de dono (uma vez por arquivo) |
| `Stop`, `TaskCompleted` | `grafo_hook.py fim [--bloquear] [--base REF]` | `validate --base` (REF: `base` da configuração ou o merge-base com `origin/HEAD`/`origin/main`/`main`...); sai na hora, calado, se nenhum arquivo coberto nem o YAML mudou. Padrão: só avisa (`systemMessage`, para o humano; não repete o mesmo aviso na sessão). Com `--bloquear` e erro: Stop devolve `decision: block` (não repete com `stop_hook_active`) e TaskCompleted sai com código 2 (o motivo volta ao agente) |

Também dá para usar as regras por caminho do Claude Code: `sync-rules --escrever` gera `.claude/rules/arq-*.md`, que só
entram no contexto quando o agente lê arquivos daquele sistema.

## Modo Teams (líder + colegas)

O colega **não herda o histórico do líder**: o recorte tem de ir no prompt de criação.

1. Líder, antes de despachar: `python grafo.py impact <arquivos do cartão>` (ou `--diff origin/main` numa branch) para
   ver sistemas tocados/impactados e testes; depois `python grafo.py slice <sistema> --budget 400` de cada sistema
   tocado.
2. **Um sistema por colega** (paralelismo sem conflito): divida o cartão pelos sistemas tocados; colegas em sistemas
   vizinhos recebem no prompt o `depende de`/`usado por` do slice para combinar interfaces por mensagem.
3. Cole no prompt do colega: o slice (≤ 400 tokens), os testes `*` do impact e a regra "import de outro sistema exige
   `depends_on`; arquivo novo precisa de dono (`grafo.py suggest`)".
4. Com os hooks instalados no projeto, cada colega recebe o contexto do sistema na 1ª edição e o aviso de arquivo sem
   dono; o `TaskCompleted` roda `validate --base` antes de a tarefa ser dada como concluída.

## Custo

- Nada aqui chama modelo (o `init --llm` só imprime o prompt; ~200–400 tokens de entrada por 30 sistemas).
- Projeto real de referência (31 sistemas, ~56 mil tokens de YAML): `resumo.txt` ~1.000 tokens; `slice` 250–600 tokens; hook `pre`
  ~150–250 tokens uma vez por sistema por sessão; `validate`/`drift`/`find` ~3 s numa cópia sem git (com git a listagem
  é mais rápida); `owner` sem varrer o código.
- Os hooks rodam como processo local (sem tokens); só o texto que injetam entra no contexto.

## Testes

`python -W error grafo/testes/testar_grafo.py` — repositório git temporário com Python/C++/TS falsos e um grafo com
problemas conhecidos (aresta real não declarada, ciclo real, camada violada, órfão, caminho inexistente): init,
validate (inclusive `--base`, sem PyYAML), owner/suggest (Windows, worktree, outro clone, maiúsculas), slice
(orçamento), impact (`--diff`), find, drift, index e sync-rules determinísticos, hooks (JSON válido, uma vez por
sessão, bloqueio, entrada quebrada), instalador (sem duplicar, desinstalar, `--copiar`). Fumaça opcional contra um
projeto seu: `GRAFO_BASE_EXEMPLO=<raiz com docs/ARCHITECTURE_GRAPH.yaml>` (sem a variável, é pulada).

## Limitações

- Heurísticas de import: sem tree-sitter; macros, imports dinâmicos (`importlib`, `__import__`), `sys.path` montado em
  tempo de execução, aliases de TS e regras de módulo de build (`*.Build.cs`) não são entendidos; módulo de mesmo nome em duas
  pastas é resolvido pelo mais próximo do importador. O `sys.path` herdado é seguido só até 2 níveis de import.
- Referência a script só conta em linha de chamada; caminho montado em variável numa linha e usado em outra só é
  visto se a linha da montagem tiver `Join-Path` (ou outro contexto de chamada).
- `validate --base` sai na hora (código 0, `info.atalho`) se nenhum arquivo coberto, nenhum path declarado, o YAML e a
  configuração não mudaram; sem atalho, não roda as checagens do YAML se ele não mudou; paths de arquivos apagados/renomeados no diff são conferidos.
- "Dependência declarada sem uso" é só aviso: dependência por dados/arquivo/processo é legítima e não aparece no código.
- O sentido de eventos `call` sem `caller`/`callee` depende de `classes` registradas; sem elas, o evento explica os dois
  sentidos.
- `find` lê o conteúdo dos arquivos cobertos a cada chamada (sem índice persistente de busca).
- Não gera Mermaid nem confere símbolos de eventos (o validador do projeto faz isso).
