import json,sys,tempfile,unittest,sqlite3,hashlib,base64
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from fila_prs import validar,planejar,projetar,versao_politica,preparar_fila,autor_encerrado,contexto_preparacao
from gestao_projeto import validar as politica

class Fila(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.p=Path(self.tmp.name)
        self.cfg=politica({'kanban':{'repo':'o/r'},'equipes':[{'nome':'Dev','especialidade':'Código','executor':{'console':'codex'}}]})
        self.pr={'number':3,'state':'open','head':{'sha':'a'*40,'ref':'work/1'},'base':{'repo':{'full_name':'o/r'}},'body':'Parte de #1','draft':False}
        self.d={'pr':3,'head':'a'*40,'equipe':'Dev','acao':'etapa','motivo':'Validação prevista em etapa separada','objetivo':'medir mapa','aceite':'registro real das medições','evidencias_faltantes':'disponibilidade da bancada'}
        self.k=Mock();self.k.issue.return_value={'number':1,'body':'aceite original preservado'}
        self.k.chamar.return_value={'check_runs':[],'total_count':0};self.k._paginas.return_value=[]
    def test_classifica_uma_vez_por_contexto_sem_escrever_kanban(self):
        consultar=Mock(return_value=[self.d]);etapa=Mock()
        a=planejar(self.p,self.cfg,[self.pr],[],self.p,self.k,consultar,ao_consulta=etapa)
        b=planejar(self.p,self.cfg,[self.pr],[],self.p,self.k,consultar,ao_consulta=etapa)
        self.assertEqual(a,b);consultar.assert_called_once()
        self.assertTrue(all(len(chamada.args)==1 for chamada in self.k.chamar.call_args_list))
        etapa.assert_called_once()
        self.assertTrue(a['somente_preparacao']);self.assertIn('aceite original preservado',consultar.call_args.args[0])
        self.pr['head']['sha']='b'*40;self.d['head']='b'*40
        planejar(self.p,self.cfg,[self.pr],[],self.p,self.k,consultar);self.assertEqual(consultar.call_count,2)
    def revisao_fixture(self):
        from revisao_cruzada import assinatura
        pasta=self.p/'revisoes';pasta.mkdir(exist_ok=True)
        r={'sha':'a'*40,'politica':assinatura(self.cfg),'revisoes':[{'nome':'Revisor',
            'sha':'a'*40,'resposta':{'veredito':'reprovado','achados':[{
                'prioridade':'P1','arquivo':'src/world.py','linha':3,'evidencia':'Falta cobertura real da emissão.'}]}}]}
        arq=pasta/('a'*40+'.json');arq.write_text(json.dumps(r),encoding='utf-8')
        return arq,r

    def test_revisao_registrada_informa_diretor_e_mudanca_invalida_cache(self):
        arq,r=self.revisao_fixture();antes=arq.read_bytes();consultar=Mock(return_value=[self.d])
        planejar(self.p,self.cfg,[self.pr],[],self.p,self.k,consultar)
        texto=consultar.call_args.args[0]
        self.assertIn('Falta cobertura real da emissão.',texto)
        self.assertIn('"politica_revisao_compativel": true',texto)
        self.assertIn('"somente_contexto": true',texto)
        self.assertNotIn(str(self.p),texto);self.assertEqual(antes,arq.read_bytes())
        planejar(self.p,self.cfg,[self.pr],[],self.p,self.k,consultar);consultar.assert_called_once()
        r['revisoes'][0]['resposta']['achados'][0]['evidencia']='Nova evidência registrada'
        arq.write_text(json.dumps(r),encoding='utf-8')
        planejar(self.p,self.cfg,[self.pr],[],self.p,self.k,consultar)
        self.assertEqual(consultar.call_count,2)

    def test_revisao_antiga_incompativel_e_falha_nao_viram_aprovacao(self):
        from fila_prs import contexto_revisao
        arq,r=self.revisao_fixture();r['politica']='politica anterior'
        r['revisoes'][0]={'nome':'Revisor','sha':'a'*40,'erro':'credencial privada'}
        arq.write_text(json.dumps(r),encoding='utf-8')
        d=contexto_revisao(self.cfg,'a'*40,self.p)
        self.assertFalse(d['politica_revisao_compativel'])
        self.assertEqual(d['revisoes'][0]['estado'],'falha_console')
        self.assertNotIn('credencial privada',json.dumps(d));self.assertNotIn('aprovado',d)

    def test_revisao_de_outro_head_ou_grande_nao_chama_modelo(self):
        arq,r=self.revisao_fixture();r['sha']='b'*40
        arq.write_text(json.dumps(r),encoding='utf-8');consultar=Mock()
        with self.assertRaisesRegex(ValueError,'outro commit'):
            planejar(self.p,self.cfg,[self.pr],[],self.p,self.k,consultar)
        arq.write_text(' '*128001,encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'sem truncar'):
            planejar(self.p,self.cfg,[self.pr],[],self.p,self.k,consultar)
        consultar.assert_not_called()

    def test_caminho_de_revisao_exige_sha_completo(self):
        from fila_prs import contexto_revisao
        for sha in ('../outro','a'*39,'A'*40,None):
            with self.assertRaisesRegex(ValueError,'commit completo'):
                contexto_revisao(self.cfg,sha,self.p)

    def test_incerteza_nao_repete_chamada(self):
        consultar=Mock(side_effect=RuntimeError('conexão perdida'))
        with self.assertRaises(RuntimeError):planejar(self.p,self.cfg,[self.pr],[],self.p,self.k,consultar)
        with self.assertRaisesRegex(ValueError,'incerta'):planejar(self.p,self.cfg,[self.pr],[],self.p,self.k,consultar)
        consultar.assert_called_once()
    def test_decisao_omissa_head_divergente_e_equipe_inventada(self):
        for ds in ([],[{**self.d,'head':'b'*40}],[{**self.d,'equipe':'Inventada'}],[self.d,self.d]):
            with self.assertRaises(ValueError):validar(json.dumps({'encaminhamentos':ds}),[self.pr],self.cfg)
        self.assertEqual(validar(json.dumps({'encaminhamentos':[self.d]}),[self.pr],self.cfg),[self.d])
    def test_pr_de_outro_repo_nao_chama_diretor(self):
        self.pr['base']['repo']['full_name']='outro/repo';consultar=Mock()
        with self.assertRaises(ValueError):planejar(self.p,self.cfg,[self.pr],[],self.p,self.k,consultar)
        consultar.assert_not_called()
    def test_check_atual_entra_no_pacote_e_mudanca_reclassifica(self):
        run={'id':12,'name':'compilar','head_sha':'a'*40,'status':'completed','conclusion':'success','app':{'id':15368}}
        self.k.chamar.return_value={'check_runs':[run],'total_count':1};consultar=Mock(return_value=[self.d])
        planejar(self.p,self.cfg,[self.pr],[],self.p,self.k,consultar)
        self.assertIn('"estado": "success"',consultar.call_args.args[0])
        run['conclusion']='failure';planejar(self.p,self.cfg,[self.pr],[],self.p,self.k,consultar)
        self.assertEqual(consultar.call_count,2)

    def contexto_fixture(self):
        self.cfg['merge']['checks']=['ci']
        s={'titulo':'Preparação','equipe':'Dev','objetivo':'Investigar fase','aceite':'Registrar evidências','skills':'nenhuma'}
        ident={'repo':'o/r','pr':3,'head':'a'*40,'pai':1,'politica':versao_politica(self.cfg),'fontes':[]}
        for pasta,nome,d in [('preparacoes_prs','3',{'estado':'criado','numero':9,'identidade':ident,'proposta':s}),
            ('desbloqueios','1',{'estado':'criado','pai':1,'numero':9,'origem_pr':3,'proposta':s})]:
            p=self.p/pasta;p.mkdir();(p/(nome+'.json')).write_text(json.dumps(d),encoding='utf-8')
        self.filho={'number':9,'title':'Preparação','state':'closed','html_url':'https://github.com/o/r/issues/9',
                    'body':'**Objetivo:** Investigar fase\n\n**Aceite:** Registrar evidências\n\n'
                    '**Escopo:** Planejamento/investigação deste bloqueio; não implementar o pai.\n\n**Skills:** nenhuma'}
        self.futuro={'number':10,'title':'Validar fase','state':'open','html_url':'https://github.com/o/r/issues/10',
                     'body':'Depende da integração; medições ainda pendentes'}
        self.k.issue.side_effect=lambda n:{9:self.filho,10:self.futuro,1:{'number':1,'body':'aceite original preservado'}}[n]
        bruto=b'Investigacao versionada: montagem e benchmark ainda pendentes.'
        sha=hashlib.sha1(b'blob '+str(len(bruto)).encode()+b'\0'+bruto).hexdigest()
        self.artefato={'type':'file','path':'docs/preparacao.md','encoding':'base64','size':len(bruto),
                       'sha':sha,'content':base64.b64encode(bruto).decode()}
        self.k._paginas.side_effect=lambda url:([self.futuro] if '/sub_issues?' in url else
            [{'filename':'docs/preparacao.md','sha':sha,'status':'added'}] if '/pulls/11/files?' in url else [])
        self.k.chamar.side_effect=lambda url:self.artefato if '/contents/' in url else {'check_runs':[],'total_count':0}
        self.k.cartoes.return_value=[{'numero':10,'equipe':'Dev','status':'Backlog','prioridade':'P1','etapa':'L2'}]
        self.ev={'repo':'o/r','cartao':9,'pr':11,'head':'b'*40,'merge_commit':'c'*40,'merged_at':'2026-10-11T00:00:00Z',
                 'politica_sha256':versao_politica(self.cfg),'checks':{'gates':[{'nome':'ci','estado':'success'}]}}
        with closing(sqlite3.connect(self.p/'tarefas.db')) as db,db:
            db.execute('CREATE TABLE reserva (projeto TEXT,cartao TEXT,token TEXT,estado TEXT)')
            db.execute('CREATE TABLE conclusao (token TEXT,evidencia TEXT)')
            db.execute('INSERT INTO reserva VALUES (?,?,?,?)',('o/r','9','PRIVATE_TOKEN','concluido'))
            db.execute('INSERT INTO conclusao VALUES (?,?)',('PRIVATE_TOKEN',json.dumps(self.ev)))

    def test_preparacao_concluida_e_futuro_real_entram_no_diretor_sem_aprovar_pai(self):
        self.contexto_fixture();antes=(self.p/'tarefas.db').read_bytes();consultar=Mock(return_value=[self.d])
        planejar(self.p,self.cfg,[self.pr],[],self.p,self.k,consultar)
        texto=consultar.call_args.args[0]
        self.assertIn('"entrega_por_merge": {"pr": 11',texto)
        self.assertIn('medições ainda pendentes',texto)
        self.assertIn('"aceite": false',texto)
        self.assertIn('"prioridade": "P1"',texto)
        self.assertIn('Investigacao versionada: montagem e benchmark ainda pendentes.',texto)
        self.assertIn('"artefatos_versionados"',texto)
        self.assertNotIn('PRIVATE_TOKEN',texto);self.assertEqual(antes,(self.p/'tarefas.db').read_bytes())
        planejar(self.p,self.cfg,[self.pr],[],self.p,self.k,consultar);consultar.assert_called_once()
        self.futuro['body']='Aceite futuro alterado'
        planejar(self.p,self.cfg,[self.pr],[],self.p,self.k,consultar);self.assertEqual(consultar.call_count,2)

    def test_preparacao_bloqueada_nao_inventa_entrega_ou_atividade(self):
        self.contexto_fixture()
        with closing(sqlite3.connect(self.p/'tarefas.db')) as db,db:db.execute("UPDATE reserva SET estado='bloqueado'")
        r=contexto_preparacao(self.cfg,self.pr,[],self.p,self.k)
        self.assertEqual(r['preparacao']['reserva'],'bloqueado');self.assertIsNone(r['preparacao']['entrega_por_merge'])

    def test_prova_falha_head_mudado_e_issue_de_outro_repo_nao_sao_adotados(self):
        self.contexto_fixture();self.ev['checks']['gates'][0]['estado']='failure'
        with closing(sqlite3.connect(self.p/'tarefas.db')) as db,db:db.execute('UPDATE conclusao SET evidencia=?',(json.dumps(self.ev),))
        self.assertIsNone(contexto_preparacao(self.cfg,self.pr,[],self.p,self.k)['preparacao']['entrega_por_merge'])
        self.pr['head']['sha']='d'*40
        self.assertEqual(contexto_preparacao(self.cfg,self.pr,[],self.p,self.k)['estado'],'vinculo_desatualizado')
        self.pr['head']['sha']='a'*40;self.futuro['html_url']='https://github.com/outro/repo/issues/10'
        with self.assertRaisesRegex(ValueError,'outro repositório'):contexto_preparacao(self.cfg,self.pr,[],self.p,self.k)

    def test_subissues_excessivas_nao_sao_truncadas(self):
        self.contexto_fixture();original=self.k._paginas.side_effect
        self.k._paginas.side_effect=lambda url:[self.futuro]*21 if '/sub_issues?' in url else original(url)
        with self.assertRaisesRegex(ValueError,'sem truncar'):contexto_preparacao(self.cfg,self.pr,[],self.p,self.k)

    def test_artefato_versionado_adulterado_nao_e_evidencia(self):
        self.contexto_fixture();self.artefato['content']=base64.b64encode(b'Medicao inventada').decode()
        with self.assertRaisesRegex(ValueError,'divergente'):contexto_preparacao(self.cfg,self.pr,[],self.p,self.k)

    def test_projecao_exige_politica_head_e_equipe_sem_expor_recibo(self):
        estado={'fila_politica':versao_politica(self.cfg),'encaminhamentos_prs':[self.d],
                'pid':999,'segredo':'nao_expor'}
        arq=self.p/'ciclo.json'
        with patch('gestao_cli.pasta_dados',return_value=self.p):
            arq.write_text(json.dumps(estado),encoding='utf-8')
            r=projetar(self.p,self.cfg,[self.pr]);self.assertTrue(r[3]['somente_preparacao'])
            self.assertNotIn('segredo',json.dumps(r));self.assertNotIn('pid',json.dumps(r))
            self.assertEqual(projetar(self.p,self.cfg,[{**self.pr,'head':{'sha':'b'*40}}]),{})
            estado['fila_politica']='antiga';arq.write_text(json.dumps(estado),encoding='utf-8')
            self.assertEqual(projetar(self.p,self.cfg,[self.pr]),{})
            estado['fila_politica']=versao_politica(self.cfg)
            estado['encaminhamentos_prs']=[{**self.d,'equipe':'Inventada'}]
            arq.write_text(json.dumps(estado),encoding='utf-8')
            self.assertEqual(projetar(self.p,self.cfg,[self.pr]),{})
            arq.write_text('{quebrado',encoding='utf-8')
            self.assertEqual(projetar(self.p,self.cfg,[self.pr]),{})

    def preparar_fixture(self):
        self.cfg['ciclo']['criar_subtarefas']=True;self.cfg['kanban']['prioridades']=['P1']
        self.k.cartao.return_value={'numero':1,'equipe':'Dev','prioridade':'P1','status':'Em revisão'}
        self.k.issue.return_value={'number':1,'state':'open','html_url':'https://github.com/o/r/issues/1','body':'aceite do pai'}
        self.k.chamar.return_value=self.pr
        return {'titulo':'Formalizar etapa','equipe':'Dev','objetivo':'Planejar validação','aceite':'Documento vinculado ao pai e PR','skills':'nenhuma'}

    def test_preparacao_independente_usa_criador_com_origem_e_preserva_pai(self):
        s=self.preparar_fixture();consulta=Mock(return_value=json.dumps({'subtarefa':s}));criar=Mock(return_value=9)
        with patch('gestao_projeto.carregar',return_value=self.cfg):
            r=preparar_fila(self.p,self.cfg,[self.pr],{'encaminhamentos':[self.d]},[],self.p,self.k,criar,consulta)
        self.assertEqual(r['numero'],9);self.assertEqual(r['pr'],3)
        self.assertEqual(criar.call_args.kwargs,{'origem_pr':3})
        self.assertIsNone(criar.call_args.args[3]['objetivo_gdd'])
        self.assertIn('PR #3',criar.call_args.args[4]['subtarefa']['objetivo'])
        self.assertIn('não repita',consulta.call_args.args[0].lower())
        self.assertTrue(all(len(x.args)==1 for x in self.k.chamar.call_args_list))

    def test_preparacao_preserva_objetivo_do_pai_comprovado_pelo_gdd(self):
        s=self.preparar_fixture();self.cfg['kanban']['prioridades']=['P0'];self.k.cartao.return_value['prioridade']='P0'
        docs=[{'tipo':'produto','caminho':'PRODUTO.md','sha256':'a'*64,
               'conteudo':'#### Objetivo 1\n#1\n'}]
        criar=Mock(return_value=9)
        with patch('gestao_projeto.carregar',return_value=self.cfg):
            preparar_fila(self.p,self.cfg,[self.pr],{'encaminhamentos':[self.d]},docs,self.p,self.k,criar,
                         lambda _:json.dumps({'subtarefa':s}))
        self.assertEqual(criar.call_args.args[3]['objetivo_gdd'],1)

    def test_envelope_kanban_nao_duplica_preparacao_e_aceite_mudado_nao_e_adotado(self):
        s=self.preparar_fixture();pai=dict(self.k.issue.return_value);cartao=dict(self.k.cartao.return_value)
        consulta=Mock(return_value=json.dumps({'subtarefa':s}));criar=Mock(return_value=9)
        with patch('gestao_projeto.carregar',return_value=self.cfg):
            preparar_fila(self.p,self.cfg,[self.pr],{'encaminhamentos':[self.d]},[],self.p,self.k,criar,consulta)
        arquivo=self.p/'preparacoes_prs/3.json';r=json.loads(arquivo.read_text(encoding='utf-8'));s=r['proposta']
        r['assinatura']='versao-anterior';r['identidade']['cartao']['item']={'updated_at':'antigo'}
        arquivo.write_text(json.dumps(r),encoding='utf-8')
        recibos=self.p/'desbloqueios';recibos.mkdir()
        (recibos/'1.json').write_text(json.dumps({'estado':'criado','numero':9,'origem_pr':3,'proposta':s}),encoding='utf-8')
        filho={'title':s['titulo'],'state':'open','body':'\n\n'.join('**'+nome+':** '+valor for nome,valor in (
            ('Objetivo',s['objetivo']),('Aceite',s['aceite']),('Skills',s['skills']),
            ('Escopo','Planejamento/investigação deste bloqueio; não implementar o pai.')))}
        self.k.issue.side_effect=lambda n:pai if n==1 else filho
        self.k.cartao.side_effect=lambda n,**kw:{**cartao,'item':{'updated_at':'novo'}} if n==1 else {'equipe':'Dev','status':'Backlog','prioridade':'P1'}
        self.assertEqual(preparar_fila(self.p,self.cfg,[self.pr],{'encaminhamentos':[self.d]},[],self.p,self.k,criar,consulta)['numero'],9)
        consulta.assert_called_once();criar.assert_called_once()
        pai['body']='Aceite do pai mudou'
        self.assertIsNone(preparar_fila(self.p,self.cfg,[self.pr],{'encaminhamentos':[self.d]},[],self.p,self.k,criar,consulta))
        consulta.assert_called_once();criar.assert_called_once()

    def test_consulta_incerta_nao_cria_nem_repete_e_subissue_existente_impede(self):
        self.preparar_fixture();criar=Mock();consulta=Mock(side_effect=RuntimeError('rede'))
        with self.assertRaises(RuntimeError):preparar_fila(self.p,self.cfg,[self.pr],{'encaminhamentos':[self.d]},[],self.p,self.k,criar,consulta)
        with self.assertRaisesRegex(ValueError,'incerta'):preparar_fila(self.p,self.cfg,[self.pr],{'encaminhamentos':[self.d]},[],self.p,self.k,criar,consulta)
        consulta.assert_called_once();criar.assert_not_called()
        self.k._paginas.return_value=[{'state':'open'}]
        outra=self.p/'outra';outra.mkdir()
        self.assertIsNone(preparar_fila(self.p,self.cfg,[self.pr],{'encaminhamentos':[self.d]},[],outra,self.k,criar,consulta))
        consulta.assert_called_once()

    def test_preparacao_dispensada_nao_consulta_em_loop(self):
        self.preparar_fixture();consulta=Mock(return_value='{"subtarefa":null}');criar=Mock()
        for _ in range(2):
            self.assertIsNone(preparar_fila(self.p,self.cfg,[self.pr],{'encaminhamentos':[self.d]},[],self.p,self.k,criar,consulta))
        consulta.assert_called_once();criar.assert_not_called()

    def test_autor_incerto_e_head_mudado_nao_criam_preparacao(self):
        s=self.preparar_fixture();consulta=Mock(return_value=json.dumps({'subtarefa':s}));criar=Mock()
        with patch('fila_prs.autor_encerrado',return_value=False):
            self.assertIsNone(preparar_fila(self.p,self.cfg,[self.pr],{'encaminhamentos':[self.d]},[],self.p,self.k,criar,consulta))
        consulta.assert_not_called();criar.assert_not_called()
        self.k.chamar.return_value={**self.pr,'head':{'sha':'b'*40}}
        with patch('gestao_projeto.carregar',return_value=self.cfg):
            with self.assertRaisesRegex(ValueError,'mudou'):preparar_fila(self.p,self.cfg,[self.pr],{'encaminhamentos':[self.d]},[],self.p,self.k,criar,consulta)
        criar.assert_not_called()

    def test_equipes_inventadas_nao_criam_cartao(self):
        s=self.preparar_fixture();s['equipe']='Inventada';criar=Mock()
        with self.assertRaisesRegex(ValueError,'inválidos'):
            preparar_fila(self.p,self.cfg,[self.pr],{'encaminhamentos':[self.d]},[],self.p,self.k,criar,lambda _:json.dumps({'subtarefa':s}))
        criar.assert_not_called()

    def test_autor_sem_retorno_ou_atividade_encerrada_nao_libera_preparacao(self):
        import sqlite3
        from contextlib import closing
        with closing(sqlite3.connect(self.p/'tarefas.db')) as db,db:
            db.executescript('CREATE TABLE reserva(projeto,cartao,token,estado);CREATE TABLE execucao_tarefa(id,token,fim,codigo);CREATE TABLE atividade_execucao(execucao,estado,codigo_console);')
            db.execute('INSERT INTO reserva VALUES (?,?,?,?)',('o/r','1','token','bloqueado'))
            db.execute('INSERT INTO execucao_tarefa VALUES (?,?,?,?)',('a','token',None,None))
        self.assertFalse(autor_encerrado(self.p,'o/r',1))
        with closing(sqlite3.connect(self.p/'tarefas.db')) as db,db:
            db.execute('UPDATE execucao_tarefa SET fim=1,codigo=124')
        self.assertFalse(autor_encerrado(self.p,'o/r',1))
        with closing(sqlite3.connect(self.p/'tarefas.db')) as db,db:
            db.execute('INSERT INTO atividade_execucao VALUES (?,?,?)',('a','encerrado',124))
        self.assertTrue(autor_encerrado(self.p,'o/r',1))

if __name__=='__main__':unittest.main()
