"""Gate autorizado: Git/SQLite reais, rede/consoles simulados, sem publicação real."""
import copy,json,sqlite3,sys,tomllib,unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import testar_revisao_execucao as fixtures
import gates_projeto as g,gestao_cli,revisao_execucao,gestao_projeto
from controle_tarefas import Controle


class Gates(unittest.TestCase):
    def setUp(self):
        fixtures.Execucao.setUp(self)
        self.script='.claude/skills/guardian/scripts/review_pr.py'
        for root in (self.repo,self.trabalho):
            p=root/self.script;p.parent.mkdir(parents=True);p.write_text('print("gate")\n',encoding='utf-8')
            (root/'CLAUDE.md').write_text('python '+self.script+' --pr <n> --publish',encoding='utf-8')
        self.git('add','.');self.git('commit','-m','Script autorizado');self.base=self.git('rev-parse','HEAD')
        self.git('update-ref','refs/remotes/origin/main',self.base)
        (self.trabalho/'codigo.py').write_text('valor = 3\n',encoding='utf-8')
        self.git('add','.');self.git('commit','-m','Entrega')
        self.cfg.update(ciclo={'ativo':True,'base':'origin/main'},kanban={'repo':'owner/repo'},
                        merge={'checks':['revisor-ia',g.CHECK]})
        (self.repo/'.office/projeto.json').write_text(json.dumps(self.cfg),encoding='utf-8')
        self.cfg=gestao_projeto.carregar(self.repo)
        self.rel=revisao_execucao.executar(self.repo,self.trabalho,self.base,'Dev','Aceite',
            chamar=lambda *_:{'veredito':'aprovado','achados':[]})
        self.dados=gestao_cli.pasta_dados(self.repo);self.ctrl=Controle(self.dados/'tarefas.db')
        pacote={'objetivo':'Entrega','aceite':'Aceite','executor':gestao_projeto.executor(self.cfg,equipe='Dev',escopo='implementacao'),
                'fontes_resolvidas':gestao_projeto.fontes_resolvidas(self.repo,self.cfg),
                'contexto_execucao':{'worktree':str(self.trabalho.resolve()),'branch':'feat/trabalho',
                                    'politica_sha256':g.assinatura(self.cfg)}}
        self.token=self.ctrl.reservar('owner/repo','1','Dev','gemini',pacote,True)
        self.ctrl.transicao(self.token,'executando');self.t=self.ctrl.iniciar_execucao(self.token)
        self.ctrl.terminar_execucao(self.t,0,1);self.ctrl.transicao(self.token,'revisao')
        with closing(sqlite3.connect(self.ctrl.banco)) as db,db:
            db.execute('INSERT INTO entrega VALUES (?,?,?,?,?,?)',(self.token,self.rel['sha'],42,1,json.dumps(self.rel),1))
            db.execute('CREATE TABLE atividade_execucao(execucao TEXT,estado TEXT,codigo_console INTEGER)')
            db.execute('CREATE TABLE atividade_eventos(execucao TEXT,eventos_filhos INTEGER)')
            db.execute('INSERT INTO atividade_execucao VALUES (?,?,?)',(self.t,'encerrado',0))
            db.execute('INSERT INTO atividade_eventos VALUES (?,0)',(self.t,))
        criados=gestao_cli.RAIZ/'dados/worktrees';criados.mkdir(parents=True)
        (criados/'criado.json').write_text(json.dumps({'estado':'criado','projeto':str(self.repo.resolve()),
            'criados':[{'cartao':1,'worktree':str(self.trabalho.resolve()),'branch':'feat/trabalho'}]}),encoding='utf-8')
        self.pr={'number':42,'state':'open','draft':False,'body':'Closes #1','labels':[],
                 'head':{'sha':self.rel['sha'],'ref':'feat/trabalho','repo':{'full_name':'owner/repo'}},
                 'base':{'sha':self.base,'ref':'main','repo':{'full_name':'owner/repo'}}}
        self.k=Mock();self.remote_base=self.base
        self.k.chamar.side_effect=lambda url:({'object':{'sha':self.remote_base}} if '/git/ref/' in url else copy.deepcopy(self.pr))
        self.statuses=[];self.k._paginas.side_effect=lambda _:copy.deepcopy(self.statuses)
        self.patches=[patch('gates_projeto.sys.platform','win32'),
                      patch('fila_prs.checks_atuais',return_value={'gates':[{'nome':g.CHECK,'estado':'missing'}]})]
        for p in self.patches:p.start();self.addCleanup(p.stop)
        self.fila={'encaminhamentos':[{'pr':42,'head':self.rel['sha'],'acao':'revisar'}]}
    def preparar(self):return g.preparar(self.repo,self.cfg,self.pr,self.dados,self.k)
    def encaminhar(self,chamar=None,rodar=None):
        return g.encaminhar(self.repo,self.cfg,[self.pr],self.fila,self.dados,self.k,
            chamar=chamar or (lambda _:json.dumps({'acao':'executar','motivo':'gate autorizado'})),rodar=rodar or self.rodar)
    def rodar(self,e,pasta,ao_processo):
        ao_processo(123);self.statuses=[{'id':1,'context':g.CHECK,'state':'success'}]
        return {'codigo':0,'pid':123,'inferencia':False}
    def test_elegibilidade_readonly_revisor_cadastrado(self):
        before=self.ctrl.banco.read_bytes();e=self.preparar()
        self.assertEqual(e['revisor']['nome'],'QA Codex');self.assertEqual(e['regra']['script'],self.script)
        self.assertEqual(before,self.ctrl.banco.read_bytes())

    def test_metas_novas_bloqueiam_gate_antigo_sem_parar_fila(self):
        self.cfg['metas'].update(tempo_min=120,tokens=4000000)
        antes=self.ctrl.banco.read_bytes();pendencias=[]
        with self.assertRaises(g.ContextoIncompativel):self.preparar()
        self.assertEqual(g.candidatos(self.repo,self.cfg,[self.pr],self.dados,self.k,pendencias=pendencias),[])
        self.assertEqual(pendencias[0]['pr'],42)
        self.assertIn('política',pendencias[0]['motivo'])
        chefe=Mock();worker=Mock();self.assertIsNone(self.encaminhar(chefe,worker))
        chefe.assert_not_called();worker.assert_not_called()
        self.assertEqual(self.ctrl.banco.read_bytes(),antes)
    def test_conciliacao_de_orcamento_exige_ceo_e_preserva_reserva(self):
        antigos={k:self.cfg['metas'][k] for k in ('tempo_min','tokens')}
        with closing(sqlite3.connect(self.ctrl.banco)) as db,db:
            pacote=json.loads(db.execute('SELECT pacote FROM reserva WHERE token=?',(self.token,)).fetchone()[0])
            pacote['meta']={'limites':antigos}
            db.execute('UPDATE reserva SET pacote=? WHERE token=?',(json.dumps(pacote),self.token))
        self.cfg['metas'].update(tempo_min=240,tokens=10000000)
        (self.repo/'.office/projeto.json').write_text(json.dumps(self.cfg),encoding='utf-8')
        before=self.ctrl.banco.read_bytes();e=self.preparar()
        self.assertEqual(e['conciliacao_orcamento']['limites_originais'],antigos)
        chefe=Mock(return_value=json.dumps({'acao':'aguardar','motivo':'conferir ambiente'}));worker=Mock()
        self.assertIsNone(self.encaminhar(chefe,worker));chefe.assert_called_once();worker.assert_not_called()
        self.assertEqual(before,self.ctrl.banco.read_bytes())
        self.cfg['merge']['checks'].append('outro-check')
        with self.assertRaisesRegex(g.ContextoIncompativel,'além'):self.preparar()

    def test_diretor_recebe_gate_registrado_em_vez_de_candidato_repetido(self):
        e=self.preparar();pasta=self.dados/'gates_projeto';pasta.mkdir()
        arq=pasta/(g.assinatura(e)+'.json')
        for estado in ('reprovado','aguardando','executando','consultando','publicado'):
            r={'estado':estado,'evidencia':e,'resultado':{'codigo':1,'inferencia':False}}
            arq.write_text(json.dumps(r),encoding='utf-8');antes=arq.read_bytes();pendencias=[]
            self.assertEqual(g.candidatos(self.repo,self.cfg,[self.pr],self.dados,self.k,pendencias=pendencias),[])
            self.assertEqual(pendencias[0]['estado'],estado)
            self.assertEqual(pendencias[0]['recibo_sha256'],g.assinatura(r))
            self.assertEqual(arq.read_bytes(),antes)
        r['evidencia']={};arq.write_text(json.dumps(r),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'identidade'):
            g.candidatos(self.repo,self.cfg,[self.pr],self.dados,self.k)

    def test_publicacao_nao_reinicia_autor_e_nao_repete(self):
        before=self.ctrl.banco.read_bytes();r=self.encaminhar()
        self.assertEqual(r['estado'],'publicado');self.assertFalse(r['inferencia'])
        self.assertEqual(before,self.ctrl.banco.read_bytes())
        chef=Mock();worker=Mock();self.assertIsNone(self.encaminhar(chef,worker));chef.assert_not_called();worker.assert_not_called()
    def test_aguardar_nao_repete_consulta(self):
        chef=Mock(return_value=json.dumps({'acao':'aguardar','motivo':'recurso indisponível'}));worker=Mock()
        self.assertIsNone(self.encaminhar(chef,worker));self.assertIsNone(self.encaminhar(chef,worker))
        chef.assert_called_once();worker.assert_not_called()
    def test_failure_e_publicacao_real_reprovada(self):
        def worker(e,pasta,ao_processo):
            ao_processo(124);self.statuses=[{'id':2,'context':g.CHECK,'state':'failure'}];return {'codigo':1}
        self.assertEqual(self.encaminhar(rodar=worker)['estado'],'reprovado')
    def test_status_antigo_nao_comprova_execucao(self):
        self.statuses=[{'id':1,'context':g.CHECK,'state':'success'}]
        with self.assertRaisesRegex(ValueError,'comprovou'):self.encaminhar()
        with self.assertRaisesRegex(ValueError,'incerto'):self.encaminhar()
    def test_manual_rascunho_e_plataforma_sem_adapter(self):
        for changes in ({'draft':True},{'labels':[{'name':'merge-manual'}]},{'state':'closed'}):
            original=copy.deepcopy(self.pr);self.pr.update(changes);self.assertIsNone(self.preparar());self.pr=original
        with patch('gates_projeto.sys.platform','linux'):self.assertIsNone(self.preparar())
    def test_filhos_incerto_e_script_alterado_nao_executam(self):
        with closing(sqlite3.connect(self.ctrl.banco)) as db,db:db.execute('UPDATE atividade_eventos SET eventos_filhos=1')
        with self.assertRaisesRegex(ValueError,'filhos'):self.preparar()
        with closing(sqlite3.connect(self.ctrl.banco)) as db,db:db.execute('UPDATE atividade_eventos SET eventos_filhos=0')
        (self.trabalho/self.script).write_text('print("alterado")\n',encoding='utf-8')
        with self.assertRaises(ValueError):self.preparar()
    def test_ceo_mudanca_head_impede_worker(self):
        def chef(_):self.pr['head']['sha']='a'*40;return json.dumps({'acao':'executar','motivo':'sim'})
        worker=Mock()
        with self.assertRaises(ValueError):self.encaminhar(chef,worker)
        worker.assert_not_called()
    def test_merge_confirmado_durante_publicacao_nao_e_execucao_incerta(self):
        def worker(e,pasta,ao_processo):
            r=self.rodar(e,pasta,ao_processo)
            self.pr.update(state='closed',merged=True,merged_at='2026-10-11T20:00:00Z',merge_commit_sha='b'*40)
            self.pr['base']['sha']='b'*40
            self.remote_base='b'*40
            return r
        self.assertEqual(self.encaminhar(rodar=worker)['estado'],'publicado')
    def test_base_mudou_sem_merge_confirmado_nao_adota(self):
        def worker(e,pasta,ao_processo):
            r=self.rodar(e,pasta,ao_processo);self.pr['base']['sha']='b'*40;return r
        with self.assertRaisesRegex(ValueError,'Contexto mudou'):self.encaminhar(rodar=worker)
    def test_script_sem_autorizacao_ou_ambiguo(self):
        (self.repo/'CLAUDE.md').write_text('Sem comando autorizado',encoding='utf-8')
        self.assertIsNone(g.comando_script(self.repo,self.cfg))
        (self.repo/'CLAUDE.md').write_text('python '+self.script+' --pr <n> --publish\npython .agents/skills/a/scripts/review_pr.py --pr <n> --publish',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'ambíguos'):g.comando_script(self.repo,self.cfg)
    def test_ref_da_base_deve_corresponder_ao_sha_remoto(self):
        self.git('update-ref','refs/remotes/origin/main',self.rel['sha'])
        with self.assertRaisesRegex(g.ContextoIncompativel,'Base local'):self.preparar()
    def test_sincronizacao_restrita_confere_origem_e_sha_sem_checkout(self):
        import subprocess
        chamadas=[]
        def run(args,**kwargs):
            cmd=args[3:];chamadas.append(cmd)
            out=('https://github.com/owner/repo.git' if cmd[:2]==['remote','get-url'] else
                 self.base+'\trefs/heads/main' if cmd[0]=='ls-remote' else
                 'commit' if cmd[0]=='cat-file' else '')
            return subprocess.CompletedProcess(args,0,out,'')
        with patch('gates_projeto.subprocess.run',side_effect=run):
            g.sincronizar_base(self.trabalho,'owner/repo','origin/main',self.base,'a'*40)
        self.assertEqual(chamadas[-1],['update-ref','refs/remotes/origin/main',self.base,'a'*40])
        self.assertEqual([c[0] for c in chamadas].count('fetch'),1)
        self.assertFalse(any(c[0] in ('checkout','reset','merge') for c in chamadas))
        with patch('gates_projeto.subprocess.run',return_value=subprocess.CompletedProcess([],0,'https://example.com/repo','')):
            with self.assertRaisesRegex(ValueError,'Origin'):g.sincronizar_base(self.trabalho,'owner/repo','origin/main',self.base,'a'*40)

    def test_sincronizacao_git_real_preserva_checkout_e_rejeita_ref_concorrente(self):
        import subprocess
        run_real=subprocess.run
        remoto=self.repo.parent/'remoto-gate.git'
        run_real(['git','clone','--bare',str(self.trabalho),str(remoto)],capture_output=True,check=True)
        run_real(['git','--git-dir',str(remoto),'update-ref','refs/heads/main',self.rel['sha']],check=True)
        url='https://github.com/owner/repo.git'
        def run(args,**kwargs):
            if args[3:]==['remote','get-url','origin']:return subprocess.CompletedProcess(args,0,url,'')
            return run_real([str(remoto) if a==url else a for a in args],**kwargs)
        before=gestao_cli.estado_git(self.trabalho)
        with patch('gates_projeto.subprocess.run',side_effect=run):
            g.sincronizar_base(self.trabalho,'owner/repo','origin/main',self.rel['sha'],self.base)
            with self.assertRaises(subprocess.CalledProcessError):
                g.sincronizar_base(self.trabalho,'owner/repo','origin/main',self.rel['sha'],self.base)
            with self.assertRaisesRegex(ValueError,'antes'):
                g.sincronizar_base(self.trabalho,'owner/repo','origin/main',self.base,self.rel['sha'])
        self.assertEqual(gestao_cli.estado_git(self.trabalho),before)
        self.assertEqual(self.git('rev-parse','origin/main'),self.rel['sha'])

    def test_snapshot_antigo_do_pr_nao_substitui_referencia_atual(self):
        self.pr['base']['sha']='a'*40
        e=self.preparar();self.assertEqual(e['base'],self.base);self.assertEqual(e['base_pr'],'a'*40)
    def test_comando_nativo_fixo_perfil_restrito_sem_inferencia(self):
        import subprocess
        e=self.preparar();pasta=self.dados/'logs';pasta.mkdir()
        process=Mock();process.pid=99;process.returncode=0;process.communicate.return_value=(b'gate',b'')
        process.__enter__=Mock(return_value=process);process.__exit__=Mock(return_value=False)
        def run(args,**kwargs):
            if '--help' in args:return subprocess.CompletedProcess(args,0,'--permission-profile','')
            return subprocess.CompletedProcess(args,0,str(self.repo/'.git'),'')
        with (patch('providers_console.selecionar',return_value=(Mock(nome='codex'),'codex.exe')),
              patch('providers_console.comando_nativo',return_value=['codex.exe']),
              patch('gates_projeto.subprocess.run',side_effect=run),
              patch('gates_projeto.subprocess.Popen',return_value=process) as popen,
              patch('gates_projeto.subprocess.CREATE_NO_WINDOW',0,create=True)):
            cb=Mock();r=g.executar(e,pasta,cb)
        args=popen.call_args.args[0];cb.assert_called_once_with(99)
        ambiente=popen.call_args.kwargs['env']
        for chave in ('TMP','TEMP','TMPDIR'):
            self.assertEqual(Path(ambiente[chave]),pasta.resolve()/'tmp')
            self.assertTrue(Path(ambiente[chave]).is_dir())
        self.assertEqual(args[:4],['codex.exe','sandbox','--permission-profile','office-gate'])
        override=next(a for a in args if a.startswith('permissions='))
        profile=tomllib.loads(override)['permissions']['office-gate']
        self.assertEqual(profile['extends'],':workspace')
        self.assertEqual(profile['filesystem'],{pasta.resolve().as_posix():'write'})
        self.assertEqual(profile['network']['domains'],{'api.github.com':'allow','github.com':'allow'})
        self.assertIn('features.network_proxy=true',args)
        self.assertEqual(args[args.index('--')+1:],[sys.executable,str(self.trabalho/self.script),
            '--base','origin/main','--pr','42','--publish'])
        self.assertFalse(r['inferencia']);self.assertNotIn('danger-full-access',' '.join(args))


if __name__=='__main__':unittest.main()
