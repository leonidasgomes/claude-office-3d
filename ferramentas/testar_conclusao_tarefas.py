import hashlib
import json
import sqlite3
from contextlib import closing
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from controle_tarefas import Controle
import conclusao_tarefas as alvo

HEAD='a'*40
MERGE='b'*40


class Quadro:
    def __init__(self,cfg):
        self.cfg=cfg['kanban'];self.status='Em revisão';self.movimentos=[]
        self.pr={'number':8,'state':'closed','merged':True,'merged_at':'2026-10-10T10:00:00Z',
            'merge_commit_sha':MERGE,'body':'Closes #4','head':{'sha':HEAD,'ref':'feat/cartao-4',
            'repo':{'full_name':'o/r'}},'base':{'repo':{'full_name':'o/r'}}}
        self.checks=[{'id':i,'head_sha':HEAD,'app':{'id':1},'name':n,'status':'completed','conclusion':'success'} for i,n in enumerate(('verificar','preparar-windows'),1)]
        self.total=None;self.statuses=[]
        self.issue_state='closed';self.fechamentos=[]
    def cartao(self,n,ao_vivo=False):return {'status':self.status,'equipe':'Dev','prioridade':''}
    def issue(self,n):return {'state':self.issue_state,'html_url':'https://github.com/o/r/issues/4',
                                'title':'Objetivo','body':'**Aceite:** ok'}
    def chamar(self,url,metodo='GET',dados=None):
        if '/issues/' in url and metodo=='PATCH':
            self.fechamentos.append(dados);self.issue_state='closed';return self.issue(4)
        if '/pulls/' in url:return self.pr
        if '/check-runs' in url:return {'check_runs':self.checks,'total_count':len(self.checks) if self.total is None else self.total}
        raise AssertionError(url)
    def _paginas(self,url):
        if url.endswith('/statuses'):return self.statuses
        raise AssertionError(url)
    def mover(self,n,status):self.movimentos.append(status);self.status=status


class Conclusao(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.projeto=Path(self.tmp.name);self.banco=self.projeto/'tarefas.db'
        self.cfg={'ativo':True,'kanban':{'repo':'o/r','revisao':'Em revisão','feito':'Feito'},
                  'revisao':{'ativo':False},'merge':{'checks':['verificar','preparar-windows']}}
        self.k=Quadro(self.cfg)
        politica=hashlib.sha256(json.dumps(self.cfg,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        pacote={'objetivo':'Objetivo','aceite':'ok','escopo':'Somente o necessário para o aceite',
                'skills':'','url':'https://github.com/o/r/issues/4','prioridade':'',
                'fontes_resolvidas':[],'contexto_execucao':{'branch':'feat/cartao-4',
                'worktree':str(self.projeto),'politica_sha256':politica}}
        self.c=Controle(self.banco)
        self.token=self.c.reservar('o/r','4','Dev','codex',pacote,True)
        self.c.transicao(self.token,'executando');self.c.transicao(self.token,'revisao')
        self.patchers=[patch.object(alvo,'carregar',return_value=self.cfg),
                       patch.object(alvo,'fontes_resolvidas',return_value=[])]
        for p in self.patchers:p.start();self.addCleanup(p.stop)
    def test_fila_so_considera_entrega_vinculada_da_sessao(self):
        with closing(sqlite3.connect(self.banco)) as db,db:
            db.execute('INSERT INTO entrega VALUES (?,?,?,?,?,?)',(self.token,HEAD,8,1,'{}',1))
        registro={'vinculos_conclusao':[{'cartao':4,'token':self.token}],
            'resultados':[{'resultados':[{'cartao':4,'estado':'revisao','codigo':0}]}]}
        with patch.object(alvo,'pasta_dados',return_value=self.projeto),patch.object(alvo,'api') as api:
            itens=alvo.pendencias_sessao(self.projeto,registro)
            self.assertEqual(itens,[{'cartao':4,'equipe':'Dev','pr':8,'head':HEAD,'estado':'aguardando_merge','motivo':''}])
            api.assert_not_called()
            self.assertEqual(alvo.pendencias_sessao(self.projeto,{}),[])
            registro['conclusoes']=[{'token':self.token,'estado':'bloqueado','motivo':'Gate ausente'}]
            self.assertEqual(alvo.pendencias_sessao(self.projeto,registro)[0]['estado'],'conferencia_necessaria')
            registro['conclusoes']=[{'token':self.token,'estado':'concluido'}]
            self.assertEqual(alvo.pendencias_sessao(self.projeto,registro),[])

    def test_fila_rejeita_vinculo_substituido_ou_duplicado(self):
        registro={'vinculos_conclusao':[{'cartao':4,'token':'f'*32}],
            'resultados':[{'resultados':[{'cartao':4,'estado':'revisao','codigo':0}]}]}
        with patch.object(alvo,'pasta_dados',return_value=self.projeto):
            with self.assertRaisesRegex(ValueError,'mudou'):alvo.pendencias_sessao(self.projeto,registro)
            registro['vinculos_conclusao']*=2
            with self.assertRaises(ValueError):alvo.pendencias_sessao(self.projeto,registro)

    def run_previa(self):return alvo.preparar(self.projeto,4,8,self.banco,self.k)[0]
    def test_previa_sem_escrita_e_sucesso_idempotente(self):
        antes=self.banco.read_bytes()
        self.assertEqual(self.run_previa()['estado'],'pronto')
        self.assertEqual(self.banco.read_bytes(),antes)
        self.assertEqual(alvo.executar(self.projeto,4,8,self.banco,self.k)['estado'],'concluido')
        self.assertEqual(self.k.movimentos,['Feito'])
        self.assertEqual(alvo.executar(self.projeto,4,8,self.banco,self.k)['estado'],'concluido')
        self.assertEqual(self.k.movimentos,['Feito'])
        self.assertEqual(self.c.listar('o/r')[0]['estado'],'concluido')

    def test_merge_em_base_nao_padrao_fecha_issue_somente_apos_gates(self):
        self.k.issue_state='open'
        self.assertEqual(self.run_previa()['estado'],'pronto')
        self.assertEqual(self.k.fechamentos,[])
        self.k.pr['merged']=False
        with self.assertRaises(ValueError):alvo.executar(self.projeto,4,8,self.banco,self.k)
        self.assertEqual(self.k.fechamentos,[])
        self.k.pr['merged']=True;self.k.checks[0]['conclusion']='failure'
        with self.assertRaises(ValueError):alvo.executar(self.projeto,4,8,self.banco,self.k)
        self.assertEqual(self.k.fechamentos,[])
        self.k.checks[0]['conclusion']='success'
        alvo.executar(self.projeto,4,8,self.banco,self.k)
        alvo.executar(self.projeto,4,8,self.banco,self.k)
        self.assertEqual(self.k.fechamentos,[{'state':'closed'}])
        self.assertEqual(self.k.movimentos,['Feito'])

    def test_sessao_so_conclui_token_atual_mergeado_sem_retornar_reservas_antigas(self):
        cfg={**self.cfg,'merge':{**self.cfg['merge'],'modo':'automatico'}}
        with closing(sqlite3.connect(self.banco)) as db,db:
            db.execute('INSERT INTO entrega VALUES (?,?,?,?,?,?)',(self.token,HEAD,8,1,'{}',1))
        registro={'vinculos_conclusao':[{'cartao':4,'token':self.token}], 'resultados':[{'resultados':[{'cartao':4,'estado':'revisao','codigo':0}]}]}
        with patch.object(alvo,'carregar',return_value=cfg),patch.object(alvo,'pasta_dados',return_value=self.projeto),\
             patch.object(alvo,'api',return_value={'merged':False}),patch.object(alvo,'executar') as executar:
            self.assertEqual(alvo.confirmar_sessao(self.projeto,registro),[]);executar.assert_not_called()
        with patch.object(alvo,'carregar',return_value=cfg),patch.object(alvo,'pasta_dados',return_value=self.projeto),\
             patch.object(alvo,'api',return_value={'merged':True}),patch.object(alvo,'executar',return_value={'estado':'concluido'}) as executar:
            resultado=alvo.confirmar_sessao(self.projeto,registro)
            executar.assert_called_once_with(self.projeto,4,8)
            registro['conclusoes']=resultado
            self.assertEqual(alvo.confirmar_sessao(self.projeto,registro),[])
            registro.pop('vinculos_conclusao');registro.pop('conclusoes')
            self.assertEqual(alvo.confirmar_sessao(self.projeto,registro),[])

    def test_erro_de_conclusao_registrado_sem_retry_automatico(self):
        cfg={**self.cfg,'merge':{**self.cfg['merge'],'modo':'automatico'}}
        with closing(sqlite3.connect(self.banco)) as db,db:
            db.execute('INSERT INTO entrega VALUES (?,?,?,?,?,?)',(self.token,HEAD,8,1,'{}',1))
        registro={'vinculos_conclusao':[{'cartao':4,'token':self.token}], 'resultados':[{'resultados':[{'cartao':4,'estado':'revisao','codigo':0}]}]}
        with patch.object(alvo,'carregar',return_value=cfg),patch.object(alvo,'pasta_dados',return_value=self.projeto),\
             patch.object(alvo,'api',return_value={'merged':True}),patch.object(alvo,'executar',side_effect=ValueError('check alterado')) as executar:
            resultado=alvo.confirmar_sessao(self.projeto,registro)
            self.assertEqual(resultado[0]['estado'],'bloqueado')
            registro['conclusoes']=resultado
            self.assertEqual(alvo.confirmar_sessao(self.projeto,registro),[])
            executar.assert_called_once()

    def test_vinculo_exige_mesmo_worktree_e_nao_expoe_token_no_resumo(self):
        with patch.object(alvo,'pasta_dados',return_value=self.projeto):
            self.assertIsNone(alvo.vincular_despacho(self.projeto,{'cartao':4,'worktree':str(self.projeto/'outro')}))
            self.assertEqual(alvo.vincular_despacho(self.projeto,{'cartao':4,'worktree':str(self.projeto)}),
                             {'cartao':4,'token':self.token})
        import ciclo_gdd
        estado=self.projeto/'ciclo.json'
        estado.write_text(json.dumps({'vinculos_conclusao':[{'token':self.token}],
            'conclusoes':[{'cartao':4,'pr':8,'estado':'concluido','token':self.token}]}),encoding='utf-8')
        with patch.object(ciclo_gdd,'caminho_estado',return_value=estado):
            publico=ciclo_gdd.resumo(self.projeto)
        self.assertNotIn(self.token,json.dumps(publico))
        self.assertEqual(publico['conclusoes'][0]['estado'],'concluido')
    def test_recupera_falha_local_apos_movimento(self):
        with patch.object(Controle,'concluir',side_effect=OSError('disco')):
            with self.assertRaises(OSError):alvo.executar(self.projeto,4,8,self.banco,self.k)
        self.assertEqual(self.k.status,'Feito')
        self.assertEqual(self.c.listar('o/r')[0]['estado'],'revisao')
        self.assertEqual(alvo.executar(self.projeto,4,8,self.banco,self.k)['estado'],'concluido')
        self.assertEqual(self.k.movimentos,['Feito'])
    def test_rejeicoes_sem_escrita(self):
        casos=[lambda:self.k.pr.update(merged=False),
               lambda:self.k.pr['head'].update(ref='outra'),
               lambda:self.k.pr.update(body='Closes #40'),
               lambda:self.k.pr['head']['repo'].update(full_name='outro/r'),
               lambda:self.k.checks.pop(),
               lambda:self.k.checks[0].update(conclusion='failure'),
               lambda:self.cfg['merge'].update(checks=['outro'])]
        for alterar in casos:
            pr=json.loads(json.dumps(self.k.pr));checks=json.loads(json.dumps(self.k.checks));cfg=json.loads(json.dumps(self.cfg))
            antes=self.banco.read_bytes();alterar()
            with self.assertRaises(ValueError):self.run_previa()
            self.assertEqual(self.banco.read_bytes(),antes)
            self.k.pr=pr;self.k.checks=checks;self.cfg.clear();self.cfg.update(cfg)
    def test_revisao_ativa_exige_entrega(self):
        self.cfg['revisao']['ativo']=True
        # Atualiza o vínculo de política da fixture, sem conceder aprovação.
        with closing(sqlite3.connect(self.banco)) as db,db:
            pacote=json.loads(db.execute('SELECT pacote FROM reserva').fetchone()[0])
            pacote['contexto_execucao']['politica_sha256']=hashlib.sha256(json.dumps(self.cfg,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
            db.execute('UPDATE reserva SET pacote=?',(json.dumps(pacote),))
        with self.assertRaisesRegex(ValueError,'Revisão aprovada'):self.run_previa()

    def test_banco_anterior_sem_tabela_de_conclusao_previa_nao_migra(self):
        with closing(sqlite3.connect(self.banco)) as db,db:db.execute('DROP TABLE conclusao')
        antes=self.banco.read_bytes();self.assertEqual(self.run_previa()['estado'],'pronto')
        self.assertEqual(self.banco.read_bytes(),antes)
        self.assertEqual(alvo.executar(self.projeto,4,8,self.banco,self.k)['estado'],'concluido')

    def test_check_de_outro_head_e_paginacao_incompleta_bloqueiam(self):
        self.k.checks[0]['head_sha']='c'*40
        with self.assertRaises(ValueError):self.run_previa()
        self.k.checks[0]['head_sha']=HEAD;self.k.total=101
        with self.assertRaisesRegex(ValueError,'incompleta'):self.run_previa()

    def test_status_mais_recente_vale_e_fonte_ambigua_bloqueia(self):
        self.k.checks.pop(0)
        self.k.statuses=[{'id':3,'context':'verificar','state':'success'},
                         {'id':2,'context':'verificar','state':'failure'}]
        self.assertEqual(self.run_previa()['estado'],'pronto')
        self.k.statuses[0]['state']='pending'
        with self.assertRaises(ValueError):self.run_previa()

    def test_politica_mudando_apos_previa_nao_move_cartao(self):
        original=alvo.preparar
        def mudar(*args,**kwargs):
            r=original(*args,**kwargs);self.cfg['merge']['checks'].append('novo');return r
        with patch.object(alvo,'preparar',side_effect=mudar),self.assertRaisesRegex(ValueError,'Política mudou'):
            alvo.executar(self.projeto,4,8,self.banco,self.k)
        self.assertEqual(self.k.movimentos,[])


if __name__=='__main__':unittest.main()
