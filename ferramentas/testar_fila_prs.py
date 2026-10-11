import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from fila_prs import validar,planejar,projetar,versao_politica
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

if __name__=='__main__':unittest.main()
