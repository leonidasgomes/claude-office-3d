# -*- coding: utf-8 -*-
"""Custo do time por agente, por cartão e por PR mergeado, a partir dos transcritos do Claude Code (sem tokens).

De onde vem cada número:
- O custo de cada sessão é o `cost-state` que o Claude Code grava no próprio transcrito (totalCostUSD e, por modelo,
  costUSD) e já inclui os colegas (agent teams) e os subagentes.
- A divisão desse custo entre as respostas usa os pesos relativos de preço da API (entrada 1, escrita no cache 1,25,
  leitura do cache 0,1, saída 5): o total de cada modelo bate com o cobrado; só a divisão interna é estimada.
- Cache escrito por TTL (ephemeral_1h/5m_input_tokens de cada resposta): mostra se colegas e subagentes estão no cache de
  5 min (recomeça a cada pausa maior) ou no de 1 h (CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL=1h, doc prompt-caching).
- Quais sessões: as pastas de ~/.claude/projects dos caminhos em "projetos" do config.json (o nome da pasta é o caminho
  com todo caractere que não é letra/número trocado por "-"), e as dos worktrees dentro deles (".claude/worktrees").
- Agente: o nome da sessão/colega no transcrito, casado com "nome"/"outros_nomes" do config (sufixo "_123" ou "-3",
  segundo colega do mesmo time, sai);
  a sessão principal sem nome é do líder.
- Cartão: o número no nome do branch da sessão (`feat/31-...`) e o último "#n" de cartão citado nas ferramentas e
  mensagens (`cartão #31`, `kanban ... move 31`, worktree `...-31`). Sem cartão, agrupa pelo branch.
- Exploração de código: Read/Grep/Glob e grep/cat/sed/find no shell, e quanto texto isso jogou no contexto.
- Revisor de código (revisor_ia.py): roda fora das sessões; o custo vem de dados/revisor/estado.json e entra no total.
- Sessão ainda aberta (o time ao vivo): o Claude Code só grava o `cost-state` quando a sessão fecha; até lá o custo é
  estimado pelos tokens, com o preço por peso de cada modelo calibrado nas sessões já fechadas (antes ela ficava de fora
  e o custo do dia parecia zerar).
- O custo de cada sessão é rateado por TODAS as respostas dela e só entra o que caiu na janela (antes o total inteiro ia
  para as respostas da janela e inflava sessões longas que atravessam o corte).
- Acumulado: o banco local dados/xp/escritorio.db (banco.py, SQLite) guarda o custo de cada sessão e de cada revisão já
  vistas e uma foto por dia; só cresce, mesmo quando a janela anda ou o Claude Code apaga transcritos velhos
  (cleanupPeriodDays, 30 dias por padrão).

Uso: python custo_time.py [--dias 7]     relatório no terminal + dados/xp/custos.json (o Placar mostra "US$ por PR" e o
                                         acumulado) + dados/xp/escritorio.db (acumulado; foto do dia só com --dias 7)
"""
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))
import configuracao  # noqa: E402
import banco  # noqa: E402  (dados/xp/escritorio.db: acumulado do custo)

PROJETOS = Path.home() / ".claude" / "projects"
SAIDA = RAIZ / "dados" / "xp" / "custos.json"
INICIO = datetime(2000, 1, 1, tzinfo=timezone.utc)
PESO = {"in": 1.0, "cw": 1.25, "cr": 0.1, "out": 5.0}
HORAS_LONGA = 12          # sessão aberta mais que isso: reler o contexto longo é o que mais custa
RE_CARTAO = [re.compile(p, re.I) for p in (
    r"(?:feat|fix|perf|chore|docs|refactor|test|wip|[a-z]+-[a-z]+)/(\d{1,5})(?=[-_/\s\"']|$)",
    r"worktrees[\\/]+[a-z0-9-]*?-(\d{1,5})(?=[\\/\s\"']|$)",
    r"kanban[^\n]{0,20}\s(?:move|link-pr)\s+(\d{1,5})\b",
    r"(?:cart[ãa]o|card|issue)\s*#(\d{1,5})\b",
)]
RE_EXPLORA = re.compile(r"\b(grep|rg|find|sed -n|cat|head|tail|Select-String|Get-Content|ls)\b")
RE_SUFIXO = re.compile(r"[_-]\d+[a-z]?$")   # "Dev_235" / "Dev-3" (segundo colega do mesmo time) -> "Dev"


def _nome_pasta(caminho):
    return re.sub(r"[^A-Za-z0-9]", "-", str(Path(caminho)))


def pastas(cfg):
    bases = {_nome_pasta(p) for p in cfg.get("projetos") or []}
    if not bases or not PROJETOS.is_dir():
        return []
    return [p for p in PROJETOS.iterdir() if p.is_dir() and any(p.name == b or p.name.startswith(b + "--") for b in bases)]


def _ts(s):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def _peso(u):
    return (PESO["in"] * (u.get("input_tokens") or 0) + PESO["cw"] * (u.get("cache_creation_input_tokens") or 0)
            + PESO["cr"] * (u.get("cache_read_input_tokens") or 0) + PESO["out"] * (u.get("output_tokens") or 0))


def _cartao_em(texto):
    achado = None
    for rx in RE_CARTAO:
        for m in rx.finditer(texto):
            achado = int(m.group(1))
    return achado


class Agentes:
    """Nome no transcrito -> nome do agente no config (o líder fica com a sessão principal sem nome)."""
    def __init__(self, cfg):
        self.lider = next((a["nome"] for a in cfg["agentes"] if a.get("lider")), cfg["agentes"][0]["nome"] if cfg["agentes"] else "Líder")
        self.mapa = {}
        for a in cfg["agentes"]:
            for n in [a["nome"], *(a.get("outros_nomes") or [])]:
                self.mapa[self.chave(n)] = a["nome"]

    @staticmethod
    def chave(n):
        return re.sub(r"[-\s]", "_", RE_SUFIXO.sub("", str(n or "").strip())).lower()

    def de(self, nome, principal=False):
        if not nome:
            return self.lider if principal else "subagente"
        return self.mapa.get(self.chave(nome), RE_SUFIXO.sub("", str(nome)))


def _nome_sessao(arquivo):
    nome = ""
    for linha in arquivo.open(encoding="utf-8", errors="replace"):
        if '"agent-name"' in linha or '"custom-title"' in linha:
            try:
                d = json.loads(linha)
            except ValueError:
                continue
            nome = d.get("agentName") or d.get("customTitle") or nome
    return nome


def _nome_subagente(arq):
    try:
        j = json.loads(arq.with_name(arq.name.replace(".jsonl", ".meta.json")).read_text(encoding="utf-8"))
        return j.get("name") or j.get("agentType") or ""
    except (OSError, ValueError):
        m = re.match(r"agent-a([A-Za-z_]+)-", arq.name)
        return m.group(1) if m else ""


def _ler(arquivo, agente, desde, usar_branch, expl):
    """[(modelo, peso, rótulo do cartão, ts, agente, contexto)] das respostas; soma a exploração de código em expl."""
    saida, cartao, vistos, pend = [], None, set(), {}
    for linha in arquivo.open(encoding="utf-8", errors="replace"):
        try:
            d = json.loads(linha)
        except ValueError:
            continue
        msg = d.get("message") or {}
        conteudo = msg.get("content")
        if d.get("type") == "user":
            texto = conteudo if isinstance(conteudo, str) else " ".join(
                b.get("text", "") for b in conteudo or [] if isinstance(b, dict) and b.get("type") == "text")
            cartao = _cartao_em(texto) or cartao
            for b in conteudo if isinstance(conteudo, list) else []:
                if isinstance(b, dict) and b.get("type") == "tool_result" and pend.pop(b.get("tool_use_id"), False):
                    r = b.get("content")
                    expl["chars"] += len(r) if isinstance(r, str) else sum(len(x.get("text", "")) for x in r or [] if isinstance(x, dict))
        if d.get("type") != "assistant":
            continue
        for b in conteudo if isinstance(conteudo, list) else []:
            if isinstance(b, dict) and b.get("type") == "tool_use":
                s = json.dumps(b.get("input"), ensure_ascii=False)
                cartao = _cartao_em(s) or cartao
                if b.get("name") in ("Read", "Grep", "Glob") or (b.get("name") in ("Bash", "PowerShell") and RE_EXPLORA.search(s)):
                    expl["n"] += 1
                    pend[b.get("id")] = True
        ramo = str(d.get("gitBranch") or "") if usar_branch else ""
        if ramo:
            cartao = _cartao_em(ramo + " ") or cartao
        rid = d.get("requestId") or d.get("uuid")
        ts, u = _ts(d.get("timestamp")), msg.get("usage")
        if not u or rid in vistos or (ts and ts < desde):
            continue
        vistos.add(rid)
        rotulo = cartao if cartao else ("branch " + ramo if ramo and ramo not in ("main", "master", "develop", "HEAD") else None)
        ctx = (u.get("input_tokens") or 0) + (u.get("cache_creation_input_tokens") or 0) + (u.get("cache_read_input_tokens") or 0)
        cc = u.get("cache_creation") or {}                    # escrita no cache por TTL (1 h custa 2x, 5 min 1,25x)
        cw = (cc.get("ephemeral_1h_input_tokens") or 0, cc.get("ephemeral_5m_input_tokens") or 0)
        saida.append((msg.get("model") or "?", _peso(u), rotulo, ts, agente, ctx, cw))
    return saida


def coletar(cfg, dias):
    desde = datetime.now(timezone.utc) - timedelta(days=dias)
    nomes = Agentes(cfg)
    db = banco.conectar()
    fechadas = banco.sessoes_fechadas(db)
    # lê ao menos 7 dias de sessões: o preço da sessão aberta é calibrado nelas, igual em qualquer --dias
    calibra = min(desde, datetime.now(timezone.utc) - timedelta(days=7))
    agentes, cartoes, longas, total, sessoes = {}, {}, [], 0.0, []
    for proj in pastas(cfg):
        for principal in proj.glob("*.jsonl"):
            # fora da janela de calibração e já no banco como fechada: nada a recalcular
            if principal.stat().st_mtime < calibra.timestamp() and principal.stem in fechadas:
                continue
            custo = None
            for linha in principal.open(encoding="utf-8", errors="replace"):
                if '"cost-state"' in linha:
                    try:
                        custo = json.loads(linha)
                    except ValueError:
                        pass
            dono = nomes.de(_nome_sessao(principal), principal=True)
            expl_por = {}
            # a sessão inteira (desde INICIO): o rateio usa todas as respostas; a janela é filtrada depois
            resp = _ler(principal, dono, INICIO, True, expl_por.setdefault(dono, {"n": 0, "chars": 0}))
            sub = principal.with_suffix("") / "subagents"
            for s in sub.glob("*.jsonl") if sub.is_dir() else []:
                ag = nomes.de(_nome_subagente(s))
                resp += _ler(s, ag, INICIO, False, expl_por.setdefault(ag, {"n": 0, "chars": 0}))
            if resp:
                sessoes.append((principal.stem, custo, resp, expl_por))
    # preço por peso de cada modelo, das sessões fechadas: estima a sessão aberta, que ainda não tem cost-state
    preco = {}
    for _, custo, resp, _ in sessoes:
        if not custo:
            continue
        peso = {}
        for m, pw, *_ in resp:
            peso[m] = peso.get(m, 0.0) + pw
        for m, v in (custo.get("modelUsage") or {}).items():
            if peso.get(m) and v.get("costUSD"):
                c, w = preco.get(m, (0.0, 0.0))
                preco[m] = (c + v["costUSD"], w + peso[m])
    ao_vivo = 0
    for sid, custo, resp, expl_por in sessoes:
        soma = {}
        for m, pw, *_ in resp:
            soma[m] = soma.get(m, 0.0) + pw
        if custo:
            por_modelo = {m: (v.get("costUSD") or 0.0) for m, v in (custo.get("modelUsage") or {}).items()}
        else:
            ao_vivo += 1
            por_modelo = {m: w * preco[m][0] / preco[m][1] for m, w in soma.items() if m in preco}
        banco.gravar_sessao(db, sid, round(sum(por_modelo.values()), 4), not custo,
                            max((str(x[3]) for x in resp if x[3]), default="")[:16])
        janela = [x for x in resp if not x[3] or x[3] >= desde]
        if not janela:
            continue
        datas = [x[3] for x in janela if x[3]]
        horas = (max(datas) - min(datas)).total_seconds() / 3600 if datas else 0
        if horas > HORAS_LONGA:
            longas.append((sum(por_modelo.values()), horas, janela[0][4]))
        for m, pw, cartao, ts, ag, ctx, cw in janela:
            usd = por_modelo.get(m, 0.0) * pw / soma[m] if soma.get(m) else 0.0
            total += usd
            a = agentes.setdefault(ag, {"usd": 0.0, "modelos": {}, "ctx": 0, "n": 0, "explora": 0, "explora_chars": 0,
                                        "cw1h": 0, "cw5m": 0})
            a["usd"] += usd
            a["modelos"][m] = a["modelos"].get(m, 0.0) + usd
            a["ctx"] += ctx
            a["cw1h"] += cw[0]
            a["cw5m"] += cw[1]
            a["n"] += 1
            chave = str(cartao) if cartao else "sem cartão nem branch"
            c = cartoes.setdefault(chave, {"usd": 0.0, "agentes": {}})
            c["usd"] += usd
            c["agentes"][ag] = c["agentes"].get(ag, 0.0) + usd
        for ag, e in expl_por.items():
            if ag in agentes:
                agentes[ag]["explora"] += e["n"]
                agentes[ag]["explora_chars"] += e["chars"]
    return {"agentes": agentes, "cartoes": cartoes, "total": total, "sessoes_ao_vivo": ao_vivo,
            "longas": sorted(longas, reverse=True), "db": db}


def acumulado(db):
    """Grava as revisões do revisor_ia no banco e devolve o acumulado (só cresce): {"usd", "desde"}."""
    try:
        revs = json.loads((RAIZ / "dados" / "revisor" / "estado.json").read_text(encoding="utf-8")).get("historico", [])
    except Exception:
        revs = []
    for h in revs:
        banco.gravar_revisao(db, h.get("pr"), h.get("commit"), h.get("quando"), h.get("custo_usd") or 0)
    usd, desde = banco.acumulado(db)
    return {"usd": usd, "desde": desde}


def prs_mergeados(cfg, dias):
    import sugestoes_bot
    repo = (cfg.get("github") or {}).get("repo")
    if not repo:
        return 0
    desde = (datetime.now(timezone.utc) - timedelta(days=dias)).strftime("%Y-%m-%dT%H:%M:%SZ")
    _, prs, _ = sugestoes_bot.gh_api({"gh": configuracao.localizar_gh() or "gh"},
                                     f"repos/{repo}/pulls?state=closed&sort=updated&direction=desc&per_page=100")
    return sum(1 for p in prs or [] if (p.get("merged_at") or "") >= desde)


def custo_revisor(dias):
    """Revisões do revisor_ia.py no período: o `claude -p` dele roda fora das sessões do time (não aparece nos
    transcritos), então o custo vem do total_cost_usd que ele grava em dados/revisor/estado.json a cada revisão."""
    try:
        hist = json.loads((RAIZ / "dados" / "revisor" / "estado.json").read_text(encoding="utf-8")).get("historico", [])
    except Exception:
        return {"usd": 0.0, "revisoes": 0, "achados": 0}
    corte = (datetime.now() - timedelta(days=dias)).strftime("%Y-%m-%d %H:%M")
    hs = [h for h in hist if h.get("quando", "") >= corte]
    return {"usd": sum(h.get("custo_usd") or 0 for h in hs), "revisoes": len(hs),
            "achados": sum(h.get("achados") or 0 for h in hs)}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    dias = int(sys.argv[sys.argv.index("--dias") + 1]) if "--dias" in sys.argv else 7
    cfg = configuracao.carregar()
    if not cfg.get("projetos"):
        print('Configure "projetos" no config.json (os caminhos onde o time trabalha) para medir o custo.')
        return 1
    r = coletar(cfg, dias)
    rev = custo_revisor(dias)
    r["total"] += rev["usd"]
    acum = acumulado(r["db"])
    try:
        n_prs = prs_mergeados(cfg, dias)
    except Exception:
        n_prs = 0
    por_pr = r["total"] / n_prs if n_prs else None
    print(f"Custo do time nos últimos {dias} dia(s): US$ {r['total']:.2f}"
          + (f" · {n_prs} PR(s) mergeado(s) · US$ {por_pr:.2f} por PR" if por_pr else ""))
    if rev["revisoes"]:
        print(f"  inclui o revisor de código ([revisor-ia]): US$ {rev['usd']:.2f} em {rev['revisoes']} revisão(ões), "
              f"{rev['achados']} achado(s)")
    if r["sessoes_ao_vivo"]:
        print(f"  inclui {r['sessoes_ao_vivo']} sessão(ões) ainda aberta(s), estimada(s) pelos tokens (sem cost-state ainda)")
    print(f"Acumulado desde {acum['desde'] or 'hoje'}: US$ {acum['usd']:.2f} (dados/xp/escritorio.db, não zera)")
    if dias == 7:   # a foto do dia é sempre da janela padrão, para os dias serem comparáveis
        banco.gravar_dia(r["db"], r["total"], acum["usd"], n_prs)
    r["db"].commit()
    r["db"].close()
    print("Por agente:")
    for ag, a in sorted(r["agentes"].items(), key=lambda x: -x[1]["usd"]):
        mods = ", ".join(f"{m.replace('claude-', '')} {v:.2f}" for m, v in sorted(a["modelos"].items(), key=lambda x: -x[1]) if v >= 0.01)
        print(f"  {ag:<16} US$ {a['usd']:7.2f}  contexto médio {a['ctx'] / max(1, a['n']) / 1000:4.0f} mil  "
              f"cache 1h/5m escrito: {a['cw1h'] / 1e6:.2f}/{a['cw5m'] / 1e6:.2f} M  "
              f"exploração de código {a['explora']:>5} chamadas  ({mods})")
    if r["longas"]:
        print(f"Sessões abertas mais de {HORAS_LONGA} h (reler contexto longo é o maior custo; prefira sessão nova por tarefa):")
        for usd, h, quem in r["longas"][:5]:
            print(f"  US$ {usd:7.2f}  {h:5.1f} h  {quem}")
    print("Por cartão (os 15 mais caros):")
    for c, v in sorted(r["cartoes"].items(), key=lambda x: -x[1]["usd"])[:15]:
        quem = ", ".join(f"{a} {u:.2f}" for a, u in sorted(v["agentes"].items(), key=lambda x: -x[1]))
        print(f"  {('#' + c) if c.isdigit() else c:<14} US$ {v['usd']:7.2f}  ({quem})")
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    SAIDA.write_text(json.dumps({
        "gerado": time.strftime("%Y-%m-%d %H:%M"), "dias": dias, "total_usd": round(r["total"], 2),
        "acumulado_usd": round(acum["usd"], 2), "acumulado_desde": acum["desde"], "sessoes_ao_vivo": r["sessoes_ao_vivo"],
        "prs_mergeados": n_prs,
        "usd_por_pr": round(por_pr, 2) if por_pr else None,
        "revisor": {"usd": round(rev["usd"], 2), "revisoes": rev["revisoes"], "achados": rev["achados"]},
        "agentes": {k: round(v["usd"], 2) for k, v in r["agentes"].items()},
        "contexto_medio_mil": {k: round(v["ctx"] / max(1, v["n"]) / 1000) for k, v in r["agentes"].items()},
        "cache_escrito_mil": {k: {"1h": round(v["cw1h"] / 1000), "5m": round(v["cw5m"] / 1000)} for k, v in r["agentes"].items()},
        "cartoes": {k: round(v["usd"], 2) for k, v in r["cartoes"].items()}}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
