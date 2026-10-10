"""Adapters isolados e falhas fechadas; nenhum modelo é chamado pelos testes."""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import revisores_console as rc

RESPOSTA = {'veredito':'aprovado','achados':[]}


def evento_opencode(tipo,ident,**dados):
    return {'type':tipo,'sessionID':'nova','part':{'id':ident,'sessionID':'nova','messageID':'mensagem',
        'type':{'step_start':'step-start','step_finish':'step-finish'}.get(tipo,tipo),**dados}}


class Revisores(unittest.TestCase):
    def test_opencode_erro_json_classificado_sem_expor_corpo(self):
        args=['opencode','run','--pure','--format','json']
        for status,mensagem,nome,motivo in [
            (429,'SEGREDO','APIError','limite_ou_credito'),
            (401,'SEGREDO','APIError','autenticacao_indisponivel'),
            (403,'Access denied SEGREDO','APIError','console_falhou'),
            (None,'Invalid token SEGREDO','ProviderAuthError','autenticacao_indisponivel'),
            (403,'insufficient_credit SEGREDO','APIError','limite_ou_credito')]:
            fluxo=json.dumps({'type':'error','error':{'name':nome,'data':{
                'statusCode':status,'message':mensagem,'responseHeaders':{'secret':'SEGREDO'},
                'responseBody':'SEGREDO','metadata':{'reason':'quota'}}}})
            for codigo in (0,7):
                with self.subTest(status=status,codigo=codigo),patch.object(rc.subprocess,'run',
                        return_value=SimpleNamespace(returncode=codigo,stdout=fluxo,stderr='')):
                    recebidos=[]
                    with self.assertRaises(rc.FalhaRevisor) as falha:
                        rc.rodar(args,Path('.'),{},ao_saida=recebidos.append)
                    self.assertEqual((falha.exception.motivo,falha.exception.codigo),(motivo,codigo or 1))
                    self.assertNotIn('SEGREDO',str(falha.exception))
                    self.assertEqual(recebidos,[fluxo])

    def test_diagnostico_nao_classifica_texto_metadata_ou_outros_consoles(self):
        erro=lambda status:json.dumps({'type':'error','error':{'name':'APIError','data':{'statusCode':status}}})
        for fluxo in ('quota 429',json.dumps({'type':'text','part':{'text':'quota 429'}}),
                      '{"type":"error","type":"text","error":{"data":{"statusCode":429}}}',
                      '[]','{'):
            with self.subTest(fluxo=fluxo):self.assertIsNone(rc.motivo_opencode(fluxo))
        self.assertEqual(rc.motivo_opencode(erro(429)+'\n'+erro(401)),'console_falhou')
        fluxo=json.dumps({'type':'error','error':{'name':'APIError','data':{
            'statusCode':403,'metadata':{'error':'quota 429'},'responseBody':'invalid_api_key'}}})
        self.assertEqual(rc.motivo_opencode(fluxo),'console_falhou')
        for status in (True,'429',429.0):
            self.assertEqual(rc.motivo_opencode(erro(status)),'console_falhou')
        with patch.object(rc.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=erro(429),stderr='')):
            self.assertEqual(rc.rodar(['codex','exec','--json'],Path('.'),{}),erro(429))

    def test_subprocesso_real_ajuda_em_stderr(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'cli.py';p.write_text('import sys\nprint("--pure --format --agent",file=sys.stderr)\n',encoding='utf-8')
            rc.verificar_flags([sys.executable,str(p)],Path(tmp),{},['--pure','--format','--agent'])
            self.assertEqual(rc.rodar([sys.executable,str(p)],Path(tmp),{}),'')
    def test_ajuda_stderr_exit_zero_sem_misturar_inferencia(self):
        r=SimpleNamespace(returncode=0,stdout='',stderr='--pure --format --agent')
        with patch.object(rc.subprocess,'run',return_value=r):
            rc.verificar_flags(['opencode','run'],Path('.'),{},['--pure','--format','--agent'])
            self.assertEqual(rc.rodar(['opencode','run'],Path('.'),{}),'')
        r.returncode=1
        with patch.object(rc.subprocess,'run',return_value=r):
            with self.assertRaises(RuntimeError):rc.verificar_flags(['opencode','run'],Path('.'),{},['--pure'])
    def test_quatro_consoles_contextos_novos_controles_nativos(self):
        pastas=[]; chamadas=[]
        for nome in ('claude','codex','gemini','opencode'):
            def rodar(args, pasta, env, entrada=None, timeout=600):
                chamadas.append((nome,args,entrada)); pastas.append(str(pasta))
                self.assertNotIn('--resume',args); self.assertNotIn('--session',args)
                if '--help' in args:
                    return '--safe-mode --verbose --tools --strict-mcp-config --no-session-persistence --ignore-user-config --ignore-rules --sandbox --ephemeral --admin-policy --extensions --output-format --pure --format --agent'
                if 'debug' in args:
                    cfg=json.loads(env['OPENCODE_CONFIG_CONTENT'])
                    return json.dumps({'permission':{'*':'deny'},'agent':cfg['agent'],'mcp':cfg.get('mcp',{})})
                self.assertEqual(entrada,'Diff e regras')
                if nome=='claude':
                    self.assertEqual(args[args.index('--tools')+1],'')
                    self.assertIn('--safe-mode',args);self.assertNotIn('--bare',args)
                    return '\n'.join(json.dumps(ev) for ev in [
                        {'type':'system','subtype':'init','session_id':'review','tools':[]},
                        {'type':'result','session_id':'review','is_error':False,'result':json.dumps(RESPOSTA)}])
                if nome=='codex':
                    self.assertEqual(args[args.index('--sandbox')+1],'read-only')
                    self.assertIn('hooks',args); self.assertIn('apps',args)
                    return '\n'.join(json.dumps(e) for e in [{'type':'thread.started','thread_id':'review'},
                        {'type':'turn.started'},{'type':'item.completed','item':{'id':'msg','type':'agent_message','text':json.dumps(RESPOSTA)}},{'type':'turn.completed'}])
                if nome=='gemini':
                    self.assertIn('decision = "deny"',Path(args[args.index('--admin-policy')+1]).read_text())
                    self.assertFalse(json.loads(Path(env['GEMINI_CLI_SYSTEM_SETTINGS_PATH']).read_text())['admin']['mcp']['enabled'])
                    self.assertFalse(json.loads(Path(env['GEMINI_CLI_SYSTEM_SETTINGS_PATH']).read_text())['hooksConfig']['enabled'])
                    self.assertTrue(json.loads(Path(env['GEMINI_CLI_SYSTEM_SETTINGS_PATH']).read_text())['context']['fileName'].startswith('review-context-'))
                    self.assertFalse(json.loads(Path(env['GEMINI_CLI_SYSTEM_SETTINGS_PATH']).read_text())['security']['folderTrust']['enabled'])
                    self.assertNotIn('GEMINI_SYSTEM_MD',env);self.assertNotIn('GEMINI_APPEND_SYSTEM_MD',env)
                    return '\n'.join(json.dumps(e) for e in [{'type':'init','session_id':'nova','model':'gemini'},
                        {'type':'message','role':'assistant','content':json.dumps(RESPOSTA)},{'type':'result','status':'success'}])
                self.assertEqual(json.loads(env['OPENCODE_CONFIG_CONTENT'])['permission'],'deny')
                return '\n'.join(json.dumps(e) for e in [evento_opencode('step_start','inicio'),
                    evento_opencode('text','texto',text=json.dumps(RESPOSTA)),evento_opencode('step_finish','fim',reason='stop')])
            with patch.object(rc,'selecionar',return_value=(SimpleNamespace(nome=nome),'native')), patch.object(rc,'rodar',side_effect=rodar):
                self.assertEqual(rc.chamar({'console':nome},'Diff e regras'),RESPOSTA)
        self.assertEqual(len(set(pastas)),4)
        self.assertTrue(all(not Path(p).exists() for p in pastas))

    def test_codex_exige_sessao_turno_itens_completos_sem_ferramentas(self):
        init={'type':'thread.started','thread_id':'review'};inicio={'type':'turn.started'}
        msg={'type':'item.completed','item':{'id':'msg','type':'agent_message','text':json.dumps(RESPOSTA)}}
        fim={'type':'turn.completed'}
        fluxo=lambda evs:'\n'.join(json.dumps(e) for e in evs)
        bom=[init,inicio,msg,fim]
        self.assertEqual(rc.resposta_codex(fluxo(bom)),json.dumps(RESPOSTA))
        rac={'type':'item.started','item':{'id':'r','type':'reasoning','text':'Analise'}}
        self.assertEqual(rc.resposta_codex(fluxo([init,inicio,rac,{**rac,'type':'item.completed'},msg,fim])),json.dumps(RESPOSTA))
        invalidos=[[msg,fim],[init,msg,fim],[init,inicio,msg],[init,inicio,fim],
            [init,init,inicio,msg,fim],[init,inicio,inicio,msg,fim],bom+[msg],bom+[fim],
            [init,inicio,rac,msg,fim],[init,inicio,msg,msg,fim],
            [init,inicio,{**msg,'thread_id':'outra'},fim],
            [{**init,'thread_id':''},inicio,msg,fim],[init,inicio,[],fim]]
        for tipo in ('command_execution','file_change','mcp_tool_call','collab_tool_call','web_search','plan','futuro'):
            invalidos.append([init,inicio,{'type':'item.updated','item':{'id':'tool','type':tipo}},msg,fim])
        for item in ({'id':'msg','type':'agent_message','text':[]},{'type':'agent_message','text':'ok'},
                     {'id':'msg','type':'agent_message','text':''}):
            invalidos.append([init,inicio,{**msg,'item':item},fim])
        for ev in ({'type':'error'},{'type':'turn.failed'},{'type':'futuro'}):invalidos.append([init,inicio,ev,msg,fim])
        for evs in invalidos:
            with self.subTest(evs=evs),self.assertRaises(RuntimeError):rc.resposta_codex(fluxo(evs))

    def test_ferramenta_erro_ou_versao_incompativel_nao_aprova(self):
        with patch.object(rc,'selecionar',return_value=(SimpleNamespace(nome='codex'),'native')):
            with patch.object(rc,'rodar',return_value='Ajuda antiga'):
                with self.assertRaises(ValueError): rc.chamar({'console':'codex'},'Diff')
            ajuda='--ignore-user-config --ignore-rules --sandbox --ephemeral'
            with patch.object(rc,'rodar',side_effect=[ajuda,json.dumps({'type':'item.started','item':{'type':'command_execution'}})]):
                with self.assertRaises(RuntimeError): rc.chamar({'console':'codex'},'Diff')
        with self.assertRaises(ValueError): rc.chamar({'console':'codex','execucao':'local'},'Diff')

    def test_claude_ferramenta_sessao_erro_e_resultado_ausente_nao_aprovam(self):
        ajuda='--safe-mode --verbose --tools --strict-mcp-config --no-session-persistence'
        init={'type':'system','subtype':'init','session_id':'review','tools':[]}
        result={'type':'result','session_id':'review','is_error':False,'result':json.dumps(RESPOSTA)}
        for registros in ([{**init,'tools':['Read']},result],[result],[init],
                          [init,{**result,'is_error':True}], [init,{**result,'session_id':'outro'}],
                          [init,{**result,'parent_tool_use_id':'filho'}], [init,result,result],
                          [init,{'type':'assistant','message':{'content':[{'type':'tool_use'}]}},result],
                          [init,{'type':'assistant','message':'inválida'},result]):
            with self.subTest(registros=registros),patch.object(rc,'selecionar',return_value=(SimpleNamespace(nome='claude'),'native')), \
                 patch.object(rc,'rodar',side_effect=[ajuda,'\n'.join(json.dumps(e) for e in registros)]):
                with self.assertRaises(RuntimeError):rc.chamar({'console':'claude'},'Diff')
        with patch.object(rc,'selecionar',return_value=(SimpleNamespace(nome='claude'),'native')),patch.object(rc,'rodar',return_value='--bare --tools'):
            with self.assertRaises(ValueError):rc.chamar({'console':'claude'},'Diff')

    def test_gemini_exige_init_modelo_conclusao_unica_e_sem_ferramentas(self):
        init={'type':'init','session_id':'nova','model':'gemini'}
        msg={'type':'message','role':'assistant','content':json.dumps(RESPOSTA)}
        fim={'type':'result','status':'success'}
        fluxo=lambda evs:'\n'.join(json.dumps(e) for e in evs)
        self.assertEqual(rc.resposta_gemini(fluxo([init,msg,fim])),json.dumps(RESPOSTA))
        for evs in ([msg,fim],[init,msg],[init,fim],[init,init,msg,fim],
                    [{**init,'model':None},msg,fim], [init,{**msg,'session_id':'outra'},fim],
                    [init,msg,{**fim,'status':'error'}],[init,msg,{**fim,'error':{'message':'falhou'}}],
                    [init,msg,fim,fim],[init,{'type':'tool_result'},msg,fim],
                    [init,{'type':'tool_use'},msg,fim],[init,{'type':'error'},msg,fim],
                    [init,{'type':'futuro'},msg,fim],[init,{**msg,'content':[]},fim],[init,[],fim]):
            with self.subTest(evs=evs),self.assertRaises(RuntimeError):rc.resposta_gemini(fluxo(evs))

    def test_opencode_sessao_etapa_mensagem_fim_e_texto_estritos(self):
        inicio=evento_opencode('step_start','inicio')
        texto=evento_opencode('text','texto',text=json.dumps(RESPOSTA))
        fim=evento_opencode('step_finish','fim',reason='stop')
        fluxo=lambda eventos:'\n'.join(json.dumps(e) for e in eventos)
        self.assertEqual(rc.resposta_opencode(fluxo([inicio,texto,fim])),json.dumps(RESPOSTA))
        raciocinio=evento_opencode('reasoning','raciocinio',text='Não integra o veredito')
        self.assertEqual(rc.resposta_opencode(fluxo([inicio,raciocinio,texto,fim])),json.dumps(RESPOSTA))
        casos=[[texto,fim],[inicio,texto],[inicio,fim],[inicio,texto,fim,fim],
               [inicio,texto,fim,{'type':'error'}],[inicio,inicio,texto,fim],
               [inicio,{'type':'tool_use'},fim],[inicio,{'type':'unknown'},fim],
               [inicio,[],fim],[inicio,{**texto,'sessionID':'outra'},fim],
               [inicio,{**texto,'part':{**texto['part'],'sessionID':'outra'}},fim],
               [inicio,{**texto,'part':{**texto['part'],'messageID':'outra'}},fim],
               [inicio,{**texto,'part':{**texto['part'],'type':'tool'}},fim],
               [inicio,{**texto,'part':{**texto['part'],'text':None}},fim],
               [inicio,{**texto,'part':{**texto['part'],'id':'inicio'}},fim],
               [inicio,texto,{**fim,'part':{**fim['part'],'reason':'length'}}],
               [inicio,{**texto,'part':{**texto['part'],'messageID':''}},fim]]
        for eventos in casos:
            with self.subTest(eventos=eventos),self.assertRaises(RuntimeError):rc.resposta_opencode(fluxo(eventos))
        with self.assertRaises(ValueError):rc.resposta_opencode('Não é JSON')

    def test_diagnostico_enumera_falha_sem_expor_stderr_credenciais(self):
        for texto,codigo,motivo in [('IneligibleTierError UNSUPPORTED_CLIENT SEGREDO',1,'cliente_nao_suportado'),
                                   ('Workspace is not trusted SEGREDO',55,'workspace_nao_confiavel'),
                                   ('Quota error 429 SEGREDO',1,'limite_ou_credito'),
                                   ('FatalAuthenticationError SEGREDO',41,'autenticacao_indisponivel'),
                                   ('erro SEGREDO',1,'console_falhou')]:
            with self.subTest(motivo=motivo),patch.object(rc.subprocess,'run',return_value=SimpleNamespace(returncode=codigo,stdout='',stderr=texto)):
                with self.assertRaises(rc.FalhaRevisor) as falha:rc.rodar(['native'],Path('.'),{})
                self.assertEqual(falha.exception.motivo,motivo);self.assertEqual(falha.exception.codigo,codigo)
                self.assertNotIn('SEGREDO',str(falha.exception))
        with self.assertRaises(ValueError):rc.FalhaRevisor(True,'console_falhou')
        with self.assertRaises(ValueError):rc.FalhaRevisor(1,'SEGREDO')


if __name__ == '__main__': unittest.main()
