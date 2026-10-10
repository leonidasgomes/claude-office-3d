"""Política única no despacho/painel; REST e projetos temporários, sem GitHub real."""
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
from functools import partial
from http.server import ThreadingHTTPServer
import unittest
from unittest.mock import patch

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
OFFICE = RAIZ / 'office one' if (RAIZ / 'office one').is_dir() else RAIZ
sys.path.insert(0, str(OFFICE))
import gestao_cli
import kanban_painel
import servidor
from funcionarios import id_projeto
from gestao_projeto import validar
from kanban_gestao import Kanban


class Painel(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.raiz = Path(self.tmp.name)
        self.um = self.projeto('um', 1); self.dois = self.projeto('dois', 2)
        self.chamadas = []; self.status = 'Fila'
        self.patch = patch.object(gestao_cli, 'RAIZ', self.raiz / 'dados_app'); self.patch.start(); self.addCleanup(self.patch.stop)
        self.adapter = patch.object(kanban_painel, 'Kanban', side_effect=lambda cfg, cache: Kanban(cfg, cache, chamar=self.api))
        self.adapter.start(); self.addCleanup(self.adapter.stop)

    def projeto(self, nome, numero):
        raiz = self.raiz / nome; (raiz / '.office').mkdir(parents=True)
        cfg = validar({'ativo': True, 'kanban': {'repo': f'owner/{nome}', 'owner': 'owner', 'numero': numero,
            'campo_status': 'Situação', 'campo_time': 'Área', 'backlog': 'Fila', 'andamento': 'Executando', 'feito': 'Entregue'},
            'equipes': [{'nome': 'Dev', 'especialidade': 'Código', 'executor': {'console': 'codex'}}]})
        (raiz / '.office/projeto.json').write_text(json.dumps(cfg), encoding='utf-8')
        return raiz

    def api(self, caminho, metodo='GET', dados=None):
        self.chamadas.append((caminho, metodo))
        if metodo == 'PATCH': self.status = 'Executando'; return {}
        if '/fields?' in caminho:
            return [{'name': 'Situação', 'id': 1, 'options': [{'id': 9, 'name': 'Executando'}]},
                    {'name': 'Área', 'id': 2}, {'name': 'Prioridade', 'id': 3}]
        nome = 'dois' if '/projectsV2/2/' in caminho else 'um'
        if '/items?' in caminho:
            def item(n, url, tipo='Issue'):
                return {'id': n, 'node_id': f'node{n}', 'content_type': tipo,
                        'content': {'html_url': url, 'title': f'{nome} {n}'},
                        'fields': [{'id': 1, 'value': {'name': {'raw': self.status}}},
                                   {'id': 2, 'value': {'raw': 'Dev'}}, {'id': 3, 'value': 'P1'}]}
            return [item(42, f'https://github.com/owner/{nome}/issues/42'),
                    item(43, 'https://github.com/outro/repo/issues/43'),
                    item(44, '', 'DraftIssue'), item(45, f'https://github.com/owner/{nome}/pull/45', 'PullRequest')]
        raise AssertionError(caminho)

    def test_mesmos_campos_cache_e_invalidacao_do_despacho(self):
        dados = kanban_painel.vista([self.um])
        self.assertFalse(dados['erro']); self.assertEqual(dados['repo'], 'owner/um')
        self.assertEqual(dados['colunas'], ['Fila', 'Executando', 'Em revisão', 'Entregue'])
        self.assertEqual([c['numero'] for c in dados['cartoes']], [42, None, 45])
        c = dados['cartoes'][0]; self.assertEqual((c['status'], c['time'], c['prioridade']), ('Fila', 'Dev', 'P1'))
        k = Kanban(gestao_cli.carregar(self.um), gestao_cli.pasta_dados(self.um) / 'kanban.json', chamar=self.api)
        n = len(self.chamadas); self.assertEqual(k.cartao(42)['equipe'], c['time'])
        self.assertEqual(len(self.chamadas), n)
        k.mover(42, 'Executando')
        self.assertEqual(kanban_painel.vista([self.um])['cartoes'][0]['status'], 'Executando')

    def test_varios_projetos_exigem_selecao_sem_consulta(self):
        dados = kanban_painel.vista([self.um, self.dois]); self.assertIn('Selecione', dados['erro'])
        self.assertEqual(self.chamadas, []); self.assertEqual(len(dados['projetos']), 2)
        for raiz in (self.um, self.dois):
            dados = kanban_painel.vista([self.um, self.dois], id_projeto(raiz))
            self.assertEqual(dados['repo'], f'owner/{raiz.name}')
            self.assertTrue(dados['cartoes'][0]['titulo'].startswith(raiz.name))
        self.assertNotIn(str(self.raiz), json.dumps(dados))

    def test_id_desconhecido_nao_aceita_caminho(self):
        dados = kanban_painel.vista([self.um], str(self.dois))
        self.assertTrue(dados['erro']); self.assertEqual(dados['cartoes'], []); self.assertEqual(self.chamadas, [])

    def test_legado_desativado_sem_api_ou_criar_cache(self):
        (self.um / '.office/projeto.json').write_text('{"ativo":false}', encoding='utf-8')
        self.assertIsNone(kanban_painel.vista([self.um])); self.assertFalse(kanban_painel.habilitado([self.um]))
        self.assertEqual(self.chamadas, []); self.assertFalse((self.raiz / 'dados_app').exists())

    def test_politica_invalida_nao_faz_fallback(self):
        (self.um / '.office/projeto.json').write_text('invalido', encoding='utf-8')
        self.assertTrue(kanban_painel.habilitado([self.um]))
        self.assertTrue(kanban_painel.vista([self.um])['erro']); self.assertEqual(self.chamadas, [])
        self.assertFalse(kanban_painel.vista([self.um, self.dois], id_projeto(self.dois))['erro'])

    def test_cache_nao_bloqueia_saude_nem_consulta_api(self):
        self.assertTrue(kanban_painel.vista([self.um], somente_cache=True)['erro'])
        self.assertEqual(self.chamadas, [])
        kanban_painel.vista([self.um]); self.chamadas.clear()
        self.assertFalse(kanban_painel.vista([self.um], somente_cache=True)['erro'])
        self.assertEqual(self.chamadas, [])

    @unittest.skipIf(OFFICE != RAIZ, 'Config pública pertence à edição pública')
    def test_config_publica_ativa_quadro_sem_github_legado(self):
        import configuracao
        cfg = configuracao.normalizar({'projetos':[str(self.um)]})
        with patch.object(servidor, 'cfg', return_value=cfg):
            publico = servidor.config_publica()
        self.assertTrue(publico['github']['kanban']); self.assertTrue(publico['github']['prs'])
        self.assertEqual(publico['github']['repo'], ''); self.assertEqual(self.chamadas, [])

    @unittest.skipIf(OFFICE != RAIZ, 'Cache público pertence à edição pública')
    def test_servidor_legado_mantem_chave_do_cache(self):
        import configuracao
        cfg = configuracao.normalizar({'projetos':[], 'github':{'projeto_owner':'owner','projeto_numero':4}})
        esperado = {'cartoes':[{'titulo':'legado'}]}
        with patch.object(servidor, 'cfg', return_value=cfg), patch.object(servidor._kanban,'obter',return_value=esperado) as cache:
            self.assertIs(servidor.kanban(), esperado)
            self.assertEqual(cache.call_args.args[0][:2], ('owner',4))
    def test_falha_nao_mostra_quadro_de_outro_projeto(self):
        kanban_painel.vista([self.um])
        with patch.object(self, 'api', side_effect=ValueError('PRIVATE endpoint credentials')):
            dados = kanban_painel.vista([self.um, self.dois], id_projeto(self.dois))
        self.assertTrue(dados['erro']); self.assertEqual(dados['cartoes'], [])
        self.assertNotIn('PRIVATE', json.dumps(dados))

    def test_http_query_e_legado(self):
        import rede
        anterior = servidor.Handler.rede; servidor.Handler.rede = rede.Rede(self.raiz, False, False)
        srv = ThreadingHTTPServer(('127.0.0.1', 0), partial(servidor.Handler, directory=str(OFFICE)))
        thread = threading.Thread(target=srv.serve_forever, daemon=True); thread.start()
        try:
            with patch.object(servidor, 'cfg', return_value={'projetos': [str(self.um), str(self.dois)]}, create=True), \
                 patch.object(servidor, 'REPO_LOCAL', self.dois, create=True), patch.object(servidor, 'com_cota', side_effect=lambda d: d):
                con = http.client.HTTPConnection('127.0.0.1', srv.server_address[1], timeout=10)
                try:
                    con.request('GET', '/kanban?projeto=' + id_projeto(self.dois)); r = con.getresponse()
                    self.assertEqual(r.status, 200); self.assertEqual(json.loads(r.read())['repo'], 'owner/dois')
                    con.request('GET', '/kanban?projeto=../fora'); r = con.getresponse()
                    self.assertTrue(json.loads(r.read())['erro'])
                finally: con.close()
        finally:
            srv.shutdown(); srv.server_close(); thread.join(); servidor.Handler.rede = anterior


if __name__ == '__main__': unittest.main()
