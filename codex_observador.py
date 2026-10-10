"""Observação passiva de rollouts Codex: nenhuma escrita na sessão ou config do CLI."""
import json
import os
import re
from pathlib import Path


class Transcrito:
    def __init__(self, mesa, emitir, parentesco=None, consumo=None):
        self.mesa, self.emitir = mesa, emitir
        self.parentesco = parentesco or {}
        self.sessao = ""
        self.posicao = 0
        self.resto = b""
        self.pendentes = {}
        self.vistos = set()
        self.historico_ate = 0
        self.registros_lidos = 0
        self.consumo = consumo

    def medir(self, registro, base=False):
        if self.consumo:
            try:
                self.consumo.consumir(registro, base=base)
            except Exception:
                pass  # Falha de coleta nunca interrompe o feed/agente.

    def evento(self, tipo="trabalho", **dados):
        self.emitir({"tipo": tipo, "agente": self.mesa, "fonte": "codex", "sessao": self.sessao,
                     "para": [], **self.parentesco, **dados})

    def consumir(self, registro):
        self.medir(registro)
        payload = registro.get("payload") or {}
        if not isinstance(payload, dict):
            return
        tipo = registro.get("type")
        if tipo == "session_meta":
            if not self.sessao:
                self.sessao = str(payload.get("id") or payload.get("session_id") or "")
            return
        if tipo == "event_msg":
            if payload.get("type") in ("task_complete", "task_completed", "turn_aborted"):
                self.evento("ocioso", resumo="aguardando")
            return
        if tipo != "response_item":
            return
        item = payload.get("type")
        if item == "message" and payload.get("role") == "assistant":
            texto = "\n".join(str(c.get("text") or "") for c in payload.get("content") or []
                              if isinstance(c, dict) and c.get("type") in ("output_text", "text"))
            if texto:
                self.evento("fala", ferramenta="Mensagem", resumo=texto, texto=texto)
            return
        chave = payload.get("call_id")
        if not chave:
            return
        if item in ("function_call", "custom_tool_call"):
            if ("inicio", chave) in self.vistos:
                return
            self.vistos.add(("inicio", chave))
            ferramenta = str(payload.get("name") or "Ferramenta")
            entrada = payload.get("arguments") or payload.get("input") or ""
            try:
                dados = json.loads(entrada) if isinstance(entrada, str) else entrada
            except ValueError:
                dados = {}
            resumo = (dados.get("cmd") or dados.get("command") or dados.get("file_path") or ferramenta) if isinstance(dados, dict) else ferramenta
            self.pendentes[chave] = (ferramenta, resumo)
            ev = {"ferramenta": ferramenta, "resumo": resumo, "detalhe": str(entrada)[:400],
                  "inicio": True, "espera_s": 120}
            if ferramenta.split(".")[-1] in ("spawn_agent", "send_input", "send_message"):
                ev["tipo"] = "subagente" if ferramenta.endswith("spawn_agent") else "fala"
                if isinstance(dados, dict):
                    alvo = dados.get("id") or dados.get("target") or dados.get("agent_id")
                    if alvo:
                        ev["para"] = [str(alvo)]
                    ev["texto"] = str(dados.get("message") or dados.get("prompt") or "")
            self.evento(**ev)
        elif item in ("function_call_output", "custom_tool_call_output"):
            if ("fim", chave) in self.vistos or chave not in self.pendentes:
                return
            self.vistos.add(("fim", chave))
            ferramenta, resumo = self.pendentes.pop(chave)
            saida = payload.get("output") or ""
            resultado = {}
            if isinstance(saida, str):
                # Só afirma resultado com código explícito; textos livres não provam sucesso.
                match = re.search(r"(?:Process exited with code|Exit code:|exit_code[\"']?\s*:)\s*(-?\d+)", saida)
                if match:
                    codigo = int(match.group(1))
                    resultado.update(ok=codigo == 0, codigo=codigo)
            self.evento(ferramenta=ferramenta, resumo=resumo, **resultado)

    def ler(self, caminho):
        try:
            if caminho.stat().st_size < self.posicao:
                self.posicao, self.resto = 0, b""
            with caminho.open("rb") as f:
                f.seek(self.posicao)
                trecho = f.read(1024 * 1024)
                self.posicao = f.tell()
            self.resto += trecho
            while b"\n" in self.resto:
                linha, self.resto = self.resto.split(b"\n", 1)
                self.registros_lidos += 1
                try:
                    registro = json.loads(linha)
                    if self.registros_lidos <= self.historico_ate:
                        self.medir(registro, base=True)
                    else:
                        self.consumir(registro)
                except (ValueError, TypeError, AttributeError):
                    pass
            if len(self.resto) > 4 * 1024 * 1024:
                self.resto = b""  # linha corrompida não cresce sem limite
        except OSError:
            pass


def metadados(caminho):
    try:
        with caminho.open("rb") as f:
            registro = json.loads(f.readline(256 * 1024))
        return registro.get("payload", {}) if registro.get("type") == "session_meta" else {}
    except (OSError, ValueError):
        return {}


def base_consumo(transcrito, caminho, ate):
    """Só contadores/contexto do trecho já existente, sem republicar trabalho antigo.

    Se a cauda não contiver um saldo válido, o primeiro saldo futuro vira baseline.
    Não lê mais de 16 MB nem aceita linhas maiores que 4 MB.
    """
    if not transcrito.consumo:
        return
    with caminho.open('rb') as f:
        inicio = max(0, ate - 16*1024*1024)
        f.seek(inicio)
        if inicio:
            f.readline(4*1024*1024)
        while f.tell() < ate:
            linha = f.readline(min(4*1024*1024, ate-f.tell()))
            if not linha:
                break
            if not linha.endswith(b'\n'):
                continue
            try:
                registro = json.loads(linha)
                if registro.get('type') in ('turn_context', 'event_msg'):
                    transcrito.medir(registro, base=True)
            except (ValueError, AttributeError):
                pass


class Observador:
    """Seleciona sessão exata no resume; sessão nova somente se a descoberta for única."""
    def __init__(self, projeto, mesa, emitir, sessao=None, home=None, avisar=lambda s: None,
                 observar_principal=True, criar_consumo=None):
        self.projeto = Path(projeto).resolve()
        self.home = Path(home or os.environ.get("CODEX_HOME") or Path.home() / ".codex")
        self.sessao, self.avisar = sessao, avisar
        self.observar_principal = observar_principal
        self.criar_consumo = criar_consumo
        self.anteriores = set(self.arquivos())
        self.caminho = None
        self.transcrito = Transcrito(mesa, emitir)
        self.descendentes = {}
        self.avisou = False
        if sessao:
            candidatos = [f for f in self.anteriores if metadados(f).get("id") == sessao
                          and Path(metadados(f).get("cwd") or "").resolve() == self.projeto]
            if len(candidatos) == 1:
                self.anexar(candidatos[0], historico=False)

    def arquivos(self):
        return (self.home / "sessions").glob("*/*/*/rollout-*.jsonl")

    def anexar(self, caminho, historico=True):
        self.caminho = caminho
        self.transcrito.sessao = str(metadados(caminho).get("id") or "")
        if self.criar_consumo and self.observar_principal:
            self.transcrito.consumo = self.criar_consumo(self.transcrito.mesa, self.transcrito.sessao, historico)
        if not historico:
            self.transcrito.posicao = caminho.stat().st_size
            base_consumo(self.transcrito, caminho, self.transcrito.posicao)

    def tick(self):
        if not self.observar_principal and not self.sessao:
            return  # exec --json entrega a identidade exata em thread.started
        if self.caminho is None:
            candidatos = []
            for caminho in self.arquivos():
                if not self.sessao and caminho in self.anteriores:
                    continue
                meta = metadados(caminho)
                if self.sessao and meta.get("id") != self.sessao:
                    continue
                if not meta.get("cwd") or Path(meta["cwd"]).resolve() != self.projeto:
                    continue
                # Não anexa subagente como sessão principal.
                if isinstance(meta.get("source"), dict):
                    continue
                candidatos.append(caminho)
            if len(candidatos) == 1:
                self.anexar(candidatos[0])
            elif len(candidatos) > 1 and not self.avisou:
                self.avisar("Sessões Codex simultâneas: informe --sessao para observar uma identidade exata.")
                self.avisou = True
        if self.caminho is not None:
            if self.observar_principal:
                self.transcrito.ler(self.caminho)
            self.ler_descendentes()

    def ler_descendentes(self):
        """Associa filhos pela ancestralidade nativa, inclusive em worktrees diferentes."""
        conhecidos = {self.transcrito.sessao: self.transcrito}
        conhecidos.update({t.sessao: t for t in self.descendentes.values()})
        candidatos = []
        for caminho in self.arquivos():
            if caminho == self.caminho or caminho in self.descendentes:
                continue
            meta = metadados(caminho)
            source = meta.get("source")
            sub = source.get("subagent", {}) if isinstance(source, dict) else {}
            spawn = sub.get("thread_spawn", {}) if isinstance(sub, dict) else {}
            if isinstance(spawn, dict) and spawn.get("parent_thread_id") and meta.get("id"):
                candidatos.append((caminho, meta, spawn))
        # Filhos podem aparecer antes do pai na listagem do sistema de arquivos.
        while candidatos:
            restantes = []
            for caminho, meta, spawn in candidatos:
                pai = conhecidos.get(spawn["parent_thread_id"])
                if pai is None:
                    restantes.append((caminho, meta, spawn))
                    continue
                ident = str(meta["id"])
                apelido = str(spawn.get("agent_nickname") or "Agente")
                apelido = re.sub(r"[^\w-]", "_", apelido)[:40]
                mesa = f"Codex_{apelido}_s{ident.replace('-', '')[-12:]}"
                filho = Transcrito(mesa, self.transcrito.emitir, {
                    "sessao_pai": pai.sessao, "agente_pai": pai.mesa,
                    "funcao": str(spawn.get("agent_role") or spawn.get("agent_path") or "Subagente Codex")})
                filho.sessao = ident
                if self.criar_consumo:
                    filho.consumo = self.criar_consumo(mesa, ident, caminho not in self.anteriores)
                ordinal = meta.get("subagent_history_start_ordinal")
                if type(ordinal) is int and ordinal >= 0 and caminho not in self.anteriores:
                    filho.historico_ate = ordinal
                if caminho in self.anteriores:
                    filho.posicao = caminho.stat().st_size
                    base_consumo(filho, caminho, filho.posicao)
                self.descendentes[caminho] = filho
                conhecidos[ident] = filho
                if caminho not in self.anteriores:
                    pai.evento("subagente", para=[mesa], sessao_filho=ident,
                               funcao=filho.parentesco["funcao"], resumo="delegação Codex")
            if len(restantes) == len(candidatos):
                break
            candidatos = restantes
        for caminho, transcrito in self.descendentes.items():
            transcrito.ler(caminho)

    def acompanhar(self, parar):
        while not parar.is_set():
            try:
                self.tick()
            except Exception:
                pass  # observar nunca interrompe o agente
            parar.wait(0.3)
        self.tick()
