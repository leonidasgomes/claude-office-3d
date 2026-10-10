"""Perfis dos quatro consoles, arquivos/SQLite reais; sem inferência."""
from pathlib import Path
import json,os,subprocess,sys,tomllib,unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import agentes_nativos as a
import funcionarios as f
import testar_funcionarios as fixtures


class Perfis(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.Cadastro();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.raiz=self.fixture.raiz
    def membro(self,console='codex',**extras):
        modelo='opencode/space-bunny-free' if console=='opencode' else 'modelo-explicito'
        dados={**self.fixture.dados,'nome':'Especialista '+console,'executor':{'console':console,'modelo':modelo},**extras}
        return f.cadastrar(self.raiz,dados)
    def test_quatro_formatos_idempotencia_e_contexto_atual_sem_copiar_skills(self):
        for console in ('claude','codex','opencode','gemini'):
            with self.subTest(console=console):
                item=self.membro(console,funcao='Texto "com aspas"\n---\nname: não altera o cabeçalho')
                p=a.preparar(self.raiz,item['id']);destino=self.raiz/p['arquivo']
                self.assertFalse(destino.exists());self.assertEqual(p['estado'],'ausente')
                if console=='codex':
                    meta=tomllib.loads(p['conteudo']);self.assertEqual(meta['name'],p['nome'])
                    self.assertIn('--contexto',meta['developer_instructions'])
                else:
                    cab=p['conteudo'].split('\n---\n',1)[0].splitlines()[1:]
                    meta={k:json.loads(v) for k,v in (linha.split(': ',1) for linha in cab)}
                    self.assertEqual(meta.get('mode'),'all' if console=='opencode' else None)
                self.assertEqual(meta['model'],item['executor']['modelo'])
                self.assertNotIn('permissionMode',meta);self.assertNotIn('sandbox_mode',meta);self.assertNotIn('tools',meta)
                self.assertTrue(a.aplicar(self.raiz,item['id'],p['confirmacao'])['criado'])
                novo=a.preparar(self.raiz,item['id']);antes=destino.read_bytes()
                self.assertFalse(a.aplicar(self.raiz,item['id'],novo['confirmacao'])['criado'])
                self.assertEqual(destino.read_bytes(),antes)
                self.assertIn(item['funcao'],a.contexto(self.raiz,item['id']))
                self.assertEqual(list((self.raiz/'.claude/skills').glob('*/SKILL.md')),[self.raiz/'.claude/skills/historia/SKILL.md'])
    def test_modelo_vazio_herda_exceto_opencode_sem_modelo_explicito(self):
        for console in ('claude','codex','gemini','opencode'):
            item=self.membro(console,executor={'console':console})
            if console=='opencode':
                with self.assertRaisesRegex(ValueError,'explícito'):a.preparar(self.raiz,item['id'])
            else:self.assertNotIn('model',a.preparar(self.raiz,item['id'])['conteudo'].split('\n---\n')[0])
    def test_estado_no_painel_e_somente_leitura_e_isola_perfil_invalido(self):
        from gestao_painel import resumo
        itens=[self.membro(c) for c in ('claude','codex','opencode','gemini')]
        sem_modelo=self.membro('opencode',nome='Sem modelo',executor={'console':'opencode'})
        def arquivos():
            return {str(p.relative_to(self.raiz)):p.read_bytes() for p in self.raiz.rglob('*') if p.is_file()}
        antes=arquivos()
        for item in itens:
            estado=a.resumo(self.raiz,item['id'])
            self.assertEqual(estado['estado'],'ausente')
            self.assertEqual(set(estado),{'estado','console','arquivo'})
        self.assertEqual(a.resumo(self.raiz,sem_modelo['id']),{'estado':'indisponivel'})
        painel=resumo([self.raiz],banco_consumo=self.raiz/'consumo-ausente.db')['projetos'][0]
        self.assertNotIn('erro',painel)
        self.assertEqual({x['perfil_nativo']['estado'] for x in painel['funcionarios']},{'ausente','indisponivel'})
        self.assertEqual(arquivos(),antes)
        item=itens[0];plano=a.preparar(self.raiz,item['id'])
        a.aplicar(self.raiz,item['id'],plano['confirmacao'])
        self.assertEqual(a.resumo(self.raiz,item['id'])['estado'],'atual')
        cfg_antes=json.loads(json.dumps(self.fixture.cfg))
        perfil_antes=(self.raiz/plano['arquivo']).read_bytes()
        self.fixture.cfg['ceo']['modelo']='outra-politica';self.fixture.salvar()
        self.assertEqual(a.resumo(self.raiz,item['id'])['estado'],'divergente')
        self.assertEqual((self.raiz/plano['arquivo']).read_bytes(),perfil_antes)
        self.fixture.cfg=cfg_antes;self.fixture.salvar()
        self.assertEqual(a.resumo(self.raiz,item['id'])['estado'],'atual')
        destino=self.raiz/plano['arquivo'];destino.write_text('Perfil personalizado',encoding='utf-8')
        antes=arquivos()
        self.assertEqual(a.resumo(self.raiz,item['id'])['estado'],'divergente')
        painel=resumo([self.raiz],banco_consumo=self.raiz/'consumo-ausente.db')['projetos'][0]
        self.assertEqual(next(x for x in painel['funcionarios'] if x['id']==item['id'])['perfil_nativo']['estado'],'divergente')
        self.assertEqual(arquivos(),antes)
        destino.unlink();destino.mkdir()
        self.assertEqual(a.resumo(self.raiz,item['id']),{'estado':'indisponivel'})
        self.fixture.cfg['local']['ativo']=True;self.fixture.salvar()
        local=self.membro('claude',nome='Local',executor={'console':'claude','modelo':'modelo-local','execucao':'local'})
        self.assertEqual(a.resumo(self.raiz,local['id']),{'estado':'gerenciado'})
    def test_divergencia_race_e_politica_alterada_preservam_arquivos(self):
        item=self.membro();p=a.preparar(self.raiz,item['id']);destino=self.raiz/p['arquivo']
        destino.parent.mkdir(parents=True);destino.write_text('customizado',encoding='utf-8')
        with self.assertRaises(a.Conflito):a.aplicar(self.raiz,item['id'],p['confirmacao'])
        atual=a.preparar(self.raiz,item['id'])
        with self.assertRaises(a.Conflito):a.aplicar(self.raiz,item['id'],atual['confirmacao'])
        self.assertEqual(destino.read_text(),'customizado');destino.unlink()
        with patch('agentes_nativos.os.link',side_effect=FileExistsError):
            with self.assertRaises(a.Conflito):a.aplicar(self.raiz,item['id'],p['confirmacao'])
        self.assertFalse(destino.exists());self.assertEqual(list(destino.parent.iterdir()),[])
        self.fixture.cfg['ceo']['modelo']='modelo-alterado';self.fixture.salvar()
        with self.assertRaises(a.Conflito):a.aplicar(self.raiz,item['id'],p['confirmacao'])
    def test_contexto_recusa_perfil_desatualizado_ou_ausente(self):
        item=self.membro()
        with self.assertRaises(a.Conflito):a.contexto(self.raiz,item['id'])
        p=a.preparar(self.raiz,item['id']);a.aplicar(self.raiz,item['id'],p['confirmacao'])
        (self.raiz/p['arquivo']).write_text('alterado',encoding='utf-8')
        with self.assertRaises(a.Conflito):a.contexto(self.raiz,item['id'])
    def test_local_preserva_protecao_e_api_pc_por_projeto(self):
        item=self.membro();d={'projeto_id':f.id_projeto(self.raiz),'funcionario_id':item['id']}
        self.assertEqual(a.api([self.raiz],d,{'permissao':'ver'})[0],403)
        self.assertEqual(a.api([self.raiz],{**d,'projeto_id':'outro'},{'permissao':'pc'})[0],400)
        self.assertEqual(a.api([self.raiz],{**d,'aplicar':'sim'},{'permissao':'pc'})[0],400)
        codigo,p=a.api([self.raiz],d,{'permissao':'pc'});self.assertEqual(codigo,200)
        self.assertEqual(a.api([self.raiz],{**d,'aplicar':True,'confirmacao':p['confirmacao']},{'permissao':'pc'})[0],200)
        self.fixture.cfg['local']['ativo']=True;self.fixture.salvar()
        local=self.membro('claude',nome='Local',executor={'console':'claude','modelo':'modelo-local','execucao':'local'})
        with self.assertRaisesRegex(ValueError,'proteção'):a.preparar(self.raiz,local['id'])
    def test_links_na_pasta_nativa_recusados(self):
        item=self.membro()
        # Junction real no Windows; symlink nos demais sistemas.
        alvo=self.raiz/'alvo';alvo.mkdir();pasta=self.raiz/'.codex';pasta.mkdir()
        if os.name=='nt':
            subprocess.run(['powershell','-NoProfile','-NonInteractive','-Command',
                'New-Item -ItemType Junction -Path $env:OFFICE_LINK -Target $env:OFFICE_SOURCE -ErrorAction Stop | Out-Null'],
                env={**os.environ,'OFFICE_LINK':str(pasta/'agents'),'OFFICE_SOURCE':str(alvo)},check=True,capture_output=True)
        else:(pasta/'agents').symlink_to(alvo,target_is_directory=True)
        with self.assertRaisesRegex(ValueError,'links|junctions'):a.preparar(self.raiz,item['id'])
        self.assertEqual(list(alvo.iterdir()),[])

    def test_http_real_previa_origem_criacao_e_hash(self):
        import http.client,threading
        from functools import partial
        from http.server import ThreadingHTTPServer
        import servidor,rede
        item=self.membro();pedido={'projeto_id':f.id_projeto(self.raiz),'funcionario_id':item['id']}
        antes=servidor.Handler.rede;servidor.Handler.rede=rede.Rede(self.raiz,False,False)
        srv=ThreadingHTTPServer(('127.0.0.1',0),partial(servidor.Handler,directory=str(self.raiz)))
        thread=threading.Thread(target=srv.serve_forever,daemon=True);thread.start()
        host=f'127.0.0.1:{srv.server_address[1]}'
        con=http.client.HTTPConnection('127.0.0.1',srv.server_address[1],timeout=10)
        try:
            with patch.object(servidor,'cfg',return_value={'projetos':[str(self.raiz)]}):
                def enviar(dados,origem):
                    con.request('POST','/api/gestao/funcionarios/perfil',json.dumps(dados),
                        {'Host':host,'Content-Type':'application/json','X-Office-Acao':'1','Origin':origem})
                    r=con.getresponse();bruto=r.read()
                    return r.status,json.loads(bruto) if r.status==200 else {}
                self.assertEqual(enviar(pedido,'https://outra.example')[0],403)
                codigo,p=enviar(pedido,'http://'+host);self.assertEqual(codigo,200)
                destino=self.raiz/p['arquivo'];self.assertFalse(destino.exists())
                self.assertEqual(enviar({**pedido,'aplicar':True,'confirmacao':'errado'},'http://'+host)[0],409)
                self.assertFalse(destino.exists())
                self.assertEqual(enviar({**pedido,'aplicar':True,'confirmacao':p['confirmacao']},'http://'+host)[0],200)
                self.assertEqual(destino.read_text(encoding='utf-8'),p['conteudo'])
        finally:con.close();srv.shutdown();srv.server_close();thread.join();servidor.Handler.rede=antes


if __name__=='__main__':unittest.main()
