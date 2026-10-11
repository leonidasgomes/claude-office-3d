"""Metas verificáveis, sem consumo pago nem alterações em projetos reais."""
import copy
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from contextlib import closing
import unittest
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import gestao_cli as gc
import metas_cartao as m
import politica_painel as p
from gestao_projeto import validar
from consumo_providers import Registro,identidade_projeto


class Metas(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.raiz=Path(self.tmp.name);(self.raiz/'.office').mkdir()
        self.cfg=validar({'ativo':True,'fontes':{'produto':'PRODUTO.md'},'kanban':{'repo':'owner/repo'},
            'metas':{'ativo':True,'tempo_min':1,'tokens':1000}})
        (self.raiz/'PRODUTO.md').write_text('#### Objetivo 1 — Navegar\nEntregar #42 e #50.\n#### Objetivo 2 — NPCs\nEntregar #60.\n',encoding='utf-8')
        (self.raiz/'CLAUDE.md').write_text('Preservar gates.',encoding='utf-8')
        self.arq=self.raiz/'.office/projeto.json';self.arq.write_text(json.dumps(self.cfg),encoding='utf-8')
        self.issue={'title':'Navegar','body':'**Aceite:** teste real','html_url':'https://github.com/owner/repo/issues/42'}
        self.cartao={'numero':42,'equipe':'Dev'}
        self.pacote={**gc.instrucoes_cartao(self.issue),'cartao':42,'url':self.issue['html_url'],'dependencias':{'verificadas_em':1,'bloqueadores':[]}}
        self.meta=m.construir(self.raiz,self.cfg,self.cartao,self.issue,self.pacote)
        self.dados=self.raiz/'dados';self.ledger=self.raiz/'consumo.db';self.ident='a'*32

    def test_meta_kanban_gdd_sem_inventar_objetivo_ou_mudar_aceite(self):
        self.assertEqual(self.meta['gdd']['numero'],1);self.assertEqual(self.meta['aceite'],'teste real')
        self.assertEqual(len(self.meta['gdd']['sha256']),64)
        self.assertNotIn('verificadas_em',self.meta['dependencias'])
        novo=copy.deepcopy(self.pacote);novo['dependencias']['verificadas_em']=99
        self.assertEqual(m.construir(self.raiz,self.cfg,self.cartao,self.issue,novo),self.meta)
        with self.assertRaisesRegex(ValueError,'vincule'):
            m.construir(self.raiz,self.cfg,{**self.cartao,'numero':43},self.issue,self.pacote)
        issue={**self.issue,'body':'**Objetivo GDD:** 2\n\n**Aceite:** teste real'}
        with self.assertRaisesRegex(ValueError,'divergente'):m.construir(self.raiz,self.cfg,self.cartao,issue,self.pacote)
        self.assertEqual(m.construir(self.raiz,self.cfg,{**self.cartao,'numero':43},issue,self.pacote)['gdd']['numero'],2)
        self.assertIsNone(m.construir(self.raiz,{**self.cfg,'metas':{**self.cfg['metas'],'ativo':False}},self.cartao,self.issue,self.pacote))

    def test_ledger_idempotente_isolado_e_ausencia_nao_zero(self):
        self.assertEqual(m.tokens_observados(self.ledger,self.raiz,self.ident),(None,'sem_amostras'))
        registro=Registro(self.ledger,tentativa=self.ident)
        def gravar(chave,total,projeto=None):
            registro.gravar(chave,'codex','modelo','configurado','Dev',identidade_projeto(projeto or self.raiz),'sessao','teste',
                            {'entrada':900,'cache':800,'saida':100,'total':total})
        gravar('x',1000);gravar('x',1000)
        self.assertEqual(m.tokens_observados(self.ledger,self.raiz,self.ident),(1000,'observado'))
        self.assertEqual(m.tokens_observados(self.ledger,self.raiz,'b'*32),(None,'sem_amostras'))
        self.assertEqual(m.tokens_observados(self.ledger,self.raiz/'outro',self.ident),(None,'sem_amostras'))
        gravar('parcial',None)
        self.assertEqual(m.tokens_observados(self.ledger,self.raiz,self.ident),(1000,'parcial'))

    def test_classificacao_gdd_so_com_recibo_e_escopo_de_planejamento(self):
        proposta={'titulo':'Classificar vínculo','equipe':'Dev','objetivo':'Investigar vínculo do pai',
                  'aceite':'Decisão documentada com fontes','skills':'nenhuma'}
        issue={'title':proposta['titulo'],'body':
            'Parte de #99. <!-- office-desbloqueio:99 -->\n\n'
            '**Objetivo:** '+proposta['objetivo']+'\n\n**Aceite:** '+proposta['aceite']+
            '\n\n**Escopo:** Planejamento/investigação deste bloqueio; não implementar o pai.'
            '\n\n**Skills:** nenhuma\n\n**Objetivo GDD:** classificação a confirmar'}
        cartao={'numero':43,'equipe':'Dev'}
        pacote={**gc.instrucoes_cartao(issue),'cartao':43,'url':'https://github.com/owner/repo/issues/43',
                'dependencias':{'bloqueadores':[]}}
        pasta=self.dados/'desbloqueios';pasta.mkdir(parents=True);arquivo=pasta/'99.json'
        registro={'estado':'criado','pai':99,'numero':43,'proposta':proposta}
        with patch('gestao_cli.pasta_dados',return_value=self.dados):
            with self.assertRaises(ValueError):m.construir(self.raiz,self.cfg,cartao,issue,pacote)
            arquivo.write_text(json.dumps(registro),encoding='utf-8')
            meta=m.construir(self.raiz,self.cfg,cartao,issue,pacote)
            self.assertIsNone(meta['gdd']['numero']);self.assertEqual(meta['gdd']['pai'],99)
            self.assertIn('Objetivo 1',meta['gdd']['trecho']);self.assertIn('Objetivo 2',meta['gdd']['trecho'])
            self.assertEqual(meta['limites'],self.meta['limites'])
            for campo,valor in (('estado','criando'),('numero',44),('pai',98)):
                arquivo.write_text(json.dumps({**registro,campo:valor}),encoding='utf-8')
                with self.assertRaises(ValueError):m.construir(self.raiz,self.cfg,cartao,issue,pacote)
            arquivo.write_text(json.dumps(registro),encoding='utf-8')
            with self.assertRaises(ValueError):m.construir(self.raiz,self.cfg,cartao,issue,{**pacote,'escopo':'Implementar o pai'})
            with self.assertRaises(ValueError):m.construir(self.raiz,self.cfg,{**cartao,'equipe':'Outra'},issue,pacote)

    def test_tempo_tokens_incerto_e_revisao_sem_conclusao_falsa(self):
        agora=[0];total=[None]
        e=m.Execucao(self.raiz,self.dados,self.ident,self.meta,self.ledger,relogio=lambda:agora[0],leitor=lambda *_:(total[0],'sem_amostras'))
        self.assertIsNone(e.conferir());total[0]=1000
        self.assertEqual(e.conferir(),'limite_tokens');e.finalizar('em_revisao')
        self.assertEqual(json.loads(e.arquivo.read_text())['estado'],'limite_tokens')
        with self.assertRaisesRegex(ValueError,'existente'):
            m.Execucao(self.raiz,self.dados,self.ident,self.meta,self.ledger)
        total[0]=None
        e=m.Execucao(self.raiz,self.dados,'b'*32,self.meta,self.ledger,relogio=lambda:agora[0],leitor=lambda *_:(None,'indisponivel'))
        agora[0]=60;self.assertEqual(e.conferir(),'limite_tempo')
        e=m.Execucao(self.raiz,self.dados,'c'*32,self.meta,self.ledger,relogio=lambda:agora[0],leitor=lambda *_:(None,'sem_amostras'))
        agora[0]=61;e.encerrar_medicao();agora[0]=1000;e.finalizar('em_revisao',pr=12)
        r=json.loads(e.arquivo.read_text());self.assertEqual(r['estado'],'em_revisao');self.assertEqual(r['tempo_seg'],1)
        publico=m.resumo(self.dados);self.assertNotIn('trecho',json.dumps(publico));self.assertNotIn(str(self.raiz),json.dumps(publico))
        self.assertIsNone(next(x for x in publico['itens'] if x['pr']==12)['tokens_observados'])

    def test_monitor_interrompe_apenas_processo_recebido(self):
        encerrados=[];processo=SimpleNamespace(pid=123,poll=lambda:None)
        e=m.Execucao(self.raiz,self.dados,self.ident,self.meta,self.ledger,leitor=lambda *_:(1000,'observado'),encerrar=lambda p:encerrados.append(p))
        with e.vigiar(processo,intervalo=.01):
            import time
            for _ in range(100):
                if encerrados:break
                time.sleep(.01)
        self.assertEqual(encerrados,[processo]);self.assertEqual(e.motivo,'limite_tokens')

    def test_console_real_simulado_interrompido_sem_chamada_cloud(self):
        import console_provider,contextlib,io
        from providers_console import PROVIDERS
        fake=self.raiz/'fake.py'
        ev={'type':'step_finish','sessionID':'sessao','part':{'id':'part1','sessionID':'sessao',
            'type':'step-finish','reason':'tool-calls','tokens':{'input':900,'output':100,'reasoning':0,'cache':{'read':0,'write':0}}}}
        fake.write_text('import time\nprint('+repr(json.dumps(ev))+',flush=True)\ntime.sleep(60)\n',encoding='utf-8')
        consumo=self.raiz/'consumo_providers.db'
        e=m.Execucao(self.raiz,self.dados,self.ident,self.meta,consumo)
        with patch('providers_console.comando_nativo',return_value=[sys.executable,str(fake)]),contextlib.redirect_stdout(io.StringIO()):
            codigo=console_provider.executar(PROVIDERS['opencode'],'fake',self.raiz,'Dev',prompt='teste',
                        banco=self.raiz/'eventos.db',projeto_consumo=self.raiz,tentativa_consumo=self.ident,limites_meta=e)
        self.assertNotEqual(codigo,0);self.assertEqual(e.motivo,'limite_tokens')
        self.assertEqual(e.registro['tokens_observados'],1000)

    def test_politica_pc_hash_sem_tocar_gates_e_bloqueio_em_execucao(self):
        novo={'ativo':True,'tempo_min':60,'tokens':100000};hash=p.snapshot(self.raiz)[1]
        pedido={'projeto_id':__import__('funcionarios').id_projeto(self.raiz),'versao':hash,'metas':novo}
        with patch('gestao_cli.pasta_dados',return_value=self.dados):
            self.assertEqual(p.api_metas([self.raiz],pedido,{'permissao':'celular'})[0],403)
            self.assertEqual(p.api_metas([],pedido,{'permissao':'pc'})[0],400)
            self.dados.mkdir();estado=self.dados/'ciclo.json';estado.write_text('{"estado":"implementando"}')
            antes=self.arq.read_bytes();self.assertEqual(p.api_metas([self.raiz],pedido,{'permissao':'pc'})[0],409)
            self.assertEqual(antes,self.arq.read_bytes());estado.write_text('{"estado":"limite"}')
            self.assertEqual(p.api_metas([self.raiz],pedido,{'permissao':'pc'})[0],200)
            atual=p.snapshot(self.raiz)[0]
            for k in set(atual)-{'metas'}:self.assertEqual(atual[k],self.cfg[k])
            self.assertEqual(p.api_metas([self.raiz],pedido,{'permissao':'pc'})[0],409)
            banco=self.dados/'tarefas.db'
            with closing(sqlite3.connect(banco)) as db,db:
                db.execute('CREATE TABLE reserva(projeto TEXT,estado TEXT)');db.execute("INSERT INTO reserva VALUES ('owner/repo','executando')")
            with self.assertRaisesRegex(p.Conflito,'tarefa'):
                p.atualizar_metas(self.raiz,p.snapshot(self.raiz)[1],{**novo,'tempo_min':30})
        for mudanca in ({'ativo':1},{'tempo_min':0},{'tempo_min':True},{'tokens':999},{'tokens':10000001},{'tokens':1.5}):
            with self.assertRaises(ValueError):validar({**self.cfg,'metas':{**novo,**mudanca}})

    def test_despacho_persiste_meta_e_limite_bloqueia_entrega_mesmo_saida_zero(self):
        from testar_despacho_revisao import DespachoRevisao
        for esgotado in (False,True):
            f=DespachoRevisao();f.setUp()
            try:
                f.cfg['metas']={'ativo':True,'tempo_min':60,'tokens':1000}
                f.cfg['fontes']['produto']='PRODUTO.md';f.cfg['revisao']['ativo']=False
                (f.pasta/'PRODUTO.md').write_text('#### Objetivo 1 — Navegar\nCartão #42.\n',encoding='utf-8')
                (f.pasta/'CLAUDE.md').write_text('Regras',encoding='utf-8')
                (f.pasta/'.office/projeto.json').write_text(json.dumps(f.cfg),encoding='utf-8')
                recebidos=[]
                def rodar(*args,**kw):
                    e=kw['limites_meta'];recebidos.append(kw['prompt'])
                    if esgotado:e.leitor=lambda *_:(1000,'observado')
                    return 0
                with patch('gestao_cli.pasta_dados',return_value=f.pasta/'dados'):
                    r=f.executar(lambda *_:None,rodar=rodar)
                self.assertIn('Meta deste cartão',recebidos[0])
                registros=m.resumo(f.pasta/'dados')['itens'];self.assertEqual(len(registros),1)
                self.assertEqual(r['estado'],'bloqueado' if esgotado else 'revisao')
                self.assertEqual(registros[0]['estado'],'limite_tokens' if esgotado else 'em_revisao')
                self.assertEqual(f.moves,['Em andamento'] if esgotado else ['Em andamento','Em revisão'])
            finally:f.doCleanups()


if __name__=='__main__':unittest.main()
