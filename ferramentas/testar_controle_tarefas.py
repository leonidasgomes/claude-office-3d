from contextlib import closing
import concurrent.futures
import sqlite3
import threading
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from controle_tarefas import Controle, ocupar_worktree


class Reservas(unittest.TestCase):
    def test_medicao_idempotente_e_intervalo_validado(self):
        with tempfile.TemporaryDirectory() as tmp:
            c=Controle(Path(tmp)/'tarefas.db')
            token=c.reservar('owner/repo','42','Dev','codex',{'objetivo':'x','aceite':'y',
                'executor':{'console':'codex','modelo':'modelo-configurado','execucao':'cloud'}},True)
            with self.assertRaises(ValueError): c.iniciar_execucao(token)
            c.transicao(token,'executando'); ident=c.iniciar_execucao(token)
            with self.assertRaisesRegex(ValueError,'sem retorno'): c.iniciar_execucao(token)
            for codigo,duracao in ((True,1),(0,float('nan')),(0,-1),(0,None)):
                with self.assertRaises(ValueError): c.terminar_execucao(ident,codigo,duracao)
            c.terminar_execucao(ident,0,2.5); c.terminar_execucao(ident,0,2.5)
            with self.assertRaisesRegex(ValueError,'outro retorno'): c.terminar_execucao(ident,1,2.5)
            with closing(sqlite3.connect(c.banco)) as db:
                linha=db.execute('SELECT console,modelo,origem_modelo,execucao,duracao_seg,codigo FROM execucao_tarefa').fetchone()
                self.assertEqual(linha,('codex','modelo-configurado','configurado','cloud',2.5,0))
                self.assertEqual(db.execute('SELECT count(*) FROM execucao_tarefa').fetchone()[0],1)

    def test_sem_retorno_nao_inventa_intervalo_nem_permite_nova_tentativa(self):
        with tempfile.TemporaryDirectory() as tmp:
            c=Controle(Path(tmp)/'tarefas.db')
            token=c.reservar('owner/repo','42','Dev','claude',{'objetivo':'x','aceite':'y'},True)
            c.transicao(token,'executando'); c.iniciar_execucao(token)
            c.transicao(token,'bloqueado'); c.transicao(token,'executando')
            with self.assertRaisesRegex(ValueError,'sem retorno'): c.iniciar_execucao(token)
            with closing(sqlite3.connect(c.banco)) as db:
                self.assertEqual(db.execute('SELECT fim,duracao_seg,codigo FROM execucao_tarefa').fetchone(),(None,None,None))

    def test_worktree_exclusivo_entre_cartoes_e_libera_no_final(self):
        from contextlib import closing
        with tempfile.TemporaryDirectory() as tmp:
            banco=Path(tmp)/'execucoes.db'; trabalho=Path(tmp)/'checkout'
            entrou=threading.Event(); liberar=threading.Event()
            def dono():
                with ocupar_worktree(banco,trabalho):
                    entrou.set(); self.assertTrue(liberar.wait(5))
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                futuro=pool.submit(dono); self.assertTrue(entrou.wait(5))
                try:
                    with self.assertRaisesRegex(ValueError,'já ocupado'):
                        with ocupar_worktree(banco,trabalho): self.fail('Segundo executor entrou')
                    with ocupar_worktree(banco,Path(tmp)/'outro-checkout'): pass
                finally: liberar.set()
                futuro.result()
            with ocupar_worktree(banco,trabalho): pass
            with closing(sqlite3.connect(banco)) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM worktree_ocupado').fetchone()[0],0)

    def test_trava_antiga_nao_e_roubada_por_prazo_ou_pid(self):
        from contextlib import closing
        import os
        with tempfile.TemporaryDirectory() as tmp:
            banco=Path(tmp)/'execucoes.db'; trabalho=Path(tmp)/'checkout'
            with ocupar_worktree(banco,trabalho): pass
            with closing(sqlite3.connect(banco)) as db,db:
                db.execute('INSERT INTO worktree_ocupado VALUES (?,?,?,?)',
                           (os.path.normcase(str(trabalho.resolve())),'anterior',999999999,1))
            with self.assertRaisesRegex(ValueError,'concilie'):
                with ocupar_worktree(banco,trabalho): self.fail('Trava anterior foi roubada')

    def test_excecao_sem_prova_de_termino_mantem_ocupacao(self):
        with tempfile.TemporaryDirectory() as tmp:
            banco=Path(tmp)/'execucoes.db'; trabalho=Path(tmp)/'checkout'
            with self.assertRaises(RuntimeError):
                with ocupar_worktree(banco,trabalho): raise RuntimeError('Controle perdido')
            with self.assertRaisesRegex(ValueError,'concilie'):
                with ocupar_worktree(banco,trabalho): self.fail('Execução incerta liberada')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.controle = Controle(Path(self.tmp.name) / "tarefas.db")

    def reservar(self, projeto="repo"):
        return self.controle.reservar(projeto, "42", "Dev", "codex",
                                      {"objetivo": "Corrigir", "aceite": ["Teste passa"]}, True)

    def test_concorrencia_so_um_dono(self):
        def tentar(_):
            try:
                return self.reservar()
            except ValueError:
                return None
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            resultados = list(pool.map(tentar, range(4)))
        self.assertEqual(sum(x is not None for x in resultados), 1)

    def test_sessao_e_retomada_persistentes(self):
        token = self.reservar()
        self.controle.transicao(token, "executando", "native-id")
        novo = Controle(self.controle.banco)
        self.assertEqual(novo.listar("repo")[0]["sessao"], "native-id")
        with self.assertRaises(ValueError):
            novo.transicao(token, "bloqueado", "outro-id")
        novo.transicao(token, "revisao")
        novo.transicao(token, "concluido")
        self.assertNotEqual(self.reservar(), token)

    def test_vinculo_nativo_imutavel_e_restrito_ao_console(self):
        token=self.reservar()
        with self.assertRaises(ValueError): self.controle.vincular_sessao(token,'codex','sessao-1')
        self.controle.transicao(token,'executando')
        for sessao in ('', 'sessao com espaço', 'x'*257):
            with self.assertRaises(ValueError): self.controle.vincular_sessao(token,'codex',sessao)
        with self.assertRaises(ValueError): self.controle.vincular_sessao(token,'gemini','sessao-1')
        self.controle.vincular_sessao(token,'codex','sessao-1')
        novo=Controle(self.controle.banco)
        novo.vincular_sessao(token,'codex','sessao-1')
        with self.assertRaises(ValueError): novo.vincular_sessao(token,'codex','sessao-2')
        self.assertEqual(novo.listar('repo')[0]['sessao'],'sessao-1')
        self.assertEqual(novo.listar('repo')[0]['estado'],'executando')

    def test_projetos_e_tokens_isolados(self):
        a, b = self.reservar("a"), self.reservar("b")
        self.assertNotEqual(a, b)
        self.assertEqual(len(self.controle.listar("a")), 1)
        with self.assertRaises(ValueError):
            self.controle.transicao("falso", "executando")

    def test_rede_e_aceite_obrigatorios(self):
        with self.assertRaises(ValueError):
            self.controle.reservar("a", "1", "Dev", "codex", {"objetivo": "x", "aceite": "y"})
        with self.assertRaises(ValueError):
            self.controle.reservar("a", "1", "Dev", "codex", {"objetivo": "x"}, True)


if __name__ == "__main__":
    unittest.main()
