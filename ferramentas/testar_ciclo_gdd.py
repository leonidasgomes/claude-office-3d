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
        for cambio in ({'max_cartoes':3},{'duracao_min':True},{'intervalo_seg':0},{'ativo':True,'base':'-x'}):
            with self.assertRaises(ValueError):validar({'ciclo':cambio})

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
        with self.assertRaises(ValueError):c.validar_decisao(json.dumps({'decisoes':[self.decisao(1,'executar')]}),[candidato],self.cfg)
        d=self.decisao(1,'desbloquear');d['subtarefa']={'titulo':'x','equipe':'inventada','objetivo':'x','aceite':'x','skills':'nenhuma'}
        with self.assertRaises(ValueError):c.validar_decisao(json.dumps({'decisoes':[d]}),[candidato],self.cfg)

    def test_nao_reinicia_sessao_incerta(self):
        c.atomico(c.caminho_estado(self.p),{'estado':'erro'})
        with self.assertRaisesRegex(ValueError,'existente/incerto'):c.iniciar(self.p)

    def test_inicio_windows_fecha_lock_e_impede_duplicacao(self):
        with patch.object(c.subprocess,'Popen',return_value=Mock(pid=123)) as criar:
            r=c.iniciar(self.p)
            self.assertEqual(r['pid'],123)
            self.assertFalse(c.caminho_estado(self.p).with_suffix('.inicio.lock').exists())
            with self.assertRaises(ValueError):c.iniciar(self.p)
            self.assertEqual(criar.call_count,1)

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
        def lote(p,plano):
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


if __name__=='__main__':unittest.main()
