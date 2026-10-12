import hashlib,json,sqlite3,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import recursos_host as h
from controle_tarefas import Controle
from gestao_projeto import validar


class Assets(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.proj=self.root/'projeto';self.proj.mkdir()
        self.office=self.root/'office';self.office.mkdir();self.dados=self.root/'dados';self.dados.mkdir()
        self.work=self.root/'worktrees'/'cartao';self.work.parent.mkdir()
        self.cfg=validar({'ativo':True,'ciclo':{'ativo':True,'base':'origin/main'},'kanban':{'repo':'o/r'}})
        self.conteudo=b'asset local verificado';self.oid=hashlib.sha256(self.conteudo).hexdigest()
        self.pointer=f'version https://git-lfs.github.com/spec/v1\noid sha256:{self.oid}\nsize {len(self.conteudo)}\n'.encode()
        self.git(self.proj,'init','-b','main');self.git(self.proj,'config','user.name','Teste')
        self.git(self.proj,'config','user.email','teste@example.com')
        (self.proj/'mapa.umap').write_bytes(self.pointer)
        self.git(self.proj,'add','.');self.git(self.proj,'commit','-m','base')
        self.git(self.proj,'worktree','add','-b','work/cartao',str(self.work),'main')
        self.cache=self.proj/'.git/lfs/objects'/self.oid[:2]/self.oid[2:4]/self.oid
        self.cache.parent.mkdir(parents=True);self.cache.write_bytes(self.conteudo)
        r=self.office/'dados/worktrees';r.mkdir(parents=True)
        (r/'recibo.json').write_text(json.dumps({'projeto':str(self.proj),'estado':'criado',
             'criados':[{'cartao':7,'worktree':str(self.work),'branch':'work/cartao'}]}),encoding='utf-8')
        self.ctrl=Controle(self.dados/'tarefas.db')
        pacote={'objetivo':'mapa','aceite':'validar','contexto_execucao':{'worktree':str(self.work),
            'branch':'work/cartao','politica_sha256':hashlib.sha256(json.dumps(self.cfg,sort_keys=True,ensure_ascii=False).encode()).hexdigest()}}
        self.token=self.ctrl.reservar('o/r','7','Dev','codex',pacote,quadro_atual=True)
        self.ctrl.transicao(self.token,'executando');self.tentativa=self.ctrl.iniciar_execucao(self.token)
        for p in (patch.object(h,'RAIZ',self.office),patch('gestao_cli.pasta_dados',return_value=self.dados),
                  patch('gestao_projeto.carregar',return_value=self.cfg)):
            p.start();self.addCleanup(p.stop)
        self.pedido={'cartao':7,'worktree':str(self.work),'arquivos':['mapa.umap']}

    def git(self,p,*args):
        return subprocess.run(['git','-C',str(p),*args],capture_output=True,check=True).stdout

    def test_hidrata_so_asset_versionado_do_cache_sem_git_ou_checkout_principal_alterados(self):
        antes=self.git(self.proj,'rev-parse','HEAD');origem=(self.proj/'mapa.umap').read_bytes()
        r=h.hidratar_lfs(self.proj,self.pedido)
        self.assertEqual(r['estado'],'preparado');self.assertEqual(r['hidratados'][0]['oid'],self.oid)
        self.assertEqual((self.work/'mapa.umap').read_bytes(),self.conteudo)
        self.assertEqual((self.proj/'mapa.umap').read_bytes(),origem)
        self.assertEqual(self.git(self.proj,'rev-parse','HEAD'),antes)
        self.assertEqual(self.git(self.work,'rev-parse','HEAD'),antes)

    def test_hidrata_sem_apis_adicionadas_no_python_311_e_312(self):
        with patch.object(Path,'is_junction',None,create=True),patch.object(hashlib,'file_digest',None,create=True):
            self.test_hidrata_so_asset_versionado_do_cache_sem_git_ou_checkout_principal_alterados()

    def test_nao_hidrata_cache_corrompido_nem_repete_preparacao_incerta(self):
        antes=(self.work/'mapa.umap').read_bytes()
        self.cache.write_bytes(b'x'*len(self.conteudo))
        with self.assertRaisesRegex(ValueError,'corrompido'):h.hidratar_lfs(self.proj,self.pedido)
        self.assertEqual((self.work/'mapa.umap').read_bytes(),antes)
        self.cache.write_bytes(self.conteudo)
        with self.assertRaisesRegex(ValueError,'anterior'):h.hidratar_lfs(self.proj,self.pedido)

    def test_rejeita_ausente_modificado_nao_versionado_e_caminhos_escapando(self):
        self.cache.unlink()
        with self.assertRaisesRegex(ValueError,'cache'):h.hidratar_lfs(self.proj,self.pedido)
        self.cache.write_bytes(self.conteudo)
        (self.work/'mapa.umap').write_bytes(b'alterado')
        with self.assertRaisesRegex(ValueError,'modificado'):h.hidratar_lfs(self.proj,self.pedido)
        for caminho in ('../mapa.umap','/mapa.umap','C:/mapa.umap','.git/config','novo.umap'):
            with self.assertRaises((ValueError,subprocess.CalledProcessError)):
                h.hidratar_lfs(self.proj,{**self.pedido,'arquivos':[caminho]})
        self.assertFalse((self.dados/'assets').exists())

    def test_reserva_encerrada_ou_projeto_principal_nao_recebe_assets(self):
        with self.assertRaisesRegex(ValueError,'separado'):
            h.hidratar_lfs(self.proj,{**self.pedido,'worktree':str(self.proj)})
        self.ctrl.terminar_execucao(self.tentativa,0,1)
        with self.assertRaisesRegex(ValueError,'tentativa'):h.hidratar_lfs(self.proj,self.pedido)
        self.ctrl.transicao(self.token,'bloqueado')
        with self.assertRaisesRegex(ValueError,'reserva'):h.hidratar_lfs(self.proj,self.pedido)

    def test_travas_so_com_autorizacao_do_projeto_e_equipes(self):
        from recursos_host import diretorios_travas
        cfg=validar({**self.cfg,'equipes':[{'nome':'Dev','especialidade':'Código','executor':{'console':'codex'}},
                                       {'nome':'QA','especialidade':'Testes','executor':{'console':'codex'}}]})
        self.assertEqual(diretorios_travas(self.proj,self.dados,cfg,'Dev'),[])
        p=self.root/'travas';p.mkdir()
        r={'projeto':str(self.proj),'politica':hashlib.sha256(json.dumps(cfg,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),
           'origem':'Autorização do operador para a bancada','equipes':['Dev'],'travas':str(p)}
        f=self.dados/'recursos_escrita.json';f.write_text(json.dumps(r),encoding='utf-8')
        self.assertEqual(diretorios_travas(self.proj,self.dados,cfg,'Dev'),[p])
        self.assertEqual(diretorios_travas(self.proj,self.dados,cfg,'QA'),[])
        for caminho in (str(self.root),str(self.root/'worktrees'),str(self.proj)):
            f.write_text(json.dumps({**r,'travas':caminho}),encoding='utf-8')
            with self.assertRaises(ValueError):diretorios_travas(self.proj,self.dados,cfg,'Dev')
        f.write_text(json.dumps({**r,'politica':'a'*64}),encoding='utf-8')
        with self.assertRaises(ValueError):diretorios_travas(self.proj,self.dados,cfg,'Dev')

    def test_politica_antiga_informa_diretor_sem_liberar_travas(self):
        cfg=validar({'ativo':True,'equipes':[{'nome':'Dev','especialidade':'Código','executor':{'console':'codex'}}]})
        p=self.root/'travas';p.mkdir()
        r={'projeto':str(self.proj),'politica':'a'*64,'origem':'Autorização anterior',
           'equipes':['Dev'],'travas':str(p)}
        f=self.dados/'recursos_escrita.json';f.write_text(json.dumps(r),encoding='utf-8');antes=f.read_bytes()
        with self.assertRaises(h.PoliticaRecursosDivergente):h.diretorios_travas(self.proj,self.dados,cfg,'Dev')
        contexto=h.contexto_travas(self.proj,self.dados,cfg)
        self.assertEqual(contexto['travas_por_equipe'],{'Dev':[]})
        self.assertEqual(contexto['pendencias'][0]['recurso'],'travas')
        self.assertEqual(f.read_bytes(),antes);self.assertEqual(list(p.iterdir()),[])
        f.write_text(json.dumps({**r,'travas':str(self.proj)}),encoding='utf-8')
        with self.assertRaises(ValueError):h.contexto_travas(self.proj,self.dados,cfg)


if __name__=='__main__':unittest.main()
