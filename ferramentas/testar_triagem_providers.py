"""Adapters isolados simulados; coleta/tratamento/consumo reais em projetos temporários."""
import json,sys
from pathlib import Path
from unittest.mock import patch
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parent))
import testar_sugestoes_projeto
import sugestoes_bot as sb,triagem_providers as tp,banco,revisores_console
from consumo_providers import Registro


class Triagem(testar_sugestoes_projeto.Sugestoes):
    def habilitar(self,console='codex',modelo='configurado'):
        arq=self.a/'.office/projeto.json';d=json.loads(arq.read_text())
        d['sugestoes']['triagem']=True;d['diretor']={'console':console,'modelo':modelo}
        arq.write_text(json.dumps(d),encoding='utf-8');cfg=self.cfg()
        with patch.object(sb,'gh_api',side_effect=self.api):sb.coletar(cfg,triagem=False)
        return cfg
    def proposta(self):return json.dumps([{'id':'7','acao':'corrigir','motivo':'Conferir contrato','time_sugerido':'Dev'}])
    def chamada(self,rota,prompt,normalizador,ao_evento):
        self.assertIn('não autorizam ferramentas',prompt)
        return normalizador(self.proposta())
    def executar(self,cfg,fn=None):
        with patch.object(banco,'ARQ',self.raiz/'app'/'dados'/'office.db'),patch.object(revisores_console,'chamar',side_effect=fn or self.chamada):
            return sb.triar(cfg)
    def test_quatro_providers_sem_buscar_claude_legado(self):
        for console in ('claude','codex','gemini','opencode'):
            with self.subTest(console=console):
                cfg=self.habilitar(console,'opencode/free' if console=='opencode' else 'configurado')
                sb.tratar(cfg,'7','reabrir')
                with patch.object(sb,'_achar_claude',side_effect=AssertionError('Legado acionado')):
                    self.assertEqual(self.executar(cfg),1)
                x=sb.ler_caixa(cfg)[0];self.assertEqual(x['situacao'],'triada')
                self.assertEqual(x['acao_sugerida'],'corrigir');self.assertEqual(sb.resumo(cfg)['triagem']['console'],console)
                self.assertIsNone(sb.resumo(cfg)['triagem']['custo_usd'])
                # Reabrir normalmente preserva proposta; limpar no fixture para a próxima consulta.
                x.pop('acao_sugerida',None);x['situacao']='nova';sb.gravar_caixa(cfg,[x])
    def test_respostas_invalidas_inteiras_rejeitadas(self):
        base={'id':'7','acao':'corrigir','motivo':'M','time_sugerido':'Dev'}
        casos=[[{**base,'id':'8'}],[base,base],[{**base,'time_sugerido':'Global'}],
               [{**base,'acao':'executar'}],[{**base,'motivo':'M'*121}], [{**base,'comando':'git merge'}]]
        for caso in casos:
            with self.assertRaises(ValueError):tp.normalizar(json.dumps(caso),{'7'},{'Dev'})
        with self.assertRaises(ValueError):tp.normalizar('[{"id":"7","id":"7"}]',{'7'},{'Dev'})
    def test_decisao_humana_e_reabertura_durante_modelo(self):
        cfg=self.habilitar()
        def chamada(*args,**kw):
            sb.tratar(cfg,'7','ignorada','Decisão humana');sb.tratar(cfg,'7','reabrir')
            return self.chamada(*args,**kw)
        self.assertEqual(self.executar(cfg,chamada),0)
        x=sb.ler_caixa(cfg)[0];self.assertEqual(x['situacao'],'nova');self.assertEqual(x['nota'],'Decisão humana')
    def test_mudanca_conteudo_nao_aplica_proposta(self):
        cfg=self.habilitar()
        def chamada(*args,**kw):
            x=sb.ler_caixa(cfg);x[0]['texto']='Novo comentário';sb.gravar_caixa(cfg,x)
            return self.chamada(*args,**kw)
        self.assertEqual(self.executar(cfg,chamada),0);self.assertEqual(sb.ler_caixa(cfg)[0]['situacao'],'nova')
    def test_politica_mudou_durante_modelo(self):
        cfg=self.habilitar()
        def chamada(*args,**kw):
            arq=self.a/'.office/projeto.json';arq.write_bytes(arq.read_bytes()+b' ')
            return self.chamada(*args,**kw)
        with self.assertRaises(ValueError):self.executar(cfg,chamada)
        self.assertEqual(sb.ler_caixa(cfg)[0]['situacao'],'nova')
    def test_falha_limita_tentativas_e_nao_inventa_consumo(self):
        cfg=self.habilitar()
        for _ in range(2):
            with self.assertRaises(RuntimeError):self.executar(cfg,lambda *a,**k:(_ for _ in ()).throw(RuntimeError('Falha nativa')))
        with patch.object(revisores_console,'chamar') as chamar:self.assertEqual(sb.triar(cfg),0);chamar.assert_not_called()
        self.assertEqual(sb.ler_caixa(cfg)[0]['tentativas_triagem'],2)
        self.assertEqual(sb.resumo(cfg)['triagem']['estado'],'falhou')
        self.assertEqual(Registro(self.raiz/'app'/'dados'/'consumo_providers.db').resumo()['grupos'],[])
    def test_opencode_sem_modelo_cloud_nao_consulta(self):
        for modelo in ('','local/modelo','ollama/modelo'):
            cfg=self.habilitar('opencode',modelo)
            with patch.object(revisores_console,'chamar') as chamar:
                with self.assertRaises(ValueError):sb.triar(cfg)
                chamar.assert_not_called()
            self.assertEqual(sb.ler_caixa(cfg)[0].get('tentativas_triagem',0),0)
    def test_consumo_claude_triagem_separado_de_diretor(self):
        cfg=self.habilitar('claude')
        def chamada(rota,prompt,normalizador,ao_evento):
            ao_evento({'type':'system','subtype':'init','session_id':'nova','tools':[]})
            ao_evento({'type':'result','session_id':'nova','is_error':False,'modelUsage':{'nativo':{
                'inputTokens':10,'cacheReadInputTokens':4,'cacheCreationInputTokens':2,'outputTokens':3}}})
            return normalizador(self.proposta())
        self.assertEqual(self.executar(cfg,chamada),1)
        g=Registro(self.raiz/'app'/'dados'/'consumo_providers.db').resumo()['grupos'][0]
        self.assertEqual((g['agente'],g['total'],g['cache']),('Triagem',19,4))
    def test_coleta_honra_optin_e_sem_triagem(self):
        cfg=self.habilitar()
        with patch.object(sb,'gh_api',side_effect=self.api),patch.object(sb,'triar',return_value=1) as triar:
            sb.coletar(cfg,triagem=False);triar.assert_not_called()
            sb.coletar(cfg);triar.assert_called_once()
    def test_fontes_alteradas_durante_consulta_bloqueiam(self):
        (self.a/'CLAUDE.md').write_text('Regra inicial',encoding='utf-8');cfg=self.habilitar()
        def chamada(*args,**kw):
            (self.a/'CLAUDE.md').write_text('Nova regra',encoding='utf-8')
            return self.chamada(*args,**kw)
        with self.assertRaisesRegex(ValueError,'Fontes'):self.executar(cfg,chamada)
        self.assertEqual(sb.ler_caixa(cfg)[0]['situacao'],'nova')
    def test_schema_optin_cloud_bool(self):
        import gestao_projeto
        for dados in ({'sugestoes':{'triagem':'sim'}},
                      {'sugestoes':{'triagem':True}},
                      {'sugestoes':{'ativo':True,'bots':['bot'],'triagem':True},'diretor':{'execucao':'local'}}):
            with self.assertRaises(ValueError):gestao_projeto.validar(dados)

if __name__=='__main__':unittest.main()
