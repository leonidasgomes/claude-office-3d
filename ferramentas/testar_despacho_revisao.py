"""Entrega no Kanban exige aprovação independente do head/base exatos, sem merge."""
import copy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import gestao_cli as gc
from controle_tarefas import Controle
from gestao_projeto import validar
from providers_console import PROVIDERS
from revisao_cruzada import revisar


class DespachoRevisao(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.pasta=Path(self.tmp.name); (self.pasta/'.office').mkdir()
        self.cfg=validar({'ativo':True,'kanban':{'repo':'owner/repo'},
            'equipes':[{'nome':'Dev','especialidade':'Código','executor':{'console':'gemini'}}],
            'revisao':{'ativo':True,'revisores':[{'nome':'QA1','executor':{'console':'claude'}},
                                               {'nome':'QA2','executor':{'console':'codex'}}]}})
        (self.pasta/'.office/projeto.json').write_text(json.dumps(self.cfg),encoding='utf-8')
        self.sha='a'*40; self.base='b'*40; self.status='Backlog'; self.moves=[]; self.calls=0
        self.pr={'number':12,'head':{'sha':self.sha},'base':{'sha':self.base}}
        self.k=SimpleNamespace(cartao=lambda *a,**kw:{'status':self.status,'equipe':'Dev'},
            cfg=self.cfg['kanban'],bloqueadores=lambda _:[],
            issue=lambda *_:{'state':'open','title':'Tarefa','body':'**Aceite:** Deve passar'},
            mover=self.mover,entrega=lambda *_:copy.deepcopy(self.pr))
        self.db=self.pasta/'tarefas.db'

    def mover(self, numero, status): self.status=status; self.moves.append(status)

    def executar(self, callback, funcionario=None, rodar=None):
        def git(pasta,*args):
            if args[0]=='rev-parse': return self.sha
            if args[0]=='branch': return 'feat/tarefa'
            if args[0]=='status': return ''
            raise AssertionError(args)
        with patch('gestao_cli.selecionar',return_value=(PROVIDERS[self.cfg['equipes'][0]['executor']['console']],'native')), \
             patch('gestao_cli.validar_worktree',return_value=self.pasta), \
             patch('gestao_cli.subprocess.run',return_value=SimpleNamespace(stdout='feat/tarefa')), \
             patch('revisao_execucao.git',side_effect=git):
            return gc.despachar(self.pasta,42,'Dev','implementacao',self.pasta,banco=self.db,
                                kanban=self.k,rodar=rodar or (lambda *a,**kw:0),revisar=callback,funcionario=funcionario,
                                banco_execucoes=self.pasta/'execucoes.db')

    def relatorio(self, aprovado=True):
        return revisar(self.cfg,self.cfg['equipes'][0]['executor'],self.sha,'diff','Deve passar','regras',
                       lambda *_:{'veredito':'aprovado' if aprovado else 'reprovado','achados':[]})

    def test_despacho_transmite_sandbox_configurado_ao_executor(self):
        self.cfg['equipes'][0]['executor']={'console':'codex','modelo':'modelo','sandbox':'workspace-write'}
        self.cfg['revisao']['revisores']=[{'nome':'QA1','executor':{'console':'claude'}},
                                        {'nome':'QA2','executor':{'console':'gemini'}}]
        (self.pasta/'.office/projeto.json').write_text(json.dumps(self.cfg),encoding='utf-8')
        recebidos=[]
        def rodar(*args,**kwargs):
            recebidos.append(kwargs.get('sandbox'))
            return 0
        self.executar(lambda *a,**kw:self.relatorio(),rodar=rodar)
        self.assertEqual(recebidos,['workspace-write'])

    def test_revisor_desativado_bloqueia_antes_de_reservar_mover_ou_inferir(self):
        self.cfg['revisao']['revisores'][0]['ativo']=False
        (self.pasta/'.office/projeto.json').write_text(json.dumps(self.cfg),encoding='utf-8')
        chamadas=[]
        with self.assertRaisesRegex(ValueError,'revisores suficientes'):
            self.executar(lambda *a,**kw:chamadas.append('revisor'),rodar=lambda *a,**kw:chamadas.append('autor'))
        self.assertEqual(chamadas,[])
        self.assertEqual(self.moves,[])
        self.assertFalse(self.db.exists())

    def test_erro_novos_consoles_com_exit_zero_bloqueia_kanban_e_revisao(self):
        import console_provider,contextlib,io
        self.cfg['revisao']['ativo']=False
        for nome in ('codex','opencode','gemini'):
            with self.subTest(console=nome):
                self.status='Backlog';self.moves=[]
                self.cfg['equipes'][0]['executor']={'console':nome,'modelo':'opencode/space-bunny-free' if nome=='opencode' else ''}
                (self.pasta/'.office/projeto.json').write_text(json.dumps(self.cfg),encoding='utf-8')
                fake=self.pasta/'fake.py'
                fake.write_text('import json\nprint(json.dumps({"type":"error"}))\n',encoding='utf-8')
                revisoes=[]
                def rodar(*args,**kwargs):
                    return console_provider.executar(*args,**kwargs,banco=self.pasta/'eventos.db')
                with patch('providers_console.comando_nativo',return_value=[sys.executable,str(fake)]),contextlib.redirect_stdout(io.StringIO()):
                    r=self.executar(lambda *a,**kw:revisoes.append(1),rodar=rodar)
                self.assertEqual((r['codigo'],r['estado']),(1,'bloqueado'))
                self.assertEqual(self.moves,['Em andamento']);self.assertEqual(revisoes,[])
                self.assertIsNone(Controle(self.db).revisao(r['token']))
                Controle(self.db).transicao(r['token'],'cancelado')

    def test_erro_claude_com_exit_zero_bloqueia_cartao_sem_revisar_ou_entregar(self):
        import console_provider
        import contextlib,io
        self.cfg['equipes'][0]['executor']['console']='claude'
        self.cfg['revisao']['revisores'][0]['executor']['console']='gemini'
        (self.pasta/'.office/projeto.json').write_text(json.dumps(self.cfg),encoding='utf-8')
        fake=self.pasta/'fake.py'
        fake.write_text('''import sys,json,os
sys.stdin.read()
s=os.environ['OFFICE_CLAUDE_STREAM_SESSION']
print(json.dumps({'type':'system','subtype':'init','session_id':s}),flush=True)
print(json.dumps({'type':'result','session_id':s,'is_error':True}),flush=True)
''',encoding='utf-8')
        revisoes=[]
        def rodar(*args,**kwargs):
            return console_provider.executar(*args,**kwargs,banco=self.pasta/'eventos.db')
        with patch('providers_console.comando_nativo',return_value=[sys.executable,str(fake)]),contextlib.redirect_stdout(io.StringIO()):
            r=self.executar(lambda *a,**kw:revisoes.append(1),rodar=rodar)
        self.assertEqual((r['codigo'],r['estado']),(1,'bloqueado'))
        self.assertEqual(self.moves,['Em andamento'])
        self.assertEqual(revisoes,[])
        self.assertIsNone(Controle(self.db).revisao(r['token']))
        tarefa=Controle(self.db).listar('owner/repo')[0]
        self.assertTrue(tarefa['sessao'])

    def test_skill_nativa_exige_evidencia_mesmo_se_executor_retorna_zero(self):
        self.cfg['equipes'][0]['executor']['console']='claude'
        self.cfg['revisao']['revisores'][0]['executor']['console']='gemini'
        (self.pasta/'.office/projeto.json').write_text(json.dumps(self.cfg),encoding='utf-8')
        skill=self.pasta/'.claude/skills/teste';skill.mkdir(parents=True)
        (skill/'SKILL.md').write_text('---\nname: teste\ndescription: Teste\nallowed-tools: Read\n---\nLeia.',encoding='utf-8')
        self.k.issue=lambda *_:{'state':'open','title':'Tarefa','body':'**Aceite:** Deve passar\n**Skills:** teste'}
        revisoes=[]
        r=self.executar(lambda *a,**kw:revisoes.append(1))
        self.assertEqual((r['codigo'],r['estado']),(1,'bloqueado'))
        self.assertEqual(self.moves,['Em andamento']);self.assertEqual(revisoes,[])

    def test_evidencia_skill_vinculada_sessao_persiste_e_libera_revisao(self):
        self.cfg['equipes'][0]['executor']['console']='claude'
        self.cfg['revisao']['revisores'][0]['executor']['console']='gemini'
        (self.pasta/'.office/projeto.json').write_text(json.dumps(self.cfg),encoding='utf-8')
        skill=self.pasta/'.claude/skills/teste';skill.mkdir(parents=True)
        (skill/'SKILL.md').write_text('---\nname: teste\ndescription: Teste\nallowed-tools: Read\n---\nLeia.',encoding='utf-8')
        self.k.issue=lambda *_:{'state':'open','title':'Tarefa','body':'**Aceite:** Deve passar\n**Skills:** teste'}
        def rodar(*args,**kwargs):
            kwargs['ao_sessao']('sessao')
            e={'console':'claude','sessao':'errada','solicitadas':['teste'],'confirmadas':['teste'],'pendentes':[],'valida':True}
            with self.assertRaisesRegex(ValueError,'diverge'):kwargs['ao_skills'](e)
            kwargs['ao_skills']({**e,'sessao':'sessao'})
            return 0
        r=self.executar(lambda *a,**kw:self.relatorio(),rodar=rodar)
        self.assertEqual((r['codigo'],r['estado']),(0,'revisao'))
        self.assertTrue(Controle(self.db).skills(r['token'])['valida'])

    def test_aprovacao_persiste_entrega_sem_concluir_ou_merge(self):
        r=self.executar(lambda *a,**kw:self.relatorio())
        self.assertEqual(r['estado'],'revisao'); self.assertEqual(self.moves,['Em andamento','Em revisão'])
        evidencia=Controle(self.db).revisao(r['token'])
        fases=Controle(self.db).listar('owner/repo')[0]['pacote']['dependencias_verificadas']
        self.assertEqual(set(fases),{'antes_execucao','entrega','apos_revisao'})
        self.assertLessEqual(fases['antes_execucao']['verificadas_em'],fases['apos_revisao']['verificadas_em'])
        self.assertEqual((evidencia['sha'],evidencia['pr'],evidencia['aprovado']),(self.sha,12,1))
        from gestao_painel import resumo
        with patch('gestao_painel.pasta_dados',return_value=self.pasta):
            painel=resumo([self.pasta])
        self.assertEqual(painel['projetos'][0]['tarefas'][0]['revisao_sha'],self.sha)
        self.assertNotIn(r['token'],json.dumps(painel))
        self.assertNotIn('relatorio',json.dumps(painel))

    def test_intervalo_real_do_despacho_e_projetado_sem_token(self):
        r=self.executar(lambda *a,**kw:self.relatorio())
        from gestao_painel import resumo
        with patch('gestao_painel.pasta_dados',return_value=self.pasta):
            projeto=resumo([self.pasta])['projetos'][0]
        medicao=projeto['tarefas'][0]['ultima_execucao']
        self.assertEqual(medicao['codigo'],0); self.assertGreaterEqual(medicao['duracao_seg'],0)
        g=projeto['desempenho']['grupos'][0]
        self.assertEqual((g['tentativas'],g['com_intervalo'],g['sem_retorno']),(1,1,0))
        self.assertEqual((g['equipe'],g['despachos'],g['resultados']['revisao_aprovada']),('Dev',1,1))
        self.assertNotIn(r['token'],json.dumps(projeto))

    def test_erro_do_console_deixa_medicao_sem_retorno(self):
        def rodar(*a,**kw): raise ValueError('CLI sem retorno')
        with self.assertRaisesRegex(ValueError,'CLI sem retorno'):
            self.executar(lambda *a,**kw:self.relatorio(),rodar=rodar)
        from gestao_painel import resumo
        with patch('gestao_painel.pasta_dados',return_value=self.pasta):
            projeto=resumo([self.pasta])['projetos'][0]
        g=projeto['desempenho']['grupos'][0]
        self.assertEqual((g['tentativas'],g['com_intervalo'],g['sem_retorno']),(1,0,1))
        self.assertEqual(g['sem_resultado'],1)
        self.assertIsNone(g['media_seg']); self.assertIsNone(projeto['tarefas'][0]['ultima_execucao']['fim'])

    def test_worktree_ocupado_impede_reserva_modelo_e_movimento(self):
        from controle_tarefas import ocupar_worktree
        chamadas=[]
        with ocupar_worktree(self.pasta/'execucoes.db',self.pasta):
            with self.assertRaisesRegex(ValueError,'Worktree já ocupado'):
                self.executar(lambda *a,**kw:self.relatorio(),rodar=lambda *a,**kw:chamadas.append(1) or 0)
        self.assertEqual(chamadas,[]); self.assertEqual(self.moves,[])
        self.assertFalse(self.db.exists())

    def test_sessao_observada_persiste_na_reserva_e_painel(self):
        def rodar(*a,**kw):
            kw['ao_sessao']('native-gemini-1'); return 0
        resultado=self.executar(lambda *a,**kw:self.relatorio(),rodar=rodar)
        tarefa=Controle(self.db).listar('owner/repo')[0]
        self.assertEqual(tarefa['sessao'],'native-gemini-1')
        self.assertEqual(tarefa['estado'],'revisao')
        from gestao_painel import resumo
        with patch('gestao_painel.pasta_dados',return_value=self.pasta):
            self.assertEqual(resumo([self.pasta])['projetos'][0]['tarefas'][0]['sessao'],'native-gemini-1')
        self.assertNotIn(resultado['token'],json.dumps(resumo([])))

    def test_troca_de_sessao_bloqueia_e_mantem_ocupacao_incerta(self):
        from controle_tarefas import ocupar_worktree
        def rodar(*a,**kw):
            kw['ao_sessao']('native-original'); kw['ao_sessao']('native-outra'); return 0
        with self.assertRaisesRegex(ValueError,'outra sessão'):
            self.executar(lambda *a,**kw:self.relatorio(),rodar=rodar)
        tarefa=Controle(self.db).listar('owner/repo')[0]
        self.assertEqual(tarefa['sessao'],'native-original'); self.assertEqual(tarefa['estado'],'bloqueado')
        self.assertEqual(self.moves,['Em andamento']); self.assertIsNone(Controle(self.db).revisao(tarefa['token']))
        with self.assertRaisesRegex(ValueError,'concilie'):
            with ocupar_worktree(self.pasta/'execucoes.db',self.pasta): pass

    def test_reprovacao_bloqueia_mesmo_com_exit_zero(self):
        r=self.executar(lambda *a,**kw:self.relatorio(False))
        self.assertEqual(r['estado'],'bloqueado'); self.assertEqual(self.moves,['Em andamento'])
        self.assertEqual(Controle(self.db).revisao(r['token'])['aprovado'],0)
        import sqlite3
        from contextlib import closing
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual(db.execute('SELECT resultado FROM execucao_resultado').fetchone()[0],'revisao_reprovada')

    def test_dependencia_reaberta_na_revisao_nao_aprova_entrega(self):
        dep={'number':1,'html_url':'https://github.com/owner/repo/issues/1','state':'closed','state_reason':'completed'}
        self.k.bloqueadores=lambda _:[copy.deepcopy(dep)]
        self.k.chamar=lambda _:copy.deepcopy(dep)
        def callback(*a,**kw):
            relatorio=self.relatorio(); dep['state']='open'; return relatorio
        with self.assertRaises(ValueError): self.executar(callback)
        reserva=Controle(self.db).listar('owner/repo')[0]
        self.assertEqual(reserva['estado'],'bloqueado'); self.assertEqual(self.moves,['Em andamento'])
        self.assertIsNone(Controle(self.db).revisao(reserva['token']))

    def test_pr_mudando_nao_persiste_aprovacao(self):
        def callback(*a,**kw):
            relatorio=self.relatorio(); self.pr['head']['sha']='c'*40; return relatorio
        with self.assertRaises(ValueError): self.executar(callback)
        reserva=Controle(self.db).listar('owner/repo')[0]
        self.assertEqual(reserva['estado'],'bloqueado'); self.assertIsNone(Controle(self.db).revisao(reserva['token']))
        self.assertEqual(self.moves,['Em andamento'])

    def test_head_nao_publicado_nao_chama_modelos(self):
        self.pr['head']['sha']='c'*40
        def proibido(*a,**kw): raise AssertionError('Não pode chamar modelos para SHA divergente')
        with self.assertRaises(ValueError): self.executar(proibido)

    def test_aceite_mudando_invalida_aprovacao(self):
        def callback(*a,**kw):
            relatorio=self.relatorio()
            self.k.issue=lambda *_:{'state':'open','body':'**Aceite:** Critério diferente'}
            return relatorio
        with self.assertRaises(ValueError): self.executar(callback)
        self.assertEqual(Controle(self.db).listar('owner/repo')[0]['estado'],'bloqueado')

    def test_objetivo_mudando_antes_execucao_nao_chama_modelo(self):
        original=self.k.issue
        chamadas=[]
        def issue(*args):
            item=original(*args)
            if chamadas: item['title']='Outro objetivo'
            chamadas.append(1)
            return item
        self.k.issue=issue
        modelos=[]
        with self.assertRaisesRegex(ValueError,'instruções'):
            self.executar(lambda *a,**kw:self.relatorio(),rodar=lambda *a,**kw:modelos.append(1) or 0)
        self.assertEqual(modelos,[]); self.assertEqual(self.moves,[])
        self.assertEqual(Controle(self.db).listar('owner/repo')[0]['estado'],'bloqueado')

    def test_escopo_mudando_durante_execucao_sem_revisao_bloqueia(self):
        self.cfg['revisao']['ativo']=False
        (self.pasta/'.office/projeto.json').write_text(json.dumps(self.cfg),encoding='utf-8')
        original=self.k.issue
        def rodar(*a,**kw):
            self.k.issue=lambda *_:{**original(), 'body':'**Aceite:** Deve passar\n\n**Escopo:** Alterar tudo'}
            return 0
        revisoes=[]
        with self.assertRaisesRegex(ValueError,'instruções'):
            self.executar(lambda *a,**kw:revisoes.append(1),rodar=rodar)
        self.assertEqual(revisoes,[]); self.assertEqual(self.moves,['Em andamento'])
        self.assertIsNone(Controle(self.db).revisao(Controle(self.db).listar('owner/repo')[0]['token']))

    def test_time_mudando_na_entrega_sem_revisao_nao_move_cartao(self):
        self.cfg['revisao']['ativo']=False
        (self.pasta/'.office/projeto.json').write_text(json.dumps(self.cfg),encoding='utf-8')
        def entrega(*args):
            self.k.cartao=lambda *a,**kw:{'status':self.status,'equipe':'Outra'}
            return copy.deepcopy(self.pr)
        self.k.entrega=entrega
        with self.assertRaisesRegex(ValueError,'instruções'):
            self.executar(lambda *a,**kw:self.relatorio())
        self.assertEqual(self.moves,['Em andamento'])
        self.assertEqual(Controle(self.db).listar('owner/repo')[0]['estado'],'bloqueado')

    def test_politica_mudando_na_consulta_de_entrega_bloqueia_encaminhamento(self):
        self.cfg['revisao']['ativo']=False
        (self.pasta/'.office/projeto.json').write_text(json.dumps(self.cfg),encoding='utf-8')
        def entrega(*args):
            nova=copy.deepcopy(self.cfg);nova['diretor']['console']='codex'
            (self.pasta/'.office/projeto.json').write_text(json.dumps(nova),encoding='utf-8')
            return copy.deepcopy(self.pr)
        self.k.entrega=entrega
        with self.assertRaisesRegex(ValueError,'Política mudou'):
            self.executar(lambda *a,**kw:self.relatorio())
        self.assertEqual(self.moves,['Em andamento'])
        c=Controle(self.db);t=c.listar('owner/repo')[0]
        self.assertEqual(t['estado'],'bloqueado')
        self.assertIsNone(c.revisao(t['token']))
        from contextlib import closing
        with closing(c._abrir()) as db:
            self.assertEqual(db.execute('SELECT resultado FROM execucao_resultado').fetchone()[0],'gate_bloqueado')

    def test_politica_mudando_dentro_da_conferencia_bloqueia_snapshot(self):
        with patch('gestao_cli.selecionar',return_value=(PROVIDERS['gemini'],'native')):
            pacote=gc.preparar(self.pasta,42,'Dev',kanban=self.k)[4]
        original=self.k.issue
        def issue(*args):
            nova=copy.deepcopy(self.cfg);nova['diretor']['console']='codex'
            (self.pasta/'.office/projeto.json').write_text(json.dumps(nova),encoding='utf-8')
            return original(*args)
        self.k.issue=issue
        with self.assertRaisesRegex(ValueError,'Política mudou'):
            gc.conferir_cartao(self.k,42,self.pasta,self.cfg,'Dev',pacote,'Backlog')
        self.assertEqual(self.moves,[])

    def test_skills_mudando_na_revisao_nao_persiste_aprovacao(self):
        original=self.k.issue
        def callback(*a,**kw):
            relatorio=self.relatorio()
            self.k.issue=lambda *_:{**original(), 'body':'**Aceite:** Deve passar\n\n**Skills:** outra-skill'}
            return relatorio
        with self.assertRaisesRegex(ValueError,'instruções'): self.executar(callback)
        tarefa=Controle(self.db).listar('owner/repo')[0]
        self.assertEqual(tarefa['estado'],'bloqueado')
        self.assertIsNone(Controle(self.db).revisao(tarefa['token']))
        self.assertEqual(self.moves,['Em andamento'])

    def skill(self,nome='teste'):
        pasta=self.pasta/'.claude/skills'/nome; pasta.mkdir(parents=True)
        arq=pasta/'SKILL.md'
        arq.write_text('---\nname: '+nome+'\ndescription: Exemplo\n---\nRegra original',encoding='utf-8')
        return arq

    def test_skill_desconhecida_impede_reserva_e_modelo(self):
        original=self.k.issue
        self.k.issue=lambda *_:{**original(), 'body':'**Aceite:** Deve passar\n\n**Skills:** ausente'}
        modelos=[]
        with self.assertRaisesRegex(ValueError,'Skill indisponível'):
            self.executar(lambda *a,**kw:self.relatorio(),rodar=lambda *a,**kw:modelos.append(1) or 0)
        self.assertEqual(modelos,[]); self.assertEqual(self.moves,[])
        self.assertFalse(self.db.exists())

    def test_conteudo_skill_mudando_invalida_execucao(self):
        arq=self.skill(); original=self.k.issue
        self.k.issue=lambda *_:{**original(), 'body':'**Aceite:** Deve passar\n\n**Skills:** teste'}
        def rodar(*a,**kw):
            self.assertIn('.claude/skills/teste/SKILL.md',kw['prompt'])
            arq.write_text(arq.read_text(encoding='utf-8')+'\nOutra regra',encoding='utf-8')
            return 0
        with self.assertRaisesRegex(ValueError,'Skill mudou'):
            self.executar(lambda *a,**kw:self.relatorio(),rodar=rodar)
        tarefa=Controle(self.db).listar('owner/repo')[0]
        self.assertEqual(tarefa['estado'],'bloqueado')
        self.assertEqual(self.moves,['Em andamento'])
        self.assertIsNone(Controle(self.db).revisao(tarefa['token']))

    def test_skill_funcionario_e_cartao_compartilham_snapshot(self):
        import funcionarios
        self.skill(); original=self.k.issue
        self.k.issue=lambda *_:{**original(), 'body':'**Aceite:** Deve passar\n\n**Skills:** `teste`, teste'}
        membro=funcionarios.cadastrar(self.pasta,{'nome':'Especialista','funcao':'Testar','equipe':'Dev',
            'executor':{'console':'gemini'},'skills':['teste']})
        r=self.executar(lambda *a,**kw:revisar(self.cfg,membro['executor'],self.sha,'diff','Deve passar','regras',
            lambda *_:{'veredito':'aprovado','achados':[]}),funcionario=membro['id'])
        refs=Controle(self.db).listar('owner/repo')[0]['pacote']['skills_resolvidas']
        self.assertEqual(len(refs),1); self.assertEqual(refs[0]['nome'],'teste')
        self.assertEqual(len(refs[0]['sha256']),64); self.assertEqual(r['estado'],'revisao')
        self.assertNotIn('Regra original',json.dumps(refs))

    def test_fonte_canonica_mudando_durante_execucao_bloqueia_entrega(self):
        regras=self.pasta/'CLAUDE.md'; regras.write_text('Regra original',encoding='utf-8')
        def rodar(*a,**kw):
            regras.write_text('Regra modificada',encoding='utf-8'); return 0
        with self.assertRaisesRegex(ValueError,'Fonte documental mudou'):
            self.executar(lambda *a,**kw:self.relatorio(),rodar=rodar)
        tarefa=Controle(self.db).listar('owner/repo')[0]
        self.assertEqual(tarefa['estado'],'bloqueado')
        self.assertEqual(self.moves,['Em andamento']); self.assertIsNone(Controle(self.db).revisao(tarefa['token']))

    def test_skill_runtime_claude_rejeitada_antes_de_reserva_gemini(self):
        arq=self.skill()
        arq.write_text('---\nname: teste\ndescription: Teste\nallowed-tools: Read\n---\nInstruções',encoding='utf-8')
        original=self.k.issue
        self.k.issue=lambda *_:{**original(), 'body':'**Aceite:** Deve passar\n\n**Skills:** teste'}
        chamadas=[]
        with self.assertRaisesRegex(ValueError,'incompatível com gemini'):
            self.executar(lambda *a,**kw:chamadas.append('revisao'),rodar=lambda *a,**kw:chamadas.append('modelo'))
        self.assertEqual(chamadas,[]);self.assertEqual(self.moves,[])
        self.assertFalse(self.db.exists())

    def test_funcionario_no_despacho_e_autor_da_revisao(self):
        import funcionarios
        membro=funcionarios.cadastrar(self.pasta,{'nome':'Especialista','funcao':'Analisar regras de jogo','equipe':'Dev',
            'executor':{'console':'gemini','modelo':'modelo-especialista'},'skills':[]})
        chamadas=[]
        def callback(*a,**kw):
            self.assertEqual(kw['funcionario'],membro['id'])
            return revisar(self.cfg,membro['executor'],self.sha,'diff','Deve passar','regras',lambda *_:{'veredito':'aprovado','achados':[]})
        def rodar(*a,**kw): chamadas.append((a,kw)); return 0
        r=self.executar(callback,membro['id'],rodar)
        self.assertEqual(r['estado'],'revisao')
        self.assertEqual(chamadas[0][0][3],funcionarios.nome_eventos(membro))
        self.assertEqual(chamadas[0][1]['modelo'],'modelo-especialista')
        self.assertIn('Analisar regras de jogo',chamadas[0][1]['prompt'])
        pacote=Controle(self.db).listar('owner/repo')[0]['pacote']
        self.assertEqual(pacote['funcionario']['id'],membro['id'])
        from gestao_painel import resumo
        with patch('gestao_painel.pasta_dados',return_value=self.pasta):
            tarefa=resumo([self.pasta])['projetos'][0]['tarefas'][0]
        self.assertEqual(tarefa['funcionario_nome'],'Especialista')
        self.assertNotIn('pacote',tarefa)

    def test_cadastro_mudando_invalida_revisao(self):
        import funcionarios,sqlite3
        membro=funcionarios.cadastrar(self.pasta,{'nome':'Especialista','funcao':'Testar','equipe':'Dev','executor':{'console':'gemini'},'skills':[]})
        def callback(*a,**kw):
            relatorio=revisar(self.cfg,membro['executor'],self.sha,'diff','Deve passar','regras',lambda *_:{'veredito':'aprovado','achados':[]})
            novo={**membro,'funcao':'Outra responsabilidade'}
            from contextlib import closing
            with closing(sqlite3.connect(funcionarios.arquivo(self.pasta))) as db,db:
                db.execute('UPDATE funcionario SET dados=? WHERE id=?',(json.dumps(novo),membro['id']))
            return relatorio
        with self.assertRaises(ValueError): self.executar(callback,membro['id'])
        self.assertEqual(Controle(self.db).listar('owner/repo')[0]['estado'],'bloqueado')


if __name__=='__main__': unittest.main()
