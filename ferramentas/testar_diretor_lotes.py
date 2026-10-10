"""Lotes com worktrees Git reais, GitHub/CLIs simulados e nenhum modelo pago."""
import copy
import json
import io
from contextlib import redirect_stdout
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import gestao_cli as gc
import testar_gestao_kanban as fixtures
from providers_console import PROVIDERS
from controle_tarefas import Controle, ocupar_worktree


class Lotes(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.KanbanGestao(); self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.raiz=self.fixture.raiz
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.work=Path(self.tmp.name)
        self.git(self.raiz,'init','-b','main')
        self.git(self.raiz,'add','.office/projeto.json')
        self.git(self.raiz,'-c','user.name=Fixture','-c','user.email=fixture@example.com','commit','-m','fixture')
        self.plano={'cartoes':[]}
        for numero in (42,43):
            pasta=self.work/str(numero)
            self.git(self.raiz,'worktree','add','-b','feat/card-'+str(numero),str(pasta))
            self.plano['cartoes'].append({'cartao':numero,'worktree':str(pasta)})
        self.status={42:'Backlog',43:'Backlog'}
        self.equipes={42:'Dev',43:'Dev'}; self.prioridades={}; self.consoles=[]; self.prompts=[]
        self.corpos={n:'**Aceite:** Testes passam' for n in self.status}
        self.k=self.fixture.kanban(); self.k.chamar=self.api
        self.modelos=[]
        p=patch.object(gc,'RAIZ',self.work/'app'); p.start(); self.addCleanup(p.stop)
        p=patch.object(gc,'selecionar',return_value=(PROVIDERS['codex'],'native')); p.start(); self.addCleanup(p.stop)

    def git(self, pasta, *args):
        return subprocess.run(['git','-C',str(pasta),*args],capture_output=True,text=True,
            encoding='utf-8',check=True,timeout=20).stdout.strip()

    def api(self,caminho,metodo='GET',dados=None):
        self.fixture.chamadas.append((caminho,metodo,dados))
        if '/dependencies/blocked_by?' in caminho: return []
        if '/fields?' in caminho:
            return [{'id':1,'name':'Status','options':[{'id':9,'name':'Em andamento'},{'id':10,'name':'Em revisão'}]},
                    {'id':2,'name':'Time'}]+([{'id':3,'name':'Prioridade'}] if self.prioridades else [])
        if '/items?' in caminho:
            return [{'id':n,'content':{'html_url':'https://github.com/owner/jogo/issues/'+str(n)},
                     'fields':[{'id':1,'value':{'name':self.status[n]}},{'id':2,'value':self.equipes[n]}]+([{'id':3,'value':self.prioridades[n]}] if self.prioridades else [])} for n in self.status]
        if metodo=='PATCH':
            n=int(caminho.rsplit('/',1)[1]); valor=dados['fields'][0]['value']
            self.status[n]={9:'Em andamento',10:'Em revisão'}[valor]; return {}
        for n in self.status:
            if caminho.endswith('/issues/'+str(n)):
                return {'state':'open','title':'Tarefa '+str(n),'body':self.corpos[n]}
        if '/pulls?' in caminho:
            from urllib.parse import unquote
            n=next(n for n in self.status if 'feat/card-'+str(n) in unquote(caminho))
            return [{'number':n+100,'head':{'ref':'feat/card-'+str(n)},'body':'Closes #'+str(n),'draft':False}]
        raise AssertionError(caminho)

    def despacho(self,*args,**kw):
        def rodar(*a,**opcoes):
            self.modelos.append(args[1]); self.consoles.append(a[0].nome); self.prompts.append((Path(a[2]),opcoes['prompt'])); opcoes['ao_sessao']('native-'+str(args[1])); return 0
        return gc.despachar(*args,**kw,rodar=rodar)

    def test_previa_valida_git_sem_reserva_ou_movimento(self):
        r=gc.preparar_lote(self.raiz,self.plano,self.k)
        self.assertEqual([i['cartao'] for i in r['cartoes']],[42,43])
        self.assertEqual([i['git']['branch'] for i in r['cartoes']],['feat/card-42','feat/card-43'])
        self.assertFalse((gc.pasta_dados(self.raiz)/'tarefas.db').exists())
        self.assertFalse(gc.banco_worktrees(self.work/'42').exists())
        self.assertFalse(any(c[1]!='GET' for c in self.fixture.chamadas))

    def test_cli_sem_executar_so_prepara_plano_utf8(self):
        arquivo=self.work/'lote.json'; arquivo.write_text(json.dumps(self.plano),encoding='utf-8-sig')
        saida=io.StringIO()
        with patch.object(gc,'Kanban',return_value=self.k),redirect_stdout(saida):
            codigo=gc.main(['--projeto',str(self.raiz),'lote','--plano',str(arquivo)])
        self.assertEqual(codigo,0)
        self.assertTrue(json.loads(saida.getvalue())['somente_preparacao'])
        self.assertFalse((gc.pasta_dados(self.raiz)/'lotes').exists())
        self.assertEqual(self.modelos,[])

    def test_entradas_duplicadas_e_override_provider_rejeitados(self):
        for plano in ({'cartoes':[self.plano['cartoes'][0]]*2},
                      {'cartoes':[self.plano['cartoes'][0],{**self.plano['cartoes'][1],'worktree':self.plano['cartoes'][0]['worktree']}]},
                      {'cartoes':[{**self.plano['cartoes'][0],'console':'gemini'}]},
                      {'cartoes':[{'cartao':True,'worktree':str(self.work/'42')}]},
                      {'cartoes':[{'cartao':42,'worktree':'relativo'}]}):
            with self.subTest(plano=plano),self.assertRaises(ValueError):
                gc.preparar_lote(self.raiz,plano,self.k)
        self.assertFalse(self.fixture.chamadas)

    def test_ultimo_cartao_invalido_nao_executa_primeiro(self):
        self.corpos[43]='Sem aceite'
        with self.assertRaisesRegex(ValueError,'Aceite'):
            gc.executar_lote(self.raiz,self.plano,self.k,self.despacho)
        self.assertEqual(self.modelos,[]); self.assertFalse(any(c[1]!='GET' for c in self.fixture.chamadas))
        self.assertFalse((gc.pasta_dados(self.raiz)/'lotes').exists())

    def test_dois_despachos_reais_preservam_gates_e_sessoes(self):
        r=gc.executar_lote(self.raiz,self.plano,self.k,self.despacho)
        self.assertEqual(r['estado'],'processado'); self.assertEqual(self.modelos,[42,43])
        self.assertEqual(self.status,{42:'Em revisão',43:'Em revisão'})
        tarefas=Controle(gc.pasta_dados(self.raiz)/'tarefas.db').listar('owner/jogo')
        self.assertEqual({t['sessao'] for t in tarefas},{'native-42','native-43'})
        registro=Path(r['relatorio']).read_text(encoding='utf-8')
        self.assertNotIn('Testes passam',registro)
        for tarefa in tarefas: self.assertNotIn(tarefa['token'],registro)
        self.assertIsNone(r['cartao_em_execucao'])
        from gestao_painel import resumo
        lotes=resumo([self.raiz])['projetos'][0]['lotes']
        self.assertEqual(lotes['itens'][0]['estado'],'processado')
        self.assertEqual(lotes['itens'][0]['cartoes'],[42,43])
        self.assertNotIn(r['relatorio'],json.dumps(lotes))

    def test_bloqueio_interrompe_lote_sem_repetir(self):
        chamadas=[]
        def despacho(*args,**kw):
            chamadas.append(args[1]); return {'codigo':0,'estado':'bloqueado'}
        r=gc.executar_lote(self.raiz,self.plano,self.k,despacho)
        self.assertEqual(chamadas,[42]); self.assertEqual(r['estado'],'interrompido')
        self.assertEqual(len(r['resultados']),1)

    def test_cartao_mudando_depois_primeiro_nao_recebe_novo_prompt(self):
        def despacho(*args,**kw):
            r=self.despacho(*args,**kw)
            self.corpos[43]='**Aceite:** Outro aceite'
            return r
        with self.assertRaisesRegex(ValueError,'diverge do plano'):
            gc.executar_lote(self.raiz,self.plano,self.k,despacho)
        self.assertEqual(self.modelos,[42]); self.assertEqual(self.status[43],'Backlog')
        arquivos=list((gc.pasta_dados(self.raiz)/'lotes').glob('*.json'))
        r=json.loads(arquivos[0].read_text(encoding='utf-8'))
        self.assertEqual((r['estado'],r['cartao_em_execucao']),('incerto',43))
        self.assertEqual(len(r['resultados']),1)

    def test_worktree_ocupado_no_fim_impede_lote_inteiro(self):
        with ocupar_worktree(gc.banco_worktrees(self.work/'43'),self.work/'43'):
            with self.assertRaisesRegex(ValueError,'Worktree já ocupado'):
                gc.executar_lote(self.raiz,self.plano,self.k,self.despacho)
        self.assertEqual(self.modelos,[])
        self.assertFalse((gc.pasta_dados(self.raiz)/'lotes').exists())

    def test_reserva_existente_no_fim_nao_e_roubada(self):
        c=Controle(gc.pasta_dados(self.raiz)/'tarefas.db')
        token=c.reservar('owner/jogo','43','Dev','codex',{'objetivo':'x','aceite':'y'},True)
        with self.assertRaisesRegex(ValueError,'já reservado'):
            gc.executar_lote(self.raiz,self.plano,self.k,self.despacho)
        self.assertEqual(c.listar('owner/jogo')[0]['token'],token); self.assertEqual(self.modelos,[])

    def test_prioridade_aprovada_ordena_lote_sem_mudar_quadro(self):
        cfg=self.fixture.cfg; cfg['kanban']['prioridades']=['P0','P1','P2']
        (self.raiz/'.office/projeto.json').write_text(json.dumps(cfg),encoding='utf-8')
        self.prioridades={42:'P2',43:'P0'}
        r=gc.preparar_lote(self.raiz,self.plano,self.k)
        self.assertEqual([i['cartao'] for i in r['cartoes']],[43,42])
        self.assertFalse(any(c[1]!='GET' for c in self.fixture.chamadas))

    def test_equipes_de_consoles_distintos_usam_rota_canonica(self):
        cfg=self.fixture.cfg
        cfg['equipes'].append({'nome':'QA','especialidade':'Testes','executor':{'console':'gemini'}})
        (self.raiz/'.office/projeto.json').write_text(json.dumps(cfg),encoding='utf-8')
        self.equipes[43]='QA'
        with patch.object(gc,'selecionar',side_effect=lambda nome:(PROVIDERS[nome],nome)):
            r=gc.executar_lote(self.raiz,self.plano,self.k,self.despacho)
        self.assertEqual(r['estado'],'processado'); self.assertEqual(self.consoles,['codex','gemini'])
        tarefas=Controle(gc.pasta_dados(self.raiz)/'tarefas.db').listar('owner/jogo')
        self.assertEqual({(t['equipe'],t['console']) for t in tarefas},{('Dev','codex'),('QA','gemini')})

    def test_head_alterado_apos_primeiro_impede_segundo_modelo(self):
        def despacho(*args,**kw):
            r=self.despacho(*args,**kw)
            trabalho=self.work/'43'; (trabalho/'fixture.txt').write_text('novo commit',encoding='utf-8')
            self.git(trabalho,'add','fixture.txt')
            self.git(trabalho,'-c','user.name=Fixture','-c','user.email=fixture@example.com','commit','-m','mudou')
            return r
        with self.assertRaisesRegex(ValueError,'Branch/HEAD mudou'):
            gc.executar_lote(self.raiz,self.plano,self.k,despacho)
        self.assertEqual(self.modelos,[42]); self.assertEqual(self.status[43],'Backlog')
        self.assertEqual(len(Controle(gc.pasta_dados(self.raiz)/'tarefas.db').listar('owner/jogo')),1)
        with self.assertRaisesRegex(ValueError,'já ocupado'):
            with ocupar_worktree(gc.banco_worktrees(self.work/'43'),self.work/'43'): pass

    def test_worktree_divergente_recebe_referencia_da_raiz_canonica(self):
        regras=self.raiz/'CLAUDE.md'; regras.write_text('Regra canônica',encoding='utf-8')
        trabalho=self.work/'42'; (trabalho/'CLAUDE.md').write_text('Regra divergente',encoding='utf-8')
        self.git(trabalho,'add','CLAUDE.md')
        self.git(trabalho,'-c','user.name=Fixture','-c','user.email=fixture@example.com','commit','-m','regra local')
        r=gc.executar_lote(self.raiz,self.plano,self.k,self.despacho)
        self.assertEqual(r['estado'],'processado')
        self.assertEqual(self.prompts[0][0],trabalho)
        self.assertIn(json.dumps(regras.resolve().as_posix()),self.prompts[0][1])
        self.assertNotIn('Regra divergente',self.prompts[0][1])
        self.assertEqual((trabalho/'CLAUDE.md').read_text(encoding='utf-8'),'Regra divergente')
        self.assertEqual(regras.read_text(encoding='utf-8'),'Regra canônica')

    def test_interrupcao_registra_incerteza_sem_continuar(self):
        chamadas=[]
        def despacho(*args,**kw):
            chamadas.append(args[1]); raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt): gc.executar_lote(self.raiz,self.plano,self.k,despacho)
        self.assertEqual(chamadas,[42])
        arquivo=next((gc.pasta_dados(self.raiz)/'lotes').glob('*.json'))
        self.assertEqual(json.loads(arquivo.read_text(encoding='utf-8'))['estado'],'incerto')


    def test_paralelismo_validado_antes_da_consulta(self):
        for valor in (True,0,5,2.0,'2',None):
            with self.subTest(valor=valor),self.assertRaisesRegex(ValueError,'Paralelismo'):
                gc.preparar_lote(self.raiz,{**self.plano,'paralelismo':valor},self.k)
        self.assertFalse(self.fixture.chamadas)

    def test_clouds_concorrentes_com_gates_e_sessoes_reais(self):
        barreira=threading.Barrier(2,timeout=15)
        cfg=self.fixture.cfg
        cfg['equipes'].append({'nome':'QA','especialidade':'Testes','executor':{'console':'gemini'}})
        (self.raiz/'.office/projeto.json').write_text(json.dumps(cfg),encoding='utf-8')
        self.equipes[43]='QA'
        def despacho(*args,**kw):
            def rodar(*a,**opcoes):
                opcoes['ao_sessao']('native-'+str(args[1]))
                self.consoles.append(a[0].nome)
                barreira.wait()
                return 0
            return gc.despachar(*args,**kw,rodar=rodar)
        with patch.object(gc,'selecionar',side_effect=lambda nome:(PROVIDERS[nome],nome)):
            r=gc.executar_lote(self.raiz,{**self.plano,'paralelismo':2},self.k,despacho)
        self.assertEqual(r['estado'],'processado'); self.assertEqual(r['cartoes_em_execucao'],[])
        self.assertEqual(set(self.consoles),{'codex','gemini'})
        self.assertEqual(self.status,{42:'Em revisão',43:'Em revisão'})
        tarefas=Controle(gc.pasta_dados(self.raiz)/'tarefas.db').listar('owner/jogo')
        self.assertEqual({t['sessao'] for t in tarefas},{'native-42','native-43'})
        from gestao_painel import resumo
        painel=resumo([self.raiz])['projetos'][0]['lotes']
        self.assertEqual(painel['problemas'],0)
        self.assertEqual(painel['itens'][0]['paralelismo'],2)

    def test_falha_para_admissao_e_aguarda_iniciados(self):
        for excecao in (False,True):
            with self.subTest(excecao=excecao):
                barreira=threading.Barrier(2,timeout=5); liberar=threading.Event(); chamadas=[]
                registro={'cartoes':[42,43,44],'resultados':[],'cartoes_em_execucao':[]}
                preparado={'paralelismo':2,'cartoes':[{'cartao':n} for n in registro['cartoes']]}
                def salvar():
                    if registro['estado'] in ('incerto','interrompido'): liberar.set()
                def despacho(item):
                    n=item['cartao']; chamadas.append(n); barreira.wait()
                    if n==42:
                        if excecao: raise ValueError('falha nativa')
                        return {'estado':'bloqueado','codigo':1}
                    if not liberar.wait(5): raise AssertionError('Falha não registrada')
                    return {'estado':'revisao','codigo':0}
                if excecao:
                    with self.assertRaisesRegex(ValueError,'falha nativa'):
                        gc.executar_lote_paralelo(preparado,registro,salvar,despacho)
                    self.assertEqual(registro['estado'],'incerto')
                    self.assertEqual(registro['cartoes_em_execucao'],[42])
                else:
                    gc.executar_lote_paralelo(preparado,registro,salvar,despacho)
                    self.assertEqual(registro['estado'],'interrompido')
                    self.assertEqual(registro['cartoes_em_execucao'],[])
                self.assertEqual(set(chamadas),{42,43})
                self.assertEqual(registro['resultados'][-1],{'cartao':43,'estado':'revisao','codigo':0})

if __name__=='__main__': unittest.main()
