import sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import servidor as s

class SaudeProjeto(unittest.TestCase):
    def test_legado_sem_gestao_preservado(self):
        with patch('kanban_painel.escolher',return_value=None),patch.object(s,'cfg',return_value={'projetos':[]}):
            self.assertIsNone(s.saude_projeto())
    def test_sem_selecao_nao_consulta_github(self):
        with patch('kanban_painel.escolher',return_value=(None,[], 'Selecione o projeto')),patch.object(s,'cfg',return_value={'projetos':[]}),patch.object(s,'prs_projeto') as prs:
            self.assertEqual(s.saude_projeto()['erro'],'Selecione o projeto');prs.assert_not_called()
    def test_filtra_eventos_e_usa_kanban_prs_do_mesmo_projeto(self):
        pid='a'*20;politica={'kanban':{'repo':'exemplo/projeto'}}
        cfg={'projetos':['projeto'],'alertas':{'parado_horas':24}}
        eventos=[{'projeto_id':pid,'tipo':'fala'},{'projeto_id':'b'*20,'tipo':'fala'},{'tipo':'fala'}]
        with patch('kanban_painel.escolher',return_value=((Path('projeto'),politica,{'id':pid}),[],'')),patch.object(s,'cfg',return_value=cfg),patch.object(s.banco,'ler_eventos',return_value=(3,eventos)),patch.object(s,'kanban',return_value={'cartoes':[],'erro':''}) as kanban,patch.object(s,'prs_projeto',return_value={'prs':[{'numero':1}],'erro':''}) as prs,patch.object(s.saude,'resumo',return_value={'sem_prs':True}) as resumo:
            dados=s.saude_projeto(pid)
            kanban.assert_called_once_with(pid);prs.assert_called_once_with(projeto=pid)
            self.assertEqual(resumo.call_args.args[2],[eventos[0]])
            self.assertEqual(dados['projeto_id'],pid);self.assertEqual(dados['prs']['prs'][0]['numero'],1)
            self.assertNotIn('fora do ar',dados['sem_prs_motivo'])

if __name__=='__main__':unittest.main()
