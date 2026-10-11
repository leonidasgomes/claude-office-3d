from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from memoria_entregas import recuperar
from gestao_painel import checkpoint


class Memoria(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.b=Path(self.tmp.name)/'tarefas.db'
        self.pacote={'meta':{'cartao':2,'gdd':{'sha256':'d'*64,'numero':1}}}
        self.ev={'repo':'o/r','cartao':1,'pr':3,'head':'a'*40,'merge_commit':'b'*40,
            'merged_at':'2026-10-11T12:00:00Z','checks':{'gates':[{'estado':'success'}]}}
        self.antigo={'meta':{'objetivo':'Entrega testada','gdd':{'sha256':'d'*64,'numero':1}}}
        with closing(sqlite3.connect(self.b)) as db,db:
            db.execute('CREATE TABLE reserva (projeto TEXT,cartao TEXT,equipe TEXT,pacote TEXT,token TEXT,estado TEXT,atualizado REAL)')
            db.execute('CREATE TABLE conclusao (token TEXT,evidencia TEXT)')
            db.execute('INSERT INTO reserva VALUES (?,?,?,?,?,?,?)',('o/r','1','Dev',json.dumps(self.antigo),'segredo','concluido',1))
            db.execute('INSERT INTO conclusao VALUES (?,?)',('segredo',json.dumps(self.ev)))
    def mudar(self,ev=None,pacote=None,estado=None):
        with closing(sqlite3.connect(self.b)) as db,db:
            if ev is not None:db.execute('UPDATE conclusao SET evidencia=?',(json.dumps(ev),))
            if pacote is not None:db.execute('UPDATE reserva SET pacote=?',(json.dumps(pacote),))
            if estado is not None:db.execute('UPDATE reserva SET estado=?',(estado,))
    def test_memoria_so_merge_mesmo_projeto_objetivo_e_gdd(self):
        antes=self.b.read_bytes();refs=recuperar(self.b,'o/r',self.pacote)
        self.assertEqual(len(refs),1);self.assertEqual(refs[0]['objetivo'],'Entrega testada')
        self.assertEqual(self.b.read_bytes(),antes);self.assertNotIn('segredo',json.dumps(refs))
        self.assertEqual(recuperar(self.b,'outro/r',self.pacote),[])
        self.assertEqual(recuperar(self.b,'o/r',self.pacote,0),[])
        self.antigo['meta']['gdd']['sha256']='e'*64;self.mudar(pacote=self.antigo)
        self.assertEqual(recuperar(self.b,'o/r',self.pacote),[])
    def test_pr_aberto_sem_prova_e_gates_falhos_nao_viram_memoria(self):
        self.mudar(estado='revisao');self.assertEqual(recuperar(self.b,'o/r',self.pacote),[])
        self.mudar(estado='concluido');self.ev['checks']['gates'][0]['estado']='failure';self.mudar(ev=self.ev)
        self.assertEqual(recuperar(self.b,'o/r',self.pacote),[])
        self.ev['checks']['gates']=[None];self.mudar(ev=self.ev)
        self.assertEqual(recuperar(self.b,'o/r',self.pacote),[])
    def test_memoria_encontra_objetivo_depois_de_cem_outros(self):
        outro={'meta':{'gdd':{'sha256':'d'*64,'numero':2}}}
        with closing(sqlite3.connect(self.b)) as db,db:
            for n in range(100,201):
                db.execute('INSERT INTO reserva VALUES (?,?,?,?,?,?,?)',('o/r',str(n),'Dev',json.dumps(outro),str(n),'concluido',n))
                db.execute('INSERT INTO conclusao VALUES (?,?)',(str(n),json.dumps(self.ev)))
        self.assertEqual(recuperar(self.b,'o/r',self.pacote)[0]['cartao'],1)
    def test_memoria_sem_gate_e_checkpoint_de_outra_reserva(self):
        self.ev['checks']['gates']=[];self.mudar(ev=self.ev)
        self.assertEqual(recuperar(self.b,'o/r',self.pacote),[])
        with closing(sqlite3.connect(self.b)) as db,db:
            db.execute('CREATE TABLE entrega (token TEXT,pr INTEGER,sha TEXT,aprovado INTEGER)')
            db.execute('INSERT INTO entrega VALUES (?,?,?,?)',('segredo',3,'a'*40,1))
            cfg={'kanban':{'repo':'o/r'}}
            self.assertIsNone(checkpoint(db,cfg,1,{},None,'outro')['entrega'])
            self.assertEqual(checkpoint(db,cfg,1,{},None,'segredo')['entrega']['pr'],3)

    def test_json_valido_com_tipo_errado_nao_interrompe_despacho(self):
        for invalido in ([],42,{'meta':[]},{'meta':{'gdd':42}}):
            self.mudar(pacote=invalido)
            self.assertEqual(recuperar(self.b,'o/r',self.pacote),[])
        self.mudar(pacote=self.antigo)
        for invalido in ([],42,{**self.ev,'checks':[]}):
            self.mudar(ev=invalido)
            self.assertEqual(recuperar(self.b,'o/r',self.pacote),[])

    def test_entrada_invalida_tipos_sha_booleano_e_duplicacao(self):
        for pacote in ([],{'meta':{'gdd':42}},{'meta':{'gdd':{'sha256':123,'numero':1}}}):
            self.assertEqual(recuperar(self.b,'o/r',pacote),[])
        self.ev['cartao']=True;self.mudar(ev=self.ev)
        self.assertEqual(recuperar(self.b,'o/r',self.pacote),[])
        self.ev['cartao']=1;self.mudar(ev=self.ev)
        with closing(sqlite3.connect(self.b)) as db,db:
            db.execute('INSERT INTO conclusao VALUES (?,?)',('segredo',json.dumps(self.ev)))
        self.assertEqual(len(recuperar(self.b,'o/r',self.pacote)),1)

    def test_checkpoint_nao_expoe_worktree_tokens_nem_prompts(self):
        cfg={'kanban':{'repo':'o/r'}}
        with closing(sqlite3.connect(self.b)) as db,db:
            cp=checkpoint(db,cfg,1,{'contexto_execucao':{'branch':'feat/1','worktree':'D:/privado/segredo'}},None)
        self.assertEqual(cp['branch'],'feat/1');self.assertTrue(cp['worktree_vinculado'])
        self.assertFalse(cp['politica_compativel']);self.assertIn('conciliar',cp['acao'])
        self.assertNotIn('privado',json.dumps(cp));self.assertNotIn('segredo',json.dumps(cp))
        self.assertEqual(len(cp['evidencia_sha256']),64)

if __name__=='__main__':unittest.main()
