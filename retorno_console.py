"""Conclusão do fluxo principal; não aprova código nem comprova processos filhos."""


class Retorno:
    def __init__(self,console):
        if console not in ('claude','codex','opencode','gemini'):raise ValueError('Console sem contrato de retorno')
        self.console=console;self.sessao=None;self.mensagem=None
        self.ativo=False;self.terminou=False;self.falhou=False

    @staticmethod
    def ident(valor):
        return isinstance(valor,str) and 1<=len(valor)<=256

    def vincular(self,ident):
        if not self.ident(ident) or (self.sessao is not None and self.sessao!=ident):
            self.falhou=True;return
        self.sessao=ident

    def consumir(self,ev):
        if not isinstance(ev,dict):return
        tipo=ev.get('type')
        if self.console=='claude':
            # Filhos não concluem nem invalidam por conta própria o fluxo do pai.
            if ev.get('parent_tool_use_id') is not None:
                if not self.ident(ev['parent_tool_use_id']):self.falhou=True
                return
            if tipo=='system' and ev.get('subtype')=='init':
                self.vincular(ev.get('session_id'));self.ativo=True;self.terminou=False;return
            if tipo=='error':self.falhou=True;return
            if tipo not in ('assistant','user','stream_event','result'):return
            if not self.sessao or ev.get('session_id')!=self.sessao:
                self.falhou=True;return
            if tipo=='result':
                if ev.get('is_error') is not False or ev.get('subtype')!='success':self.falhou=True
                self.ativo=False;self.terminou=True
            else:
                # Trabalho background pode iniciar outro turno após um resultado.
                self.ativo=True;self.terminou=False
        elif self.console=='codex':
            if tipo in ('error','turn.failed'):self.falhou=True;return
            if tipo not in ('thread.started','turn.started','turn.completed','item.started','item.updated','item.completed'):return
            if self.terminou:self.falhou=True;return
            if tipo=='thread.started':self.vincular(ev.get('thread_id'));return
            if not self.sessao:self.falhou=True;return
            if tipo=='turn.started':
                if self.ativo:self.falhou=True
                self.ativo=True
            elif tipo=='turn.completed':
                if not self.ativo:self.falhou=True
                self.ativo=False;self.terminou=True
            elif not self.ativo:self.falhou=True
        elif self.console=='gemini':
            if tipo=='error':self.falhou=True;return
            if tipo not in ('init','message','tool_use','tool_result','result'):return
            if self.terminou:self.falhou=True;return
            if tipo=='init':
                self.vincular(ev.get('session_id'))
                if not self.ident(ev.get('model')):self.falhou=True
                self.ativo=True;return
            if not self.sessao or (ev.get('session_id') is not None and ev['session_id']!=self.sessao):
                self.falhou=True;return
            if tipo=='result':
                if ev.get('status')!='success' or ev.get('error') is not None:self.falhou=True
                self.ativo=False;self.terminou=True
        else:
            if tipo=='error':self.falhou=True;return
            if tipo not in ('step_start','step_finish','text','reasoning','tool_use'):return
            if self.terminou:self.falhou=True;return
            part=ev.get('part')
            if not isinstance(part,dict):self.falhou=True;return
            self.vincular(ev.get('sessionID'))
            if (part.get('sessionID')!=self.sessao or not self.ident(part.get('messageID'))
                or part.get('type')!={'step_start':'step-start','step_finish':'step-finish',
                                     'tool_use':'tool'}.get(tipo,tipo)):
                self.falhou=True;return
            if tipo=='step_start':
                if self.ativo:self.falhou=True
                self.ativo=True;self.mensagem=part['messageID'];return
            if not self.ativo or part['messageID']!=self.mensagem:self.falhou=True;return
            if tipo=='step_finish':
                motivo=part.get('reason')
                if motivo not in ('stop','tool-calls'):self.falhou=True
                self.ativo=False;self.terminou=motivo=='stop'

    def sucesso(self):
        return self.sessao is not None and self.terminou and not self.ativo and not self.falhou
