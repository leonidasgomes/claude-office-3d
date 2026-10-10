"""Coordenação real do controlador com worktrees Git; respostas cloud simuladas."""
import copy
import json
import io
from contextlib import redirect_stdout
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import coordenacao as c
import gestao_cli as gc
from coordenacao_registro import resumo as recibos
import testar_diretor_lotes as fixtures


class Coordenacao(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.Lotes();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.chamadas=[]
        cfg=self.f.fixture.cfg
        cfg['ceo']={'console':'codex','modelo':'modelo-ceo','execucao':'cloud'}
        cfg['diretor']={'console':'gemini','modelo':'modelo-diretor','execucao':'cloud'}
        (self.f.raiz/'.office/projeto.json').write_text(json.dumps(cfg),encoding='utf-8')

    def chamada(self,rota,prompt):
        self.chamadas.append((rota,prompt))
        return {'cartoes':[42,43] if len(self.chamadas)==1 else [43],'motivo':'Dentro do objetivo','bloqueios':[]}

    def rodar(self,**kw):
        return c.coordenar(self.f.raiz,self.f.plano,'Corrigir o marco aprovado',kanban=self.f.k,
                           chamar=self.chamada,despacho=self.f.despacho,**kw)

    def test_previa_sem_inferencia_reserva_ou_mutacao(self):
        r=self.rodar();self.assertTrue(r['somente_preparacao']);self.assertEqual(self.chamadas,[])
        self.assertFalse((gc.pasta_dados(self.f.raiz)/'tarefas.db').exists())
        self.assertFalse(any(x[1]!='GET' for x in self.f.fixture.chamadas))

    def test_consulta_ceo_diretor_e_reduz_sem_mudar_caminhos(self):
        r=self.rodar(consultar=True)
        self.assertEqual(r['estado'],'organizado')
        self.assertEqual(r['plano']['cartoes'],[self.f.plano['cartoes'][1]])
        self.assertEqual([x[0]['console'] for x in self.chamadas],['codex','gemini'])
        self.assertFalse(any(x[1]!='GET' for x in self.f.fixture.chamadas))
        recibo=recibos(self.f.raiz,'owner/jogo')['itens'][0]
        self.assertEqual(recibo['id'],r['recibo_id']);self.assertEqual(recibo['estado'],'organizado')
        self.assertEqual(recibo['diretor']['cartoes'],[43])

    def test_execucao_vai_pelo_lote_comum_apenas_selecao(self):
        r=self.rodar(executar=True)
        self.assertEqual(r['estado'],'processado')
        self.assertEqual(self.f.modelos,[43])
        self.assertEqual(self.f.status,{42:'Backlog',43:'Em revisão'})
        recibo=recibos(self.f.raiz,'owner/jogo')['itens'][0]
        self.assertEqual(recibo['estado'],'processado');self.assertEqual(recibo['lote_id'],r['lote']['id'])

    def test_diretor_nao_amplia_selecao(self):
        def chamar(rota,prompt):
            self.chamadas.append(rota)
            return {'cartoes':[42] if len(self.chamadas)==1 else [43],'motivo':'Teste','bloqueios':[]}
        with self.assertRaisesRegex(ValueError,'autorizados'):
            c.coordenar(self.f.raiz,self.f.plano,'Objetivo',consultar=True,kanban=self.f.k,chamar=chamar)
        self.assertEqual(self.f.modelos,[])

    def test_mudanca_kanban_entre_papeis_bloqueia(self):
        def chamar(rota,prompt):
            self.f.corpos[42]='**Aceite:** Outro aceite'
            return {'cartoes':[42],'motivo':'Teste','bloqueios':[]}
        with self.assertRaisesRegex(ValueError,'mudaram'):
            c.coordenar(self.f.raiz,self.f.plano,'Objetivo',consultar=True,kanban=self.f.k,chamar=chamar)
        self.assertFalse(any(x[1]!='GET' for x in self.f.fixture.chamadas))
        recibo=recibos(self.f.raiz,'owner/jogo')['itens'][0]
        self.assertEqual(recibo['estado'],'incerto');self.assertEqual(recibo['ceo']['cartoes'],[42])

    def test_bloqueio_ceo_nao_chama_diretor_ou_despacho(self):
        def chamar(*_):
            self.chamadas.append(1);return {'cartoes':[42],'motivo':'Falta decisão','bloqueios':['Escopo incerto']}
        r=c.coordenar(self.f.raiz,self.f.plano,'Objetivo',executar=True,kanban=self.f.k,chamar=chamar)
        self.assertEqual(r['estado'],'bloqueado');self.assertEqual(self.chamadas,[1]);self.assertEqual(self.f.modelos,[])
        self.assertEqual(recibos(self.f.raiz,'owner/jogo')['itens'][0]['estado'],'bloqueado')

    def test_schema_rejeita_comandos_duplicatas_booleanos_e_cartoes_externos(self):
        base={'cartoes':[42],'motivo':'Teste','bloqueios':[]}
        for item in ({**base,'comando':'git merge'}, {**base,'cartoes':[True]},
                     {**base,'cartoes':[42,42]}, {**base,'cartoes':[999]}):
            with self.assertRaises(ValueError):c.selecionar(item,{42})
        with self.assertRaisesRegex(ValueError,'repetido'):c.resposta('{"cartoes":[],"cartoes":[42]}')

    def test_lote_nao_aceita_snapshot_divergente(self):
        esperado=gc.preparar_lote(self.f.raiz,self.f.plano,self.f.k)
        errado=copy.deepcopy(esperado);errado['cartoes'][0]['git']['sha']='a'*40
        with self.assertRaisesRegex(ValueError,'diverge'):
            gc.executar_lote(self.f.raiz,self.f.plano,self.f.k,self.f.despacho,esperado=errado)
        self.assertEqual(self.f.modelos,[])

    def test_cli_previa_utf8_sem_inferencia(self):
        plano=self.f.work/'plano.json';plano.write_text(json.dumps(self.f.plano),encoding='utf-8-sig')
        objetivo=self.f.work/'objetivo.txt';objetivo.write_text('Organizar o marco',encoding='utf-8-sig')
        with patch.object(gc,'Kanban',return_value=self.f.k),patch('revisores_console.chamar') as chamar,redirect_stdout(io.StringIO()) as saida:
            codigo=gc.main(['--projeto',str(self.f.raiz),'coordenar','--plano',str(plano),'--solicitacao',str(objetivo)])
        self.assertEqual(codigo,0);self.assertTrue(json.loads(saida.getvalue())['somente_preparacao']);chamar.assert_not_called()

    def test_cli_lote_interrompido_nao_retorna_sucesso(self):
        plano=self.f.work/'plano.json';plano.write_text(json.dumps(self.f.plano),encoding='utf-8')
        objetivo=self.f.work/'objetivo.txt';objetivo.write_text('Objetivo',encoding='utf-8')
        with patch('coordenacao.coordenar',return_value={'estado':'interrompido'}),redirect_stdout(io.StringIO()):
            codigo=gc.main(['--projeto',str(self.f.raiz),'coordenar','--plano',str(plano),'--solicitacao',str(objetivo),'--executar'])
        self.assertEqual(codigo,1)

    def test_versao_painel_revalidada_apos_ceo(self):
        from politica_painel import snapshot
        versao=snapshot(self.f.raiz)[1]
        chamadas=[]
        def chamar(*args):
            chamadas.append(1)
            p=self.f.raiz/'.office/projeto.json';cfg=json.loads(p.read_text(encoding='utf-8'))
            p.write_text(json.dumps(cfg,indent=2),encoding='utf-8')
            return {'cartoes':[42],'motivo':'Teste','bloqueios':[]}
        with self.assertRaisesRegex(ValueError,'Política diverge'):
            c.coordenar(self.f.raiz,self.f.plano,'Objetivo',consultar=True,kanban=self.f.k,chamar=chamar,versao_politica=versao)
        self.assertEqual(chamadas,[1]);self.assertEqual(self.f.modelos,[])

    def test_opencode_default_ou_local_nao_inicia_modelo_fora_admissao(self):
        p=self.f.raiz/'.office/projeto.json';cfg=json.loads(p.read_text(encoding='utf-8'))
        for modelo in ('','local/modelo','ollama/modelo'):
            cfg['ceo']={'console':'opencode','modelo':modelo,'execucao':'cloud'}
            p.write_text(json.dumps(cfg),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'modelo cloud explícito'):self.rodar(consultar=True)
        self.assertEqual(self.chamadas,[])


if __name__=='__main__':unittest.main()
