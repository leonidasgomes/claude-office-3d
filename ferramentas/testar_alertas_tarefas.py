"""Detector/fonte/fila com SQLite real; sem envio ou chamadas cloud/GitHub."""
import json,sqlite3,sys
from contextlib import closing
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import testar_sugestoes_projeto as fixtures
import alertas,alertas_projetos,gestao_cli
from controle_tarefas import Controle


class Tarefas(fixtures.Sugestoes):
    def setUp(self):
        super().setUp();self.est={};self.opc=alertas.normalizar_opcoes({})
    def passo(self,agora=10000):
        return alertas.detectar(self.est,{'projetos':alertas_projetos.fontes(self.base)},agora,self.opc)
    def tarefa(self,p=None,estado='bloqueado',cartao='42'):
        p=p or self.a;repo='owner/'+p.name
        c=Controle(gestao_cli.pasta_dados(p)/'tarefas.db')
        token=c.reservar(repo,cartao,'Dev','codex',{'objetivo':'SEGREDO','aceite':'ok'},True)
        c.transicao(token,estado)
        return c,token
    def test_bloqueio_por_projeto_dedup_e_sem_segredo(self):
        self.assertEqual(self.passo(),[])
        for p in (self.a,self.b):self.tarefa(p)
        novos=self.passo();self.assertEqual(len(novos),2)
        self.assertEqual({a['repo'] for a in novos},{'owner/a','owner/b'})
        for a in novos:
            self.assertEqual(a['tipo'],'tarefa_pendente')
            self.assertEqual(a['url'],'/#alerta=gestao&projeto='+a['projeto_id'])
            self.assertNotIn('SEGREDO',json.dumps(a))
        self.assertEqual(self.passo(),[])
    def test_primeira_leitura_registra_sem_aviso(self):
        self.tarefa();self.assertEqual(self.passo(),[])
        self.assertEqual(self.passo(),[])
    def test_sem_retorno_so_apos_30_min_e_cancelamento_nao_some(self):
        self.passo();c,token=self.tarefa(estado='executando')
        ident=c.iniciar_execucao(token)
        with closing(sqlite3.connect(c.banco)) as db,db:db.execute('UPDATE execucao_tarefa SET inicio=10000 WHERE id=?',(ident,))
        self.assertEqual(self.passo(11799),[])
        aviso=self.passo(11800);self.assertEqual(len(aviso),1)
        self.assertIn('30 min',aviso[0]['corpo']);self.assertNotIn('morto',aviso[0]['corpo'])
        c.transicao(token,'cancelado');self.assertEqual(self.passo(11801),[])
    def test_falha_nova_tentativa_mesmo_cartao(self):
        self.passo();c,token=self.tarefa(estado='executando');ident=c.iniciar_execucao(token)
        c.terminar_execucao(ident,9,1)
        self.assertEqual(len(self.passo()),1)
        c.transicao(token,'cancelado');self.passo()
        c,token=self.tarefa(estado='executando');ident=c.iniciar_execucao(token)
        c.terminar_execucao(ident,9,1)
        self.assertEqual(len(self.passo()),1)
    def test_erro_banco_preserva_baseline(self):
        c,token=self.tarefa();self.passo()
        antes=json.dumps(self.est,sort_keys=True);original=c.banco.read_bytes()
        c.banco.write_bytes(b'invalido')
        self.assertEqual(self.passo(),[]);self.assertEqual(json.dumps(self.est,sort_keys=True),antes)
        c.banco.write_bytes(original);self.assertEqual(self.passo(),[])
    def test_cobertura_parcial_nao_apaga_registro_ausente(self):
        f={'pendencias':[{'registro':'a'*32,'cartao':'42','sinais':['bloqueada']}],'limitado':False}
        est={};alertas._detectar_tarefas(est,f,10000,[])
        alertas._detectar_tarefas(est,{'pendencias':[],'limitado':True},10000,[])
        novos=[];alertas._detectar_tarefas(est,f,10000,novos);self.assertEqual(novos,[])
    def test_fila_persistida_reinicio_e_orcamento(self):
        fontes={'projetos':lambda:alertas_projetos.fontes(self.base)}
        a=alertas.Alertas(self.raiz/'fila',fontes,{'imediatos':[]})
        self.assertEqual(a.passo(10000),[]);self.tarefa()
        self.assertEqual(len(a.passo(10001)),1)
        b=alertas.Alertas(self.raiz/'fila',fontes,{'imediatos':[]})
        self.assertEqual(b.passo(10002),[])
        fila,_=b.listar();self.assertEqual(len(fila),1)
        self.assertEqual(fila[0]['tipo'],'tarefa_pendente')


if __name__=='__main__':
    import unittest
    unittest.main()
