"""Snapshots Claude novos; consultas isoladas conservam a exigência sem ferramentas."""
import hashlib
from consumo_providers import Coletor,contador


class ColetorIsolado:
    def __init__(self,arquivo,executor,projeto,papel):
        if papel not in ('ceo','diretor','triagem','auditor') or executor.get('execucao','cloud')!='cloud':
            raise ValueError('Coletor exige papel cloud')
        self.coletor=Coletor(arquivo,executor['console'],projeto,{'ceo':'CEO','diretor':'Diretor','triagem':'Triagem','auditor':'Auditor'}[papel],executor.get('modelo'))
        self.snapshot=SnapshotClaude(self.coletor,isolado=True) if executor['console']=='claude' else None

    def consumir(self,ev):
        if self.snapshot:return self.snapshot.consumir(ev)
        if isinstance(ev,dict) and ev.get('parent_tool_use_id') is None:return self.coletor.consumir(ev)


class SnapshotClaude:
    """Agregado principal: isolado novo ou incrementos do saldo do launcher."""
    def __init__(self,coletor,isolado=False,sessao_esperada=None,novo=True):
        self.coletor=coletor;self.isolado=isolado;self.esperada=sessao_esperada
        self.novo=novo
        self.sessao=None;self.invalida=False;self.ultimos={}

    def consumir(self,ev):
        if not isinstance(ev,dict) or ev.get('parent_tool_use_id') is not None:return
        c=self.coletor
        if ev.get('type')=='system' and ev.get('subtype')=='init':
            ident=ev.get('session_id')
            if ((self.isolado and ev.get('tools')!=[]) or not isinstance(ident,str) or not ident or len(ident)>256
                or (self.esperada is not None and ident!=self.esperada)
                or (self.sessao is not None and self.sessao!=ident)):
                self.invalida=True;return
            self.sessao=ident;return
        if (self.invalida or not self.sessao or ev.get('session_id')!=self.sessao
            or ev.get('type')!='result' or type(ev.get('is_error')) is not bool):return
        modelos=ev.get('modelUsage')
        if not isinstance(modelos,dict) or len(modelos)>20:return
        for modelo,uso in modelos.items():
            if not isinstance(modelo,str) or not 1<=len(modelo)<=200 or not isinstance(uso,dict):continue
            valores=[contador(uso.get(k)) for k in ('inputTokens','cacheReadInputTokens','cacheCreationInputTokens','outputTokens')]
            if any(v is None for v in valores):continue
            entrada,cache,criacao,saida=valores
            entrada=contador(entrada+cache+criacao)
            total=contador(entrada+saida) if entrada is not None else None
            if entrada is None or total is None:continue
            if ev.get('is_error') is True and total==0:continue
            anterior=self.ultimos.get(modelo)
            if anterior and any(v<a for v,a in zip(valores,anterior)):continue
            if not self.isolado:
                c.registro.cumulativo_claude(c.projeto,self.sessao,modelo,c.agente,c.execucao,valores,self.novo)
                self.ultimos[modelo]=valores
                continue
            chave=hashlib.sha256(f'claude-isolado|{c.execucao}|{self.sessao}|{modelo}'.encode()).hexdigest()
            fonte='claude.result/modelUsage.sessao-nova'
            c.registro.gravar(chave,'claude',modelo,'informado',c.agente,c.projeto,self.sessao,
                fonte,{'entrada':entrada,'cache':cache,'saida':saida,'total':total})
            self.ultimos[modelo]=valores
