"""Conciliação do pedido vinculado à tentativa exata; nenhuma liberação de tarefas."""
from contextlib import closing
from pathlib import Path
import json,sqlite3,sys,unittest
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent));sys.path.insert(0,str(Path(__file__).resolve().parent))
import retomada_painel as painel
import testar_retomada_painel as fixtures
import gestao_cli as gc
from controle_tarefas import Controle

class Conciliacao(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.Painel();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.projeto=self.f.projeto;self.repo=self.f.repo;self.db=self.f.f.db
        codigo,r=self.f.api(self.f.preparar());self.assertEqual(codigo,202)
        final=self.f.aguardar(r['pedido_id']);self.assertEqual(final['estado'],'concluida')
        self.pedido=r['pedido_id']
        # Simula perda do registro final do painel, mantendo retorno real da tentativa.
        with closing(painel.abrir(self.projeto,True)) as db,db:
            db.execute("UPDATE pedido_retomada SET estado='incerto',resultado=NULL,codigo=NULL WHERE id=?",(self.pedido,))
        self.dados={k:v for k,v in self.f.dados.items() if k!='cartao'};self.dados.update(pedido_id=self.pedido,acao='previa')
    def api(self,dados=None,permissao='pc'):return painel.api_conciliar([self.projeto],dados or self.dados,{'permissao':permissao})
    def previa(self):
        codigo,r=self.api();self.assertEqual(codigo,200)
        return {**self.dados,'acao':'aplicar','evidencia_sha256':r['evidencia_sha256']}
    def registro(self):
        with closing(painel.abrir(self.projeto)) as db:return db.execute('SELECT estado FROM pedido_retomada WHERE id=?',(self.pedido,)).fetchone()[0]

    def test_conciliar_so_acompanhamento_sem_alterar_reserva_historico_kanban(self):
        antes=Controle(self.db).listar(self.repo);patches=len(self.f.f.f.fixture.chamadas);calls=list(self.f.f.calls)
        with closing(sqlite3.connect(self.db)) as db:historico=db.execute('SELECT * FROM execucao_tarefa ORDER BY id').fetchall()
        d=self.previa();codigo,r=self.api(d);self.assertEqual((codigo,r['estado'],r['resultado']),(200,'conciliada','bloqueado'))
        self.assertEqual(Controle(self.db).listar(self.repo),antes);self.assertEqual(self.f.f.calls,calls)
        self.assertEqual(len(self.f.f.f.fixture.chamadas),patches)
        with closing(sqlite3.connect(self.db)) as db:self.assertEqual(db.execute('SELECT * FROM execucao_tarefa ORDER BY id').fetchall(),historico)
        self.assertEqual(painel.resumo(self.projeto,self.repo)['itens'][0]['estado'],'conciliada')
        self.assertEqual(self.api(d)[0],409)
        # A conciliação permite outro pedido, que ainda passa pelos gates de retomada.
        codigo,r=self.f.api(self.f.preparar());self.assertEqual(codigo,202);self.f.aguardar(r['pedido_id'])
        self.assertEqual(len(self.f.f.calls),3)

    def test_saida_zero_nao_aprova_cartao_e_resposta_nao_vaza_vinculos(self):
        codigo,r=self.api();self.assertEqual(codigo,200);self.assertEqual((r['resultado'],r['codigo']),('bloqueado',0))
        texto=json.dumps(r);self.assertNotIn('sessao-42',texto);self.assertNotIn(str(self.f.f.trabalho),texto)
        self.assertEqual(set(r),{'pedido_id','cartao','resultado','codigo','evidencia_sha256','somente_preparacao'})
        with closing(painel.abrir(self.projeto)) as db:
            token,tentativa=db.execute('SELECT reserva,execucao FROM retomada_contexto WHERE pedido=?',(self.pedido,)).fetchone()
        self.assertNotIn(token,texto);self.assertNotIn(tentativa,texto)

    def test_tentativa_sem_retorno_ou_atividade_interrompida_rejeitadas(self):
        with closing(painel.abrir(self.projeto)) as db:ident=db.execute('SELECT execucao FROM retomada_contexto WHERE pedido=?',(self.pedido,)).fetchone()[0]
        with closing(sqlite3.connect(self.db)) as db,db:
            fim=db.execute('SELECT fim FROM execucao_tarefa WHERE id=?',(ident,)).fetchone()[0]
            db.execute('UPDATE execucao_tarefa SET fim=NULL WHERE id=?',(ident,))
        self.assertEqual(self.api()[0],409)
        with closing(sqlite3.connect(self.db)) as db,db:
            db.execute('UPDATE execucao_tarefa SET fim=? WHERE id=?',(fim,ident));db.execute("UPDATE atividade_execucao SET estado='interrompido' WHERE execucao=?",(ident,))
        self.assertEqual(self.api()[0],409);self.assertEqual(self.registro(),'incerto')

    def test_nova_tentativa_cli_nao_e_retorno_do_pedido_antigo(self):
        self.f.f.retomar()
        self.assertEqual(len(self.f.f.calls),3);self.assertEqual(self.api()[0],409);self.assertEqual(self.registro(),'incerto')

    def test_nova_reserva_do_mesmo_cartao_nao_e_mesmo_pedido(self):
        controle=Controle(self.db);atual=controle.listar(self.repo)[0];controle.transicao(atual['token'],'cancelado')
        controle.reservar(self.repo,'42','Dev','codex',atual['pacote'],quadro_atual=True)
        self.assertEqual(self.api()[0],409)

    def test_hash_politica_ou_atividade_alteradas_impedem_aplicacao(self):
        d=self.previa();self.assertEqual(self.api({**d,'evidencia_sha256':'a'*64})[0],409)
        self.assertEqual(self.api({**d,'versao':'a'*64})[0],409)
        with closing(sqlite3.connect(self.db)) as db,db:db.execute('UPDATE atividade_execucao SET ultimo_sinal=ultimo_sinal+1')
        self.assertEqual(self.api(d)[0],409);self.assertEqual(self.registro(),'incerto')

    def test_pedido_ativo_ou_celular_e_campos_extras_rejeitados(self):
        self.assertEqual(self.api(permissao='conferir')[0],403)
        self.assertEqual(self.api({**self.dados,'execucao':'a'*32})[0],400)
        self.assertEqual(self.api({**self.dados,'pedido_id':42})[0],400)
        with patch.dict(painel._ativos,{self.pedido:SimpleNamespace(is_alive=lambda:True)}):self.assertEqual(self.api()[0],409)

    def test_historico_sem_contexto_nao_e_inferido(self):
        with closing(painel.abrir(self.projeto,True)) as db,db:db.execute('DROP TABLE retomada_contexto')
        self.assertEqual(self.api()[0],409);self.assertEqual(self.registro(),'incerto')
        with closing(painel.abrir(self.projeto)) as db:self.assertFalse(db.execute("SELECT 1 FROM sqlite_master WHERE name='retomada_contexto'").fetchone())

    def test_falha_de_vinculo_antes_de_lancar_impede_nova_inferencia(self):
        with closing(painel.abrir(self.projeto,True)) as db,db:db.execute("UPDATE pedido_retomada SET estado='concluida',resultado='bloqueado',codigo=0 WHERE id=?",(self.pedido,))
        d=self.f.preparar();antes=len(self.f.f.calls)
        with patch.object(painel,'vincular',side_effect=ValueError('falhou vínculo')):
            codigo,r=self.f.api(d);self.assertEqual(codigo,202);final=self.f.aguardar(r['pedido_id'])
        self.assertEqual(final['estado'],'incerto');self.assertEqual(len(self.f.f.calls),antes)
        self.dados['pedido_id']=r['pedido_id'];self.assertEqual(self.api()[0],409)

    def test_snapshot_de_tarefas_fica_protegido_ate_commit_do_ledger(self):
        d=self.previa();real=painel.evidencia_conciliacao;verificou=[]
        def conferir(*args,**kw):
            r=real(*args,**kw)
            if len(args)>4:
                with self.assertRaises(sqlite3.OperationalError),closing(sqlite3.connect(self.db,timeout=.01)) as outro,outro:
                    outro.execute('UPDATE reserva SET atualizado=atualizado+1')
                verificou.append(True)
            return r
        with patch.object(painel,'evidencia_conciliacao',side_effect=conferir):self.assertEqual(self.api(d)[0],200)
        self.assertEqual(verificou,[True])

    def test_wal_nao_finge_atomicidade_de_dois_bancos(self):
        d=self.previa()
        with closing(sqlite3.connect(self.db)) as db:db.execute('PRAGMA journal_mode=WAL')
        self.assertEqual(self.api(d)[0],409);self.assertEqual(self.registro(),'incerto')

if __name__=='__main__':unittest.main()
