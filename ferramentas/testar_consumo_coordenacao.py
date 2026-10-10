"""Contadores isolados e transporte real com erro; sem inferência cloud."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from consumo_coordenacao import ColetorIsolado
from consumo_providers import Registro
from revisores_console import rodar


class Consumo(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.p=Path(self.tmp.name);self.db=self.p/'consumo.db'

    def coletor(self,console='claude',papel='ceo'):
        return ColetorIsolado(self.db,{'console':console,'modelo':'configurado'},self.p,papel)

    def resultado(self,**extras):
        return {'type':'result','session_id':'s','is_error':False,'modelUsage':{'modelo-nativo':{
            'inputTokens':100,'cacheReadInputTokens':40,'cacheCreationInputTokens':20,'outputTokens':30}},**extras}

    def init(self,c):c.consumir({'type':'system','subtype':'init','tools':[],'session_id':'s'})

    def test_claude_modelo_cache_dedup_e_nao_precifica_assinatura(self):
        c=self.coletor();self.init(c)
        c.consumir(self.resultado());c.consumir(self.resultado())
        g=Registro(self.db).resumo()['grupos'][0]
        self.assertEqual((g['entrada'],g['cache'],g['saida'],g['total'],g['amostras']),(160,40,30,190,1))
        self.assertEqual((g['modelo'],g['origem_modelo'],g['agente']),('modelo-nativo','informado','CEO'))
        self.assertIsNone(Registro(self.db).resumo()['cobranca_usd'])

    def test_sem_init_filhos_ou_sessao_diferente_nao_somam(self):
        c=self.coletor();c.consumir(self.resultado());self.assertFalse(self.db.exists())
        self.init(c);c.consumir(self.resultado(parent_tool_use_id='pai'));c.consumir(self.resultado(session_id='outra'))
        self.assertFalse(self.db.exists())
        c.consumir({'type':'system','subtype':'init','tools':[],'session_id':'mudou'})
        c.consumir(self.resultado());self.assertFalse(self.db.exists())

    def test_erro_com_contadores_preserva_mas_zero_de_crash_nao_rebaixa(self):
        c=self.coletor();self.init(c);c.consumir(self.resultado(is_error=True))
        r=self.resultado(is_error=True)
        for k in r['modelUsage']['modelo-nativo']:r['modelUsage']['modelo-nativo'][k]=0
        c.consumir(r)
        self.assertEqual(Registro(self.db).resumo()['grupos'][0]['total'],190)

    def test_ausencia_campos_nao_vira_zero(self):
        c=self.coletor();self.init(c);r=self.resultado();del r['modelUsage']['modelo-nativo']['cacheCreationInputTokens']
        c.consumir(r);self.assertFalse(self.db.exists())

    def test_codex_gemini_papeis_distintos_e_agregado_nao_duplica(self):
        c=self.coletor('codex');c.consumir({'type':'turn.completed','usage':{'input_tokens':100,'cached_input_tokens':20,'output_tokens':30}})
        g=self.coletor('gemini','diretor');g.consumir({'type':'result','stats':{'total_tokens':999,'models':{
            'gemini-real':{'input_tokens':20,'cached':5,'output_tokens':10,'total_tokens':30}}}})
        gs=Registro(self.db).resumo()['grupos'];self.assertEqual(sum(g['total'] for g in gs),160)
        self.assertEqual({g['agente'] for g in gs},{'CEO','Diretor'})

    def test_opencode_conta_partes_uma_vez(self):
        c=self.coletor('opencode')
        ev={'type':'step_finish','sessionID':'s','part':{'id':'p','sessionID':'s','type':'step-finish','tokens':{
            'input':10,'output':5,'reasoning':2,'cache':{'read':3,'write':1}}}}
        c.consumir(ev);c.consumir(ev)
        g=Registro(self.db).resumo()['grupos'][0];self.assertEqual((g['entrada'],g['saida'],g['amostras']),(14,7,1))

    def test_transporte_nao_descarta_consumo_por_exit_erro(self):
        c=self.coletor('codex');f=self.p/'fake.py'
        ev={'type':'turn.completed','usage':{'input_tokens':10,'cached_input_tokens':0,'output_tokens':2}}
        f.write_text('import json,sys\nprint(json.dumps('+repr(ev)+'))\nsys.exit(7)\n',encoding='utf-8')
        with self.assertRaises(RuntimeError):
            rodar([sys.executable,str(f)],self.p,{},ao_saida=lambda s:[c.consumir(json.loads(l)) for l in s.splitlines()])
        self.assertEqual(Registro(self.db).resumo()['grupos'][0]['total'],12)

    def test_adapter_claude_define_uuid_e_rejeita_sessao_foreign_sem_contar(self):
        import revisores_console as rc
        for correta in (True,False):
            db=self.p/('correta.db' if correta else 'foreign.db')
            c=ColetorIsolado(db,{'console':'claude'},self.p,'ceo')
            def transporte(args,pasta,env,entrada=None,timeout=600,ao_saida=None):
                if '--help' in args:return '--safe-mode --tools --strict-mcp-config --no-session-persistence --verbose --session-id'
                self.assertIn('--session-id',args);sessao=args[args.index('--session-id')+1] if correta else 'foreign'
                fluxo=[{'type':'system','subtype':'init','tools':[],'session_id':sessao},
                       self.resultado(session_id=sessao,result='{}')]
                texto='\n'.join(json.dumps(e) for e in fluxo)
                ao_saida(texto);return texto
            with patch.object(rc,'selecionar',return_value=(SimpleNamespace(nome='claude'),'native')),patch.object(rc,'rodar',side_effect=transporte):
                if correta:self.assertEqual(rc.chamar({'console':'claude'},'Contexto',normalizador=json.loads,ao_evento=c.consumir),{})
                else:
                    with self.assertRaisesRegex(RuntimeError,'sessão nova'):
                        rc.chamar({'console':'claude'},'Contexto',normalizador=json.loads,ao_evento=c.consumir)
            self.assertEqual(db.exists(),correta)


if __name__=='__main__':unittest.main()
