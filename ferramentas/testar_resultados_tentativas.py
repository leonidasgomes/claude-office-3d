"""Atribuição/histórico em SQLite real; sem cloud, GitHub ou migração do legado."""
from contextlib import closing
from pathlib import Path
import json,sqlite3,sys,tempfile,time,unittest
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from controle_tarefas import Controle
from gestao_painel import desempenho,consumo_desempenho

class Resultados(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.raiz=Path(self.tmp.name);self.banco=self.raiz/'tarefas.db';self.c=Controle(self.banco)
    def reserva(self,cartao='42',equipe='Dev',repo='owner/a'):
        t=self.c.reservar(repo,cartao,equipe,'codex',{'objetivo':'segredo','aceite':'segredo',
            'executor':{'modelo':'configurado','execucao':'cloud'}},quadro_atual=True)
        self.c.transicao(t,'executando');return t
    def tentativa(self,t,tipo='despacho',codigo=0,resultado=None):
        i=self.c.iniciar_execucao(t,tipo)
        if codigo is not None:self.c.terminar_execucao(i,codigo,1)
        if resultado:self.c.registrar_resultado(i,resultado)
        return i
    def ler(self,repo='owner/a'):
        with closing(sqlite3.connect(self.banco.resolve().as_uri()+'?mode=ro',uri=True)) as db:
            d=desempenho(db,repo)
        consumo_desempenho(d,self.raiz/'ausente.db',self.raiz)
        return d
    def test_resultados_imutaveis_e_condizentes_com_retorno(self):
        t=self.reserva();i=self.tentativa(t,codigo=None)
        with self.assertRaises(ValueError):self.c.registrar_resultado(i,'revisao_aprovada')
        self.c.terminar_execucao(i,1,1)
        with self.assertRaises(ValueError):self.c.registrar_resultado(i,'revisao_aprovada')
        self.c.registrar_resultado(i,'falha_console');self.c.registrar_resultado(i,'falha_console')
        with self.assertRaises(ValueError):self.c.registrar_resultado(i,'sem_entrega')
        with self.assertRaises(ValueError):self.c.iniciar_execucao(t,'adivinhado')
    def test_equipes_projetos_e_reserva_substituida_conservam_atribuicao(self):
        t=self.reserva();i=self.tentativa(t,resultado='sem_entrega')
        self.c.transicao(t,'cancelado')
        novo=self.reserva(equipe='Pesquisa');self.tentativa(novo,resultado='revisao_desativada')
        outro=self.reserva(repo='owner/b');self.tentativa(outro,codigo=9,resultado='falha_console')
        antes=self.banco.read_bytes();d=self.ler();self.assertEqual(antes,self.banco.read_bytes())
        g={x['equipe']:x for x in d['grupos']}
        self.assertEqual(g['Dev']['resultados']['sem_entrega'],1)
        self.assertEqual(g['Pesquisa']['resultados']['revisao_desativada'],1)
        self.assertEqual(len(self.ler('owner/b')['grupos']),1)
        publico=json.dumps(d);self.assertNotIn(t,publico);self.assertNotIn(i,publico);self.assertNotIn('segredo',publico)
        self.assertFalse((self.raiz/'ausente.db').exists())
    def test_retomada_tipo_explicito_e_cobertura_resultado_independente(self):
        t=self.reserva();self.tentativa(t,codigo=1,resultado='falha_console')
        self.tentativa(t,'retomada',resultado='revisao_aprovada')
        self.tentativa(t,codigo=None)
        g=self.ler()['grupos'][0]
        self.assertEqual((g['tentativas'],g['despachos'],g['retomadas'],g['sem_resultado']),(3,2,1,1))
        self.assertEqual((g['sem_retorno'],g['resultados']['revisao_aprovada'],g['resultados']['falha_console']),(1,1,1))
    def test_banco_anterior_nao_adivinha_resultado_ou_equipe(self):
        t=self.reserva();i=self.tentativa(t,resultado='revisao_aprovada')
        with closing(sqlite3.connect(self.banco)) as db,db:db.execute('DROP TABLE execucao_resultado')
        antes=self.banco.read_bytes();g=self.ler()['grupos'][0]
        self.assertEqual(antes,self.banco.read_bytes())
        self.assertEqual((g['equipe'],g['tipo_nao_informado'],g['sem_resultado']),('não informado',1,1))
        self.assertEqual(sum(g['resultados'].values()),0)
    def test_resultado_corrompido_nao_vira_entrega_aceita(self):
        t=self.reserva();i=self.tentativa(t,codigo=1,resultado='falha_console')
        with closing(sqlite3.connect(self.banco)) as db,db:
            db.execute("UPDATE execucao_resultado SET resultado='revisao_aprovada' WHERE execucao=?",(i,))
        with self.assertRaises(ValueError):self.ler()

if __name__=='__main__':unittest.main()
