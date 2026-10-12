# Contexto pesquisável do projeto

Busca local, somente leitura, para consultar referências. Não escreve memória de
agentes, não altera regras, não prepara prompts e não chama modelos, GitHub ou
consoles. As referências históricas não substituem a documentação atual.

## Fontes e proveniência

- Somente os arquivos explicitamente configurados em `fontes.regras`,
  `fontes.produto` e `fontes.arquitetura`. Não há descoberta de arquivos nem busca
  recursiva. O diagnóstico de presença já existente em Gestão continua separado.
- Cada documento é um snapshot da árvore de trabalho atual, inclusive mudanças
  ainda não commitadas. Mostra papel, caminho relativo permitido, SHA-256 dos
  bytes, data de modificação local, linha e um trecho. A data não é data de commit.
- O histórico usa apenas conclusões locais do mesmo projeto/repositório com
  estado concluído, cartão/PR/head/merge vinculados, data de merge válida, gates
  registrados como sucesso e proveniência GDD. Título/objetivo e equipe são as
  únicas informações textuais extraídas do pacote. Prompt, sessão, token e
  caminhos de execução nunca fazem parte do resultado.
- O SHA de merge, head, data de merge, hash da evidência, objetivo/hash do GDD e
  link validado do PR acompanham o resultado histórico. A evidência é registrada
  localmente, sem nova conferência remota. Merge não comprova aceite visual ou
  aceite do usuário. Um GDD antigo não é apresentado como a versão atual.
- Registro de arquivo na galeria, PR aberto ou aprovação de revisão isolada não
  bastam para entrar no histórico. A busca não lê os blobs de entrega como texto.

## Limites explícitos

- Consulta literal sem regex, de 2 a 160 caracteres e até 12 termos; os termos
  precisam aparecer na mesma linha. Uma referência por fonte, até 20 resultados,
  com trechos de até 400 caracteres. Documentos vêm antes das entregas recentes.
- Até 128 KiB por documento ou política, UTF-8, formatos `.md`, `.txt`, `.yaml`,
  `.yml` e `.json`. Arquivos binários, especiais e grandes ficam indisponíveis.
- Até 100 registros recentes de conclusão, 64 mil caracteres por pacote ou
  evidência, orçamento agregado de 2 MiB e tempo SQL limitado. A lista não é um
  inventário completo de todo o histórico.
- O histórico exige Python 3.11+ com as APIs SQLite `deserialize` e `setlimit`.
  Em runtimes sem elas, documentos continuam pesquisáveis e histórico aparece
  indisponível; não há fallback para abrir um caminho SQLite inseguro.
- O snapshot do banco tem limite de 32 MiB. Arquivos da galeria ocupam o mesmo
  banco e contam nesse tamanho, mesmo sem serem pesquisados. Quando o limite é
  excedido, **o histórico não é pesquisado**; os documentos continuam disponíveis.
- Banco com WAL/journal ativo ou formato WAL não é consultado. Mudança da fonte
  durante a leitura descarta a projeção. Uma única consulta pode manter snapshot
  em memória por processo; chamadas concorrentes precisam tentar novamente.

## Proteções

Apenas o PC pode consultar o conteúdo; pareamento móvel não amplia esse acesso.
O projeto é sempre explícito e deve estar registrado, ativo e ter política válida.
Um projeto sem repositório configurado pode pesquisar seus documentos canônicos;
nesse caso o histórico fica explicitamente indisponível, sem inferir um repositório.
Mesmo dois checkouts do mesmo repositório não compartilham diário de tarefas.

Não são aceitos caminhos absolutos, travessia, links simbólicos, junctions,
arquivos de credenciais, configurações privadas ou diretórios gerados. A exceção
para diretórios ocultos é estreita: um documento textual diretamente em `.office`
explicitamente configurado, como `.office/REGRAS.md`; configurações, segredos e
subdiretórios não entram nessa exceção. Uma fonte excluída aparece com motivo
genérico, sem revelar seu caminho privado.

O leitor confere componentes e identidade dos arquivos e usa descritores sem
seguir links quando a plataforma suporta. SQLite recebe uma cópia limitada dos
bytes desse descritor em memória, nunca o caminho do banco. Consultas SQL não
podem gravar, anexar bancos, executar funções arbitrárias ou criar temporários
em disco. Não há índice persistido, alteração de tabelas, manutenção automática
ou gravação de consultas.

Texto com padrões conhecidos de credenciais ou chaves privadas é excluído antes
da extração dos trechos. Essa proteção é conservadora e pode produzir falsos
positivos; ela não identifica todo segredo possível em texto livre. Conteúdo
é apresentado como texto, sem executar HTML, Markdown, links do documento ou
instruções encontradas nele.
