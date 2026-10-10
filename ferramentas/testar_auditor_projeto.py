"""Auditoria cloud simulada, arquivo/Placar/decisões reais; nenhuma escrita GitHub."""
import json,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
import testar_xp_projeto
import auditor_projeto as au,xp_projeto,gestao_projeto,auditor_xp,configuracao

class Auditor(testar_xp_projeto.XPProjeto):
    def habilitar(self,p=None):
        p=p or self.a;arq=p/'.office/projeto.json';d=json.loads(arq.read_text())
        d.update(auditor={'ativo':True},revisao={'ativo':True,'clouds_distintas':2,'separar_autor':True,'revisores':[
            {'nome':'A','executor':{'console':'claude'}},{'nome':'G','executor':{'console':'gemini'}}]})
        arq.write_text(json.dumps(d));ctx=self.contexto(p);self.placar(ctx);return ctx
    def api(self,url,**kw):
        self.assertFalse(kw.get('metodo'))
        if '/files?' in url:return [{'filename':'teste.py','status':'modified','patch':'@@ -1 +1 @@\n-antigo\n+novo','additions':1,'deletions':1}]
        repo='/'.join(url.split('/')[1:3]);return {'number':42,'state':'open','html_url':f'https://github.com/{repo}/pull/42',
            'base':{'repo':{'full_name':repo}},'head':{'sha':'a'*40},'changed_files':1}
    def chamar(self,rota,prompt):return {'veredito':'legitimo','motivo':'Cobertura preservada','evidencia':''}
    def test_revisores_independentes_persistidos_sem_conferir_ou_issue(self):
        ctx=self.habilitar();prompts=[]
        def chamar(rota,prompt):prompts.append(prompt);return self.chamar(rota,prompt)
        r=au.auditar(self.a,self.base,self.api,chamar);self.assertEqual(len(r),1)
        self.assertEqual(r[0]['estado'],'concluido');self.assertEqual(r[0]['veredito'],'legitimo')
        self.assertEqual(len(r[0]['pareceres']),2);self.assertEqual(prompts[0],prompts[1])
        self.assertNotIn('Cobertura preservada',prompts[1]);self.assertEqual(ctx['decisoes'].decisoes('conferido'),set())
        with patch.object(auditor_xp,'abrir_issue',side_effect=AssertionError('Issue legada indevida')):
            self.assertEqual(au.auditar(self.a,self.base,self.api,chamar),[])
        self.assertEqual(len(xp_projeto.vista(self.base['projetos'],self.base,ctx['id'])['auditor']['pareceres']),1)
    def test_suspeito_exige_evidencia_e_nao_resolve_amarelo(self):
        ctx=self.habilitar()
        def chamar(rota,prompt):return {'veredito':'suspeito','motivo':'Asserção removida','evidencia':'teste.py:1'}
        r=au.auditar(self.a,self.base,self.api,chamar)[0]
        self.assertEqual(r['veredito'],'suspeito');self.assertEqual(len(au.candidatos(ctx)),1)
        for texto in ('{"veredito":"legitimo","veredito":"suspeito"}',json.dumps({'veredito':'suspeito','motivo':'M','evidencia':''})):
            with self.assertRaises(ValueError):au.normalizar(texto)
    def test_falha_conta_tentativa_antes_e_maximo_duas(self):
        ctx=self.habilitar()
        def falhar(*args):
            self.assertEqual(next(iter(au.ler(ctx).values()))['estado'],'consultando')
            raise RuntimeError('cloud indisponível')
        for tentativa in (1,2):
            r=au.auditar(self.a,self.base,self.api,falhar)[0];self.assertEqual(r['tentativas'],tentativa);self.assertEqual(r['estado'],'falhou')
        self.assertEqual(au.auditar(self.a,self.base,self.api,falhar),[])
    def test_sha_mudou_durante_consulta(self):
        self.habilitar();mudou=False
        def api(url,**kw):
            d=self.api(url,**kw)
            if mudou and isinstance(d,dict):d['head']['sha']='b'*40
            return d
        def chamar(*args):
            nonlocal mudou
            mudou=True;return self.chamar(*args)
        r=au.auditar(self.a,self.base,api,chamar)[0];self.assertEqual(r['estado'],'falhou')
    def test_diff_omitido_ou_truncado_nao_chama_modelo(self):
        self.habilitar()
        for erro in ('patch','contagem','arquivos'):
            def api(url,**kw):
                d=self.api(url,**kw)
                if isinstance(d,list):
                    if erro=='patch':d[0].pop('patch')
                    elif erro=='contagem':d[0]['additions']=2
                    else:d=[]
                return d
            with patch('revisores_console.chamar') as chamar:
                with self.assertRaises(ValueError):au.auditar(self.a,self.base,api=api)
                chamar.assert_not_called()
    def test_mesmo_pr_outro_projeto_nao_reusa_parecer(self):
        a=self.habilitar();b=self.habilitar(self.b)
        self.assertEqual(len(au.auditar(self.a,self.base,self.api,self.chamar)),1)
        self.assertEqual(au.resumo(b)['pareceres'],[])
        self.assertEqual(len(au.auditar(self.b,self.base,self.api,self.chamar)),1)
        self.assertNotEqual(au.caminho(a),au.caminho(b))
    def test_politica_mudou_nao_grava_conclusao(self):
        ctx=self.habilitar()
        def chamar(*args):
            arq=self.a/'.office/projeto.json';arq.write_bytes(arq.read_bytes()+b' ')
            return self.chamar(*args)
        with self.assertRaises(ValueError):au.auditar(self.a,self.base,self.api,chamar)
        self.assertEqual(next(iter(au.ler(ctx).values()))['estado'],'consultando')
    def test_schema_local_optin_e_legacy_cli_bloqueado(self):
        for d in ({'auditor':{'ativo':True}},{'auditor':{'max_prs':0}},{'auditor':{'max_diff':True}}):
            with self.assertRaises(ValueError):gestao_projeto.validar(d)
        with patch.object(configuracao,'carregar',return_value=self.base),patch.object(sys,'argv',['auditor_xp.py']),patch.object(auditor_xp,'auditar') as legado:
            self.assertEqual(auditor_xp.main(),2);legado.assert_not_called()
    def test_previa_somente_leitura_e_optout_sem_modelo(self):
        ctx=self.habilitar()
        with patch.object(configuracao,'carregar',return_value=self.base),patch.object(sys,'argv',['auditor_xp.py','--projeto',str(self.a),'--seco']),patch.object(au,'auditar') as chamada:
            self.assertEqual(auditor_xp.main(),0);chamada.assert_not_called()
        self.assertFalse(au.caminho(ctx).exists())
        arq=self.a/'.office/projeto.json';d=json.loads(arq.read_text());d['auditor']['ativo']=False;arq.write_text(json.dumps(d))
        self.assertEqual(au.auditar(self.a,self.base,lambda *a:(_ for _ in ()).throw(AssertionError('API indevida'))),[])
    def test_adapter_nativo_coletor_auditor_sem_custo_presumido(self):
        import banco,revisores_console
        from consumo_providers import Registro
        self.habilitar()
        def chamar(rota,prompt,normalizador,ao_evento):
            if rota['console']=='claude':
                ao_evento({'type':'system','subtype':'init','tools':[],'session_id':'nova'})
                ao_evento({'type':'result','session_id':'nova','is_error':False,'modelUsage':{'informado':{
                    'inputTokens':10,'cacheReadInputTokens':2,'cacheCreationInputTokens':1,'outputTokens':3}}})
            return normalizador(json.dumps(self.chamar(rota,prompt)))
        with patch.object(banco,'ARQ',self.raiz/'app'/'dados'/'office.db'),patch.object(revisores_console,'chamar',side_effect=chamar):
            self.assertEqual(au.auditar(self.a,self.base,self.api)[0]['estado'],'concluido')
        d=Registro(self.raiz/'app'/'dados'/'consumo_providers.db').resumo()
        self.assertEqual(d['grupos'][0]['agente'],'Auditor');self.assertEqual(d['grupos'][0]['total'],16)
        self.assertIsNone(d['cobranca_usd'])
    def test_worker_audita_sem_bots_e_nao_usa_global(self):
        import servidor
        self.habilitar()
        class Parar:
            terminou=False
            esperas=0
            def is_set(self):return self.terminou
            def wait(self,*a):
                self.esperas+=1
                if self.esperas>1:self.terminou=True
                return False
        with (patch.object(servidor,'cfg',return_value=self.base),patch.object(au,'auditar',return_value=[]) as chamada,
             patch.object(auditor_xp,'auditar',side_effect=AssertionError('Auditor global'))):
            servidor.sugestoes_laco(Parar());chamada.assert_called_once_with(self.a,self.base)

if __name__=='__main__':unittest.main()
