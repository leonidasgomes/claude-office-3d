"""CRUD por projeto: concorrência, vínculos e histórico; sem modelos/GitHub reais."""
import copy, json, sqlite3, sys, tempfile, unittest
from pathlib import Path
from contextlib import closing
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import cadastro_gestao as c
import funcionarios as f
from gestao_projeto import validar
from politica_painel import snapshot, Conflito

class Cadastros(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);(self.root/'.office').mkdir()
        self.cfg=validar({'ativo':True,'equipes':[{'nome':'Dev','especialidade':'Código','executor':{'console':'codex','modelo':'modelo'}}]})
        self.arq=self.root/'.office/projeto.json';self.arq.write_text(json.dumps(self.cfg),encoding='utf-8')
        self.data=self.root/'app';self.data.mkdir()
        self.patcher=patch('gestao_cli.pasta_dados',return_value=self.data);self.patcher.start();self.addCleanup(self.patcher.stop)
        self.team={'nome':'Pesquisa','especialidade':'História','executor':{'console':'codex','modelo':'modelo'}}
        self.staff={'nome':'Ana','funcao':'Pesquisa','equipe':'Dev','executor':{'console':'codex','modelo':'modelo'},'skills':[]}
    def pedido(self,**kw):
        return {'projeto_id':f.id_projeto(self.root),'versao':snapshot(self.root)[1],**kw}
    def call(self,**kw):
        return c.api([self.root],self.pedido(**kw),{'permissao':'pc'})
    def pendente(self,item):
        with closing(sqlite3.connect(self.data/'tarefas.db')) as db,db:
            db.execute('CREATE TABLE reserva (projeto TEXT,equipe TEXT,pacote TEXT,estado TEXT)')
            db.execute('INSERT INTO reserva VALUES (?,?,?,?)',(self.cfg['kanban']['repo'],'Dev',json.dumps({'funcionario':item}),'bloqueado'))
    def test_equipe_criar_editar_excluir_preserva_politica(self):
        original=self.arq.read_bytes()
        self.assertEqual(self.call(tipo='equipe',acao='criar',equipe=self.team)[0],200)
        novo=snapshot(self.root)[0]
        for chave in set(novo)-{'equipes'}:self.assertEqual(novo[chave],self.cfg[chave])
        backups=list((self.root/'.office/historico-politica').glob('*.json'));self.assertEqual(backups[0].read_bytes(),original)
        self.assertEqual(self.call(tipo='equipe',acao='editar',nome='Pesquisa',equipe={**self.team,'especialidade':'Fontes'})[0],200)
        self.assertEqual(self.call(tipo='equipe',acao='excluir',nome='Pesquisa')[0],200)
        self.assertEqual(snapshot(self.root)[0],self.cfg)
    def test_equipe_duplicada_rename_e_versao_desatualizada(self):
        pedido=self.pedido(tipo='equipe',acao='criar',equipe=self.team)
        self.assertEqual(c.api([self.root],pedido,{'permissao':'pc'})[0],200)
        self.assertEqual(c.api([self.root],pedido,{'permissao':'pc'})[0],409)
        self.assertEqual(self.call(tipo='equipe',acao='criar',equipe={**self.team,'nome':'pesquisa'})[0],400)
        self.assertEqual(self.call(tipo='equipe',acao='editar',nome='Pesquisa',equipe={**self.team,'nome':'Nova'})[0],400)
    def test_funcionario_editar_conflito_excluir_preserva_identidade_historico(self):
        item=f.cadastrar(self.root,self.staff)
        edit={**self.staff,'nome':'Ana Maria'}
        status,result=self.call(tipo='funcionario',acao='editar',id=item['id'],anterior={**item,'perfil_nativo':{'estado':'ausente'}},funcionario=edit)
        self.assertEqual(status,200);atual=result['funcionario'];self.assertEqual(atual['id'],item['id'])
        self.assertEqual(self.call(tipo='funcionario',acao='editar',id=item['id'],anterior=item,funcionario=edit)[0],409)
        self.assertEqual(self.call(tipo='funcionario',acao='excluir',id=item['id'],anterior=atual)[0],200)
        self.assertEqual(f.listar(self.root),[])
        arquivado=f.listar(self.root,True)[0];self.assertTrue(arquivado['arquivado']);self.assertEqual(arquivado['id'],item['id'])
        with self.assertRaises(ValueError):f.obter(self.root,item['id'])
        with closing(sqlite3.connect(f.arquivo(self.root))) as db:self.assertEqual(db.execute('SELECT count(*) FROM funcionario_historico').fetchone()[0],2)
        recriado=f.cadastrar(self.root,{**self.staff,'nome':atual['nome']})
        self.assertNotEqual(recriado['id'],item['id'])
        self.assertEqual(f.listar(self.root),[recriado])
    def test_vinculos_pendentes_bloqueiam_sem_alterar(self):
        item=f.cadastrar(self.root,self.staff);self.pendente(item);original=self.arq.read_bytes()
        self.assertEqual(self.call(tipo='funcionario',acao='excluir',id=item['id'],anterior=item)[0],400)
        self.assertEqual(self.call(tipo='funcionario',acao='editar',id=item['id'],anterior=item,funcionario=self.staff)[0],400)
        self.assertEqual(self.call(tipo='equipe',acao='editar',nome='Dev',equipe=self.cfg['equipes'][0])[0],400)
        self.assertEqual(self.arq.read_bytes(),original);self.assertEqual(f.listar(self.root),[item])
    def test_equipe_com_funcionario_ou_kanban_nao_exclui(self):
        f.cadastrar(self.root,self.staff)
        self.assertEqual(self.call(tipo='equipe',acao='excluir',nome='Dev')[0],400)
        self.cfg['kanban'].update(repo='exemplo/projeto',owner='exemplo',numero=1);self.arq.write_text(json.dumps(self.cfg),encoding='utf-8')
        self.call(tipo='equipe',acao='criar',equipe=self.team)
        with patch('kanban_gestao.Kanban.cartoes',return_value=[{'equipe':'Pesquisa','status':'Backlog'}]) as quadro:
            self.assertEqual(self.call(tipo='equipe',acao='excluir',nome='Pesquisa')[0],400);quadro.assert_called_once_with(ao_vivo=True)
        self.assertTrue(any(e['nome']=='Pesquisa' for e in snapshot(self.root)[0]['equipes']))
    def test_colisao_nome_nao_perde_cadastro_e_api_pc(self):
        item=f.cadastrar(self.root,self.staff);f.cadastrar(self.root,{**self.staff,'nome':'Bia'})
        self.assertEqual(self.call(tipo='funcionario',acao='editar',id=item['id'],anterior=item,funcionario={**self.staff,'nome':'Bia'})[0],400)
        self.assertEqual(f.obter(self.root,item['id']),item)
        pedido=self.pedido(tipo='equipe',acao='criar',equipe=self.team)
        self.assertEqual(c.api([self.root],pedido,{'permissao':'celular'})[0],403)
        self.assertEqual(c.api([],pedido,{'permissao':'pc'})[0],400)
        self.assertEqual(c.api([self.root],{**pedido,'inesperado':1},{'permissao':'pc'})[0],400)

    def test_http_origin_header_e_gravacao_real(self):
        import http.client, threading
        from functools import partial
        from http.server import ThreadingHTTPServer
        import servidor, rede
        antigo=servidor.Handler.rede;servidor.Handler.rede=rede.Rede(self.root,False,False)
        srv=ThreadingHTTPServer(('127.0.0.1',0),partial(servidor.Handler,directory=str(Path(servidor.__file__).parent)))
        th=threading.Thread(target=srv.serve_forever,daemon=True);th.start()
        con=http.client.HTTPConnection('127.0.0.1',srv.server_address[1],timeout=10)
        pedido=self.pedido(tipo='equipe',acao='criar',equipe=self.team)
        host=f'127.0.0.1:{srv.server_address[1]}'
        h={'Host':host,'Content-Type':'application/json','Origin':'https://externa.invalid','X-Office-Acao':'1','Connection':'close'}
        try:
            with patch.object(servidor,'cfg',return_value={'projetos':[self.root]}):
                for origin,acao,esperado in [('https://externa.invalid','1',403),('http://'+host,'',403),('http://'+host,'1',200)]:
                    h['Origin']=origin
                    if acao:h['X-Office-Acao']=acao
                    else:h.pop('X-Office-Acao',None)
                    con.request('POST','/api/gestao/cadastros',json.dumps(pedido),h)
                    r=con.getresponse();body=r.read();self.assertEqual(r.status,esperado,body)
            self.assertTrue(any(e['nome']=='Pesquisa' for e in snapshot(self.root)[0]['equipes']))
        finally:
            con.close();srv.shutdown();srv.server_close();th.join(5);servidor.Handler.rede=antigo

if __name__=='__main__':unittest.main()
