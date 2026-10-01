#!/usr/bin/env python
"""Motor de XP do time de agentes (somente biblioteca padrão, zero tokens de agente).

Lê os PRs mergeados do repositório configurado (gh), o Kanban (campo do time), o veredito da revisão e o diff,
pontua cada PR, atribui ao agente e grava dados/xp/placar.json, que o escritório mostra em GET /xp.
Cache incremental em dados/xp/estado.json: PR mergeado já analisado não é buscado de novo; a pontuação é
recalculada a cada execução (barata), o que mantém viva a janela de 14 dias de retrabalho.

Tudo vem do config.json (bloco "xp", "agentes" e "github"); veja a seção "XP, níveis e skills" do INSTALACAO.md.

Uso:  python xp.py                 calcula e grava o placar
      python xp.py --completo      ignora o cache
      python xp.py --liberar N     libera o PR N da auditoria (você revisou a mudança nos testes) e recalcula
      python xp.py --desfazer N    volta a auditar o PR N
"""
import json
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))
import configuracao  # noqa: E402

PASTA_XP = RAIZ / "dados" / "xp"
ESTADO = PASTA_XP / "estado.json"
PLACAR = PASTA_XP / "placar.json"
RESOLVIDAS = PASTA_XP / "auditorias_resolvidas.json"  # PRs que o desenvolvedor liberou da auditoria
GH = configuracao.localizar_gh()

JANELA_DIAS = 14
DESDE_PADRAO_DIAS = 30   # sem "xp.desde" no config, conta os últimos 30 dias
LIMITE_PRS = 300
ULTIMOS = 10
COLUNAS_FINAIS = {"done", "feito", "concluído", "concluido", "closed", "fechado", "finalizado", "entregue"}

RE_TESTE_CITADO = re.compile(r"test|teste|pytest|jest|valida|verifica|sweep|\bci\b", re.I)
RE_SKIP = re.compile(r"@unittest\.skip(?!Unless|If)|pytest\.mark\.(skip|xfail)|pytest\.skip\(|\bxfail\b|"
                     r"\b(it|test|describe)\.(skip|todo)\b|\bx(it|describe|test)\(|\breturn\s*#\s*skip|"
                     r"^\s*#\s*if\s+0\b|^\s*#\s*ifdef\s+DISABLED|@skip\b|@Disabled\b|@Ignore\b", re.I)
RE_FIX = re.compile(r"^\s*(fix|hotfix|bugfix|corrige|correção|correcao)\b|\bfix(es|ed)?\b[^a-z]", re.I)
RE_REVERT = re.compile(r"revert|regress|reverte", re.I)

CFG = configuracao.carregar()
XP = CFG["xp"]
GITHUB = CFG["github"]
PESOS = XP["pesos"]
NIVEIS = XP["niveis"]
RE_ARQ_TESTE = re.compile("|".join(f"(?:{p})" for p in XP["padroes_teste"]), re.I)
PREFIXOS = XP["atribuicao"]["prefixos_branch"]
AGENTE_PADRAO = XP["atribuicao"]["padrao"]
AGENTES_BASE = [a["nome"] for a in CFG["agentes"] if not a["auxiliar"]]


def _saida():
    for f in (sys.stdout, sys.stderr):
        try:
            f.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def gh(args, timeout=90, tentativas=2):
    if not GH:
        raise RuntimeError("GitHub CLI (gh) não encontrado")
    ultimo = ""
    for _ in range(tentativas):
        try:
            r = subprocess.run([GH] + args, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            ultimo = "timeout"
            continue
        out = r.stdout.decode("utf-8", errors="replace")
        if r.returncode == 0:
            return out
        ultimo = r.stderr.decode("utf-8", errors="replace").strip()[:300]
    raise RuntimeError(ultimo or "gh falhou")


def agora():
    return datetime.now(timezone.utc)


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else agora()


def desde():
    return XP["desde"] or (agora() - timedelta(days=DESDE_PADRAO_DIAS)).strftime("%Y-%m-%d")


def carregar(caminho, padrao):
    try:
        return json.loads(Path(caminho).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return padrao


def gravar_json(caminho, obj):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(caminho)


# ---- Fontes ---------------------------------------------------------------------------------------------------
def _campo(item, nome):
    """Valor de um campo do Projects no JSON do gh (as chaves vêm com a 1ª letra minúscula)."""
    if not nome:
        return ""
    for k in (nome, nome.lower(), nome[:1].lower() + nome[1:]):
        if item.get(k) not in (None, ""):
            return item[k]
    return ""


def ler_kanban():
    out = gh(["project", "item-list", str(GITHUB["projeto_numero"]), "--owner", GITHUB["projeto_owner"], "--format",
              "json", "--limit", "500"], timeout=60)
    cartoes = {}
    for i in json.loads(out or "{}").get("items", []):
        c = i.get("content") or {}
        if c.get("number"):
            cartoes[str(c["number"])] = {"time": str(_campo(i, GITHUB["campo_time"]) or ""),
                                         "status": str(i.get("status") or ""), "tipo": c.get("type", "")}
    return cartoes


def listar_prs(repo):
    out = gh(["pr", "list", "-R", repo, "--state", "merged", "--limit", str(LIMITE_PRS), "--search",
              f"merged:>={desde()}", "--json", "number,title,body,headRefName,mergedAt,closingIssuesReferences,labels"],
             timeout=120)
    return json.loads(out or "[]")


def reprovou_revisao(repo, n, shas, cache_status):
    """True se a revisão reprovou o PR: o check configurado (status ou check-run) falhou em algum commit; sem
    check configurado, alguma review pediu mudanças."""
    check = GITHUB["check_revisao"]
    if not check:
        txt = gh(["api", f"repos/{repo}/pulls/{n}/reviews?per_page=100", "--paginate", "--jq",
                  '[.[]|.state]|join(",")'])
        return "CHANGES_REQUESTED" in txt.upper()
    for sha in shas:
        k = f"{check}:{sha}"
        if k not in cache_status:
            nome = check.replace('"', "")
            a = gh(["api", f"repos/{repo}/commits/{sha}/statuses?per_page=100", "--jq",
                    f'[.[]|select(.context=="{nome}")|.state]|join(",")'])
            b = gh(["api", f"repos/{repo}/commits/{sha}/check-runs?per_page=100", "--jq",
                    f'[.check_runs[]|select(.name=="{nome}")|.conclusion]|join(",")'])
            cache_status[k] = (a.strip() + "," + b.strip()).lower()
        if re.search(r"failure|error|timed_out|cancelled", cache_status[k]):
            return True
    return False


def buscar_pr(repo, pr, cache_status):
    """Fatos caros de um PR mergeado (commits, revisão, diff). Erros levantam exceção."""
    n = pr["number"]
    bruto = gh(["api", f"repos/{repo}/pulls/{n}/commits?per_page=100", "--paginate", "--jq",
                '.[]|"\\(.sha) \\(.parents|length)"'])
    commits = [l.split() for l in bruto.splitlines() if l.strip()]
    shas = [c[0] for c in commits]
    merges = [c[0] for c in commits if int(c[1]) > 1]
    merge_no_meio = any(s != shas[-1] for s in merges) if shas else False
    reprovado = reprovou_revisao(repo, n, shas, cache_status)
    apaga, skips = analisar_diff(repo, n)
    return {"commits": len(shas), "merge_no_meio": merge_no_meio, "reprovado_revisao": reprovado,
            "apaga_teste": apaga, "skip_teste": skips}


def analisar_diff(repo, n):
    """Procura apagamento de arquivo de teste e skip/xfail incondicional acrescentado em teste. Devolve (apagados, skips).
    Apagar teste é aceito (consolidação) quando o mesmo PR cria arquivo(s) de teste novo(s) com pelo menos as mesmas
    linhas; skip condicional por ambiente (skipUnless/skipIf) não conta."""
    try:
        diff = gh(["pr", "diff", str(n), "-R", repo], timeout=120)
        arquivos = {}  # nome -> {"novo":bool,"apagado":bool,"mais":[linhas +],"menos":int}
        atual = None
        for linha in diff.splitlines():
            if linha.startswith("diff --git "):
                m = re.match(r"diff --git a/(.*) b/(.*)$", linha)
                atual = m.group(2) if m else None
                if atual and RE_ARQ_TESTE.search(atual):
                    arquivos[atual] = {"novo": False, "apagado": False, "mais": [], "menos": 0}
                else:
                    atual = None
            elif atual is None:
                continue
            elif linha.startswith("new file mode"):
                arquivos[atual]["novo"] = True
            elif linha.startswith("deleted file mode"):
                arquivos[atual]["apagado"] = True
            elif linha.startswith("+") and not linha.startswith("+++"):
                arquivos[atual]["mais"].append(linha[1:])
            elif linha.startswith("-") and not linha.startswith("---"):
                arquivos[atual]["menos"] += 1
    except RuntimeError:  # diff grande demais para o gh: cai para a lista de arquivos da API
        bruto = gh(["api", f"repos/{repo}/pulls/{n}/files?per_page=100", "--paginate", "--jq",
                    '.[]|{f:.filename,s:.status,p:(.patch//"")}'])
        arquivos = {}
        for l in bruto.splitlines():
            if not l.strip():
                continue
            a = json.loads(l)
            if RE_ARQ_TESTE.search(a["f"]):
                linhas = a["p"].splitlines()
                arquivos[a["f"]] = {"novo": a["s"] == "added", "apagado": a["s"] == "removed",
                                    "mais": [x[1:] for x in linhas if x.startswith("+")],
                                    "menos": sum(1 for x in linhas if x.startswith("-"))}
    apagados = [f for f, d in arquivos.items() if d["apagado"]]
    criado = sum(len(d["mais"]) for d in arquivos.values() if d["novo"])
    removido = sum(d["menos"] for f, d in arquivos.items() if d["apagado"])
    if apagados and criado >= removido:
        apagados = []
    skips = [f for f, d in arquivos.items() if not d["apagado"] and any(RE_SKIP.search(x) for x in d["mais"])]
    return apagados, skips


# ---- Atribuição -----------------------------------------------------------------------------------------------
def mapa_times():
    """Valor do campo do time (ou rótulo do PR) -> agente. Valor vazio no config = cartão de humano, ignorado."""
    saida = {}
    for k, v in (GITHUB.get("times") or {}).items():
        saida[configuracao.chave(k)] = configuracao._agente_canonico(CFG["agentes"], v) if v else None
    return saida


TIMES = mapa_times()


def atribuir(pr, cartoes):
    """Devolve (agente|None, fonte, cartao|None). agente None = ignorado (cartão atribuído a um humano)."""
    titulo, corpo, branch = pr.get("title") or "", pr.get("body") or "", pr.get("headRefName") or ""
    bl = branch.lower()
    n = pr["number"]

    def por_cartao(num, fonte):
        c = cartoes.get(str(num))
        if not c or str(num) == str(n):
            return None
        k = configuracao.chave(c["time"])
        if k not in TIMES:
            return None  # cartão sem time conhecido: segue para as outras regras
        return (TIMES[k], fonte, int(num))

    for i in pr.get("closingIssuesReferences") or []:  # (a) cartão fechado pelo PR
        r = por_cartao(i["number"], f"cartão fechado #{i['number']}")
        if r:
            return r
    for m in re.finditer(r"(?:closes|fixes|resolves)\s+#(\d+)", corpo, re.I):  # "Closes #n" (PR fora da base padrão)
        r = por_cartao(m.group(1), f"Closes #{m.group(1)} no corpo")
        if r:
            return r
    cit = re.findall(r"#(\d+)", titulo) + re.findall(r"^[a-z\-]+/(\d+)-", bl) + re.findall(r"#(\d+)", corpo)
    for num in cit:  # (b) "#n" no título, no branch (feat/225-x) e no corpo, nessa ordem
        r = por_cartao(num, f"#{num} citado")
        if r:
            return r
    for rotulo in pr.get("labels") or []:  # (c) rótulo do PR igual a um valor de github.times
        k = configuracao.chave(rotulo.get("name"))
        if k in TIMES and TIMES[k]:
            return (TIMES[k], f"rótulo {rotulo.get('name')}", None)
    for pref, agente in PREFIXOS.items():  # (d) prefixo do branch (xp.atribuicao.prefixos_branch)
        if bl.startswith(pref):
            return (agente, f"branch {pref}", None)
    return (AGENTE_PADRAO or None, "padrão (resto)", None)


# ---- Pontuação ------------------------------------------------------------------------------------------------
def e_fix(pr):
    return bool(RE_FIX.search(pr["title"]) or pr["headRefName"].lower().startswith(("fix/", "hotfix/", "bugfix/")))


def citacoes_posteriores(pr, todos):
    """PRs posteriores, até JANELA_DIAS depois do merge, que citam '#N' deste PR: (fix_ou_revert, revert)."""
    n, fim = pr["number"], ts(pr["mergedAt"])
    padrao = re.compile(rf"(?<![\w/]){'#' + str(n)}(?!\d)")
    fix = rev = False
    for o in todos:
        if o["number"] <= n or ts(o["mergedAt"]) < fim or ts(o["mergedAt"]) - fim > timedelta(days=JANELA_DIAS):
            continue
        texto = (o["title"] or "") + "\n" + (o["body"] or "")
        if not padrao.search(texto):
            continue
        if RE_REVERT.search(o["title"] or "") or re.search(r"\b(reverts?|regress\w*)\b", o["body"] or "", re.I):
            rev = True
        elif e_fix(o):
            fix = True
    return fix, rev


def cartao_feito(c):
    final = str((GITHUB.get("colunas") or [""])[-1]).strip().lower()
    st = str((c or {}).get("status") or "").strip().lower()
    return bool(st) and (st in COLUNAS_FINAIS or st == final)


def pontuar(pr, fatos, atrib, cartoes, todos, resolvidas):
    agente, fonte, cartao = atrib
    pts, motivos = 0, []
    fim = ts(pr["mergedAt"])
    janela_fechada = agora() - fim >= timedelta(days=JANELA_DIAS)
    fix_dep, rev_dep = citacoes_posteriores(pr, todos)
    retrabalho = False
    P = PESOS
    reprovado = fatos.get("reprovado_revisao", False)
    manip = []
    if fatos["apaga_teste"]:
        manip.append("apaga arquivo de teste: " + ", ".join(fatos["apaga_teste"][:3]))
    if fatos["skip_teste"]:
        manip.append("acrescenta skip/xfail em teste: " + ", ".join(fatos["skip_teste"][:3]))
    if manip and pr["number"] in resolvidas:
        manip = []
    if manip:
        return {"pr": pr["number"], "titulo": pr["title"], "agente": agente, "fonte": fonte, "pontos": 0,
                "motivos": ["manipulação de teste: pontos zerados"], "auditoria": "; ".join(manip), "data": pr["mergedAt"],
                "aprovado_primeira": not reprovado, "retrabalho": False}
    if not reprovado:
        pts += P["aprovado_de_primeira"]
        motivos.append(f"aprovado de primeira {P['aprovado_de_primeira']:+d}")
    else:
        retrabalho = True
    if not fatos["merge_no_meio"] and RE_TESTE_CITADO.search(pr.get("body") or ""):
        pts += P["sem_conflito_com_testes"]
        motivos.append(f"sem conflito com testes citados {P['sem_conflito_com_testes']:+d}")
    if cartao is not None and cartao_feito(cartoes.get(str(cartao))):
        pts += P["cartao_fechado"]
        motivos.append(f"cartão fechado {P['cartao_fechado']:+d}")
    if rev_dep:
        pts += P["regressao"]
        motivos.append(f"regressão (revert/regress posterior) {P['regressao']:+d}")
    elif fix_dep:
        retrabalho = True
    if retrabalho:
        pts += P["retrabalho"]
        motivos.append(f"reprovado/retrabalho {P['retrabalho']:+d}")
    if e_fix(pr) and not fix_dep and not rev_dep and janela_fechada:
        pts += P["bug_nao_voltou_14d"]
        motivos.append(f"bug não voltou em 14 dias {P['bug_nao_voltou_14d']:+d}")
    return {"pr": pr["number"], "titulo": pr["title"], "agente": agente, "fonte": fonte, "pontos": pts, "motivos": motivos,
            "auditoria": "", "data": pr["mergedAt"], "aprovado_primeira": not reprovado,
            "retrabalho": retrabalho or rev_dep}


# ---- Skills ---------------------------------------------------------------------------------------------------
def pontos_skills():
    """Devolve {agente: {'pontos':N,'motivos':[...],'autor':[nomes],'reusadas':N}} a partir de skills.py e dos eventos."""
    try:
        import skills
    except Exception:
        return {}
    res = {}

    def a(ag):
        return res.setdefault(ag, {"pontos": 0, "motivos": [], "autor": [], "reusadas": 0})

    autores = {}
    for _p, m, _c in skills.candidatos():
        autor = m.get("autor") or "?"
        autores[m["name"]] = autor
        x = a(autor)
        x["autor"].append(m["name"])
        if m.get("estado") == "aprovado":
            x["pontos"] += PESOS["skill_promovida"]
            x["motivos"].append(f"skill promovida '{m['name']}' {PESOS['skill_promovida']:+d}")
        for u in m.get("usos", []):
            if u.get("agente") and u["agente"] != autor and u.get("resultado") == "ok":
                x["pontos"] += PESOS["skill_reusada_por_outro"]
                x["reusadas"] += 1
                x["motivos"].append(f"{u['agente']} usou '{m['name']}' {PESOS['skill_reusada_por_outro']:+d}")
    for _t, agente, nome in skills.eventos_skill():
        autor = autores.get(nome)
        if autor and agente != autor:
            x = a(autor)
            x["pontos"] += PESOS["skill_reusada_por_outro"]
            x["reusadas"] += 1
            x["motivos"].append(f"{agente} usou '{nome}' {PESOS['skill_reusada_por_outro']:+d}")
    return res


def nivel_de(xp):
    atual = NIVEIS[0]
    for n in NIVEIS:
        if xp >= n["xp"]:
            atual = n
    prox = next((n["xp"] for n in NIVEIS if n["xp"] > xp), None)
    return atual, prox


def novo_agente():
    return {"xp": 0, "prs": 0, "ultimos": [], "auditoria": [], "skills_autor": [], "skills_reusadas_por_outros": 0}


# ---- Principal ------------------------------------------------------------------------------------------------
def liberar(argv):
    """--liberar N / --desfazer N: mexe na lista de PRs liberados da auditoria."""
    desfazer = "--desfazer" in argv
    flag = "--desfazer" if desfazer else "--liberar"
    try:
        n = int(argv[argv.index(flag) + 1].lstrip("#"))
    except (IndexError, ValueError):
        print(f"uso: xp.py {flag} <número do PR>")
        return 2
    lista = set(carregar(RESOLVIDAS, []))
    if desfazer:
        lista.discard(n)
    else:
        lista.add(n)
    gravar_json(RESOLVIDAS, sorted(lista))
    print(f"PR #{n} {'volta a ser auditado' if desfazer else 'liberado da auditoria'}.")
    return 0


def main():
    _saida()
    if not XP["ativo"]:
        print('XP desligado: ponha "xp": {"ativo": true} no config.json (ou rode instalar.py de novo).')
        return 0
    if "--liberar" in sys.argv or "--desfazer" in sys.argv:
        liberar(sys.argv)
    t0 = time.time()
    completo = "--completo" in sys.argv
    repo = GITHUB["repo"]
    estado = {} if completo else carregar(ESTADO, {})
    assinatura = json.dumps([repo, GITHUB["check_revisao"], XP["padroes_teste"]], ensure_ascii=False)
    if estado.get("assinatura") != assinatura:   # repositório, check ou padrões de teste mudaram: refaz tudo
        estado = {"assinatura": assinatura}
    fatos_cache = estado.get("prs", {})
    status_cache = estado.get("status", {})
    avisos = []
    cartoes = {}
    if GITHUB["projeto_owner"] and GITHUB["projeto_numero"]:
        try:
            cartoes = ler_kanban()
            estado["kanban"] = cartoes
        except Exception as e:
            cartoes = estado.get("kanban", {})
            avisos.append(f"Kanban indisponível ({str(e)[:80]}); usando o último conhecido")
    prs = []
    if not repo:
        avisos.append("github.repo não configurado: só as skills pontuam")
    else:
        try:
            prs = listar_prs(repo)
        except Exception as e:
            avisos.append(f"PRs indisponíveis ({str(e)[:100]}); só as skills pontuam")
    novos = [p for p in prs if str(p["number"]) not in fatos_cache]

    def tarefa(p):
        try:
            return p["number"], buscar_pr(repo, p, status_cache), None
        except Exception as e:
            return p["number"], None, str(e)[:120]

    with ThreadPoolExecutor(max_workers=6) as ex:
        for n, fatos, erro in ex.map(tarefa, novos):
            if fatos:
                fatos_cache[str(n)] = fatos
            else:
                avisos.append(f"PR #{n} não analisado ({erro}); tenta de novo na próxima")
    estado["prs"], estado["status"] = fatos_cache, status_cache
    gravar_json(ESTADO, estado)

    resolvidas = set(carregar(RESOLVIDAS, []))
    agentes = {a: novo_agente() for a in AGENTES_BASE}
    resultados, ignorados = [], 0
    for pr in sorted(prs, key=lambda p: p["mergedAt"]):
        fatos = fatos_cache.get(str(pr["number"]))
        if not fatos:
            continue
        atrib = atribuir(pr, cartoes)
        if atrib[0] is None:
            ignorados += 1
            continue
        r = pontuar(pr, fatos, atrib, cartoes, prs, resolvidas)
        resultados.append(r)
        ag = agentes.setdefault(r["agente"], novo_agente())
        ag["xp"] += r["pontos"]
        ag["prs"] += 1
        ag["ultimos"].append({"pr": r["pr"], "pontos": r["pontos"], "motivos": r["motivos"], "data": r["data"],
                              "titulo": r["titulo"][:90], "fonte": r["fonte"]})
        if r["auditoria"]:
            ag["auditoria"].append({"pr": r["pr"], "motivo": r["auditoria"]})
    for nome, s in pontos_skills().items():
        nome = configuracao._agente_canonico(CFG["agentes"], nome) or nome
        ag = agentes.setdefault(nome, novo_agente())
        ag["xp"] += s["pontos"]
        ag["skills_autor"] = s["autor"]
        ag["skills_reusadas_por_outros"] = s["reusadas"]
        if s["pontos"]:
            ag["ultimos"].append({"pr": None, "pontos": s["pontos"], "motivos": s["motivos"][-5:],
                                  "data": agora().isoformat(timespec="seconds"), "titulo": "skills", "fonte": "skills"})
    for ag in agentes.values():
        ag["xp"] = max(0, ag["xp"])
        n, prox = nivel_de(ag["xp"])
        ag["nivel"], ag["titulo_nivel"], ag["xp_proximo"] = n["nivel"], n["titulo"], prox
        ag["ultimos"] = sorted(ag["ultimos"], key=lambda u: u["data"], reverse=True)[:ULTIMOS]
    n = len(resultados) or 1
    placar = {
        "atualizado": agora().astimezone().isoformat(timespec="seconds"),
        "regras": dict(PESOS, janela_retrabalho_dias=JANELA_DIAS, desde=desde()),
        "niveis": NIVEIS,
        "time": {"xp_total": sum(a["xp"] for a in agentes.values()), "prs_pontuados": len(resultados),
                 "aprovacao_primeira": round(sum(1 for r in resultados if r["aprovado_primeira"]) / n, 3),
                 "retrabalho_14d": round(sum(1 for r in resultados if r["retrabalho"]) / n, 3),
                 "auditorias_abertas": sum(len(a["auditoria"]) for a in agentes.values()),
                 "prs_ignorados": ignorados},
        "agentes": agentes,
    }
    if avisos:
        placar["avisos"] = avisos
    gravar_json(PLACAR, placar)

    t = placar["time"]
    print(f"XP do time: {t['xp_total']} em {t['prs_pontuados']} PRs pontuados ({ignorados} ignorados, cartões de humanos), "
          f"{time.time() - t0:.1f}s, {len(novos)} PRs novos buscados.")
    print(f"Aprovação de primeira {t['aprovacao_primeira']:.0%} | retrabalho/regressão em 14 d {t['retrabalho_14d']:.0%} | "
          f"auditorias abertas {t['auditorias_abertas']}.")
    for nome, a in sorted(agentes.items(), key=lambda kv: -kv[1]["xp"]):
        print(f"  {nome}: {a['xp']} XP, nível {a['nivel']} {a['titulo_nivel']}, {a['prs']} PRs")
    for nome, a in agentes.items():
        for x in a["auditoria"]:
            print(f"  AUDITORIA {nome} PR #{x['pr']}: {x['motivo']}  (liberar: python xp.py --liberar {x['pr']})")
    for av in avisos[:3]:
        print("  aviso:", av)
    return 0


if __name__ == "__main__":
    sys.exit(main())
