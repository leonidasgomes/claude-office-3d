"""Projeto filtra contadores e preços pela mesma identidade, sem mutar o histórico."""
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from unittest.mock import patch
from datetime import datetime,timezone
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from consumo_providers import Registro,Coletor,identidade_projeto
from gestao_projeto import validar
import gestao_painel

class ConsumoProjeto(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.raiz=Path(self.tmp.name);self.a=self.raiz/'a';self.b=self.raiz/'b'
        self.a.mkdir();self.b.mkdir();self.db=self.raiz/'uso.db'
        self.ts=datetime(2026,10,10,tzinfo=timezone.utc).timestamp()
        self.reg=Registro(self.db)
    def gravar(self,projeto,chave,total,ts=None):
        with patch('consumo_providers.time.time',return_value=self.ts if ts is None else ts):
            self.reg.gravar(chave,'codex','modelo','informado','Dev',identidade_projeto(projeto),'s',
                            'codex.exec/turn.completed',{'entrada':total,'cache':0,'saida':0,'total':total})
    def tarifa(self):
        tarifa={'provider':'codex','modelo':'modelo','desde':'2026-01-01','ate':'2026-12-31','fonte':'https://example.org/tarifa',
                'entrada_usd_milhao':'2','cache_usd_milhao':'1','saida_usd_milhao':'3'}
        (self.raiz/'precos_tokens.json').write_text(json.dumps({'versao':1,'tarifas':[tarifa]}),encoding='utf-8')
    def test_mesmo_grupo_filtra_tokens_e_preco_sem_vazamento(self):
        self.gravar(self.a,'a',1000000);self.gravar(self.b,'b',9000000);self.tarifa()
        antes=self.db.read_bytes()
        a=self.reg.resumo(self.ts,projeto_hash=identidade_projeto(self.a));b=self.reg.resumo(self.ts,projeto_hash=identidade_projeto(self.b))
        self.assertEqual((a['grupos'][0]['total'],a['grupos'][0]['equivalente_api_usd'],a['grupos'][0]['com_preco']),(1000000,'2',1))
        self.assertEqual((b['grupos'][0]['total'],b['grupos'][0]['equivalente_api_usd']),(9000000,'18'))
        self.assertEqual(self.reg.resumo(self.ts)['grupos'][0]['total'],10000000)
        self.assertEqual(self.reg.resumo(self.ts)['escopo'],'escritorio')
        self.assertEqual(self.db.read_bytes(),antes)
        self.assertNotIn(identidade_projeto(self.a),json.dumps(a));self.assertIsNone(a['cobranca_usd'])
    def test_limites_periodo_e_registros_sem_vinculo_excluidos(self):
        self.gravar(self.a,'velho',100,self.ts-7*86400-1);self.gravar(self.a,'futuro',100,self.ts+1)
        self.gravar(self.a,'inicio',2,self.ts-7*86400);self.gravar(self.a,'fim',3,self.ts)
        with patch('consumo_providers.time.time',return_value=self.ts):
            self.reg.gravar('historico','codex','modelo','informado','Dev','antigo','s','fonte',{'total':999})
        a=self.reg.resumo(self.ts,projeto_hash=identidade_projeto(self.a))
        self.assertEqual((a['grupos'][0]['total'],a['grupos'][0]['amostras']),(5,2))
    def test_coletor_usa_mesma_identidade_e_ausente_nao_cria_banco(self):
        vazio=Registro(self.raiz/'inexistente'/'db').resumo(self.ts,projeto_hash=identidade_projeto(self.a))
        self.assertEqual(vazio['grupos'],[]);self.assertEqual(vazio['escopo'],'projeto')
        self.assertFalse((self.raiz/'inexistente').exists())
        c=Coletor(self.db,'codex',self.a,'CEO')
        with patch('consumo_providers.time.time',return_value=self.ts):
            c.consumir({'type':'turn.completed','usage':{'input_tokens':4,'output_tokens':2}})
        a=self.reg.resumo(self.ts,projeto_hash=identidade_projeto(self.a))
        self.assertEqual(a['grupos'][0]['total'],6);self.assertEqual(a['grupos'][0]['agente'],'CEO')
        self.assertEqual(self.reg.resumo(self.ts,projeto_hash=identidade_projeto(self.b))['grupos'],[])
    def test_identidade_invalida_rejeitada_antes_de_sql(self):
        for valor in ('',"' OR 1=1 --",'f'*63,[],123):
            with self.subTest(valor=valor),self.assertRaises(ValueError):self.reg.resumo(self.ts,projeto_hash=valor)
        self.assertFalse(self.db.exists())
    def test_catalogo_invalido_preserva_contadores_do_projeto(self):
        self.gravar(self.a,'a',10);self.gravar(self.b,'b',999)
        (self.raiz/'precos_tokens.json').write_text('inválido',encoding='utf-8')
        a=self.reg.resumo(self.ts,projeto_hash=identidade_projeto(self.a))
        self.assertEqual(a['grupos'][0]['total'],10);self.assertEqual(a['precos']['estado'],'catálogo inválido')
    def test_painel_por_projeto_e_erro_do_ledger_nao_oculta_gestao(self):
        for projeto in (self.a,self.b):
            (projeto/'.office').mkdir();(projeto/'.office/projeto.json').write_text(json.dumps(validar({'ativo':True})),encoding='utf-8')
        self.gravar(self.a,'a',4);self.gravar(self.b,'b',9)
        with patch('consumo_providers.time.time',return_value=self.ts):dados=gestao_painel.resumo([self.a,self.b],banco_consumo=self.db)
        self.assertEqual([p['consumo']['grupos'][0]['total'] for p in dados['projetos']],[4,9])
        self.assertNotIn(str(self.raiz),json.dumps(dados))
        self.db.write_bytes(b'banco quebrado')
        dados=gestao_painel.resumo([self.a],banco_consumo=self.db)
        self.assertTrue(dados['projetos'][0]['ativo']);self.assertIn('erro',dados['projetos'][0]['consumo'])
    def test_http_gestao_entrega_consumo_isolado_dos_dois_projetos(self):
        import http.client,threading
        from functools import partial
        from http.server import ThreadingHTTPServer
        import servidor,rede,banco
        for projeto in (self.a,self.b):
            (projeto/'.office').mkdir();(projeto/'.office/projeto.json').write_text(json.dumps(validar({'ativo':True})),encoding='utf-8')
        self.gravar(self.a,'a',12);self.gravar(self.b,'b',120)
        self.db.rename(self.raiz/'consumo_providers.db')
        anterior=servidor.Handler.rede;servidor.Handler.rede=rede.Rede(self.raiz,False,False)
        srv=ThreadingHTTPServer(('127.0.0.1',0),partial(servidor.Handler,directory=str(Path(servidor.__file__).parent)))
        th=threading.Thread(target=srv.serve_forever,daemon=True);th.start()
        con=http.client.HTTPConnection('127.0.0.1',srv.server_address[1],timeout=10)
        try:
            with patch.object(banco,'ARQ',self.raiz/'escritorio.db'),patch.object(servidor,'cfg',return_value={'projetos':[self.a,self.b]}),patch('consumo_providers.time.time',return_value=self.ts):
                con.request('GET','/api/gestao');r=con.getresponse();dados=json.loads(r.read())
                self.assertEqual(r.status,200)
                self.assertEqual([p['consumo']['grupos'][0]['total'] for p in dados['projetos']],[12,120])
                self.assertNotIn(identidade_projeto(self.a),json.dumps(dados));self.assertNotIn(str(self.raiz),json.dumps(dados))
        finally:con.close();srv.shutdown();srv.server_close();th.join(5);servidor.Handler.rede=anterior

    def test_vinculo_transacional_idempotencia_e_recusa_de_reatribuicao(self):
        from concurrent.futures import ThreadPoolExecutor
        ident=identidade_projeto(self.a)
        def gravar(t):
            try:
                Registro(self.db,t).gravar('comum','codex','modelo','informado','Dev',ident,'s','codex.exec/turn.completed',{'entrada':10,'cache':0,'saida':2,'total':12})
                return t
            except ValueError:return None
        with ThreadPoolExecutor(4) as pool:resultados=list(pool.map(gravar,[c*32 for c in 'abcd']))
        dono=next(t for t in resultados if t)
        self.assertEqual(sum(t is not None for t in resultados),1)
        self.assertEqual(gravar(dono),dono)
        self.assertEqual(Registro(self.db).resumo(projeto_hash=ident)['grupos'][0]['amostras'],1)
        self.reg.gravar('antigo','codex','modelo','informado','Dev',ident,'s','fonte',{'total':99})
        with self.assertRaisesRegex(ValueError,'sem vínculo'):
            Registro(self.db,dono).gravar('antigo','codex','modelo','informado','Dev',ident,'s','fonte',{'total':2})
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual(db.execute('SELECT total FROM consumo WHERE chave=?',('antigo',)).fetchone()[0],99)
            self.assertEqual(db.execute('SELECT count(*) FROM consumo_tentativa').fetchone()[0],1)

    def test_lote_filtra_periodo_projeto_tentativa_e_preco_mesma_cobertura(self):
        ident=identidade_projeto(self.a);t1='a'*32;t2='b'*32
        def inserir(chave,projeto,t,valor,ts):
            with patch('consumo_providers.time.time',return_value=ts):
                Registro(self.db,t).gravar(chave,'codex','modelo','informado','Dev',identidade_projeto(projeto),'s','codex.exec/turn.completed',{'entrada':valor,'cache':0,'saida':0,'total':valor})
        inserir('1',self.a,t1,1000000,self.ts);inserir('2',self.a,t2,2000000,self.ts)
        inserir('3',self.b,t1,9000000,self.ts);inserir('4',self.a,t1,7000000,self.ts-7*86400-1)
        self.gravar(self.a,'sem-vinculo',8000000);self.tarifa();antes=self.db.read_bytes()
        lote=self.reg.resumos_tentativas([t1,t2],ident,self.ts)
        self.assertEqual(lote[t1]['grupos'][0]['total'],1000000)
        self.assertEqual(lote[t1]['grupos'][0]['equivalente_api_usd'],'2')
        self.assertEqual(lote[t2]['grupos'][0]['equivalente_api_usd'],'4')
        for t in (t1,t2):
            self.assertEqual(lote[t]['grupos'],self.reg.resumo(self.ts,ident,[t])['grupos'])
        self.assertEqual(self.db.read_bytes(),antes)
        (self.raiz/'precos_tokens.json').write_text('inválido',encoding='utf-8')
        lote=self.reg.resumos_tentativas([t1],ident,self.ts)
        self.assertEqual(lote[t1]['precos']['estado'],'catálogo inválido')
        self.assertEqual(lote[t1]['grupos'][0]['total'],1000000)

    def test_ausencia_e_argumentos_invalidos_nao_criam_historico(self):
        ident=identidade_projeto(self.a)
        self.assertEqual(self.reg.resumos_tentativas(['a'*32],ident,self.ts),{})
        self.assertFalse(self.db.exists())
        for ids in ([],['invalido'],['a'*32]*2,['a'*32]*1001):
            with self.subTest(ids=len(ids)),self.assertRaises(ValueError):self.reg.resumos_tentativas(ids,ident,self.ts)
        self.gravar(self.a,'legado',55);antes=self.db.read_bytes()
        self.assertEqual(self.reg.resumos_tentativas(['a'*32],ident,self.ts),{})
        self.assertEqual(self.reg.resumo(self.ts,ident,['a'*32])['grupos'],[])
        self.assertEqual(self.db.read_bytes(),antes)

    def test_todos_coletores_ligam_contadores_sem_duplicar_saldos(self):
        from consumo_providers import ColetorRollout
        t='c'*32;ident=identidade_projeto(self.a)
        claude=Coletor(self.db,'claude',self.a,'Dev',sessao_claude_nova='claude-s',tentativa=t)
        claude.consumir({'type':'system','subtype':'init','session_id':'claude-s'})
        result={'type':'result','session_id':'claude-s','is_error':False,'modelUsage':{'modelo':{'inputTokens':3,'cacheReadInputTokens':2,'cacheCreationInputTokens':1,'outputTokens':4}}}
        claude.consumir(result);claude.consumir(result)
        codex=Coletor(self.db,'codex',self.a,'Dev',tentativa=t)
        codex.consumir({'type':'turn.completed','usage':{'input_tokens':5,'output_tokens':2,'cached_input_tokens':1}})
        gemini=Coletor(self.db,'gemini',self.a,'Dev',tentativa=t)
        gemini.consumir({'type':'result','stats':{'models':{'g':{'input_tokens':4,'output_tokens':1,'cached':0,'total_tokens':5}}}})
        oc=Coletor(self.db,'opencode',self.a,'Dev',tentativa=t)
        oc.consumir({'type':'step_finish','sessionID':'o','part':{'type':'step-finish','sessionID':'o','id':'part','tokens':{'input':1,'output':1,'reasoning':0,'cache':{'read':0,'write':0}}}})
        rollout=ColetorRollout(self.db,self.a,'Filho','codex-s',True,tentativa=t)
        rollout.consumir({'type':'event_msg','payload':{'type':'token_count','info':{'total_token_usage':{'input_tokens':3,'cached_input_tokens':1,'output_tokens':2,'total_tokens':5}}}})
        grupos=self.reg.resumos_tentativas([t],ident)[t]['grupos']
        self.assertEqual(sum(g['total'] for g in grupos),29)
        self.assertEqual(sum(g['amostras'] for g in grupos),5)
        with closing(sqlite3.connect(self.db)) as db:self.assertEqual(db.execute('SELECT count(*) FROM consumo_tentativa').fetchone()[0],5)

    def test_launcher_real_vincula_e_painel_nao_expoe_identidades(self):
        import contextlib,io
        import console_provider,gestao_cli
        from providers_console import PROVIDERS
        from controle_tarefas import Controle
        (self.a/'.office').mkdir();(self.a/'.office/projeto.json').write_text(json.dumps(validar({'ativo':True,'kanban':{'repo':'owner/repo'}})),encoding='utf-8')
        tarefa_db=self.raiz/'tarefas.db';controle=Controle(tarefa_db)
        token=controle.reservar('owner/repo','42','Dev','codex',{'objetivo':'teste','aceite':'teste','executor':{'console':'codex','modelo':'configurado'}},True)
        controle.transicao(token,'executando');tentativa=controle.iniciar_execucao(token)
        fake=self.raiz/'fake.py'
        fake.write_text("import sys,json\nsys.stdin.read()\nfor e in "+repr([{'type':'thread.started','thread_id':'privada'}, {'type':'turn.started'}, {'type':'turn.completed','usage':{'input_tokens':8,'output_tokens':2,'cached_input_tokens':0}}])+":print(json.dumps(e),flush=True)\n",encoding='utf-8')
        with patch('providers_console.comando_nativo',return_value=[sys.executable,str(fake)]),patch('console_provider.contexto',return_value='regras'),contextlib.redirect_stdout(io.StringIO()):
            codigo=console_provider.executar(PROVIDERS['codex'],'fake',self.a,'Dev',prompt='teste',banco=self.raiz/'eventos.db',tentativa_consumo=tentativa)
        self.assertEqual(codigo,0);controle.terminar_execucao(tentativa,codigo,12)
        ledger=self.raiz/'consumo_providers.db'
        with patch.object(gestao_painel,'pasta_dados',return_value=self.raiz):dados=gestao_painel.resumo([self.a],banco_consumo=ledger)
        p=dados['projetos'][0];g=p['desempenho']['grupos'][0]
        self.assertEqual(g['tentativas_com_consumo'],1);self.assertEqual(g['consumo_observado']['total'],10)
        self.assertEqual(p['tarefas'][0]['ultima_execucao']['consumo']['grupos'][0]['total'],10)
        for privado in (tentativa,token,'privada',identidade_projeto(self.a),str(self.raiz),'_tentativa'):
            self.assertNotIn(privado,json.dumps(dados))
        ledger.write_bytes(b'quebrado')
        with patch.object(gestao_painel,'pasta_dados',return_value=self.raiz):p=gestao_painel.resumo([self.a],banco_consumo=ledger)['projetos'][0]
        self.assertTrue(p['ativo']);self.assertIn('consumo_erro',p['desempenho'])
        self.assertNotIn(tentativa,json.dumps(p))

if __name__=='__main__':unittest.main()
