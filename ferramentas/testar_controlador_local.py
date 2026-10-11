import sys,tempfile,unittest
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

if __name__=='__main__':unittest.main()
