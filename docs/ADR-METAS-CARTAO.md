# Metas por cartão no controlador

Status: aceito. Data: 2026-10-11.

O Kanban já controla tarefas, dependências, reservas e entregas. O GDD define os objetivos. Os consoles têm capacidades e contadores diferentes; não existe um teto comum de tokens faturáveis nem uma função de meta nativa equivalente em todos eles.

Decisão: uma meta do escritório é um snapshot verificável do cartão e de seu objetivo do GDD, carregado no despacho existente. Cada tentativa tem recibo próprio, tempo controlado pelo host e orçamento de tokens observados no ledger já usado pelo Placar. Não cria outra fila, funcionário, loop de modelo ou reserva; não depende do comando `/goal` de um console. Instalações antigas ficam desativadas até habilitação explícita.

Alternativas: depender de metas nativas de um console impediria paridade e controle pelo host. Criar uma segunda fila duplicaria o Kanban. Estimar tokens por caracteres não comprovaria consumo. A solução comum preserva os adapters e aceita que contadores tardios ou ausentes impedem um teto financeiro rígido.

Consequências: lacuna de vínculo ao GDD bloqueia a implementação. Uma subtarefa de classificação criada e registrada pelo host pode investigar esse vínculo sem presumir um objetivo numerado: usa as seções canônicas com hash, preserva seu escopo/aceite e exige correspondência integral com o recibo de criação. Não implementa nem encerra o pai. Orçamento atingido interrompe somente a árvore do console lançado e mantém trabalho não entregue como bloqueado. Mudanças de limites exigem ciclo e tarefas parados. Revisão independente mantém seus gates e orçamento próprio; não faz parte da janela do agente autor. Registros antigos não são retomados nem recebem metas retroativas. PR aberto significa revisão, e somente a conclusão registrada pelo controle existente permite projetar a meta como entregue.

Validação: testes de vínculo/hashes, consumo ausente e isolado, watchdog com processo simulado real, despacho até revisão e bloqueio por orçamento, formulário, edição concorrente e regressões dos providers na CI.
