"""Integração da política com consoles e admissão local, sem chamadas pagas."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from contextlib import closing
import sqlite3
import time
import json
import os
import subprocess

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import console_provider
from gestao_projeto import validar, executor
from providers_console import PROVIDERS, Eventos
from recursos_local import reservar, verificar


class GestaoExecucao(unittest.TestCase):
    def test_sandbox_politica_propagado_e_argumento_divergente_bloqueado(self):
        with tempfile.TemporaryDirectory() as tmp:
            raiz=Path(tmp);(raiz/'.office').mkdir()
            (raiz/'.office/projeto.json').write_text(json.dumps({'ativo':True,
                'ceo':{'console':'codex','sandbox':'workspace-write'}}),encoding='utf-8')
            with patch('console_provider.selecionar',return_value=(PROVIDERS['codex'],'codex')), \
                 patch('console_provider.executar',return_value=0) as rodar:
                self.assertEqual(console_provider.main(['--projeto',tmp,'--papel','ceo']),0)
                self.assertEqual(rodar.call_args.kwargs['sandbox'],'workspace-write')
                rodar.reset_mock()
                self.assertEqual(console_provider.main(['--projeto',tmp,'--papel','ceo','--sandbox','read-only']),2)
                rodar.assert_not_called()

    def test_cli_windows_codificacao_utf8_sem_depender_do_terminal(self):
        with tempfile.TemporaryDirectory() as tmp:
            raiz=Path(tmp);(raiz/'.office').mkdir()
            (raiz/'.office/projeto.json').write_text(json.dumps({'equipes':[
                {'nome':'QA ≥ 2','especialidade':'ação','executor':{'console':'codex'}}]}),encoding='utf-8')
            r=subprocess.run([sys.executable,str(Path(console_provider.__file__).with_name('gestao_cli.py')),
                '--projeto',tmp,'estado'],env={**os.environ,'PYTHONIOENCODING':'ascii'},capture_output=True)
            self.assertEqual(r.returncode,0,r.stderr.decode('utf-8'))
            self.assertIn('QA ≥ 2',r.stdout.decode('utf-8'))

    def test_painel_nao_expoe_prompt_token_ou_caminhos(self):
        import gestao_cli
        from gestao_painel import resumo
        from controle_tarefas import Controle
        with tempfile.TemporaryDirectory() as pasta:
            raiz = Path(pasta) / "projeto"
            (raiz / ".office").mkdir(parents=True)
            cfg = {"ativo": True, "kanban": {"repo": "owner/repo"}}
            (raiz / ".office" / "projeto.json").write_text(json.dumps(cfg), encoding="utf-8")
            with patch.object(gestao_cli, "RAIZ", Path(pasta) / "instalacao"):
                banco = gestao_cli.pasta_dados(raiz) / "tarefas.db"
                c = Controle(banco)
                token = c.reservar("owner/repo", "1", "Dev", "codex", {"objetivo": "PROMPT_PRIVADO", "aceite": "teste"}, True)
                dados = json.dumps(resumo([raiz]))
                self.assertNotIn(token, dados)
                self.assertNotIn("PROMPT_PRIVADO", dados)
                self.assertNotIn(str(raiz), dados)
                self.assertIn("reservado", dados)
                self.assertEqual(resumo([raiz])["projetos"][0]["ceo"]["console"], "claude")
                c.transicao(token, "bloqueado")
                saude=resumo([raiz])["projetos"][0]["saude_tarefas"]
                self.assertEqual(saude['contagens']['bloqueada'],1)
                self.assertEqual(saude['pendencias'][0]['cartao'],'1')

    def test_lotes_no_painel_sao_sanitizados_e_somente_leitura(self):
        import gestao_painel
        with tempfile.TemporaryDirectory() as tmp:
            raiz=Path(tmp); (raiz/'.office').mkdir()
            (raiz/'.office/projeto.json').write_text(json.dumps({'ativo':True,'kanban':{'repo':'owner/repo'}}),encoding='utf-8')
            dados=raiz/'dados'; pasta=dados/'lotes'; pasta.mkdir(parents=True)
            ident='a'*32
            registro={'id':ident,'repo':'owner/repo','estado':'incerto','atualizado':1234,
                'cartoes':[42,43],'resultados':[{'cartao':42,'estado':'revisao','codigo':0,'prompt':'SEGREDO'}],
                'cartao_em_execucao':43,'token':'TOKEN_PRIVADO','caminho':str(raiz)}
            arq=pasta/(ident+'.json'); arq.write_text(json.dumps(registro),encoding='utf-8'); antes=arq.read_bytes()
            with patch.object(gestao_painel,'pasta_dados',return_value=dados):
                painel=gestao_painel.resumo([raiz])
            lote=painel['projetos'][0]['lotes']['itens'][0]
            self.assertEqual((lote['estado'],lote['cartao_em_execucao']),('incerto',43))
            self.assertEqual(lote['resultados'],[{'cartao':42,'estado':'revisao','codigo':0}])
            texto=json.dumps(painel)
            for proibido in ('SEGREDO','TOKEN_PRIVADO',str(raiz)):
                self.assertNotIn(proibido,texto)
            self.assertEqual(arq.read_bytes(),antes)

    def test_lote_paralelo_aceita_retorno_fora_de_ordem_e_rejeita_conflitos(self):
        import gestao_painel
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp); pasta=base/'lotes'; pasta.mkdir()
            r={'id':'c'*32,'repo':'owner/repo','estado':'executando','atualizado':1234,
               'cartoes':[42,43,44],'resultados':[{'cartao':43,'estado':'revisao','codigo':0}],
               'cartao_em_execucao':None,'paralelismo':2,'cartoes_em_execucao':[42,44]}
            arq=pasta/(r['id']+'.json')
            def ler():
                arq.write_text(json.dumps(r),encoding='utf-8')
                with patch.object(gestao_painel,'pasta_dados',return_value=base):
                    return gestao_painel.lotes(base,'owner/repo')
            self.assertEqual(ler()['itens'][0]['resultados'][0]['cartao'],43)
            for chave,valor in [('cartoes_em_execucao',[42,43]),('cartoes_em_execucao',[42,42]),
                                 ('paralelismo',True),('estado','processado')]:
                anterior=r[chave]; r[chave]=valor
                self.assertEqual(ler()['problemas'],1)
                r[chave]=anterior

    def test_relatorio_corrompido_nao_esconde_projeto_e_processado_parcial_e_rejeitado(self):
        import gestao_painel
        with tempfile.TemporaryDirectory() as tmp:
            raiz=Path(tmp); (raiz/'.office').mkdir()
            (raiz/'.office/projeto.json').write_text(json.dumps({'ativo':True,'kanban':{'repo':'owner/repo'}}),encoding='utf-8')
            pasta=raiz/'dados/lotes'; pasta.mkdir(parents=True)
            (pasta/('a'*32+'.json')).write_text('{incompleto',encoding='utf-8')
            registro={'id':'b'*32,'repo':'owner/repo','estado':'processado','atualizado':1234,
                'cartoes':[42,43],'resultados':[{'cartao':42,'estado':'revisao','codigo':0}], 'cartao_em_execucao':None}
            (pasta/('b'*32+'.json')).write_text(json.dumps(registro),encoding='utf-8')
            with patch.object(gestao_painel,'pasta_dados',return_value=pasta.parent):
                projeto=gestao_painel.resumo([raiz])['projetos'][0]
            self.assertTrue(projeto['ativo']); self.assertNotIn('erro',projeto)
            self.assertEqual(projeto['lotes']['itens'],[]); self.assertEqual(projeto['lotes']['problemas'],2)

    def test_lotes_limite_e_repo_distinto_nao_e_misturado(self):
        from gestao_painel import lotes
        with tempfile.TemporaryDirectory() as tmp:
            dados=Path(tmp); pasta=dados/'lotes'; pasta.mkdir()
            for n in range(15):
                ident=format(n,'032x')
                registro={'id':ident,'repo':'owner/repo','estado':'processado','atualizado':1234+n,
                    'cartoes':[42],'resultados':[{'cartao':42,'estado':'revisao','codigo':0}], 'cartao_em_execucao':None}
                (pasta/(ident+'.json')).write_text(json.dumps(registro),encoding='utf-8')
            with patch('gestao_painel.pasta_dados',return_value=dados):
                r=lotes(dados,'owner/repo'); outro=lotes(dados,'owner/outro')
            self.assertEqual(len(r['itens']),10); self.assertTrue(r['limitado'])
            self.assertEqual(outro['itens'],[]); self.assertEqual(outro['problemas'],15)

    def test_lotes_link_fora_do_diretorio_nao_e_lido(self):
        from gestao_painel import lotes
        with tempfile.TemporaryDirectory() as tmp:
            raiz=Path(tmp); dados=raiz/'dados'; dados.mkdir(); fora=raiz/'fora'; fora.mkdir()
            registro={'id':'a'*32,'repo':'owner/repo','estado':'preparado','atualizado':1234,
                'cartoes':[42],'resultados':[],'cartao_em_execucao':None}
            (fora/('a'*32+'.json')).write_text(json.dumps(registro),encoding='utf-8')
            try: (dados/'lotes').symlink_to(fora,target_is_directory=True)
            except OSError:
                if os.name!='nt': self.skipTest('Sistema não permite symlink nesta conta')
                ambiente={**os.environ,'TEST_LOTES_LINK':str(dados/'lotes'),'TEST_LOTES_SOURCE':str(fora)}
                r=subprocess.run(['powershell','-NoProfile','-NonInteractive','-Command',
                    'New-Item -ItemType Junction -Path $env:TEST_LOTES_LINK -Target $env:TEST_LOTES_SOURCE -ErrorAction Stop | Out-Null'],
                    env=ambiente,capture_output=True,text=True,timeout=15)
                if r.returncode: self.skipTest('Sistema não permite junction nesta conta')
            with patch('gestao_painel.pasta_dados',return_value=dados): r=lotes(dados,'owner/repo')
            self.assertEqual(r['itens'],[]); self.assertEqual(r['problemas'],1)

    def test_intervalos_parciais_modelos_e_local_sao_separados(self):
        from controle_tarefas import Controle
        from gestao_painel import desempenho
        with tempfile.TemporaryDirectory() as tmp:
            c=Controle(Path(tmp)/'tarefas.db')
            for n,modo,duracao in ((1,'cloud',8),(2,'cloud',12),(3,'cloud',None),(4,'local',4)):
                token=c.reservar('owner/repo',str(n),'Dev','codex',{'objetivo':'x','aceite':'y',
                    'executor':{'console':'codex','modelo':'modelo-configurado','execucao':modo}},True)
                c.transicao(token,'executando'); ident=c.iniciar_execucao(token)
                if duracao is not None: c.terminar_execucao(ident,0,duracao)
            with closing(sqlite3.connect(c.banco)) as db:
                r=desempenho(db,'owner/repo')
            grupos={g['execucao']:g for g in r['grupos']}
            self.assertEqual((grupos['cloud']['media_seg'],grupos['cloud']['com_intervalo'],grupos['cloud']['tentativas']),(10,2,3))
            self.assertEqual(grupos['cloud']['sem_retorno'],1)
            self.assertEqual((grupos['local']['media_seg'],grupos['local']['tentativas']),(4,1))
            self.assertIsNone(r['por_cartao']['3']['duracao_seg'])
            self.assertNotIn('token',json.dumps(r))

    def test_intervalos_recusam_retorno_inconsistente(self):
        from controle_tarefas import Controle
        from gestao_painel import desempenho
        with tempfile.TemporaryDirectory() as tmp:
            c=Controle(Path(tmp)/'tarefas.db')
            token=c.reservar('owner/repo','1','Dev','claude',{'objetivo':'x','aceite':'y','executor':{}},True)
            c.transicao(token,'executando'); ident=c.iniciar_execucao(token)
            with closing(sqlite3.connect(c.banco)) as db,db:
                inicio=db.execute('SELECT inicio FROM execucao_tarefa').fetchone()[0]
                casos=((None,4,None),(None,None,0),(inicio-1,4,0),
                       (inicio+1,None,0),(inicio+1,4,None),(inicio+1,-4,0),
                       (inicio+1,4,0.5),(float('inf'),4,0))
                for fim,duracao,codigo in casos:
                    with self.subTest(fim=fim,duracao=duracao,codigo=codigo):
                        db.execute('UPDATE execucao_tarefa SET fim=?,duracao_seg=?,codigo=? WHERE id=?',
                                   (fim,duracao,codigo,ident))
                        with self.assertRaises(ValueError): desempenho(db,'owner/repo')
                db.execute('UPDATE execucao_tarefa SET fim=?,duracao_seg=0,codigo=1 WHERE id=?',
                           (inicio,ident))
                g=desempenho(db,'owner/repo')['grupos'][0]
                self.assertEqual((g['saida_zero'],g['saida_nao_zero'],g['media_seg']),(0,1,0))

    def test_cobertura_exatamente_mil_e_truncamento_por_projeto(self):
        from controle_tarefas import Controle
        from gestao_painel import desempenho
        with tempfile.TemporaryDirectory() as tmp:
            c=Controle(Path(tmp)/'tarefas.db'); agora=1000000
            token=c.reservar('owner/repo','1','Dev','codex',{'objetivo':'x','aceite':'y','executor':{}},True)
            outro=c.reservar('other/repo','2','Dev','gemini',{'objetivo':'x','aceite':'y','executor':{}},True)
            with closing(sqlite3.connect(c.banco)) as db,db:
                def inserir(ident,dono,inicio):
                    db.execute('INSERT INTO execucao_tarefa VALUES (?,?,?,?,?,?,?,?,?,?)',
                               (ident,dono,'codex','x','configurado','cloud',inicio,inicio,2,0))
                for n in range(1000): inserir(str(n),token,agora-n)
                inserir('outro',outro,agora); inserir('antigo',token,agora-7*86400-1)
                inserir('futuro',token,agora+1)
                r=desempenho(db,'owner/repo',agora)
                self.assertFalse(r['limitado']); self.assertEqual(r['grupos'][0]['tentativas'],1000)
                inserir('extra',token,agora-1001)
                r=desempenho(db,'owner/repo',agora)
                self.assertTrue(r['limitado']); self.assertEqual(r['grupos'][0]['tentativas'],1000)
                self.assertEqual(r['por_cartao']['1']['inicio'],agora)

    def test_historico_persiste_apos_nova_reserva_sem_virar_atividade_atual(self):
        from controle_tarefas import Controle
        from gestao_painel import desempenho
        with tempfile.TemporaryDirectory() as tmp:
            c=Controle(Path(tmp)/'tarefas.db')
            pacote={'objetivo':'x','aceite':'y','executor':{'modelo':'anterior'}}
            velho=c.reservar('owner/repo','42','Dev','claude',pacote,True)
            c.transicao(velho,'executando'); tentativa=c.iniciar_execucao(velho)
            c.terminar_execucao(tentativa,1,5); c.transicao(velho,'cancelado')
            novo=c.reservar('owner/repo','42','Dev','codex',{'objetivo':'x','aceite':'y'},True)
            with closing(sqlite3.connect(c.banco)) as db:
                r=desempenho(db,'owner/repo')
                self.assertEqual((r['grupos'][0]['console'],r['grupos'][0]['saida_nao_zero']),('claude',1))
                self.assertEqual(r['por_cartao'],{})
                self.assertFalse(r['historico_sem_vinculo'])
                self.assertEqual(desempenho(db,'other/repo')['grupos'],[])
                self.assertNotIn(velho,json.dumps(r)); self.assertNotIn(novo,json.dumps(r))
            c.transicao(novo,'executando'); c.iniciar_execucao(novo)
            with closing(sqlite3.connect(c.banco)) as db:
                r=desempenho(db,'owner/repo')
                self.assertEqual(len(r['grupos']),2)
                self.assertEqual(r['por_cartao']['42']['console'],'codex')
                self.assertIsNone(r['por_cartao']['42']['fim'])

    def test_banco_anterior_backfill_somente_vinculo_comprovavel(self):
        from controle_tarefas import Controle
        from gestao_painel import desempenho
        with tempfile.TemporaryDirectory() as tmp:
            c=Controle(Path(tmp)/'tarefas.db')
            token=c.reservar('owner/repo','42','Dev','codex',{'objetivo':'x','aceite':'y'},True)
            c.transicao(token,'executando'); c.iniciar_execucao(token)
            with closing(sqlite3.connect(c.banco)) as db,db:
                db.execute('DROP TABLE execucao_contexto')
                db.execute('INSERT INTO execucao_tarefa VALUES (?,?,?,?,?,?,?,?,?,?)',
                           ('orfao','token-substituido','gemini','x','configurado','cloud',time.time(),None,None,None))
            with closing(sqlite3.connect(c.banco.resolve().as_uri()+'?mode=ro',uri=True)) as db:
                r=desempenho(db,'owner/repo')
                self.assertTrue(r['historico_sem_vinculo']); self.assertEqual(len(r['grupos']),1)
                self.assertIsNone(db.execute("SELECT 1 FROM sqlite_master WHERE name='execucao_contexto'").fetchone())
            Controle(c.banco)
            with closing(sqlite3.connect(c.banco)) as db,db:
                self.assertEqual(db.execute('SELECT * FROM execucao_contexto').fetchall(),[(token,'owner/repo','42')])
                db.execute("UPDATE reserva SET estado='cancelado'")
            c.reservar('owner/repo','42','Dev','claude',{'objetivo':'x','aceite':'y'},True)
            with closing(sqlite3.connect(c.banco)) as db:
                r=desempenho(db,'owner/repo')
                self.assertTrue(r['historico_sem_vinculo']); self.assertEqual(len(r['grupos']),1)
                self.assertEqual(r['por_cartao'],{})

    def test_contexto_divergente_nao_atribui_tentativa_a_outro_projeto(self):
        from controle_tarefas import Controle
        from gestao_painel import desempenho
        with tempfile.TemporaryDirectory() as tmp:
            c=Controle(Path(tmp)/'tarefas.db')
            token=c.reservar('owner/repo','42','Dev','codex',{'objetivo':'x','aceite':'y'},True)
            c.transicao(token,'executando'); c.iniciar_execucao(token)
            with closing(sqlite3.connect(c.banco)) as db,db:
                db.execute("UPDATE execucao_contexto SET projeto='other/repo'")
                for repo in ('owner/repo','other/repo'):
                    with self.assertRaises(ValueError): desempenho(db,repo)
            with self.assertRaises(ValueError): Controle(c.banco)

    def test_painel_legado_sem_tabela_de_intervalos_nao_migra_por_leitura(self):
        from controle_tarefas import Controle
        from gestao_painel import desempenho
        with tempfile.TemporaryDirectory() as tmp:
            arq=Path(tmp)/'tarefas.db'; Controle(arq)
            with closing(sqlite3.connect(arq)) as db,db: db.execute('DROP TABLE execucao_tarefa')
            with closing(sqlite3.connect(arq.resolve().as_uri()+'?mode=ro',uri=True)) as db:
                r=desempenho(db,'owner/repo')
                self.assertEqual(r['grupos'],[])
                self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='execucao_tarefa'").fetchone())

    def test_ceo_configurado_e_modelo_sem_fallback(self):
        with tempfile.TemporaryDirectory() as pasta:
            raiz = Path(pasta)
            (raiz / ".office").mkdir()
            cfg = {"ativo": True, "ceo": {"console": "gemini", "modelo": "modelo-aprovado"}}
            (raiz / ".office" / "projeto.json").write_text(json.dumps(cfg), encoding="utf-8")
            with patch("console_provider.selecionar", return_value=(PROVIDERS["gemini"], "gemini")) as selecionar, \
                    patch("console_provider.executar", return_value=0) as executar:
                self.assertEqual(console_provider.main(["--projeto", pasta, "--papel", "ceo"]), 0)
                selecionar.assert_called_once_with("gemini")
                args = executar.call_args.args
                self.assertEqual(args[5], "modelo-aprovado")
                self.assertIn("Papel CEO", args[4])
                self.assertIn(".office/projeto.json", args[4])
            with patch("console_provider.executar") as executar:
                self.assertEqual(console_provider.main(["--projeto", pasta, "--papel", "ceo", "--provider", "codex"]), 2)
                executar.assert_not_called()

    def test_rota_local_so_simples_no_perfil_fraco(self):
        cfg = validar({"ativo": True, "local": {"ativo": True}, "rotas": {
            "simples": {"console": "opencode", "execucao": "local", "modelo": "ollama/teste"},
            "implementacao": {"console": "opencode", "execucao": "local", "modelo": "ollama/teste"}}})
        self.assertEqual(executor(cfg, escopo="simples")["execucao"], "local")
        with self.assertRaises(ValueError):
            executor(cfg, escopo="implementacao")

    def test_recursos_ram_e_blender(self):
        cfg = validar({"local": {"ativo": True}})
        for estado in ({"ram_livre_gb": 7, "pesados": []},
                       {"ram_livre_gb": 16, "pesados": ["blender.exe"]},
                       {"ram_livre_gb": 16}, {"ram_livre_gb": float("nan"), "pesados": []}):
            with self.subTest(estado=estado), self.assertRaises(ValueError):
                verificar(cfg, estado)
        verificar(cfg, {"ram_livre_gb": 16, "pesados": [], 'cpu_uso_pct':10,
                       'ollama':{'quantidade':0,'memoria_bytes':0,'vram_bytes':0},
                       'gpu':{'estado':'indisponivel','gpus':[]}})

    def test_reserva_global_e_liberacao(self):
        cfg = validar({"local": {"ativo": True}})
        medidor = lambda: {"ram_livre_gb": 16, "pesados": [], 'cpu_uso_pct':10,
                          'ollama':{'quantidade':0,'memoria_bytes':0,'vram_bytes':0},
                          'gpu':{'estado':'indisponivel','gpus':[]}}
        with tempfile.TemporaryDirectory() as pasta:
            banco = Path(pasta) / "local.db"
            with reservar(banco, cfg, medidor=medidor, vivo=lambda _: True):
                with self.assertRaises(ValueError):
                    with reservar(banco, cfg, medidor=medidor, vivo=lambda _: True):
                        self.fail("Admitiu inferência duplicada")
            with reservar(banco, cfg, medidor=medidor):
                pass

    def test_gemini_eventos_e_comando_preservam_permissoes(self):
        comando = PROVIDERS["gemini"].comando("gemini", Path("."), "tarefa", "modelo", "id")
        self.assertIn("--resume", comando)
        self.assertIn("stream-json", comando)
        self.assertNotIn("--yolo", comando)
        e = Eventos("gemini", "ceo")
        self.assertEqual(e.converter({"type": "init", "session_id": "id"}), [])
        self.assertEqual(e.converter({"type": "message", "role": "assistant", "content": "plano"})[0]["sessao"], "id")
        e.converter({"type": "tool_use", "tool_id": "t", "tool_name": "read_file", "parameters": {"path": "PRODUTO.md"}})
        fim = e.converter({"type": "tool_result", "tool_id": "t", "status": "error"})[0]
        self.assertEqual(fim["ferramenta"], "read_file")
        self.assertFalse(fim["ok"])
        self.assertEqual(e.converter({"type": "result"})[0]["tipo"], "ocioso")


if __name__ == "__main__":
    unittest.main()
