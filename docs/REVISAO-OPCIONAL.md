# Revisão por projeto

No painel Gestão, abra **Configurar revisão deste projeto**. Desmarque **Exigir
revisão por IA** para executar sem revisores. Salve a política. Isso afeta somente
o projeto selecionado; os revisores cadastrados e suas configurações são mantidos.

Quando habilitada, configure a quantidade de fornecedores distintos (inteiro
positivo) e a exigência de fornecedor diferente do autor. A execução verifica
identidade e disponibilidade antes do despacho. Fornecedor desconhecido não
comprova independência. O auditor automático exige revisão ativa com pelo menos
dois fornecedores e separação do autor; desativá-la com auditor ativo é rejeitado.

A fonte única continua sendo `.office/projeto.json`, no bloco `revisao`:

```json
{"ativo": false, "clouds_distintas": 2, "separar_autor": true, "revisores": []}
```

O painel modifica somente as três opções; para cadastrar modelos/executores,
edite `revisores` na política do projeto. Cada revisor pode ser suspenso com
`ativo: false`; omitido significa habilitado.

Desativar a revisão por IA não remove checks obrigatórios do GitHub, proteções de
branch, requisitos de entrega ou regras de merge. O cartão pode seguir para a
coluna Em revisão do Kanban mesmo sem revisão por IA. A mudança não aprova tarefas
em curso automaticamente: evidências ligadas à política anterior precisam ser
conferidas novamente. Projetos novos já começam com revisão por IA desativada.

A edição pelo painel ocorre somente no PC, com backup exato em
`.office/historico-politica`, hash de versão e gravação atômica. Salvar não chama
modelos, faz merge ou altera as políticas de outros projetos.
