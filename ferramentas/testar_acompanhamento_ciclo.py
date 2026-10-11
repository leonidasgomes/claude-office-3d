import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import acompanhamento_ciclo as a


class Acompanhamento(unittest.TestCase):
    def test_recibos_e_reservas_somente_leitura(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p/'ciclo.json').write_text(json.dumps({'id':'teste','estado':'diretor'}))
            (p/'publicacoes').mkdir()
            (p/'publicacoes'/'270.json').write_text(json.dumps(
                {'estado':'publicado','cartao':270,'pr':'https://github.com/a/b/pull/670'}))
            (p/'publicacoes'/'52.json').write_text(json.dumps({'estado':'criando','cartao':52}))
            db = sqlite3.connect(p/'tarefas.db')
            db.execute('CREATE TABLE reserva(cartao TEXT,equipe TEXT,estado TEXT)')
            db.execute("INSERT INTO reserva VALUES('628','Team Lead Arch','bloqueado')")
            db.commit();db.close()
            antes = {f.name:f.read_bytes() for f in p.rglob('*') if f.is_file()}
            with patch.object(a,'pasta_dados',return_value=p):
                estado,reservas,prs=a.ler(p)
            self.assertEqual(prs,[{'cartao':270,'pr':'https://github.com/a/b/pull/670'}])
            self.assertEqual(reservas[0]['estado'],'bloqueado')
            self.assertEqual(antes,{f.name:f.read_bytes() for f in p.rglob('*') if f.is_file()})

    def test_candidatos_nao_sao_execucao_e_prazo_nao_negativo(self):
        s=a.texto('p',{'estado':'diretor','limite':2,'cartoes':[{'cartao':52,'equipe':'Arch'}]},[],[],False,10)
        self.assertIn('não são equipes executando',s)
        self.assertIn('0 min',s)
        self.assertIn('não confirmado',s)
        self.assertNotIn('Despacho atual',s)

    def test_mudanca_sessao_nao_segue_outro_ciclo(self):
        with patch.object(a,'ler',side_effect=[({'id':'a','estado':'diretor'},[],[]),({'id':'b'},[],[])]), \
             patch.object(a,'coordenador_vivo',return_value=True),patch.object(a.time,'sleep'),patch('builtins.print') as imprimir:
            self.assertEqual(a.acompanhar(Path('p')),0)
            self.assertTrue(any('sessão mudou' in str(x) for x in imprimir.call_args_list))

    def test_erro_de_leitura_visivel(self):
        with patch.object(a,'ler',side_effect=ValueError('arquivo parcial')),patch('builtins.print') as imprimir:
            self.assertEqual(a.acompanhar(Path('p'),True),0)
            self.assertTrue(any('não é prova de parada' in str(x) for x in imprimir.call_args_list))


if __name__=='__main__':unittest.main()
