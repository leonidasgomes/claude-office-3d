"""Preços opcionais não convertem assinatura em fatura nem alteram o ledger."""
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from consumo_providers import Registro
from precos_tokens import carregar, equivalente


class Precos(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.p = Path(self.tmp.name)/'precos_tokens.json'
        self.t = {'provider':'codex', 'modelo':'modelo-teste', 'desde':'2026-01-01',
                  'ate':'2026-12-31', 'fonte':'https://example.org/tarifa-sintetica',
                  'entrada_usd_milhao':'2', 'cache_usd_milhao':'0.5', 'saida_usd_milhao':'8'}
        self.ts = datetime(2026, 10, 10, tzinfo=timezone.utc).timestamp()

    def escrever(self, tarifas=None):
        self.p.write_text(json.dumps({'versao':1,'tarifas':tarifas or [self.t]}), encoding='utf-8')
        return carregar(self.p)

    def test_cache_sem_duplica_e_validade_exclusiva(self):
        tarifas = self.escrever()
        args = ('codex','modelo-teste','informado',self.ts,1000000,200000,100000,'codex.exec/turn.completed')
        self.assertEqual(equivalente(tarifas,*args), Decimal('2.5'))
        for campo, valor in [(0,'opencode'),(0,'codex_local'),(1,'outro'),(2,'configurado'),
                             (5,None),(5,1000001),(7,'desconhecido')]:
            novos=list(args); novos[campo]=valor
            self.assertIsNone(equivalente(tarifas,*novos))
        novos=list(args); novos[3]=datetime(2026,12,31,tzinfo=timezone.utc).timestamp()
        self.assertIsNone(equivalente(tarifas,*novos))

    def test_catalogo_rejeita_sobreposicao_precos_e_repeticoes(self):
        for campo, valor in [('entrada_usd_milhao','NaN'),('cache_usd_milhao','Infinity'),
                             ('saida_usd_milhao',True),('entrada_usd_milhao','-1'),
                             ('ate','2025-01-01'),('provider','opencode')]:
            t=dict(self.t); t[campo]=valor
            with self.subTest(campo=campo,valor=valor), self.assertRaises(ValueError): self.escrever([t])
        with self.assertRaises(ValueError): self.escrever([self.t,self.t])
        self.p.write_text('{"versao":1,"versao":1,"tarifas":[]}',encoding='utf-8')
        with self.assertRaises(ValueError): carregar(self.p)

    def test_resumo_parcial_idempotente_sem_mudar_db(self):
        self.escrever()
        r=Registro(self.p.parent/'uso.db')
        def gravar(chave, cache):
            r.gravar(chave,'codex','modelo-teste','informado','Dev','p','s',
                     'codex.exec/turn.completed',{'entrada':1000000,'cache':cache,'saida':100000,'total':1100000})
        gravar('1',200000); gravar('1',200000); gravar('2',None)
        with closing(sqlite3.connect(r.arquivo)) as db, db: db.execute('UPDATE consumo SET ts=?',(self.ts,))
        antes=r.arquivo.read_bytes()
        resumo=r.resumo(self.ts+1); g=resumo['grupos'][0]
        self.assertEqual((g['amostras'],g['com_preco'],g['equivalente_api_usd']),(2,1,'2.5'))
        self.assertIsNone(resumo['cobranca_usd']); self.assertIsNone(resumo['estimativa_usd'])
        self.assertEqual(antes,r.arquivo.read_bytes())
        self.p.write_text('{}',encoding='utf-8')
        ruim=r.resumo(self.ts+1)
        self.assertEqual(ruim['precos']['estado'],'catálogo inválido')
        self.assertEqual(ruim['grupos'][0]['total'],2200000)
        self.assertNotIn(self.tmp.name,str(ruim))

    def test_tarifas_por_data_nao_precificam_passado_com_preco_novo(self):
        nova=dict(self.t,desde='2026-10-11',ate='2027-01-01',entrada_usd_milhao='4')
        velha=dict(self.t,ate='2026-10-11')
        tarifas=self.escrever([velha,nova])
        for ts, esperado in [(self.ts,'2'),(self.ts+86400,'4')]:
            self.assertEqual(equivalente(tarifas,'codex','modelo-teste','informado',ts,
                                        1000000,0,0,'codex.rollout/token_count.delta'),Decimal(esperado))


if __name__ == '__main__': unittest.main()
