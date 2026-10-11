"""Conferência por equipe: rede/modelos simulados, sem publicar ou aprovar gates."""
import copy,hashlib,json,sqlite3,sys,tempfile,time,unittest
from pathlib import Path
from contextlib import closing
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import conferencias_prs as c
from gestao_projeto import validar


class Conferencias(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.p=Path(self.tmp.name)
        self.cfg=validar({'ativo':True,'ciclo':{'ativo':True,'base':'origin/main'},'kanban':{'repo':'o/r'},
            'ceo':{'console':'codex'},'equipes':[{'nome':'Dev','especialidade':'Código','executor':{'console':'codex','modelo':'teste'}}]})
        self.pr={'number':3,'state':'open','draft':True,'title':'Conferir política','body':'Parte de #1','changed_files':1,
            'head':{'sha':'a'*40,'ref':'work/pr'},'base':{'sha':'b'*40,'ref':'main','repo':{'full_name':'o/r'}}}
        self.d={'pr':3,'head':'a'*40,'equipe':'Dev','acao':'revisar','objetivo':'Conferir bloqueio','aceite':'parecer verificável',
                'motivo':'Conferência necessária','evidencias_faltantes':'Resultado do gate'}
        self.docs=[{'tipo':'produto','caminho':'PRODUTO.md','sha256':'c'*64,'conteudo':'Objetivo e aceite'}]
        self.fs=[{'filename':'codigo.py','status':'modified','additions':1,'deletions':1,'patch':'@@ -1 +1 @@\n-velho\n+novo'}]
        self.rel={'resumo':'A alteração exige conferir a regra citada.','evidencias':['codigo.py: mudança observada no diff'],
            'pendencias':['Falta resultado do gate.'],'proxima_acao':'Conferir gate, sem retomar autor.'}
        self.k=Mock();self.comentarios=[];self.posts=[]
        self.k.chamar.side_effect=self.api;self.k._paginas.side_effect=self.paginas
        self.k.issue.return_value={'number':1,'title':'Tarefa','body':'Aceite completo','state':'open'}
        self.consultar=Mock(side_effect=lambda ex,texto,papel:{'acao':'conferir','motivo':'Conferência útil'} if papel=='ceo' else self.rel)
        for p in [patch('gestao_projeto.carregar',side_effect=lambda _:copy.deepcopy(self.cfg)),
                  patch('ciclo_gdd.documentos',side_effect=lambda *_:copy.deepcopy(self.docs))]:
            p.start();self.addCleanup(p.stop)
    def api(self,url,metodo='GET',dados=None):
        if url=='user':return {'login':'owner'}
        if url=='repos/o/r/pulls/3':return copy.deepcopy(self.pr)
        if metodo=='POST':
            self.posts.append((url,dados));r={'id':7,'body':dados['body'],'user':{'login':'owner'}}
            self.comentarios.append(r);return r
        return {'check_runs':[],'total_count':0}
    def paginas(self,url):
        if url.endswith('/files'):return copy.deepcopy(self.fs)
        if url.endswith('/comments'):return copy.deepcopy(self.comentarios)
        return []
    def executar(self):
        return c.encaminhar(self.p,self.cfg,[self.pr],{'encaminhamentos':[self.d]},self.docs,self.p,self.k,chamar=self.consultar)
    def recibo(self):return next((self.p/'conferencias_prs').glob('*.json'))

    def test_ceo_delega_para_equipe_e_publica_sem_gate_ou_conclusao(self):
        r=self.executar();self.assertEqual(r['estado'],'publicado')
        self.assertEqual([a.args[2] for a in self.consultar.call_args_list],['ceo','conferencia:Dev'])
        self.assertEqual(self.consultar.call_args_list[1].args[0],self.cfg['equipes'][0]['executor'])
        self.assertIn('não conclui cartão',self.posts[0][1]['body'])
        self.assertEqual([p[0] for p in self.posts],['repos/o/r/issues/3/comments'])
        self.assertFalse((self.p/'tarefas.db').exists());self.assertFalse((self.p/'revisoes').exists())
        self.assertEqual(c.contexto(self.p,[self.pr],self.cfg)[0]['parecer'],self.rel)
        self.assertIsNone(self.executar());self.assertEqual(self.consultar.call_count,2);self.assertEqual(len(self.posts),1)

    def test_adapter_real_inicializa_coletor_da_equipe_sem_inferencia(self):
        ex=self.cfg['equipes'][0]['executor']
        def chamar(executor,prompt,normalizador,ao_evento):
            ao_evento({'type':'turn.completed','usage':{'input_tokens':20,'output_tokens':5}})
            return normalizador(self.rel)
        with patch('banco.ARQ',self.p/'banco.db'),patch('revisores_console.chamar',side_effect=chamar):
            self.assertEqual(c.consultar(self.p,ex,'contexto',c.parecer,'conferencia:Dev'),self.rel)
        from consumo_providers import Registro
        g=Registro(self.p/'consumo_providers.db').resumo()['grupos'][0]
        self.assertEqual(g['agente'],'Conferência: Dev');self.assertEqual(g['total'],25)
        from consumo_coordenacao import ColetorIsolado
        with self.assertRaises(ValueError):ColetorIsolado(self.p/'uso.db',ex,self.p,'conferencia',equipe='inventada')
        with self.assertRaises(ValueError):ColetorIsolado(self.p/'uso.db',{**ex,'modelo':'outro'},self.p,'conferencia',equipe='Dev')

    def test_aguardar_nao_consulta_equipe_nem_repete_ceo(self):
        self.consultar.side_effect=lambda *_:{'acao':'aguardar','motivo':'Recurso indisponível'}
        self.assertIsNone(self.executar());self.assertIsNone(self.executar())
        self.consultar.assert_called_once();self.assertEqual(self.posts,[])
        self.assertEqual(c.contexto(self.p,[self.pr],self.cfg)[0]['estado'],'aguardando')

    def test_erro_ou_resposta_sem_evidencias_nao_publica_nem_reinicia(self):
        self.rel.pop('pendencias')
        with self.assertRaises(ValueError):self.executar()
        self.assertEqual(self.posts,[]);self.assertIsNone(self.executar());self.assertEqual(self.consultar.call_count,2)
        self.assertEqual(c.contexto(self.p,[self.pr],self.cfg)[0]['estado'],'conferindo')

    def test_mudanca_head_ou_aceite_impede_publicar(self):
        original=self.consultar.side_effect
        def chamar(ex,texto,papel):
            r=original(ex,texto,papel)
            if papel!='ceo':self.pr['head']['sha']='d'*40
            return r
        self.consultar.side_effect=chamar
        with self.assertRaisesRegex(ValueError,'Contexto mudou'):self.executar()
        self.assertEqual(self.posts,[])

    def test_autor_incerto_nao_consulta_modelos(self):
        with patch('fila_prs.autor_encerrado',return_value=False):self.assertIsNone(self.executar())
        self.consultar.assert_not_called();self.assertEqual(self.posts,[])

    def test_diff_incompleto_nao_e_truncado_nem_enviado_ao_modelo(self):
        self.fs[0]['additions']=2
        with self.assertRaisesRegex(ValueError,'Diff incompleto'):self.executar()
        self.consultar.assert_not_called();self.assertEqual(self.posts,[])

    def test_gate_envia_resultado_real_com_hash_e_rejeita_log_adulterado(self):
        pasta=self.p/'gates_projeto';pasta.mkdir();f=pasta/('f'*64+'.json');log=f.with_suffix('')/'stdout.txt'
        log.parent.mkdir();bruto=b'PermissionError: resource denied\n';log.write_bytes(bruto)
        r={'estado':'reprovado','evidencia':{'pr':3,'sha':'a'*40},
           'resultado':{'codigo':1,'inferencia':False,'stdout_sha256':hashlib.sha256(bruto).hexdigest()}}
        f.write_text(json.dumps(r),encoding='utf-8')
        self.executar();self.assertIn('PermissionError: resource denied',self.consultar.call_args.args[1])
        self.assertIn('"codigo": 1',self.consultar.call_args.args[1])
        log.write_bytes(b'alterado');self.cfg['metas']['tokens']=4000000
        with self.assertRaisesRegex(ValueError,'Log do gate diverge'):self.executar()
        self.assertEqual(self.consultar.call_count,2);self.assertEqual(len(self.posts),1)

    def test_filhos_incerto_impedem_conferencia(self):
        with closing(sqlite3.connect(self.p/'tarefas.db')) as db,db:
            db.execute('CREATE TABLE reserva (projeto TEXT,cartao TEXT,token TEXT)')
            db.execute('CREATE TABLE execucao_tarefa (id TEXT,token TEXT)')
            db.execute('CREATE TABLE atividade_eventos (execucao TEXT,eventos_filhos INTEGER)')
            db.execute("INSERT INTO reserva VALUES ('o/r','1','token')")
            db.execute("INSERT INTO execucao_tarefa VALUES ('tentativa','token')")
            db.execute("INSERT INTO atividade_eventos VALUES ('tentativa',1)")
        with patch('fila_prs.autor_encerrado',return_value=True):
            self.assertIsNone(self.executar())
        self.consultar.assert_not_called()

    def test_equipe_nao_cadastrada_ou_pr_fechado_nao_executa(self):
        self.d['equipe']='inventada';self.assertIsNone(self.executar())
        self.d['equipe']='Dev';self.pr['state']='closed';self.assertIsNone(self.executar())
        self.consultar.assert_not_called()

    def test_contexto_ignora_outro_head_e_politica(self):
        self.executar();self.pr['head']['sha']='d'*40
        self.assertEqual(c.contexto(self.p,[self.pr],self.cfg),[])
        self.pr['head']['sha']='a'*40;self.cfg['metas']['tokens']=4000000
        self.assertEqual(c.contexto(self.p,[self.pr],self.cfg),[])

    def test_confirmacao_perdida_recupera_comentario_sem_novo_post(self):
        self.executar();f=self.recibo();r=json.loads(f.read_text(encoding='utf-8'));r.pop('comentario');r['estado']='publicando'
        f.write_text(json.dumps(r),encoding='utf-8');self.consultar.reset_mock()
        self.assertEqual(self.executar()['estado'],'publicado');self.consultar.assert_not_called();self.assertEqual(len(self.posts),1)

    def test_comentario_de_outro_usuario_nao_comprova_publicacao(self):
        self.executar();f=self.recibo();r=json.loads(f.read_text(encoding='utf-8'));r['estado']='publicando'
        f.write_text(json.dumps(r),encoding='utf-8');self.comentarios[0]['user']['login']='outro'
        self.assertIsNone(self.executar());self.assertEqual(json.loads(f.read_text(encoding='utf-8'))['estado'],'publicando')
        self.assertEqual(len(self.posts),1)

    def test_inicializacao_rejeitada_concilia_sem_repetir_ceo_ou_retornar_sessao(self):
        original=self.consultar.side_effect
        def falhar(ex,texto,papel):
            if papel!='ceo':raise ValueError('Coletor exige papel cloud')
            return original(ex,texto,papel)
        self.consultar.side_effect=falhar
        with self.assertRaises(ValueError):self.executar()
        f=self.recibo();estado=self.p/'ciclo.json'
        estado.write_text(json.dumps({'id':'f'*32,'estado':'erro','motivo':'Coletor exige papel cloud',
            'inicio':time.time()-10,'atualizado':time.time()+10}),encoding='utf-8')
        with patch('gestao_cli.pasta_dados',return_value=self.p),patch('ciclo_gdd.caminho_estado',return_value=estado),\
             patch('ciclo_gdd.conferir_encerramento',return_value={'processos':[],'tentativas_pendentes':False}):
            self.assertEqual(c.conciliar_inicializacao(self.p,f.stem)['estado'],'pronto')
        self.consultar.reset_mock();self.consultar.side_effect=original
        self.assertEqual(self.executar()['estado'],'publicado')
        self.assertEqual(self.consultar.call_count,1);self.assertEqual(self.consultar.call_args.args[2],'conferencia:Dev')
        self.assertEqual(len(self.posts),1)
        self.assertEqual(len(list((f.parent/'historico').glob('*.json'))),1)

    def test_pronto_preserva_escopo_e_recupera_arquivo_do_ciclo_antigo(self):
        self.executar();f=self.recibo();r=json.loads(f.read_text(encoding='utf-8'))
        r['estado']='pronto';r.pop('parecer');r.pop('comentario');r.pop('corpo');r.pop('publicador')
        f.write_text(json.dumps(r),encoding='utf-8')
        self.assertEqual(c.fila_prontas(self.p,self.cfg,[self.pr],self.docs)['encaminhamentos'],[self.d])
        self.assertFalse(c.contexto(self.p,[self.pr],self.cfg)[0]['publicado_comprovado'])
        r.pop('encaminhamento');r['conciliacao_inicializacao']={'ciclo':'a'*32}
        f.write_text(json.dumps(r),encoding='utf-8');pasta=self.p/'ciclos';pasta.mkdir()
        bruto=json.dumps({'id':'a'*32,'encaminhamentos_prs':[self.d]}).encode('utf-8')
        arq=pasta/(hashlib.sha256(bruto).hexdigest()+'.json');arq.write_bytes(bruto)
        self.assertEqual(c.fila_prontas(self.p,self.cfg,[self.pr],self.docs)['encaminhamentos'],[self.d])
        arq.write_bytes(bruto+b' ')
        with self.assertRaisesRegex(ValueError,'hash'):c.fila_prontas(self.p,self.cfg,[self.pr],self.docs)

    def test_pronto_outro_head_politica_ou_sem_ceo_nao_e_despachavel(self):
        self.executar();f=self.recibo();r=json.loads(f.read_text(encoding='utf-8'));r['estado']='pronto'
        f.write_text(json.dumps(r),encoding='utf-8')
        self.pr['head']['sha']='f'*40
        # Head novo não deve enviar escopo antigo ao validador da fila.
        self.assertEqual(c.fila_prontas(self.p,self.cfg,[self.pr],self.docs)['encaminhamentos'],[])
        self.pr['head']['sha']='a'*40;r['ceo']['acao']='aguardar';f.write_text(json.dumps(r),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'CEO'):c.fila_prontas(self.p,self.cfg,[self.pr],self.docs)

    def test_nao_concilia_erro_de_modelo_ou_publicacao(self):
        self.executar();f=self.recibo();estado=self.p/'ciclo.json'
        estado.write_text(json.dumps({'estado':'erro','motivo':'Coletor exige papel cloud'}),encoding='utf-8')
        with patch('gestao_cli.pasta_dados',return_value=self.p),patch('ciclo_gdd.caminho_estado',return_value=estado):
            with self.assertRaises(ValueError):c.conciliar_inicializacao(self.p,f.stem)
        self.assertEqual(json.loads(f.read_text(encoding='utf-8'))['estado'],'publicado')


if __name__=='__main__':unittest.main()
