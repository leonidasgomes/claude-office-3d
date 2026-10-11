import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import publicacao_host as h
from controle_tarefas import Controle


class Publicacao(unittest.TestCase):
    def test_git_real_reserva_paths_e_nao_repetir(self):
        with tempfile.TemporaryDirectory() as tmp:
            raiz=Path(tmp);projeto=raiz/'projeto';office=raiz/'office';work=raiz/'worktrees'/'novo';dados=raiz/'dados'
            projeto.mkdir();office.mkdir();work.parent.mkdir();dados.mkdir()
            def git(*args):return subprocess.run(['git',*map(str,args)],check=True,capture_output=True,text=True).stdout.strip()
            remoto=raiz/'remoto.git';git('init','--bare',remoto);git('init','-b','main',projeto)
            git('-C',projeto,'config','user.name','Teste');git('-C',projeto,'config','user.email','teste@example.com')
            (projeto/'base.txt').write_text('base');git('-C',projeto,'add','.');git('-C',projeto,'commit','-m','base')
            git('-C',projeto,'remote','add','origin',remoto);git('-C',projeto,'push','origin','main')
            git('-C',projeto,'worktree','add','-b','work/teste',work,'main')
            pasta=office/'dados'/'worktrees';pasta.mkdir(parents=True)
            (pasta/'recibo.json').write_text(json.dumps({'projeto':str(projeto),'estado':'criado',
                'criados':[{'cartao':7,'worktree':str(work),'branch':'work/teste'}]}))
            cfg={'ciclo':{'ativo':True,'base':'origin/main'},'kanban':{'repo':'teste/projeto'}}
            controle=Controle(dados/'tarefas.db');token=controle.reservar('teste/projeto','7','Dev','codex',{'objetivo':'teste','aceite':'arquivo'},quadro_atual=True)
            controle.transicao(token,'executando')
            (work/'entrega.txt').write_text('resultado')
            original=subprocess.run
            def rodar(args,**kwargs):
                if args[0]=='gh':return subprocess.CompletedProcess(args,0,'https://github.com/teste/projeto/pull/1','')
                return original(args,**kwargs)
            pedido={'cartao':7,'worktree':str(work),'titulo':'Entrega','corpo':'Closes #7\nTeste real'}
            operacional=work/'pedido operação.json'
            operacional.write_text(json.dumps(pedido),encoding='utf-8-sig')
            (work/'dados.json').write_text(json.dumps({'cartao':7,'entrega':'dados reais'}))
            with patch.object(h,'RAIZ',office),patch('gestao_cli.pasta_dados',return_value=dados),patch('gestao_projeto.carregar',return_value=cfg),patch.object(h.subprocess,'run',side_effect=rodar):
                with self.assertRaises(ValueError):h.publicar(projeto,{**pedido,'worktree':str(projeto)})
                git('-C',work,'add','--',operacional.name)
                with self.assertRaisesRegex(ValueError,'já versionado/indexado'):h.publicar(projeto,pedido)
                self.assertFalse((dados/'publicacoes'/'7.json').exists())
                git('-C',work,'restore','--staged','--',operacional.name)
                resultado=h.publicar(projeto,pedido)
                self.assertEqual(resultado['estado'],'publicado')
                self.assertEqual(git('--git-dir',remoto,'rev-parse','refs/heads/work/teste'),resultado['sha'])
                self.assertEqual(git('-C',projeto,'branch','--show-current'),'main')
                self.assertEqual(resultado['arquivos_pedido_excluidos'],[operacional.name])
                arquivos=git('-C',work,'ls-tree','--name-only','HEAD').splitlines()
                self.assertNotIn(operacional.name,arquivos)
                self.assertIn('dados.json',arquivos);self.assertIn('entrega.txt',arquivos)
                self.assertTrue(operacional.exists())
                with self.assertRaisesRegex(ValueError,'anterior'):h.publicar(projeto,pedido)

if __name__=='__main__':unittest.main()
