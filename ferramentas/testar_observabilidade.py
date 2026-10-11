"""Fixtures offline: formatos Codex, cursores SSE, intervalos e cotas vencidas."""
from contextlib import closing
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from codex_observador import Transcrito,origem_filho,origem_interna
from emit_evento import normalizar
from eventos_sse import lote,servir,CLIENTES
from observabilidade_equipes import etapa,esperas,registrar_operacoes,operacoes,entregas,etapa_reserva
from uso_providers import validade,normalizar_limites


class Observabilidade(unittest.TestCase):
    def test_paginado_contexto_e_deduplicacao(self):
        eventos=[];t=Transcrito('Dev',eventos.append)
        t.consumir({'type':'session_meta','payload':{'id':'sessao','history_mode':'paginated'}})
        t.consumir({'type':'response_item','payload':{'type':'message','role':'assistant','content':[{'type':'output_text','text':'contexto antigo'}]}})
        t.consumir({'type':'response_item','payload':{'type':'function_call','call_id':'a','name':'exec_command','arguments':'{"cmd":"pytest"}'}})
        reg={'type':'event_msg','payload':{'type':'item_completed','item':{'type':'CommandExecution','id':'a','command':['pytest'],'exit_code':1}}}
        t.consumir(reg);t.consumir(reg)
        t.consumir({'type':'response_item','payload':{'type':'function_call_output','call_id':'a','output':'Exit code: 1'}})
        self.assertEqual(len(eventos),2)
        self.assertEqual(normalizar(eventos[-1])['operacao_estado'],'concluido')
        self.assertEqual(eventos[-1]['codigo'],1)

    def test_resultado_sem_inicio_nao_inventa_sucesso(self):
        eventos=[];t=Transcrito('Dev',eventos.append)
        t.item_concluido({'type':'McpToolCall','id':'b','status':'completed'})
        self.assertNotIn('ok',eventos[0])
        self.assertNotIn('inicio',eventos[0])
        t.item_concluido({'type':'AgentMessage','id':'m','content':[{'text':'feito'}]})
        t.item_concluido({'type':'AgentMessage','id':'m','content':[{'text':'feito'}]})
        self.assertEqual(len(eventos),2)

    def test_segundo_plano_consulta_mesmo_comando(self):
        eventos=[];t=Transcrito('Dev',eventos.append)
        def chamada(ident,nome,args):t.consumir({'type':'response_item','payload':{'type':'function_call','call_id':ident,'name':nome,'arguments':json.dumps(args)}})
        def resultado(ident,saida):t.consumir({'type':'response_item','payload':{'type':'function_call_output','call_id':ident,'output':saida}})
        chamada('a','exec_command',{'cmd':'pytest'})
        resultado('a','Process running with session ID 42')
        chamada('b','write_stdin',{'session_id':42})
        resultado('b','Process exited with code 0')
        self.assertEqual([e['operacao_id'] for e in eventos],['a','a','a'])
        self.assertEqual([e['operacao_estado'] for e in eventos],['executando','segundo_plano','concluido'])

    def test_fontes_internas_e_variantes(self):
        meta={'source':{'subAgent':{'threadSpawn':{'parentThreadId':'p','agentNickname':'QA'}}}}
        self.assertEqual(origem_filho(meta)['parent_thread_id'],'p')
        self.assertTrue(origem_interna(meta))
        self.assertTrue(origem_interna({'source':{'subagent':'memory_consolidation'}}))
        self.assertFalse(origem_interna({'source':{'custom':'cliente'}}))

    def test_cursor_mais_de_uma_pagina_e_corrompido(self):
        with tempfile.TemporaryDirectory() as tmp:
            arq=Path(tmp)/'b.db'
            with closing(sqlite3.connect(arq)) as db,db:
                db.execute('CREATE TABLE evento(id INTEGER PRIMARY KEY,dados TEXT)')
                db.executemany('INSERT INTO evento VALUES (?,?)',[(i,'{}' if i!=13 else 'quebrado') for i in range(1,451)])
            cursor=0;ids=[]
            while cursor<450:
                total,eventos=lote(arq,cursor);ids.extend(i for i,_ in eventos);cursor=eventos[-1][0]
            self.assertEqual(ids,list(range(1,451)));self.assertEqual(total,450)

    def test_sse_envelope_limite_e_liberacao(self):
        class Handler:
            def __init__(self):self.wfile=io.BytesIO();self.connection=self;self.headers={}
            def settimeout(self,v):pass
            def send_response(self,v):self.status=v
            def send_header(self,k,v):self.headers[k]=v
            def end_headers(self):pass
            def responder(self,corpo,codigo):self.status=codigo
        with tempfile.TemporaryDirectory() as tmp:
            h=Handler()
            with patch('eventos_sse.time.monotonic',side_effect=[0,0,0,130]),patch('eventos_sse.time.sleep'):
                servir(h,Path(tmp)/'b.db',0,tmp)
            self.assertEqual(h.status,200)
            self.assertIn(b'event: batida',h.wfile.getvalue())
            self.assertEqual(h.headers['Cache-Control'],'no-cache, no-store')
            for _ in range(8):self.assertTrue(CLIENTES.acquire(False))
            try:
                cheio=Handler();servir(cheio,Path(tmp)/'b.db',0,tmp)
                self.assertEqual(cheio.status,503)
            finally:
                for _ in range(8):CLIENTES.release()

    def test_espera_fechada_sem_duplicar_batidas_ou_ciclos(self):
        with tempfile.TemporaryDirectory() as tmp:
            arq=Path(tmp)/'b.db'
            etapa(arq,'a','diretor',10,[{'cartao':1}])
            etapa(arq,'a','diretor',15,[{'cartao':1}])
            etapa(arq,'b','aguardando',16,[])
            etapa(arq,'a','implementando',20,[{'cartao':1}])
            with closing(sqlite3.connect(arq)) as db:r=esperas(db)
            self.assertEqual(r['segundos'],10)
            self.assertEqual(len(r['intervalos']),1)

    def test_operacoes_historicas_nao_sao_ativas(self):
        with closing(sqlite3.connect(':memory:')) as db:
            db.execute('CREATE TABLE execucao_tarefa(id TEXT,token TEXT,fim REAL)')
            db.execute("INSERT INTO execucao_tarefa VALUES ('e','t',NULL)")
            registrar_operacoes(db,'e',{('s','a'):{'ferramenta':'Bash','inicio':10,'fim':None,'estado':'segundo_plano','codigo':None}})
            self.assertEqual(operacoes(db,'t',True,30)[0]['duracao_seg'],20)
            op=operacoes(db,'t',False,30)[0]
            self.assertEqual(op['estado'],'sem_retorno');self.assertIsNone(op['duracao_seg'])
            self.assertEqual(operacoes(db,'outra',True,30),[])

    def test_cota_vencida_nao_e_zero_nem_atual(self):
        original=normalizar_limites({'rateLimits':{'secondary':{'usedPercent':90,'windowDurationMins':10080,'resetsAt':200}}},100)
        nova=validade(original,201)
        j=nova['limites'][0]['janelas'][0]
        self.assertIsNone(j['usado_pct']);self.assertIsNone(j['restante_pct'])
        self.assertEqual(j['ultimo_usado_pct'],90);self.assertFalse(j['atual'])
        self.assertEqual(original['limites'][0]['janelas'][0]['usado_pct'],90)
        self.assertTrue(validade(original,101,falhou=True)['desatualizado'])
        self.assertTrue(validade(original,401)['desatualizado'])

    def test_pr_aberto_nao_conta_como_entrega(self):
        with closing(sqlite3.connect(':memory:')) as db:
            self.assertEqual(entregas(db,'a/b','inexistente','.' )['merges'],0)

    def test_revisao_fechada_e_merge_sem_duplicar_tokens(self):
        with closing(sqlite3.connect(':memory:')) as db:
            db.execute('CREATE TABLE reserva(token TEXT,cartao TEXT,projeto TEXT,estado TEXT)')
            db.execute('CREATE TABLE conclusao(token TEXT,evidencia TEXT,atualizado REAL)')
            db.execute('CREATE TABLE execucao_tarefa(id TEXT,token TEXT)')
            db.executemany('INSERT INTO reserva VALUES (?,?,?,?)',[('t','1','a/b','concluido'),('u','2','a/b','revisao')])
            db.execute('INSERT INTO conclusao VALUES (?,?,1)',('t',json.dumps({'merge_commit':'a'*40,'merged_at':'data'})))
            db.execute("INSERT INTO execucao_tarefa VALUES ('e','t')")
            etapa_reserva(db,'t','revisao',10);etapa_reserva(db,'t','concluido',40)
            self.assertEqual(esperas(db)['segundos'],30)
            with patch('consumo_providers.Registro.resumos_tentativas',return_value={'e':{'grupos':[{'total':80,'com_total':1}]}}):
                r=entregas(db,'a/b','inexistente','.')
            self.assertEqual(r['merges'],1);self.assertEqual(r['tokens_por_merge'],80)

    def test_rota_sse_preserva_guarda_remota(self):
        import servidor
        from unittest.mock import Mock
        h=servidor.Handler.__new__(servidor.Handler)
        h.client_address=('203.0.113.1',1);h.path='/eventos/ao-vivo';h.rede=None
        h._negar=Mock()
        with patch('eventos_sse.servir') as stream:
            h.do_GET();stream.assert_not_called()
        self.assertEqual(h._negar.call_args.args[0],403)


if __name__=='__main__':unittest.main()
