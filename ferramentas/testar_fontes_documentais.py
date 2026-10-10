import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from fontes_documentais import resumo,LIMITE
from gestao_projeto import validar
import gestao_painel

class Fontes(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.raiz=Path(self.tmp.name)
    def escrever(self,nome,texto):
        p=self.raiz/nome;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(texto,encoding='utf-8')
    def test_revisor_suspenso_nao_marca_wrapper_como_usado(self):
        cfg={'ativo':True,'ceo':{'console':'codex'},'diretor':{'console':'codex'},
             'revisao':{'ativo':True,'revisores':[
                 {'nome':'QA Claude','executor':{'console':'claude'},'ativo':False},
                 {'nome':'QA Gemini','executor':{'console':'gemini'},'ativo':False}]}}
        r=resumo(self.raiz,cfg)
        por_nome={w['arquivo']:w for w in r['instrucoes_consoles']}
        self.assertFalse(por_nome['GEMINI.md']['necessario'])
        self.assertFalse(por_nome['CLAUDE.md']['necessario'])
        self.assertTrue(por_nome['CLAUDE.md']['fonte_regras'])
        self.assertTrue(por_nome['AGENTS.md']['necessario'])
    def test_ausentes_e_projeto_inativo_sem_escrita(self):
        d=resumo(self.raiz,{})
        self.assertEqual([f['estado'] for f in d['fontes']],['ausente']*3)
        self.assertFalse(any(f['necessario'] for f in d['instrucoes_consoles']))
        self.assertEqual(list(self.raiz.iterdir()),[])
    def test_referencia_limitada_nao_comprova_semantica(self):
        self.escrever('CLAUDE.md','SEGREDO: faça A')
        self.escrever('AGENTS.md','Leia [regras](./CLAUDE.md). SEGREDO: faça o contrário')
        self.escrever('GEMINI.md','@./CLAUDE.md')
        antes={p.name:p.read_bytes() for p in self.raiz.iterdir()}
        d=resumo(self.raiz,{'ativo':True,'ceo':{'console':'codex'},'diretor':{'console':'gemini'}})
        self.assertTrue(d['instrucoes_consoles'][0]['fonte_regras'])
        self.assertTrue(all(f['cita_regras'] for f in d['instrucoes_consoles'][1:]))
        self.assertTrue(all(f['necessario'] for f in d['instrucoes_consoles'][1:]))
        self.assertFalse(d['instrucoes_consoles'][0]['necessario'])
        self.assertEqual(d['semantica'],'não verificada')
        self.assertNotIn('SEGREDO',json.dumps(d));self.assertNotIn(str(self.raiz),json.dumps(d))
        self.assertEqual(antes,{p.name:p.read_bytes() for p in self.raiz.iterdir()})
    def test_fonte_customizada_e_limites_da_mencao(self):
        self.escrever('.office/REGRAS.md','regra')
        cfg={'fontes':{'regras':'.office/REGRAS.md'}}
        for texto,esperado in [('Leia .office/REGRAS.md',True),('@./.office/REGRAS.md',True),
                               ('outra/.office/REGRAS.md',False),('.office/REGRAS.md.bak',False)]:
            with self.subTest(texto=texto):
                self.escrever('AGENTS.md',texto)
                self.assertEqual(resumo(self.raiz,cfg)['instrucoes_consoles'][1]['cita_regras'],esperado)
    def test_tamanho_tipo_e_codificacao(self):
        (self.raiz/'CLAUDE.md').write_bytes(b'x'*(LIMITE+1))
        (self.raiz/'PRODUTO.md').mkdir()
        (self.raiz/'AGENTS.md').write_bytes(b'\xff')
        d=resumo(self.raiz,{})
        self.assertEqual(d['fontes'][0]['estado'],'acima_limite')
        self.assertEqual(d['fontes'][1]['estado'],'tipo_invalido')
        self.assertEqual(d['instrucoes_consoles'][1]['estado'],'ilegivel')
    def test_link_nao_e_lido(self):
        self.escrever('privado','CLAUDE.md SEGREDO')
        with patch.object(Path,'is_symlink',return_value=True),patch.object(Path,'open',side_effect=AssertionError('não ler')):
            d=resumo(self.raiz,{})
        self.assertEqual(d['instrucoes_consoles'][1]['estado'],'fora_projeto')
    def test_painel_inativo_preserva_diagnostico_sem_banco(self):
        d=gestao_painel.resumo([self.raiz],banco_consumo=self.raiz/'ausente.db')['projetos'][0]
        self.assertFalse(d['ativo']);self.assertNotIn('erro',d)
        self.assertEqual(d['documentacao']['fontes'][0]['estado'],'ausente')
        self.assertEqual(list(self.raiz.iterdir()),[])
    def test_http_nao_publica_conteudo_das_regras(self):
        import http.client,threading
        from functools import partial
        from http.server import ThreadingHTTPServer
        import servidor,rede,banco
        self.escrever('CLAUDE.md','SEGREDO_DOCUMENTO')
        anterior=servidor.Handler.rede;servidor.Handler.rede=rede.Rede(self.raiz,False,False)
        srv=ThreadingHTTPServer(('127.0.0.1',0),partial(servidor.Handler,directory=str(Path(servidor.__file__).parent)))
        th=threading.Thread(target=srv.serve_forever,daemon=True);th.start()
        con=http.client.HTTPConnection('127.0.0.1',srv.server_address[1],timeout=10)
        try:
            with patch.object(banco,'ARQ',self.raiz/'escritorio.db'),patch.object(servidor,'cfg',return_value={'projetos':[self.raiz]}):
                con.request('GET','/api/gestao');resp=con.getresponse();bruto=resp.read().decode('utf-8')
                self.assertEqual(resp.status,200)
                doc=json.loads(bruto)['projetos'][0]['documentacao']
                self.assertEqual(doc['fontes'][0]['estado'],'presente')
                self.assertNotIn('SEGREDO_DOCUMENTO',bruto);self.assertNotIn(str(self.raiz),bruto)
        finally:
            con.close();srv.shutdown();srv.server_close();th.join(5);servidor.Handler.rede=anterior

if __name__=='__main__':unittest.main()
