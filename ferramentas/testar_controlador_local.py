import sys,tempfile,unittest,subprocess,json
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import controlador_local as c
from funcionarios import id_projeto

class Controlador(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.raiz=Path(self.tmp.name);self.projeto=self.raiz/'projeto';self.projeto.mkdir()
        self.office=self.raiz/'office';self.office.mkdir()
        self.patch=patch.object(c,'RAIZ',self.office);self.patch.start();self.addCleanup(self.patch.stop)
        self.cfg=patch('gestao_projeto.carregar',return_value={'ativo':True});self.cfg.start();self.addCleanup(self.cfg.stop)
    def pedido(self,acao,dados):
        return {'projeto_id':id_projeto(self.projeto),'acao':acao,'dados':dados}
    def test_consulta_host_usa_projeto_canonico(self):
        chamados=[]
        resultado=c.executar_pedido(self.pedido('diretor','Classifique'),[str(self.projeto)],
            consulta=lambda p,d: chamados.append((p,d)) or {'codigo':0,'saida':'aceite'})
        self.assertEqual(chamados,[(self.projeto.resolve(),'Classifique')]);self.assertEqual(resultado['codigo'],0)
    def test_validacao_nao_executa_e_execucao_delega(self):
        plano={'paralelismo':1,'cartoes':[{'cartao':7,'worktree':str(self.raiz/'worktrees'/'novo')}]}
        for executar in (False,True):
            chamados=[]
            c.executar_pedido(self.pedido('lote',{'plano':plano,'executar':executar}),[str(self.projeto)],
                lote=lambda p,d,e:chamados.append(e))
            self.assertEqual(chamados,[executar])
    def test_recusa_projeto_operacao_e_worktree_fora(self):
        for pedido in (self.pedido('shell','qualquer'),{'projeto_id':'desconhecido','acao':'diretor','dados':'x'},
            self.pedido('lote',{'plano':{'cartoes':[{'cartao':1,'worktree':str(self.projeto)}]},'executar':True})):
            with self.assertRaises(ValueError):c.executar_pedido(pedido,[str(self.projeto)])
    def test_recusa_paralelismo_e_tres_cartoes(self):
        item={'cartao':1,'worktree':str(self.raiz/'worktrees'/'novo')}
        for plano in ({'cartoes':[item]*3},{'cartoes':[item],'paralelismo':2},{'cartoes':[item],'paralelismo':True}):
            with self.assertRaises(ValueError):c.executar_pedido(self.pedido('lote',{'plano':plano,'executar':True}),[str(self.projeto)])
    def test_erro_diretor_nao_faz_fallback(self):
        def falhar(*args):raise RuntimeError('diretor indisponível')
        with self.assertRaisesRegex(RuntimeError,'diretor indisponível'):
            c.executar_pedido(self.pedido('diretor','x'),[str(self.projeto)],consulta=falhar)
    def test_lock_impede_segundo_servidor(self):
        with patch.object(c,'FILA',self.raiz):
            lock=c.bloquear_instancia()
            try:
                with self.assertRaisesRegex(ValueError,'já iniciado'):c.bloquear_instancia()
            finally:lock.close()
    def test_sem_servidor_nao_cria_pedido(self):
        arquivo=self.raiz/'prompt.txt';arquivo.write_text('x',encoding='utf-8');fila=self.raiz/'fila'
        with patch.object(c,'FILA',fila):
            self.assertEqual(c.main(['--projeto',str(self.projeto),'--acao','diretor','--arquivo',str(arquivo)]),2)
        self.assertEqual(list(fila.glob('*.pedido.json')),[])

    def git(self,*args):
        return subprocess.run(['git',*map(str,args)],check=True,capture_output=True,text=True).stdout.strip()

    def ambiente_git(self):
        remoto=self.raiz/'remoto.git';self.git('init','--bare',remoto)
        self.git('init','-b','main',self.projeto)
        self.git('-C',self.projeto,'config','user.name','Teste')
        self.git('-C',self.projeto,'config','user.email','teste@example.com')
        (self.projeto/'arquivo.txt').write_text('base',encoding='utf-8')
        self.git('-C',self.projeto,'add','.');self.git('-C',self.projeto,'commit','-m','base')
        self.git('-C',self.projeto,'remote','add','origin',remoto)
        self.git('-C',self.projeto,'push','origin','main')

    def preparar_mocks(self):
        kanban=patch('kanban_gestao.Kanban');k=kanban.start();self.addCleanup(kanban.stop)
        k.return_value.cartoes.return_value=[{'numero':7,'equipe':'Dev'},{'numero':8,'equipe':'QA'}]
        preparar=patch('gestao_cli.preparar',return_value=({'ativo':True},None,None,None,{}))
        preparar.start();self.addCleanup(preparar.stop)
        disp=patch('gestao_cli.conferir_disponibilidade');d=disp.start();self.addCleanup(disp.stop)
        return d

    def test_cria_git_real_preserva_checkout_e_recusa_repeticao(self):
        self.ambiente_git();self.preparar_mocks()
        (self.projeto/'arquivo.txt').write_text('alteração do usuário',encoding='utf-8')
        pedido=self.pedido('worktrees',{'base':'origin/main','cartoes':[7,8]})
        r=c.executar_pedido(pedido,[str(self.projeto)])
        self.assertEqual(r['estado'],'criado');self.assertEqual(len(r['criados']),2)
        self.assertEqual((self.projeto/'arquivo.txt').read_text(encoding='utf-8'),'alteração do usuário')
        self.assertEqual(self.git('-C',self.projeto,'branch','--show-current'),'main')
        for item in r['criados']:
            self.assertEqual(self.git('-C',item['worktree'],'rev-parse','HEAD'),r['sha'])
            self.assertEqual(self.git('-C',item['worktree'],'branch','--show-current'),item['branch'])
        with self.assertRaisesRegex(ValueError,'Criação anterior'):
            c.executar_pedido(pedido,[str(self.projeto)])

    def test_reserva_bloqueada_impede_criacao(self):
        self.ambiente_git();d=self.preparar_mocks();d.side_effect=ValueError('Cartão já reservado')
        with self.assertRaisesRegex(ValueError,'já reservado'):
            c.criar_worktrees(self.projeto,{'base':'origin/main','cartoes':[7]})
        self.assertFalse((self.raiz/'worktrees').exists())

    def test_falha_parcial_deixa_recibo_sem_limpar(self):
        self.ambiente_git();self.preparar_mocks();original=c.subprocess.run
        def rodar(args,**kwargs):
            if 'worktree' in args:self.assertEqual(kwargs['env']['GIT_LFS_SKIP_SMUDGE'],'1')
            if 'worktree' in args and any('office-8-' in a for a in args):
                return subprocess.CompletedProcess(args,1,'','falha simulada')
            return original(args,**kwargs)
        with patch.object(c.subprocess,'run',side_effect=rodar),self.assertRaisesRegex(ValueError,'não repetir'):
            c.criar_worktrees(self.projeto,{'base':'origin/main','cartoes':[7,8]})
        recibos=list((self.office/'dados'/'worktrees').glob('*.json'))
        r=json.loads(recibos[0].read_text(encoding='utf-8'))
        self.assertEqual(r['estado'],'incerto');self.assertEqual(len(r['criados']),1)
        self.assertTrue(Path(r['criados'][0]['worktree']).exists())

    def test_rejeita_base_injetada_cartoes_invalidos_e_destino_interno(self):
        for base,cartoes in [('main',[7]),('origin/--x',[True]),('origin/main',[7,7]),
                             ('origin/main',[7,8,9]),('origin/main;echo',[7])]:
            with self.assertRaises(ValueError):c.criar_worktrees(self.projeto,{'base':base,'cartoes':cartoes})
        self.ambiente_git()
        with patch.object(c,'RAIZ',self.projeto/'office'),self.assertRaisesRegex(ValueError,'dentro do checkout'):
            c.criar_worktrees(self.projeto,{'base':'origin/main','cartoes':[7]})

if __name__=='__main__':unittest.main()
