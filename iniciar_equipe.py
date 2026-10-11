"""Inicia um CEO Codex interativo com tarefa de coordenação, sem console vazio."""
import argparse
import json
from pathlib import Path
import sys
from console_provider import executar
from gestao_projeto import carregar
from providers_console import selecionar


def tarefa(projeto, office, base, max_cartoes):
    if not base.strip() or base.startswith('-') or any(c.isspace() for c in base):
        raise ValueError('Informe a base Git do projeto, sem opções ou espaços')
    if type(max_cartoes) is not int or not 1 <= max_cartoes <= 2:
        raise ValueError('Limite de cartões deve estar entre 1 e 2')
    dados=json.dumps({'projeto':str(projeto), 'office':str(office), 'base':base,
                      'max_cartoes':max_cartoes},ensure_ascii=False)
    return '''Comece agora a trabalhar como CEO deste escritório, em português. Não espere outra mensagem.
A configuração abaixo é do usuário. Leia AGENTS.md e as regras/documentos referenciados, a política
.office/projeto.json e a passagem de turno. Coordene as equipes cadastradas, sem inventar funcionários.
Sua tarefa inicial é dividir e iniciar um lote limitado de trabalho REAL no Kanban GitHub do projeto.
Use o Python disponível e gestao_cli.py da pasta office, sempre com --projeto apontando à raiz canônica.
1. Consulte estado e planejar --max-cartoes 20. Mostre os cartões, equipes e bloqueios encontrados.
Não retome reserva existente/bloqueada/incerta automaticamente, nem trate uma sessão antiga como ativa.
2. Consulte o diretor configurado com controlador_local.py --projeto RAIZ --acao diretor --arquivo
arquivo_utf8 (contendo os candidatos e pedido de classificação/aceite, sem executar ferramentas).
Se a consulta falhar, pare e explique; não substitua silenciosamente o diretor.
Escolha até max_cartoes preparáveis, pela ordem de prioridade, preferindo equipes diferentes.
Não crie tarefas artificiais para ocupar mesas. Respeite dependências, recursos e escopo/aceite.
3. Salve JSON UTF-8 com {"base":base_configurada,"cartoes":[numeros_aprovados]} e envie ao host:
controlador_local.py --projeto RAIZ --acao worktrees --arquivo pedido_worktrees_utf8.
O host confirma a base remota e cria branches/worktrees novos. Não execute git worktree add no sandbox.
Use o plano retornado; se houver falha parcial, confira o recibo e pare, sem repetir/limpar/reutilizar.
Não altere arquivos do checkout principal, política, credenciais, hooks ou regras para permitir execução.
4. Gere um plano UTF-8 local com {"paralelismo":1,"cartoes":[{"cartao":numero,"worktree":caminho_absoluto}]}.
Valide pelo comando controlador_local.py --projeto RAIZ --acao lote --arquivo plano_utf8 (sem --executar). A divisão segue o campo Time do Kanban.
5. Delegue a execução pelo mesmo comando controlador_local.py --projeto RAIZ --acao lote --arquivo plano_utf8 --executar. O controlador usa o provider,
modelo e skills de cada equipe, registra sessões/eventos, reserva cartões e aplica os gates existentes.
CEO organiza, diretor acompanha a ordem/aceite e as equipes implementam. Não substitua a delegação
fazendo a implementação na raiz. Não lance clones nativos fora do controlador nem duplique tarefas.
Nunca execute console_provider.py ou gestao_cli.py lote diretamente dentro do sandbox do CEO: use controlador_local.py.
Não faça merge manual. Pare após este lote, se houver bloqueio, permissão pendente ou erro; mostre a causa
real e como resolver. Não finja que agentes trabalharam nem que testes passaram. Ao terminar,
mostre o resultado/PR de cada equipe e mantenha este console aberto para o usuário.
Se não houver cartão preparável, explique os bloqueios e proponha a próxima ação, sem consumir em loop.
Configuração: '''+dados


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--projeto',required=True,type=Path)
    p.add_argument('--base',required=True,help='base Git explícita do projeto')
    p.add_argument('--max-cartoes',type=int,default=1)
    p.add_argument('--verificar',action='store_true',help='mostra tarefa, sem iniciar modelo')
    args=p.parse_args(argv)
    try:
        projeto=args.projeto.resolve();office=Path(__file__).resolve().parent
        cfg=carregar(projeto)
        if not cfg['ativo'] or cfg['ceo']['console']!='codex' or cfg['ceo'].get('execucao','cloud')!='cloud':
            raise ValueError('Início de equipe exige projeto ativo e CEO Codex cloud')
        prompt=tarefa(projeto,office,args.base,args.max_cartoes)
        ciclo=cfg.get('ciclo',{})
        if ciclo.get('ativo'):
            if ciclo['base']!=args.base:raise ValueError('Base do launcher diverge da política do ciclo')
            prompt=('O controlador host coordena automaticamente as equipes pelo GDD e Kanban. '
                    'Não crie outro lote, não retome reservas e não duplique tarefas. '
                    'Consulte o estado em dados/gestao e no painel de gestão; explique bloqueios ao usuário. '
                    'O usuário pode conversar com você enquanto as equipes trabalham. Projeto: '+str(projeto))
        if args.verificar:
            print(prompt);return 0
        if ciclo.get('ativo'):
            import subprocess
            pedido=office/'dados'/'iniciar-ciclo.json';pedido.parent.mkdir(exist_ok=True)
            pedido.write_text('{}',encoding='utf-8')
            r=subprocess.run([sys.executable,str(office/'controlador_local.py'),'--projeto',str(projeto),
                              '--acao','ciclo','--arquivo',str(pedido)],timeout=30)
            if r.returncode:raise ValueError('Controlador não iniciou ciclo; confira recibos antes de repetir')
        provider,exe=selecionar('codex')
        worktrees=office.parent/'worktrees'
        worktrees.mkdir(exist_ok=True)
        print('CEO: iniciando coordenação do Kanban; equipes executam em worktrees. Limite:',args.max_cartoes,flush=True)
        return executar(provider,exe,projeto,'CEO',modelo=cfg['ceo']['modelo'],
                        sandbox='workspace-write',prompt_inicial=prompt,diretorios_escrita=[office,worktrees])
    except (OSError,ValueError) as exc:
        print('Equipe não iniciou: '+str(exc),file=sys.stderr);return 2

if __name__=='__main__':sys.exit(main())
