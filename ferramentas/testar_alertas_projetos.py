"""Fontes/estado/fila reais; GitHub simulado, entrega de notificações não acionada."""
import json,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
import testar_sugestoes_projeto
import alertas,alertas_projetos,xp_projeto,sugestoes_bot as sb


class Projetos(testar_sugestoes_projeto.Sugestoes):
    def setUp(self):
        super().setUp();self.opc=alertas.normalizar_opcoes({});self.est={}
    def fontes(self):return alertas_projetos.fontes(self.base)
    def passo(self):return alertas.detectar(self.est,{'projetos':self.fontes()},1000000,self.opc)
    def nova(self,p,id_='8'):
        c=self.cfg(p);x=sb.ler_caixa(c)[0].copy();x.update(id=id_,situacao='nova')
        sb.gravar_caixa(c,sb.ler_caixa(c)+[x])
    def test_baseline_projetos_mesmo_id_e_dedup(self):
        for p in (self.a,self.b):self.coletar(self.cfg(p))
        self.assertEqual(self.passo(),[])
        for p in (self.a,self.b):self.nova(p)
        novos=self.passo();self.assertEqual(len(novos),2)
        self.assertEqual({a['repo'] for a in novos},{'owner/a','owner/b'})
        self.assertEqual(len({a['chave'] for a in novos}),2)
        for a in novos:self.assertIn('&projeto='+a['projeto_id'],a['url'])
        self.assertEqual(self.passo(),[])
    def test_erro_coleta_nao_apaga_baseline(self):
        c=self.cfg();self.coletar(c);self.passo()
        est=sb.ler_estado(c);est['erro']='API fora';sb.gravar_estado(c,est)
        antes=json.dumps(self.est,sort_keys=True);self.assertEqual(self.passo(),[])
        self.assertEqual(json.dumps(self.est,sort_keys=True),antes)
        est['erro']='';sb.gravar_estado(c,est);self.assertEqual(self.passo(),[])
        self.nova(self.a);self.assertEqual(len(self.passo()),1)
    def test_repo_trocado_nova_base_sem_repetir(self):
        self.coletar(self.cfg());self.passo()
        arq=self.a/'.office/projeto.json';d=json.loads(arq.read_text());d['kanban']['repo']='owner/novo';arq.write_text(json.dumps(d))
        self.coletar(self.cfg());self.assertEqual(self.passo(),[])
        self.nova(self.a);novos=self.passo();self.assertEqual(len(novos),1);self.assertEqual(novos[0]['repo'],'owner/novo')
    def test_fontes_somente_leitura_nao_criam_dados(self):
        self.fontes();self.assertFalse((self.raiz/'app').exists())
    def test_placar_versao_exata_e_alerta_conferir(self):
        self.base['xp']['ativo']=True;ctx=xp_projeto.contexto(self.a,self.base)
        ctx['pasta'].mkdir(parents=True)
        d={'repo':'owner/a','projeto_id':ctx['id'],'politica_versao':ctx['versao'],'agentes':{'Dev':{'conferir':[]}}}
        ctx['placar'].write_text(json.dumps(d));self.passo()
        d['agentes']['Dev']['conferir']=[{'pr':42}];ctx['placar'].write_text(json.dumps(d))
        a=self.passo();self.assertEqual(len(a),1);self.assertEqual((a[0]['tipo'],a[0]['repo']),('conferir','owner/a'))
        d['politica_versao']='0'*64;d['agentes']['Dev']['conferir']=[];ctx['placar'].write_text(json.dumps(d))
        self.assertEqual(self.passo(),[])
        d['politica_versao']=ctx['versao'];d['agentes']['Dev']['conferir']=[{'pr':42}];ctx['placar'].write_text(json.dumps(d))
        self.assertEqual(self.passo(),[])
    def test_servico_nao_chama_globais_em_gestao_e_reinicio(self):
        self.coletar(self.cfg());fontes={'projetos':self.fontes}
        for nome in ('prs','placar','eventos','escalonamentos','sugestoes','saude'):
            fontes[nome]=lambda *a:(_ for _ in ()).throw(AssertionError('Fonte global chamada'))
        a=alertas.Alertas(self.raiz/'fila',fontes,{'imediatos':[]})
        self.assertEqual(a.passo(1000000),[]);self.nova(self.a)
        self.assertEqual(len(a.passo(1000001)),1)
        b=alertas.Alertas(self.raiz/'fila',fontes,{'imediatos':[]})
        self.assertEqual(b.passo(1000002),[]);fila,_=b.listar();self.assertEqual(len(fila),1)
        self.assertEqual(fila[0]['projeto_id'],self.cfg()['projeto_id'])
    def test_detector_rejeita_fontes_globais_com_gestao(self):
        ent={'projetos':{'ativo':True,'projetos':[]},'sugestoes':{'ativo':True,'itens':[]}}
        alertas.detectar(self.est,ent,1000000,self.opc)
        ent['sugestoes']['itens']=[{'id':'7','prioridade':'P0','pr':42}]
        self.assertEqual(alertas.detectar(self.est,ent,1000001,self.opc),[])
        self.assertNotIn('sug',self.est)
    def test_sem_politica_mantem_legacy(self):
        for p in (self.a,self.b):(p/'.office/projeto.json').unlink()
        self.assertFalse(self.fontes()['ativo'])
        ent={'projetos':self.fontes(),'sugestoes':{'ativo':True,'itens':[]}}
        alertas.detectar(self.est,ent,1000000,self.opc)
        ent['sugestoes']['itens']=[{'id':'7','prioridade':'P0','pr':42}]
        self.assertEqual(len(alertas.detectar(self.est,ent,1000001,self.opc)),1)
    def test_push_preserva_so_id_opaco_nos_paineis_permitidos(self):
        import push
        for painel in ('prs','placar','gestao'):
            url='/#alerta='+painel+'&projeto='+'a'*20;self.assertEqual(push.url_relativa(url),url)
        for url in ('/#alerta=prs&projeto=D:/segredo','/#alerta=prs&projeto='+'a'*20+'&url=https://fora',
                    '/#alerta=saude&projeto='+'a'*20):self.assertEqual(push.url_relativa(url),'/')
    def test_caixa_corrompida_nao_apaga_estado(self):
        c=self.cfg();self.coletar(c);self.passo();antes=json.dumps(self.est,sort_keys=True)
        caixa=c['pasta']/'caixa.jsonl';original=caixa.read_bytes();caixa.write_text('{incompleto')
        self.assertEqual(self.passo(),[]);self.assertEqual(json.dumps(self.est,sort_keys=True),antes)
        caixa.write_bytes(original);self.assertEqual(self.passo(),[])

if __name__=='__main__':unittest.main()
