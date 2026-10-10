"""SQLite real e projeção pública; sem consoles, modelos ou GitHub."""
from contextlib import closing
from pathlib import Path
import json
import sqlite3
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from controle_tarefas import Controle
from gestao_painel import saude_tarefas


class Saude(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.banco=Path(self.tmp.name)/'tarefas.db'; Controle(self.banco)
        self.db=sqlite3.connect(self.banco); self.addCleanup(self.db.close)

    def reserva(self,cartao='42',repo='owner/a',estado='executando',token=None):
        token=token or 'segredo-'+repo+'-'+cartao
        self.db.execute('INSERT OR REPLACE INTO reserva VALUES (?,?,?,?,?,?,?,?,?)',
            (repo,cartao,token,'Dev','claude',estado,10,'sessao-secreta','{"objetivo":"prompt-secreto"}'))
        return token

    def medicao(self,token,inicio=1,fim=None,codigo=None,ident='tentativa'):
        self.db.execute('INSERT INTO execucao_tarefa VALUES (?,?,?,?,?,?,?,?,?,?)',
            (ident,token,'claude','configurado','configurado','cloud',inicio,fim,None if fim is None else fim-inicio,codigo))

    def test_antiga_sem_retorno_e_cancelada_requer_conferencia(self):
        token=self.reserva(estado='cancelado'); self.medicao(token)
        s=saude_tarefas(self.db,'owner/a')
        self.assertEqual(s['pendencias'][0]['sinais'],['sem_retorno'])
        self.assertEqual(s['contagens']['sem_retorno'],1)
        self.assertNotIn('segredo',json.dumps(s)); self.assertNotIn('prompt',json.dumps(s))

    def test_projeto_separado_mesmo_cartao_e_nova_reserva(self):
        antigo=self.reserva(); self.medicao(antigo,fim=2,codigo=1)
        self.reserva(token='novo',estado='reservado')
        outro=self.reserva(repo='owner/b',estado='bloqueado'); self.medicao(outro,ident='outro')
        self.assertEqual(saude_tarefas(self.db,'owner/a')['pendencias'],[])
        self.assertEqual(saude_tarefas(self.db,'owner/b')['pendencias'][0]['sinais'],['sem_retorno','bloqueada'])

    def test_ultima_tentativa_substitui_falha_anterior(self):
        token=self.reserva(estado='revisao')
        self.medicao(token,fim=2,codigo=1,ident='antiga')
        self.medicao(token,inicio=3,fim=4,codigo=0,ident='nova')
        self.assertEqual(saude_tarefas(self.db,'owner/a')['pendencias'],[])

    def test_bloqueio_e_falha_independentes_sem_medicao(self):
        token=self.reserva(estado='bloqueado'); self.medicao(token,fim=2,codigo=9)
        self.reserva('43')
        s=saude_tarefas(self.db,'owner/a')
        self.assertEqual(s['contagens'],{'bloqueada':1,'sem_retorno':0,'falha':1,'sem_medicao':1})

    def test_limite_exato_nao_confunde_cobertura(self):
        for n in range(200): self.reserva(str(n))
        self.assertFalse(saude_tarefas(self.db,'owner/a')['limitado'])
        self.reserva('201')
        s=saude_tarefas(self.db,'owner/a')
        self.assertTrue(s['limitado']); self.assertEqual(s['consultadas'],200)

    def test_esquema_antigo_e_leitura_sem_mutacao(self):
        self.reserva(); self.db.execute('DROP TABLE execucao_tarefa'); self.db.commit()
        antes=self.banco.read_bytes()
        with closing(sqlite3.connect(self.banco.resolve().as_uri()+'?mode=ro',uri=True)) as db:
            self.assertEqual(saude_tarefas(db,'owner/a')['contagens']['sem_medicao'],1)
        self.assertEqual(antes,self.banco.read_bytes())

    def test_medicao_inconsistente_nao_vira_estado_saudavel(self):
        token=self.reserva(); self.medicao(token,fim=2,codigo=None)
        with self.assertRaises(ValueError): saude_tarefas(self.db,'owner/a')

    def test_eventos_invalidos_nao_viram_atividade_valida(self):
        token=self.reserva();self.medicao(token)
        self.db.execute('CREATE TABLE atividade_execucao(execucao,controlador,pid_controlador,pid_console,ultimo_sinal,estado,codigo_console)')
        self.db.execute("INSERT INTO atividade_execucao VALUES ('tentativa','privado',123,456,10,'acompanhando',NULL)")
        self.db.execute('CREATE TABLE atividade_eventos(execucao,ultimo_evento,total,ultimo_tipo,eventos_filhos)')
        for evento in ((10,1,'fala',2),(-1,1,'fala',0),(10,0,'fala',0),(10,1,'desconhecido',0)):
            self.db.execute('DELETE FROM atividade_eventos')
            self.db.execute('INSERT INTO atividade_eventos VALUES (?,?,?,?,?)',('tentativa',*evento))
            with self.subTest(evento=evento),self.assertRaisesRegex(ValueError,'Eventos de atividade'):
                saude_tarefas(self.db,'owner/a')
        self.db.execute('DELETE FROM atividade_eventos')
        dados=saude_tarefas(self.db,'owner/a')
        self.assertNotIn('eventos',dados['atividades']['42'])
        self.assertNotIn('privado',json.dumps(dados))


if __name__=='__main__': unittest.main()
