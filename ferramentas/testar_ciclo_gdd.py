import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch,Mock
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import ciclo_gdd as c
from gestao_projeto import validar


class Ciclo(unittest.TestCase):
    def test_pr_historico_impede_acumular_antes_de_chamar_diretor(self):
        self.cfg['ciclo']['max_prs_pendentes']=1;ident='a'*32;tempo=[0]
        c.atomico(c.caminho_estado(self.p),{'id':ident,'estado':'iniciando','continuo':True,'limite':None,'resultados':[],'pausa_configuravel':True})
        k=Mock();k.quadro.return_value={'campos':[],'itens':[self.item(1)]};k.cartoes.return_value=[self.item(1)]
        k._paginas.return_value=[{'number':667,'state':'open','draft':True},{'number':672,'state':'open','draft':False}]
        consulta=Mock();criar=Mock();lote=Mock()
        def dormir(seg):
            self.assertEqual(c.resumo(self.p)['estado'],'aguardando')
            self.assertEqual(c.resumo(self.p)['prs_abertos'],2)
            c.solicitar_pausa(self.p,ident);tempo[0]+=seg
        with patch.object(c,'Kanban',return_value=k):
            c.rodar(self.p,ident,relogio=lambda:tempo[0],dormir=dormir,consulta=consulta,criar=criar,lote=lote)
        consulta.assert_not_called();criar.assert_not_called();lote.assert_not_called()
        self.assertEqual(c.resumo(self.p)['estado'],'pausado')

    def test_dois_limites_seguidos_param_antes_de_novo_despacho(self):
        itens=[self.item(1),self.item(25),self.item(50)];despachos=[]
        c.atomico(c.caminho_estado(self.p),{'id':'teste','estado':'iniciando','limite':600,'resultados':[]})
        k=Mock();k.quadro.return_value={'campos':[],'itens':itens};k.cartoes.return_value=itens;k._paginas.return_value=[]
        def candidatos(p,cfg,k,grupo,mapa):
            return [{**i,'preparavel':True,'objetivo_gdd':1,'issue':{'body':''}} for i in grupo]
        def consulta(p,cfg,docs,grupo,prs,ocupada):return [self.decisao(i['numero'],'executar') for i in grupo]
        def lote(p,plano,ao_execucao=None):
            n=plano['cartoes'][0]['cartao'];despachos.append(n)
            return {'resultados':[{'cartao':n,'estado':'bloqueado','codigo':124,'motivo':'limite_tokens'}]}
        with patch.object(c,'Kanban',return_value=k),patch.object(c,'bancada_ocupada',return_value=False),patch.object(c,'candidatos',side_effect=candidatos):
            with self.assertRaisesRegex(ValueError,'Dois despachos consecutivos'):
                c.rodar(self.p,'teste',relogio=lambda:0,consulta=consulta,
                    criar=lambda p,d:{'plano':{'cartoes':[{'cartao':n,'worktree':'novo'} for n in d['cartoes']]}},lote=lote)
        self.assertEqual(despachos,[1,25]);estado=c.resumo(self.p)
        self.assertEqual(estado['estado'],'erro');self.assertEqual(len(estado['resultados']),2)
        self.assertIn('configure tempo/tokens',estado['motivo'])

    def test_entrega_intermediaria_zera_limites_e_primeiro_nao_impede_independente(self):
        itens=[self.item(n) for n in (1,25,50,51,52)];despachos=[]
        c.atomico(c.caminho_estado(self.p),{'id':'teste','estado':'iniciando','limite':600,'resultados':[]})
        k=Mock();k.quadro.return_value={'campos':[],'itens':itens};k.cartoes.return_value=itens;k._paginas.return_value=[]
        def candidatos(p,cfg,k,grupo,mapa):
            return [{**i,'preparavel':True,'objetivo_gdd':1,'issue':{'body':''}} for i in grupo]
        def consulta(p,cfg,docs,grupo,prs,ocupada):return [self.decisao(i['numero'],'executar') for i in grupo]
        def lote(p,plano,ao_execucao=None):
            n=plano['cartoes'][0]['cartao'];despachos.append(n)
            return {'resultados':[{'cartao':n,'estado':'revisao' if n==25 else 'bloqueado',
                                  'codigo':0 if n==25 else 124,'motivo':'' if n==25 else 'limite_tempo'}]}
        with patch.object(c,'Kanban',return_value=k),patch.object(c,'bancada_ocupada',return_value=False),patch.object(c,'candidatos',side_effect=candidatos):
            with self.assertRaisesRegex(ValueError,'Dois despachos consecutivos'):
                c.rodar(self.p,'teste',relogio=lambda:0,consulta=consulta,
                    criar=lambda p,d:{'plano':{'cartoes':[{'cartao':n,'worktree':'novo'} for n in d['cartoes']]}},lote=lote)
        self.assertEqual(despachos,[1,25,50,51])
        self.assertEqual(len(c.resumo(self.p)['resultados']),4)

    def test_etapa_so_avanca_apos_execucao_registrada(self):
        ident='a'*32;item=self.item(1)
        c.atomico(c.caminho_estado(self.p),{'id':ident,'estado':'iniciando','continuo':True,
            'limite':None,'resultados':[],'pausa_configuravel':True})
        k=Mock();k.quadro.return_value={'campos':[],'itens':[item]};k.cartoes.return_value=[item];k._paginas.return_value=[]
        grupo=[{**item,'preparavel':True,'objetivo_gdd':1,'issue':{'body':''}}]
        def lote(p,plano,ao_execucao=None):
            self.assertEqual(c.resumo(p)['estado'],'preparando')
            self.assertIn('validar',c.resumo(p)['proxima_acao'])
            ao_execucao(1,'token','tentativa')
            self.assertEqual(c.resumo(p)['estado'],'implementando')
            c.solicitar_pausa(p,ident)
            return {'resultados':[{'cartao':1,'estado':'revisao','codigo':0}]}
        with patch.object(c,'Kanban',return_value=k),patch.object(c,'bancada_ocupada',return_value=False),patch.object(c,'candidatos',return_value=grupo):
            c.rodar(self.p,ident,consulta=lambda *a:[self.decisao(1,'executar')],
                criar=lambda p,d:{'plano':{'cartoes':[{'cartao':1,'worktree':'novo'}]}},lote=lote)
        self.assertEqual(c.resumo(self.p)['estado'],'pausado')

    def test_falha_validacao_nao_anuncia_implementacao(self):
        ident='a'*32;item=self.item(1);etapas=[]
        c.atomico(c.caminho_estado(self.p),{'id':ident,'estado':'iniciando','limite':999999999999,'resultados':[]})
        k=Mock();k.quadro.return_value={'campos':[],'itens':[item]};k.cartoes.return_value=[item];k._paginas.return_value=[]
        grupo=[{**item,'preparavel':True,'objetivo_gdd':1,'issue':{'body':''}}]
        atomico=c.atomico
        def gravar(p,registro):
            etapas.append(registro.get('estado'));return atomico(p,registro)
        def lote(p,plano,ao_execucao=None):raise ValueError('Dependência mudou')
        with patch.object(c,'Kanban',return_value=k),patch.object(c,'bancada_ocupada',return_value=False),patch.object(c,'candidatos',return_value=grupo),patch.object(c,'atomico',side_effect=gravar):
            with self.assertRaisesRegex(ValueError,'Dependência mudou'):
                c.rodar(self.p,ident,consulta=lambda *a:[self.decisao(1,'executar')],
                    criar=lambda p,d:{'plano':{'cartoes':[{'cartao':1,'worktree':'novo'}]}},lote=lote)
        self.assertIn('preparando',etapas);self.assertNotIn('implementando',etapas)
        self.assertEqual(c.resumo(self.p)['estado'],'erro')

    def test_fila_aguarda_sem_modelo_nem_novo_despacho_e_pausa_responsiva(self):
        self.cfg['ciclo']['max_prs_pendentes']=1;ident='a'*32;tempo=[0]
        c.atomico(c.caminho_estado(self.p),{'id':ident,'estado':'iniciando','continuo':True,
            'limite':None,'resultados':[],'pausa_configuravel':True})
        consulta=Mock();lote=Mock();k=Mock()
        def dormir(seg):tempo[0]+=seg;c.solicitar_pausa(self.p,ident)
        with patch.object(c,'Kanban',return_value=k),patch('conclusao_tarefas.confirmar_sessao',return_value=[]),patch('conclusao_tarefas.pendencias_sessao',return_value=[{'cartao':4,'pr':8}]):
            c.rodar(self.p,ident,relogio=lambda:tempo[0],dormir=dormir,consulta=consulta,lote=lote)
        consulta.assert_not_called();lote.assert_not_called();k.quadro.assert_not_called()
        self.assertEqual(c.resumo(self.p)['estado'],'pausado');self.assertGreater(tempo[0],0)

    def test_duracao_futura_nao_muda_politica_efetiva(self):
        import copy
        atual=copy.deepcopy(self.cfg);atual['ciclo']['duracao_min']=60
        self.assertTrue(c.mesma_politica_em_execucao(atual,self.cfg))
        self.assertEqual(atual['ciclo']['duracao_min'],60)
        atual['ciclo']['continuo']=True
        self.assertTrue(c.mesma_politica_em_execucao(atual,self.cfg))
        atual['revisao']['ativo']=True
        self.assertFalse(c.mesma_politica_em_execucao(atual,self.cfg))
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.raiz=Path(self.tmp.name);self.p=self.raiz/'projeto';self.p.mkdir()
        self.cfg=validar({'ativo':True,'fontes':{'produto':'PRODUTO.md'},
            'kanban':{'prioridades':['P0','P1','P2','P3']},
            'ciclo':{'ativo':True,'base':'origin/main','criar_subtarefas':True},
            'equipes':[{'nome':'Dev','especialidade':'Código','executor':{'console':'codex'}}]})
        for alvo,val in [('carregar',self.cfg),('pasta_dados',self.raiz/'dados')]:
            p=patch.object(c,alvo,return_value=val);p.start();self.addCleanup(p.stop)
        self.dados=self.raiz/'dados';self.dados.mkdir()
        (self.p/'PRODUTO.md').write_text('#### Objetivo 1 — cidade\nCartões: #1 #25\n',encoding='utf-8')
        (self.p/'CLAUDE.md').write_text('Regras',encoding='utf-8')

    def item(self,n):return {'numero':n,'status':'Backlog','equipe':'Dev','prioridade':'P0','etapa':'L1'}
    def decisao(self,n,acao='aguardar'):
        return {'cartao':n,'acao':acao,'motivo':'motivo','evidencia_faltante':'', 'recurso':'leve','subtarefa':None}

    def test_config_desligada_e_limites_validos(self):
        self.assertFalse(validar({})['ciclo']['ativo'])
        self.assertFalse(validar({})['ciclo']['continuo'])
        with self.assertRaises(ValueError):validar({'ciclo':{'continuo':True}})
        for cambio in ({'max_cartoes':3},{'duracao_min':True},{'intervalo_seg':0},{'ativo':True,'base':'-x'}):
            with self.assertRaises(ValueError):validar({'ciclo':cambio})

    def test_inicio_continuo_exige_metas_e_nao_tem_prazo_global(self):
        self.cfg['metas']['ativo']=True;self.cfg['ciclo']['continuo']=True
        validar(self.cfg)
        with patch.object(c.subprocess,'Popen',return_value=Mock(pid=123)):
            c.iniciar(self.p)
        self.assertIsNone(c.resumo(self.p)['limite'])
        self.assertTrue(c.resumo(self.p)['continuo'])

    def test_continuo_passa_prazo_sem_repetir_ia_e_pausa_responsiva(self):
        tempo=[0];consulta=Mock(return_value=[self.decisao(1)]);ident='a'*32
        c.atomico(c.caminho_estado(self.p),{'id':ident,'estado':'iniciando','continuo':True,
            'limite':10,'resultados':[],'pausa_configuravel':True})
        k=Mock();k.quadro.return_value={'campos':[],'itens':[self.item(1)]};k.cartoes.return_value=[self.item(1)];k._paginas.return_value=[]
        def dormir(seg):
            tempo[0]+=seg
            if tempo[0]>=30:c.solicitar_pausa(self.p,ident)
        with patch.object(c,'Kanban',return_value=k),patch.object(c,'bancada_ocupada',return_value=False),patch.object(c,'candidatos',return_value=[{**self.item(1),'preparavel':True,'objetivo_gdd':1,'issue':{'body':''}}]):
            c.rodar(self.p,ident,relogio=lambda:tempo[0],dormir=dormir,consulta=consulta)
        self.assertGreater(tempo[0],10);self.assertEqual(consulta.call_count,1)
        self.assertEqual(c.resumo(self.p)['estado'],'pausado')

    def test_pausa_encerra_despacho_em_curso_sem_iniciar_segundo_cartao(self):
        ident='a'*32;itens=[self.item(1),self.item(25)];despachos=[]
        c.atomico(c.caminho_estado(self.p),{'id':ident,'estado':'iniciando','continuo':True,
            'limite':None,'resultados':[],'pausa_configuravel':True})
        k=Mock();k.quadro.return_value={'campos':[],'itens':itens};k.cartoes.return_value=itens;k._paginas.return_value=[]
        grupo=[{**i,'preparavel':True,'objetivo_gdd':1,'issue':{'body':''}} for i in itens]
        def lote(p,plano,ao_execucao=None):
            despachos.extend(plano['cartoes']);c.solicitar_pausa(p,ident)
            return {'estado':'processado','resultados':[{'cartao':1,'estado':'revisao','codigo':0}]}
        with patch.object(c,'Kanban',return_value=k),patch.object(c,'bancada_ocupada',return_value=False),patch.object(c,'candidatos',return_value=grupo):
            c.rodar(self.p,ident,consulta=lambda *args:[self.decisao(i['numero'],'executar') for i in itens],
                criar=lambda p,d:{'plano':{'cartoes':[{'cartao':n,'worktree':'novo'} for n in d['cartoes']]}},lote=lote)
        self.assertEqual([i['cartao'] for i in despachos],[1])
        self.assertEqual(c.resumo(self.p)['estado'],'pausado')
        self.assertEqual(len(c.resumo(self.p)['resultados']),1)
        with self.assertRaises(ValueError):c.solicitar_pausa(self.p,ident)

    def test_continuo_para_por_falha_do_provider_sem_loop(self):
        ident='a'*32
        c.atomico(c.caminho_estado(self.p),{'id':ident,'estado':'iniciando','continuo':True,'limite':None,'resultados':[]})
        k=Mock();k.quadro.return_value={'campos':[],'itens':[self.item(1)]};k.cartoes.return_value=[self.item(1)];k._paginas.return_value=[]
        consulta=Mock(side_effect=ValueError('Provider sem tokens'))
        with patch.object(c,'Kanban',return_value=k),patch.object(c,'bancada_ocupada',return_value=False),patch.object(c,'candidatos',return_value=[self.item(1)]):
            with self.assertRaisesRegex(ValueError,'sem tokens'):c.rodar(self.p,ident,consulta=consulta)
        self.assertEqual(consulta.call_count,1);self.assertEqual(c.resumo(self.p)['estado'],'erro')

    def test_ordem_prioridade_objetivo_nao_numero(self):
        itens=[{**self.item(1),'prioridade':'P2'},self.item(25),self.item(30)]
        self.assertEqual([i['numero'] for i in c.ordenar(itens,self.cfg,{25:1,30:3})],[25,30,1])

    def test_fontes_com_hash_e_evidencia_sem_truncar(self):
        docs=c.documentos(self.p,self.cfg);self.assertEqual(len(docs[0]['sha256']),64)
        self.assertEqual(c.objetivos(docs[0]['conteudo']),{1:1,25:1})
        pasta=self.p/'Benchmarks';pasta.mkdir(parents=True)
        (pasta/'pequeno.csv').write_text('ms\n33\n',encoding='utf-8')
        (pasta/'grande.csv').write_text('x'*17000,encoding='utf-8')
        ev=c.evidencias(self.p)['benchmarks']
        self.assertTrue(any(x['conteudo'] is not None and x['conteudo'].splitlines()==['ms','33'] for x in ev))
        self.assertTrue(any(x['conteudo'] is None and x['bytes']==17000 for x in ev))

    def test_diretor_nao_executa_bloqueado_nem_inventa_equipe(self):
        candidato={**self.item(1),'preparavel':False,'bloqueio':'reserva bloqueada'}
        r=c.validar_decisao(json.dumps({'decisoes':[self.decisao(1,'executar')]}),[candidato],self.cfg)
        self.assertEqual(r[0]['acao'],'aguardar');self.assertIn('reserva bloqueada',r[0]['motivo'])
        d=self.decisao(1,'desbloquear');d['subtarefa']={'titulo':'x','equipe':'inventada','objetivo':'x','aceite':'x','skills':'nenhuma'}
        with self.assertRaises(ValueError):c.validar_decisao(json.dumps({'decisoes':[d]}),[candidato],self.cfg)

    def test_nao_reinicia_sessao_incerta(self):
        c.atomico(c.caminho_estado(self.p),{'estado':'erro'})
        with self.assertRaisesRegex(ValueError,'existente/incerto'):c.iniciar(self.p)

    def test_conciliacao_preserva_tarefas_e_historico_sem_despachar(self):
        registro={'id':'a'*32,'estado':'erro','limite':200,'resultados':[]}
        p=c.caminho_estado(self.p);c.atomico(p,registro);bruto=p.read_bytes()
        dados={'versao':c.hashlib.sha256(bruto).hexdigest(),'nova_janela':True}
        with patch.object(c,'processos_do_projeto',return_value=[]),patch.object(c.subprocess,'Popen') as iniciar:
            resultado=c.conciliar(self.p,dados)
            self.assertEqual(resultado['estado'],'pausado');iniciar.assert_not_called()
        self.assertEqual((self.dados/'ciclos'/(dados['versao']+'.json')).read_bytes(),bruto)
        self.assertFalse(json.loads(p.read_text())['conciliacao']['preservar_janela'])
        with self.assertRaises(ValueError):c.conciliar(self.p,dados)

    def test_conciliacao_recusa_processos_desconhecidos_e_versao_antiga(self):
        p=c.caminho_estado(self.p);c.atomico(p,{'estado':'erro'})
        dados={'versao':c.hashlib.sha256(p.read_bytes()).hexdigest(),'nova_janela':False}
        for efeito in ([123],ValueError('Inventário indisponível')):
            with patch.object(c,'processos_do_projeto',**({'side_effect':efeito} if isinstance(efeito,Exception) else {'return_value':efeito})):
                with self.assertRaises(ValueError):c.conciliar(self.p,dados)
        with self.assertRaises(ValueError):c.conciliar(self.p,{**dados,'versao':'0'*64})
        self.assertEqual(c.resumo(self.p)['estado'],'erro')

    def test_conciliacao_recusa_tentativa_ou_lote_pendente(self):
        from contextlib import closing
        import sqlite3
        p=c.caminho_estado(self.p);c.atomico(p,{'estado':'erro','resultados':[]})
        dados={'versao':c.hashlib.sha256(p.read_bytes()).hexdigest(),'nova_janela':False}
        with closing(sqlite3.connect(self.dados/'tarefas.db')) as db,db:
            db.execute('CREATE TABLE execucao_tarefa(fim REAL)');db.execute('INSERT INTO execucao_tarefa VALUES(NULL)')
        with patch.object(c,'processos_do_projeto',return_value=[]):
            with self.assertRaisesRegex(ValueError,'incerta'):c.conciliar(self.p,dados)
        with closing(sqlite3.connect(self.dados/'tarefas.db')) as db,db:db.execute('DELETE FROM execucao_tarefa')
        c.atomico(p,{'estado':'erro','resultados':[{'id':'a'*32}]})
        dados['versao']=c.hashlib.sha256(p.read_bytes()).hexdigest()
        (self.dados/'lotes').mkdir();c.atomico(self.dados/'lotes'/('a'*32+'.json'),{'estado':'executando'})
        with patch.object(c,'processos_do_projeto',return_value=[]):
            with self.assertRaisesRegex(ValueError,'encerramento'):c.conciliar(self.p,dados)
        self.assertFalse(p.with_suffix('.inicio.lock').exists())

    def test_inventario_windows_exclui_shell_de_observacao(self):
        processos=[{'ProcessId':123,'Name':'powershell.exe','CommandLine':str(self.p)+' codex consulta'},
                   {'ProcessId':456,'Name':'python.exe','CommandLine':'python ciclo_gdd.py --projeto '+str(self.p)},
                   {'ProcessId':789,'Name':'codex.exe','CommandLine':'codex -C '+str(self.p)}]
        with patch.object(c.sys,'platform','win32'),patch.object(c.subprocess,'run',return_value=Mock(returncode=0,stdout=json.dumps(processos))):
            self.assertEqual(c.processos_do_projeto(self.p),[456,789])
        processos=[{'ProcessId':789,'Name':'codex.exe','CommandLine':None}]
        with patch.object(c.sys,'platform','win32'),patch.object(c.subprocess,'run',return_value=Mock(returncode=0,stdout=json.dumps(processos))):
            with self.assertRaisesRegex(ValueError,'verificável'):c.processos_do_projeto(self.p)

    def test_inicio_windows_fecha_lock_e_impede_duplicacao(self):
        with patch.object(c.subprocess,'Popen',return_value=Mock(pid=123)) as criar,patch.object(c,'coordenador_vivo',return_value=False):
            r=c.iniciar(self.p)
            self.assertEqual(r['pid'],123)
            self.assertFalse(c.caminho_estado(self.p).with_suffix('.inicio.lock').exists())
            with self.assertRaises(ValueError):c.iniciar(self.p)
            self.assertEqual(criar.call_count,1)

    def test_inicio_conciliado_nao_estende_janela(self):
        c.atomico(c.caminho_estado(self.p),{'estado':'pausado','limite':200,'conciliacao':{'preservar_janela':True}})
        with patch.object(c.time,'time',return_value=100),patch.object(c.subprocess,'Popen',return_value=Mock(pid=123)):
            c.iniciar(self.p)
        self.assertEqual(c.resumo(self.p)['limite'],200)

    def test_reabrir_ciclo_vivo_nao_cria_processo_nem_muda_prazo(self):
        registro={'id':'a'*32,'estado':'implementando','pid':123,'limite':200,'cartoes':[{'cartao':1}]}
        c.atomico(c.caminho_estado(self.p),registro)
        with patch.object(c,'coordenador_vivo',return_value=True),patch.object(c.subprocess,'Popen') as criar:
            r=c.iniciar(self.p)
        self.assertTrue(r['existente']);criar.assert_not_called()
        self.assertEqual(json.loads(c.caminho_estado(self.p).read_text(encoding='utf-8')),registro)

    def test_pid_exige_projeto_sessao_executavel_e_recibo(self):
        registro={'id':'a'*32,'estado':'implementando','pid':123}
        recibo=c.caminho_estado(self.p).with_suffix('.processo.json')
        c.atomico(recibo,{'id':registro['id'],'pid':123})
        argumentos=[str(c.RAIZ/'ciclo_gdd.py'),'--projeto',str(self.p.resolve()),'--sessao',registro['id']]
        processo={'ProcessId':123,'ExecutablePath':sys.executable,'CommandLine':sys.executable+' '+c.subprocess.list2cmdline(argumentos)}
        with patch.object(c.sys,'platform','win32'),patch.object(c.subprocess,'run') as consultar:
            consultar.return_value=Mock(returncode=0,stdout=json.dumps(processo))
            self.assertTrue(c.coordenador_vivo(self.p,registro))
            for campo,valor in [('CommandLine','outro projeto'),('ExecutablePath',str(self.raiz/'outro.exe')),('ProcessId',321)]:
                consultar.return_value=Mock(returncode=0,stdout=json.dumps({**processo,campo:valor}))
                self.assertFalse(c.coordenador_vivo(self.p,registro))
            consultar.return_value=Mock(returncode=0,stdout=json.dumps(processo))
            self.assertFalse(c.coordenador_vivo(self.p,{**registro,'estado':'erro'}))
            c.atomico(recibo,{'id':'b'*32,'pid':123})
            self.assertFalse(c.coordenador_vivo(self.p,registro))

    def test_paginas_20_encontra_cartao_25_e_respeita_limite(self):
        itens=[self.item(n) for n in range(1,26)];tempo=[0];consultados=[];despachos=[]
        (self.p/'PRODUTO.md').write_text('#### Objetivo 1\n'+ ' '.join('#'+str(n) for n in range(1,26)),encoding='utf-8')
        c.atomico(c.caminho_estado(self.p),{'id':'teste','estado':'iniciando','limite':10,'resultados':[]})
        k=Mock();k.quadro.return_value={'campos':[],'itens':itens};k.cartoes.return_value=itens;k._paginas.return_value=[]
        def candidatos(p,cfg,k,grupo,mapa):
            return [{**i,'preparavel':True,'objetivo_gdd':1,'issue':{'body':'aceite'}} for i in grupo]
        def consulta(p,cfg,docs,grupo,prs,ocupada):
            consultados.append([i['numero'] for i in grupo])
            return [self.decisao(i['numero'],'executar' if i['numero']==25 else 'aguardar') for i in grupo]
        def lote(p,plano,ao_execucao=None):
            despachos.extend(plano['cartoes']);tempo[0]=11;return {'estado':'processado'}
        with patch.object(c,'Kanban',return_value=k),patch.object(c,'bancada_ocupada',return_value=False),patch.object(c,'candidatos',side_effect=candidatos):
            c.rodar(self.p,'teste',relogio=lambda:tempo[0],dormir=lambda s:None,consulta=consulta,
                criar=lambda p,d:{'plano':{'cartoes':[{'cartao':25,'worktree':'novo'}]}},lote=lote)
        self.assertEqual(list(map(len,consultados)),[20,5]);self.assertEqual(despachos[0]['cartao'],25)
        self.assertEqual(c.resumo(self.p)['estado'],'limite')

    def test_espera_sem_reconsultar_modelo(self):
        tempo=[0];consulta=Mock(return_value=[self.decisao(1)])
        c.atomico(c.caminho_estado(self.p),{'id':'teste','estado':'iniciando','limite':600,'resultados':[]})
        k=Mock();k.quadro.return_value={'campos':[],'itens':[self.item(1)]};k.cartoes.return_value=[self.item(1)];k._paginas.return_value=[]
        with patch.object(c,'Kanban',return_value=k),patch.object(c,'bancada_ocupada',return_value=False),patch.object(c,'candidatos',return_value=[{**self.item(1),'preparavel':True,'objetivo_gdd':1,'issue':{'body':''}}]):
            c.rodar(self.p,'teste',relogio=lambda:tempo[0],dormir=lambda s:tempo.__setitem__(0,tempo[0]+s),consulta=consulta)
        self.assertEqual(consulta.call_count,1)

    def test_subtarefa_idempotente_envelope_rest(self):
        k=Mock();k._paginas.return_value=[];k.cache=self.raiz/'cache'
        k.base='users/test/projectsV2/4'
        campos=[{'id':i,'name':nome,'options':[{'id':str(i),'name':valor}]} for i,(nome,valor) in enumerate([
            ('Status','Backlog'),('Time','Dev'),('Prioridade','P0'),('Etapa GDD','L1')],1)]
        k.quadro.return_value={'campos':campos}
        k.chamar.side_effect=[{'number':50,'id':123},{},{'value':{'id':9}},{}]
        d=self.decisao(1,'desbloquear');d['subtarefa']={'titulo':'Investigar','equipe':'Dev','objetivo':'medir','aceite':'CSV','skills':'nenhuma'}
        self.assertEqual(c.subtarefa(self.p,self.cfg,k,{**self.item(1),'objetivo_gdd':1},d),50)
        self.assertEqual(c.subtarefa(self.p,self.cfg,k,self.item(1),d),50)
        self.assertEqual(k.chamar.call_count,4)
        corpo=k.chamar.call_args_list[0].args[2]['body'];self.assertIn('Parte de #1',corpo);self.assertNotIn('Closes #1',corpo)

    def test_preparacao_e_classificada_e_despachada_sem_varrer_resto_do_quadro(self):
        tempo=[0];consultas=[];despachos=[];itens=[self.item(1),self.item(25)]
        filho=self.item(50)
        c.atomico(c.caminho_estado(self.p),{'id':'teste','estado':'iniciando','limite':10,'resultados':[]})
        k=Mock();k.quadro.return_value={'campos':[],'itens':itens};k.cartoes.side_effect=[itens,[*itens,filho]];k._paginas.return_value=[]
        def candidatos(p,cfg,k,grupo,mapa):
            return [{**i,'preparavel':True,'objetivo_gdd':1,
                'pacote':{'escopo':'Planejamento/investigação deste bloqueio; não implementar o pai.'},
                'issue':{'body':'**Objetivo GDD:** 1'}} for i in grupo]
        def consulta(p,cfg,docs,grupo,prs,ocupada):
            consultas.append([i['numero'] for i in grupo])
            if grupo[0]['numero']==50:return [self.decisao(50,'executar')]
            d=self.decisao(1,'desbloquear');d['subtarefa']={'titulo':'Preparar','equipe':'Dev','objetivo':'classificar','aceite':'ADR','skills':'nenhuma'}
            return [d,self.decisao(25)]
        def lote(p,plano,ao_execucao=None):
            despachos.extend(plano['cartoes']);tempo[0]=11
            self.assertEqual(c.resumo(p)['estado'],'preparando')
            ao_execucao(50,'token','tentativa')
            self.assertEqual(c.resumo(p)['estado'],'investigando')
            return {'estado':'processado'}
        with patch.object(c,'Kanban',return_value=k),patch.object(c,'bancada_ocupada',return_value=False),patch.object(c,'candidatos',side_effect=candidatos),patch.object(c,'subtarefa',return_value=50):
            c.rodar(self.p,'teste',relogio=lambda:tempo[0],consulta=consulta,
                criar=lambda p,d:{'plano':{'cartoes':[{'cartao':n,'worktree':'novo'} for n in d['cartoes']]}},lote=lote)
        self.assertEqual(consultas,[[1,25],[50]])
        self.assertEqual([i['cartao'] for i in despachos],[50])
        self.assertEqual(len(list((self.dados/'decisoes').glob('*preparacao-50*.json'))),1)

    def test_preparacao_com_reserva_bloqueada_nao_e_retomada(self):
        tempo=[0];consulta=Mock();itens=[self.item(1)];filho=self.item(50)
        c.atomico(c.caminho_estado(self.p),{'id':'teste','estado':'iniciando','limite':10,'resultados':[]})
        k=Mock();k.quadro.return_value={'campos':[],'itens':itens};k.cartoes.side_effect=[itens,[*itens,filho]];k._paginas.return_value=[]
        d=self.decisao(1,'desbloquear');d['subtarefa']={'titulo':'Preparar','equipe':'Dev','objetivo':'classificar','aceite':'ADR','skills':'nenhuma'}
        consulta.return_value=[d]
        def candidatos(p,cfg,k,grupo,mapa):
            if grupo[0]['numero']==50:tempo[0]=11
            return [{**i,'preparavel':i['numero']!=50,'objetivo_gdd':1,'bloqueio':'reserva bloqueada','issue':{'body':''}} for i in grupo]
        with patch.object(c,'Kanban',return_value=k),patch.object(c,'bancada_ocupada',return_value=False),patch.object(c,'candidatos',side_effect=candidatos),patch.object(c,'subtarefa',return_value=50),patch.object(c,'criar_worktrees') as criar:
            c.rodar(self.p,'teste',relogio=lambda:tempo[0],consulta=consulta,criar=criar)
        self.assertEqual(consulta.call_count,1);criar.assert_not_called()

    def test_bancada_livre_replaneja_sem_mudar_quadro(self):
        tempo=[0];consulta=Mock(return_value=[self.decisao(1)])
        c.atomico(c.caminho_estado(self.p),{'id':'teste','estado':'iniciando','limite':600,'resultados':[]})
        k=Mock();k.quadro.return_value={'campos':[],'itens':[self.item(1)]};k.cartoes.return_value=[self.item(1)];k._paginas.return_value=[]
        with patch.object(c,'Kanban',return_value=k),patch.object(c,'bancada_ocupada',side_effect=[True,False]),patch.object(c,'candidatos',return_value=[{**self.item(1),'preparavel':True,'objetivo_gdd':1,'issue':{'body':''}}]):
            c.rodar(self.p,'teste',relogio=lambda:tempo[0],dormir=lambda s:tempo.__setitem__(0,tempo[0]+s),consulta=consulta)
        self.assertEqual(consulta.call_count,2)

    def test_subtarefa_resposta_rest_direta(self):
        k=Mock();k._paginas.return_value=[];k.cache=self.raiz/'cache';k.base='users/test/projectsV2/4'
        k.quadro.return_value={'campos':[{'id':i,'name':nome} for i,nome in enumerate(['Status','Time','Prioridade','Etapa GDD'],1)]}
        k.chamar.side_effect=[{'number':50,'id':123},{},{'id':9},{}]
        d=self.decisao(1,'desbloquear');d['subtarefa']={'titulo':'Investigar','equipe':'Dev','objetivo':'medir','aceite':'CSV','skills':'nenhuma'}
        self.assertEqual(c.subtarefa(self.p,self.cfg,k,{**self.item(1),'objetivo_gdd':1},d),50)
        self.assertEqual(k.chamar.call_args_list[-1].args[0],'users/test/projectsV2/4/items/9')

    def test_retorno_atual_encaminha_preparacao_sem_retomar_pai(self):
        tempo=[0];consultas=[];despachos=[]
        c.atomico(c.caminho_estado(self.p),{'id':'teste','estado':'iniciando','limite':10,'resultados':[]})
        k=Mock();k.quadro.return_value={'campos':[],'itens':[self.item(1)]};k.cartoes.return_value=[self.item(1)];k._paginas.return_value=[]
        candidato={**self.item(1),'preparavel':True,'objetivo_gdd':1,'issue':{'body':'aceite'}}
        def consulta(p,cfg,docs,grupo,prs,ocupada):
            consultas.extend(grupo)
            d=self.decisao(1,'desbloquear' if len(consultas)>1 else 'executar')
            if len(consultas)>1:d['subtarefa']={'titulo':'Investigar camada','equipe':'Dev','objetivo':'projeto técnico','aceite':'fixture verificável','skills':'nenhuma'}
            return [d]
        def lote(p,plano,ao_execucao=None):
            despachos.extend(plano['cartoes'])
            return {'resultados':[{'cartao':1,'estado':'bloqueado','codigo':0,'motivo':'sem PR'}]}
        def subtarefa(*args):tempo[0]=11;return 50
        with patch.object(c,'Kanban',return_value=k),patch.object(c,'bancada_ocupada',return_value=False),patch.object(c,'candidatos',return_value=[candidato]),patch.object(c,'subtarefa',side_effect=subtarefa) as criar:
            c.rodar(self.p,'teste',relogio=lambda:tempo[0],dormir=lambda s:None,consulta=consulta,
                criar=lambda p,d:{'plano':{'cartoes':[{'cartao':1,'worktree':'novo'}]}},lote=lote)
        self.assertEqual(len(despachos),1);self.assertTrue(consultas[1]['retorno_atual_confirmado']);self.assertEqual(criar.call_count,1)
        d=self.decisao(1,'desbloquear');d['subtarefa']={'titulo':'Investigar','equipe':'Dev','objetivo':'x','aceite':'y','skills':'nenhuma'}
        anterior={**candidato,'preparavel':False,'bloqueio':'reserva bloqueada'}
        with self.assertRaisesRegex(ValueError,'Reserva anterior'):
            c.validar_decisao(json.dumps({'decisoes':[d]}),[anterior],self.cfg)
        atual={**anterior,'retorno_atual_confirmado':True}
        self.assertEqual(c.validar_decisao(json.dumps({'decisoes':[d]}),[atual],self.cfg)[0]['acao'],'desbloquear')


if __name__=='__main__':unittest.main()
