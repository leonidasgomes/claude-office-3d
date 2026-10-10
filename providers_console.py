"""Adapters da nova versão; todos os consoles usam eventos comuns."""
import importlib.util
import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path


def comando_nativo(exe, nome):
    """Evita cmd.exe nos shims npm dos novos providers (prompts são dados, não shell)."""
    caminho = Path(exe)
    if caminho.suffix.lower() not in (".cmd", ".ps1") or nome == "claude":
        return [exe]
    if nome == "opencode":
        nativo = caminho.parent / "node_modules/opencode-ai/bin/opencode.exe"
        if nativo.is_file():
            return [str(nativo)]
    if nome == "codex":
        script = caminho.parent / "node_modules/@openai/codex/bin/codex.js"
        node = shutil.which("node")
        if script.is_file() and node:
            return [node, str(script)]
    if nome == "gemini":
        script = caminho.parent / "node_modules/@google/gemini-cli/bundle/gemini.js"
        node = shutil.which("node")
        if script.is_file() and node:
            return [node, str(script)]
    raise ValueError(f"Shim {nome} sem executável nativo conhecido; instale o CLI oficial no PATH.")


@dataclass(frozen=True)
class Capacidades:
    team_nativo: bool
    eventos_json: bool
    skills_claude: bool
    retomar: bool = True


@dataclass(frozen=True)
class Provider:
    nome: str
    capacidades: Capacidades

    def comando(self, exe, projeto, prompt=None, modelo=None, sessao=None, agente=None):
        if self.nome == "gemini":
            if agente:
                raise ValueError("Gemini: selecione o papel pelas instruções de gestão, não por --agente.")
            args = comando_nativo(exe, self.nome)
            if sessao:
                args += ["--resume", sessao]
            if modelo:
                args += ["--model", modelo]
            if prompt is not None:
                args += ["--output-format", "stream-json", "--prompt", prompt]
            return args
        if self.nome == "claude":
            args = comando_nativo(exe, self.nome)
            if sessao:
                args += ["--resume", sessao]
            if agente:
                args += ["--agent", agente]
            if modelo:
                args += ["--model", modelo]
            if prompt is not None:
                # Entrada padrão evita limites e interpretação de prompts pelo shell.
                args += ["-p", "--verbose", "--output-format", "stream-json"]
            return args
        if self.nome == "codex":
            if agente:
                raise ValueError("Codex não carrega .claude/agents; use instruções no prompt.")
            args = comando_nativo(exe, self.nome)
            if prompt is not None:
                args += ["exec"]
                if sessao:
                    args += ["resume", sessao]
                args += ["--json"]
            elif sessao:
                args += ["resume", sessao]
            if modelo:
                args += ["--model", modelo]
            if prompt is not None:
                args += [prompt]
            return args
        args = comando_nativo(exe, self.nome)
        if prompt is not None:
            args += ["run", "--format", "json"]
        if sessao:
            args += ["--session", sessao]
        if agente:
            args += ["--agent", agente]
        if modelo:
            args += ["--model", modelo]
        if prompt is not None:
            args += [prompt]
        return args


PROVIDERS = {
    "claude": Provider("claude", Capacidades(True, True, True)),
    "codex": Provider("codex", Capacidades(False, True, False)),
    "opencode": Provider("opencode", Capacidades(False, True, True)),
    "gemini": Provider("gemini", Capacidades(False, True, False)),
}


def selecionar(nome=None, config=None, localizar=shutil.which):
    """Padrão Claude. Apenas auto tenta outro CLI; escolha explícita nunca muda de backend."""
    nome = nome or os.environ.get("OFFICE_PROVIDER") or (config or {}).get("provider") or "claude"
    nome = {"gpt": "codex", "gpt-console": "codex"}.get(nome, nome)
    if nome == "auto":
        for candidato in PROVIDERS:
            exe = localizar(candidato)
            if exe:
                return PROVIDERS[candidato], exe
        raise ValueError("Nenhum console encontrado no PATH (claude, codex, opencode, gemini).")
    if nome not in PROVIDERS:
        raise ValueError(f"Provider desconhecido: {nome}")
    exe = localizar(nome)
    if not exe:
        raise ValueError(f"{nome} não encontrado no PATH; nenhum outro provider será iniciado.")
    return PROVIDERS[nome], exe


def hook_claude(raiz):
    """Carrega o hook original, sem conversão de sua saída ou alterações de implementação."""
    caminho = raiz / "registrar_evento.py"
    if not caminho.is_file():
        caminho = raiz / "office one" / "registrar_evento.py"
    spec = importlib.util.spec_from_file_location("office_hook_claude", caminho)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo.evento


def sessao_nativa(provider, registro):
    """Identidade do fluxo principal em envelopes conhecidos; nunca a do filho."""
    if not isinstance(registro,dict): return None
    tipo=registro.get('type')
    if provider=='claude' and tipo=='system' and registro.get('subtype')=='init' and not registro.get('parent_tool_use_id'):
        return registro.get('session_id')
    if provider=='codex' and tipo=='thread.started': return registro.get('thread_id')
    if provider=='gemini' and tipo=='init': return registro.get('session_id')
    if provider=='opencode' and tipo in ('step_start','text','tool_use','step_finish','error','session.error'):
        return registro.get('sessionID')
    return None


class Eventos:
    """Traduz envelopes documentados dos CLIs. Tipos desconhecidos são ignorados."""
    def __init__(self, provider, mesa, claude=None):
        self.provider, self.mesa, self.claude = provider, mesa, claude
        self.sessao = ""
        self.vistos = set()
        self.ferramentas = {}

    def base(self, tipo="trabalho", **campos):
        return {"tipo": tipo, "agente": self.mesa, "fonte": self.provider,
                "para": [], "sessao": self.sessao, **campos}

    def converter(self, registro):
        if not isinstance(registro, dict):
            return []
        if self.provider == "claude":
            if self.claude is not None:
                ev = self.claude(registro)
                return [ev] if ev else []
            return self.converter_claude(registro)
        ident=sessao_nativa(self.provider,registro)
        if isinstance(ident,str) and ident:
            self.sessao=ident
        tipo = registro.get("type")
        if self.provider == "gemini":
            if tipo == "message" and registro.get("role") == "assistant":
                texto = str(registro.get("content") or "")
                return [self.base("fala", ferramenta="Mensagem", resumo=texto, texto=texto)]
            if tipo == "tool_use":
                nome = str(registro.get("tool_name") or "Ferramenta")
                self.ferramentas[str(registro.get("tool_id"))] = nome
                return [self.base(ferramenta=nome, resumo=nome, inicio=True, espera_s=120,
                                  detalhe=json.dumps(registro.get("parameters") or {}, ensure_ascii=False))]
            if tipo == "tool_result":
                ev = self.base(ferramenta=self.ferramentas.get(str(registro.get("tool_id")), "Ferramenta"),
                               resumo="resultado da ferramenta")
                if registro.get("status") in ("success", "error"):
                    ev["ok"] = registro["status"] == "success"
                if registro.get("error"):
                    ev["erro"] = str(registro["error"])
                return [ev]
            if tipo == "result":
                return [self.base("ocioso", resumo="turno encerrado")]
            if tipo == "error":
                return [self.base(ferramenta="Console", resumo="erro do console",
                                  erro=str(registro.get("message") or registro.get("error") or "erro"))]
            return []
        if tipo in ("turn.completed", "turn.failed") or (tipo == "step_finish" and (registro.get("part") or {}).get("reason") == "stop"):
            return [self.base("ocioso", resumo="aguardando")]
        if tipo in ("error", "session.error"):
            return [self.base(ferramenta="Console", resumo="erro do console", ok=False,
                              erro=str(registro.get("message") or registro.get("error") or "erro"))]
        if self.provider == "codex":
            if tipo not in ("item.started", "item.completed"):
                return []
            item = registro.get("item") or {}
            if item.get("type") == "error":
                return [self.base(ferramenta="Console", resumo="aviso do console", erro=item.get("message", ""))]
            chave = (tipo, item.get("id"))
            if item.get("id") and chave in self.vistos:
                return []
            self.vistos.add(chave)
            if item.get("type") == "agent_message" and tipo == "item.completed":
                return [self.base("fala", ferramenta="Mensagem", resumo=item.get("text", ""),
                                  texto=item.get("text", ""))]
            nomes = {"command_execution": "Bash", "file_change": "Edit", "mcp_tool_call": "MCP",
                     "web_search": "WebSearch", "collab_tool_call": "Agent"}
            ferramenta = nomes.get(item.get("type"))
            if not ferramenta:
                return []
            detalhe = item.get("command") or json.dumps(item.get("changes") or item.get("arguments") or {}, ensure_ascii=False)
            ev = self.base(ferramenta=ferramenta, resumo=detalhe, detalhe=detalhe)
            if tipo == "item.started":
                ev.update(inicio=True, espera_s=120)
            else:
                codigo = item.get("exit_code")
                if type(codigo) is int:
                    ev.update(ok=codigo == 0, codigo=codigo)
                elif item.get("status") in ("failed", "completed"):
                    ev["ok"] = item["status"] == "completed"
            if ferramenta == "Agent":
                # IDs de threads não são nomes de mesas. O observador liga filhos
                # pela sessão nativa; wait/close não devem criar figuras de subagentes.
                operacao = str(item.get("tool") or "Agent")
                ev.update(resumo=operacao, detalhe=json.dumps({
                    "tool": operacao, "sessoes": item.get("receiver_thread_ids") or []}, ensure_ascii=False))
                if operacao in ("send_input", "send_message") and item.get("prompt"):
                    ev.update(tipo="fala", texto=str(item["prompt"]))
            return [ev]
        if tipo == "text":
            texto = (registro.get("part") or {}).get("text", "")
            return [self.base("fala", ferramenta="Mensagem", resumo=texto, texto=texto)]
        if tipo != "tool_use":
            return []
        part = registro.get("part") or {}
        estado = part.get("state") or {}
        tool = part.get("tool", "")
        entrada = estado.get("input") or {}
        detalhe = "\n".join(f"{k}: {v}" for k, v in entrada.items())
        if tool == "skill" and entrada.get("name"):
            detalhe = "skill: " + str(entrada["name"])
        ev = self.base(ferramenta="Skill" if tool == "skill" else tool,
                       resumo=estado.get("title") or tool, detalhe=detalhe)
        status = estado.get("status")
        if status in ("pending", "running"):
            ev.update(inicio=True, espera_s=120)
        elif status in ("completed", "error"):
            ev["ok"] = status == "completed"
        if estado.get("error"):
            ev["erro"] = str(estado["error"])
        if tool == "task":
            ev.update(tipo="subagente", para=[str(entrada.get("subagent_type") or "Assistente")])
            metadata = estado.get("metadata") or {}
            if metadata.get("sessionId"):
                papel = str(entrada.get("subagent_type") or "Agente")
                papel = re.sub(r"[^a-zA-Z0-9_-]", "_", papel)[:40]
                ev.update(para=[f"OpenCode_{papel}_{metadata['sessionId']}"],
                          sessao_filho=str(metadata["sessionId"]))
        return [ev]


    def converter_claude(self, registro):
        """Stream principal completo; deltas/pensamento/filhos não viram eventos do pai."""
        if registro.get("parent_tool_use_id"):
            return []
        ident = sessao_nativa("claude", registro)
        if isinstance(ident, str) and ident:
            self.sessao = ident
        if not self.sessao or registro.get("session_id", self.sessao) != self.sessao:
            return []
        tipo = registro.get("type")
        mensagem = registro.get("message")
        if tipo in ("assistant", "user") and isinstance(mensagem, dict):
            chave = (tipo, mensagem.get("id") or registro.get("uuid"))
            if chave[1]:
                if chave in self.vistos:
                    return []
                self.vistos.add(chave)
            saida = []
            conteudo = mensagem.get("content")
            if not isinstance(conteudo, list):
                return []
            for bloco in conteudo:
                if not isinstance(bloco, dict):
                    continue
                if tipo == "assistant" and bloco.get("type") == "text" and isinstance(bloco.get("text"), str):
                    saida.append(self.base("fala", ferramenta="Mensagem", resumo=bloco["text"], texto=bloco["text"]))
                elif tipo == "assistant" and bloco.get("type") == "tool_use":
                    ident = bloco.get("id")
                    nome = bloco.get("name")
                    if not isinstance(ident, str) or not isinstance(nome, str) or ident in self.ferramentas:
                        continue
                    self.ferramentas[ident] = nome
                    saida.append(self.base(ferramenta=nome, resumo=nome, inicio=True, espera_s=120,
                                           detalhe=json.dumps(bloco.get("input") or {}, ensure_ascii=False)))
                elif tipo == "user" and bloco.get("type") == "tool_result":
                    ident = bloco.get("tool_use_id")
                    if ident not in self.ferramentas or ("resultado", ident) in self.vistos:
                        continue
                    self.vistos.add(("resultado", ident))
                    ok = bloco.get("is_error") is not True
                    saida.append(self.base(ferramenta=self.ferramentas[ident], resumo="resultado da ferramenta", ok=ok,
                                           **({"erro": "ferramenta retornou erro"} if not ok else {})))
            return saida
        if tipo == "result":
            chave = ("result", registro.get("uuid") or self.sessao)
            if chave in self.vistos:
                return []
            self.vistos.add(chave)
            if registro.get("is_error") is True:
                return [self.base(ferramenta="Console", resumo="erro do console", ok=False,
                                  erro="Claude encerrou o turno com erro"), self.base("ocioso", resumo="turno encerrado com erro")]
            return [self.base("ocioso", resumo="turno encerrado")]
        return []
