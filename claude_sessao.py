"""Observação passiva da sessão Claude por metadados novos do worktree exato.

Não altera flags, hooks, configuração ou transcritos. Histórico anterior e
subagentes não identificam uma execução nova; duas sessões são ambiguidade.
"""
from datetime import datetime
import json
import os
from pathlib import Path
import re
import time
import uuid


class Observador:
    def __init__(self, projeto, config=None, inicio=None, sessao=None, prompt=None):
        self.projeto=Path(projeto).resolve()
        base=Path(config or os.environ.get('CLAUDE_CONFIG_DIR') or Path.home()/'.claude')
        self.pasta=base/'projects'/re.sub(r'[^A-Za-z0-9]','-',str(self.projeto))
        self.inicio=time.time() if inicio is None else inicio
        self.posicoes={p:p.stat().st_size for p in self.pasta.glob('*.jsonl') if p.is_file()}
        self.anteriores=set(self.posicoes)
        self.esperada=sessao
        self.prompt=prompt
        self.identidades=set()

    def consultar(self):
        for arquivo in sorted(self.pasta.glob('*.jsonl')):
            if not arquivo.is_file() or arquivo.is_symlink(): continue
            if self.esperada:
                if arquivo.stem!=self.esperada: continue
            elif arquivo in self.anteriores:
                continue
            posicao=self.posicoes.get(arquivo,0)
            # Rotação/truncamento não torna o histórico uma sessão recém-iniciada.
            if arquivo.stat().st_size<posicao: continue
            with arquivo.open('rb') as fluxo:
                fluxo.seek(posicao)
                for _ in range(100):
                    linha=fluxo.readline(2*1024*1024+1)
                    if not linha or not linha.endswith(b'\n'): break
                    self.posicoes[arquivo]=fluxo.tell()
                    try:
                        d=json.loads(linha)
                        if (not isinstance(d,dict) or d.get('type') not in ('user','assistant')
                            or d.get('isSidechain') is not False or d.get('agentId')
                            or not isinstance(d.get('cwd'),str)
                            or Path(d['cwd']).resolve()!=self.projeto): continue
                        if self.prompt is not None:
                            if d.get('type')!='user' or d.get('isMeta'): continue
                            conteudo=(d.get('message') or {}).get('content')
                            if isinstance(conteudo,list):
                                conteudo=''.join(x.get('text','') for x in conteudo
                                                if isinstance(x,dict) and x.get('type')=='text')
                            if conteudo!=self.prompt: continue
                        ts=datetime.fromisoformat(d['timestamp'].replace('Z','+00:00'))
                        if ts.tzinfo is None or ts.timestamp()<self.inicio: continue
                        ident=d['sessionId']
                        if not isinstance(ident,str) or str(uuid.UUID(ident))!=ident or arquivo.stem!=ident: continue
                    except (ValueError,TypeError,KeyError,AttributeError):
                        continue
                    self.identidades.add(ident)
        if len(self.identidades)>1:
            raise ValueError('Mais de uma sessão Claude nova no worktree; concilie antes de vincular')
        return next(iter(self.identidades),None)
