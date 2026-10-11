import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import ciclo_painel as c

class Painel(unittest.TestCase):
    def test_leitura_local_sem_caminhos_ids_ou_publicacao_incerta(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'publicacoes').mkdir()
            (p/'ciclo.json').write_text(json.dumps({'id':'privado','pid':123,'estado':'diretor','cartoes':[]}))
            for nome,r in [('bom',{'estado':'publicado','cartao':52,'pr':'https://github.com/a/b/pull/668'}),
                           ('incerto',{'estado':'criando','cartao':270,'pr':'https://github.com/a/b/pull/670'}),
                           ('url',{'estado':'publicado','cartao':1,'pr':'javascript:123/666'})]:
                (p/'publicacoes'/f'{nome}.json').write_text(json.dumps(r))
            db=sqlite3.connect(p/'tarefas.db');db.execute('CREATE TABLE reserva(cartao,equipe,estado)')
            db.execute("INSERT INTO reserva VALUES('36','Team Dev','executando')");db.commit();db.close()
            antes={str(f.relative_to(p)):f.read_bytes() for f in p.rglob('*') if f.is_file()}
            selecionado=((p,{'kanban':{'repo':'a/b'}},{'id':'a'*20}),[], '')
            with patch.object(c,'escolher',return_value=selecionado),patch.object(c,'pasta_dados',return_value=p):
                r=c.vista([], 'a'*20)
            self.assertTrue(r['ok']);self.assertEqual(len(r['publicacoes']),1)
            self.assertNotIn('id',r['ciclo']);self.assertNotIn('pid',r['ciclo'])
            self.assertEqual(r['tarefas'][0]['estado'],'executando')
            self.assertEqual(antes,{str(f.relative_to(p)):f.read_bytes() for f in p.rglob('*') if f.is_file()})
    def test_projeto_desconhecido_nao_le_arquivo(self):
        with patch.object(c,'escolher',return_value=(None,[],'erro')),patch.object(c,'pasta_dados') as ler:
            self.assertFalse(c.vista([], '../segredo')['ok']);ler.assert_not_called()
    def test_erro_nao_omite_reserva_e_finge_equipe_livre(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'ciclo.json').write_text('{')
            with patch.object(c,'escolher',return_value=((p,{}, {'id':'a'*20}),[],'')),patch.object(c,'pasta_dados',return_value=p):
                self.assertFalse(c.vista([],'a'*20)['ok'])

if __name__=='__main__':unittest.main()
