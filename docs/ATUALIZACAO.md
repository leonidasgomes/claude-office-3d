# Instalar e atualizar 2.x com preservação

`iniciar_projeto.py` prepara o projeto e cria uma instalação nova. Repetir esse
comando numa instalação existente **não atualiza o código**. Use o fluxo abaixo
para atualizar a edição 2.x; a edição Claude 1.x deve continuar separada.

## Preparar

1. Baixe o ZIP do pacote 2.x na página oficial de releases do repositório
   leonidasgomes/claude-office-3d. Extraia em uma pasta nova, fora da instalação.
   Não extraia por cima da instalação existente. Confira o SHA-256 publicado.
2. Pare o escritório e todos os agentes/escritores que usam sua pasta. Feche os
   terminais que têm essa pasta como diretório atual, especialmente no Windows.
   O atualizador não encerra processos. A checagem da porta configurada e a
   detecção de processos no Linux são auxiliares; não substituem parar o app,
   inclusive quando ele foi aberto com uma porta diferente.
3. Reserve espaço para uma cópia completa da instalação, incluindo dados e
   `.venv`. A cópia original fica guardada como backup após a troca. Não execute
   outras operações de instalação/cadastro durante esse processo.
4. Execute os comandos **na pasta do pacote novo**, com Python 3.9+ (`python3`
   no Linux/macOS). Os exemplos usam aspas para aceitar espaços nos caminhos.

```sh
python atualizar_instalacao.py --destino "/caminho/Meu escritorio"
python atualizar_instalacao.py --destino "/caminho/Meu escritorio" --aplicar
```

Sem `--aplicar` não há gravações, locks ou backups. A prévia omite o conteúdo da
configuração. A aplicação revalida os arquivos antes de trocar as pastas.

### Instalações dev.5/dev.6 sem manifesto

Informe também o pacote **da mesma versão que está instalada**, extraído de uma
release oficial confiável. Não reutilize a instalação modificada como referência.
O atualizador lê a lista de arquivos sem executar o código desse pacote anterior.
Essa referência comprova correspondência local, não autenticidade do download.

```sh
python atualizar_instalacao.py --destino "/caminho/Meu escritorio" --pacote-anterior "/downloads/office-multi-provider-v2.0.0-dev.5"
python atualizar_instalacao.py --destino "/caminho/Meu escritorio" --pacote-anterior "/downloads/office-multi-provider-v2.0.0-dev.5" --aplicar
```

Configuração, porta, dados, arquivos desconhecidos, skills, hooks, políticas e
projetos permanecem como estavam. Os quatro atalhos gerados pelo instalador
anterior são reconhecidos apenas quando iguais aos modelos conhecidos. Código
personalizado, pacote incompleto ou colisão de um novo arquivo com arquivo do
usuário bloqueiam a atualização. Preserve suas personalizações separadamente e
revise o conflito; não apague dados nem edite o manifesto para forçar a operação.

Novas instalações pelo `iniciar_projeto.py` já registram o manifesto. Também é
possível instalar somente o app em pasta vazia usando `--config config.json`
com `atualizar_instalacao.py`. Esse comando não configura projetos, providers,
contas, hooks, atalhos do desktop ou ambientes virtuais.

## Backup, reversão e interrupções

A aplicação prepara uma pasta irmã, confere os hashes e guarda um recibo JSON
antes das renomeações. O caminho do recibo e do backup aparece no resultado.
O backup contém a instalação original inteira, inclusive arquivos privados;
proteja-o como protege a instalação. Não o publique nem envie ao repositório.
Não há exclusão automática de backups.

Antes de abrir o escritório novamente, uma reversão pode ser testada assim:

```sh
python atualizar_instalacao.py --reverter "/caminho/Meu escritorio.backup-ID.json"
python atualizar_instalacao.py --reverter "/caminho/Meu escritorio.backup-ID.json" --aplicar
```

A reversão guarda a instalação substituída em outra pasta, sem descartá-la.
Mudanças posteriores no conteúdo, nos caminhos, nos links ou nos modos dos
arquivos bloqueiam uma reversão integral: não se perde trabalho novo para voltar a uma versão.
Nesse caso, preserve ambas as cópias e faça uma recuperação revisada.

Se uma renomeação falhar, a ferramenta tenta devolver a pasta original. Não
promete transação atômica contra queda de energia. Se o processo for interrompido
entre as renomeações e o destino desaparecer, o mesmo `--reverter RECIBO` recupera
o backup após conferi-lo. Um lock órfão exige primeiro verificar que nenhum
atualizador está executando; só então remover o arquivo `.NOME.atualizacao.lock`
indicado ao lado do destino e repetir a prévia. Nunca remova a pasta de backup
ou a pasta `.NOME.preparando-*` sem conferir o recibo e as cópias existentes.

Links de arquivos pessoais e do `.venv` são copiados sem seguir seu destino.
Links nos caminhos de código/configuração, junctions/reparse points, hardlinks,
montagens internas e arquivos especiais são recusados. Erros de acesso, falta
de espaço e arquivos abertos no Windows bloqueiam a troca. Não há alteração de
permissões de sistema nem tentativa de contornar esses bloqueios. Concorrência
com processos que continuam gravando ou alteram caminhos de propósito não é
suportada: pare todos os escritores antes de aplicar.

## Limite de plataforma desta primeira versão

A troca/reversão de instalações existentes é habilitada inicialmente somente em Linux, para
arquivos com proprietário e grupo do usuário atual, sem ACL personalizada nem
bits especiais. Falha ao inspecionar ACLs também bloqueia a aplicação. macOS e
outros POSIX aguardam uma inspeção nativa de ACL qualificada.
O copiador padrão não preserva ACLs nativas do Windows nem proprietários diferentes;
esses casos são recusados antes da troca, sem tentar alterar permissões. No Windows,
a prévia e a instalação nova em pasta vazia continuam disponíveis; a atualização
existente aguarda implementação e qualificação de uma cópia nativa com ACLs.
Não confunda testes sintéticos Linux com validação em Windows real.

O assistente legado `instalar.py` conserva seu comportamento de configuração e
cópia. Ele não oferece a transação de atualização descrita aqui. Não o use para
substituir o código de uma instalação com dados que pretende preservar.

A comparação de conflito cobre conteúdo, caminhos, links e modos de arquivo;
não cobre timestamps nem todos os atributos estendidos. Atributos de privilégio
`security.*` também são recusados. O backup original é preservado por renomeação.

O manifesto `.office-pacote.json` e seus hashes verificam correspondência local,
não autenticidade: obtenha também o pacote novo por uma release oficial confiável.
Módulos gerenciados que desapareceram da release nova são conservados nesta etapa;
o atualizador não faz limpeza automática de arquivos antigos. Revise uma eventual
limpeza separadamente, depois de conferir compatibilidade e backup.
