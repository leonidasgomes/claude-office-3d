"""Recibos locais e projeção HTTP sem motivos, paths ou inferência."""
from contextlib import closing
import http.client
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
from functools import partial
from http.server import ThreadingHTTPServer
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import gestao_cli as gc
import coordenacao_registro as cr


class Registro(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.raiz=Path(self.tmp.name);self.projeto=self.raiz/'projeto';(self.projeto/'.office').mkdir(parents=True)
        (self.projeto/'.office/projeto.json').write_text(json.dumps({'ativo':True,'kanban':{'repo':'owner/repo'},
            'equipes':[{'nome':'Dev','especialidade':'Código','executor':{'console':'codex'}}]}),encoding='utf-8')
        p=patch.object(gc,'RAIZ',self.raiz/'app');p.start();self.addCleanup(p.stop)
        self.rotas={p:{'console':'codex','modelo':'modelo','execucao':'cloud'} for p in ('ceo','diretor')}
        self.decisao={'cartoes':[42],'motivo':'SEGREDO C:/privado','bloqueios':[]}

    def criar(self):
        r=cr.Registro(self.projeto)
        return r,r.criar('owner/repo','a'*64,self.rotas,[42,43])

    def organizar(self):
        r,ident=self.criar()
        r.atualizar(ident,'consultando_ceo');r.atualizar(ident,'ceo_registrado',ceo=self.decisao)
        r.atualizar(ident,'consultando_diretor');r.atualizar(ident,'diretor_registrado',diretor=self.decisao)
        r.atualizar(ident,'organizado');return r,ident

    def test_leitura_nao_cria_banco_e_isola_projetos(self):
        self.assertEqual(cr.resumo(self.projeto,'owner/repo')['itens'],[])
        self.assertFalse(cr.arquivo(self.projeto).exists())
        self.organizar()
        self.assertEqual(cr.resumo(self.projeto,'owner/outro')['itens'],[])
        self.assertEqual(cr.resumo(self.raiz/'outro-projeto','owner/repo')['itens'],[])

    def test_decisoes_persistem_e_publico_omite_motivos_contexto_paths(self):
        r,ident=self.organizar()
        d=cr.resumo(self.projeto,'owner/repo')['itens'][0]
        self.assertEqual(d['estado'],'organizado');self.assertEqual(d['diretor']['cartoes'],[42])
        texto=json.dumps(d);self.assertNotIn('SEGREDO',texto);self.assertNotIn('contexto_sha256',texto)
        with closing(r.abrir()) as db:
            privado=json.loads(db.execute('SELECT dados FROM coordenacao WHERE id=?',(ident,)).fetchone()[0])
        self.assertEqual(privado['ceo']['motivo'],self.decisao['motivo'])
        self.assertEqual(privado['contexto_sha256'],'a'*64)

    def test_transicao_fora_ordem_e_decisao_na_fase_errada_rejeitadas(self):
        r,ident=self.criar()
        with self.assertRaises(ValueError):r.atualizar(ident,'processado',lote_id='b'*32)
        with self.assertRaises(ValueError):r.atualizar(ident,'consultando_ceo',ceo=self.decisao)
        r.atualizar(ident,'consultando_ceo');r.atualizar(ident,'incerto')
        with self.assertRaises(ValueError):r.atualizar(ident,'consultando_ceo')

    def test_lote_final_exige_vinculo_e_receipt_corrompido_nao_vira_decisao(self):
        r,ident=self.organizar();r.atualizar(ident,'despachando')
        with self.assertRaises(ValueError):r.atualizar(ident,'processado')
        r.atualizar(ident,'processado',lote_id='b'*32)
        self.assertEqual(cr.resumo(self.projeto,'owner/repo')['itens'][0]['lote_id'],'b'*32)
        with closing(r.abrir()) as db,db:db.execute('UPDATE coordenacao SET dados=? WHERE id=?',('x'*64001,ident))
        self.assertEqual(cr.resumo(self.projeto,'owner/repo'),{'itens':[],'problemas':1,'limitado':False})

    def test_limite_recent_dez(self):
        for _ in range(12):self.criar()
        d=cr.resumo(self.projeto,'owner/repo');self.assertEqual(len(d['itens']),10);self.assertTrue(d['limitado'])

    def test_http_gestao_expoe_apenas_metadados(self):
        import servidor,rede,configuracao
        self.organizar();anterior=servidor.Handler.rede
        servidor.Handler.rede=rede.Rede(self.raiz,False,False)
        srv=ThreadingHTTPServer(('127.0.0.1',0),partial(servidor.Handler,directory=str(Path(servidor.__file__).parent)))
        thread=threading.Thread(target=srv.serve_forever,daemon=True);thread.start()
        con=http.client.HTTPConnection('127.0.0.1',srv.server_address[1],timeout=10)
        try:
            with patch.object(servidor,'cfg',return_value=configuracao.normalizar({'projetos':[str(self.projeto)]})):
                con.request('GET','/api/gestao');resp=con.getresponse();raw=resp.read().decode()
                self.assertEqual(resp.status,200)
                d=json.loads(raw)['projetos'][0]['coordenacoes']['itens'][0]
                self.assertEqual(d['ceo']['cartoes'],[42]);self.assertNotIn('SEGREDO',raw)
                self.assertNotIn('C:/privado',raw);self.assertNotIn('contexto_sha256',raw)
        finally:
            con.close();srv.shutdown();srv.server_close();thread.join(timeout=5);servidor.Handler.rede=anterior


if __name__=='__main__':unittest.main()
