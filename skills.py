#!/usr/bin/env python
"""Ciclo de vida das skills candidatas do time de agentes (somente biblioteca padrão).

Comandos:
  skills.py listar
  skills.py novo <nome> --autor X
  skills.py usar <nome> --agente X --cartao N --resultado ok|falhou
  skills.py contar-uso            (lê os eventos do escritório; sugere revisão após 30 dias sem uso)
  skills.py promover <nome>       (gera dados/skills-promover/<nome>/SKILL.md; não grava no seu projeto)

Os candidatos ficam em dados/skills/<nome>.md (pasta local, fora do git); o modelo é skills-candidatos/MODELO.md.
Os nomes de agente vêm do config.json (campo "agentes").
"""
import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))
import configuracao  # noqa: E402

PASTA = RAIZ / "dados" / "skills"
MODELO = RAIZ / "skills-candidatos" / "MODELO.md"
PROMOVER = RAIZ / "dados" / "skills-promover"
EVENTOS_ANTIGO = RAIZ / "dados" / "eventos.antigo.jsonl"   # o que o hook das versões até a 1.9 separou aos 4 MB
USO_JSON = PASTA / "uso.json"
ESTADOS = ("candidato", "quarentena", "pronto-ab", "aprovado", "rejeitado", "aposentado")
DIAS_SEM_USO = 30
RE_NOME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def _reconfigurar_saida():
    for f in (sys.stdout, sys.stderr):
        try:
            f.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def validar_nome(nome):
    if not nome or len(nome) > 64 or not RE_NOME.match(nome):
        raise SystemExit(f"Nome inválido '{nome}': use minúsculas, números e hífen (até 64 caracteres).")


def _valor(v):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        try:
            return json.loads(v) if v[0] == '"' else v[1:-1]
        except ValueError:
            return v[1:-1]
    return v


def _uso_de_linha(texto):
    texto = texto.strip()
    if texto.startswith("{") and texto.endswith("}"):
        texto = texto[1:-1]
    uso = {}
    for parte in re.split(r",\s*(?=[a-z]+:)", texto):
        if ":" in parte:
            k, v = parte.split(":", 1)
            uso[k.strip()] = _valor(v)
    return uso


def ler(caminho):
    """Devolve (meta, corpo). meta['usos'] é lista de dicts."""
    texto = Path(caminho).read_text(encoding="utf-8")
    m = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n?(.*)$", texto, re.S)
    if not m:
        raise ValueError(f"{caminho}: sem frontmatter")
    meta = {"usos": []}
    em_usos = False
    for linha in m.group(1).splitlines():
        if not linha.strip():
            continue
        if em_usos and linha.lstrip().startswith("- "):
            meta["usos"].append(_uso_de_linha(linha.lstrip()[2:]))
            continue
        em_usos = False
        if ":" in linha and not linha.startswith(" "):
            k, v = linha.split(":", 1)
            k = k.strip()
            if k == "usos":
                em_usos = True
                if v.strip().startswith("["):
                    for item in re.findall(r"\{[^}]*\}", v):
                        meta["usos"].append(_uso_de_linha(item))
            else:
                meta[k] = _valor(v)
    return meta, m.group(2)


def _fm_valor(v):
    v = str(v)
    precisa = re.search(r"(^[\s\"'\[{&*!|>%@`#-])|(: )| #|:$", v)
    return json.dumps(v, ensure_ascii=False) if precisa else v


def gravar(caminho, meta, corpo):
    linhas = ["---"]
    for k in ("name", "description", "autor", "criado", "estado", "promovido"):
        if meta.get(k) not in (None, ""):
            linhas.append(f"{k}: {_fm_valor(meta[k])}")
    linhas.append("usos:")
    for u in meta.get("usos", []):
        campos = ", ".join(f"{k}: {_fm_valor(u.get(k, ''))}" for k in ("data", "agente", "cartao", "resultado"))
        linhas.append("  - {" + campos + "}")
    linhas.append(f"evidencia: {_fm_valor(meta.get('evidencia', ''))}")
    linhas.append("---")
    Path(caminho).write_text("\n".join(linhas) + "\n" + corpo.lstrip("\n"), encoding="utf-8", newline="\n")


def candidatos():
    """Lista de (caminho, meta, corpo) de todos os candidatos (exceto o modelo)."""
    saida = []
    for p in sorted(PASTA.glob("*.md")):
        if p.name.upper() == "MODELO.MD":
            continue
        try:
            meta, corpo = ler(p)
        except (ValueError, OSError):
            continue
        meta.setdefault("name", p.stem)
        saida.append((p, meta, corpo))
    return saida


def _caminho(nome):
    validar_nome(nome)
    p = PASTA / f"{nome}.md"
    if not p.exists():
        raise SystemExit(f"Candidato '{nome}' não existe. Veja: python skills.py listar")
    return p


def agente_canonico(nome):
    """Nome do agente como está no config.json (aceita apelidos de outros_nomes); avisa se não existir."""
    certo = configuracao._agente_canonico(configuracao.carregar()["agentes"], nome)
    if not certo:
        print(f"Aviso: '{nome}' não é um agente do config.json; o XP só aparece para agentes configurados.")
    return certo or nome


def _tarefas_ok(meta):
    return {str(u.get("cartao")) for u in meta.get("usos", []) if u.get("resultado") == "ok"}


def cmd_listar(_a):
    lista = candidatos()
    if not lista:
        print("Nenhum candidato em skills-candidatos/.")
        return 0
    print(f"{'nome':32} {'estado':11} {'autor':14} {'usos ok/total':13} criado")
    for _p, m, _c in lista:
        usos = m.get("usos", [])
        ok = sum(1 for u in usos if u.get("resultado") == "ok")
        print(f"{m['name'][:32]:32} {m.get('estado', '?'):11} {m.get('autor', '?')[:14]:14} {ok}/{len(usos):<11} {m.get('criado', '')}")
    return 0


def cmd_novo(a):
    validar_nome(a.nome)
    destino = PASTA / f"{a.nome}.md"
    if destino.exists():
        raise SystemExit(f"Já existe: {destino.name}")
    modelo = MODELO.read_text(encoding="utf-8")
    texto = modelo.replace("{{nome}}", a.nome).replace("{{autor}}", agente_canonico(a.autor)).replace("{{criado}}", date.today().isoformat())
    PASTA.mkdir(parents=True, exist_ok=True)
    destino.write_text(texto, encoding="utf-8", newline="\n")
    print(f"Criado {destino}. Preencha description (3ª pessoa, QUANDO usar), evidencia e o corpo.")
    return 0


def cmd_usar(a):
    p = _caminho(a.nome)
    meta, corpo = ler(p)
    if meta.get("estado") in ("rejeitado", "aposentado"):
        raise SystemExit(f"'{a.nome}' está {meta['estado']}; não registra uso.")
    meta["usos"].append({"data": date.today().isoformat(), "agente": agente_canonico(a.agente), "cartao": str(a.cartao), "resultado": a.resultado})
    antes = meta.get("estado", "candidato")
    falhas = sum(1 for u in meta["usos"] if u.get("resultado") == "falhou")
    if antes in ("candidato", "quarentena", "pronto-ab"):
        if falhas and antes == "candidato":
            meta["estado"] = "quarentena"
        elif len(_tarefas_ok(meta)) >= 2 and (not falhas or antes == "quarentena"):
            meta["estado"] = "pronto-ab"
    gravar(p, meta, corpo)
    msg = f"Uso registrado ({a.resultado}, cartão {a.cartao}). Estado: {antes}"
    print(msg + (f" -> {meta['estado']}" if antes != meta["estado"] else ""))
    return 0


def eventos_skill():
    """Itera (ts, agente, nome_da_skill) dos eventos do escritório com ferramenta Skill: a tabela evento do banco local
    e, antes dela, o dados/eventos.antigo.jsonl das versões antigas, se ainda existir."""
    import banco
    antigos = []
    if EVENTOS_ANTIGO.exists():
        with open(EVENTOS_ANTIGO, "rb") as f:
            for bruto in f:
                if b'"Skill"' not in bruto:
                    continue
                try:
                    antigos.append(json.loads(bruto.decode("utf-8", errors="replace")))
                except ValueError:
                    continue
    for ev in [*antigos, *banco.eventos_da_ferramenta("Skill")]:
        if not isinstance(ev, dict) or ev.get("ferramenta") != "Skill":
            continue
        m = re.match(r"\s*skill:\s*([^\s,]+)", ev.get("detalhe", "") or "")
        if m:
            yield ev.get("ts", ""), ev.get("agente", "?"), m.group(1).split(":")[-1].strip()


def cmd_contar_uso(_a):
    por_skill = {}
    for ts, agente, nome in eventos_skill():
        d = por_skill.setdefault(nome, {"total": 0, "ultimo": "", "agentes": {}})
        d["total"] += 1
        d["ultimo"] = max(d["ultimo"], ts)
        d["agentes"][agente] = d["agentes"].get(agente, 0) + 1
    PASTA.mkdir(parents=True, exist_ok=True)
    USO_JSON.write_text(json.dumps(por_skill, ensure_ascii=False, indent=1), encoding="utf-8")
    hoje = datetime.now()
    revisar = []
    promovidas = [(m["name"], m) for _p, m, _c in candidatos() if m.get("estado") == "aprovado"]
    print(f"{'skill promovida':32} {'usos':>5}  último uso")
    for nome, m in promovidas:
        d = por_skill.get(nome, {"total": 0, "ultimo": ""})
        ref = d["ultimo"] or m.get("promovido") or m.get("criado") or ""
        try:
            dt = datetime.fromisoformat(ref[:19])
        except ValueError:
            dt = hoje
        print(f"{nome[:32]:32} {d['total']:>5}  {d['ultimo'] or '(nunca)'}")
        if hoje - dt > timedelta(days=DIAS_SEM_USO):
            revisar.append(nome)
    if not promovidas:
        print("(nenhuma skill promovida ainda)")
    if revisar:
        print(f"\nSEM USO HÁ {DIAS_SEM_USO}+ DIAS -> sugerir revisão/aposentadoria: {', '.join(revisar)}")
    return 0


def cmd_promover(a):
    p = _caminho(a.nome)
    meta, corpo = ler(p)
    estado = meta.get("estado")
    if estado not in ("pronto-ab", "aprovado") and not a.forcar:
        raise SystemExit(f"'{a.nome}' está '{estado}': só promove pronto-ab (ou aprovado, para regerar). Use --forcar para ignorar.")
    desc = (meta.get("description") or "").strip()
    if not desc or desc.startswith("Descreva em 3ª pessoa"):
        raise SystemExit("description ainda é o texto do modelo; escreva em 3ª pessoa dizendo QUANDO usar.")
    if len(desc) > 1024:
        raise SystemExit("description passa de 1024 caracteres.")
    corpo = re.sub(r"<!--.*?-->", "", corpo, flags=re.S).strip() + "\n"
    if corpo.count("\n") >= 500:
        raise SystemExit("Corpo com 500 linhas ou mais; o formato oficial pede menos. Enxugue.")
    validar_nome(meta["name"])
    saida = PROMOVER / a.nome
    saida.mkdir(parents=True, exist_ok=True)
    cabeca = f"---\nname: {meta['name']}\ndescription: {json.dumps(desc, ensure_ascii=False)}\n---\n"
    (saida / "SKILL.md").write_text(cabeca + corpo, encoding="utf-8", newline="\n")
    meta["estado"] = "aprovado"
    meta["promovido"] = date.today().isoformat()
    gravar(p, meta, ler(p)[1])
    print(f"Gerado {saida / 'SKILL.md'}. Próximo passo: copie a pasta para "
          f".claude/skills/{a.nome}/ do seu projeto (ou ~/.claude/skills/{a.nome}/ para valer em todos) e faça o commit/PR.")
    return 0


def main(argv=None):
    _reconfigurar_saida()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("listar").set_defaults(f=cmd_listar)
    s = sub.add_parser("novo")
    s.add_argument("nome")
    s.add_argument("--autor", required=True)
    s.set_defaults(f=cmd_novo)
    s = sub.add_parser("usar")
    s.add_argument("nome")
    s.add_argument("--agente", required=True)
    s.add_argument("--cartao", required=True)
    s.add_argument("--resultado", required=True, choices=("ok", "falhou"))
    s.set_defaults(f=cmd_usar)
    sub.add_parser("contar-uso").set_defaults(f=cmd_contar_uso)
    s = sub.add_parser("promover")
    s.add_argument("nome")
    s.add_argument("--forcar", action="store_true")
    s.set_defaults(f=cmd_promover)
    a = ap.parse_args(argv)
    return a.f(a)


if __name__ == "__main__":
    sys.exit(main())
