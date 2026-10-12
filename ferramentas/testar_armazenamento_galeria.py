"""Compatibilidade, orçamento físico e exclusão real, somente fixtures locais."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import shutil
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import armazenamento_galeria as a
import galeria_entregas as g
import testar_galeria_entregas as base


@unittest.skipUnless(sys.platform.startswith('linux'), 'escrita externa qualificada somente no Linux')
class Armazenamento(base.Galeria):
    def alvo(self):
        item = g.listar(self.projeto)['itens'][0]['arquivos'][0]
        return item, self.dados / a.PASTA / item['sha256']

    def inventario(self):
        return {str(p.relative_to(self.raiz)): (p.stat().st_size, p.stat().st_mtime_ns,
                hashlib.sha256(p.read_bytes()).hexdigest()) for p in self.raiz.rglob('*') if p.is_file()}

    def inline(self, sem_coluna=False):
        self.registrar()
        with closing(sqlite3.connect(self.dados / 'tarefas.db')) as db, db:
            for ident, sha in db.execute('SELECT id,sha256 FROM galeria_arquivo').fetchall():
                body = (self.dados / a.PASTA / sha).read_bytes()
                db.execute("UPDATE galeria_arquivo SET conteudo=?,armazenamento='inline' WHERE id=?", (body, ident))
            if sem_coluna:
                db.execute('ALTER TABLE galeria_arquivo DROP COLUMN armazenamento')

    def test_novo_corpo_externo_e_permissoes(self):
        self.registrar()
        with closing(sqlite3.connect(self.dados / 'tarefas.db')) as db:
            rows = db.execute('SELECT conteudo,armazenamento FROM galeria_arquivo').fetchall()
        self.assertTrue(all(row == (b'', 'externo-v1') for row in rows))
        item, arquivo = self.alvo()
        self.assertEqual(arquivo.stat().st_mode & 0o777, 0o600)
        self.assertEqual(arquivo.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(hashlib.sha256(arquivo.read_bytes()).hexdigest(), item['sha256'])

    def test_legado_sem_discriminador_preview_e_replay(self):
        self.inline(sem_coluna=True)
        item, _ = self.alvo()
        self.assertTrue(g.arquivo(self.projeto, item['id'])['ok'])
        self.assertEqual(self.registrar()['estado'], 'ja_registrado')
        with closing(sqlite3.connect(self.dados / 'tarefas.db')) as db:
            self.assertTrue(all(r[0] == 'inline' and len(r[1]) > 0 for r in db.execute('SELECT armazenamento,conteudo FROM galeria_arquivo')))

    def test_replay_externo_revalida_bytes(self):
        self.registrar(); _, p = self.alvo(); p.write_bytes(b'corrompido')
        with self.assertRaisesRegex(ValueError, 'Integridade'): self.registrar()

    def test_replay_nao_omite_linha_extra_corrompida(self):
        manifesto = self.registrar()['id']
        for corpo in (b'x' * (g.MAX_ARQUIVO + 1), 'texto indevido'):
            with closing(sqlite3.connect(self.dados / 'tarefas.db')) as db, db:
                db.execute('DELETE FROM galeria_arquivo WHERE id=?', ('e' * 64,))
                db.execute('INSERT INTO galeria_arquivo (id,manifesto,nome,tamanho,mime,preview,sha256,conteudo,armazenamento) VALUES (?,?,?,?,?,?,?,?,?)',
                           ('e' * 64,manifesto,'extra.txt',1,'text/plain','texto','f' * 64,corpo,'inline'))
            with self.assertRaisesRegex(ValueError,'Integridade'): self.registrar()

    def test_modo_desconhecido_e_corpo_externo_ambiguo(self):
        self.registrar(); item, _ = self.alvo()
        for modo, corpo in [('futuro-v99', b''), ('externo-v1', b'nao vazio')]:
            with closing(sqlite3.connect(self.dados / 'tarefas.db')) as db, db:
                db.execute('UPDATE galeria_arquivo SET armazenamento=?,conteudo=? WHERE id=?', (modo, corpo, item['id']))
            with self.assertRaises(ValueError): g.arquivo(self.projeto, item['id'])
            with self.assertRaises(ValueError): self.registrar()

    def test_corpo_externo_zero_bytes(self):
        (self.work / 'vazio.txt').write_bytes(b''); self.recibo['sha'] = self.commit(self.work)
        self.registrar(['vazio.txt']); item, p = self.alvo()
        self.assertEqual(p.read_bytes(), b'')
        self.assertEqual(g.arquivo(self.projeto, item['id'])['conteudo'], '')
        self.assertEqual(self.registrar(['vazio.txt'])['estado'], 'ja_registrado')

    def test_leitura_do_corpo_nao_escreve_ou_abre_sqlite(self):
        self.registrar(); item, _ = self.alvo(); antes = self.inventario()
        with patch('sqlite3.connect', side_effect=AssertionError('SQL de corpo proibido')):
            dados = a.ler(self.projeto, item['sha256'])
        self.assertEqual(hashlib.sha256(dados).hexdigest(), item['sha256'])
        self.assertEqual(antes, self.inventario())

    def test_arquivo_faltando_sem_fallback_git(self):
        self.registrar(); item, p = self.alvo(); p.rename(p.with_name('.captura-' + '1' * 32))
        with patch.object(g, '_git', side_effect=AssertionError('Sem fallback Git')):
            with self.assertRaises(OSError): g.arquivo(self.projeto, item['id'])
        with self.assertRaises(OSError): self.registrar()

    def test_hardlink_e_symlink_corpo_rejeitados(self):
        self.registrar(); item, p = self.alvo(); outro = self.raiz / 'copia'
        os.link(p, outro)
        with self.assertRaises(ValueError): a.ler(self.projeto, item['sha256'])
        with self.assertRaises(ValueError): self.registrar()
        outro.unlink(); p.rename(outro); p.symlink_to(outro)
        with self.assertRaises((OSError, ValueError)): a.ler(self.projeto, item['sha256'])

    def test_hardlink_db_bloqueia_antes_de_mutar(self):
        p = self.dados / 'tarefas.db'; os.link(p, self.raiz / 'db-copia')
        with self.assertRaises(ValueError): self.registrar()
        self.assertFalse((self.dados / a.PASTA).exists())

    def test_pasta_blob_link_ou_permissiva_rejeitada(self):
        outro = self.raiz / 'fora'; outro.mkdir()
        p = self.dados / a.PASTA; p.symlink_to(outro, target_is_directory=True)
        with self.assertRaises((OSError, ValueError)): self.registrar()
        p.unlink(); p.mkdir(mode=0o755)
        with self.assertRaisesRegex(ValueError, 'privacidade'): self.registrar()
        self.assertEqual(list(outro.iterdir()), [])

    def test_pasta_dados_intermediaria_link_rejeitada(self):
        real = self.raiz / 'real'; self.dados.rename(real); self.dados.symlink_to(real, target_is_directory=True)
        with self.assertRaises(OSError): self.registrar()

    def test_troca_durante_leitura_nao_devolve_bytes(self):
        self.registrar(); item, p = self.alvo(); abrir = os.open
        def trocar(nome, flags, *args, **kw):
            fd = abrir(nome, flags, *args, **kw)
            if nome == item['sha256']:
                p.rename(p.with_name('.captura-' + '2' * 32)); p.write_bytes(b'alterado'); p.chmod(0o600)
            return fd
        with patch.object(a.os, 'open', side_effect=trocar), self.assertRaises(ValueError):
            a.ler(self.projeto, item['sha256'])

    def test_orcamento_bytes_e_entradas_antes_de_captura(self):
        for limite in ('MAX_FISICO', 'MAX_ENTRADAS'):
            with patch.object(a, limite, 0), self.assertRaisesRegex(ValueError, 'físico'):
                self.registrar()
            self.assertEqual(list((self.dados / a.PASTA).iterdir()), [])
        self.assertEqual(g.listar(self.projeto)['itens'], [])

    def test_orfaos_contam_sem_limpeza(self):
        p = self.dados / a.PASTA; p.mkdir(mode=0o700)
        orfao = p / ('.captura-' + 'f' * 32); orfao.write_bytes(b'guardado'); orfao.chmod(0o600)
        with patch.object(a, 'MAX_ENTRADAS', 1), self.assertRaises(ValueError): self.registrar()
        self.assertEqual(orfao.read_bytes(), b'guardado')

    def test_corpo_existente_conflitante_nao_sobrescrito(self):
        body = (self.work / 'relatorio.md').read_bytes(); sha = hashlib.sha256(body).hexdigest()
        p = self.dados / a.PASTA; p.mkdir(mode=0o700); alvo = p / sha
        alvo.write_bytes(b'preservar'); alvo.chmod(0o600)
        with self.assertRaises(ValueError): self.registrar()
        self.assertEqual(alvo.read_bytes(), b'preservar')
        self.assertEqual(g.listar(self.projeto)['itens'], [])

    def test_falha_de_link_preserva_orfao_sem_manifesto(self):
        with patch.object(a.os, 'link', side_effect=OSError('disco cheio')):
            with self.assertRaises(OSError): self.registrar()
        p = self.dados / a.PASTA
        self.assertEqual(len(list(p.iterdir())), 1)
        self.assertTrue(next(p.iterdir()).name.startswith('.captura-'))
        self.assertEqual(g.listar(self.projeto)['itens'], [])

    def test_falha_apos_link_nlink2_nunca_aceita(self):
        original = os.unlink
        def falhar(nome, *args, **kw):
            if str(nome).startswith('.captura-'): raise OSError('interrompido')
            return original(nome, *args, **kw)
        with patch.object(a.os, 'unlink', side_effect=falhar), self.assertRaises(OSError): self.registrar()
        p = self.dados / a.PASTA
        self.assertEqual(len(list(p.iterdir())), 2)
        self.assertTrue(all(q.stat().st_nlink == 2 for q in p.iterdir()))
        with self.assertRaises(ValueError): self.registrar()
        self.assertEqual(g.listar(self.projeto)['itens'], [])

    def test_arquivo_de_hash_aparece_antes_do_link_nao_clobber(self):
        original = os.link
        def colidir(src, dst, **kw):
            fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=kw['dst_dir_fd'])
            os.write(fd, b'nao substituir'); os.close(fd)
            return original(src, dst, **kw)
        with patch.object(a.os, 'link', side_effect=colidir), self.assertRaises(FileExistsError): self.registrar()
        self.assertEqual(g.listar(self.projeto)['itens'], [])
        self.assertIn(b'nao substituir', [p.read_bytes() for p in (self.dados / a.PASTA).iterdir()])

    def test_locks_antes_de_qualquer_banco_e_sem_reaquisicao(self):
        lock = self.raiz.parent / ('.' + self.raiz.name + '.atualizacao.lock')
        lock.write_text('atualizador')
        try:
            with patch.object(g, '_banco', side_effect=AssertionError('não abrir banco')):
                with self.assertRaises(FileExistsError): self.registrar()
            self.assertEqual(lock.read_text(), 'atualizador')
        finally: lock.unlink()
        pasta = self.dados / 'publicacoes'; pasta.mkdir()
        (pasta / '7.json').write_text(json.dumps(self.recibo))
        pedido = {'cartao': 7, 'tentativa': self.tentativa, 'pr': 8, 'sha': self.sha, 'arquivos': ['relatorio.md']}
        self.assertEqual(g.registrar(self.projeto, pedido)['estado'], 'registrado')
        self.assertFalse(lock.exists())

    def test_processo_antigo_rejeita_app_substituido(self):
        antes = a.APP_ID
        with patch.object(a, 'APP_ID', (antes[0], antes[1] + 1, antes[2])):
            with patch.object(g, '_banco', side_effect=AssertionError('não abrir banco')):
                with self.assertRaisesRegex(ValueError, 'reinicie'): self.registrar()

    def test_linux_nao_qualificado_nao_faz_fallback_inline(self):
        with patch.object(a, 'DIR_FD', False):
            with self.assertRaisesRegex(ValueError, 'Linux'): self.registrar()
        self.assertFalse((self.dados / a.PASTA).exists())
        self.assertEqual(g.listar(self.projeto)['itens'], [])

    def test_windows_macos_preservam_registro_inline_arquivo_e_replay(self):
        for plataforma in ('win32', 'darwin'):
            (self.work / 'relatorio.md').write_text('Legado ' + plataforma)
            self.recibo['sha'] = self.commit(self.work)
            with patch.object(g.sys, 'platform', plataforma), patch.object(a, 'mutacao', side_effect=AssertionError('Sem backend externo')):
                registro = self.registrar(['relatorio.md'])
                self.assertEqual(self.registrar(['relatorio.md'])['estado'],'ja_registrado')
                item = next(i for i in g.listar(self.projeto)['itens'] if i['id']==registro['id'])
                self.assertEqual(g.arquivo(self.projeto,item['arquivos'][0]['id'])['conteudo'],'Legado '+plataforma)
                g.arquivar(self.projeto,{'id':registro['id'],'arquivada':True})
                self.assertTrue(next(i for i in g.listar(self.projeto)['itens'] if i['id']==registro['id'])['arquivada'])
                g.arquivar(self.projeto,{'id':registro['id'],'arquivada':False})
        self.assertFalse((self.dados / a.PASTA).exists())
        with closing(sqlite3.connect(self.dados/'tarefas.db')) as db:
            self.assertTrue(all(modo=='inline' and corpo for modo,corpo in db.execute('SELECT armazenamento,conteudo FROM galeria_arquivo')))

    def test_windows_macos_cota_logica_e_tentativa_preservadas(self):
        for plataforma in ('win32','darwin'):
            with patch.object(g.sys,'platform',plataforma):
                with patch.object(g,'MAX_MANIFESTOS',0), self.assertRaisesRegex(ValueError,'manifestos'):self.registrar()
                with self.assertRaises(ValueError):g.registrar_publicacao(self.projeto,{**self.recibo,'tentativa':'0'*32},['relatorio.md'])
        self.assertFalse((self.dados/a.PASTA).exists())
        self.assertEqual(g.listar(self.projeto)['itens'],[])

    def test_corpo_linux_nao_e_portado_silenciosamente(self):
        self.registrar();item,p=self.alvo();antes=p.read_bytes()
        for plataforma in ('win32','darwin'):
            with patch.object(g.sys,'platform',plataforma):
                with self.assertRaisesRegex(ValueError,'Linux'):g.arquivo(self.projeto,item['id'])
                with self.assertRaisesRegex(ValueError,'Linux'):self.registrar()
        self.assertEqual(p.read_bytes(),antes)

    def test_trava_substituida_nao_removida(self):
        lock = self.raiz.parent / ('.' + self.raiz.name + '.atualizacao.lock')
        try:
            with self.assertRaisesRegex(ValueError, 'substituída'):
                with a.mutacao(self.projeto):
                    lock.rename(lock.with_name(lock.name + '.guardada'))
                    lock.write_text('outro'); lock.chmod(0o600)
            self.assertEqual(lock.read_text(), 'outro')
        finally:
            lock.unlink(missing_ok=True); lock.with_name(lock.name + '.guardada').unlink(missing_ok=True)

    def test_exclusao_real_subprocesso_nos_dois_sentidos(self):
        codigo = """import atualizar_instalacao as u,sys
from unittest.mock import patch

def parar(*args):
    print('locked',flush=True); sys.stdin.readline(); raise ValueError('fixture')
try:
    with patch.object(u,'preparar',side_effect=parar):
        u.aplicar({'destino':sys.argv[1],'origem':'fixture','anterior':None,'config':None})
except ValueError:
    pass
"""
        env = {**os.environ, 'PYTHONPATH':str(Path(g.__file__).parent)}
        proc = subprocess.Popen([sys.executable, '-c', codigo, str(self.raiz)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=env)
        try:
            self.assertEqual(proc.stdout.readline().strip(), 'locked')
            with self.assertRaises(FileExistsError): self.registrar()
            proc.stdin.write('\n'); proc.stdin.flush(); self.assertEqual(proc.wait(timeout=5), 0)
        finally:
            if proc.poll() is None: proc.kill(); proc.wait()
            proc.stdin.close(); proc.stdout.close()
        with a.mutacao(self.projeto):
            r = subprocess.run([sys.executable, '-c', 'import atualizar_instalacao as u,sys; u.aplicar({"destino":sys.argv[1]})', str(self.raiz)], capture_output=True, env=env)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn(b'FileExistsError', r.stderr)

    def test_crash_de_writer_preserva_lock_global(self):
        lock = self.raiz.parent / ('.' + self.raiz.name + '.atualizacao.lock')
        codigo = """from pathlib import Path
import armazenamento_galeria as a,gestao_cli,sys,os
a.APP=Path(sys.argv[1]); a.APP_ID=a._id(a.APP.lstat())
gestao_cli.pasta_dados=lambda p:a.APP/'dados'
with a.mutacao(a.APP/'projeto'):
    os._exit(17)
"""
        r = subprocess.run([sys.executable, '-c', codigo, str(self.raiz)], capture_output=True,
                           env={**os.environ,'PYTHONPATH':str(Path(g.__file__).parent)})
        try:
            self.assertEqual(r.returncode, 17, r.stderr)
            pid = lock.read_text(); self.assertTrue(pid.isdigit())
            with self.assertRaises(FileExistsError): self.registrar()
            self.assertEqual(lock.read_text(), pid)
        finally: lock.unlink(missing_ok=True)

    def test_app_renomeado_processo_carregado_nao_escreve_novo(self):
        app = self.raiz / 'app-carregado'; app.mkdir()
        shutil.copyfile(a.__file__, app / 'armazenamento_galeria.py')
        codigo = """import armazenamento_galeria as a,sys
print('loaded',flush=True); sys.stdin.readline()
try:
    with a.mutacao(a.APP):
        raise RuntimeError('não deveria obter acesso')
except ValueError as exc:
    assert 'reinicie' in str(exc)
"""
        proc = subprocess.Popen([sys.executable,'-c',codigo],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,text=True,cwd=app,
                                env={**os.environ,'PYTHONPATH':str(app)})
        try:
            self.assertEqual(proc.stdout.readline().strip(),'loaded')
            app.rename(self.raiz/'app-antigo'); app.mkdir()
            proc.stdin.write('\n'); proc.stdin.flush()
            self.assertEqual(proc.wait(timeout=5),0,proc.stderr.read())
            self.assertEqual(list(app.iterdir()),[])
        finally:
            if proc.poll() is None: proc.kill(); proc.wait()
            proc.stdin.close(); proc.stdout.close(); proc.stderr.close()

    def test_banco_legado_grande_nao_migrado_ou_compactado(self):
        self.inline()
        with closing(sqlite3.connect(self.dados / 'tarefas.db')) as db, db:
            db.execute('CREATE TABLE carga_legada (conteudo BLOB)')
            db.execute('INSERT INTO carga_legada VALUES (zeroblob(33554433))')
            antes = db.execute('SELECT id,conteudo,armazenamento FROM galeria_arquivo ORDER BY id').fetchall()
        tamanho = (self.dados/'tarefas.db').stat().st_size
        self.assertEqual(self.registrar()['estado'],'ja_registrado')
        with closing(sqlite3.connect(self.dados/'tarefas.db')) as db:
            self.assertEqual(antes,db.execute('SELECT id,conteudo,armazenamento FROM galeria_arquivo ORDER BY id').fetchall())
            self.assertEqual(db.execute('SELECT length(conteudo) FROM carga_legada').fetchone()[0],33554433)
        self.assertGreaterEqual((self.dados/'tarefas.db').stat().st_size,tamanho)

    def test_40mib_novos_nao_crescem_db_contexto_e_arquivo_preservado(self):
        import contexto_projeto as c
        from funcionarios import id_projeto
        for lote in range(8):
            nomes = []
            for i in range(5):
                nome = f'parte{i}.txt'; nomes.append(nome)
                corpo = f'{lote}:{i}:'.encode().ljust(1024 * 1024, b'x')
                (self.work / nome).write_bytes(corpo)
            self.recibo['sha'] = self.commit(self.work)
            registro = self.registrar(nomes)
            g.arquivar(self.projeto, {'id': registro['id'], 'arquivada': True})
        self.assertLess((self.dados / 'tarefas.db').stat().st_size, c.MAX_BANCO)
        self.assertEqual(sum(q.stat().st_size for q in (self.dados / a.PASTA).iterdir()), 40 * 1024 * 1024)
        self.assertTrue(all(i['arquivada'] for i in g.listar(self.projeto)['itens']))
        (self.projeto / '.office').mkdir()
        (self.projeto / '.office' / 'projeto.json').write_text(json.dumps({'ativo': True, 'kanban': {'repo':'teste/projeto'}}))
        (self.projeto / 'CLAUDE.md').write_text('regra'); (self.projeto / 'PRODUTO.md').write_text('produto')
        (self.projeto / 'docs').mkdir(); (self.projeto / 'docs' / 'ARCHITECTURE_GRAPH.yaml').write_text('arquitetura: segura')
        with closing(sqlite3.connect(self.dados / 'tarefas.db')) as db, db:
            pacote = json.loads(db.execute('SELECT pacote FROM reserva').fetchone()[0])
            pacote['meta'] = {'objetivo': 'pesquisa aceita', 'gdd': {'sha256':'d'*64,'numero':1}}
            db.execute("UPDATE reserva SET estado='concluido',pacote=?", (json.dumps(pacote),))
            ev = {'repo':'teste/projeto','cartao':7,'pr':8,'head':self.recibo['sha'],'merge_commit':'a'*40,
                  'merged_at':'2026-10-12T12:00:00Z','checks':{'gates':[{'estado':'success'}]}}
            db.execute('INSERT INTO conclusao VALUES(?,?,?)', (self.token,json.dumps(ev),1))
        antes = self.inventario()
        r = c.buscar([self.projeto], id_projeto(self.projeto), 'pesquisa')
        self.assertEqual(len(r['resultados']), 1)
        self.assertEqual(r['resultados'][0]['aceite_usuario'], 'nao_inferido')
        self.assertEqual(antes, self.inventario())
        # WAL continua recusado pelo contexto, sem mudar bytes/sidecars da consulta.
        with closing(sqlite3.connect(self.dados / 'tarefas.db')) as db:
            db.execute('PRAGMA journal_mode=WAL'); db.execute('UPDATE reserva SET atualizado=2'); db.commit()
            antes = self.inventario(); r = c.buscar([self.projeto], id_projeto(self.projeto), 'pesquisa')
            self.assertEqual(r['fontes'][-1]['estado'], 'indisponivel_ou_excluida')
            self.assertEqual(antes, self.inventario())


if __name__ == '__main__':
    unittest.main()
