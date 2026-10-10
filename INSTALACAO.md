# Instalação do Office Multi-provider 2.x

A edição nova usa pasta, configuração e bancos próprios. Comece por este guia
para cadastrar projetos e escolher CEO, diretor e equipes. A integração de
hooks/statusline Claude está em [Claude — compatibilidade](docs/CLAUDE-COMPATIBILIDADE.md).
Confira [VERSOES](docs/VERSOES.md) antes de migrar; o arquivo histórico não é backup
dos dados atuais. O instalador recusa outra edição ou destino ocupado sem identidade.

## Preparar as ferramentas

O servidor/assistente usa Python 3.9+ com biblioteca padrão. Git e GitHub CLI são
necessários para o fluxo gerenciado de worktrees/Kanban. Instale os consoles
escolhidos na política; encontrar o executável não comprova login, cotas ou modelo.
Recursos opcionais, como Web Push, têm requisitos próprios no guia de compatibilidade.

### Preparação do Windows sem Python

Na pasta extraída da edição 2.x, abra `preparar_maquina.bat`. Ele usa o PowerShell
do Windows, pergunta quais consoles instalar e mostra o plano antes de confirmar.
Também pode conferir pelo terminal:

```powershell
powershell.exe -NoProfile -File .\preparar_maquina.ps1 -Consoles claude -PastaFerramentas D:\OfficeTools
```

Somente componentes ausentes entram no plano: Python, Git, GitHub CLI e consoles
escolhidos; Node entra quando necessário para Codex, Gemini ou OpenCode. O preparador
exige Python 3.9+ e Node 22+ quando este for usado. Versão instalada incompatível
bloqueia; não atualiza automaticamente. WinGet precisa estar disponível para
instalar dependências e Claude; ausência do gerenciador é mostrada no plano.

O plano usa [WinGet](https://learn.microsoft.com/en-us/windows/package-manager/winget/install)
e os pacotes dos guias oficiais de [Claude](https://code.claude.com/docs/en/setup),
[Codex](https://developers.openai.com/codex/cli/),
[Gemini](https://geminicli.com/docs/get-started/installation/) e
[OpenCode](https://opencode.ai/docs/). O destino solicitado ao WinGet depende do
suporte de cada pacote; ele pode pedir aceite e elevação. O script não contorna
essas solicitações nem muda a política de execução do Windows.

A aplicação exige confirmar o plano atual. Usa pasta própria identificada por
`office-maquina.json`, recusa pasta ocupada sem essa identificação e interrompe
se o estado mudar. Cache/tmp ficam nessa pasta. Novos caminhos de ferramentas
são acrescentados ao PATH do usuário após sucesso, com backup local
`path-anterior-*.json`; esse backup não pertence ao pacote público. Falha pode
deixar componentes parcialmente instalados: confira o erro e refaça a prévia.
Reabra o terminal ao terminar e siga com `iniciar_projeto.py`.

Não instala modelos locais, autentica contas, altera hooks do projeto ou inicia
agentes. Login, modelos gratuitos disponíveis, cotas e acesso ao Kanban devem
ser verificados separadamente. Os testes simulam instaladores em PowerShell
nativo; uma instalação real em Windows limpo ainda precisa ser validada.

## Criar o escritório e cadastrar o projeto

Extraia o ZIP da nova edição. No terminal da pasta extraída:

```powershell
python iniciar_projeto.py --projeto D:/projetos/meu-jogo --destino D:/escritorios/meu-jogo --porta 8766
```

O assistente pergunta CEO, diretor, equipes, Kanban e revisores e apresenta a
prévia. Acrescente --exigir-requisitos para bloquear aplicação com requisitos
locais ausentes. Confira as escolhas e repita com --aplicar. Para uma política
já revisada, use --politica caminho/projeto.json. O projeto deve existir; o destino
inicial deve estar vazio e separado do projeto. Abra abrir_escritorio.bat no destino
(Linux/macOS: abrir_escritorio.sh).

O comando copia o aplicativo, cadastra o projeto e cria somente instruções/política
ausentes. Repetição com mesma política/projeto/porta preserva dados e configuração.
Não instala hooks/statusline, autentica contas, inicia agentes, baixa modelos ou
altera o GitHub. A preparação Windows é uma etapa separada. Divergências em arquivos
existentes exigem conciliação; não há rollback global após uma falha parcial.

Para outro projeto, faça prévia com --cadastrar-projeto, a mesma porta e uma política
própria; repita com --aplicar após conferir. Os projetos anteriores são preservados,
com backup da configuração. Detalhes do cadastro e da política em [GESTAO](docs/GESTAO.md).

## Selecionar consoles e equipes

No painel Gestão, escolha os consoles de CEO/diretor/equipes e cadastre especialistas
com nome, função e equipe. As escolhas são salvas na política do projeto selecionado.
O padrão de novos projetos é merge manual e execução local desativada. Auto-merge é
opção de cada projeto, respeitando checks/exceções; O projeto de validação tem política própria.
Consulte [GESTAO](docs/GESTAO.md) para gates, revisão independente e roteamento.

Use [PROVIDERS](docs/PROVIDERS.md) para comandos de Claude, Codex, OpenCode e Gemini,
autenticação no cliente nativo, contexto/skills e limites de capacidades. Modelos
OpenCode gratuitos são escolhidos explicitamente no catálogo consultado; não há
fallback para pago. Skills permanecem nas fontes configuradas, sem copiar corpos;
hooks, permissões e ferramentas específicas não são convertidos automaticamente.

Local é opcional, para tarefas simples e recursos disponíveis, conforme política
e gates de CPU/RAM/VRAM. O preparador não baixa modelos. Equivalência de Team nativo,
revisões cloud e disponibilidade de contas não são comprovadas pela instalação.

## Integrar o Claude existente

Para configurar hooks/statusline na instalação nova, use python instalar.py
(Windows: instalar.bat; Linux/macOS: instalar.sh). Esse assistente tem um fluxo
específico Claude e mostra o plano antes de gravar. Escopo, backup, convivência com
outros hooks e remoção estão no [guia de compatibilidade](docs/CLAUDE-COMPATIBILIDADE.md).
Confira os caminhos de hooks ao migrar; não renomeie o legado nem acrescente marcador
de edição para forçar atualização. A ponte opcional lê eventos antigos sem migrar
custos, reservas ou sessões; veja [GESTAO](docs/GESTAO.md).

## Usar os indicadores e conferir a instalação

Gestão mostra tarefas, atividade, resultados por tentativa, duração e consumo
vinculado por projeto/equipe/modelo. Placar mostra limites disponíveis por fornecedor;
cota desconhecida permanece desconhecida. Equivalente teórico de API não é fatura
ou custo de assinatura. Nenhum indicador libera revisão ou merge.

Diagnóstico e prévia verificam requisitos locais, não inferência cloud ou qualidade.
Instalação Windows limpa e operação integral das equipes ainda precisam de provas
nativas. Estado da edição em [VERSOES](docs/VERSOES.md); arquitetura/contratos em
[SDD](docs/SDD.md). Para celular, Web Push, grafo, XP e hooks, consulte o guia de
compatibilidade. Em gestão ativa, a política por projeto continua sendo a autoridade.

## Onde cada regra fica

| Fonte | Responsabilidade |
|---|---|
| INSTALACAO.md | Preparar máquina/aplicativo e seguir para configuração de projeto |
| docs/GESTAO.md | Gestão e política por projeto, papéis, Kanban e gates |
| docs/PROVIDERS.md | Consoles, contexto compartilhado e compatibilidade de skills |
| docs/CLAUDE-COMPATIBILIDADE.md | Hooks/statusline e recursos globais compatíveis |
| docs/SDD.md | Interfaces, persistência e contratos verificados contra o código |
| docs/VERSOES.md | Identidade da edição, separação e limites de migração |
