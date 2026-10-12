"""Galeria: Git real, snapshots imutáveis e isolamento do projeto/API."""
from contextlib import ExitStack, closing
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import galeria_entregas as g
from controle_tarefas import Controle
from funcionarios import id_projeto
from gestao_projeto import validar


class Galeria(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.raiz = Path(self.tmp.name).resolve()
        self.projeto = self.raiz / 'projeto'; self.projeto.mkdir()
        (self.raiz / 'worktrees').mkdir()
        self.work = self.raiz / 'worktrees' / 'work'; self.dados = self.raiz / 'dados'; self.dados.mkdir()
        self.git(self.projeto, 'init', '-b', 'main')
        self.git(self.projeto, 'config', 'user.name', 'Teste')
        self.git(self.projeto, 'config', 'user.email', 'teste@example.com')
        (self.projeto / 'base.txt').write_text('base')
        self.commit(self.projeto)
        self.git(self.projeto, 'worktree', 'add', '-b', 'work/teste', self.work)
        (self.work / 'relatorio.md').write_text('# Entrega\n<script>alert(1)</script>\nOlá!', encoding='utf-8')
        (self.work / 'imagem.png').write_bytes(b'\x89PNG\r\n\x1a\nconteudo')
        self.sha = self.commit(self.work)
        self.cfg = validar({'ativo': True, 'ciclo': {'ativo': True, 'base': 'origin/main'}, 'kanban': {'repo': 'teste/projeto'}})
        self.controle = Controle(self.dados / 'tarefas.db')
        self.token = self.controle.reservar('teste/projeto', '7', 'Dev', 'codex', {
            'objetivo': 'entrega', 'aceite': 'conferência humana',
            'contexto_execucao': {'worktree': str(self.work), 'branch': 'work/teste'}}, quadro_atual=True)
        self.controle.transicao(self.token, 'executando')
        self.tentativa = self.controle.iniciar_execucao(self.token)
        self.recibo = {'estado': 'publicado', 'cartao': 7, 'worktree': str(self.work),
                       'branch': 'work/teste', 'token': self.token, 'tentativa': self.tentativa,
                       'sha': self.sha, 'pr': 'https://github.com/teste/projeto/pull/8'}
        self.patches = ExitStack(); self.addCleanup(self.patches.close)
        self.patches.enter_context(patch('gestao_cli.pasta_dados', return_value=self.dados))
        self.patches.enter_context(patch('gestao_projeto.carregar', return_value=self.cfg))

    def git(self, pasta, *args):
        return subprocess.run(['git', '-C', str(pasta), *map(str, args)], check=True,
                              capture_output=True).stdout.decode().strip()

    def commit(self, pasta):
        self.git(pasta, 'add', '--all'); self.git(pasta, 'commit', '-m', 'Entrega de teste')
        return self.git(pasta, 'rev-parse', 'HEAD')

    def registrar(self, arquivos=None):
        return g.registrar_publicacao(self.projeto, self.recibo, arquivos or ['relatorio.md', 'imagem.png'])

    def test_git_snapshot_hash_tamanho_e_aceites_independentes(self):
        registro = self.registrar()
        item = g.listar(self.projeto)['itens'][0]
        self.assertEqual(item['id'], registro['id'])
        self.assertEqual(item['sha'], self.sha)
        self.assertEqual(item['tentativa'], self.tentativa)
        self.assertEqual(item['execucao']['estado'], 'sem_retorno')
        self.assertEqual(item['revisao']['estado'], 'nao_informada')
        self.assertEqual(item['merge']['estado'], 'nao_comprovado')
        self.assertEqual(item['aprovacao_visual'], 'nao_registrada')
        self.assertEqual(item['aceite_usuario'], 'nao_registrado')
        texto = next(a for a in item['arquivos'] if a['nome'].endswith('.md'))
        original = (self.work / 'relatorio.md').read_bytes()
        self.assertEqual(texto['tamanho'], len(original))
        self.assertEqual(texto['sha256'], hashlib.sha256(original).hexdigest())
        (self.work / 'relatorio.md').write_text('mudou depois')
        self.commit(self.work)
        self.assertEqual(g.arquivo(self.projeto, texto['id'])['conteudo'].encode(), original)
        self.assertEqual(self.registrar()['estado'], 'ja_registrado')
        with self.assertRaisesRegex(ValueError, 'imutável'):
            self.registrar(['relatorio.md'])

    def test_versoes_arquivo_nao_apaga_historia(self):
        primeiro = self.registrar()
        g.arquivar(self.projeto, {'id': primeiro['id'], 'arquivada': True})
        (self.work / 'relatorio.md').write_text('versão 2')
        self.recibo['sha'] = self.commit(self.work)
        segundo = self.registrar()
        self.assertNotEqual(primeiro['id'], segundo['id'])
        itens = g.listar(self.projeto)['itens']
        self.assertEqual(len(itens), 2)
        self.assertTrue(next(i for i in itens if i['id'] == primeiro['id'])['arquivada'])
        g.arquivar(self.projeto, {'id': primeiro['id'], 'arquivada': False})
        self.assertFalse(any(i['arquivada'] for i in g.listar(self.projeto)['itens']))

    def test_api_isolamento_pc_parametros_duplicados_e_sem_paths(self):
        self.registrar()
        arquivo = g.listar(self.projeto)['itens'][0]['arquivos'][0]['id']
        pid = id_projeto(self.projeto)
        qs = {'projeto': [pid]}
        self.assertEqual(g.api([self.projeto], qs, {'permissao': 'pc'})[0], 200)
        self.assertEqual(g.api([self.projeto], qs, {'permissao': 'ver'})[0], 403)
        self.assertEqual(g.api([self.projeto], {'projeto': [pid, pid]}, {'permissao': 'pc'})[0], 400)
        self.assertEqual(g.api([self.projeto], {'projeto': [pid], 'path': ['base.txt']}, {'permissao': 'pc'})[0], 400)
        outro = self.raiz / 'outro'; outro.mkdir()
        self.assertEqual(g.listar(outro)['itens'], [])  # mesmo banco/repo não dá acesso cruzado
        with self.assertRaises(ValueError): g.arquivo(outro, arquivo)
        with self.assertRaises(ValueError): g.arquivar(outro, {'id': g.listar(self.projeto)['itens'][0]['id'], 'arquivada': True})
        self.assertEqual(g.api([outro], {'projeto': [id_projeto(outro)], 'arquivo': [arquivo]}, {'permissao': 'pc'}, True)[0], 409)
        self.assertEqual(g.api([self.projeto], {'projeto': [pid], 'arquivo': ['../../.env']}, {'permissao': 'pc'}, True)[0], 409)
        self.assertNotIn(str(self.work), json.dumps(g.listar(self.projeto)))

    def test_nao_indexa_arquivos_e_bloqueia_paths_segredos_formatos(self):
        for nome in ('../relatorio.md', '/etc/passwd', 'C:/entrega.txt', 'a\\b.txt',
                     '.env.txt', '.git/config.txt', 'dados/recibo.md', 'foo//bar.txt',
                     'foo/./bar.txt', 'foo/../bar.txt', 'arquivo.txt ', 'senha.txt',
                     'secret/key.txt', 'index.html', 'imagem.svg', 'arquivo.json'):
            with self.subTest(nome=nome), self.assertRaises(ValueError): g.caminhos([nome])
        for arquivos in ([], ['a.txt'] * 2, ['a.txt', 'A.txt'], ['a.txt'] * 21, 'a.txt'):
            with self.assertRaises(ValueError): g.caminhos(arquivos)
        self.registrar(['relatorio.md'])
        self.assertEqual([a['nome'] for a in g.listar(self.projeto)['itens'][0]['arquivos']], ['relatorio.md'])
        (self.work / 'chave-inocente.md').write_text('x')
        with self.assertRaises(ValueError): g.caminhos(['chave-inocente.md'])

    def test_links_git_e_raiz_worktree_rejeitados(self):
        (self.work / 'link.md').symlink_to(self.raiz / 'externo.md')
        (self.work / 'pasta').symlink_to(self.projeto, target_is_directory=True)
        self.recibo['sha'] = self.commit(self.work)
        for caminho in ('link.md', 'pasta/base.txt'):
            with self.assertRaisesRegex(ValueError, 'simbólico'): self.registrar([caminho])
        atalho = self.raiz / 'atalho'; atalho.symlink_to(self.work, target_is_directory=True)
        with self.assertRaises(ValueError): g._raiz_git(self.projeto, atalho)
        outro = self.raiz / 'outro'; outro.mkdir(); self.git(outro, 'init')
        with self.assertRaises(ValueError): g._raiz_git(self.projeto, outro)

    def test_tamanho_tipo_conteudo_credenciais_e_objeto_adulterado(self):
        for nome, dados in [('enorme.txt', b'a' * (g.MAX_ARQUIVO + 1)), ('falso.png', b'<html>'),
                            ('falso.jpg', b'x'), ('falso.webp', b'x'), ('falso.pdf', b'x'),
                            ('falso.glb', b'x'), ('controle.txt', b'abc\0'),
                            ('invalido.txt', b'\xff'), ('documento.md', b'-----BEGIN ' + b'PRIVATE KEY-----')]:
            with self.subTest(nome=nome):
                (self.work / nome).write_bytes(dados); self.recibo['sha'] = self.commit(self.work)
                with self.assertRaises((ValueError, UnicodeError)): self.registrar([nome])
        original = g._git
        def adulterar(raiz, *args, **kw):
            saida = original(raiz, *args, **kw)
            return saida.replace(b'Ola', b'xxx') if args[:2] == ('cat-file', 'blob') else saida
        (self.work / 'ok.txt').write_text('Ola'); self.recibo['sha'] = self.commit(self.work)
        with patch.object(g, '_git', side_effect=adulterar), self.assertRaisesRegex(ValueError, 'Integridade'):
            self.registrar(['ok.txt'])
        self.assertEqual(g.listar(self.projeto)['itens'], [])

    def test_snapshot_corrompido_bloqueia_preview(self):
        self.registrar()
        arquivo = g.listar(self.projeto)['itens'][0]['arquivos'][0]['id']
        with closing(sqlite3.connect(self.dados / 'tarefas.db')) as db, db:
            db.execute('UPDATE galeria_arquivo SET conteudo=? WHERE id=?', (b'adulterado', arquivo))
        with self.assertRaisesRegex(ValueError, 'Integridade'): g.arquivo(self.projeto, arquivo)

    def test_recibo_tentativa_pr_sha_projeto_e_estado_exatos(self):
        for chave, valor in [('tentativa', '0' * 32), ('token', '0' * 32), ('cartao', 9),
                             ('branch', 'main'), ('estado', 'publicando'),
                             ('pr', 'https://github.com/outro/repo/pull/8'), ('sha', 'abc')]:
            r = {**self.recibo, chave: valor}
            with self.subTest(chave=chave), self.assertRaises(ValueError):
                g.registrar_publicacao(self.projeto, r, ['relatorio.md'])
        pasta = self.dados / 'publicacoes'; pasta.mkdir()
        (pasta / '7.json').write_text(json.dumps(self.recibo))
        dados = {'cartao': 7, 'tentativa': self.tentativa, 'pr': 8, 'sha': self.sha, 'arquivos': ['relatorio.md']}
        self.assertEqual(g.registrar(self.projeto, dados)['estado'], 'registrado')
        self.assertEqual(g.registrar(self.projeto, dados)['estado'], 'ja_registrado')
        (pasta / '7-copia.json').write_text(json.dumps(self.recibo))
        with self.assertRaisesRegex(ValueError, 'único'): g.registrar(self.projeto, dados)

    def test_troca_de_contexto_entre_captura_e_commit_nao_persiste(self):
        original = g._blob
        def trocar(*args):
            dados = original(*args)
            with closing(sqlite3.connect(self.dados / 'tarefas.db')) as db, db:
                db.execute("UPDATE reserva SET estado='bloqueado' WHERE token=?", (self.token,))
            return dados
        with patch.object(g, '_blob', side_effect=trocar), self.assertRaisesRegex(ValueError, 'mudou'):
            self.registrar(['relatorio.md'])
        self.assertEqual(g.listar(self.projeto)['itens'], [])

    def test_estados_leem_recibos_nao_transformam_merge_em_aceite(self):
        self.registrar()
        ev = {'repo': 'teste/projeto', 'cartao': 7, 'pr': 8, 'head': self.sha,
              'merge_commit': 'a' * 40, 'merged_at': '2026-10-12T00:00:00Z'}
        with closing(sqlite3.connect(self.dados / 'tarefas.db')) as db, db:
            db.execute('UPDATE execucao_tarefa SET fim=1,codigo=0 WHERE id=?', (self.tentativa,))
            db.execute('INSERT INTO entrega VALUES (?,?,?,?,?,?)', (self.token, self.sha, 8, 1, '{}', 1))
            db.execute('INSERT INTO conclusao VALUES (?,?,?)', (self.token, json.dumps(ev), 1))
        item = g.listar(self.projeto)['itens'][0]
        self.assertEqual(item['execucao']['estado'], 'encerrada')
        self.assertEqual(item['revisao']['estado'], 'aprovada')
        self.assertEqual(item['merge']['estado'], 'registrado')
        self.assertEqual(item['aceite_usuario'], 'nao_registrado')
        self.assertEqual(item['aprovacao_visual'], 'nao_registrada')

    def test_http_real_json_nosniff_e_estaticos_continuam_bloqueados(self):
        import http.client
        import threading
        from functools import partial
        from http.server import ThreadingHTTPServer
        import servidor
        import rede
        self.registrar()
        with patch.object(servidor, 'cfg', return_value={'projetos': [str(self.projeto)]}), patch.object(servidor.Handler, 'rede', rede.Rede(self.raiz, False, False)):
            srv = ThreadingHTTPServer(('127.0.0.1', 0), partial(servidor.Handler, directory=str(self.raiz)))
            thread = threading.Thread(target=srv.serve_forever, daemon=True); thread.start()
            try:
                conn = http.client.HTTPConnection('127.0.0.1', srv.server_port, timeout=3)
                self.addCleanup(conn.close)
                conn.request('GET', '/api/gestao/entregas?projeto=' + id_projeto(self.projeto))
                r = conn.getresponse(); body = json.loads(r.read())
                self.assertEqual(r.status, 200)
                self.assertEqual(r.getheader('X-Content-Type-Options'), 'nosniff')
                self.assertEqual(r.getheader('Cache-Control'), 'no-store')
                a = next(a for a in body['itens'][0]['arquivos'] if a['preview'] == 'texto')
                conn.request('GET', '/api/gestao/entregas/arquivo?projeto=' + id_projeto(self.projeto) + '&arquivo=' + a['id'])
                r = conn.getresponse(); body = json.loads(r.read())
                self.assertEqual(r.status, 200)
                self.assertTrue(r.getheader('Content-Type').startswith('application/json'))
                self.assertIn('<script>', body['conteudo'])  # literal JSON, never an HTML page
                for path in ('/dados/tarefas.db', '/worktrees/work/relatorio.md', '/api/gestao/entregas?projeto=x&path=/etc/passwd',
                             '/api/gestao/entregas?projeto=' + id_projeto(self.projeto) + '&projeto=',
                             '/api/gestao/entregas?projeto=' + id_projeto(self.projeto) + '&path='):
                    conn.request('GET', path); r = conn.getresponse(); r.read()
                    self.assertIn(r.status, (400, 403, 404))
            finally:
                srv.shutdown(); srv.server_close(); thread.join()

    def test_publicacao_real_alimenta_galeria_opcional_sem_nova_chamada(self):
        import publicacao_host as h
        office = self.raiz / 'office'; pasta = office / 'dados' / 'worktrees'
        pasta.mkdir(parents=True)
        (pasta / 'recibo.json').write_text(json.dumps({'estado': 'criado', 'projeto': str(self.projeto),
            'criados': [{'cartao': 7, 'worktree': str(self.work), 'branch': 'work/teste'}]}))
        remoto = self.raiz / 'remoto.git'; self.git(self.projeto, 'init', '--bare', remoto)
        self.git(self.projeto, 'remote', 'add', 'origin', remoto)
        (self.work / 'relatorio.md').write_text('Versão publicada pela operação real')
        pedido = {'cartao': 7, 'worktree': str(self.work), 'titulo': 'Entrega',
                  'corpo': 'Parte de #7', 'arquivos_entrega': ['relatorio.md']}
        (self.work / 'pedido.json').write_text(json.dumps(pedido))
        original = subprocess.run; chamadas = []
        def rodar(args, **kw):
            if args[0] == 'gh':
                chamadas.append(args)
                return subprocess.CompletedProcess(args, 0, self.recibo['pr'], '')
            return original(args, **kw)
        with patch.object(h, 'RAIZ', office), patch.object(h.subprocess, 'run', side_effect=rodar):
            r = h.publicar(self.projeto, pedido)
        self.assertEqual(r['estado'], 'publicado')
        self.assertEqual(r['galeria']['estado'], 'registrado')
        self.assertEqual(len(chamadas), 1)
        self.assertNotIn('pedido.json', self.git(self.work, 'ls-tree', '--name-only', 'HEAD'))
        item = g.listar(self.projeto)['itens'][0]
        self.assertEqual(item['sha'], r['sha'])
        self.assertEqual(item['tentativa'], self.tentativa)
        self.assertEqual(g.arquivo(self.projeto, item['arquivos'][0]['id'])['conteudo'],
                         'Versão publicada pela operação real')
        reconciliar = {'cartao': 7, 'tentativa': self.tentativa, 'pr': 8, 'sha': r['sha'], 'arquivos': ['relatorio.md']}
        with patch.object(h.subprocess, 'run', side_effect=AssertionError('Não pode publicar de novo')):
            self.assertEqual(g.registrar(self.projeto, reconciliar)['estado'], 'ja_registrado')

    def test_hook_falha_de_captura_nao_falha_publicacao_nem_repete(self):
        import publicacao_host
        with patch.object(g, 'registrar_publicacao', side_effect=sqlite3.OperationalError('falha')):
            r = publicacao_host.catalogar(self.projeto, self.recibo, {'arquivos_entrega': ['relatorio.md']})
        self.assertEqual(r['estado'], 'publicado')
        self.assertEqual(r['galeria']['estado'], 'nao_registrada')
        with patch.object(g, 'registrar_publicacao') as chamada:
            self.assertEqual(publicacao_host.catalogar(self.projeto, self.recibo, {}), self.recibo)
            chamada.assert_not_called()


if __name__ == '__main__':
    unittest.main()
