import copy,json,sqlite3,sys,tempfile,unittest
from pathlib import Path
from contextlib import closing
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import correcoes_prs as c
from controle_tarefas import Controle
from gestao_projeto import validar


class Correcoes(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.p=Path(self.tmp.name)
        self.cfg=validar({'ativo':True,'metas':{'ativo':True,'tempo_min':60,'tokens':2000000},
            'ciclo':{'ativo':True,'base':'origin/main'},'kanban':{'repo':'o/r'},
            'equipes':[{'nome':'Dev','especialidade':'Código','executor':{'console':'codex'}}]})
        self.ctrl=Controle(self.p/'tarefas.db')
        self.pacote={'objetivo':'entrega','aceite':'aceite integral preservado','escopo':'implementar',
            'skills':'nenhuma','cartao':1,'url':'https://github.com/o/r/issues/1',
            'executor':{'console':'codex','modelo':'modelo','execucao':'cloud'},
            'contexto_execucao':{'worktree':str(self.p),'branch':'work/teste'},
            'dependencias':{'verificadas_em':1,'itens':[]},
            'meta':{'limites':{'tempo_min':60,'tokens':2000000}}}
        self.token=self.ctrl.reservar('o/r','1','Dev','codex',self.pacote,quadro_atual=True)
        self.ctrl.transicao(self.token,'executando')
        self.tentativa=self.ctrl.iniciar_execucao(self.token)
        self.ctrl.terminar_execucao(self.tentativa,124,60)
        self.ctrl.transicao(self.token,'bloqueado')
        with closing(sqlite3.connect(self.ctrl.banco)) as db,db:
            db.execute('CREATE TABLE atividade_execucao (execucao TEXT,estado TEXT,codigo_console INTEGER)')
            db.execute('CREATE TABLE atividade_eventos (execucao TEXT,eventos_filhos INTEGER)')
            db.execute('INSERT INTO atividade_execucao VALUES (?,?,?)',(self.tentativa,'encerrado',0))
        self.reserva=self.ctrl.listar('o/r')[0]
        self.d={'id':'f'*32,'ativo':True,'repo':'o/r','politica':c.assinatura(self.cfg),
            'origem':'Usuário delegou decisões ao CEO/diretor','limites':{'tempo_min':60,'tokens':2000000},
            'prs':[{'pr':3,'cartao':1,'token':self.token,'head':'a'*40}]}
        self.e={'delegacao':self.d['id'],'pr':3,'cartao':1,'head':'a'*40,'token_anterior':self.token,
            'equipe':'Dev','limites':self.d['limites'],'reserva_sha256':c.assinatura(self.reserva),
            'pacote_sha256':c.identidade_pacote(self.pacote)}
        decisao={'estado':'decidido','evidencia':self.e,'ceo':{'acao':'corrigir','motivo':'corrigir achados'}}
        self.contrato={**self.e,'assinatura':c.assinatura(decisao),'ceo':decisao['ceo']}

    def contratar(self):
        return self.ctrl.contratar_correcao(self.reserva,{**self.pacote,'contrato_correcao':self.contrato},self.contrato)

    def gravar_delegacao(self):
        (self.p/'delegacao_correcoes.json').write_text(json.dumps(self.d),encoding='utf-8')

    def test_instalacao_existente_nao_habilita_correcao(self):
        self.assertIsNone(c.delegacao(self.p,self.cfg))
        self.gravar_delegacao();self.assertEqual(c.delegacao(self.p,self.cfg),self.d)

    def test_politica_e_orcamento_divergentes_nao_autorizam(self):
        self.d['limites']['tokens']=3000000;self.gravar_delegacao()
        with self.assertRaises(ValueError):c.delegacao(self.p,self.cfg)
        self.d['limites']['tokens']=2000000;self.d['politica']='b'*64;self.gravar_delegacao()
        with self.assertRaises(ValueError):c.delegacao(self.p,self.cfg)

    def test_prs_duplicados_rejeitados(self):
        self.d['prs']*=2;self.gravar_delegacao()
        with self.assertRaises(ValueError):c.delegacao(self.p,self.cfg)

    def meta_limite(self):
        (self.p/'metas').mkdir(exist_ok=True)
        r={'tentativa':self.tentativa,'meta':{'cartao':1,'limites':self.d['limites']},
           'estado':'limite_tokens','fim':1,'tokens_observados':2000020}
        (self.p/'metas'/(self.tentativa+'.json')).write_text(json.dumps(r),encoding='utf-8')
        return r

    def test_continuacao_opcional_exige_booleano_e_prova(self):
        self.d['continuar_limite']=True;self.gravar_delegacao();self.meta_limite()
        r=c.contexto_continuacao(self.p,self.cfg)
        self.assertEqual(r['prs'][0]['limite_confirmado']['tokens_observados'],2000020)
        self.assertEqual(r['limites']['tokens'],2000000)
        self.d['continuar_limite']='sim';self.gravar_delegacao()
        with self.assertRaises(ValueError):c.delegacao(self.p,self.cfg)

    def test_limite_sem_meta_de_outro_cartao_ou_retorno_nao_autoriza(self):
        with self.assertRaises(ValueError):c.limite_confirmado(self.p,self.d['prs'][0])
        r=self.meta_limite();r['meta']['cartao']=2
        (self.p/'metas'/(self.tentativa+'.json')).write_text(json.dumps(r),encoding='utf-8')
        with self.assertRaises(ValueError):c.limite_confirmado(self.p,self.d['prs'][0])
        self.meta_limite()
        with closing(sqlite3.connect(self.ctrl.banco)) as db,db:db.execute('UPDATE execucao_tarefa SET fim=NULL')
        with self.assertRaises(ValueError):c.limite_confirmado(self.p,self.d['prs'][0])

    def test_continuacao_usada_nao_renova_nem_consulta_chefe(self):
        self.d['continuar_limite']=True;self.gravar_delegacao();self.meta_limite();self.contratar()
        self.assertIsNone(c.contexto_continuacao(self.p,self.cfg))
        chefe=Mock();despacho=Mock()
        self.assertIsNone(c.encaminhar(self.p,self.cfg,[{'number':3}],
            {'encaminhamentos':[{'pr':3,'acao':'etapa'}]},self.p,Mock(),chamar=chefe,despachar=despacho))
        chefe.assert_not_called();despacho.assert_not_called()

    def test_diretor_pode_encaminhar_evidencias_sem_inventar_achado(self):
        self.d['continuar_limite']=True;self.gravar_delegacao()
        despacho=Mock(return_value={'codigo':0,'estado':'revisao'})
        with patch.object(c,'preparar',return_value=(self.e,(),self.reserva,self.p)):
            r=c.encaminhar(self.p,self.cfg,[{'number':3}],{'encaminhamentos':[{'pr':3,'acao':'etapa'}]},
                self.p,Mock(),chamar=lambda _:json.dumps({'acao':'corrigir','motivo':'completar evidências'}),despachar=despacho)
        self.assertEqual(r['pr'],3);despacho.assert_called_once()

    def test_grant_antigo_nao_despacha_etapa(self):
        self.gravar_delegacao();despacho=Mock()
        self.assertIsNone(c.encaminhar(self.p,self.cfg,[{'number':3}],
            {'encaminhamentos':[{'pr':3,'acao':'etapa'}]},self.p,Mock(),despachar=despacho))
        despacho.assert_not_called()

    def test_chefe_decide_proxima_concessao_sem_apagar_historico(self):
        self.d.update(continuar_limite=True,max_concessoes=2);self.gravar_delegacao()
        token=self.contratar();tentativa=self.ctrl.iniciar_execucao(token)
        self.ctrl.terminar_execucao(tentativa,124,30);self.ctrl.transicao(token,'bloqueado')
        with closing(sqlite3.connect(self.ctrl.banco)) as db,db:
            db.execute('INSERT INTO atividade_execucao VALUES (?,?,?)',(tentativa,'encerrado',124))
        self.tentativa=tentativa;self.meta_limite()
        with patch('gestao_cli.estado_git',return_value={'sha':'b'*40}):
            ds=c.pendentes(self.p,self.cfg)
            self.assertEqual(len(ds),1);self.assertNotEqual(ds[0]['id'],self.d['id'])
            self.assertEqual(ds[0]['prs'][0]['token'],token)
            self.assertEqual(ds[0]['prs'][0]['head'],'b'*40)
            self.assertEqual(ds[0]['rodada'],2);self.assertEqual(ds[0]['raiz'],self.d['id'])
            self.assertEqual(ds,c.pendentes(self.p,self.cfg))
            self.assertEqual(c.contexto_continuacao(self.p,self.cfg)['max_concessoes'],2)
            contrato={**self.contrato,'delegacao':ds[0]['id'],'head':'b'*40}
            self.assertEqual(c.conferir_concessao(self.p,self.cfg,contrato,{'token':token}),ds[0])
            with self.assertRaises(ValueError):
                c.conferir_concessao(self.p,self.cfg,{**contrato,'delegacao':self.d['id']},{'token':token})
            with self.assertRaises(ValueError):
                c.conferir_concessao(self.p,self.cfg,{**contrato,'head':'c'*40},{'token':token})
        with closing(sqlite3.connect(self.ctrl.banco)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM execucao_tarefa').fetchone()[0],2)
        self.d['max_concessoes']=1;self.gravar_delegacao()
        self.assertEqual(c.pendentes(self.p,self.cfg),[])

    def test_concessoes_exigem_teto_finito_e_nao_renovam_revisao(self):
        for valor in (0,6,True,'2'):
            self.d.update(continuar_limite=True,max_concessoes=valor);self.gravar_delegacao()
            with self.assertRaises(ValueError):c.delegacao(self.p,self.cfg)
        self.d.update(continuar_limite=False,max_concessoes=2);self.gravar_delegacao()
        with self.assertRaises(ValueError):c.delegacao(self.p,self.cfg)
        self.d.update(continuar_limite=True,max_concessoes=2);self.gravar_delegacao()
        token=self.contratar();tentativa=self.ctrl.iniciar_execucao(token)
        self.ctrl.terminar_execucao(tentativa,0,30);self.ctrl.transicao(token,'bloqueado')
        self.assertEqual(c.pendentes(self.p,self.cfg),[])

    def test_nova_concessao_nao_retoma_tentativa_ativa(self):
        self.d.update(continuar_limite=True,max_concessoes=2);self.gravar_delegacao()
        token=self.contratar();self.ctrl.iniciar_execucao(token);self.ctrl.transicao(token,'bloqueado')
        with self.assertRaisesRegex(ValueError,'incerta'):c.pendentes(self.p,self.cfg)

    def test_novo_contrato_arquiva_historico_sem_aprovar_entrega(self):
        token=self.contratar();self.assertNotEqual(token,self.token)
        self.assertEqual(self.ctrl.listar('o/r')[0]['estado'],'executando')
        with closing(sqlite3.connect(self.ctrl.banco)) as db:
            old=json.loads(db.execute('SELECT reserva_anterior FROM contrato_correcao').fetchone()[0])
            self.assertEqual(old,self.reserva)
            self.assertEqual(db.execute('SELECT codigo FROM execucao_tarefa WHERE token=?',(self.token,)).fetchone()[0],124)
            self.assertEqual(db.execute('SELECT pr,sha,aprovado FROM entrega WHERE token=?',(token,)).fetchone(),(3,'a'*40,0))
        self.assertTrue(c.utilizado(self.p,self.d,3))

    def test_segundo_claim_nao_renova_orcamento(self):
        self.contratar()
        with self.assertRaises(ValueError):self.contratar()

    def test_nova_consulta_de_dependencias_preserva_identidade(self):
        antes=c.identidade_pacote(self.pacote)
        self.pacote['dependencias']['verificadas_em']=2
        self.assertEqual(c.identidade_pacote(self.pacote),antes)
        self.assertIsNotNone(self.contratar())

    def test_dependencia_alterada_invalida_decisao(self):
        self.pacote['dependencias']['itens']=[{'numero':2,'estado':'bloqueado'}]
        with self.assertRaises(ValueError):self.contratar()

    def test_alterar_aceite_ou_orcamento_rejeitado(self):
        self.pacote['aceite']='outro'
        with self.assertRaises(ValueError):self.contratar()
        self.assertEqual(self.ctrl.listar('o/r')[0]['token'],self.token)

    def test_decisao_aguardar_nao_autoriza_claim(self):
        self.contrato['ceo']['acao']='aguardar'
        with self.assertRaises(ValueError):self.contratar()

    def test_sem_retorno_nao_contrata(self):
        with closing(sqlite3.connect(self.ctrl.banco)) as db,db:
            db.execute('UPDATE execucao_tarefa SET fim=NULL')
        with self.assertRaises(ValueError):self.contratar()

    def test_processo_incerto_ou_filhos_bloqueiam(self):
        with closing(sqlite3.connect(self.ctrl.banco)) as db,db:
            db.execute("UPDATE atividade_execucao SET estado='interrompido'")
        with self.assertRaises(ValueError):self.contratar()
        with closing(sqlite3.connect(self.ctrl.banco)) as db,db:
            db.execute("UPDATE atividade_execucao SET estado='encerrado'")
            db.execute('INSERT INTO atividade_eventos VALUES (?,1)',(self.tentativa,))
        with self.assertRaises(ValueError):self.contratar()

    def test_ceo_uma_consulta_por_evidencia_inalterada(self):
        chamada=Mock(return_value=json.dumps({'acao':'corrigir','motivo':'corrigir achados'}))
        a=c.decidir(self.p,self.cfg,self.e,self.p,chamada)
        b=c.decidir(self.p,self.cfg,self.e,self.p,chamada)
        self.assertEqual(a,b);chamada.assert_called_once()
        self.assertIn('Não mude aceite, gates',chamada.call_args.args[0])

    def test_resposta_invalida_ou_falha_nao_repetem_modelo(self):
        chamada=Mock(return_value='{"acao":"merge","motivo":"ignorar gates"}')
        with self.assertRaises(ValueError):c.decidir(self.p,self.cfg,self.e,self.p,chamada)
        with self.assertRaises(ValueError):c.decidir(self.p,self.cfg,self.e,self.p,chamada)
        chamada.assert_called_once()

    def test_sem_delegacao_nao_despacha(self):
        dispatcher=Mock()
        self.assertIsNone(c.encaminhar(self.p,self.cfg,[],{},self.p,Mock(),despachar=dispatcher))
        dispatcher.assert_not_called()

    def test_head_mudou_na_decisao_nao_despacha(self):
        self.gravar_delegacao();preparador=Mock(side_effect=[(self.e,(),self.reserva,self.p),
            ({**self.e,'head':'b'*40},(),self.reserva,self.p)])
        e={'pr':3,'acao':'correcao'};dispatcher=Mock()
        with patch.object(c,'preparar',preparador):
            with self.assertRaises(ValueError):c.encaminhar(self.p,self.cfg,[{'number':3}],
                {'encaminhamentos':[e]},self.p,Mock(),chamar=lambda _:json.dumps({'acao':'corrigir','motivo':'sim'}),
                despachar=dispatcher)
        dispatcher.assert_not_called()

    def test_encaminha_um_pr_por_rodada_no_despacho_comum(self):
        self.gravar_delegacao();dispatcher=Mock(return_value={'codigo':0,'estado':'revisao'})
        e={'pr':3,'acao':'correcao'}
        with patch.object(c,'preparar',return_value=(self.e,(),self.reserva,self.p)):
            r=c.encaminhar(self.p,self.cfg,[{'number':3}],{'encaminhamentos':[e]},self.p,Mock(),
                chamar=lambda _:json.dumps({'acao':'corrigir','motivo':'sim'}),despachar=dispatcher)
        self.assertEqual(r['pr'],3);dispatcher.assert_called_once()
        self.assertEqual(dispatcher.call_args.args[-1]['token_anterior'],self.token)
        self.assertNotIn('concluido',json.dumps(r))

    def test_mesa_trabalhando_somente_apos_tentativa_registrada(self):
        self.gravar_delegacao();etapas=[]
        def despacho(*args,**kw):
            self.assertEqual(etapas,['diretor','preparando'])
            kw['ao_execucao']('token','tentativa')
            self.assertEqual(etapas[-1],'implementando')
            return {'codigo':0,'estado':'revisao'}
        with patch.object(c,'preparar',return_value=(self.e,(),self.reserva,self.p)):
            c.encaminhar(self.p,self.cfg,[{'number':3}],{'encaminhamentos':[{'pr':3,'acao':'correcao'}]},
                self.p,Mock(),ao_etapa=lambda etapa,*a,**kw:etapas.append(etapa),
                chamar=lambda _:json.dumps({'acao':'corrigir','motivo':'sim'}),despachar=despacho)


if __name__=='__main__':unittest.main()
