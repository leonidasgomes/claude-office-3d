"""Assistente de política multi-console. Nunca instala CLIs, autentica ou altera GitHub."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import re
import shutil
import sys

from gestao_projeto import validar
from providers_console import PROVIDERS, comando_nativo
from skills_compartilhados import REGRAS_PASTA


def detectar():
    saida=[]
    for nome, provider in PROVIDERS.items():
        caminho=shutil.which(nome); disponivel=False
        if caminho:
            try: comando_nativo(caminho,nome); disponivel=True
            except ValueError: pass
        saida.append({'console':nome,'instalado':disponivel,'capacidades':asdict(provider.capacidades),
                      'autenticacao':'não verificada'})
    return saida


def preparar(projeto,dados):
    raiz=Path(projeto).resolve()
    if not raiz.is_dir(): raise ValueError('Pasta do projeto não existe')
    cfg=validar(dados)
    pasta=(raiz/'.office').resolve()
    if not pasta.is_relative_to(raiz): raise ValueError('Pasta .office fora do projeto')
    destino=pasta/'projeto.json'
    texto=json.dumps(cfg,ensure_ascii=False,indent=2)+'\n'
    existente=destino.exists()
    if existente:
        atual=validar(json.loads(destino.read_text(encoding='utf-8-sig')))
        if atual != cfg: raise ValueError('Política existente preservada; edite/revise esse arquivo antes de migrar')
    for fonte in cfg['fontes'].values():
        if not (raiz/fonte).resolve().is_relative_to(raiz): raise ValueError('Fonte fora do projeto')
    if cfg['ativo']:
        if not cfg['equipes']: raise ValueError('Gestão ativa exige pelo menos uma equipe')
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',cfg['kanban']['repo']) or cfg['kanban']['numero']<1 or not cfg['kanban']['owner']:
            raise ValueError('Informe repositório e projeto GitHub do Kanban')
    arquivos={} if existente else {'.office/projeto.json':texto}
    regras=raiz/cfg['fontes']['regras']
    if not regras.is_file():
        if existente: raise ValueError('Fonte de regras ausente na política existente; restaure/revise a fonte antes de reparar as entradas')
        if cfg['fontes']['regras'] != '.office/REGRAS.md': raise ValueError('Fonte de regras não existe; escolha arquivo existente ou .office/REGRAS.md')
        arquivos['.office/REGRAS.md']=('# Regras do projeto\n\nO usuário define objetivos, escopo e orçamento.\n'
            'A política de execução está em .office/projeto.json.\n'
            'O Kanban GitHub define tarefas, equipe, dependências e critérios de aceite.\n'
            'Cada tarefa exige branch/worktree próprio e revisão antes da conclusão.\n'
            'Agentes não fazem merge nem alteram política por conta própria.\n'
            'Consoles consultam esta fonte comum; skills são referenciados, sem duplicação.\n')
    for nome in ('CLAUDE.md','AGENTS.md','GEMINI.md'):
        if not (raiz/nome).exists():
            arquivos[nome]=('# Instruções compartilhadas\n\nLeia '+cfg['fontes']['regras']+
                ' como fonte única de regras deste projeto e .office/projeto.json para a política do escritório.\n'
                'Os skills compartilhados estão em '+cfg['fontes']['skills']+'. Consulte apenas os relevantes para a tarefa.\n'
                +REGRAS_PASTA+'\n'
                'O cartão do Kanban fornece equipe, escopo e critérios de aceite.\n')
            fonte=Path(cfg['fontes']['regras']).as_posix()
            if nome in ('CLAUDE.md','GEMINI.md') and re.fullmatch(r'[A-Za-z0-9_./-]+',fonte):
                console='Claude Code' if nome=='CLAUDE.md' else 'Gemini CLI'
                arquivos[nome]+='\nImportação da fonte oficial pelo '+console+':\n\n@./'+fonte+'\n'
    # Metadados SQLite locais ficam fora do versionamento; política/regras são compartilháveis.
    ignore=pasta/'.gitignore'
    if not ignore.exists(): arquivos['.office/.gitignore']='funcionarios.db\nfuncionarios.db-*\nhistorico-politica/\npolitica.edicao.lock\npolitica-*.tmp\nperfis-nativos.lock\n'
    return {'politica':cfg,'arquivos':arquivos,'existente':existente}


def aplicar(projeto,plano):
    # Revalida inclusive corrida com configuração criada após o preview.
    atual=preparar(projeto,plano['politica'])
    if atual != plano: raise ValueError('Projeto mudou desde a preparação; refaça o plano')
    raiz=Path(projeto).resolve()
    escritos=[]
    # A política vem por último: não ativa um projeto antes das regras estarem gravadas.
    for nome in sorted(atual['arquivos'],key=lambda n:n.endswith('projeto.json')):
        alvo=raiz/nome; alvo.parent.mkdir(parents=True,exist_ok=True)
        with alvo.open('x',encoding='utf-8') as fluxo: fluxo.write(atual['arquivos'][nome])
        escritos.append(nome)
    return escritos


def guiado(projeto,entrada=input):
    def ler(texto,padrao=''):
        return entrada(f'{texto} [{padrao}]: ').strip() or padrao
    disponiveis=[x['console'] for x in detectar() if x['instalado']]
    print('Consoles disponíveis: '+(', '.join(disponiveis) or 'nenhum; instale o CLI oficial antes de executar'))
    def escolher(titulo,padrao):
        console=ler(titulo+' console (claude/codex/opencode/gemini)',padrao)
        if console not in PROVIDERS: raise ValueError('Console desconhecido')
        e={'console':console,'modelo':ler(titulo+' modelo (vazio usa padrão)'),'execucao':'cloud'}
        if console=='opencode':
            cloud=ler(titulo+' fornecedor real do modelo (vazio se não informado; obrigatório na revisão cruzada)')
            if cloud:e['cloud']=cloud
        return e
    raiz=Path(projeto)
    # Sugestão para instalação nova; a escolha explícita e políticas existentes
    # continuam preservadas. Detectar o CLI não comprova login ou disponibilidade.
    padrao_ceo='codex' if 'codex' in disponiveis else (disponiveis[0] if disponiveis else 'codex')
    ceo=escolher('CEO',padrao_ceo)
    diretor=escolher('Diretor',ceo['console'])
    nomes=ler('Equipes por especialidade, separadas por vírgula','Dev, QA').split(',')
    equipes=[]
    for nome in nomes:
        nome=nome.strip()
        equipes.append({'nome':nome,'especialidade':ler('Especialidade de '+nome,nome),'executor':escolher(nome,diretor['console'])})
    repo=ler('Repositório GitHub (owner/repo)')
    owner=ler('Dono do projeto Kanban',repo.split('/')[0])
    numero=int(ler('Número do projeto Kanban','1'))
    tipo=ler('Tipo do dono (users/orgs)','users')
    revisao={'ativo':False}
    if ler('Revisão cruzada de clouds distintas (s/n)','s').lower() in ('s','sim'):
        revisao={'ativo':True,'clouds_distintas':2,'separar_autor':True,'revisores':[]}
        print('Configure três clouds para garantir dois revisores distintos da cloud do autor.')
        for padrao in ('claude','codex','gemini'):
            revisao['revisores'].append({'nome':'QA '+padrao,'executor':escolher('Revisor '+padrao,padrao)})
    regras=next((p for p in ('CLAUDE.md','AGENTS.md') if (raiz/p).is_file()),'.office/REGRAS.md')
    return validar({'ativo':True,'ceo':ceo,'diretor':diretor,'equipes':equipes,
        'fontes':{'regras':ler('Fonte única de regras',regras)},
        'kanban':{'repo':repo,'owner':owner,'numero':numero,'tipo_owner':tipo},'revisao':revisao})


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--projeto',required=True,type=Path)
    p.add_argument('--politica',type=Path,help='JSON revisado; sem ele abre o assistente')
    p.add_argument('--aplicar',action='store_true',help='grava apenas arquivos novos após preparar')
    args=p.parse_args(argv)
    try:
        dados=json.loads(args.politica.read_text(encoding='utf-8-sig')) if args.politica else guiado(args.projeto)
        plano=preparar(args.projeto,dados)
        print(json.dumps({'consoles':detectar(),'plano':plano},ensure_ascii=False,indent=2))
        if args.aplicar: print('Arquivos criados: '+', '.join(aplicar(args.projeto,plano)))
        else: print('Prévia: nenhum arquivo gravado. Use --aplicar para criar esta configuração.')
        return 0
    except (ValueError,OSError,EOFError,KeyboardInterrupt) as exc:
        print('Configuração não concluída: '+str(exc),file=sys.stderr); return 2


if __name__=='__main__': sys.exit(main())
