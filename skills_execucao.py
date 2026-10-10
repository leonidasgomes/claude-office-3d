"""Evidência de chamada Skill no stream principal; não atesta efeitos de hooks."""
import hashlib
from pathlib import Path


def conferir_worktree(trabalho, referencias):
    raiz=Path(trabalho).resolve()
    for ref in referencias:
        if ref.get('ativacao_nativa')!='Skill': continue
        arquivo=raiz/'.claude/skills'/ref['nome']/'SKILL.md'
        if not arquivo.resolve().is_relative_to(raiz) or not arquivo.is_file():
            raise ValueError('Skill Claude nativa ausente ou fora do worktree: '+ref['nome'])
        with arquivo.open('rb') as f: dados=f.read(8*1024*1024+1)
        if len(dados)>8*1024*1024 or hashlib.sha256(dados).hexdigest()!=ref['sha256']:
            raise ValueError('Skill Claude no worktree diverge do snapshot: '+ref['nome'])


class EvidenciaClaude:
    def __init__(self, nomes, sessao):
        if (not isinstance(nomes,list) or not nomes or len(nomes)>200
                or any(not isinstance(n,str) or not n or len(n)>200 for n in nomes)):
            raise ValueError('Seleção de skills nativas inválida')
        self.nomes=set(nomes)
        self.sessao=sessao
        self.init=False
        self.fim=False
        self.invalida=False
        self.chamadas={}
        self.resultados={}

    def consumir(self, registro):
        if not isinstance(registro,dict) or registro.get('parent_tool_use_id'): return
        if registro.get('session_id') != self.sessao: return
        tipo=registro.get('type')
        if tipo=='system' and registro.get('subtype')=='init':
            self.init=isinstance(registro.get('tools'),list) and 'Skill' in registro['tools']
            return
        if not self.init or self.fim: return
        if tipo=='result':
            self.fim=registro.get('is_error') is False
            if not self.fim: self.invalida=True
            return
        conteudo=(registro.get('message') or {}).get('content') if isinstance(registro.get('message'),dict) else None
        if not isinstance(conteudo,list): return
        for bloco in conteudo:
            if not isinstance(bloco,dict): continue
            if tipo=='assistant' and bloco.get('type')=='tool_use' and bloco.get('name')=='Skill':
                entrada=bloco.get('input')
                nome=entrada.get('skill') if isinstance(entrada,dict) else None
                ident=bloco.get('id')
                if not isinstance(nome,str) or nome not in self.nomes: continue
                if not isinstance(ident,str) or not ident or len(ident)>256 or len(self.chamadas)>=1024:
                    self.invalida=True; continue
                if ident in self.chamadas and self.chamadas[ident]!=nome:
                    self.invalida=True; continue
                self.chamadas[ident]=nome
            elif tipo=='user' and bloco.get('type')=='tool_result':
                ident=bloco.get('tool_use_id')
                if not isinstance(ident,str) or ident not in self.chamadas: continue
                erro=bloco.get('is_error',False)
                ok=type(erro) is bool and not erro
                if ident in self.resultados and self.resultados[ident]!=ok: self.invalida=True
                self.resultados[ident]=ok

    def resumo(self):
        confirmadas=sorted({nome for ident,nome in self.chamadas.items() if self.resultados.get(ident) is True})
        pendentes=sorted(self.nomes-set(confirmadas))
        return {'console':'claude','sessao':self.sessao,'solicitadas':sorted(self.nomes),
                'confirmadas':confirmadas,'pendentes':pendentes,
                'valida':self.init and self.fim and not self.invalida and not pendentes}
