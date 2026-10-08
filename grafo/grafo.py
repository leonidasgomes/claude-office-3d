#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""grafo — grafo de arquitetura para agentes de IA (CLI; só biblioteca padrão, PyYAML opcional).

Lê o grafo do projeto (formato modular: ARCHITECTURE_GRAPH.yaml com includes SYSTEMS/EVENTS/FEATURES, ou um YAML
único com as mesmas seções), compara com os imports/includes reais do código e responde perguntas baratas para agentes.

Comandos (rode `grafo.py <comando> -h`):
  init        varre o repositório e propõe um grafo novo (status: proposto); nunca sobrescreve um existente
  validate    esquema, referências, cobertura, camadas, ciclos + arestas REAIS (imports/includes) x depends_on
  owner       dono de um arquivo (exato > pasta mais longa; empate: o último declarado vence, como CODEOWNERS)
  suggest     sugestão de dono para um arquivo sem dono (pasta + maioria dos imports)
  slice       recorte de um sistema dentro de um orçamento de tokens (~4 caracteres por token)
  impact      sistemas tocados/impactados, testes, ADRs e arquivos prováveis para arquivos ou um diff
  find        busca em ids, nomes, classes, caminhos, símbolos e conteúdo; lista os arquivos que casaram
  drift       métricas de desvio entre o grafo e o código
  index       gera .grafo/index.json e .grafo/resumo.txt (determinísticos)
  sync-rules  gera .claude/rules/arq-<sistema>.md (paths: no front matter); só grava com --escrever

Configuração (opcional) na raiz do projeto: grafo.json ou .grafo.toml com as chaves
  grafo (caminho do YAML), raizes, extensoes, ignorar, saida (pasta do index, padrão .grafo), regras (padrão .claude/rules),
  base (ref do git para os hooks), orcamento (tokens do slice).
Saída: 0 ok; 1 achados (validate reprovado, dono não encontrado); 2 erro de uso/leitura.
"""
from __future__ import annotations

import argparse
import ast
import datetime as _dt
import hashlib
import json
import os
import re
import subprocess
import sys
import unicodedata
import warnings
from collections import defaultdict
from pathlib import Path

VERSAO = "0.1.0"
CARACTERES_POR_TOKEN = 4
FORMATO_MODELO = 1   # sobe quando o modelo em cache dos hooks muda de forma

# ===================================================================================================== utilidades


def as_list(v) -> list:
    if v is None:
        return []
    return list(v) if isinstance(v, (list, tuple)) else [v]


def norm_txt(t) -> str:
    """Sem acento, minúsculo, só alfanumérico e espaço."""
    t = unicodedata.normalize("NFKD", str(t))
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", t).split())


def posix(p) -> str:
    return str(p).replace("\\", "/")


def sha1_arquivos(caminhos) -> str:
    h = hashlib.sha1()
    for c in caminhos:
        try:
            h.update(Path(c).read_bytes())
        except OSError:
            h.update(b"<ausente>")
        h.update(b"\0")
    return h.hexdigest()


def tokens_aprox(texto: str) -> int:
    return (len(texto) + CARACTERES_POR_TOKEN - 1) // CARACTERES_POR_TOKEN


def git(raiz, *args, timeout=60) -> tuple[int, str]:
    try:
        p = subprocess.run(["git", "-C", str(raiz), *args], capture_output=True, timeout=timeout)
        return p.returncode, p.stdout.decode("utf-8", "replace")
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)


def resolver_ref(raiz, ref) -> str:
    """Ref vinda da CLI/configuração -> SHA de um commit. Recusa o que começa com '-' (seria opção do git, ex.:
    --output=arquivo) e só passa ao git o SHA verificado."""
    ref = str(ref or "").strip()
    if not ref or ref.startswith("-") or any(c in ref for c in "\0\n\r"):
        raise ValueError(f"ref inválida: {ref!r}")
    rc, out = git(raiz, "rev-parse", "--verify", "--quiet", "--end-of-options", f"{ref}^{{commit}}", timeout=15)
    sha = out.strip()
    if rc != 0 or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", sha):
        raise ValueError(f"ref inexistente ou não é commit: {ref!r}")
    return sha


def sem_prefixo(sid: str) -> str:
    return sid.split(".", 1)[1] if "." in sid else sid


# ===================================================================================================== YAML
# PyYAML é usado quando está instalado (com o leitor estrito que recusa chave repetida, como os validadores de grafo costumam fazer).
# Sem PyYAML (ou com GRAFO_SEM_PYYAML=1) entra o leitor abaixo, que cobre o subconjunto usado pelo formato: mapas e
# listas em bloco, listas/mapas em fluxo ([a, b] e {a: b}, inclusive em várias linhas), textos entre aspas, blocos > e |
# (com - e +), comentários e escalares simples (null, bool, int, float; datas ficam texto). Âncoras, aliases, tags e
# documentos múltiplos não são suportados. A gravação é sempre a deste módulo (saída determinística).


class ErroYaml(ValueError):
    pass


def _carregar_pyyaml():
    if os.environ.get("GRAFO_SEM_PYYAML"):
        return None
    try:
        import yaml  # noqa: PLC0415
        return yaml
    except ImportError:
        return None


_YAML = _carregar_pyyaml()
_LOADER = None


def _loader_estrito():
    global _LOADER
    if _LOADER is None:
        base = getattr(_YAML, "CSafeLoader", None) or _YAML.SafeLoader

        class Estrito(base):  # type: ignore[misc, valid-type]
            pass

        def construir_mapa(loader, no, deep=False):
            vistos = {}
            for k_no, _ in no.value:
                k = loader.construct_object(k_no, deep=deep)
                try:
                    if k in vistos:
                        raise _YAML.constructor.ConstructorError(
                            None, None, f"chave duplicada {k!r} (primeira na linha {vistos[k] + 1})", k_no.start_mark)
                    vistos[k] = k_no.start_mark.line
                except TypeError:
                    pass
            return loader.construct_mapping(no, deep=deep)

        Estrito.add_constructor(_YAML.resolver.BaseResolver.DEFAULT_MAPPING_TAG, construir_mapa)
        _LOADER = Estrito
    return _LOADER


def _datas_texto(v):
    if isinstance(v, dict):
        return {(k.isoformat() if isinstance(k, _dt.date) else k): _datas_texto(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_datas_texto(x) for x in v]
    if isinstance(v, _dt.date):
        return v.isoformat()
    return v


def ler_yaml_texto(texto: str, nome: str = "<yaml>"):
    if _YAML is not None:
        try:
            return _datas_texto(_YAML.load(texto, Loader=_loader_estrito()))
        except _YAML.YAMLError as e:
            raise ErroYaml(f"{nome}: {e}") from None
    return _MiniYaml(texto, nome).documento()


_RE_CHAVE = re.compile(r"""^(?P<k>"(?:[^"\\]|\\.)*"|'(?:[^']|'')*'|[^\s#'"\[\]{},:-][^#]*?|-[^\s#][^#]*?)\s*:(?:[ \t]+(?P<v>.*))?$""")
_BOOL = {"true": True, "yes": True, "on": True, "false": False, "no": False, "off": False}
_RE_INT = re.compile(r"[-+]?(?:0|[1-9][0-9_]*)")
_RE_FLOAT = re.compile(r"[-+]?(?:[0-9][0-9_]*)?\.[0-9_]*(?:[eE][-+][0-9]+)?")


def _escalar(t: str):
    if t in ("", "~", "null", "Null", "NULL"):
        return None
    lo = t.lower()
    if lo in _BOOL and t in (lo, lo.capitalize(), lo.upper()):
        return _BOOL[lo]
    if _RE_INT.fullmatch(t):
        return int(t.replace("_", ""))
    if _RE_FLOAT.fullmatch(t) and any(c.isdigit() for c in t):
        return float(t.replace("_", ""))
    if lo in (".inf", "+.inf"):
        return float("inf")
    if lo == "-.inf":
        return float("-inf")
    if lo == ".nan":
        return float("nan")
    return t


def _sem_comentario(s: str) -> str:
    q = None
    i = 0
    while i < len(s):
        c = s[i]
        if q:
            if q == '"' and c == "\\":
                i += 2
                continue
            if c == q:
                if q == "'" and i + 1 < len(s) and s[i + 1] == "'":
                    i += 2
                    continue
                q = None
        elif c in "\"'" and (i == 0 or s[i - 1] in " \t[{,:"):
            q = c
        elif c == "#" and (i == 0 or s[i - 1] in " \t"):
            return s[:i].rstrip()
        i += 1
    return s.rstrip()


def _fim_aspas(buf: str, q: str):
    i = 1
    while i < len(buf):
        c = buf[i]
        if q == '"' and c == "\\":
            i += 2
            continue
        if c == q:
            if q == "'" and i + 1 < len(buf) and buf[i + 1] == "'":
                i += 2
                continue
            return i
        i += 1
    return None


_ESC_YAML = {"0": "\0", "a": "\a", "b": "\b", "t": "\t", "\t": "\t", "n": "\n", "v": "\v", "f": "\f", "r": "\r",
             "e": "\x1b", " ": " ", '"': '"', "/": "/", "\\": "\\", "N": "\x85", "_": "\xa0", "L": " ",
             "P": " "}


def _desaspas(raw: str) -> str:
    if raw[0] == "'":
        return raw[1:-1].replace("''", "'")
    s, out, i = raw[1:-1], [], 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            n = s[i + 1]
            if n in "xuU":
                tam = {"x": 2, "u": 4, "U": 8}[n]
                out.append(chr(int(s[i + 2:i + 2 + tam], 16)))
                i += 2 + tam
                continue
            out.append(_ESC_YAML.get(n, n))
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _fechado(buf: str) -> bool:
    nivel, q, i = 0, None, 0
    while i < len(buf):
        c = buf[i]
        if q:
            if q == '"' and c == "\\":
                i += 2
                continue
            if c == q:
                q = None
        elif c in "\"'" and (i == 0 or buf[i - 1] in " \t[{,:"):
            q = c
        elif c in "[{":
            nivel += 1
        elif c in "]}":
            nivel -= 1
        i += 1
    return nivel <= 0


def _dobrar(linhas: list[str]) -> str:
    """Bloco > : linhas normais viram espaço, linha vazia vira quebra, linhas mais indentadas mantêm a quebra."""
    res = []
    for k, ln in enumerate(linhas):
        if k == 0:
            res.append(ln)
            continue
        ant = linhas[k - 1]
        if ln == "":
            res.append("\n")
        elif ant == "":
            res.append(ln)
        elif ln.startswith((" ", "\t")) or ant.startswith((" ", "\t")):
            res.append("\n" + ln)
        else:
            res.append(" " + ln)
    return "".join(res)


class _Fluxo:
    def __init__(self, s: str, dono: "_MiniYaml"):
        self.s, self.p, self.dono = s, 0, dono

    def total(self):
        try:
            v = self.valor()
            self.ws()
        except IndexError:
            self.dono.erro("coleção em fluxo incompleta")
        if self.p != len(self.s):
            self.dono.erro(f"sobra depois da coleção: {self.s[self.p:self.p + 30]!r}")
        return v

    def ws(self):
        while self.p < len(self.s) and self.s[self.p] in " \t\n":
            self.p += 1

    def valor(self):
        self.ws()
        s = self.s
        c = s[self.p]
        if c == "[":
            self.p += 1
            out = []
            while True:
                self.ws()
                if s[self.p] == "]":
                    self.p += 1
                    return out
                out.append(self.valor())
                self.ws()
                if s[self.p] == ",":
                    self.p += 1
                    continue
                if s[self.p] == "]":
                    self.p += 1
                    return out
                self.dono.erro(f"esperava , ou ] em {s[self.p:self.p + 20]!r}")
        if c == "{":
            self.p += 1
            out = {}
            while True:
                self.ws()
                if s[self.p] == "}":
                    self.p += 1
                    return out
                k = self.valor()
                self.ws()
                v = None
                if s[self.p] == ":":
                    self.p += 1
                    self.ws()
                    if s[self.p] not in ",}":
                        v = self.valor()
                if k in out:
                    self.dono.erro(f"chave duplicada {k!r}")
                out[k] = v
                self.ws()
                if s[self.p] == ",":
                    self.p += 1
                    continue
                if s[self.p] == "}":
                    self.p += 1
                    return out
                self.dono.erro(f"esperava , ou }} em {s[self.p:self.p + 20]!r}")
        if c in "\"'":
            fim = _fim_aspas(s[self.p:], c)
            if fim is None:
                self.dono.erro("texto entre aspas sem fechar")
            raw = s[self.p:self.p + fim + 1]
            self.p += fim + 1
            return _desaspas(raw)
        ini = self.p
        while self.p < len(s):
            ch = s[self.p]
            if ch in ",]}":
                break
            if ch == ":" and (self.p + 1 == len(s) or s[self.p + 1] in " ,]}\t"):
                break
            self.p += 1
        return _escalar(s[ini:self.p].strip())


class _MiniYaml:
    def __init__(self, texto: str, nome: str):
        self.nome = nome
        texto = texto.replace("\r\n", "\n").replace("\r", "\n")
        if texto.startswith("﻿"):
            texto = texto[1:]
        self.l = texto.split("\n")
        self.i = 0

    def erro(self, msg):
        raise ErroYaml(f"{self.nome}:{self.i + 1}: {msg}")

    @staticmethod
    def _ind(linha: str) -> int:
        return len(linha) - len(linha.lstrip(" "))

    @staticmethod
    def _eh_item(s: str) -> bool:
        return s == "-" or s.startswith("- ")

    def _pular(self) -> bool:
        while self.i < len(self.l):
            s = self.l[self.i].strip()
            if s == "" or s.startswith("#") or s == "---" or s.startswith("%"):
                self.i += 1
                continue
            if s == "...":
                self.i = len(self.l)
            break
        return self.i < len(self.l)

    def documento(self):
        try:
            if not self._pular():
                return None
            v = self._bloco(self._ind(self.l[self.i]))
            if self._pular():
                self.erro("conteúdo inesperado (indentação?)")
            return v
        except ErroYaml as e:
            if str(e).startswith(self.nome + ":"):
                raise
            raise ErroYaml(f"{self.nome}:{self.i + 1}: {e}") from None
        except (IndexError, ValueError, RecursionError) as e:
            raise ErroYaml(f"{self.nome}:{self.i + 1}: {type(e).__name__}: {e}") from None

    def _bloco(self, ind: int):
        s = self.l[self.i].strip()
        if "\t" in self.l[self.i][:ind]:
            self.erro("tabulação na indentação")
        if self._eh_item(s):
            return self._lista(ind)
        if _RE_CHAVE.match(s) and s[0] not in "[{":
            return self._mapa(ind)
        return self._inline(self.l[self.i][ind:], ind - 1)

    def _lista(self, ind: int):
        out = []
        while self._pular():
            linha = self.l[self.i]
            li, s = self._ind(linha), linha.strip()
            if li != ind or not self._eh_item(s):
                if li > ind:
                    self.erro("indentação inesperada")
                break
            resto = linha[li + 1:]
            if resto.strip() == "" or resto.strip().startswith("#"):
                self.i += 1
                if self._pular() and self._ind(self.l[self.i]) > ind:
                    out.append(self._bloco(self._ind(self.l[self.i])))
                else:
                    out.append(None)
                continue
            conteudo = resto.lstrip(" ")
            col = li + 1 + (len(resto) - len(conteudo))
            if self._eh_item(conteudo) or (conteudo[0] not in "[{\"'" and _RE_CHAVE.match(conteudo)) \
                    or (conteudo[0] in "\"'" and _RE_CHAVE.match(_sem_comentario(conteudo))):
                self.l[self.i] = " " * col + conteudo
                out.append(self._bloco(col))
            else:
                out.append(self._inline(conteudo, ind))
        return out

    def _chave(self, k: str):
        if k[0] in "\"'":
            return _desaspas(k)
        return _escalar(k)

    def _mapa(self, ind: int):
        out = {}
        while self._pular():
            linha = self.l[self.i]
            li, s = self._ind(linha), linha.strip()
            if li != ind or self._eh_item(s):
                if li > ind:
                    self.erro("indentação inesperada")
                break
            m = _RE_CHAVE.match(s)
            if not m:
                self.erro(f"esperava 'chave: valor' em {s[:60]!r}")
            k = self._chave(m.group("k"))
            if k in out:
                self.erro(f"chave duplicada {k!r}")
            v = m.group("v") or ""
            if v.strip() == "" or v.lstrip().startswith("#"):
                self.i += 1
                if self._pular():
                    li2, s2 = self._ind(self.l[self.i]), self.l[self.i].strip()
                    if li2 > ind or (li2 == ind and self._eh_item(s2)):
                        out[k] = self._bloco(li2)
                        continue
                out[k] = None
            else:
                out[k] = self._inline(v, ind)
        return out

    def _inline(self, texto: str, ind_pai: int):
        t = texto.strip()
        if t == "":
            self.i += 1
            return None
        c = t[0]
        if c in "[{":
            buf = _sem_comentario(t)
            while not _fechado(buf):
                self.i += 1
                if self.i >= len(self.l):
                    self.erro("coleção [ ] ou { } sem fechar")
                buf += " " + _sem_comentario(self.l[self.i].strip())
            self.i += 1
            return _Fluxo(buf, self).total()
        if c in "\"'":
            partes = [t]

            def junto():
                r = partes[0]
                for p in partes[1:]:
                    r = r + "\n" if p == "" else (r + p if r.endswith("\n") else r + " " + p)
                return r

            while _fim_aspas(junto(), c) is None:
                self.i += 1
                if self.i >= len(self.l):
                    self.erro("texto entre aspas sem fechar")
                partes.append(self.l[self.i].strip())
            buf = junto()
            fim = _fim_aspas(buf, c)
            sobra = buf[fim + 1:].strip()
            if sobra and not sobra.startswith("#"):
                self.erro(f"texto depois das aspas: {sobra[:30]!r}")
            try:
                v = _desaspas(buf[:fim + 1])
            except ValueError:
                self.erro("escape inválido no texto entre aspas")
            self.i += 1
            return v
        if c in "|>":
            return self._bloco_escalar(t, ind_pai)
        if c in "&*!":
            self.erro("âncoras, aliases e tags não são suportados sem PyYAML (pip install pyyaml)")
        partes = [_sem_comentario(t)]
        self.i += 1
        while self.i < len(self.l):
            linha = self.l[self.i]
            s = linha.strip()
            if s == "" or s.startswith("#") or self._ind(linha) <= ind_pai:
                break
            partes.append(_sem_comentario(s))
            self.i += 1
        return _escalar(" ".join(partes))

    def _bloco_escalar(self, cab: str, ind_pai: int):
        cab = _sem_comentario(cab)
        estilo, mod = cab[0], cab[1:]
        chomp = "-" if "-" in mod else "+" if "+" in mod else ""
        dig = re.search(r"[1-9]", mod)
        bi = max(ind_pai, 0) + int(dig.group()) if dig else None
        self.i += 1
        linhas = []
        while self.i < len(self.l):
            linha = self.l[self.i]
            if linha.strip() == "":
                linhas.append("")
                self.i += 1
                continue
            li = self._ind(linha)
            if bi is None:
                if li <= ind_pai:
                    break
                bi = li
            if li < bi:
                break
            linhas.append(linha[bi:])
            self.i += 1
        fim = len(linhas)
        while fim > 0 and linhas[fim - 1] == "":
            fim -= 1
        corpo, sobra = linhas[:fim], len(linhas) - fim
        # linhas vazias consumidas no fim pertencem ao bloco só para o chomp "+"; devolve o cursor para não engolir nada
        if not corpo:
            return ""
        txt = "\n".join(corpo) if estilo == "|" else _dobrar(corpo)
        if chomp == "-":
            return txt
        if chomp == "+":
            return txt + "\n" * (1 + sobra)
        return txt + "\n"


_RE_SEGURO = re.compile(r"^[A-Za-z0-9_./][A-Za-z0-9_./ \-()+@]*$")


def _yaml_txt(s: str, fluxo: bool = False) -> str:
    if s and _RE_SEGURO.match(s) and not s.endswith(" ") and _escalar(s) == s and ": " not in s and " #" not in s \
            and not (fluxo and any(c in s for c in ",[]{}")):
        return s
    return json.dumps(s, ensure_ascii=False)


def _yaml_inline(v, fluxo: bool = False) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return _yaml_txt(v, fluxo)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_yaml_inline(x, True) for x in v) + "]"
    if isinstance(v, dict):
        return "{" + ", ".join(f"{_yaml_txt(str(k), True)}: {_yaml_inline(x, True)}" for k, x in v.items()) + "}"
    return _yaml_txt(str(v), fluxo)


def _curta(lst) -> bool:
    return all(not isinstance(x, (dict, list)) for x in lst) and len(_yaml_inline(lst)) <= 96


def gravar_yaml(v) -> str:
    """Emissor determinístico (mapas e listas em bloco; listas curtas de escalares em fluxo)."""
    out: list[str] = []

    def emitir(x, ind):
        sp = " " * ind
        if isinstance(x, dict):
            for k, y in x.items():
                chave = _yaml_txt(str(k))
                if isinstance(y, dict) and y:
                    out.append(f"{sp}{chave}:")
                    emitir(y, ind + 2)
                elif isinstance(y, list) and y and not _curta(y):
                    out.append(f"{sp}{chave}:")
                    emitir(y, ind + 2)
                else:
                    out.append(f"{sp}{chave}: {_yaml_inline(y)}")
        elif isinstance(x, list):
            for y in x:
                if isinstance(y, dict) and y:
                    ini = len(out)
                    emitir(y, ind + 2)
                    out[ini] = sp + "- " + out[ini][ind + 2:]
                elif isinstance(y, list) and y and not _curta(y):
                    out.append(f"{sp}-")
                    emitir(y, ind + 2)
                else:
                    out.append(f"{sp}- {_yaml_inline(y)}")
        else:
            out.append(sp + _yaml_inline(x))

    emitir(v, 0)
    return "\n".join(out) + "\n"


# ===================================================================================================== projeto e grafo

GRAFOS_PADRAO = ["docs/ARCHITECTURE_GRAPH.yaml", "ARCHITECTURE_GRAPH.yaml", "docs/grafo.yaml", "grafo.yaml",
                 ".grafo.yaml", "docs/architecture.yaml", "architecture.yaml"]
KINDS = {"system": "sys.", "event": "evt.", "feature": "feat.", "data_source": "ds.", "test": "test.",
         "decision": "adr."}
SECOES = {"systems": "system", "events": "event", "features": "feature", "data_sources": "data_source",
          "tests": "test", "decisions": "decision"}
ID_RE = re.compile(r"^[a-z]+\.[a-z0-9_]+(\.[a-z0-9_]+)*$")
REQUIRED = {
    "system": ["id", "name", "layer", "status", "description", "paths"],
    "event": ["id", "name", "kind", "producer", "description"],
    "feature": ["id", "name", "description", "status", "owner_system"],
    "data_source": ["id", "name", "provider", "status", "paths"],
    "test": ["id", "name", "kind", "paths", "covers"],
    "decision": ["id", "title", "status", "date", "decision"],
}
ENUMS = {
    ("system", "status"): {"active", "experimental", "deprecated", "planned", "proposto"},
    ("feature", "status"): {"planned", "in_progress", "done", "deprecated", "cancelled"},
    ("event", "kind"): {"delegate", "call", "file", "log", "input", "config"},
    ("data_source", "status"): {"historical", "observed", "operational", "planned", "inferred", "projected",
                                "simulated", "retired"},
    ("test", "kind"): {"automation", "editor_python", "powershell", "python", "manual"},
    ("decision", "status"): {"proposed", "accepted", "superseded", "rejected"},
}
REFS = {
    ("system", "depends_on"): {"system"},
    ("system", "data_sources"): {"data_source"},
    ("system", "decisions"): {"decision"},
    ("system", "produces"): {"event", "data_source"},
    ("system", "consumes"): {"event", "data_source"},
    ("event", "producer"): {"system"},
    ("event", "consumers"): {"system"},
    ("event", "caller"): {"system"},
    ("event", "callee"): {"system"},
    ("feature", "owner_system"): {"system"},
    ("feature", "depends_on"): {"feature"},
    ("feature", "affects"): {"system"},
    ("feature", "data_sources"): {"data_source"},
    ("feature", "events"): {"event"},
    ("feature", "decisions"): {"decision"},
    ("data_source", "produced_by"): {"system"},
    ("test", "covers"): {"system", "feature", "event"},
    ("decision", "affects"): {"system", "feature", "data_source"},
    ("decision", "supersedes"): {"decision"},
}
CAMPOS_NOVOS = ["summary", "entrypoints", "invariants", "test_cmd", "extension_points", "pitfalls", "lessons",
                "produces", "consumes"]
CORES = ["#4e79a7", "#f28e2b", "#59a14f", "#b07aa1", "#e15759", "#76b7b2", "#edc948", "#ff9da7", "#9c755f"]
COR_SEM_CAMADA = "#9e9e9e"
EVENTOS_DE_CODIGO = {"call", "input", "delegate"}

EXT_PY = {".py", ".pyw"}
EXT_C = {".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx", ".inl", ".ipp", ".m", ".mm"}
EXT_JS = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts"}
EXT_CS = {".cs"}
EXT_SH = {".ps1", ".psm1", ".sh", ".bash", ".bat", ".cmd"}
EXTS_PADRAO = EXT_PY | EXT_C | EXT_JS | EXT_CS
EXTS_ANALISE = EXT_PY | EXT_C | EXT_JS | EXT_CS | EXT_SH
DIRS_IGNORADOS = {".git", "node_modules", "__pycache__", ".venv", "venv", "env", ".grafo", ".tox", ".mypy_cache",
                  ".pytest_cache", ".idea", ".vs", ".vscode", "dist", "build", "out", "target", "bin", "obj",
                  "Binaries", "Intermediate", "Saved", "DerivedDataCache", ".next", "coverage", "vendor",
                  "third_party", "external"}
LIMITE_LEITURA = 2_000_000


def ler_toml_simples(texto: str) -> dict:
    try:
        import tomllib  # noqa: PLC0415
        return tomllib.loads(texto)
    except ImportError:
        pass
    out = {}
    for ln in texto.splitlines():
        ln = ln.split("#", 1)[0].strip()
        if "=" in ln and not ln.startswith("["):
            k, v = (x.strip() for x in ln.split("=", 1))
            try:
                out[k] = json.loads(v.replace("'", '"'))
            except ValueError:
                out[k] = v.strip("\"'")
    return out


ARQUIVOS_CONFIG = ("grafo.json", ".grafo.json", ".grafo.toml")


def ler_config(raiz: Path) -> dict:
    for nome in ("grafo.json", ".grafo.json"):
        p = raiz / nome
        if p.is_file():
            try:
                return json.loads(p.read_text(encoding="utf-8")) or {}
            except (OSError, ValueError):
                return {}
    p = raiz / ".grafo.toml"
    if p.is_file():
        try:
            d = ler_toml_simples(p.read_text(encoding="utf-8"))
            return d.get("grafo", d) if isinstance(d.get("grafo"), dict) else d
        except (OSError, ValueError):
            return {}
    return {}


def achar_raiz(inicio=None) -> Path:
    ini = Path(inicio or os.getcwd()).resolve()
    if ini.is_file():
        ini = ini.parent
    rc, out = git(ini, "rev-parse", "--show-toplevel", timeout=15)
    if rc == 0 and out.strip():
        return Path(out.strip()).resolve()
    for p in [ini, *ini.parents]:
        if any((p / n).is_file() for n in ("grafo.json", ".grafo.json", ".grafo.toml", *GRAFOS_PADRAO)):
            return p
    return ini


class Projeto:
    """Raiz + configuração + caminho do grafo."""

    def __init__(self, raiz=None, grafo=None):
        self.raiz = Path(raiz).resolve() if raiz else achar_raiz()
        self.config = ler_config(self.raiz)
        escolhido = grafo or self.config.get("grafo")
        self.grafo_arq = None
        if escolhido:
            p = Path(escolhido)
            self.grafo_arq = p if p.is_absolute() else self.raiz / p
        else:
            for c in GRAFOS_PADRAO:
                if (self.raiz / c).is_file():
                    self.grafo_arq = self.raiz / c
                    break
        self._repo = None

    @property
    def repo(self) -> "Repo":
        if self._repo is None:
            self._repo = Repo(self.raiz)
        return self._repo

    def pasta_saida(self, opcao=None) -> Path:
        if opcao:
            p = Path(opcao)
            return p if p.is_absolute() else self.raiz / p
        return self.pasta_da_config("saida", ".grafo")

    def pasta_da_config(self, chave: str, padrao: str) -> Path:
        """Pasta vinda do grafo.json: precisa ficar dentro da raiz (pela CLI é livre)."""
        p = (self.raiz / str(self.config.get(chave) or padrao)).resolve()
        try:
            p.relative_to(self.raiz.resolve())
        except ValueError:
            raise ValueError(f"'{chave}' da configuração aponta para fora do projeto: {posix(p)}") from None
        return p

    def grafo(self) -> "Grafo":
        if self.grafo_arq is None:
            raise FileNotFoundError("grafo não encontrado: use --grafo, grafo.json/.grafo.toml ou rode `grafo.py init`")
        return Grafo(self.grafo_arq, self.raiz)


class Grafo:
    def __init__(self, caminho: Path, raiz: Path):
        self.caminho, self.raiz = Path(caminho), Path(raiz)
        self.problemas: list[str] = []
        self.fontes: list[Path] = [self.caminho]
        self.dados = self._ler(self.caminho)
        self.nos: dict[str, list] = {k: [] for k in KINDS}
        incl = self.dados.get("includes") or {}
        if not isinstance(incl, dict):
            self.problemas.append("includes: esperado um mapa seção: arquivo")
            incl = {}
        for secao, rel in incl.items():
            kind = SECOES.get(secao)
            if kind is None:
                self.problemas.append(f"includes.{secao}: seção desconhecida (use {', '.join(SECOES)})")
                continue
            arq = self.caminho.parent / str(rel)
            try:   # include fora da raiz do projeto (../../, caminho absoluto, link): erro de leitura, não é lido
                arq.resolve().relative_to(self.raiz.resolve())
            except (ValueError, OSError):
                self.problemas.append(f"includes.{secao}: {posix(str(rel))} fica fora do projeto (não lido)")
                continue
            self.fontes.append(arq)
            self.nos[kind].extend(self._higienizar(kind, as_list(self._ler(arq).get(secao)), arq))
        for secao, kind in SECOES.items():
            self.nos[kind].extend(self._higienizar(kind, as_list(self.dados.get(secao)), self.caminho))
        self.indice: dict[str, tuple[str, dict]] = {}
        for kind, itens in self.nos.items():
            for n in itens:
                if isinstance(n, dict) and isinstance(n.get("id"), str):
                    self.indice.setdefault(n["id"], (kind, n))
        self.sistemas: dict[str, dict] = {}
        for n in self.nos["system"]:
            if isinstance(n, dict) and isinstance(n.get("id"), str):
                self.sistemas.setdefault(n["id"], n)
        camadas = self.dados.get("layers") or {}
        if not isinstance(camadas, dict):
            self.problemas.append(f"{posix(self.caminho.name)}: layers deve ser um mapa camada: {{may_depend_on: [...]}}")
            camadas = {}
        self.camadas: dict = {}
        for c, v in camadas.items():
            if not isinstance(v, (dict, type(None))):
                self.problemas.append(f"{posix(self.caminho.name)}: layers.{c} deve ser um mapa")
                v = {}
            v = dict(v or {})
            v["may_depend_on"] = [x for x in as_list(v.get("may_depend_on")) if isinstance(x, str)]
            self.camadas[str(c)] = v
        cov = self.dados.get("coverage") or {}
        if not isinstance(cov, dict):
            self.problemas.append(f"{posix(self.caminho.name)}: coverage deve ser um mapa")
            cov = {}
        self.cobertura: dict = {k: ([x for x in as_list(v) if isinstance(x, str)] if k in ("roots", "extensions", "ignore")
                                    else v) for k, v in cov.items()}
        self._pares_evento = None

    def _higienizar(self, kind: str, itens: list, arq: Path) -> list:
        """Tipos errados viram problema (erro de leitura com o arquivo) em vez de derrubar a validação:
        campos de texto que vieram como lista/mapa viram texto; listas de referência ficam só com textos."""
        listas = {c for (k, c) in REFS if k == kind} | {"paths", "classes", "symbol", "covers"}
        textos = {"id", "name", "title", "layer", "status", "kind", "producer", "owner_system", "summary", "test_cmd",
                  "command", "date"}
        nome = posix(arq.name)
        for i, n in enumerate(itens):
            if not isinstance(n, dict):
                continue
            nid = n.get("id") if isinstance(n.get("id"), str) else f"{kind}[{i}]"
            for campo, v in list(n.items()):
                if campo in textos and isinstance(v, (list, dict)):
                    self.problemas.append(f"{nome}: {nid}.{campo} deve ser texto, veio {type(v).__name__}")
                    n[campo] = str(v)
                elif campo in textos and v is not None and not isinstance(v, str):
                    n[campo] = str(v)   # escalar do YAML (name: 2024, status: true, data): vira texto, sem quebrar index/painel
                elif campo in listas and campo not in textos:
                    vs = as_list(v) if not isinstance(v, dict) else [v]
                    ruins = [x for x in vs if not isinstance(x, str)]
                    if ruins:
                        self.problemas.append(f"{nome}: {nid}.{campo} aceita só textos (ignorado: {str(ruins)[:60]})")
                        n[campo] = [x for x in vs if isinstance(x, str)]
        return itens

    @property
    def arquivo_sistemas(self) -> Path:
        """Arquivo onde os sistemas são declarados (includes.systems ou o próprio grafo)."""
        rel = (self.dados.get("includes") or {}).get("systems") if isinstance(self.dados.get("includes"), dict) else None
        return self.caminho.parent / str(rel) if rel else self.caminho

    def _ler(self, arq: Path) -> dict:
        try:
            texto = arq.read_text(encoding="utf-8")
        except OSError:
            self.problemas.append(f"arquivo não encontrado: {posix(arq)}")
            return {}
        try:
            d = ler_yaml_texto(texto, posix(arq))
        except ErroYaml as e:
            self.problemas.append(f"YAML inválido: {e}")
            return {}
        if d is None:
            return {}
        if not isinstance(d, dict):
            self.problemas.append(f"{posix(arq)}: a raiz deve ser um mapa")
            return {}
        return d

    def assinatura(self) -> str:
        return sha1_arquivos(self.fontes)

    # ---------------- consultas
    def no(self, nid):
        return self.indice.get(nid, (None, {}))[1]

    def deps(self, sid) -> list[str]:
        return [d for d in as_list(self.sistemas.get(sid, {}).get("depends_on")) if isinstance(d, str)]

    def usado_por(self, sid) -> list[str]:
        return sorted(a for a, n in self.sistemas.items() if sid in as_list(n.get("depends_on")))

    def camada(self, sid) -> str:
        return str(self.sistemas.get(sid, {}).get("layer") or "")

    def cor(self, camada: str) -> str:
        nomes = list(self.camadas)
        return CORES[nomes.index(camada) % len(CORES)] if camada in nomes else COR_SEM_CAMADA

    def eventos(self, sid) -> tuple[list, list]:
        """(eventos que o sistema produz/chama, eventos que consome/recebe)."""
        prod, cons = [], []
        for e in self.nos["event"]:
            if not isinstance(e, dict):
                continue
            if sid == e.get("producer") or sid in as_list(e.get("caller")):
                prod.append(e)
            elif sid in as_list(e.get("consumers")) or sid in as_list(e.get("callee")):
                cons.append(e)
        sis = self.sistemas.get(sid, {})
        ids_p = {x.get("id") for x in prod}
        ids_c = {x.get("id") for x in cons}
        for eid in as_list(sis.get("produces")):
            if self.indice.get(eid, (None,))[0] == "event" and eid not in ids_p:
                prod.append(self.no(eid))
        for eid in as_list(sis.get("consumes")):
            if self.indice.get(eid, (None,))[0] == "event" and eid not in ids_c:
                cons.append(self.no(eid))
        return prod, cons

    def pares_evento(self) -> set:
        """Pares (a, b) em que um import/include de a para b é explicado por um evento de código (kind call, input ou
        delegate; eventos file/log/config são troca de dados e não explicam acoplamento de código).
        Sentido: caller -> callee quando declarados; senão, o dono da classe do símbolo (Classe::Metodo, pelo campo
        classes dos sistemas) é quem é chamado e os demais participantes chamam; sem isso, vale nos dois sentidos.
        delegate vale nos dois sentidos (quem assina inclui o produtor)."""
        if self._pares_evento is None:
            dono_classe = {str(c): sid for sid, n in self.sistemas.items() for c in as_list(n.get("classes"))}
            pares = set()
            for e in self.nos["event"]:
                if not isinstance(e, dict):
                    continue
                kind = e.get("kind")
                caller = [x for x in as_list(e.get("caller")) if isinstance(x, str)]
                callee = [x for x in as_list(e.get("callee")) if isinstance(x, str)]
                if kind not in EVENTOS_DE_CODIGO and not (caller or callee):
                    continue
                partes = {x for x in as_list(e.get("producer")) + as_list(e.get("consumers")) + caller + callee
                          if isinstance(x, str)}
                if caller and callee:
                    novos = {(a, b) for a in caller for b in callee}
                else:
                    chamados = {dono_classe.get(str(sym).split("::")[0]) for sym in as_list(e.get("symbol"))
                                if "::" in str(sym)} & partes
                    if callee:
                        chamados = set(callee)
                    if chamados and kind != "delegate":
                        novos = {(a, b) for b in chamados for a in partes}
                    else:
                        novos = {(a, b) for a in partes for b in partes}
                for a, b in novos:
                    if a != b:
                        pares.add((a, b))
                        if kind == "delegate":
                            pares.add((b, a))
            prod, cons = defaultdict(set), defaultdict(set)
            for sid, n in self.sistemas.items():
                for eid in as_list(n.get("produces")):
                    prod[eid].add(sid)
                for eid in as_list(n.get("consumes")):
                    cons[eid].add(sid)
            for eid in prod:
                k = self.indice.get(eid, (None, {}))
                if k[0] == "event" and k[1].get("kind") in EVENTOS_DE_CODIGO:
                    pares.update((a, b) for a in prod[eid] for b in cons.get(eid, ()) if a != b)
            self._pares_evento = pares
        return self._pares_evento

    def testes(self, sid) -> list[dict]:
        return [t for t in self.nos["test"] if isinstance(t, dict) and sid in as_list(t.get("covers"))]

    def adrs(self, sid) -> list[dict]:
        ids = list(as_list(self.sistemas.get(sid, {}).get("decisions")))
        for d in self.nos["decision"]:
            if isinstance(d, dict) and sid in as_list(d.get("affects")) and d.get("id") not in ids:
                ids.append(d.get("id"))
        return [self.no(i) or {"id": i} for i in ids]

    def resumo(self, sid, limite=200) -> str:
        n = self.sistemas.get(sid) or self.no(sid) or {}
        return resumo_texto(n.get("summary") or n.get("description") or "", limite)

    def achar_sistema(self, texto: str):
        t = texto.strip()
        if t in self.sistemas:
            return t
        for cand in (f"sys.{t}", t.lower(), f"sys.{t.lower()}"):
            if cand in self.sistemas:
                return cand
        return None


def resumo_texto(texto, limite=200) -> str:
    t = " ".join(str(texto or "").split())
    if not t:
        return ""
    primeira = re.split(r"(?<=[.!?])\s+(?=[A-ZÀ-Ý0-9(])", t, maxsplit=1)[0]
    if len(primeira) <= limite:
        return primeira
    corte = primeira[:limite - 1].rsplit(" ", 1)[0]
    return corte.rstrip(",;:—- ") + "…"


# ===================================================================================================== arquivos e donos

_GLOB_CACHE: dict = {}


def glob_re(pat: str):
    r = _GLOB_CACHE.get(pat)
    if r is None:
        i, out = 0, []
        while i < len(pat):
            c = pat[i]
            if pat.startswith("**/", i):
                out.append("(?:.*/)?")
                i += 3
                continue
            if pat.startswith("**", i):
                out.append(".*")
                i += 2
                continue
            if c == "*":
                out.append("[^/]*")
            elif c == "?":
                out.append("[^/]")
            elif c == "[":
                j = pat.find("]", i)
                if j < 0:
                    out.append(re.escape(c))
                else:
                    out.append("[" + pat[i + 1:j].replace("!", "^", 1) + "]")
                    i = j
            else:
                out.append(re.escape(c))
            i += 1
        try:
            r = re.compile("".join(out) + r"\Z", re.I)
        except re.error:   # padrão inválido ([] vazio, faixa ao contrário): casa só o texto literal; validate acusa
            GLOBS_INVALIDOS.add(pat)
            r = re.compile(re.escape(pat) + r"\Z", re.I)
        _GLOB_CACHE[pat] = r
    return r


GLOBS_INVALIDOS: set = set()


def eh_glob(p: str) -> bool:
    return any(c in p for c in "*?[")


def norm_padrao(p) -> str:
    q = posix(str(p)).strip()
    while q.startswith("./"):
        q = q[2:]
    return q.rstrip("/")


def sob_raiz(f: str, raiz: str) -> bool:
    raiz = norm_padrao(raiz)
    if raiz in ("", "."):
        return True
    if eh_glob(raiz):
        return bool(glob_re(raiz).match(f) or glob_re(raiz + "/**").match(f))
    fl, rl = f.lower(), raiz.lower()
    return fl == rl or fl.startswith(rl + "/")


class Repo:
    def __init__(self, raiz: Path):
        self.raiz = Path(raiz)
        self._todos = None
        self._minusc = None
        self.eh_git = (self.raiz / ".git").exists()

    def todos(self) -> list[str]:
        if self._todos is None:
            arqs = None
            if self.eh_git:
                rc, out = git(self.raiz, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
                if rc == 0:
                    arqs = {a for a in out.split("\0") if a}
                    rc2, out2 = git(self.raiz, "ls-files", "-z", "--deleted")
                    if rc2 == 0:
                        arqs -= {a for a in out2.split("\0") if a}
            if arqs is None:
                arqs = set()
                base = str(self.raiz)
                for d, subdirs, files in os.walk(base):
                    subdirs[:] = sorted(x for x in subdirs if x not in DIRS_IGNORADOS)
                    rel = posix(d[len(base):]).strip("/")
                    for f in files:
                        arqs.add(f"{rel}/{f}" if rel else f)
            self._todos = sorted(posix(a) for a in arqs)
        return self._todos

    def minusculo(self) -> dict:
        if self._minusc is None:
            self._minusc = {f.lower(): f for f in self.todos()}
        return self._minusc

    def pastas(self) -> set:
        if getattr(self, "_pastas", None) is None:
            ps = set()
            for f in self.todos():
                d = _dir(f).lower()
                while d and d not in ps:
                    ps.add(d)
                    d = _dir(d)
            self._pastas = ps
        return self._pastas

    def ler(self, rel: str) -> str:
        try:
            p = self.raiz / rel
            if p.stat().st_size > LIMITE_LEITURA:
                return ""
            return p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def mudados(self, ref: str) -> list[str]:
        sha = resolver_ref(self.raiz, ref)
        rc, out = git(self.raiz, "diff", "--name-only", "-z", sha, "--")
        if rc != 0:
            raise ValueError(f"git diff {ref} falhou: {out.strip()[:200] or 'ref inexistente?'}")
        arqs = {a for a in out.split("\0") if a}
        rc, out = git(self.raiz, "ls-files", "-z", "--others", "--exclude-standard")
        if rc == 0:
            arqs |= {a for a in out.split("\0") if a}
        return sorted(posix(a) for a in arqs)


def normalizar_caminho(caminho: str, raiz: Path, repo: Repo | None = None, donos: "Donos | None" = None) -> str:
    """Caminho do agente -> relativo à raiz: aceita absoluto, '\\' do Windows, worktrees e maiúsculas diferentes."""
    c = posix(str(caminho).strip().strip("\"'"))
    while c.startswith("./"):
        c = c[2:]
    r = posix(str(raiz)).rstrip("/")
    absoluto = bool(re.match(r"^[A-Za-z]:/", c)) or c.startswith("/")
    if absoluto:
        if c.lower() == r.lower():
            return ""
        if c.lower().startswith(r.lower() + "/"):
            c = c[len(r) + 1:]
            absoluto = False
    m = re.search(r"(?:^|/)\.claude/worktrees/[^/]+/(.*)$", c) or re.search(r"(?:^|/)\.worktrees/[^/]+/(.*)$", c)
    if m:
        c, absoluto = m.group(1), False
    mapa = repo.minusculo() if repo is not None else {}
    if not absoluto:
        return mapa.get(c.lower(), c)
    partes = [p for p in c.split("/") if p]
    if re.match(r"^[A-Za-z]:$", partes[0] if partes else ""):
        partes = partes[1:]
    # absoluto fora da raiz (outra worktree/clone): o maior sufixo que existe no repositório ou que tem dono
    for i in range(len(partes)):
        cand = "/".join(partes[i:])
        if cand.lower() in mapa:
            return mapa[cand.lower()]
    if repo is not None:   # arquivo novo: o maior sufixo cuja pasta existe no repositório
        pastas = repo.pastas()
        for i in range(len(partes) - 1):
            cand = "/".join(partes[i:])
            if _dir(cand).lower() in pastas:
                return cand
    if donos is not None:
        for i in range(len(partes)):
            cand = "/".join(partes[i:])
            d = donos.dono(cand)
            if d and d[2] >= 2 and "/" in cand:
                return cand
    return "/".join(partes)


class Donos:
    """Dono de cada arquivo: caminho exato > pasta (ou padrão) mais longa; empate: o último declarado vence."""

    def __init__(self, sistemas):
        self.exatos: dict[str, list] = defaultdict(list)
        self.globs: list = []
        self.todos: list = []
        ordem = 0
        for n in sistemas:
            sid = n.get("id")
            for p in as_list(n.get("paths")):
                if not isinstance(p, str):
                    continue
                q = norm_padrao(p)
                if q in ("", "."):
                    q = "**"
                self.todos.append((q, sid, ordem))
                if eh_glob(q):
                    literal = len(re.split(r"[*?\[]", q, maxsplit=1)[0])
                    self.globs.append((glob_re(q), literal, ordem, sid, q))
                else:
                    self.exatos[q.lower()].append((ordem, sid, q))
                ordem += 1

    def dono(self, rel: str):
        """(sistema, padrão, rank) — rank 3 = arquivo exato, 2 = pasta/padrão; None sem dono."""
        rl = norm_padrao(rel).lower()
        melhor = None
        for ordem, sid, q in self.exatos.get(rl, []):
            k = (3, len(q), ordem)
            if melhor is None or k > melhor[0]:
                melhor = (k, sid, q)
        if melhor is None:
            partes = rl.split("/")
            for i in range(len(partes) - 1, 0, -1):
                pref = "/".join(partes[:i])
                if pref in self.exatos:
                    for ordem, sid, q in self.exatos[pref]:
                        k = (2, len(q), ordem)
                        if melhor is None or k > melhor[0]:
                            melhor = (k, sid, q)
                    break
            pastas = [rl]
            d = _dir(rl)
            while d:
                pastas.append(d)
                d = _dir(d)
            for rx, literal, ordem, sid, q in self.globs:
                if any(rx.match(x) for x in pastas):   # padrão que casa uma pasta é dono do conteúdo (src/Foo*)
                    k = (2, literal, ordem)
                    if melhor is None or k > melhor[0]:
                        melhor = (k, sid, q)
        if melhor is None:
            return None
        return melhor[1], melhor[2], melhor[0][0]

    def conflitos(self):
        out = []
        for chave, lst in self.exatos.items():
            sids = sorted({s for _, s, _ in lst})
            if len(sids) > 1:
                out.append((lst[0][2], sids))
        vistos = defaultdict(set)
        for _, _, _, sid, q in self.globs:
            vistos[q.lower()].add(sid)
        out += [(q, sorted(s)) for q, s in vistos.items() if len(s) > 1]
        return sorted(out)

    def aninhados(self):
        """Pasta de um sistema que contém caminho de outro (resolvido pelo mais específico)."""
        nao_glob = [(q, s) for q, s, _ in self.todos if not eh_glob(q) and q != "**"]
        out = []
        for q, s in nao_glob:
            for q2, s2 in nao_glob:
                if s != s2 and q2.lower().startswith(q.lower() + "/"):
                    out.append((s, q, s2, q2))
        return sorted(set(out))


def arquivos_cobertos(g: Grafo, repo: Repo, cfg: dict) -> list[str]:
    cov = g.cobertura
    raizes = [norm_padrao(r) for r in (as_list(cov.get("roots")) or as_list(cfg.get("raizes")) or [""])]
    exts = {e.lower() if e.startswith(".") else "." + e.lower()
            for e in (as_list(cov.get("extensions")) or as_list(cfg.get("extensoes")) or sorted(EXTS_PADRAO))}
    ignorar = as_list(cov.get("ignore")) + as_list(cfg.get("ignorar"))
    out = []
    for f in repo.todos():
        if os.path.splitext(f)[1].lower() not in exts:
            continue
        if not any(sob_raiz(f, r) for r in raizes):
            continue
        if any(glob_re(norm_padrao(p)).match(f) or sob_raiz(f, p) for p in ignorar if p):
            continue
        out.append(f)
    return out


# ===================================================================================================== imports reais

_RE_PY_IMPORT = re.compile(r"^[ \t]*import[ \t]+([\w.]+(?:[ \t]+as[ \t]+\w+)?(?:[ \t]*,[ \t]*[\w.]+(?:[ \t]+as[ \t]+\w+)?)*)", re.M)
_RE_PY_FROM = re.compile(r"^[ \t]*from[ \t]+(\.*)([\w.]*)[ \t]+import[ \t]+\(?\s*([\w\s,*]+)", re.M)
_RE_INC = re.compile(r'^[ \t]*#[ \t]*(?:include|import)[ \t]*([<"])([^>"\n]+)[>"]', re.M)
_RE_JS = re.compile(r"""(?:\bimport\s+(?:type\s+)?(?:[\w*{}\s,$]+?\s+from\s+)?|\bexport\s+(?:type\s+)?[\w*{}\s,$]+?\s+from\s+|\brequire\s*\(\s*|\bimport\s*\(\s*)(['"])([^'"\n]+)\1""")
_RE_CS_USING = re.compile(r"^[ \t]*(?:global[ \t]+)?using[ \t]+(?:static[ \t]+)?(?:\w+[ \t]*=[ \t]*)?([\w.]+)[ \t]*;", re.M)
_RE_CS_NS = re.compile(r"^[ \t]*namespace[ \t]+([\w.]+)", re.M)
_RE_SH_REF = re.compile(r"[\w$%~.:{}()\\/\-]*?[\w\-]+\.(?:py|ps1|psm1|sh|bat|cmd)\b", re.I)
_STDLIB = set(getattr(sys, "stdlib_module_names", ()))


def _linha(texto: str, pos: int) -> int:
    return texto.count("\n", 0, pos) + 1


def _imports_ast(arvore):
    """Só comandos (não desce em expressões): imports no módulo, em funções, classes, if/try/with/match."""
    pilha = list(arvore.body)
    while pilha:
        no = pilha.pop()
        if isinstance(no, (ast.Import, ast.ImportFrom)):
            yield no
            continue
        for campo in ("body", "orelse", "finalbody", "handlers", "cases"):
            v = getattr(no, campo, None)
            if isinstance(v, list):
                pilha.extend(x for x in v if isinstance(x, ast.AST))


def extrair_refs(rel: str, texto: str) -> list[tuple]:
    """Referências cruas de um arquivo: (tipo, alvo, linha). tipo: py | inc | js | cs | sh."""
    ext = os.path.splitext(rel)[1].lower()
    out: list[tuple] = []
    if ext in EXT_PY:
        arvore = None
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                arvore = ast.parse(texto)
        except (SyntaxError, ValueError):
            arvore = None
        if arvore is not None:
            for no in _imports_ast(arvore):
                if isinstance(no, ast.Import):
                    for a in no.names:
                        out.append(("py", (0, a.name, ()), no.lineno))
                elif isinstance(no, ast.ImportFrom):
                    out.append(("py", (no.level or 0, no.module or "", tuple(a.name for a in no.names)), no.lineno))
        else:
            for m in _RE_PY_IMPORT.finditer(texto):
                for parte in m.group(1).split(","):
                    out.append(("py", (0, parte.split()[0], ()), _linha(texto, m.start())))
            for m in _RE_PY_FROM.finditer(texto):
                nomes = tuple(x.split()[0] for x in m.group(3).replace("\n", " ").split(",") if x.split())
                out.append(("py", (len(m.group(1)), m.group(2), nomes), _linha(texto, m.start())))
    elif ext in EXT_C:
        for m in _RE_INC.finditer(texto):
            out.append(("inc", posix(m.group(2).strip()), _linha(texto, m.start())))
    elif ext in EXT_JS:
        for m in _RE_JS.finditer(texto):
            out.append(("js", m.group(2), _linha(texto, m.start())))
    elif ext in EXT_CS:
        for m in _RE_CS_USING.finditer(texto):
            out.append(("cs", m.group(1), _linha(texto, m.start())))
    elif ext in EXT_SH:
        out += _refs_script(texto)
    return out


_RE_SH_COMENTARIO = re.compile(r"^(?:#|::|//|rem(?:\s|$)|@rem(?:\s|$))", re.I)
_RE_SH_TEXTO = re.compile(r"^(?:throw|write-host|write-output|write-warning|write-error|write-verbose|write-information|"
                          r"echo|print|printf|@echo)\b", re.I)
_RE_SH_CHAMADA = re.compile(r"(?:^|[\s(;|{])(?:&|\.(?=\s)|python[\w.]*|py|pwsh|powershell(?:\.exe)?|bash|sh|call|source|"
                            r"invoke-expression|iex|start-process|import-module|join-path|-file|import)(?=[\s('\"]|$)", re.I)


def _refs_script(texto: str) -> list[tuple]:
    """Scripts citados num .ps1/.sh/.bat: só em linha de chamada (&, ., python, call, source, Join-Path,
    Start-Process...), fora de comentários (#, REM, ::, //, <# #>) e de textos de throw/Write-Host/echo/print."""
    out, bloco = [], False
    for n, bruta in enumerate(texto.splitlines(), 1):
        ln = bruta.strip()
        if bloco:
            if "#>" in ln:
                bloco = False
                ln = ln.split("#>", 1)[1].strip()
            else:
                continue
        if "<#" in ln:
            antes, depois = ln.split("<#", 1)
            if "#>" not in depois:
                bloco = True
            ln = (antes + " " + depois.split("#>", 1)[1]) if "#>" in depois else antes
            ln = ln.strip()
        if not ln or _RE_SH_COMENTARIO.match(ln):
            continue
        ln = _sem_comentario(ln)
        # trecho depois de throw/Write-Host/echo (inclusive dentro de { }) é texto, não chamada
        partes = re.split(r"[;{}]", ln)
        uteis = [p for p in partes if p.strip() and not _RE_SH_TEXTO.match(p.strip())]
        ln = " ; ".join(uteis)
        if not ln or not _RE_SH_CHAMADA.search(ln):
            continue
        for m in _RE_SH_REF.finditer(ln):
            out.append(("sh", m.group(0), n))
    return out


def _dir(f: str) -> str:
    return f.rsplit("/", 1)[0] if "/" in f else ""


def _comum(a: str, b: str) -> int:
    pa, pb = _dir(a).lower().split("/"), _dir(b).lower().split("/")
    n = 0
    for x, y in zip(pa, pb):
        if x != y:
            break
        n += 1
    return n


def _juntar(base: str, rel: str) -> str:
    partes = [p for p in base.split("/") if p] if base else []
    for p in rel.split("/"):
        if p in ("", "."):
            continue
        if p == "..":
            if partes:
                partes.pop()
            continue
        partes.append(p)
    return "/".join(partes)


_RE_SYS_PATH = re.compile(r"sys\.path\.(?:insert|append|extend)\b")
_RE_FOR = re.compile(r"^[ \t]*for[ \t]+([A-Za-z_]\w*)[ \t]+in[ \t]+(.+?):[ \t]*$", re.M)
_RE_PALAVRA = re.compile(r"[\w\-]+")
_RE_ATRIB = re.compile(r"^[ \t]*([A-Za-z_]\w*)[ \t]*=(?!=)(.*)$", re.M)
_FICHAS_SOBE = {"parent", "parents", "dirname", "pardir", ".."}


def fichas_sys_path(texto: str) -> set:
    """Pedaços de caminho citados em sys.path.insert/append, seguindo as variáveis usadas ali (atribuições e
    `for p in (A, B)`) até dois níveis."""
    defs = defaultdict(list)
    for m in _RE_ATRIB.finditer(texto):
        defs[m.group(1)].append(m.group(2))
    for m in _RE_FOR.finditer(texto):
        defs[m.group(1)].append(m.group(2))
    fichas: set = set()
    pendentes = []
    for ln in texto.splitlines():
        if _RE_SYS_PATH.search(ln):
            pendentes.append(ln)
    vistos: set = set()
    for _ in range(3):
        novos = []
        for trecho in pendentes:
            palavras = _RE_PALAVRA.findall(trecho)
            fichas.update(p.lower() for p in palavras)
            if ".." in trecho:
                fichas.add("..")
            for p in palavras:
                if p in defs and p not in vistos:
                    vistos.add(p)
                    novos += defs[p]
        pendentes = novos
    return fichas


class Resolvedor:
    def __init__(self, arquivos: list[str], textos_cs: dict | None = None, raiz=None, raizes_python=None, leitor=None):
        self.raiz = posix(raiz or "")
        self.raizes_python = {norm_padrao(r).lower() for r in as_list(raizes_python) if isinstance(r, str)}
        self.fichas: dict[str, set] = {}
        self.leitor = leitor
        self._ctx: dict = {}
        self._refs: dict = {}
        self._lidos: set = set()
        self.minusc = {f.lower(): f for f in arquivos}
        self.por_nome: dict[str, list] = defaultdict(list)
        for f in arquivos:
            self.por_nome[f.rsplit("/", 1)[-1].lower()].append(f)
        self.ns: dict[str, set] = defaultdict(set)
        for f, t in (textos_cs or {}).items():
            for m in _RE_CS_NS.finditer(t):
                self.ns[m.group(1)].add(f)

    def existe(self, rel: str):
        return self.minusc.get(rel.lower())

    def sufixo(self, suf: str, origem: str):
        suf = suf.strip("/")
        nome = suf.rsplit("/", 1)[-1].lower()
        alvo = "/" + suf.lower()
        cands = [f for f in self.por_nome.get(nome, []) if ("/" + f.lower()).endswith(alvo)]
        if not cands:
            return None
        return min(cands, key=lambda f: (-_comum(f, origem), len(f), f))

    def _py_mod(self, origem: str, segs: list[str], base: str | None, prof: int = 2):
        """Ordem determinística (não depende do que está instalado na máquina): pasta relativa; mesma pasta; pacote do
        repositório pela raiz; por sufixo com a pasta no sys.path do arquivo (próprio ou herdado dos módulos do repo
        que ele importa, até `prof` níveis), em raizes_python ou acima dele. Nada do repo casou: import externo."""
        if not segs:
            return None
        caminho = "/".join(segs)
        if base is not None:
            return self.existe(_juntar(base, caminho + ".py")) or self.existe(_juntar(base, caminho + "/__init__.py"))
        d = _dir(origem)
        achado = self.existe(_juntar(d, caminho + ".py")) or self.existe(_juntar(d, caminho + "/__init__.py"))
        if achado:   # mesma pasta (script rodado da própria pasta)
            return achado
        if segs[0] in _STDLIB:
            return None
        achado = self.existe(caminho + ".py") or self.existe(caminho + "/__init__.py")
        if achado:   # pacote do próprio repositório pela raiz
            return achado
        for p in sorted({0, prof}):   # primeiro só o sys.path do próprio arquivo; depois o herdado
            achado = self._por_sys_path(origem, caminho, *self._contexto(origem, p))
            if achado:
                return achado
        return None

    def _por_sys_path(self, origem: str, caminho: str, nomes: frozenset, pastas: frozenset):
        for suf in (caminho + ".py", caminho + "/__init__.py"):
            nome = suf.rsplit("/", 1)[-1].lower()
            alvo = "/" + suf.lower()
            cands = []
            for f in self.por_nome.get(nome, []):
                if not ("/" + f.lower()).endswith(alvo):
                    continue
                prefixo = f[:len(f) - len(suf)].rstrip("/").lower()
                ultimo = prefixo.rsplit("/", 1)[-1]
                if prefixo in self.raizes_python or (ultimo and ultimo in nomes) \
                        or any((x + "/").startswith(prefixo + "/") for x in pastas):
                    cands.append(f)
            if cands:
                return min(cands, key=lambda f: (-_comum(f, origem), len(f), f))
        return None

    def _contexto(self, f: str, prof: int):
        """(nomes de pasta, pastas de onde se sobe) que o sys.path de f alcança, com o herdado dos módulos do repo
        importados por f até `prof` níveis (cache; ciclos de import não recursam)."""
        chave = (f, prof)
        if chave in self._ctx:
            return self._ctx[chave]
        self._ctx[chave] = (frozenset(), frozenset())   # guarda contra ciclo
        if f not in self.fichas and f not in self._lidos and self.leitor is not None:
            self._lidos.add(f)
            self.registrar_py(f, self.leitor(f) or "")
        proprias = self.fichas.get(f, set())
        nomes = set(proprias - _FICHAS_SOBE)
        pastas = {_dir(f).lower()} if proprias & _FICHAS_SOBE else set()
        if prof > 0:
            for nivel, modulo, nomes_imp in self._refs_py(f):
                segs = [x for x in modulo.split(".") if x]
                base = None
                if nivel:
                    base = _dir(f)
                    for _ in range(nivel - 1):
                        base = _dir(base)
                for alvo in [segs + [n] for n in nomes_imp if n != "*"] + [segs]:
                    m = self._py_mod(f, alvo, base, 0)
                    if m and m != f:
                        n2, p2 = self._contexto(m, prof - 1)
                        nomes |= n2
                        pastas |= p2
        r = (frozenset(nomes), frozenset(pastas))
        self._ctx[chave] = r
        return r

    def _refs_py(self, f: str) -> list:
        if f not in self._refs:
            texto = self.leitor(f) if self.leitor is not None else ""
            self._refs[f] = [a for t, a, _ in extrair_refs(f, texto or "") if t == "py"] if texto else []
        return self._refs[f]

    def registrar_py(self, origem: str, texto: str):
        self._lidos.add(origem)
        if "sys.path" in texto:
            self.fichas[origem] = fichas_sys_path(texto)
        self._ctx = {k: v for k, v in self._ctx.items() if k[0] != origem} if self._ctx else self._ctx

    def resolver(self, origem: str, tipo: str, alvo) -> list[str]:
        if tipo == "py":
            nivel, modulo, nomes = alvo
            segs = [s for s in modulo.split(".") if s]
            base = None
            if nivel:
                base = _dir(origem)
                for _ in range(nivel - 1):
                    base = _dir(base)
            out = []
            for nome in nomes:
                if nome != "*":
                    sub = self._py_mod(origem, segs + [nome], base)
                    if sub:
                        out.append(sub)
            if not out:
                if segs:
                    m = self._py_mod(origem, segs, base)
                    if m:
                        out.append(m)
                elif base is not None:
                    m = self.existe(_juntar(base, "__init__.py"))
                    if m:
                        out.append(m)
            return out
        if tipo == "inc":
            r = self.existe(_juntar(_dir(origem), alvo)) or self.sufixo(alvo, origem)
            return [r] if r else []
        if tipo == "js":
            if not alvo.startswith("."):
                return []
            b = _juntar(_dir(origem), alvo)
            cands = [b] + [b + e for e in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts", ".json")] \
                + [b + "/index" + e for e in (".ts", ".tsx", ".js", ".jsx", ".mjs")]
            if b.endswith(".js"):
                cands += [b[:-3] + ".ts", b[:-3] + ".tsx"]
            for c in cands:
                r = self.existe(c)
                if r:
                    return [r]
            return []
        if tipo == "cs":
            return sorted(f for f in self.ns.get(alvo, ()) if f != origem)
        if tipo == "sh":
            s = posix(alvo)
            partes = s.split("/")
            limpo = []
            for p in reversed(partes):
                if not re.fullmatch(r"[\w.\-]+", p) or p in (".", ".."):
                    break
                limpo.append(p)
            limpo.reverse()
            if not limpo:
                return []
            suf = "/".join(limpo)
            r = self.existe(_juntar(_dir(origem), suf)) or self.sufixo(suf, origem)
            return [r] if r and r != origem else []
        return []


_RE_SIMBOLOS = {
    "py": [re.compile(r"^[ \t]*(?:async[ \t]+)?(?:def|class)[ \t]+([A-Za-z_]\w*)", re.M)],
    "c": [re.compile(r"\b(?:class|struct|enum[ \t]+class|enum|namespace|union)[ \t]+(?:[A-Z0-9_]+_API[ \t]+)?([A-Za-z_]\w*)"),
          re.compile(r"^(?:[\w:<>,*&]+[ \t]+)*?[*&]?([A-Za-z_]\w*::~?[A-Za-z_]\w*)[ \t]*\(", re.M),
          re.compile(r"^[ \t]*#[ \t]*define[ \t]+([A-Za-z_]\w*)", re.M),
          re.compile(r"\bDECLARE_\w*DELEGATE\w*\(\s*([A-Za-z_]\w*)")],
    "js": [re.compile(r"\b(?:function\*?|class|interface|type|enum)[ \t]+([A-Za-z_$][\w$]*)"),
           re.compile(r"\bexport[ \t]+(?:default[ \t]+)?(?:async[ \t]+)?(?:const|let|var)[ \t]+([A-Za-z_$][\w$]*)")],
    "cs": [re.compile(r"\b(?:class|struct|interface|enum|record)[ \t]+([A-Za-z_]\w*)"),
           re.compile(r"\b(?:public|private|protected|internal)[\w \t<>\[\],?]*?[ \t]([A-Za-z_]\w*)[ \t]*\(")],
    "sh": [re.compile(r"^[ \t]*function[ \t]+([\w\-]+)", re.M | re.I),
           re.compile(r"^[ \t]*([\w\-]+)[ \t]*\(\)[ \t]*\{", re.M)],
}
_PALAVRAS_C = {"if", "for", "while", "switch", "return", "sizeof", "UCLASS", "USTRUCT", "UENUM", "UFUNCTION",
               "UPROPERTY", "GENERATED_BODY", "TEXT", "check", "ensure"}


def simbolos(rel: str, texto: str) -> list[tuple[str, int]]:
    ext = os.path.splitext(rel)[1].lower()
    ling = "py" if ext in EXT_PY else "c" if ext in EXT_C else "js" if ext in EXT_JS else "cs" if ext in EXT_CS \
        else "sh" if ext in EXT_SH else None
    if ling is None:
        return []
    vistos, out = set(), []
    for rx in _RE_SIMBOLOS[ling]:
        for m in rx.finditer(texto):
            nome = m.group(1)
            if nome in _PALAVRAS_C or nome in vistos:
                continue
            vistos.add(nome)
            out.append((nome, _linha(texto, m.start())))
            if "::" in nome:
                curto = nome.split("::")[-1]
                if curto not in vistos:
                    vistos.add(curto)
                    out.append((curto, _linha(texto, m.start())))
    return out


class Analise:
    """Arquivos cobertos, donos e arestas reais (arquivo->arquivo e sistema->sistema)."""

    def __init__(self, proj: Projeto, g: Grafo):
        self.proj, self.g, self.repo = proj, g, proj.repo
        self.arquivos = arquivos_cobertos(g, self.repo, proj.config)
        self.donos = Donos([n for n in g.sistemas.values()])
        self.dono: dict[str, str | None] = {}
        for f in self.arquivos:
            d = self.donos.dono(f)
            self.dono[f] = d[0] if d else None
        self._textos: dict[str, str] = {}
        self._arestas = None
        self._sis = None
        self._res = None
        self._pastas = None

    def texto(self, rel: str) -> str:
        if rel not in self._textos:
            self._textos[rel] = self.repo.ler(rel)
        return self._textos[rel]

    def dono_de(self, rel: str):
        if rel in self.dono:
            return self.dono[rel]
        d = self.donos.dono(rel)
        return d[0] if d else None

    def resolvedor(self, analisaveis=None) -> "Resolvedor":
        """Resolvedor de imports (um por análise)."""
        if self._res is None:
            if analisaveis is None:
                analisaveis = [f for f in self.arquivos if os.path.splitext(f)[1].lower() in EXTS_ANALISE]
            alvos = [f for f in self.repo.todos() if os.path.splitext(f)[1].lower() in EXTS_ANALISE]
            textos_cs = {f: self.texto(f) for f in analisaveis if f.lower().endswith(".cs")}
            self._res = Resolvedor(alvos, textos_cs, self.proj.raiz, self.proj.config.get("raizes_python"), self.texto)
            for f in analisaveis:
                if os.path.splitext(f)[1].lower() in EXT_PY:
                    self._res.registrar_py(f, self.texto(f))
        return self._res

    def contagem_pastas(self):
        """(pasta -> {dono: n} dos arquivos diretos, pasta -> {dono: n} recursivo), uma vez por análise."""
        if self._pastas is None:
            diretos, recursivos = defaultdict(lambda: defaultdict(int)), defaultdict(lambda: defaultdict(int))
            for f in self.repo.todos():
                s = self.dono_de(f)
                if not s:
                    continue
                d = _dir(f)
                diretos[d][s] += 1
                while True:
                    recursivos[d][s] += 1
                    if not d:
                        break
                    d = _dir(d)
            self._pastas = (diretos, recursivos)
        return self._pastas

    @property
    def arestas_arquivo(self) -> list[tuple]:
        """(origem, destino, tipo, linha), sem repetição de (origem, destino)."""
        if self._arestas is None:
            analisaveis = [f for f in self.arquivos if os.path.splitext(f)[1].lower() in EXTS_ANALISE]
            alvos = [f for f in self.repo.todos() if os.path.splitext(f)[1].lower() in EXTS_ANALISE]
            res = self.resolvedor(analisaveis)
            vistos, out = set(), []
            refs = {f: extrair_refs(f, self.texto(f)) for f in analisaveis}
            for f, lst in refs.items():   # o resolvedor reaproveita (sys.path herdado) sem reler/reanalisar
                res._refs[f] = [a for t, a, _ in lst if t == "py"]
            for f in analisaveis:
                for tipo, alvo, ln in refs[f]:
                    for d in res.resolver(f, tipo, alvo):
                        if d != f and (f, d) not in vistos:
                            vistos.add((f, d))
                            out.append((f, d, tipo, ln))
            self._arestas = out
        return self._arestas

    @property
    def arestas_sistema(self) -> dict[tuple, list]:
        """(a, b) -> [(origem, linha, destino, tipo)]"""
        if self._sis is None:
            sis = defaultdict(list)
            for o, d, tipo, ln in self.arestas_arquivo:
                a, b = self.dono_de(o), self.dono_de(d)
                if a and b and a != b:
                    sis[(a, b)].append((o, ln, d, tipo))
            for lst in sis.values():
                lst.sort(key=lambda e: (e[3] == "sh", e[0], e[1]))   # import/include antes de referência em script
            self._sis = dict(sorted(sis.items()))
        return self._sis

    def classe(self, a: str, b: str) -> str:
        if b in self.g.deps(a):
            return "declarada"
        if (a, b) in self.g.pares_evento():
            return "evento"
        return "nao_declarada"

    def arquivos_de(self, sid: str) -> list[str]:
        return [f for f in self.arquivos if self.dono.get(f) == sid]


# ===================================================================================================== validate


class Relatorio:
    def __init__(self):
        self.erros: list[dict] = []
        self.avisos: list[dict] = []
        self.info: dict = {}
        self._vistos: set = set()

    def _add(self, lista, codigo, msg, **extra):
        chave = (id(lista), codigo, msg)
        if chave not in self._vistos:
            self._vistos.add(chave)
            lista.append({"codigo": codigo, "msg": msg, **extra})

    def erro(self, codigo, msg, **extra):
        self._add(self.erros, codigo, msg, **extra)

    def aviso(self, codigo, msg, **extra):
        self._add(self.avisos, codigo, msg, **extra)


def _evid(lst, n=1) -> str:
    partes = [f"{o}:{ln} -> {d}" for o, ln, d, _ in lst[:n]]
    extra = f" (+{len(lst) - n})" if len(lst) > n else ""
    return "; ".join(partes) + extra


def _ciclos_scc(arestas: dict[str, set]) -> list[list[str]]:
    """Componentes fortemente conexos com mais de um nó (Tarjan iterativo), ordenados."""
    indice, baixo, pilha, na_pilha, out = {}, {}, [], set(), []
    cont = [0]
    for raiz in sorted(arestas):
        if raiz in indice:
            continue
        trabalho = [(raiz, iter(sorted(arestas.get(raiz, ()))))]
        indice[raiz] = baixo[raiz] = cont[0]
        cont[0] += 1
        pilha.append(raiz)
        na_pilha.add(raiz)
        while trabalho:
            v, it = trabalho[-1]
            avancou = False
            for w in it:
                if w not in indice:
                    indice[w] = baixo[w] = cont[0]
                    cont[0] += 1
                    pilha.append(w)
                    na_pilha.add(w)
                    trabalho.append((w, iter(sorted(arestas.get(w, ())))))
                    avancou = True
                    break
                if w in na_pilha:
                    baixo[v] = min(baixo[v], indice[w])
            if avancou:
                continue
            trabalho.pop()
            if trabalho:
                baixo[trabalho[-1][0]] = min(baixo[trabalho[-1][0]], baixo[v])
            if baixo[v] == indice[v]:
                comp = []
                while True:
                    w = pilha.pop()
                    na_pilha.discard(w)
                    comp.append(w)
                    if w == v:
                        break
                if len(comp) > 1:
                    out.append(sorted(comp))
    return sorted(out)


def _um_ciclo(comp: list[str], arestas: dict[str, set]) -> list[str]:
    membros = set(comp)
    ini = comp[0]
    # BFS do início até voltar a ele (menor ciclo que passa por ini)
    anterior = {ini: None}
    fila = [ini]
    while fila:
        v = fila.pop(0)
        for w in sorted(arestas.get(v, ())):
            if w not in membros:
                continue
            if w == ini:
                cam = [v]
                while anterior[cam[-1]] is not None:
                    cam.append(anterior[cam[-1]])
                cam.reverse()
                return cam + [ini]
            if w not in anterior:
                anterior[w] = v
                fila.append(w)
    return comp + [ini]


def _ciclos_declarados(itens: dict[str, list[str]]) -> list[list[str]]:
    arestas = {a: {b for b in bs if b in itens} for a, bs in itens.items()}
    return [_um_ciclo(c, arestas) for c in _ciclos_scc(arestas)]


def validar(proj: Projeto, base: str | None = None, com_codigo: bool = True) -> Relatorio:
    rep = Relatorio()
    g = proj.grafo()
    for p in g.problemas:
        rep.erro("leitura", p)
    if not g.dados and g.problemas:
        return rep
    mudados = None
    grafo_mudou = True
    if base:
        mudados = set(proj.repo.mudados(base))
        fontes_rel = set()
        for f in g.fontes:
            try:
                fontes_rel.add(Path(f).resolve().relative_to(proj.raiz).as_posix())
            except ValueError:
                pass
        grafo_mudou = bool((fontes_rel | set(ARQUIVOS_CONFIG)) & mudados)
        rep.info["mudados"] = len(mudados)
        # atalho (o mesmo do hook fim): nada coberto mudou, nem o YAML, nem um path declarado -> nada a validar
        cob = cobertura_efetiva(g, proj.config)
        declarados = [norm_padrao(p).lower() for n in g.sistemas.values() for p in as_list(n.get("paths"))
                      if isinstance(p, str)]
        if not grafo_mudou and not any(coberto_por(cob, m) or any(m.lower() == q or m.lower().startswith(q + "/")
                                                                 for q in declarados) for m in mudados):
            rep.info["atalho"] = "nada coberto mudou"
            return rep
    if grafo_mudou:
        _validar_esquema(g, rep)
    if not com_codigo:
        return rep
    an = Analise(proj, g)
    rep.info["analise"] = an
    _validar_arquivos(proj, g, an, rep, mudados, grafo_mudou)
    _validar_reais(g, an, rep, mudados)
    return rep


def _validar_esquema(g: Grafo, rep: Relatorio):
    vistos: dict[str, str] = {}
    for kind, itens in g.nos.items():
        for i, n in enumerate(itens):
            if not isinstance(n, dict):
                rep.erro("esquema", f"{kind}[{i}]: esperado um mapa")
                continue
            nid = n.get("id", f"<{kind}[{i}] sem id>")
            proposto = kind == "system" and n.get("status") == "proposto"
            for campo in REQUIRED[kind]:
                if campo == "paths" and kind == "system" and n.get("status") == "planned":
                    continue
                if n.get(campo) in (None, "", []):
                    if proposto and campo in ("layer", "description"):
                        rep.aviso("proposto", f"{nid}: sistema proposto sem {campo} (revise)")
                    else:
                        rep.erro("esquema", f"{nid}: campo obrigatório ausente: {campo}")
            if not isinstance(nid, str) or not ID_RE.match(nid):
                rep.erro("id", f"{nid}: id fora do formato <prefixo>.<snake_case>")
            elif not nid.startswith(KINDS[kind]):
                rep.erro("id", f"{nid}: id de {kind} deve começar com '{KINDS[kind]}'")
            for (k, campo), permitidos in ENUMS.items():
                if k == kind and campo in n and (not isinstance(n[campo], str) or n[campo] not in permitidos):
                    rep.erro("enum", f"{nid}: {campo}='{n[campo]}' inválido; use {sorted(permitidos)}")
            if proposto:
                rep.aviso("proposto", f"{nid}: status proposto (gerado pelo init) — revise e troque para active")
            if kind == "system" and n.get("summary") and len(str(n["summary"])) > 200:
                rep.aviso("summary", f"{nid}: summary com {len(str(n['summary']))} caracteres (máximo 200)")
            if isinstance(nid, str):
                if nid in vistos:
                    rep.erro("duplicado", f"DUPLICIDADE de id: '{nid}' aparece em {vistos[nid]} e {kind}")
                else:
                    vistos[nid] = kind
            for (k, campo), aceitos in REFS.items():
                if k != kind:
                    continue
                for ref in as_list(n.get(campo)):
                    alvo = g.indice.get(ref) if isinstance(ref, str) else None
                    if alvo is None:
                        rep.erro("ref", f"{nid}.{campo}: referência inexistente '{ref}'")
                    elif alvo[0] not in aceitos:
                        rep.erro("ref", f"{nid}.{campo}: '{ref}' é {alvo[0]}, esperado {sorted(aceitos)}")
                    elif ref == nid:
                        rep.erro("ref", f"{nid}.{campo}: nó referencia a si mesmo")
    # símbolos e paths repetidos
    donos_sim: dict[str, str] = {}
    for kind, campo in (("system", "classes"), ("event", "symbol")):
        for n in g.nos[kind]:
            if isinstance(n, dict):
                for s in as_list(n.get(campo)):
                    if s in donos_sim and donos_sim[s] != n.get("id"):
                        rep.erro("duplicado", f"DUPLICIDADE de símbolo '{s}': {donos_sim[s]} e {n.get('id')}")
                    donos_sim.setdefault(s, n.get("id"))
    for q, sids in Donos(list(g.sistemas.values())).conflitos():
        rep.erro("dono_conflito", f"DUPLICIDADE de dono: '{q}' está em {', '.join(sids)}")
    # ciclos declarados
    for kind in ("system", "feature"):
        itens = {nid: [d for d in as_list(n.get("depends_on")) if isinstance(d, str)]
                 for nid, (k, n) in g.indice.items() if k == kind}
        for c in _ciclos_declarados(itens):
            rep.erro("ciclo_declarado", f"ciclo em {kind}.depends_on: " + " -> ".join(c))
    # camadas declaradas
    for sid, n in g.sistemas.items():
        camada = n.get("layer")
        if not camada:
            continue
        if camada not in g.camadas:
            rep.erro("camada", f"{sid}: layer '{camada}' não declarada em layers ({sorted(g.camadas)})")
            continue
        perm = set(as_list((g.camadas[camada] or {}).get("may_depend_on"))) | {camada}
        for d in g.deps(sid):
            dc = g.camada(d)
            if dc and dc not in perm:
                rep.erro("camada_declarada", f"camada violada: {sid} ({camada}) depende de {d} ({dc})")
            if n.get("status") != "deprecated" and g.sistemas.get(d, {}).get("status") == "deprecated":
                rep.aviso("deprecated", f"{sid} depende de sistema deprecated {d}")
    testados = {c for t in g.nos["test"] if isinstance(t, dict) for c in as_list(t.get("covers"))}
    for sid, n in g.sistemas.items():
        if n.get("status") == "active" and sid not in testados:
            rep.aviso("sem_teste", f"{sid}: sistema ativo sem teste em tests[].covers")
    for e in g.nos["event"]:
        if isinstance(e, dict) and not as_list(e.get("consumers")) and not as_list(e.get("callee")) \
                and e.get("kind") != "log":
            rep.aviso("evento_sem_consumidor", f"{e.get('id')}: evento sem consumidor")


def _validar_arquivos(proj, g: Grafo, an: Analise, rep: Relatorio, mudados, grafo_mudou):
    raiz, repo = proj.raiz, proj.repo
    todos = repo.todos()
    minusc = repo.minusculo()
    # com --base, também os paths de arquivos mudados (apagado/renomeado deixa o path quebrado sem mexer no YAML)
    mud_l = {m.lower() for m in mudados} if mudados is not None else set()

    def afetado(q):
        ql = q.lower()
        return ql in mud_l or any(m.startswith(ql + "/") for m in mud_l)

    for kind in ("system", "data_source", "test"):
        for n in g.nos[kind]:
            if not isinstance(n, dict) or n.get("external"):
                continue
            for p in as_list(n.get("paths")):
                if not isinstance(p, str):
                    continue
                q = norm_padrao(p)
                if not grafo_mudou and not afetado(q):
                    continue
                if eh_glob(q):
                    glob_re(q)
                    if q in GLOBS_INVALIDOS:
                        rep.erro("padrao_invalido", f"{n.get('id')}: padrão inválido '{p}' (confira os colchetes)")
                    elif not any(sob_raiz(f, q) for f in todos):
                        rep.aviso("padrao_vazio", f"{n.get('id')}: padrão '{p}' não casa com nenhum arquivo")
                elif not (raiz / q).exists() and q.lower() not in minusc:
                    rep.erro("caminho_inexistente", f"{n.get('id')}: caminho inexistente '{p}'")
    if grafo_mudou:
        for r in as_list(g.cobertura.get("roots")):
            q = norm_padrao(r)
            if q and not eh_glob(q) and not (raiz / q).exists():
                rep.erro("raiz_inexistente", f"coverage.roots: '{r}' não existe")
        for s, q, s2, q2 in Donos(list(g.sistemas.values())).aninhados():
            rep.aviso("aninhado", f"'{q2}' ({s2}) fica dentro de '{q}' ({s}); vale o mais específico ({s2})")
        for nid, (kind, n) in sorted(g.indice.items()):
            for d in as_list(n.get("docs")):
                if isinstance(d, str) and not (raiz / posix(d)).is_file():
                    rep.erro("doc_inexistente", f"{nid}.docs: documento inexistente '{d}'")
        # classes declaradas precisam existir no código C/C++ do dono
        for sid, n in g.sistemas.items():
            classes = as_list(n.get("classes"))
            if not classes:
                continue
            codigo = "\n".join(an.texto(f) for f in an.arquivos_de(sid) if os.path.splitext(f)[1].lower() in EXT_C)
            if not codigo:
                continue
            for c in classes:
                rx = re.compile(rf"\b(?:class|struct|enum\s+class|enum|namespace)\s+(?:\w+_API\s+)?{re.escape(str(c))}\b")
                if not rx.search(codigo):
                    rep.erro("classe", f"{sid}.classes: '{c}' não está declarada nos arquivos do sistema")
    for f in an.arquivos:
        if mudados is not None and f not in mudados:
            continue
        if an.dono.get(f) is None:
            sug = sugerir(proj, g, an, f)
            dica = f"; sugestão: {sug[0]['sistema']}" if sug else ""
            rep.erro("orfao", f"código ÓRFÃO sem sistema dono: {f}{dica}", arquivo=f)


def _validar_reais(g: Grafo, an: Analise, rep: Relatorio, mudados):
    sis = an.arestas_sistema

    def filtrar(lst):
        return lst if mudados is None else [e for e in lst if e[0] in mudados]

    estrutural: dict[str, set] = defaultdict(set)
    nao_decl = 0
    for (a, b), lst in sis.items():
        classe = an.classe(a, b)
        if classe != "evento":
            estrutural[a].add(b)
        ev = filtrar(lst)
        if not ev:
            continue
        if classe == "nao_declarada":
            nao_decl += 1
            inverso = " (inverso de uma dependência declarada)" if a in g.deps(b) else ""
            rep.aviso("aresta_nao_declarada",
                      f"aresta real não declarada: {a} -> {b}{inverso} ({len(lst)} ref.; {_evid(ev)})",
                      de=a, para=b, evidencias=[f"{o}:{ln} -> {d}" for o, ln, d, _ in ev[:5]])
        if classe != "evento":
            ca, cb = g.camada(a), g.camada(b)
            if ca in g.camadas and cb:
                perm = set(as_list((g.camadas[ca] or {}).get("may_depend_on"))) | {ca}
                if cb not in perm:
                    rep.erro("camada_real", f"camada violada no código: {a} ({ca}) -> {b} ({cb}): {_evid(ev, 2)}",
                             de=a, para=b, evidencias=[f"{o}:{ln} -> {d}" for o, ln, d, _ in ev[:5]])
    for comp in _ciclos_scc(estrutural):
        ciclo = _um_ciclo(comp, estrutural)
        pares = list(zip(ciclo, ciclo[1:]))
        if mudados is not None and not any(filtrar(sis.get(p, [])) for p in pares):
            continue
        prova = "; ".join(f"{a}->{b}: {_evid(sis.get((a, b), []))}" for a, b in pares)
        extra = f" (componente com {len(comp)} sistemas: {', '.join(comp)})" if len(comp) > len(ciclo) - 1 else ""
        rep.erro("ciclo_real", "ciclo real no código: " + " -> ".join(ciclo) + extra + f" [{prova}]", sistemas=comp)
    if mudados is None:
        com_codigo = {an.dono[f] for f in an.arquivos if an.dono.get(f)
                      and os.path.splitext(f)[1].lower() in EXTS_ANALISE}
        for a, n in sorted(g.sistemas.items()):
            for b in g.deps(a):
                if (a, b) not in sis and a in com_codigo and b in com_codigo:
                    rep.aviso("dependencia_sem_uso",
                              f"dependência declarada sem uso no código: {a} -> {b} (pode ser por dados/arquivo; confira)",
                              de=a, para=b)
    rep.info["arestas_reais"] = len(sis)
    rep.info["nao_declaradas"] = nao_decl


def imprimir_relatorio(rep: Relatorio, g: Grafo | None, strict: bool, como_json: bool) -> int:
    reprovado = bool(rep.erros) or (strict and bool(rep.avisos))
    if como_json:
        info = {k: v for k, v in rep.info.items() if k != "analise"}
        print(json.dumps({"ok": not reprovado, "erros": rep.erros, "avisos": rep.avisos, "info": info,
                          "contagens": {k: len(v) for k, v in g.nos.items()} if g else {}},
                         ensure_ascii=False, indent=1, sort_keys=True))
    else:
        for a in rep.avisos:
            print(f"AVISO [{a['codigo']}] {a['msg']}")
        for e in rep.erros:
            print(f"ERRO  [{e['codigo']}] {e['msg']}")
        cont = ", ".join(f"{len(v)} {k}" for k, v in g.nos.items()) if g else ""
        extra = ""
        if "arestas_reais" in rep.info:
            extra = f"; arestas reais entre sistemas: {rep.info['arestas_reais']} ({rep.info['nao_declaradas']} não declaradas)"
        print(f"{'REPROVADO' if reprovado else 'OK'}: {len(rep.erros)} erro(s), {len(rep.avisos)} aviso(s) — {cont}{extra}")
    return 1 if reprovado else 0


# ===================================================================================================== owner / suggest


def sugerir(proj: Projeto, g: Grafo, an: Analise, rel: str, max_itens=3) -> list[dict]:
    """Sugestões de dono: vizinhos da mesma pasta (subindo até achar) + donos dos imports do arquivo."""
    pontos: dict[str, float] = defaultdict(float)
    motivos: dict[str, list] = defaultdict(list)
    diretos, recursivos = an.contagem_pastas()
    proprio = an.dono_de(rel) if rel.lower() in proj.repo.minusculo() else None
    d = _dir(rel)
    nivel = 0
    while True:
        cont = dict((diretos if nivel == 0 else recursivos).get(d, {}))
        if proprio and proprio in cont and (nivel > 0 or _dir(rel) == d):
            cont[proprio] -= 1
            if cont[proprio] <= 0:
                del cont[proprio]
        if cont:
            total = sum(cont.values())
            for s, c in cont.items():
                pontos[s] += 2.0 * c / total / (1 + nivel)
                motivos[s].append(f"{c} de {total} arquivo(s) vizinhos em {d or '.'}/")
            break
        if not d:
            break
        d = _dir(d)
        nivel += 1
    texto = an.texto(rel)
    if texto:
        res = an.resolvedor()
        if os.path.splitext(rel)[1].lower() in EXT_PY:
            res.registrar_py(rel, texto)
        cont = defaultdict(int)
        for tipo, alvo, _ in extrair_refs(rel, texto):
            for dst in res.resolver(rel, tipo, alvo):
                s = an.dono_de(dst)
                if s:
                    cont[s] += 1
        total = sum(cont.values())
        for s, c in cont.items():
            pontos[s] += 1.5 * c / total
            motivos[s].append(f"{c} de {total} import(s)")
    ordem = sorted(pontos.items(), key=lambda x: (-x[1], x[0]))[:max_itens]
    return [{"sistema": s, "pontos": round(p, 3), "motivos": motivos[s]} for s, p in ordem]


# ===================================================================================================== slice


def compactar_paths(paths, minimo=3) -> list[str]:
    """Arquivos com o mesmo pai (>= minimo) viram 'pasta/ (N)'."""
    ps = [norm_padrao(p) for p in as_list(paths) if isinstance(p, str)]
    grupos = defaultdict(list)
    for p in ps:
        if not eh_glob(p):
            grupos[_dir(p)].append(p)
    out, emitidos = [], set()
    for p in ps:
        d = _dir(p)
        if not eh_glob(p) and len(grupos[d]) >= minimo and d:
            if d not in emitidos:
                emitidos.add(d)
                out.append(f"{d}/ ({len(grupos[d])})")
        else:
            out.append(p)
    return out


def _lista_curta(itens, n) -> str:
    itens = list(itens)
    return ", ".join(itens[:n]) + (f" (+{len(itens) - n})" if len(itens) > n else "")


def recorte(g: Grafo, sid: str, orcamento: int, an: Analise | None = None) -> dict:
    n = g.sistemas[sid]
    limite = orcamento * CARACTERES_POR_TOKEN
    secoes: list[tuple[str, list[str]]] = []
    cab = f"# {sid} — {n.get('name', '')} [{n.get('layer') or 'sem camada'}, {n.get('status', '?')}]"
    secoes.append(("cabecalho", [cab, g.resumo(sid)]))
    secoes.append(("paths", ["paths: " + _lista_curta(compactar_paths(n.get("paths")), 8)]))
    for campo, rot in (("entrypoints", "entradas"), ("invariants", "invariantes"), ("pitfalls", "armadilhas"),
                       ("lessons", "lições"), ("extension_points", "pontos de extensão")):
        if n.get(campo):
            secoes.append((campo, [f"{rot}: " + "; ".join(str(x) for x in as_list(n[campo]))]))
    deps = g.deps(sid)
    usados = g.usado_por(sid)
    nome = {s: g.sistemas[s].get("name", "") for s in g.sistemas}
    viz = []
    if deps:
        viz.append("depende de: " + "; ".join(f"{d} ({nome.get(d, '?')})" for d in deps))
    if usados:
        viz.append("usado por: " + "; ".join(f"{d} ({nome.get(d, '?')})" for d in usados))
    if an is not None:
        reais_out = sorted({b for (a, b) in an.arestas_sistema if a == sid and an.classe(a, b) == "nao_declarada"})
        reais_in = sorted({a for (a, b) in an.arestas_sistema if b == sid and an.classe(a, b) == "nao_declarada"})
        if reais_out:
            viz.append("importa sem declarar: " + ", ".join(reais_out))
        if reais_in:
            viz.append("importado sem declarar por: " + ", ".join(reais_in))
    if viz:
        secoes.append(("vizinhos", viz))
    prod, cons = g.eventos(sid)
    ev = []
    for e in prod:
        ev.append(f"produz {e.get('id')} ({e.get('kind', '?')}) -> {', '.join(as_list(e.get('consumers')) + as_list(e.get('callee'))) or '—'}")
    for e in cons:
        ev.append(f"consome {e.get('id')} ({e.get('kind', '?')}) de {e.get('producer') or ', '.join(as_list(e.get('caller'))) or '?'}")
    if ev:
        secoes.append(("eventos", ev))
    ts = []
    if n.get("test_cmd"):
        ts.append(f"rodar: {n['test_cmd']}")
    for t in g.testes(sid):
        cmd = t.get("command")
        ts.append(f"{t.get('id')}: {cmd or _lista_curta([norm_padrao(p) for p in as_list(t.get('paths'))], 2)}")
    if ts:
        secoes.append(("testes", ["testes: " + ts[0]] + ["  " + x for x in ts[1:]]))
    adrs = g.adrs(sid)
    if adrs:
        secoes.append(("adrs", ["ADRs: " + "; ".join(f"{a.get('id')} {a.get('title', '')}".strip() for a in adrs)]))
    linhas, usados_chars, cortadas = [], 0, []
    for nome_sec, ls in secoes:
        for ln in ls:
            if usados_chars + len(ln) + 1 <= limite:
                linhas.append(ln)
                usados_chars += len(ln) + 1
            else:
                resta = limite - usados_chars - 2
                if resta > 40:
                    linhas.append(ln[:resta - 1] + "…")
                    usados_chars += resta + 1
                cortadas.append(nome_sec)
                break
    if cortadas:
        aviso = f"(cortado pelo orçamento: {', '.join(dict.fromkeys(cortadas))})"
        if usados_chars + len(aviso) + 1 > limite and linhas:
            linhas[-1] = linhas[-1][:max(0, len(linhas[-1]) - len(aviso) - 2)] + "…"
        linhas.append(aviso)
    texto = "\n".join(linhas)
    if len(texto) > limite:   # orçamento minúsculo: corta seco
        texto = texto[:max(0, limite - 1)] + "…"
    return {"sistema": sid, "texto": texto, "tokens": tokens_aprox(texto), "orcamento": orcamento,
            "cortado": sorted(set(cortadas))}


def modelo_sistemas(g: Grafo) -> dict:
    """Modelo mínimo por sistema (o que os hooks precisam), serializável em JSON."""
    out = {}
    for sid, n in sorted(g.sistemas.items()):
        out[sid] = {
            "nome": n.get("name", ""), "camada": str(n.get("layer") or ""), "resumo": g.resumo(sid, 160),
            "paths": [p for p in as_list(n.get("paths")) if isinstance(p, str)],
            "deps": g.deps(sid), "usado_por": g.usado_por(sid),
            "testes": ([str(n["test_cmd"])] if n.get("test_cmd") else [])
            + [f"{t.get('id')} ({t['command']})" if t.get("command") else str(t.get("id")) for t in g.testes(sid)],
            "adrs": [str(a.get("id")) for a in g.adrs(sid)],
            "invariantes": [str(x) for x in as_list(n.get("invariants"))],
        }
    return out


def modelo_hook(proj: Projeto, cache_dir: Path | None = None) -> dict:
    """Modelo dos hooks com cache na pasta temporária (refeito quando o conteúdo do grafo muda)."""
    import tempfile  # noqa: PLC0415
    pasta = Path(cache_dir or os.environ.get("GRAFO_ESTADO") or Path(tempfile.gettempdir()) / "grafo-claude")
    chave = hashlib.sha1(posix(proj.grafo_arq).lower().encode("utf-8")).hexdigest()[:16]
    arq = pasta / f"modelo-{chave}.json"
    try:
        m = json.loads(arq.read_text(encoding="utf-8"))
        if (m.get("versao"), m.get("formato")) == (VERSAO, FORMATO_MODELO) \
                and m.get("assinatura") == sha1_arquivos(m.get("fontes", [])):
            return m
    except (OSError, ValueError, TypeError):
        pass
    g = proj.grafo()
    fontes = [posix(f) for f in g.fontes] + [posix(proj.raiz / n) for n in ARQUIVOS_CONFIG]
    m = {"versao": VERSAO, "formato": FORMATO_MODELO, "fontes": fontes, "assinatura": sha1_arquivos(fontes),
         "grafo": posix(proj.grafo_arq), "sistemas": modelo_sistemas(g),
         "cobertura": cobertura_efetiva(g, proj.config)}
    try:
        pasta.mkdir(parents=True, exist_ok=True)
        tmp = arq.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, arq)
    except OSError:
        pass
    return m


def cobertura_efetiva(g: Grafo, cfg: dict) -> dict:
    """roots/extensions/ignore do grafo, com a configuração como reserva (o mesmo que arquivos_cobertos usa)."""
    return {"roots": as_list(g.cobertura.get("roots")) or as_list(cfg.get("raizes")),
            "extensions": as_list(g.cobertura.get("extensions")) or as_list(cfg.get("extensoes")),
            "ignore": as_list(g.cobertura.get("ignore")) + as_list(cfg.get("ignorar"))}


def coberto_por(cobertura: dict, rel: str) -> bool:
    """O arquivo entra na cobertura (raízes + extensões - ignorados)?"""
    exts = {e.lower() if str(e).startswith(".") else "." + str(e).lower()
            for e in (as_list(cobertura.get("extensions")) or sorted(EXTS_PADRAO))}
    if os.path.splitext(rel)[1].lower() not in exts:
        return False
    raizes = as_list(cobertura.get("roots")) or [""]
    if not any(sob_raiz(rel, r) for r in raizes):
        return False
    return not any(glob_re(norm_padrao(p)).match(rel) or sob_raiz(rel, p) for p in as_list(cobertura.get("ignore")) if p)


def contexto_curto(sis: dict, sid: str, arquivo: str, limite=700) -> str:
    """Contexto que o hook PreToolUse injeta na 1ª edição de um sistema na sessão (sis = modelo_sistemas()[sid])."""
    partes = [f"[grafo] {arquivo} é do sistema {sid} ({sis.get('nome', '')}; camada {sis.get('camada') or '?'})."]
    if sis.get("resumo"):
        partes.append(sis["resumo"])
    if sis.get("deps"):
        partes.append("Depende de: " + _lista_curta(sis["deps"], 6) + " (import de outro sistema exige depends_on).")
    if sis.get("usado_por"):
        partes.append("Usado por: " + _lista_curta(sis["usado_por"], 6) + ".")
    if sis.get("invariantes"):
        partes.append("Invariantes: " + "; ".join(sis["invariantes"][:3]) + ".")
    if sis.get("testes"):
        partes.append("Testes: " + _lista_curta(sis["testes"], 3) + ".")
    if sis.get("adrs"):
        partes.append("ADRs: " + _lista_curta(sis["adrs"], 3) + ".")
    partes.append(f"Mais: grafo.py slice {sid}")
    t = " ".join(partes)
    return t if len(t) <= limite else t[:limite - 1] + "…"


# ===================================================================================================== impact


def impacto(proj: Projeto, g: Grafo, an: Analise, arquivos: list[str]) -> dict:
    arqs = [normalizar_caminho(a, proj.raiz, proj.repo, an.donos) for a in arquivos]
    arqs = sorted(dict.fromkeys(a for a in arqs if a))
    tocados: dict[str, list] = defaultdict(list)
    sem_dono = []
    for a in arqs:
        s = an.dono_de(a)
        if s:
            tocados[s].append(a)
        elif a in an.arquivos or os.path.splitext(a)[1].lower() in EXTS_PADRAO:
            sem_dono.append(a)
    rev: dict[str, set] = defaultdict(set)
    for a, n in g.sistemas.items():
        for b in g.deps(a):
            rev[b].add(a)
    for (a, b) in an.arestas_sistema:
        rev[b].add(a)
    dist = {s: 0 for s in tocados}
    fila = sorted(tocados)
    while fila:
        v = fila.pop(0)
        for w in sorted(rev.get(v, ())):
            if w not in dist:
                dist[w] = dist[v] + 1
                fila.append(w)
    impactados = {s: d for s, d in dist.items() if d > 0}
    conj = set(dist)
    testes = []
    mudados = set(arqs)
    for t in g.nos["test"]:
        if not isinstance(t, dict):
            continue
        cobre = set(as_list(t.get("covers")))
        tps = [norm_padrao(p) for p in as_list(t.get("paths")) if isinstance(p, str)]
        toca_arquivo = any(m == p or m.startswith(p + "/") for m in mudados for p in tps)
        if cobre & set(tocados) or toca_arquivo:
            prio = 1
        elif cobre & conj:
            prio = 2
        else:
            continue
        testes.append({"id": t.get("id"), "prioridade": prio, "comando": t.get("command"), "paths": tps})
    for s in sorted(tocados):
        if g.sistemas.get(s, {}).get("test_cmd"):
            testes.append({"id": f"{s}.test_cmd", "prioridade": 1, "comando": g.sistemas[s]["test_cmd"], "paths": []})
    testes.sort(key=lambda t: (t["prioridade"], str(t["id"])))
    adrs = {}
    for s in sorted(tocados):
        for a in g.adrs(s):
            adrs[a.get("id")] = a.get("title", "")
    reverso = defaultdict(set)
    for o, d, _, _ in an.arestas_arquivo:
        reverso[d].add(o)
    provaveis = sorted({o for a in arqs for o in reverso.get(a, ()) if o not in mudados})
    return {"arquivos": arqs, "tocados": {s: v for s, v in sorted(tocados.items())},
            "impactados": dict(sorted(impactados.items(), key=lambda x: (x[1], x[0]))),
            "sem_dono": sem_dono, "testes": testes, "adrs": adrs, "arquivos_provaveis": provaveis}


# ===================================================================================================== find


def buscar(proj: Projeto, g: Grafo, an: Analise, consulta: str) -> dict:
    q = consulta.strip()
    qn = norm_txt(q)
    ql = q.lower().replace("\\", "/")
    toks = [t for t in qn.split() if len(t) >= 2] or qn.split()
    por_sis: dict[str, dict] = {}

    def entrada(sid):
        if sid not in por_sis:
            por_sis[sid] = {"sistema": sid, "nome": g.sistemas.get(sid, {}).get("name", ""), "pontos": 0.0,
                            "motivos": [], "arquivos": {}}
        return por_sis[sid]

    def toks_casam(texto_norm: str) -> float:
        if not toks:
            return 0.0
        palavras = set(texto_norm.split())
        radicais = {p[:5] for p in palavras}
        return sum(1 for t in toks if t in palavras or t[:5] in radicais) / len(toks)

    # nós do grafo (sistemas)
    for sid, n in g.sistemas.items():
        e = None
        idn = norm_txt(sid)
        if qn and (qn == idn or qn == norm_txt(sem_prefixo(sid))):
            e = entrada(sid)
            e["pontos"] += 100
            e["motivos"].append("id")
        elif qn and qn in idn:
            e = entrada(sid)
            e["pontos"] += 30
            e["motivos"].append("parte do id")
        else:   # id citado numa frase ("ciclo entre gameplay_data e ..." casa sys.gameplay_data)
            idc = norm_txt(sem_prefixo(sid))
            if len(idc) >= 4 and f" {idc} " in f" {qn} ":   # id de uma palavra ("agents", "locale") pesa menos
                e = entrada(sid)
                e["pontos"] += 40 if " " in idc else 20
                e["motivos"].append("id citado")
        for c in as_list(n.get("classes")):
            if str(c).lower() == ql:
                e = entrada(sid)
                e["pontos"] += 80
                e["motivos"].append(f"classe {c}")
        nome_n = norm_txt(n.get("name", ""))
        if qn and qn == nome_n:
            e = entrada(sid)
            e["pontos"] += 90
            e["motivos"].append("nome")
        texto_n = norm_txt(" ".join(str(n.get(k, "")) for k in ("name", "summary", "description")))
        frac = toks_casam(texto_n)
        if frac >= 0.5:
            e = entrada(sid)
            e["pontos"] += 20 * frac + (10 if qn and qn in texto_n else 0)
            e["motivos"].append(f"descrição ({int(frac * 100)}% das palavras)")
    # arquivos: caminho, símbolos, conteúdo
    analisaveis = [f for f in an.arquivos]
    for f in analisaveis:
        sid = an.dono.get(f)
        if not sid:
            continue
        pts, mot = 0.0, []
        fl = f.lower()
        nome_arq = fl.rsplit("/", 1)[-1]
        stem = nome_arq.rsplit(".", 1)[0]
        if ql == fl or fl.endswith("/" + ql):
            pts, mot = 95, ["caminho"]
        elif ql in (stem, nome_arq):
            pts, mot = 70, ["nome do arquivo"]
        elif len(ql) >= 3 and ql in stem:
            pts, mot = 25, ["parte do nome do arquivo"]
        elif len(ql) >= 3 and ql in fl:
            pts, mot = 10, ["parte do caminho"]
        texto = an.texto(f)
        if len(ql) >= 2 and texto:
            for nome, ln in simbolos(f, texto):
                nl = nome.lower()
                if nl == ql or nl.split("::")[-1] == ql:
                    if 60 > pts:
                        pts = 60
                    mot.append(f"símbolo {nome} (linha {ln})")
                    break
                if len(ql) >= 4 and ql in nl and pts < 20:
                    pts = 20
                    mot.append(f"símbolo {nome} (linha {ln})")
            tl = texto.lower()
            if toks:
                if ql in tl:
                    hits = tl.count(ql)
                    ln = _linha(texto, tl.find(ql))
                    pts += 5 + min(hits, 10) * 0.5
                    mot.append(f"conteúdo ({hits}x; 1ª na linha {ln})")
                elif len(toks) > 1 and all(t in norm_txt(tl) for t in toks):
                    pts += 3
                    mot.append("conteúdo (todas as palavras)")
        if pts > 0:
            e = entrada(sid)
            e["arquivos"][f] = {"pontos": round(pts, 2), "motivos": mot}
    # outros nós (eventos, testes, ADRs, features, fontes)
    outros = []
    for nid, (kind, n) in g.indice.items():
        if kind == "system":
            continue
        campos = " ".join(str(n.get(k, "")) for k in ("name", "title", "description", "summary"))
        sim = [str(s).lower() for s in as_list(n.get("symbol"))]
        pts = 0.0
        if qn == norm_txt(nid) or qn == norm_txt(sem_prefixo(nid)):
            pts = 100
        elif ql and any(ql == s or ql == s.split("::")[-1] for s in sim):
            pts = 80
        else:
            frac = toks_casam(norm_txt(campos + " " + nid))
            if frac >= 0.5:
                pts = 20 * frac + (10 if qn and qn in norm_txt(campos) else 0)
        if pts:
            outros.append({"id": nid, "tipo": kind, "nome": n.get("name") or n.get("title", ""), "pontos": round(pts, 2)})
    for e in por_sis.values():
        arqs = sorted(e["arquivos"].items(), key=lambda x: (-x[1]["pontos"], x[0]))
        e["arquivos"] = [{"arquivo": f, **v} for f, v in arqs]
        if arqs:
            e["pontos"] += arqs[0][1]["pontos"] + 0.1 * sum(v["pontos"] for _, v in arqs[1:])
        e["pontos"] = round(e["pontos"], 2)
    sistemas = sorted(por_sis.values(), key=lambda e: (-e["pontos"], e["sistema"]))
    outros.sort(key=lambda o: (-o["pontos"], o["id"]))
    return {"consulta": consulta, "sistemas": sistemas, "outros": outros}


# ===================================================================================================== drift / index / rules


def metricas(proj: Projeto, g: Grafo, an: Analise, rep: Relatorio | None = None) -> dict:
    total = len(an.arquivos)
    com_dono = sum(1 for f in an.arquivos if an.dono.get(f))
    sis = an.arestas_sistema
    nao_decl = sorted(f"{a}->{b}" for (a, b) in sis if an.classe(a, b) == "nao_declarada")
    com_codigo = {an.dono[f] for f in an.arquivos if an.dono.get(f) and os.path.splitext(f)[1].lower() in EXTS_ANALISE}
    sem_uso = sorted(f"{a}->{b}" for a in g.sistemas for b in g.deps(a)
                     if (a, b) not in sis and a in com_codigo and b in com_codigo)
    if rep is None:
        rep = Relatorio()
        _validar_arquivos(proj, g, an, rep, None, True)
        _validar_reais(g, an, rep, None)
    quebrados = sum(1 for e in rep.erros if e["codigo"] == "caminho_inexistente") + \
        sum(1 for e in rep.avisos if e["codigo"] == "padrao_vazio")
    idade = None
    upd = g.dados.get("updated")
    if upd:
        try:
            idade = (_dt.date.today() - _dt.date.fromisoformat(str(upd)[:10])).days
        except ValueError:
            idade = None
    sem_resumo = sorted(s for s, n in g.sistemas.items()
                        if not n.get("summary") and len(" ".join(str(n.get("description") or "").split())) > 200)
    return {
        "arquivos_cobertos": total, "arquivos_com_dono": com_dono,
        "pct_com_dono": round(100.0 * com_dono / total, 1) if total else 100.0,
        "orfaos": total - com_dono,
        "arestas_reais": len(sis), "arestas_nao_declaradas": len(nao_decl), "nao_declaradas": nao_decl,
        "declaradas_sem_uso": len(sem_uso), "sem_uso": sem_uso,
        "ciclos_reais": sum(1 for e in rep.erros if e["codigo"] == "ciclo_real"),
        "camadas_violadas_reais": sum(1 for e in rep.erros if e["codigo"] == "camada_real"),
        "paths_quebrados": quebrados, "dias_desde_updated": idade,
        "sistemas": len(g.sistemas), "sistemas_sem_descricao_curta": len(sem_resumo), "sem_descricao_curta": sem_resumo,
        "sistemas_propostos": sum(1 for n in g.sistemas.values() if n.get("status") == "proposto"),
    }


def montar_index(proj: Projeto, g: Grafo, an: Analise) -> dict:
    camadas = {c: {"may_depend_on": as_list((v or {}).get("may_depend_on")), "cor": g.cor(c),
                   "descricao": resumo_texto((v or {}).get("description", ""), 120)} for c, v in g.camadas.items()}
    sistemas = {}
    for sid, n in sorted(g.sistemas.items()):
        prod, cons = g.eventos(sid)
        camada = str(n.get("layer") or "")
        sistemas[sid] = {
            "nome": str(n.get("name") or ""), "camada": camada, "status": str(n.get("status") or ""), "cor": g.cor(camada),
            "resumo": g.resumo(sid), "paths": [norm_padrao(p) for p in as_list(n.get("paths")) if isinstance(p, str)],
            "depends_on": g.deps(sid), "usado_por": g.usado_por(sid),
            "eventos_produz": sorted(str(e.get("id")) for e in prod), "eventos_consome": sorted(str(e.get("id")) for e in cons),
            "testes": sorted(str(t.get("id")) for t in g.testes(sid)), "adrs": [str(a.get("id")) for a in g.adrs(sid)],
            "arquivos": len(an.arquivos_de(sid)),
        }
        for campo in ("test_cmd", "entrypoints", "invariants", "pitfalls", "lessons", "extension_points"):
            if n.get(campo):
                sistemas[sid][campo] = n[campo]
    arquivos = {f: an.dono[f] for f in an.arquivos}
    reais = [{"de": a, "para": b, "tipo": an.classe(a, b), "refs": len(lst),
              "exemplo": f"{lst[0][0]}:{lst[0][1]} -> {lst[0][2]}"} for (a, b), lst in an.arestas_sistema.items()]
    declaradas = [[a, b] for a in sorted(g.sistemas) for b in g.deps(a)]
    # sentido como nas arestas reais: caller -> callee quando declarados; senão producer -> consumers (sempre listas)
    eventos = [{"id": e.get("id"), "kind": e.get("kind"),
                "de": as_list(e.get("caller")) or as_list(e.get("producer")),
                "para": as_list(e.get("callee")) or as_list(e.get("consumers"))}
               for e in sorted((e for e in g.nos["event"] if isinstance(e, dict)), key=lambda e: str(e.get("id")))]
    testes = {str(t.get("id")): {"covers": as_list(t.get("covers")), "paths": as_list(t.get("paths")),
                                 **({"command": t["command"]} if t.get("command") else {})}
              for t in sorted((t for t in g.nos["test"] if isinstance(t, dict)), key=lambda t: str(t.get("id")))}
    adrs = {str(d.get("id")): {"title": d.get("title", ""), "status": d.get("status", ""),
                               "affects": as_list(d.get("affects"))}
            for d in sorted((d for d in g.nos["decision"] if isinstance(d, dict)), key=lambda d: str(d.get("id")))}
    fontes = []
    for f in g.fontes:
        try:
            fontes.append(Path(f).resolve().relative_to(proj.raiz).as_posix())
        except ValueError:
            fontes.append(posix(f))
    return {"versao": 1, "gerador": f"grafo.py {VERSAO}", "projeto": g.dados.get("project", proj.raiz.name),
            "grafo": fontes, "assinatura": g.assinatura(), "updated": str(g.dados.get("updated", "")),
            "camadas": camadas, "sistemas": sistemas, "arquivos": arquivos,
            "arestas": {"declaradas": declaradas, "reais": reais, "eventos": eventos},
            "testes": testes, "adrs": adrs}


def _abreviacoes(paths: list[str], maximo=8) -> list[str]:
    """Prefixos de pasta que mais economizam caracteres no resumo (guloso pelo ganho marginal; determinístico)."""
    cands = set()
    for p in paths:
        partes = p.split("/")
        for i in range(1, len(partes)):
            cands.add("/".join(partes[:i]) + "/")
    economia = [0] * len(paths)
    escolhidos: list[str] = []
    for _ in range(maximo):
        melhor, ganho = None, 0
        for pref in sorted(cands):
            if pref in escolhidos or len(pref) <= 6:
                continue
            gn = sum(max(0, len(pref) - 4 - economia[i]) for i, p in enumerate(paths) if p.startswith(pref))
            gn -= len(pref) + 6
            if gn > ganho:
                melhor, ganho = pref, gn
        if melhor is None:
            break
        escolhidos.append(melhor)
        for i, p in enumerate(paths):
            if p.startswith(melhor):
                economia[i] = max(economia[i], len(melhor) - 4)
    return escolhidos


def montar_resumo(g: Grafo) -> str:
    linhas_paths = {sid: compactar_paths(n.get("paths")) for sid, n in sorted(g.sistemas.items())}
    abrev = _abreviacoes([p for ps in linhas_paths.values() for p in ps[:3]])
    rotulos = {p: f"@{i + 1}/" for i, p in enumerate(sorted(abrev))}
    abrev.sort(key=len, reverse=True)

    def curto(p):
        for pref in abrev:
            if p.startswith(pref):
                return rotulos[pref] + p[len(pref):]
        return p

    cab = [f"# {g.dados.get('project', '')} — sistemas (id | camada | paths | depende de | eventos produz>consome)"]
    if rotulos:
        cab.append("# " + "  ".join(f"{r}={p}" for p, r in sorted(rotulos.items(), key=lambda x: x[1])))
    linhas = []
    for sid, n in sorted(g.sistemas.items()):
        paths = [curto(p) for p in linhas_paths[sid]]
        deps = [sem_prefixo(d) for d in g.deps(sid)]
        prod, cons = g.eventos(sid)
        ev = ",".join(sem_prefixo(str(e.get("id"))) for e in prod)
        evc = ",".join(sem_prefixo(str(e.get("id"))) for e in cons)
        evs = f"{ev}>{evc}" if (ev or evc) else "-"
        linhas.append(f"{sem_prefixo(sid)} | {n.get('layer') or '-'} | {_lista_curta(paths, 3)} | "
                      f"{','.join(deps) or '-'} | {evs}")
    return "\n".join(cab + linhas) + "\n"


def nome_regra(sid: str) -> str:
    return "arq-" + re.sub(r"[^a-z0-9_-]+", "-", sem_prefixo(sid).lower()) + ".md"


MARCA_REGRA = "<!-- gerado por grafo.py sync-rules; edite o grafo, não este arquivo -->"


def comando_grafo(raiz) -> str:
    """Como as regras chamam esta ferramenta: caminho relativo à raiz quando o grafo.py está no projeto (instalado com
    --copiar, ex. `.claude/grafo/grafo.py`); senão só `grafo.py` (caminho absoluto desta máquina não vai para o git).
    A cópia do projeto vale mesmo quando quem roda é outra instalação: o texto das regras não muda conforme o grafo.py usado."""
    if (Path(raiz) / ".claude" / "grafo" / "grafo.py").is_file():
        return ".claude/grafo/grafo.py"
    try:
        return posix(Path(__file__).resolve().relative_to(Path(raiz).resolve()))
    except (ValueError, OSError):
        return "grafo.py"


def gerar_regra(g: Grafo, sid: str) -> str:
    n = g.sistemas[sid]
    globs = []
    for p in as_list(n.get("paths")):
        if not isinstance(p, str):
            continue
        q = norm_padrao(p)
        if eh_glob(q):
            globs.append(q)
        elif (g.raiz / q).is_dir() or (not (g.raiz / q).exists() and "." not in q.rsplit("/", 1)[-1]):
            globs.append(q + "/**")
        else:
            globs.append(q)
    fm = ["---", "paths:"] + [f"  - {json.dumps(x, ensure_ascii=False)}" for x in globs] + ["---"]
    corpo = [f"# {sid} — {n.get('name', '')}", MARCA_REGRA, ""]
    corpo.append(f"- O que é: {g.resumo(sid) or '(sem descrição)'} Camada: {n.get('layer') or '?'}.")
    if g.deps(sid):
        corpo.append(f"- Depende de: {', '.join(g.deps(sid))}. Não importe outros sistemas sem declarar em depends_on.")
    if g.usado_por(sid):
        corpo.append(f"- Usado por: {', '.join(g.usado_por(sid))} (mudança de interface os afeta).")
    for campo, rot in (("invariants", "Invariantes"), ("pitfalls", "Armadilhas"), ("lessons", "Lições"),
                       ("extension_points", "Pontos de extensão"), ("entrypoints", "Entradas")):
        if n.get(campo):
            corpo.append(f"- {rot}: " + "; ".join(str(x) for x in as_list(n[campo])) + ".")
    ts = ([str(n["test_cmd"])] if n.get("test_cmd") else []) + \
        [f"{t.get('id')}" + (f" (`{t['command']}`)" if t.get("command") else "") for t in g.testes(sid)]
    if ts:
        corpo.append("- Testes: " + _lista_curta(ts, 6) + ".")
    adrs = g.adrs(sid)
    if adrs:
        corpo.append("- ADRs: " + "; ".join(f"{a.get('id')} {a.get('title', '')}".strip() for a in adrs[:6]) + ".")
    cmd = comando_grafo(g.raiz)
    corpo.append(f"- Mais contexto: `python {cmd} slice {sid}`; impacto: `python {cmd} impact <arquivos>`.")
    return "\n".join(fm + corpo) + "\n"


# ===================================================================================================== init


def _id_de(d: str, usados: set) -> str:
    partes = [p for p in d.split("/") if p] or ["raiz"]
    for n in range(1, len(partes) + 1):
        base = "_".join(partes[-n:])
        cand = "sys." + (re.sub(r"[^a-z0-9]+", "_", norm_txt(base).replace(" ", "_")).strip("_") or "raiz")
        if cand not in usados:
            usados.add(cand)
            return cand
    k = 2
    while f"{cand}_{k}" in usados:
        k += 1
    usados.add(f"{cand}_{k}")
    return f"{cand}_{k}"


def agrupar(arquivos: list[str], maximo: int) -> dict[str, list[str]]:
    """Pasta -> arquivos; pastas grandes se dividem nas subpastas, e os arquivos diretos viram 'pasta/*'."""
    grupos: dict[str, list[str]] = {}

    def visitar(d: str, fs: list[str]):
        if len(fs) <= maximo:
            grupos[d] = fs
            return
        diretos = [f for f in fs if _dir(f) == d]
        sub = defaultdict(list)
        for f in fs:
            if _dir(f) != d:
                resto = f[len(d) + 1:] if d else f
                sub[(d + "/" if d else "") + resto.split("/")[0]].append(f)
        if not sub:
            grupos[d] = fs
            return
        if diretos:
            grupos[(d + "/*") if d else "*"] = diretos
        for s in sorted(sub):
            visitar(s, sub[s])

    visitar("", sorted(arquivos))
    return grupos


_RE_TESTE = re.compile(r"(^|/)(tests?|__tests__|spec)(/|$)|(^|/)test_[^/]+\.py$|_test\.py$|\.(test|spec)\.[jt]sx?$|Tests?\.cs$", re.I)


def propor_grafo(proj: Projeto, exts: set, raizes: list[str], maximo: int) -> tuple[dict, dict]:
    repo = proj.repo
    arquivos = [f for f in repo.todos()
                if os.path.splitext(f)[1].lower() in exts and any(sob_raiz(f, r) for r in raizes)
                and not any(p in DIRS_IGNORADOS for p in f.split("/")[:-1])]
    grupos = agrupar(arquivos, maximo)
    usados: set = set()
    sistemas, dono = [], {}
    ids = {}
    for d in sorted(grupos):
        sid = _id_de(d.rstrip("*").rstrip("/"), usados)
        ids[d] = sid
        for f in grupos[d]:
            dono[f] = sid
    textos = {f: repo.ler(f) for f in arquivos}
    res = Resolvedor([f for f in repo.todos() if os.path.splitext(f)[1].lower() in EXTS_ANALISE],
                     {f: t for f, t in textos.items() if f.lower().endswith(".cs")}, proj.raiz,
                     proj.config.get("raizes_python"), lambda f: textos.get(f) if f in textos else repo.ler(f))
    for f in arquivos:
        if os.path.splitext(f)[1].lower() in EXT_PY:
            res.registrar_py(f, textos[f])
    deps = defaultdict(set)
    arestas_arq = []
    for f in arquivos:
        for tipo, alvo, ln in extrair_refs(f, textos[f]):
            for d in res.resolver(f, tipo, alvo):
                arestas_arq.append((f, d))
                a, b = dono.get(f), dono.get(d)
                if a and b and a != b:
                    deps[a].add(b)
    simbs = {}
    for d in sorted(grupos):
        sid = ids[d]
        fs = grupos[d]
        paths = [d]
        if d == "":   # o repositório inteiro coube num sistema: as pastas de primeiro nível e os arquivos da raiz
            paths = sorted({f.split("/")[0] for f in fs if "/" in f}) + sorted(f for f in fs if "/" not in f)
        n = len(fs)
        simbs[sid] = list(dict.fromkeys(s for f in fs for s, _ in simbolos(f, textos[f]) if "::" not in s))[:12]
        sistemas.append({
            "id": sid, "name": d.rstrip("*").rstrip("/") or "(raiz)", "layer": "", "status": "proposto",
            "summary": f"Proposto pelo init a partir de {d or '(raiz)'} ({n} arquivo(s)); revise nome, camada e descrição.",
            "description": f"Arquivos em {d or '(raiz)'}. Descreva o que o sistema faz, regras e invariantes.",
            "paths": paths, "depends_on": sorted(deps.get(sid, ())),
        })
    # testes: um nó por pasta de arquivos de teste, cobrindo os donos dos imports
    testes = []
    por_pasta = defaultdict(list)
    for f in arquivos:
        if _RE_TESTE.search(f):
            por_pasta[_dir(f)].append(f)
    usados_t: set = set()
    for d in sorted(por_pasta):
        fs = por_pasta[d]
        cobre = sorted({dono[b] for (a, b) in arestas_arq if a in fs and b in dono and dono[b] != dono.get(a)}
                       | {dono[f] for f in fs if dono.get(f) and any(dono.get(x) == dono[f] and not _RE_TESTE.search(x)
                                                                      for x in arquivos)})
        tid = "test." + sem_prefixo(_id_de(d, usados_t))
        t = {"id": tid, "name": f"Testes em {d or '(raiz)'}", "kind": "python" if all(f.endswith(".py") for f in fs)
             else "automation", "paths": [d] if d else fs, "covers": cobre or []}
        if all(f.endswith(".py") for f in fs):
            t["command"] = f"python -m pytest {d or '.'}"
        testes.append(t)
    if any(norm_padrao(r) for r in raizes):
        raizes_cov = sorted({norm_padrao(r) for r in raizes if norm_padrao(r)})
    else:
        raizes_cov = sorted({f.split("/")[0] for f in arquivos if "/" in f}) + sorted(f for f in arquivos if "/" not in f)
    dados = {
        "schema_version": 1, "project": proj.raiz.name, "updated": _dt.date.today().isoformat(),
        "layers": {},
        "coverage": {"roots": raizes_cov, "extensions": sorted({os.path.splitext(f)[1].lower() for f in arquivos}),
                     "ignore": []},
        "systems": sistemas, "events": [], "tests": testes, "decisions": [],
    }
    return dados, simbs


def prompt_llm(dados: dict, simbs: dict) -> str:
    linhas = [
        "Você vai nomear e descrever os sistemas propostos de um grafo de arquitetura (modelo barato; responda só YAML).",
        "Para cada sistema: name (até 6 palavras), summary (até 200 caracteres, o que faz, sem histórico),",
        "layer (sugira 3 a 5 camadas e quem pode depender de quem) e, se for o caso, merge_with: <id> para unir sistemas",
        "que são a mesma coisa. Não invente arquivos. Formato da resposta:",
        "layers: {<camada>: {description: ..., may_depend_on: [...]}}",
        "systems: [{id: ..., name: ..., summary: ..., layer: ..., merge_with: ...}]",
        "",
        "Sistemas propostos (id | paths | depende de | símbolos principais):",
    ]
    for s in dados["systems"]:
        linhas.append(f"- {s['id']} | {', '.join(s['paths'])} | {', '.join(s['depends_on']) or '-'} | "
                      f"{', '.join(simbs.get(s['id'], [])) or '-'}")
    texto = "\n".join(linhas) + "\n"
    return texto + f"\n# ~{tokens_aprox(texto)} tokens de entrada\n"


# ===================================================================================================== CLI


def _saida_utf8():
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            try:
                s.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def _json(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True))


def cmd_init(args, proj: Projeto) -> int:
    exts = {("." + e.lstrip(".")).lower() for e in (args.ext.split(",") if args.ext else sorted(EXTS_PADRAO))}
    raizes = args.raizes.split(",") if args.raizes else [""]
    dados, simbs = propor_grafo(proj, exts, raizes, args.max_arquivos)
    if proj.grafo_arq and proj.grafo_arq.is_file():
        print(f"(já existe um grafo em {posix(proj.grafo_arq)}; o init não o altera)", file=sys.stderr)
    texto = ("# Grafo proposto por grafo.py init — revise ids, nomes, camadas e descrições; depois troque status para active.\n"
             "# Validar: python grafo.py validate --grafo <este arquivo>\n") + gravar_yaml(dados)
    if args.saida:
        destino = Path(args.saida)
        destino = destino if destino.is_absolute() else Path(os.getcwd()) / destino
        if destino.exists():
            print(f"ERRO: {posix(destino)} já existe; o init não sobrescreve (escolha outro --saida)", file=sys.stderr)
            return 2
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(texto, encoding="utf-8", newline="\n")
        print(f"grafo proposto gravado em {posix(destino)}: {len(dados['systems'])} sistemas, {len(dados['tests'])} testes",
              file=sys.stderr)
    if args.llm:
        sys.stdout.write(prompt_llm(dados, simbs))
    elif not args.saida:
        sys.stdout.write(texto)
    return 0


def cmd_validate(args, proj: Projeto) -> int:
    try:
        rep = validar(proj, base=args.base)
    except ValueError as e:
        print(f"ERRO: {e}", file=sys.stderr)
        return 2
    g = proj.grafo()
    return imprimir_relatorio(rep, g, args.strict, args.json)


def _carregar(proj):
    g = proj.grafo()
    if g.problemas and not g.sistemas:
        raise FileNotFoundError("; ".join(g.problemas))
    return g


def cmd_owner(args, proj: Projeto) -> int:
    g = _carregar(proj)
    donos = Donos(list(g.sistemas.values()))
    rel = normalizar_caminho(args.arquivo, proj.raiz, proj.repo, donos)
    d = donos.dono(rel)
    if d is None:
        an = Analise(proj, g)
        sug = sugerir(proj, g, an, rel)
        if args.json:
            _json({"arquivo": rel, "dono": None, "sugestoes": sug})
        else:
            print(f"{rel}: sem dono" + (f"; sugestão: {sug[0]['sistema']} ({'; '.join(sug[0]['motivos'])})" if sug else ""))
        return 1
    sid, pat, rank = d
    n = g.sistemas[sid]
    if args.json:
        _json({"arquivo": rel, "dono": sid, "nome": n.get("name", ""), "camada": n.get("layer", ""),
               "padrao": pat, "exato": rank == 3})
    else:
        print(f"{rel}: {sid} — {n.get('name', '')} [{n.get('layer') or '?'}] (por '{pat}'{', exato' if rank == 3 else ''})")
    return 0


def cmd_suggest(args, proj: Projeto) -> int:
    g = _carregar(proj)
    an = Analise(proj, g)
    rel = normalizar_caminho(args.arquivo, proj.raiz, proj.repo, an.donos)
    atual = an.donos.dono(rel)
    sug = sugerir(proj, g, an, rel)
    if args.json:
        _json({"arquivo": rel, "dono_atual": atual[0] if atual else None, "sugestoes": sug})
        return 0
    if atual:
        print(f"{rel} já tem dono: {atual[0]} (por '{atual[1]}')")
    if not sug:
        print(f"{rel}: nenhuma sugestão (pasta sem vizinhos com dono e sem imports resolvidos)")
        return 1
    for i, s in enumerate(sug):
        print(f"{'->' if i == 0 else '  '} {s['sistema']} ({s['pontos']}): {'; '.join(s['motivos'])}")
    if not atual:
        print(f"registre em {g.arquivo_sistemas.name}: em {sug[0]['sistema']}.paths, "
              f"acrescente '{rel}' (ou a pasta)")
    return 0


def cmd_slice(args, proj: Projeto) -> int:
    g = _carregar(proj)
    sid = g.achar_sistema(args.sistema)
    an = None
    if sid is None:
        donos = Donos(list(g.sistemas.values()))
        d = donos.dono(normalizar_caminho(args.sistema, proj.raiz, proj.repo, donos))
        sid = d[0] if d else None
    if sid is None:
        print(f"sistema '{args.sistema}' não encontrado (use o id, o id sem 'sys.' ou um arquivo)", file=sys.stderr)
        return 2
    if args.reais:
        an = Analise(proj, g)
    orc = args.budget or int(proj.config.get("orcamento") or 600)
    r = recorte(g, sid, orc, an)
    if args.json:
        _json(r)
    else:
        print(r["texto"])
    return 0


def cmd_impact(args, proj: Projeto) -> int:
    g = _carregar(proj)
    arquivos = list(args.arquivos or [])
    if args.diff:
        try:
            arquivos += proj.repo.mudados(args.diff)
        except ValueError as e:
            print(f"ERRO: {e}", file=sys.stderr)
            return 2
    if not arquivos:
        print("informe arquivos ou --diff REF", file=sys.stderr)
        return 2
    an = Analise(proj, g)
    r = impacto(proj, g, an, arquivos)
    if args.json:
        _json(r)
        return 0
    print(f"arquivos: {len(r['arquivos'])}")
    for s, fs in r["tocados"].items():
        print(f"tocado    {s} [{g.camada(s) or '?'}]: {_lista_curta(fs, 4)}")
    for s, d in r["impactados"].items():
        print(f"impactado {s} [{g.camada(s) or '?'}] (distância {d})")
    for a in r["sem_dono"]:
        print(f"sem dono  {a}")
    if r["testes"]:
        print("testes a rodar:")
        for t in r["testes"]:
            print(f"  {'*' if t['prioridade'] == 1 else ' '} {t['id']}: {t['comando'] or _lista_curta(t['paths'], 2)}")
    if r["adrs"]:
        print("ADRs: " + "; ".join(f"{k} {v}".strip() for k, v in r["adrs"].items()))
    if r["arquivos_provaveis"]:
        print("arquivos que importam os mudados: " + _lista_curta(r["arquivos_provaveis"], 15))
    return 0


def cmd_find(args, proj: Projeto) -> int:
    g = _carregar(proj)
    an = Analise(proj, g)
    r = buscar(proj, g, an, args.texto)
    if args.json:
        _json(r)
        return 0
    if not r["sistemas"] and not r["outros"]:
        print(f"nada encontrado para '{args.texto}' — pode ser um conceito novo")
        return 1
    for e in r["sistemas"][:args.max]:
        print(f"{e['pontos']:7.1f}  {e['sistema']} — {e['nome']}" + (f"  [{'; '.join(e['motivos'])}]" if e["motivos"] else ""))
        for a in e["arquivos"][:args.arquivos]:
            print(f"           {a['arquivo']}  ({'; '.join(a['motivos'])})")
        if len(e["arquivos"]) > args.arquivos:
            print(f"           (+{len(e['arquivos']) - args.arquivos} arquivo(s); use --arquivos N ou --json)")
    if r["outros"]:
        print("outros nós: " + "; ".join(f"{o['id']} ({o['tipo']})" for o in r["outros"][:8]))
    return 0


def cmd_drift(args, proj: Projeto) -> int:
    g = _carregar(proj)
    an = Analise(proj, g)
    m = metricas(proj, g, an)
    if args.json:
        _json(m)
        return 0
    print(f"arquivos com dono: {m['arquivos_com_dono']}/{m['arquivos_cobertos']} ({m['pct_com_dono']}%); órfãos: {m['orfaos']}")
    print(f"arestas reais entre sistemas: {m['arestas_reais']}; não declaradas: {m['arestas_nao_declaradas']}; "
          f"declaradas sem uso: {m['declaradas_sem_uso']}")
    print(f"ciclos reais: {m['ciclos_reais']}; camadas violadas no código: {m['camadas_violadas_reais']}; "
          f"paths quebrados: {m['paths_quebrados']}")
    print(f"dias desde 'updated': {m['dias_desde_updated'] if m['dias_desde_updated'] is not None else '?'}; "
          f"sistemas sem descrição curta: {m['sistemas_sem_descricao_curta']}/{m['sistemas']}; propostos: {m['sistemas_propostos']}")
    return 0


def cmd_index(args, proj: Projeto) -> int:
    g = _carregar(proj)
    an = Analise(proj, g)
    pasta = proj.pasta_saida(args.saida)
    pasta.mkdir(parents=True, exist_ok=True)
    idx = montar_index(proj, g, an)
    (pasta / "index.json").write_text(json.dumps(idx, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                                      encoding="utf-8", newline="\n")
    resumo = montar_resumo(g)
    (pasta / "resumo.txt").write_text(resumo, encoding="utf-8", newline="\n")
    print(f"{posix(pasta / 'index.json')}: {len(idx['sistemas'])} sistemas, {len(idx['arquivos'])} arquivos, "
          f"{len(idx['arestas']['reais'])} arestas reais")
    print(f"{posix(pasta / 'resumo.txt')}: {len(resumo)} caracteres (~{tokens_aprox(resumo)} tokens)")
    return 0


def cmd_sync_rules(args, proj: Projeto) -> int:
    g = _carregar(proj)
    if args.saida:
        pasta = Path(args.saida)
        pasta = pasta if pasta.is_absolute() else proj.raiz / pasta
    else:
        pasta = proj.pasta_da_config("regras", ".claude/rules")
    desejados = {nome_regra(sid): gerar_regra(g, sid) for sid in sorted(g.sistemas)
                 if as_list(g.sistemas[sid].get("paths"))}
    existentes = {p.name: p for p in pasta.glob("arq-*.md")} if pasta.is_dir() else {}
    mudancas = 0
    for nome, texto in desejados.items():
        p = pasta / nome
        atual = p.read_text(encoding="utf-8") if p.is_file() else None
        estado = "igual" if atual == texto else ("novo" if atual is None else "alterado")
        if estado != "igual":
            mudancas += 1
        if args.escrever:
            if estado != "igual":
                pasta.mkdir(parents=True, exist_ok=True)
                p.write_text(texto, encoding="utf-8", newline="\n")
            print(f"{estado:9} {posix(p)}")
        else:
            print(f"===== {estado}: {posix(p)}")
            print(texto)
    for nome, p in sorted(existentes.items()):
        if nome not in desejados:
            try:
                gerado = MARCA_REGRA in p.read_text(encoding="utf-8")
            except OSError:
                gerado = False
            if gerado:
                mudancas += 1
                if args.escrever:
                    p.unlink()
                print(f"{'removido' if args.escrever else 'remover':9} {posix(p)} (sistema não existe mais)")
    if not args.escrever:
        print(f"(nada gravado; {mudancas} mudança(s). Para gravar: grafo.py sync-rules --escrever)")
    return 0


def montar_parser() -> argparse.ArgumentParser:
    comum = argparse.ArgumentParser(add_help=False)
    comum.add_argument("--raiz", help="raiz do projeto (padrão: topo do git ou pasta atual)")
    comum.add_argument("--grafo", help="caminho do YAML do grafo (padrão: grafo.json/.grafo.toml ou descoberta)")
    ap = argparse.ArgumentParser(prog="grafo.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--versao", action="version", version=VERSAO)
    sub = ap.add_subparsers(dest="comando", required=True)

    p = sub.add_parser("init", parents=[comum], help="propõe um grafo a partir do código")
    p.add_argument("--saida", help="arquivo YAML de saída (nunca sobrescreve); padrão: imprime")
    p.add_argument("--llm", action="store_true", help="imprime o prompt para um modelo barato nomear/descrever (não chama modelo)")
    p.add_argument("--ext", help="extensões separadas por vírgula (padrão: Python, C/C++, JS/TS, C#)")
    p.add_argument("--raizes", help="pastas a varrer, separadas por vírgula (padrão: tudo)")
    p.add_argument("--max-arquivos", type=int, default=40, help="pasta com mais arquivos que isso se divide (padrão 40)")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("validate", parents=[comum], help="valida o grafo contra si mesmo e contra o código")
    p.add_argument("--base", help="só os arquivos mudados em relação a REF (git diff REF + não rastreados)")
    p.add_argument("--strict", action="store_true", help="avisos também reprovam")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("owner", parents=[comum], help="dono de um arquivo")
    p.add_argument("arquivo")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_owner)

    p = sub.add_parser("suggest", parents=[comum], help="sugere dono para arquivo sem dono")
    p.add_argument("arquivo")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_suggest)

    p = sub.add_parser("slice", parents=[comum], help="recorte de um sistema dentro do orçamento")
    p.add_argument("sistema", help="id (sys.x ou x) ou um arquivo do sistema")
    p.add_argument("--budget", type=int, help="orçamento em tokens (padrão 600 ou 'orcamento' da configuração)")
    p.add_argument("--reais", action="store_true", help="inclui imports não declarados (varre o código)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_slice)

    p = sub.add_parser("impact", parents=[comum], help="impacto de arquivos ou de um diff")
    p.add_argument("arquivos", nargs="*")
    p.add_argument("--diff", help="arquivos mudados em relação a REF")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_impact)

    p = sub.add_parser("find", parents=[comum], help="busca por id, nome, classe, caminho, símbolo e conteúdo")
    p.add_argument("texto")
    p.add_argument("--max", type=int, default=8, help="sistemas listados (padrão 8)")
    p.add_argument("--arquivos", type=int, default=12, help="arquivos por sistema no texto (padrão 12; --json lista todos)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_find)

    p = sub.add_parser("drift", parents=[comum], help="métricas de desvio grafo x código")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_drift)

    p = sub.add_parser("index", parents=[comum], help="gera index.json e resumo.txt")
    p.add_argument("--saida", help="pasta de saída (padrão .grafo/ na raiz ou 'saida' da configuração)")
    p.set_defaults(func=cmd_index)

    p = sub.add_parser("sync-rules", parents=[comum], help="gera .claude/rules/arq-<sistema>.md")
    p.add_argument("--saida", help="pasta das regras (padrão .claude/rules)")
    p.add_argument("--escrever", action="store_true", help="grava (sem isso, só mostra)")
    p.set_defaults(func=cmd_sync_rules)
    return ap


def main(argv=None) -> int:
    _saida_utf8()
    args = montar_parser().parse_args(argv)
    try:
        proj = Projeto(args.raiz, args.grafo)
        return args.func(args, proj)
    except (FileNotFoundError, ValueError) as e:
        print(f"ERRO: {e}", file=sys.stderr)
        return 2
    except Exception as e:  # noqa: BLE001 — sem traceback para o agente; o motivo basta
        print(f"ERRO interno do grafo.py: {type(e).__name__}: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
