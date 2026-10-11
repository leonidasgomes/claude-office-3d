"""Ponte local: controlador hospeda consultas e lotes, sem Codex dentro de Codex."""
import argparse
from contextlib import redirect_stdout
import io,json,os,re,subprocess,sys,time,uuid
from pathlib import Path

RAIZ=Path(__file__).resolve().parent
FILA=RAIZ/'dados'/'controlador'


def bloquear_instancia():
    """Lock do SO é liberado ao encerrar; não exclui pedidos incertos."""
    arquivo=FILA/'servidor.lock'
    if arquivo.is_symlink():raise ValueError('Lock inválido')
    lock=arquivo.open('a+b')
    lock.seek(0);lock.write(b'0');lock.flush();lock.seek(0)
    try:
        if sys.platform=='win32':
            import msvcrt
            msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError:
        lock.close();raise ValueError('Controlador já iniciado')
    return lock


def atomico(arq,dados):
    tmp=arq.with_suffix('.tmp')
    if arq.is_symlink() or tmp.is_symlink():raise ValueError('Arquivo inválido')
    tmp.write_text(json.dumps(dados,ensure_ascii=False),encoding='utf-8');tmp.replace(arq)


def criar_worktrees(projeto,dados):
    """Git no host; somente branches novos e caminhos gerados pelo controlador."""
    if not isinstance(dados,dict) or set(dados)!={'base','cartoes'}:
        raise ValueError('Informe base remota e cartoes')
    base=dados['base'];numeros=dados['cartoes']
    if (not isinstance(base,str) or not re.fullmatch(r'origin/[A-Za-z0-9_./-]+',base)
        or not isinstance(numeros,list) or not 1<=len(numeros)<=2
        or any(type(n) is not int or n<1 for n in numeros) or len(set(numeros))!=len(numeros)):
        raise ValueError('Base exige origin/branch; até dois cartões distintos')
    def git(*args):
        env=os.environ.copy()
        if args[:2]==('worktree','add'):env['GIT_LFS_SKIP_SMUDGE']='1'
        p=subprocess.run(['git','-C',str(projeto),*args],capture_output=True,text=True,env=env,
                         encoding='utf-8',errors='replace',timeout=120)
        if p.returncode:raise ValueError('Git: '+p.stderr.strip()[-2000:])
        return p.stdout.strip()
    git('check-ref-format','refs/heads/'+base[len('origin/'):])
    if Path(git('rev-parse','--show-toplevel')).resolve()!=projeto.resolve():
        raise ValueError('Projeto deve ser a raiz canônica do repositório')
    pasta=RAIZ.parent/'worktrees'
    if pasta.is_symlink() or pasta.resolve().is_relative_to(projeto.resolve()):
        raise ValueError('Pasta worktrees inválida ou dentro do checkout principal')
    from gestao_cli import preparar,conferir_disponibilidade,pasta_dados
    from gestao_projeto import carregar
    from kanban_gestao import Kanban
    cfg=carregar(projeto);k=Kanban(cfg,pasta_dados(projeto)/'kanban.json')
    quadro={c['numero']:c for c in k.cartoes(ao_vivo=True)}
    for anterior in (RAIZ/'dados'/'worktrees').glob('*.json'):
        r=json.loads(anterior.read_text(encoding='utf-8'))
        if r.get('estado')=='cancelado_antes_despacho' and r.get('conciliacao'):continue
        if r.get('projeto')==str(projeto) and set(numeros).intersection(
            i['cartao'] for i in r['plano']['cartoes']):
            raise ValueError('Criação anterior exige conciliação; não repetir. Confira '+str(anterior))
    ident=uuid.uuid4().hex;itens=[]
    for numero in numeros:
        cartao=quadro.get(numero)
        if not cartao:raise ValueError('Cartão não está no Kanban do projeto')
        atual,*_=preparar(projeto,numero,cartao['equipe'],kanban=k)
        if atual!=cfg:raise ValueError('Política mudou durante preparação')
        caminho=(pasta/(projeto.name+'-'+str(numero)+'-'+ident)).resolve()
        if not caminho.is_relative_to(pasta.resolve()) or caminho.exists():
            raise ValueError('Destino existente ou inválido; não reutilizar')
        conferir_disponibilidade(projeto,cfg,numero,caminho)
        itens.append({'cartao':numero,'worktree':str(caminho),
                      'branch':'work/office-'+str(numero)+'-'+ident})
    # Confirma a ref exata no remoto; fetch não muda HEAD nem checkout principal.
    remoto='refs/heads/'+base[len('origin/'):]
    linhas=git('ls-remote','--exit-code','--heads','origin',remoto).splitlines()
    if len(linhas)!=1 or linhas[0].split()[1]!=remoto:raise ValueError('Base remota não confirmada')
    sha=linhas[0].split()[0]
    git('fetch','--no-tags','origin',remoto)
    if git('rev-parse','FETCH_HEAD^{commit}')!=sha:raise ValueError('Base mudou durante fetch; confira novamente')
    if carregar(projeto)!=cfg:raise ValueError('Política mudou antes da criação')
    pasta.mkdir(exist_ok=True)
    recibo=RAIZ/'dados'/'worktrees'/(ident+'.json');recibo.parent.mkdir(parents=True,exist_ok=True)
    registro={'projeto':str(projeto),'base':base,'sha':sha,'estado':'criando','criados':[],
              'plano':{'paralelismo':1,'cartoes':[{'cartao':i['cartao'],'worktree':i['worktree']} for i in itens]}}
    atomico(recibo,registro)
    try:
        for item in itens:
            git('worktree','add','-b',item['branch'],item['worktree'],sha)
            registro['criados'].append(item);atomico(recibo,registro)
        registro['estado']='criado';atomico(recibo,registro)
    except Exception as exc:
        registro['estado']='incerto';registro['erro']=str(exc);atomico(recibo,registro)
        raise ValueError('Criação interrompida; não repetir nem limpar. Confira '+str(recibo)+': '+str(exc)) from exc
    return {**registro,'recibo':str(recibo)}


def executar_pedido(pedido,projetos,consulta=None,lote=None):
    from funcionarios import id_projeto
    from gestao_projeto import carregar
    if not isinstance(pedido,dict) or set(pedido)!={'projeto_id','acao','dados'}:
        raise ValueError('Pedido inválido')
    projeto=next((Path(p).resolve() for p in projetos if id_projeto(p)==pedido['projeto_id']),None)
    if projeto is None or not carregar(projeto)['ativo']:raise ValueError('Projeto não configurado/ativo')
    dados=pedido['dados'];acao=pedido['acao']
    if acao=='publicar':
        from publicacao_host import publicar
        return publicar(projeto,dados)
    if acao=='ciclo':
        if dados!={}:raise ValueError('Ciclo usa somente a política aprovada do projeto')
        from ciclo_gdd import iniciar
        return iniciar(projeto)
    if acao=='worktrees':return criar_worktrees(projeto,dados)
    if acao=='diretor':
        if not isinstance(dados,str) or not dados.strip() or len(dados)>128000:raise ValueError('Consulta inválida')
        if consulta is not None:return consulta(projeto,dados)
        import console_provider
        from gestao_projeto import executor,contexto
        from providers_console import selecionar
        cfg=carregar(projeto);rota=executor(cfg,papel='diretor');provider,exe=selecionar(rota['console'])
        texto=contexto(projeto,cfg,'diretor')+'\n\n'+dados
        saida=io.StringIO()
        with redirect_stdout(saida):
            codigo=console_provider.executar(provider,exe,projeto,'Diretor',prompt=texto,modelo=rota['modelo'],
                **({'sandbox':rota.get('sandbox','read-only')} if provider.nome=='codex' else {}))
        if codigo:raise ValueError('Diretor falhou; código '+str(codigo)+'; '+saida.getvalue()[-2000:])
        return {'codigo':codigo,'saida':saida.getvalue()}
    if acao=='lote':
        if not isinstance(dados,dict) or set(dados)!={'plano','executar'} or type(dados['executar']) is not bool:
            raise ValueError('Lote inválido')
        plano=dados['plano']
        if (not isinstance(plano,dict) or not isinstance(plano.get('cartoes'),list)
            or not 1<=len(plano['cartoes'])<=2 or type(plano.get('paralelismo',1)) is not int
            or plano.get('paralelismo',1)!=1):
            raise ValueError('Controlador permite até dois cartões, em sequência')
        worktrees=(RAIZ.parent/'worktrees').resolve()
        for item in plano['cartoes']:
            if not isinstance(item,dict) or not isinstance(item.get('worktree'),str):raise ValueError('Worktree inválido')
            p=Path(item['worktree']).resolve()
            if not p.is_relative_to(worktrees) or p==worktrees:raise ValueError('Worktree fora da pasta autorizada')
        if lote is not None:return lote(projeto,plano,dados['executar'])
        from gestao_cli import preparar_lote,executar_lote
        return (executar_lote if dados['executar'] else preparar_lote)(projeto,plano)
    raise ValueError('Operação não permitida')


def servir():
    from configuracao import normalizar
    cfg=normalizar(json.loads((RAIZ/'config.json').read_text(encoding='utf-8-sig')))
    projetos=cfg['projetos'];FILA.mkdir(parents=True,exist_ok=True)
    lock=bloquear_instancia()
    # Um arquivo já reivindicado não é repetido após crash/reinício.
    print('Controlador pronto',flush=True)
    while True:
        atomico(FILA/'servidor.json',{'pid':os.getpid(),'atualizado':time.time()})
        for arq in FILA.glob('*.pedido.json'):
            ident=arq.name.split('.')[0]
            if len(ident)!=32 or any(c not in '0123456789abcdef' for c in ident) or arq.is_symlink():continue
            ativo=FILA/(ident+'.processando.json')
            try:arq.rename(ativo)
            except OSError:continue
            try:
                if ativo.stat().st_size>256000:raise ValueError('Pedido grande demais')
                r=executar_pedido(json.loads(ativo.read_text(encoding='utf-8')),projetos)
                resposta={'ok':True,'resultado':r}
            except Exception as exc:
                resposta={'ok':False,'erro':str(exc)}
                print('Erro:',str(exc),file=sys.stderr,flush=True)
            atomico(FILA/(ident+'.resposta.json'),resposta)
            print('Pedido encerrado:',ident,'ok:',resposta['ok'],flush=True)
        time.sleep(1)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--servir',action='store_true')
    p.add_argument('--projeto',type=Path)
    p.add_argument('--acao',choices=['diretor','worktrees','lote','ciclo','publicar'])
    p.add_argument('--arquivo',type=Path,help='prompt do diretor ou plano JSON de lote')
    p.add_argument('--executar',action='store_true',help='lote: efetivar pelo controlador comum')
    args=p.parse_args(argv)
    if args.servir:servir();return 0
    if not args.projeto or not args.acao or not args.arquivo:p.error('Informe projeto, ação e arquivo')
    if args.acao!='lote' and args.executar:p.error('--executar é exclusivo de lote')
    from funcionarios import id_projeto
    if args.arquivo.stat().st_size>128000:raise ValueError('Arquivo grande demais')
    texto=args.arquivo.read_text(encoding='utf-8-sig')
    dados=texto if args.acao=='diretor' else (json.loads(texto) if args.acao in ('worktrees','ciclo','publicar')
        else {'plano':json.loads(texto),'executar':args.executar})
    FILA.mkdir(parents=True,exist_ok=True);ident=uuid.uuid4().hex
    try:
        vivo=json.loads((FILA/'servidor.json').read_text(encoding='utf-8'))
        if time.time()-vivo['atualizado']>15:raise ValueError('Controlador indisponível ou ocupado; não enfileirar novamente')
    except (OSError,KeyError,ValueError) as exc:
        print('Inicie o controlador local pelo launcher: '+str(exc),file=sys.stderr);return 2
    atomico(FILA/(ident+'.pedido.json'),{'projeto_id':id_projeto(args.projeto),'acao':args.acao,'dados':dados})
    print('Pedido enviado ao controlador:',ident,flush=True)
    resposta=FILA/(ident+'.resposta.json')
    for _ in range(3600):
        if resposta.is_file():
            d=json.loads(resposta.read_text(encoding='utf-8'));print(json.dumps(d,ensure_ascii=False,indent=2));return 0 if d['ok'] else 1
        time.sleep(1)
    print('Consulta continua pendente. Não repetir; confira '+ident,file=sys.stderr);return 2

if __name__ == '__main__':sys.exit(main())

