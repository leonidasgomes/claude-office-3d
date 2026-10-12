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
- O manifesto e os bytes vivem em tabelas do `tarefas.db` existente. Não há
  outro arquivo JSON como fonte de verdade, upload ou compartilhamento externo.
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
