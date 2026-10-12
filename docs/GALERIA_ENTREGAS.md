# Galeria de entregas por commit

Abra **Gestão → Trabalho e indicadores → Galeria de entregas** no PC do
escritório. A lista mostra somente arquivos declarados, com cartão, tentativa,
PR, commit, tamanho e SHA-256. Não pesquisa pastas nem abre arquivos arbitrários.
A lista não está disponível para aparelhos pareados nesta primeira versão.

## Registrar durante uma publicação

O produtor pode acrescentar `arquivos_entrega` ao pedido já usado pela ação
`publicar` do controlador. Os caminhos são relativos ao worktree e precisam
existir como arquivos regulares no commit publicado. Exemplo de pedido:

```json
{
  "cartao": 7,
  "worktree": "D:/escritorios/worktrees/projeto-7",
  "titulo": "Entrega do cartão 7",
  "corpo": "Parte de #7\nEvidências e limites da entrega.",
  "arquivos_entrega": ["entregas/relatorio.md", "entregas/captura.png"]
}
```

```console
python controlador_local.py --projeto D:/projetos/meu-projeto --acao publicar --arquivo pedido-publicacao.json
```

Os requisitos da publicação continuam iguais: projeto ativo, worktree criado e
reservado pelo escritório, branch e cartão vinculados. A captura também exige
uma tentativa de execução registrada e contexto do worktree na reserva. Não
crie uma tentativa artificial para preencher a galeria. Pedidos antigos sem
`arquivos_entrega` continuam funcionando sem adicionar um catálogo vazio.

A captura ocorre depois da confirmação e gravação do recibo de publicação.
O resultado inclui `galeria.estado` igual a `registrado`, `ja_registrado` ou
`nao_registrada`. Uma falha de captura **não desfaz o PR e não autoriza repetir
publicar**. Confira o recibo e use a reconciliação abaixo.

## Registrar arquivos de uma publicação já concluída

Copie os identificadores exatos do recibo, sem inventar vínculo de tentativa,
PR ou commit. A ação é local: não faz push, consulta GitHub nem chama consoles.

```json
{
  "cartao": 7,
  "tentativa": "IDENTIFICADOR_DE_32_CARACTERES_DO_RECIBO",
  "pr": 8,
  "sha": "COMMIT_COMPLETO_DE_40_CARACTERES_DO_RECIBO",
  "arquivos": ["entregas/relatorio.md", "entregas/captura.png"]
}
```

```console
python controlador_local.py --projeto D:/projetos/meu-projeto --acao registrar-entregas --arquivo pedido-galeria.json
```

Exige um único recibo publicado que corresponda aos identificadores e à reserva.
Repetir o mesmo manifesto é idempotente. Mudar a lista/conteúdo de uma versão
já registrada é rejeitado; outra tentativa ou commit gera outra versão.
As versões antigas conservam os bytes capturados, mesmo após mudanças ou
remoção do worktree. A primeira captura exige os objetos Git disponíveis
localmente, sem busca automática pela rede.

## Formatos, privacidade e limites

- Texto UTF-8 (`.txt`, `.md`, `.csv`) é mostrado literalmente, sem executar HTML
  ou converter Markdown em HTML. A prévia de texto pode ser truncada; o download
  conserva todos os bytes.
- PNG, JPEG e WebP podem ser visualizados. A assinatura do formato é conferida;
  isso não substitui validação visual. Imagem inválida pode falhar no navegador.
- PDF e GLB são somente download inerte. HTML, SVG, scripts e arquivos JSON não
  são aceitos nesta versão.
- Até 20 arquivos, 1 MiB por arquivo/objeto Git, 5 MiB por manifesto, 100 MiB de
  conteúdo e 500 manifestos no banco. Ao atingir o limite, a captura falha sem
  apagar o histórico. A galeria lista os 100 manifestos mais recentes e avisa
  quando a cobertura é limitada.
- Caminhos absolutos, travessia, links simbólicos, submódulos, pastas ocultas,
  `dados`, nomes de credenciais e padrões reconhecíveis de chaves são recusados.
  Essa filtragem não detecta todo conteúdo privado. O produtor deve declarar
  apenas arquivos realmente destinados à entrega; não inclua segredos.
- O manifesto e os recibos continuam no `tarefas.db`. No Linux qualificado,
  novos corpos ficam em
  `dados/gestao/<projeto>/galeria-blobs-v1/<sha256>`, dentro da instalação do
  Office, com leitura limitada por hash. Linhas antigas continuam com os bytes
  originais no SQLite. Não há upload, compartilhamento externo ou segunda
  fonte de verdade para conclusões/aceites.
- A cadeia Git commit/árvore/blob e o SHA-256 do snapshot são conferidos. A
  prévia lê o snapshot imutável; não afirma que o arquivo atual do worktree é
  igual ao entregue. Corrupção do snapshot bloqueia a prévia.

## Estados e histórico

Retorno do console, revisão e merge são consultados em seus recibos existentes,
sem serem promovidos a aceite. Integridade prova os bytes armazenados, não
qualidade. Aprovação visual e aceite do usuário aparecem como **não registrados**;
esta versão não acrescenta uma forma paralela de aprovar, nem altera gates.

Para arquivar ou restaurar a apresentação de uma versão, use o ID do manifesto:

```json
{"id": "ID_COMPLETO_DO_MANIFESTO", "arquivada": true}
```

```console
python controlador_local.py --projeto D:/projetos/meu-projeto --acao arquivar-entregas --arquivo pedido-arquivo.json
```

Use `false` para restaurar. Arquivar não exclui manifesto, bytes ou recibos;
**Mostrar histórico arquivado** permite consultar as versões arquivadas.

## Verificação

```console
python -W error ferramentas/testar_galeria_entregas.py
node ferramentas/testar_galeria_entregas.mjs
python ferramentas/verificar.py
python ferramentas/verificar_docs.py
```

Os testes usam repositórios e recibos sintéticos locais. Nenhum teste requer
provider, credencial, publicação real no GitHub ou alteração de configuração
de segurança do computador.

## Armazenamento externo: alcance desta etapa

Novos corpos externos são qualificados somente no Linux, com diretórios sem
links, arquivos regulares com um único hardlink e permissões privadas.
Windows/macOS mantêm registro, repetição, arquivamento/restauração e leitura
**inline**, como antes, com os mesmos limites lógicos. Portanto, nessas plataformas
os bytes novos ainda contam no limite SQLite do Contexto. Em Linux uma falha de
segurança, disco ou qualificação nunca provoca fallback silencioso para inline.

Corpos externos criados no Linux ainda não têm leitura qualificada em Windows/macOS.
Copiar uma instalação com esses corpos para outro sistema não os converte: a
prévia/repetição desses snapshots é recusada, preservando os arquivos. Mantenha o
backup integral e use o Linux original para abri-los. Snapshots inline antigos
continuam legíveis. Não há conversão automática entre sistemas.

O discriminador `inline`/`externo-v1` distingue os formatos, inclusive arquivo
vazio. No primeiro registro, uma coluna aditiva pode ser criada; nenhum corpo
legado é esvaziado, movido ou eliminado. A repetição de um manifesto compara seus
bytes e metadados independentemente de como foram armazenados. Versão desconhecida,
corpo ausente, hardlink, hash incorreto ou conflito bloqueia a operação.

No Linux qualificado, essa etapa impede que **novos arquivos da galeria**
aumentem o banco com seus bytes. Ela **não reduz bancos antigos acima de 32 MiB** e não inclui migração,
compactação ou limpeza. O Contexto mantém exatamente seus limites e sua recusa de
WAL ativo; metadados de outras funções ainda podem fazer o banco ultrapassar o teto.

Os limites lógicos continuam em 100 MiB/500 manifestos, incluindo os arquivados.
Além deles há orçamento físico de 110 MiB e 10.020 entradas de corpo por projeto,
contando arquivos temporários próprios e órfãos de interrupções. A reserva é
serializada antes de gravar. O espaço extra serve à publicação atômica e falhas,
não amplia a quota de entregas. Atingir qualquer teto preserva os dados e recusa
novas capturas. Não há coleta automática de órfãos.

A publicação usa arquivo privado exclusivo, fsync e instalação sem sobrescrever
um hash existente. Só grava os metadados depois de confirmar o corpo durável.
Interrupção pode deixar um órfão sem manifesto. Um arquivo com dois hardlinks
interrompido entre publicação e remoção do nome temporário permanece bloqueado;
não se deve removê-lo nem relaxar a verificação por tentativa. Concilie no PC,
preservando os arquivos e o banco antes de qualquer reparo manual.

No Linux, mutações adquirem a mesma trava exclusiva `.APP.atualizacao.lock` do atualizador,
antecipadamente e até fechar os arquivos/banco, seguida da trava por projeto.
Trava existente nunca é roubada; processo encerrado abruptamente pode exigir
conciliação. Um processo carregado antes da troca da pasta do app recusa novas
mutações e precisa ser reiniciado. Isso exclui **essas mutações** do atualizador;
a atualização continua exigindo parar todos os servidores, controladores e
outros processos SQLite. Não é atualização ao vivo nem cerca todos os escritores.

Corpos externos são lidos sem escrita, com verificação de caminho/inode/tamanho e
SHA-256. As consultas SQL de metadados da galeria mantêm `mode=ro`, que pode
interagir com WAL/SHM; não recebem uma garantia nova de ausência total de escrita.
O Contexto, separado, continua usando somente sua imagem SQLite limitada em memória.

A cópia integral do atualizador inclui banco, blobs e órfãos sob `dados/`. Preserve
esse conjunto nos backups. Não reverta só o banco/código descartando corpos novos;
a reversão do instalador recusa dados alterados. SHA-256 verifica consistência
com metadados, não autentica alguém que possa adulterar ambos; a captura Git e os
vínculos de projeto/tentativa/recibo continuam necessários. Nenhum hash implica
qualidade, aprovação visual ou aceite humano.
