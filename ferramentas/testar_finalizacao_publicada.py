"""Publicação anterior ao limite: Git/SQLite reais, decisões e rede simuladas."""
import copy,json,sqlite3,sys,unittest
from pathlib import Path
from contextlib import closing
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import testar_revisao_execucao as fixtures
import gestao_cli,finalizacao_publicada as f,revisao_execucao
from controle_tarefas import Controle
from gestao_projeto import fontes_resolvidas,executor


class Finalizacao(unittest.TestCase):
    preparar_publicacao=fixtures.Publicacao.preparar_publicacao
    def setUp(self):
        fixtures.Publicacao.setUp(self)
        self.cfg['ciclo']={'ativo':True,'base':'origin/main'}
        self.cfg['metas']={'ativo':True,'tempo_min':60,'tokens':2000000}
        self.cfg,self.relatorio,self.pr,self.api=self.preparar_publicacao()
        self.pr.update(body='Closes #1',title='Entrega',labels=[])
        self.pr['head']['ref']='feat/trabalho';self.pr['base']['ref']='main'
        self.dados=gestao_cli.pasta_dados(self.repo)
        self.k=Mock()
        self.k.cartao.return_value={'status':self.cfg['kanban']['andamento'],'equipe':'Dev','prioridade':'P1'}
        self.k.issue.return_value={'state':'open','title':'Entrega','body':'**Objetivo:** Entrega\n\n**Aceite:** Aceite'}
        self.k.chamar.side_effect=lambda *_:copy.deepcopy(self.pr)
        pacote={**gestao_cli.instrucoes_cartao(self.k.issue.return_value),'prioridade':'P1',
            'executor':executor(self.cfg,equipe='Dev',escopo='implementacao'),
            'skills_resolvidas':[],'fontes_resolvidas':fontes_resolvidas(self.repo,self.cfg),
            'contexto_execucao':{'worktree':str(self.trabalho.resolve()),'branch':'feat/trabalho',
                'escopo':'implementacao','politica_sha256':f.assinatura(self.cfg)}}
        self.ctrl=Controle(self.dados/'tarefas.db')
        self.token=self.ctrl.reservar('owner/repo','1','Dev','gemini',pacote,quadro_atual=True)
        self.ctrl.transicao(self.token,'executando');self.t=self.ctrl.iniciar_execucao(self.token)
        pubdir=self.dados/'publicacoes';pubdir.mkdir()
        self.pub=pubdir/'1.json'
        self.publicacao={'estado':'publicado','cartao':1,'sha':self.pr['head']['sha'],
            'pr':'https://github.com/owner/repo/pull/42','worktree':str(self.trabalho.resolve()),'branch':'feat/trabalho'}
        self.pub.write_text(json.dumps(self.publicacao),encoding='utf-8')
        self.ctrl.terminar_execucao(self.t,124,1);self.ctrl.transicao(self.token,'bloqueado')
        with closing(sqlite3.connect(self.ctrl.banco)) as db,db:
            db.execute('CREATE TABLE atividade_execucao(execucao TEXT,estado TEXT,codigo_console INTEGER)')
            db.execute('CREATE TABLE atividade_eventos(execucao TEXT,eventos_filhos INTEGER)')
            db.execute('INSERT INTO atividade_execucao VALUES (?,?,?)',(self.t,'encerrado',124))
            db.execute('INSERT INTO atividade_eventos VALUES (?,0)',(self.t,))
        md=self.dados/'metas';md.mkdir()
        self.meta={'tentativa':self.t,'estado':'limite_tokens','fim':1,'tokens_observados':2000020,
                   'meta':{'cartao':1,'limites':{'tempo_min':60,'tokens':2000000}}}
        self.metafile=md/(self.t+'.json');self.metafile.write_text(json.dumps(self.meta),encoding='utf-8')
        criados=gestao_cli.RAIZ/'dados/worktrees';criados.mkdir(parents=True)
        (criados/'criado.json').write_text(json.dumps({'estado':'criado','projeto':str(self.repo.resolve()),
            'criados':[{'cartao':1,'worktree':str(self.trabalho.resolve()),'branch':'feat/trabalho'}]}),encoding='utf-8')
        self.fila={'encaminhamentos':[{'pr':42,'head':self.pr['head']['sha'],'acao':'revisar','motivo':'revisão pendente'}]}

    def preparar(self):return f.preparar(self.repo,self.cfg,self.pr,self.dados,self.k)
    def executar(self,chamar=None,revisar=None):
        return f.encaminhar(self.repo,self.cfg,[self.pr],self.fila,self.dados,self.k,
            chamar_ceo=chamar or (lambda _:json.dumps({'acao':'revisar','motivo':'encaminhar PR existente'})),
            revisar=revisar or (lambda *a,**kw:revisao_execucao.executar(*a,**kw,
                chamar=lambda *_:{'veredito':'aprovado','achados':[]})))
    def historico(self):
        with closing(sqlite3.connect(self.ctrl.banco)) as db:
            return db.execute('SELECT * FROM execucao_tarefa').fetchall()

    def test_origem_legada_unica_com_git_real(self):
        antes=self.ctrl.banco.read_bytes();e,trabalho=self.preparar()
        self.assertEqual(e['tentativa']['codigo'],124);self.assertEqual(trabalho,self.trabalho.resolve())
        self.assertEqual(antes,self.ctrl.banco.read_bytes())
    def test_nao_adota_rascunho_manual_parcial_ou_fechado(self):
        original=copy.deepcopy(self.pr)
        for valores in ({'draft':True},{'state':'closed'},{'labels':[{'name':'merge-manual'}]},
                        {'body':'Parte de #1'},{'body':'Closes #1; closes #2'}):
            self.pr={**original,**valores};self.assertIsNone(self.preparar())
    def test_publicacao_posterior_ao_termino_nao_e_elegivel(self):
        import os,time
        os.utime(self.pub,(time.time()+10,time.time()+10));self.assertIsNone(self.preparar())
    def test_recibo_novo_exige_tentativa_e_token(self):
        self.publicacao.update(tentativa=self.t,token='outro')
        self.pub.write_text(json.dumps(self.publicacao),encoding='utf-8')
        self.assertIsNone(self.preparar())
    def test_head_sujo_base_e_contexto_divergentes_param(self):
        original=copy.deepcopy(self.pr)
        for ramo,valor in (('head','outra'),('base','outra')):
            self.pr=copy.deepcopy(original);self.pr[ramo]['ref']=valor
            with self.assertRaisesRegex(ValueError,'diverge'):self.preparar()
        self.pr=original;(self.trabalho/'codigo.py').write_text('alteração concorrente',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'altera'):self.preparar()
    def test_processo_filho_e_limite_incertos_nao_revisam(self):
        with closing(sqlite3.connect(self.ctrl.banco)) as db,db:
            db.execute('UPDATE atividade_eventos SET eventos_filhos=1')
        with self.assertRaisesRegex(ValueError,'incertos'):self.preparar()
    def test_cartao_e_fontes_mudaram_nao_finaliza(self):
        self.k.cartao.return_value['equipe']='Outra'
        with self.assertRaisesRegex(ValueError,'mudou'):self.preparar()
    def test_ceo_aguardar_e_diretor_aguardar_nao_repetem_modelo(self):
        chefe=Mock(return_value=json.dumps({'acao':'aguardar','motivo':'aguardar recurso'}));revisor=Mock()
        self.assertIsNone(self.executar(chefe,revisor));self.assertIsNone(self.executar(chefe,revisor))
        chefe.assert_called_once();revisor.assert_not_called()
        self.fila['encaminhamentos'][0]['acao']='aguardar'
        self.assertIsNone(self.executar(chefe,revisor));chefe.assert_called_once()
    def test_revisao_nova_aprovada_preserva_limite_e_tentativa(self):
        antes=self.historico();meta=self.metafile.read_bytes()
        revisor=Mock(side_effect=lambda *a,**kw:revisao_execucao.executar(*a,**kw,
            chamar=lambda *_:{'veredito':'aprovado','achados':[]}))
        with patch('revisor_ia.publicar_revisao_gestao') as pub:
            r=self.executar(revisar=revisor);pub.assert_called_once()
        revisor.assert_called_once();self.assertEqual(r['estado'],'revisao');self.assertEqual(r['codigo_autor'],124)
        self.assertEqual(self.historico(),antes);self.assertEqual(self.metafile.read_bytes(),meta)
        reserva=self.ctrl.listar('owner/repo')[0]
        self.assertEqual(reserva['estado'],'revisao');self.assertEqual(reserva['token'],self.token)
        self.k.mover.assert_called_once_with(1,self.cfg['kanban']['revisao'])
        with closing(sqlite3.connect(self.ctrl.banco)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM finalizacao_publicada').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT aprovado FROM entrega').fetchone()[0],1)
        self.assertIsNone(self.executar(revisar=revisor));revisor.assert_called_once()
        registro={'finalizacoes_publicadas':[r],'vinculos_conclusao':[{'cartao':1,'token':self.token}]}
        self.assertTrue(f.vinculo_confirmado(self.repo,registro,registro['vinculos_conclusao'][0]))
        import conclusao_tarefas
        fila=conclusao_tarefas.pendencias_sessao(self.repo,registro)
        self.assertEqual(fila[0]['pr'],42);self.assertEqual(fila[0]['estado'],'aguardando_merge')
        with patch('conclusao_tarefas.api',return_value={'merged':False}),patch('conclusao_tarefas.executar') as concluir:
            self.assertEqual(conclusao_tarefas.confirmar_sessao(self.repo,registro),[]);concluir.assert_not_called()
        with patch('conclusao_tarefas.api',return_value={'merged':True}),patch('conclusao_tarefas.executar',return_value={'estado':'concluido'}) as concluir:
            self.assertEqual(conclusao_tarefas.confirmar_sessao(self.repo,registro)[0]['estado'],'concluido')
            concluir.assert_called_once_with(self.repo,1,42)
        with closing(sqlite3.connect(self.ctrl.banco)) as db,db:
            db.execute('UPDATE execucao_tarefa SET codigo=0')
        with self.assertRaisesRegex(ValueError,'diverge'):f.vinculo_confirmado(self.repo,registro,registro['vinculos_conclusao'][0])
    def test_reprovacao_mantem_bloqueio_sem_novo_autor(self):
        antes=self.historico()
        def rejeitar(*a,**kw):return revisao_execucao.executar(*a,**kw,chamar=lambda *_:
            {'veredito':'reprovado','achados':[{'prioridade':'P2','arquivo':'codigo.py','linha':1,'evidencia':'Aceite insuficiente'}]})
        with patch('revisor_ia.publicar_revisao_gestao'):
            r=self.executar(revisar=rejeitar)
        self.assertEqual(r['estado'],'bloqueado');self.assertEqual(self.historico(),antes)
        self.k.mover.assert_not_called();self.assertIsNone(self.executar(revisar=Mock()))
    def test_console_falhou_nao_publica_e_nao_repete_revisao(self):
        def indisponivel(*a,**kw):return revisao_execucao.executar(*a,**kw,chamar=lambda *_:'inválido')
        with patch('revisor_ia.publicar_revisao_gestao') as pub:
            with self.assertRaisesRegex(ValueError,'indisponível'):self.executar(revisar=indisponivel)
            pub.assert_not_called()
        with self.assertRaisesRegex(ValueError,'incerta'):self.executar(revisar=Mock())
        self.assertEqual(self.ctrl.listar('owner/repo')[0]['estado'],'bloqueado')
    def test_mudanca_apos_ceo_impede_revisao_e_conciliacao(self):
        def chefe(_):
            self.pr['body']='Closes #1\nAceite mudou'
            return json.dumps({'acao':'revisar','motivo':'sim'})
        revisor=Mock()
        with self.assertRaisesRegex(ValueError,'Contexto mudou'):self.executar(chefe,revisor)
        revisor.assert_not_called();self.assertEqual(self.ctrl.listar('owner/repo')[0]['estado'],'bloqueado')


if __name__=='__main__':unittest.main()
