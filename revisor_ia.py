# -*- coding: utf-8 -*-
"""Revisor de código próprio ([revisor-ia]): revisão automática de cada commit novo de PR, com o contexto do seu projeto.

Por quê: os bots de revisão de terceiros (Codex, Copilot...) revisam sem conhecer as regras do projeto, parte das
sugestões é falso positivo, e a cota deles acaba. Este revisor lê só o diff do PR + os arquivos de contexto que você
indicar (padrões de código, lições aprendidas, glossário), numa chamada `claude -p` (padrão Sonnet, sem ferramentas), e
comenta no PR pela sua conta do `gh`, com a marca [revisor-ia]. O sugestoes_bot.py reconhece a marca e tudo segue o
fluxo de sempre (caixa, triagem, --pronto, painel do escritório). Não substitui a revisão humana nem um portão de
arquitetura: é a camada de código (bug, regressão, teste faltando, regra do projeto quebrada) — não estilo.

Configuração (config.json), bloco "revisor":
  {"ativo": false, "modelo": "claude-sonnet-5-5", "max_diff": 90000, "contexto": ["docs/PADROES.md", "..."]}
  - ativo: o servidor do escritório roda a revisão dos PRs pendentes antes de cada coleta das sugestões;
  - contexto: arquivos com padrões/lições/glossário (caminho absoluto ou relativo a cada pasta de "projetos");
    o glossario_triagem.md do pacote entra também, se existir;
  - o repositório vem de github.repo.

Uso: python revisor_ia.py --pr 12             revisa o commit atual do PR (se ainda não revisado)
     python revisor_ia.py --pendentes         revisa todo PR aberto cujo commit atual ainda não foi revisado
     python revisor_ia.py --pr 12 --forcar    revisa de novo o mesmo commit
     python revisor_ia.py --pr 12 --seco      só mostra os achados, sem comentar no PR
     python revisor_ia.py --local <worktree> [--base origin/main]   revisa o diff da worktree ANTES do PR (não comenta)
Estado (commits revisados, custo e tokens de cada revisão) em dados/revisor/estado.json (fora do git); o custo_time.py
soma esse custo ao do time.

Re-revisão (commit novo num PR já revisado) converge em vez de recomeçar: o modelo recebe as conversas anteriores do PR
(achados + respostas: corrigido, falso positivo e o motivo) e não pode repetir achado já respondido; P2/P3 só valem em
linha adicionada desde o último commit revisado (P0/P1 valem em qualquer lugar). Sem isso, cada commit de correção gera
uma rodada nova de P2/P3 sobre código que não mudou e o PR nunca fica pronto. Teto: a partir da 4ª revisão do mesmo PR,
só P0/P1 (critério de parada do avaliador-otimizador).

Estado final contra o aceite: o corpo das issues citadas no PR (`Closes #n`/`Parte de #n` no começo da linha, até 2) entra
na entrada como "# Aceite do cartão"; o modelo verifica primeiro se o diff cumpre o aceite e se há prova (teste) dele.
"""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))
import configuracao as _pacote  # noqa: E402
import sugestoes_bot  # noqa: E402  (gh_api, _achar_claude, _json_da_resposta, configuracao)

MARCA = sugestoes_bot.MARCA_REVISOR
PASTA = RAIZ / "dados" / "revisor"
ESTADO = PASTA / "estado.json"
MAX_ACHADOS = 12
MAX_POR_CONTEXTO = 12_000    # caracteres por arquivo de contexto
MAX_CONTEXTO = 40_000        # caracteres de contexto no total
TIMEOUT = 600
IGNORAR = re.compile(r"\.(png|jpe?g|gif|webp|ico|svg|tga|exr|psd|fbx|obj|glb|gltf|blend|uasset|umap|npz|npy|parquet|"
                     r"zip|gz|7z|tar|pdf|bin|exe|dll|so|dylib|wav|mp3|ogg|mp4|mov|ttf|otf|woff2?)$"
                     r"|\.lock$|(^|/)(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|poetry\.lock|Cargo\.lock)$"
                     r"|\.min\.(js|css)$", re.I)


def opcoes():
    """Bloco "revisor" do config.json já normalizado (configuracao.normalizar_revisor) + projetos."""
    c = _pacote.carregar()
    r = dict(c["revisor"])
    r["projetos"] = list(c["projetos"])
    return r


def prompt():
    return (
        "Você é o revisor de código deste projeto. Não use ferramentas. Receberá o contexto do projeto (padrões de código, "
        "glossário, lições aprendidas, regras) e o diff de um pull request. Aponte SÓ problemas reais e específicos: bug, "
        "regressão, condição de corrida, caso de borda não tratado, cache/chave incremental incompleta, passo que sobrescreve "
        "outro, contagem incoerente, erro de I/O/concorrência, teste faltando para o que mudou, contrato/formato quebrado, "
        "segurança, documentação/README que ficou errada em relação ao código novo, ou violação das regras do projeto "
        "descritas no contexto. Seja minucioso: percorra CADA função alterada e pergunte, para cada uma: (1) que entrada de "
        "borda quebra isto (vazio, None, limite, sobreposição, arquivo truncado)? (2) se há cache/chave incremental, ela "
        "inclui TUDO o que muda a saída? (3) um passo posterior pode sobrescrever ou desfazer o resultado de um anterior? "
        "(4) a contagem/estatística continua coerente com o que é gravado? (5) erros de I/O ou concorrência deixam lixo ou "
        "estado errado? (6) há teste para o caminho novo? Aponte o que encontrar com evidência no diff. NÃO aponte estilo, "
        "nomes, comentários, preferências nem o que o contexto diz ser correto. Cada achado precisa citar uma linha que "
        "EXISTE no lado novo do diff (as marcadas com + ou de contexto dentro de um hunk). Responda SOMENTE com um array "
        f"JSON (vazio só se de fato não houver nada), sem markdown, até {MAX_ACHADOS} itens, cada um: "
        "{\"arquivo\": \"caminho/igual/ao/diff\", \"linha\": <número no arquivo novo>, \"prioridade\": \"P0|P1|P2|P3\", "
        "\"titulo\": \"<até 90 caracteres, em português>\", \"texto\": \"<o problema, o efeito concreto e a correção "
        "sugerida, até 600 caracteres, em português>\"}. P0 = quebra o produto/dados ou perde trabalho; P1 = bug provável; "
        "P2 = defeito em caso de borda ou teste faltando; P3 = melhoria pequena mas real. "
        "Se vier \"# Aceite do cartão\", PRIMEIRO verifique se o diff cumpre esse aceite (estado final, não o processo): se "
        "não cumpre, ou se não há teste/prova no PR que o demonstre, isso é P1 — ou P2 quando o PR é \"Parte de\" e a parte "
        "que falta está declarada no corpo do PR.")


RE_FECHA = re.compile(r"(?im)^[ \t]*(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)[ \t]*:?[ \t]*#(\d+)\b")
RE_PARTE = re.compile(r"(?im)^[ \t]*(?:parte[ \t]+de|part[ \t]+of)[ \t]*:?[ \t]*#(\d+)\b")
MAX_CARTOES = 2
TETO_REVISOES = 3            # a partir da 4ª revisão do mesmo PR, só P0/P1 (critério de parada do avaliador)


def cartoes_do_corpo(corpo):
    """[(n, "Closes"|"Parte de")] citados no começo da linha, na ordem, sem repetir, no máximo MAX_CARTOES."""
    vistos, out = set(), []
    marcas = [(m.start(), int(m.group(1)), "Closes") for m in RE_FECHA.finditer(corpo or "")]
    marcas += [(m.start(), int(m.group(1)), "Parte de") for m in RE_PARTE.finditer(corpo or "")]
    for _, n, tipo in sorted(marcas):
        if n not in vistos:
            vistos.add(n)
            out.append((n, tipo))
    return out[:MAX_CARTOES]


def aceite_dos_cartoes(cfg, repo, corpo):
    """Texto "# Aceite do cartão #n (tipo)" com o corpo de cada issue citada (1 REST por cartão)."""
    partes = []
    for n, tipo in cartoes_do_corpo(corpo):
        iss = gh(cfg, f"repos/{repo}/issues/{n}") or {}
        if iss.get("pull_request") or not iss.get("title"):
            continue
        partes.append(f"# Aceite do cartão #{n} ({tipo}): {iss['title']}\n{(iss.get('body') or '')[:2000]}")
    return "\n\n".join(partes)


def gh(cfg, caminho):
    return sugestoes_bot.gh_api(cfg, caminho)[1]


def ler_estado():
    try:
        return json.loads(ESTADO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"revisados": {}, "historico": []}


def gravar_estado(est):
    PASTA.mkdir(parents=True, exist_ok=True)
    tmp = ESTADO.with_suffix(".tmp")
    tmp.write_text(json.dumps(est, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(ESTADO)


def arquivos_contexto(op):
    """Caminhos dos arquivos de contexto que existem: cada item de revisor.contexto (absoluto, ou relativo a cada pasta
    de "projetos") e o glossario_triagem.md do pacote. Sem repetição, na ordem do config."""
    vistos, saida = set(), []
    candidatos = []
    for item in op.get("contexto") or []:
        p = Path(os.path.expandvars(os.path.expanduser(str(item))))
        candidatos += [p] if p.is_absolute() else [Path(base) / p for base in op.get("projetos") or []]
    candidatos.append(sugestoes_bot.GLOSSARIO)
    for p in candidatos:
        try:
            chave = str(p.resolve()).casefold()
        except OSError:
            continue
        if chave not in vistos and p.is_file():
            vistos.add(chave)
            saida.append(p)
    return saida


def contexto_projeto(op):
    partes, total = [], 0
    for p in arquivos_contexto(op):
        try:
            texto = p.read_text(encoding="utf-8", errors="replace")[:MAX_POR_CONTEXTO]
        except OSError:
            continue
        if total + len(texto) > MAX_CONTEXTO:
            texto = texto[:max(0, MAX_CONTEXTO - total)]
        if not texto:
            break
        partes.append(f"## {p.name}\n{texto}")
        total += len(texto)
    return "\n\n".join(partes) or "(sem arquivos de contexto: configure revisor.contexto no config.json)"


def linhas_novas(patch):
    """Números de linha do lado novo que aparecem no patch (adicionadas ou de contexto): onde um comentário pode ir."""
    ok, n = set(), 0
    for l in (patch or "").splitlines():
        m = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", l)
        if m:
            n = int(m.group(1))
            continue
        if l.startswith("-"):
            continue
        if l.startswith("+") or l.startswith(" "):
            ok.add(n)
            n += 1
    return ok


def montar_diff(arquivos, max_diff):
    diff, fora, validas = [], [], {}
    total = 0
    for f in arquivos:
        nome, patch = f.get("filename", ""), f.get("patch")
        if IGNORAR.search(nome) or not patch:
            fora.append(nome)
            continue
        bloco = f"### {nome} ({f.get('status')})\n{patch}\n"
        if total + len(bloco) > max_diff:
            fora.append(nome)
            continue
        diff.append(bloco)
        total += len(bloco)
        validas[nome] = linhas_novas(patch)
    return "".join(diff), fora, validas


def linhas_adicionadas(patch):
    """Números de linha do lado novo marcadas com "+" no patch (o que de fato mudou)."""
    ok, n = set(), 0
    for l in (patch or "").splitlines():
        m = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", l)
        if m:
            n = int(m.group(1))
            continue
        if l.startswith("-"):
            continue
        if l.startswith("+"):
            ok.add(n)
        n += 1
    return ok


def mudou_desde(cfg, repo, antes, depois):
    """{arquivo: linhas adicionadas} entre o último commit revisado e o atual, ou None (sem revisão anterior ou
    histórico reescrito: aí vale a revisão completa)."""
    if not antes:
        return None
    cmp_ = gh(cfg, f"repos/{repo}/compare/{antes}...{depois}") or {}
    if cmp_.get("status") != "ahead" or not isinstance(cmp_.get("files"), list):
        return None
    return {f.get("filename", ""): linhas_adicionadas(f.get("patch")) for f in cmp_["files"]}


def conversas_anteriores(cfg, repo, n, limite=9000):
    """Achados anteriores do revisor neste PR e as respostas dadas em cada conversa (texto compacto para o prompt)."""
    coms, pagina = [], 1
    while True:
        lote = gh(cfg, f"repos/{repo}/pulls/{n}/comments?per_page=100&page={pagina}") or []
        coms += lote
        if len(lote) < 100 or pagina >= 10:
            break
        pagina += 1
    respostas = {}
    for c in coms:
        if c.get("in_reply_to_id"):
            respostas.setdefault(c["in_reply_to_id"], []).append(c.get("body") or "")
    linhas = []
    for c in coms:
        corpo = c.get("body") or ""
        if c.get("in_reply_to_id") or MARCA not in corpo:
            continue
        titulo = corpo.split("\n", 1)[0].strip("* ")
        resp = " / ".join(r.replace("\n", " ")[:300] for r in respostas.get(c["id"], [])) or "(sem resposta)"
        linhas.append(f"- {c.get('path')}:{c.get('line') or c.get('original_line')} — {titulo[:120]} → resposta: {resp}")
    texto = "\n".join(linhas)
    return texto[-limite:]


def revisar_com_claude(modelo, contexto, cabecalho, diff, anteriores="", mudou=None):
    exe = sugestoes_bot._achar_claude()
    if not exe:
        raise RuntimeError("comando `claude` não encontrado no PATH")
    entrada = f"# Contexto do projeto\n{contexto}\n\n# Pull request\n{cabecalho}\n\n"
    if anteriores:
        entrada += ("# Revisões anteriores deste PR (achados já feitos e a resposta de cada um)\n"
                    "NÃO repita nenhum destes, nem com outras palavras: os corrigidos já foram tratados e os respondidos como "
                    "falso positivo foram aceitos pelo time. Só volte a um deles se o commit novo o quebrou de novo (P0/P1).\n"
                    f"{anteriores}\n\n")
    if mudou is not None:
        entrada += ("# O que mudou desde a última revisão (linhas adicionadas, lado novo)\n"
                    + "\n".join(f"- {a}: {len(l)} linha(s)" for a, l in mudou.items() if l)
                    + "\nEsta é uma RE-REVISÃO: P2/P3 só em linha adicionada desde a última revisão; P0/P1 em qualquer lugar.\n\n")
    entrada += f"# Diff\n{diff}"
    cmd = [exe, "-p", "--model", modelo, "--tools", "", "--strict-mcp-config", "--disable-slash-commands",
           "--no-session-persistence", "--output-format", "json", "--system-prompt", prompt()]
    r = subprocess.run(cmd, input=entrada.encode("utf-8"), capture_output=True, timeout=TIMEOUT, cwd=str(RAIZ),
                       env=dict(os.environ, PYTHONUTF8="1"))
    saida = r.stdout.decode("utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError((r.stderr.decode("utf-8", errors="replace") or saida).strip()[-300:] or "claude falhou")
    env = json.loads(saida)
    if env.get("is_error"):
        raise RuntimeError(str(env.get("result"))[:300])
    return sugestoes_bot._json_da_resposta(env.get("result")), env


def corpo_comentario(a, modelo):
    return (f"**{a['prioridade']} — {a['titulo'][:90]}**\n\n{a['texto'][:800]}\n\n"
            f"<sub>{MARCA} revisão automática ({modelo}); trate pelo `sugestoes_bot.py`.</sub>")


def revisar(n, forcar=False, seco=False, log=print):
    cfg = sugestoes_bot.configuracao()
    op = opcoes()
    repo, modelo = cfg["repo"], op["modelo"]
    if not repo:
        return "revisor: github.repo não configurado"
    pr = gh(cfg, f"repos/{repo}/pulls/{n}") or {}
    if pr.get("state") != "open":
        return f"#{n}: PR não está aberto"
    cabeca = pr["head"]["sha"]
    est = ler_estado()
    if not forcar and cabeca in est["revisados"].get(str(n), []):
        return f"#{n}: commit {cabeca[:8]} já revisado"
    PASTA.mkdir(parents=True, exist_ok=True)
    trava = PASTA / f"pr{n}-{cabeca[:12]}.lock"
    try:
        fd = os.open(trava, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
    except FileExistsError:
        if time.time() - trava.stat().st_mtime < TIMEOUT + 60:
            return f"#{n}: revisão do {cabeca[:8]} já em andamento"
        trava.unlink(missing_ok=True)
        return revisar(n, forcar, seco, log)
    try:
        arquivos, pagina = [], 1
        while True:
            lote = gh(cfg, f"repos/{repo}/pulls/{n}/files?per_page=100&page={pagina}") or []
            arquivos += lote
            if len(lote) < 100 or pagina >= 30:
                break
            pagina += 1
        diff, fora, validas = montar_diff(arquivos, op["max_diff"])
        antes = [s for s in est["revisados"].get(str(n), []) if s != cabeca]
        mudou = mudou_desde(cfg, repo, antes[-1] if antes else None, cabeca)
        descartados = 0
        if not diff:
            achados, env = [], {}
        else:
            cab = (f"#{n} {pr.get('title', '')}\nBranch {pr['head']['ref']} -> {pr['base']['ref']}\n"
                   f"Corpo do PR:\n{(pr.get('body') or '')[:3000]}")
            aceite = aceite_dos_cartoes(cfg, repo, pr.get("body") or "")
            if aceite:
                cab += "\n\n" + aceite
            anteriores = conversas_anteriores(cfg, repo, n) if antes else ""
            try:
                achados, env = revisar_com_claude(modelo, contexto_projeto(op), cab, diff, anteriores, mudou)
            except ValueError as e:   # JSON mal formado do modelo: uma nova tentativa antes de desistir
                log(f"#{n}: resposta do modelo sem JSON válido ({str(e)[:80]}); tentando de novo")
                achados, env = revisar_com_claude(modelo, contexto_projeto(op), cab, diff, anteriores, mudou)
        em_linha, no_corpo = [], []
        for a in achados if isinstance(achados, list) else []:
            if not isinstance(a, dict) or not a.get("titulo") or not a.get("texto"):
                continue
            a["prioridade"] = a.get("prioridade") if a.get("prioridade") in ("P0", "P1", "P2", "P3") else "P3"
            try:
                linha = int(a.get("linha"))
            except (TypeError, ValueError):
                linha = None
            if a["prioridade"] in ("P2", "P3") and (len(antes) >= TETO_REVISOES or (
                    mudou is not None and linha not in mudou.get(a.get("arquivo"), set()))):
                descartados += 1     # re-revisão: P2/P3 fora do que mudou (ou depois do teto) não reabre o PR
                continue
            if a.get("arquivo") in validas and linha in validas[a["arquivo"]]:
                em_linha.append({"path": a["arquivo"], "line": linha, "side": "RIGHT", "body": corpo_comentario(a, modelo)})
            else:
                no_corpo.append(a)
        resumo = [f"{MARCA} {'Re-revisão' if mudou is not None else 'Revisão'} automática do commit `{cabeca[:8]}` ({modelo}): "
                  + (f"{len(em_linha) + len(no_corpo)} achado(s)." if (em_linha or no_corpo) else "nenhum problema encontrado.")]
        if len(antes) >= TETO_REVISOES:
            resumo.append(f"\n<sub>{len(antes) + 1}ª revisão deste PR: só P0/P1 a partir da {TETO_REVISOES + 1}ª"
                          + (f" ({descartados} P2/P3 descartado(s))" if descartados else "") + ".</sub>")
        elif mudou is not None:
            resumo.append(f"\n<sub>Re-revisão: P2/P3 só no que mudou desde `{antes[-1][:8]}`"
                          + (f" ({descartados} fora disso descartado(s))" if descartados else "") + ".</sub>")
        for a in no_corpo:
            resumo.append(f"\n- **{a['prioridade']} — {a['titulo'][:90]}** (`{a.get('arquivo')}:{a.get('linha')}`): {a['texto'][:600]}")
        if fora:
            resumo.append(f"\n<sub>Não revisados (binário, gerado ou acima de {op['max_diff'] // 1000} mil caracteres): "
                          + ", ".join(f"`{f}`" for f in fora[:15]) + (" …" if len(fora) > 15 else "") + "</sub>")
        if seco:
            return json.dumps({"em_linha": em_linha, "no_corpo": no_corpo, "fora": fora, "descartados": descartados,
                               "re_revisao": mudou is not None}, ensure_ascii=False, indent=1)
        corpo = {"commit_id": cabeca, "event": "COMMENT", "body": "\n".join(resumo), "comments": em_linha}
        r = subprocess.run([cfg["gh"], "api", "-X", "POST", f"repos/{repo}/pulls/{n}/reviews", "--input", "-"],
                           input=json.dumps(corpo).encode("utf-8"), capture_output=True)
        if r.returncode != 0:
            raise RuntimeError("falha ao comentar no PR: " + r.stderr.decode("utf-8", errors="replace")[:300])
        est["revisados"].setdefault(str(n), []).append(cabeca)
        est["revisados"][str(n)] = est["revisados"][str(n)][-20:]
        uso = env.get("usage") or {}
        est["historico"] = (est.get("historico", []) + [{
            "pr": n, "commit": cabeca[:12], "quando": time.strftime("%Y-%m-%d %H:%M"), "achados": len(em_linha) + len(no_corpo),
            "modelo": modelo, "custo_usd": env.get("total_cost_usd"), "tokens_entrada": (uso.get("input_tokens") or 0)
            + (uso.get("cache_creation_input_tokens") or 0) + (uso.get("cache_read_input_tokens") or 0)}])[-200:]
        gravar_estado(est)
        return (f"#{n}: commit {cabeca[:8]} revisado — {len(em_linha)} comentário(s) em linha, {len(no_corpo)} no corpo"
                + (f", US$ {env.get('total_cost_usd'):.3f}" if env.get("total_cost_usd") else ""))
    finally:
        trava.unlink(missing_ok=True)


def pendentes(log=print):
    """Revisa todo PR aberto (não rascunho) cujo commit atual ainda não foi revisado. Devolve uma linha por PR tratado."""
    cfg = sugestoes_bot.configuracao()
    if not cfg["repo"]:
        return ["revisor: github.repo não configurado"]
    est = ler_estado()
    saida = []
    for p in gh(cfg, f"repos/{cfg['repo']}/pulls?state=open&per_page=50") or []:
        if p.get("draft") or p["head"]["sha"] in est["revisados"].get(str(p["number"]), []):
            continue
        try:
            saida.append(revisar(p["number"], log=log))
        except Exception as e:   # um PR com problema não impede os outros
            saida.append(f"#{p['number']}: ERRO {type(e).__name__}: {str(e)[:200]}")
    return saida


def revisar_local(wt, base=None):
    """Revisão ANTES do PR: o mesmo prompt e contexto sobre o diff `base...HEAD` da worktree, sem comentar no GitHub nem
    gravar estado. Achado resolvido aqui não vira rodada de PR. Base padrão: o branch padrão do origin."""
    def git(*args):
        r = subprocess.run(["git", "-C", wt, *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
        return r.stdout
    op = opcoes()
    if not base:
        base = (git("symbolic-ref", "--short", "refs/remotes/origin/HEAD").strip() or "origin/main")
    arquivos = []
    for linha in git("diff", "--name-status", f"{base}...HEAD").splitlines():
        partes = linha.split("\t")
        if len(partes) < 2:
            continue
        nome = partes[-1]
        estado = {"A": "added", "D": "removed"}.get(partes[0][:1], "modified")
        patch = git("diff", f"{base}...HEAD", "--", nome)
        patch = patch[patch.find("@@"):] if "@@" in patch else ""     # só os hunks, como no pulls/files da API
        arquivos.append({"filename": nome, "status": estado, "patch": patch})
    diff, fora, _ = montar_diff(arquivos, op["max_diff"])
    if not diff:
        return f"nada para revisar (sem diff em relação a {base})"
    ramo = git("rev-parse", "--abbrev-ref", "HEAD").strip()
    commits = git("log", "--format=- %s", f"{base}..HEAD")[:3000]
    cab = f"(revisão local, antes do PR) branch {ramo} -> {base}\nCommits:\n{commits}"
    achados, env = revisar_com_claude(op["modelo"], contexto_projeto(op), cab, diff)
    linhas = []
    for a in achados if isinstance(achados, list) else []:
        if isinstance(a, dict):
            linhas.append(f"{a.get('prioridade', 'P3')} {a.get('arquivo')}:{a.get('linha')} — {a.get('titulo')}\n"
                          f"    {str(a.get('texto', ''))[:500]}")
    saida = "\n".join(linhas) or "nenhum problema encontrado"
    custo = env.get("total_cost_usd")
    if custo:
        saida += f"\n(custo US$ {custo:.3f})"
    if fora:
        saida += "\nnão revisados: " + ", ".join(fora[:10])
    return saida


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    a = sys.argv[1:]
    if "--local" in a and a.index("--local") + 1 < len(a):
        base = a[a.index("--base") + 1] if "--base" in a and a.index("--base") + 1 < len(a) else None
        print(revisar_local(a[a.index("--local") + 1], base))
        return 0
    if "--pendentes" in a:
        for l in pendentes() or ["nenhum PR aberto com commit novo"]:
            print(l)
        return 0
    if "--pr" not in a or a.index("--pr") + 1 >= len(a):
        print(__doc__)
        return 2
    print(revisar(int(a[a.index("--pr") + 1]), forcar="--forcar" in a, seco="--seco" in a))
    return 0


if __name__ == "__main__":
    sys.exit(main())
