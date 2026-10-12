"""Isolamento, limites e proveniência da busca, sem providers ou rede."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import contexto_projeto as contexto
from funcionarios import id_projeto


class Contexto(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.a, self.b = self.base / 'A', self.base / 'B'
        for raiz in (self.a, self.b):
            (raiz / '.office').mkdir(parents=True)
            (raiz / 'docs').mkdir()
            (raiz / 'CLAUDE.md').write_text('Pesquisa canônica\nregra segura', encoding='utf-8')
            (raiz / 'PRODUTO.md').write_text('Produto pesquisável', encoding='utf-8')
            (raiz / 'docs' / 'ARCHITECTURE_GRAPH.yaml').write_text('arquitetura: pesquisa', encoding='utf-8')
            (raiz / '.office' / 'projeto.json').write_text(json.dumps({'ativo': True, 'kanban': {'repo': 'o/r'}}))
            (self.base / ('db' + raiz.name)).mkdir()
        self.dados = lambda p: self.base / ('db' + Path(p).name)
        self.addCleanup(patch.stopall)
        patch('gestao_cli.pasta_dados', self.dados).start()
        patch('subprocess.Popen', side_effect=AssertionError('Não executar subprocessos')).start()
        patch('subprocess.run', side_effect=AssertionError('Não executar subprocessos')).start()
        self.db = self.dados(self.a) / 'tarefas.db'
        self.ev = {'repo': 'o/r', 'cartao': 1, 'pr': 3, 'head': 'a' * 40, 'merge_commit': 'b' * 40,
                   'merged_at': '2026-10-11T12:00:00Z', 'checks': {'gates': [{'estado': 'success'}]}}
        self.pacote = {'meta': {'objetivo': 'Pesquisa entregue', 'gdd': {'sha256': 'd' * 64, 'numero': 1}},
                       'prompt': 'NAO_PUBLICAR_PROMPT', 'contexto_execucao': {'worktree': '/privado/nao_publicar'}}

    def buscar(self, q='pesquisa', raiz=None):
        return contexto.buscar([self.a, self.b], id_projeto(raiz or self.a), q)

    def politica(self, **alteracoes):
        cfg = {'ativo': True, 'kanban': {'repo': 'o/r'}, **alteracoes}
        (self.a / '.office' / 'projeto.json').write_text(json.dumps(cfg))

    def banco(self, ev=None, pacote=None, estado='concluido', repo='o/r', numero='1', equipe='Dev'):
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS reserva (projeto TEXT,cartao TEXT,equipe TEXT,pacote TEXT,token TEXT,estado TEXT,atualizado REAL)')
            db.execute('CREATE TABLE IF NOT EXISTS conclusao (token TEXT,evidencia TEXT)')
            db.execute('DELETE FROM reserva'); db.execute('DELETE FROM conclusao')
            db.execute('INSERT INTO reserva VALUES (?,?,?,?,?,?,?)', (repo, numero, equipe, json.dumps(self.pacote if pacote is None else pacote), 'NAO_PUBLICAR_TOKEN', estado, 1))
            db.execute('INSERT INTO conclusao VALUES (?,?)', ('NAO_PUBLICAR_TOKEN', json.dumps(self.ev if ev is None else ev)))

    def test_documentos_proveniencia_e_sem_escritas(self):
        antes = {p: p.read_bytes() for p in self.base.rglob('*') if p.is_file()}
        r = self.buscar()
        self.assertEqual(len(r['resultados']), 2)
        hit = r['resultados'][0]
        self.assertEqual(hit['snapshot'], 'arvore_de_trabalho')
        self.assertEqual(hit['data_tipo'], 'modificacao_local')
        self.assertEqual(hit['revisao'], hashlib.sha256((self.a / 'CLAUDE.md').read_bytes()).hexdigest())
        self.assertEqual(hit['linha'], 1)
        self.assertNotIn(str(self.base), json.dumps(r))
        self.assertEqual(antes, {p: p.read_bytes() for p in self.base.rglob('*') if p.is_file()})

    def test_isolamento_mesmo_repo_e_nao_descobre_arquivos(self):
        (self.b / 'CLAUDE.md').write_text('somenteB')
        (self.a / 'NAO_CANONICO.md').write_text('somenteB')
        self.assertEqual(self.buscar('somenteB')['resultados'], [])
        self.assertEqual(len(self.buscar('somenteB', self.b)['resultados']), 1)
        self.banco()
        self.assertFalse(any(x['tipo'] == 'entrega' for x in self.buscar(raiz=self.b)['resultados']))

    def test_selecao_explicita_sem_fallback(self):
        for ident in (None, '', '../A', 'f' * 20):
            with self.assertRaises(ValueError): contexto.buscar([self.a], ident, 'pesquisa')
        with self.assertRaises(ValueError): contexto.buscar([self.a, self.a], id_projeto(self.a), 'pesquisa')
        self.politica(ativo=False)
        with self.assertRaises(ValueError): self.buscar()

    def test_consultas_limitadas_literais(self):
        for q in ('', 'a', 'x' * 161, 'a\nb', '\x00xx', ' ' * 1000000 + 'pesquisa', ' '.join(str(i) for i in range(13))):
            with self.assertRaises(ValueError): self.buscar(q)
        self.assertEqual(self.buscar('.*')['resultados'], [])
        self.assertEqual(len(self.buscar('PESQUISA canônica')['resultados']), 1)

    def test_excecao_office_exata(self):
        (self.a / '.office' / 'REGRAS.md').write_text('pesquisa oculta aprovada')
        self.politica(fontes={'regras': '.office/REGRAS.md'})
        self.assertEqual(self.buscar()['resultados'][0]['fonte'], '.office/REGRAS.md')
        for nome in ('.office/projeto.json', '.office/config.yaml', '.office/auth.txt', '.office/nested/REGRAS.md', '.git/README.md', '.env',
                     'secrets/regra.md', 'docs/api_token.md', 'config.json', '/tmp/regra.md',
                     'docs/../regra.md', 'docs\\regra.md', 'docs/regra.md:stream', 'docs//regra.md'):
            with self.subTest(nome=nome), self.assertRaises(ValueError): contexto._nome(nome)

    def test_erro_generico_sem_caminho(self):
        self.politica(fontes={'regras': 'private/NAO_PUBLICAR.md'})
        r = self.buscar()
        self.assertEqual(r['fontes'][0]['estado'], 'indisponivel_ou_excluida')
        self.assertNotIn('NAO_PUBLICAR', json.dumps(r))

    def test_links_finais_e_intermediarios_mesmo_projeto(self):
        arq = self.a / 'CLAUDE.md'; arq.unlink(); arq.symlink_to(self.b / 'CLAUDE.md')
        self.assertNotIn('regras', [x.get('papel') for x in self.buscar()['resultados']])
        arq.unlink(); arq.symlink_to(self.a / 'PRODUTO.md')
        self.assertNotIn('regras', [x.get('papel') for x in self.buscar()['resultados']])
        (self.a / 'alias').symlink_to(self.a / 'docs', target_is_directory=True)
        self.politica(fontes={'regras': 'alias/ARCHITECTURE_GRAPH.yaml'})
        self.assertNotIn('regras', [x.get('papel') for x in self.buscar()['resultados']])

    def test_link_politica_e_raiz_rejeitados(self):
        politica = self.a / '.office' / 'projeto.json'
        politica.unlink(); politica.symlink_to(self.b / '.office' / 'projeto.json')
        with self.assertRaises(ValueError): self.buscar()
        alias = self.base / 'alias'; alias.symlink_to(self.b, target_is_directory=True)
        with self.assertRaises(ValueError): contexto.buscar([alias], id_projeto(alias), 'pesquisa')

    def test_reparse_windows_sem_depender_de_is_junction(self):
        from types import SimpleNamespace
        p = self.a / 'CLAUDE.md'
        cadeia = contexto._cadeia(p)
        lstat = Path.lstat
        def simular(alvo, *args, **kwargs):
            s = lstat(alvo, *args, **kwargs)
            if alvo == p:
                return SimpleNamespace(st_dev=s.st_dev, st_ino=s.st_ino, st_mode=s.st_mode,
                                       st_size=s.st_size, st_mtime_ns=s.st_mtime_ns, st_file_attributes=0x400)
            return s
        with patch.object(Path, 'lstat', autospec=True, side_effect=simular):
            with self.assertRaises(ValueError): contexto._cadeia(p)
            with self.assertRaises(ValueError): contexto._conferir(cadeia)

    def test_textos_inseguros_ilegivel_grande_e_tipo(self):
        arq = self.a / 'CLAUDE.md'
        for dados in (b'\xff', b'pesquisa\x00binario', b'x' * (contexto.MAX_ARQUIVO + 1),
                      b'pesquisa\npassword=nao_publicar', b'pesquisa\n-----BEGIN ' + b'PRIVATE KEY-----',
                      ('pesquisa\n' + 'ghp_' + 'x' * 30).encode()):
            arq.write_bytes(dados)
            self.assertNotIn('regras', [x.get('papel') for x in self.buscar()['resultados']])
        arq.unlink(); arq.mkdir()
        self.assertNotIn('regras', [x.get('papel') for x in self.buscar()['resultados']])

    def test_troca_durante_leitura_e_fifo(self):
        real = contexto._abrir
        def trocar(raiz, nome):
            fd = real(raiz, nome)
            if nome == 'CLAUDE.md':
                (raiz / nome).unlink(); (raiz / nome).write_text('pesquisa trocada')
            return fd
        with patch.object(contexto, '_abrir', trocar):
            self.assertNotIn('regras', [x.get('papel') for x in self.buscar()['resultados']])
        import os
        if hasattr(os, 'mkfifo'):
            p = self.a / 'CLAUDE.md'; p.unlink(); os.mkfifo(p)
            self.assertNotIn('regras', [x.get('papel') for x in self.buscar()['resultados']])

    def test_entrega_validada_sem_pacote_privado(self):
        self.banco(); antes = self.db.read_bytes()
        r = self.buscar(); hit = next(x for x in r['resultados'] if x['tipo'] == 'entrega')
        self.assertEqual(hit['revisao'], 'b' * 40)
        self.assertEqual(hit['gdd_sha256'], 'd' * 64)
        self.assertEqual(hit['aceite_usuario'], 'nao_inferido')
        self.assertNotIn('NAO_PUBLICAR', json.dumps(r))
        self.assertEqual(antes, self.db.read_bytes())

    def test_apenas_conclusoes_completas(self):
        for estado in ('revisao', 'reservado', 'executando', 'cancelado'):
            self.banco(estado=estado)
            self.assertFalse(any(x['tipo'] == 'entrega' for x in self.buscar()['resultados']))
        for ev in ([], {}, {**self.ev, 'repo': 'outro/repo'}, {**self.ev, 'cartao': True},
                   {**self.ev, 'head': 42}, {**self.ev, 'merge_commit': 'invalido'},
                   {**self.ev, 'merged_at': 'ontem'}, {**self.ev, 'merged_at': '2026-01-01'},
                   {**self.ev, 'checks': {'gates': []}}, {**self.ev, 'checks': {'gates': [None]}},
                   {**self.ev, 'checks': {'gates': [{'estado': 'failure'}]}}):
            self.banco(ev=ev)
            self.assertFalse(any(x['tipo'] == 'entrega' for x in self.buscar()['resultados']))

    def test_meta_invalida_e_segredos(self):
        for pacote in ([], {}, {'meta': []}, {'meta': {'gdd': {'sha256': 'd' * 64, 'numero': True}}},
                       {'meta': {**self.pacote['meta'], 'objetivo': 'pesquisa api_key=nao_publicar'}},
                       {'meta': {**self.pacote['meta'], 'objetivo': 'x' * 1001}},
                       {**self.pacote, 'grande': 'x' * contexto.MAX_REGISTRO}):
            self.banco(pacote=pacote)
            self.assertFalse(any(x['tipo'] == 'entrega' for x in self.buscar()['resultados']))

    def test_deduplicacao_limite_e_budget(self):
        self.banco()
        with closing(sqlite3.connect(self.db)) as db, db:
            for _ in range(102):
                db.execute('INSERT INTO conclusao VALUES (?,?)', ('NAO_PUBLICAR_TOKEN', json.dumps(self.ev)))
        r = self.buscar()
        self.assertTrue(r['limitado'])
        self.assertEqual(sum(x['tipo'] == 'entrega' for x in r['resultados']), 1)
        with patch.object(contexto, 'MAX_BYTES', 1):
            r = self.buscar()
            self.assertTrue(r['limitado'])
            self.assertFalse(any(x['tipo'] == 'entrega' for x in r['resultados']))

    def test_banco_link_corrompido_e_sidecar(self):
        self.banco()
        side = Path(str(self.db) + '-wal'); side.symlink_to(self.b / 'CLAUDE.md')
        self.assertEqual(self.buscar()['fontes'][-1]['estado'], 'indisponivel_ou_excluida')
        side.unlink(); self.db.unlink(); self.db.symlink_to(self.b / 'CLAUDE.md')
        self.assertEqual(self.buscar()['fontes'][-1]['estado'], 'indisponivel_ou_excluida')
        self.db.unlink(); self.db.write_text('não sqlite')
        self.assertEqual(self.buscar()['fontes'][-1]['estado'], 'indisponivel_ou_excluida')

    def test_preview_limitado_xss_e_unicode(self):
        (self.a / 'CLAUDE.md').write_text('ß' * 300 + '<script>pesquisa</script>' + 'x' * 800)
        hit = self.buscar()['resultados'][0]
        self.assertLessEqual(len(hit['trecho']), 400)
        self.assertIn('pesquisa', hit['trecho'])
        self.assertTrue(hit['trecho_truncado'])

    def test_wal_ativo_nao_cria_nem_altera_sidecars(self):
        self.banco()
        wal = Path(str(self.db) + '-wal'); wal.write_bytes(b'wal em transicao')
        antes = {p: p.read_bytes() for p in self.dados(self.a).iterdir()}
        self.assertEqual(self.buscar()['fontes'][-1]['estado'], 'indisponivel_ou_excluida')
        self.assertEqual(antes, {p: p.read_bytes() for p in self.dados(self.a).iterdir()})

    def test_politica_muda_e_nao_devolve_fontes_antigas(self):
        real = contexto._documento
        def mudar(*args):
            fonte = real(*args)
            self.politica(ativo=False)
            return fonte
        with patch.object(contexto, '_documento', mudar), self.assertRaises(ValueError): self.buscar()

    def test_banco_muda_e_descarta_projecao(self):
        self.banco()
        real = contexto._entrega
        def mudar(*args):
            fonte = real(*args)
            with closing(sqlite3.connect(self.db)) as db, db:
                db.execute("UPDATE reserva SET estado='revisao'")
            return fonte
        with patch.object(contexto, '_entrega', mudar):
            r = self.buscar()
        self.assertEqual(r['fontes'][-1]['estado'], 'indisponivel_ou_excluida')
        self.assertFalse(any(x['tipo'] == 'entrega' for x in r['resultados']))

    def test_vinte_resultados_e_snapshot_sem_tabelas(self):
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('CREATE TABLE outra (id TEXT)')
        self.assertEqual(self.buscar()['fontes'][-1]['estado'], 'disponivel')
        self.banco()
        with closing(sqlite3.connect(self.db)) as db, db:
            for numero in range(2, 35):
                db.execute('INSERT INTO reserva VALUES (?,?,?,?,?,?,?)', ('o/r', str(numero), 'Dev', json.dumps(self.pacote), str(numero), 'concluido', numero))
                db.execute('INSERT INTO conclusao VALUES (?,?)', (str(numero), json.dumps({**self.ev, 'cartao': numero, 'pr': numero})))
        r = self.buscar()
        self.assertEqual(len(r['resultados']), 20)
        self.assertTrue(r['limitado'])

    def test_repo_invalido_e_metadados_extensos(self):
        for repo in ('o/..', '../r', 'o/' + 'r' * 101):
            self.politica(kanban={'repo': repo})
            with self.assertRaises(ValueError): self.buscar()
        self.politica()
        self.banco(equipe='x' * 100000)
        self.assertFalse(any(x['tipo'] == 'entrega' for x in self.buscar()['resultados']))

    def test_politica_grande_fifo_e_complexidade(self):
        p = self.a / '.office' / 'projeto.json'
        for texto in ('x' * (contexto.MAX_ARQUIVO + 1), '[' * 15000 + '0' + ']' * 15000):
            p.write_text(texto)
            with self.assertRaises(ValueError): self.buscar()
        import os
        if hasattr(os, 'mkfifo'):
            p.unlink(); os.mkfifo(p)
            with self.assertRaises(ValueError): self.buscar()

    def test_json_profundo_omitido_sem_erro(self):
        for campo, tabela in (('pacote', 'reserva'), ('evidencia', 'conclusao')):
            self.banco()
            with closing(sqlite3.connect(self.db)) as db, db:
                db.execute(f'UPDATE {tabela} SET {campo}=?', ('[' * 15000 + '0' + ']' * 15000,))
            r = self.buscar()
            self.assertEqual(r['fontes'][-1]['omitidos'], 1)
            self.assertFalse(any(x['tipo'] == 'entrega' for x in r['resultados']))

    def test_wal_criado_durante_abertura_descarta_resultado(self):
        self.banco()
        conectar = sqlite3.connect
        def abrir(*args, **kwargs):
            Path(str(self.db) + '-wal').write_bytes(b'novo wal')
            return conectar(*args, **kwargs)
        with patch.object(contexto.sqlite3, 'connect', abrir):
            r = self.buscar()
        self.assertEqual(r['fontes'][-1]['estado'], 'indisponivel_ou_excluida')
        self.assertFalse(any(x['tipo'] == 'entrega' for x in r['resultados']))

    def test_snapshot_vinculado_ao_descritor_nao_ao_nome_sqlite(self):
        self.banco()
        original = self.db.read_bytes()
        outro = self.base / 'outro.db'; outro.write_bytes(original)
        with closing(sqlite3.connect(outro)) as db, db:
            db.execute("UPDATE reserva SET equipe='OUTRO_CHECKOUT'")
        conectar = sqlite3.connect
        def trocar(*args, **kwargs):
            self.assertEqual(args[0], ':memory:')
            antigo = self.base / 'antes.db'
            self.db.rename(antigo); outro.rename(self.db)
            try:
                return conectar(*args, **kwargs)
            finally:
                self.db.rename(outro); antigo.rename(self.db)
        with patch.object(contexto.sqlite3, 'connect', trocar):
            r = self.buscar()
        hit = next(x for x in r['resultados'] if x['tipo'] == 'entrega')
        self.assertEqual(hit['equipe'], 'Dev')
        self.assertNotIn('OUTRO_CHECKOUT', json.dumps(r))

    def test_banco_acima_limite_preserva_busca_documental(self):
        with self.db.open('wb') as f:
            f.truncate(contexto.MAX_BANCO + 1)
        r = self.buscar()
        self.assertTrue(r['limitado'])
        self.assertEqual(r['fontes'][-1]['estado'], 'indisponivel_ou_excluida')
        self.assertEqual(len(r['resultados']), 2)

    def test_concorrencia_nao_acumula_snapshots(self):
        contexto._CONSULTA.acquire()
        try:
            with self.assertRaises(ValueError): self.buscar()
        finally:
            contexto._CONSULTA.release()
        self.assertTrue(self.buscar()['ok'])

    def test_surrogate_nao_quebra_resposta_http(self):
        self.banco(pacote={'meta': {**self.pacote['meta'], 'objetivo': 'pesquisa \ud800'}})
        r = self.buscar()
        self.assertFalse(any(x['tipo'] == 'entrega' for x in r['resultados']))
        self.assertFalse(contexto._texto_seguro('pesquisa \ud800'))
        json.dumps(r, ensure_ascii=False).encode('utf-8')

    def test_views_nao_sao_fontes_de_conclusao(self):
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('CREATE VIEW reserva AS SELECT 1 AS cartao')
            db.execute('CREATE TABLE conclusao (token TEXT,evidencia TEXT)')
        self.assertFalse(any(x['tipo'] == 'entrega' for x in self.buscar()['resultados']))

    def test_politica_tipos_invalidos_api_falha_fechada(self):
        self.politica(kanban={'repo': 'o/r', 'prioridades': ['P0'], 'campo_prioridade': 1})
        codigo, r = contexto.api([self.a], {'projeto': [id_projeto(self.a)], 'q': ['pesquisa']}, {'permissao': 'pc'})
        self.assertEqual(codigo, 409)
        self.assertFalse(r['ok'])

    def test_projeto_sem_repo_pesquisa_so_documentos(self):
        self.politica(kanban={'repo': ''})
        self.banco()
        with patch.object(contexto, '_entregas', side_effect=AssertionError('Não inferir repositório')):
            r = self.buscar()
        self.assertEqual(len(r['resultados']), 2)
        self.assertTrue(all(x['tipo'] == 'documento' for x in r['resultados']))
        self.assertTrue(r['limitado'])
        self.assertEqual(r['fontes'][-1]['motivo'], 'repositorio_nao_configurado')

    def test_runtime_sem_deserialize_preserva_documentos(self):
        self.banco()
        conectar = sqlite3.connect
        class Antigo:
            def __init__(self): self.db = conectar(':memory:')
            def close(self): self.db.close()
        with patch.object(contexto.sqlite3, 'connect', lambda *a, **kw: Antigo()):
            r = self.buscar()
        self.assertEqual(len(r['resultados']), 2)
        self.assertTrue(r['limitado'])
        self.assertEqual(r['fontes'][-1]['estado'], 'indisponivel_ou_excluida')

    def test_http_montado_parametros_pc_estaticos_e_headers(self):
        import http.client
        import threading
        from functools import partial
        from http.server import ThreadingHTTPServer
        import servidor, rede
        with patch.object(servidor, 'cfg', return_value={'projetos': [str(self.a), str(self.b)]}), patch.object(servidor.Handler, 'rede', rede.Rede(self.base, False, False)):
            srv = ThreadingHTTPServer(('127.0.0.1', 0), partial(servidor.Handler, directory=str(self.a)))
            thread = threading.Thread(target=srv.serve_forever, daemon=True); thread.start()
            conn = http.client.HTTPConnection('127.0.0.1', srv.server_port, timeout=3)
            try:
                rota = '/api/gestao/contexto?projeto=' + id_projeto(self.a) + '&q=pesquisa'
                conn.request('GET', rota)
                r = conn.getresponse(); body = json.loads(r.read())
                self.assertEqual(r.status, 200)
                self.assertEqual(body['projeto_id'], id_projeto(self.a))
                self.assertEqual(r.getheader('Cache-Control'), 'no-store')
                self.assertEqual(r.getheader('X-Content-Type-Options'), 'nosniff')
                for sufixo in ('&projeto=', '&q=', '&path=', '&q=outra'):
                    conn.request('GET', rota + sufixo); r = conn.getresponse(); r.read()
                    self.assertEqual(r.status, 400)
                for path in ('/CLAUDE.md', '/.office/projeto.json', '/%2eoffice/projeto.json'):
                    conn.request('GET', path); r = conn.getresponse(); r.read()
                    self.assertIn(r.status, (403, 404))
                original = servidor.Handler.api_get
                def como_movel(handler, path, qs, ident):
                    return original(handler, path, qs, {'permissao': 'ver'})
                with patch.object(servidor.Handler, 'api_get', como_movel):
                    conn.request('GET', rota); r = conn.getresponse(); body = json.loads(r.read())
                    self.assertEqual(r.status, 403)
                    self.assertNotIn('resultados', body)
            finally:
                conn.close(); srv.shutdown(); srv.server_close(); thread.join()

    def test_api_pc_e_parametros(self):
        qs = {'projeto': [id_projeto(self.a)], 'q': ['pesquisa']}
        self.assertEqual(contexto.api([self.a], qs, {'permissao': 'pc'})[0], 200)
        for ident in (None, {}, {'permissao': 'ler'}, {'permissao': 'conferir'}):
            self.assertEqual(contexto.api([self.a], qs, ident)[0], 403)
        for args in ({}, {**qs, 'path': ['x']}, {**qs, 'q': ['a', 'b']}, {**qs, 'q': 'texto'}):
            self.assertEqual(contexto.api([self.a], args, {'permissao': 'pc'})[0], 400)
        codigo, r = contexto.api([self.a], {**qs, 'projeto': ['../private']}, {'permissao': 'pc'})
        self.assertEqual(codigo, 409)
        self.assertNotIn('private', json.dumps(r))


if __name__ == '__main__':
    unittest.main()
