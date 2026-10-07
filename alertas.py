"""Alertas do escritório: avisa o desenvolvedor quando há algo esperando por ele (somente biblioteca padrão + push.py).

O detector roda numa thread a cada 60 s, usa os dados que o servidor já tem (PRs em cache, placar de XP, eventos,
escalonamentos) e compara com o estado guardado em dados/alertas_estado.json para NÃO repetir o mesmo alerta.
Cada alerta novo vai para a fila dados/alertas.jsonl (últimos 200), para o Web Push (push.py) e, no Windows e se
ligado, para um toast do sistema. A página lê a fila em GET /api/alertas?desde=<id>.

Tipos: pr_pronto, pr_problema, auditoria, conferir, escalonamento, pergunta, lembrete, sugestao (sugestão P0/P1 do bot de
revisão; fonte "sugestoes"), cota (fonte "cota"), duplicado (o mesmo trabalho em duas branches/PRs), circulo (agente no ciclo editar → rodar → editar), pr_parado (PR aberto sem
atualização há mais de N h) — fonte "saude", de saude.py — e "teste" (do botão de teste).
Orçamento de atenção ("Oversight Has a Capacity", arXiv 2606.08919: avisar demais cansa e piora a supervisão): só os tipos em
`imediatos` vão na hora para o push/toast; os outros entram na fila marcados `resumo` (a página lista sem pop-up) e saem num
único push de resumo `resumo_horas` depois do 1º aviso pendente. A contagem por dia (imediatos x resumo) vai em GET /api/alertas (`hoje`).
Na primeira leitura de cada fonte o estado só é registrado (baseline): o que já existia não vira alerta.
"""
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import push as _push
import saude as _saude

MAX_FILA = 200
INTERVALO = 60                 # s entre leituras do detector
REPETICAO_PR = 1800            # s: o mesmo alerta de PR não se repete antes disso (checks que piscam)
LEMBRETE_INTERVALO = 86400     # no máximo 1 lembrete por dia
PAINEIS = {"prs": "/#alerta=prs", "placar": "/#alerta=placar"}

TIPOS = [
    {"id": "pr_pronto", "rotulo": "PR pronto para o seu merge", "padrao": True, "painel": "prs"},
    {"id": "pr_problema", "rotulo": "PR com conflito ou reprovado", "padrao": True, "painel": "prs"},
    {"id": "auditoria", "rotulo": "Auditoria vermelha nova no placar", "padrao": True, "painel": "placar"},
    {"id": "conferir", "rotulo": "Item novo para conferir", "padrao": False, "painel": "placar"},
    {"id": "escalonamento", "rotulo": "Escalonamento do Diretor aberto ou fechado", "padrao": True, "painel": ""},
    {"id": "pergunta", "rotulo": "Pergunta de escopo do Diretor", "padrao": True, "painel": ""},
    {"id": "lembrete", "rotulo": "Lembrete de PR pronto esperando há mais de 24 h", "padrao": True, "painel": "prs"},
    {"id": "sugestao", "rotulo": "Sugestão P0/P1 nova do bot de revisão", "padrao": True, "painel": "prs"},
    {"id": "cota", "rotulo": "Cota do GitHub baixa", "padrao": True, "painel": "prs"},
    {"id": "duplicado", "rotulo": "Trabalho duplicado (mesma tarefa em duas branches ou PRs)", "padrao": True, "painel": "prs"},
    {"id": "circulo", "rotulo": "Agente andando em círculos (edita e roda o mesmo de novo)", "padrao": True, "painel": ""},
    {"id": "pr_parado", "rotulo": "PR aberto parado (sem atualização há mais de parado_horas)", "padrao": True, "painel": "prs"},
]
IMEDIATOS_PADRAO = ["pr_pronto", "pr_problema", "pergunta", "escalonamento", "auditoria", "cota"]
REPETICAO_CIRCULO = 7200       # s: o mesmo agente em círculo no mesmo arquivo não alerta de novo antes disso
DIAS_CONTAGEM = 14
PADROES = {t["id"]: t["padrao"] for t in TIPOS}
OPCOES_PADRAO = {"ativo": True, "lembrete_horas": 24, "limite_push_hora": 20, "toast_windows": False,
                 "contato": _push.CONTATO_PADRAO, "tipos": dict(PADROES), "agentes_pergunta": [],
                 "imediatos": list(IMEDIATOS_PADRAO), "resumo_horas": 3, "parado_horas": 24}


def tipos_publicos(opcoes):
    """Lista de tipos para a página, com o padrão de cada um já vindo das opções do servidor."""
    return [dict(t, padrao=bool(opcoes["tipos"].get(t["id"], t["padrao"]))) for t in TIPOS]


def normalizar_opcoes(bruto):
    """Opções com tipos corrigidos e padrões; nunca levanta exceção por valor ruim."""
    o = json.loads(json.dumps(OPCOES_PADRAO))
    if isinstance(bruto, dict):
        o["ativo"] = bruto.get("ativo") is not False
        o["toast_windows"] = bruto.get("toast_windows") is True
        for k, minimo, maximo in (("lembrete_horas", 1, 24 * 14), ("limite_push_hora", 1, 200), ("resumo_horas", 1, 24),
                                  ("parado_horas", 1, 24 * 14)):
            try:
                o[k] = max(minimo, min(maximo, int(bruto[k]))) if k in bruto else o[k]
            except (TypeError, ValueError):
                pass
        if isinstance(bruto.get("contato"), str) and re.fullmatch(r"(mailto:[^\s@]+@[^\s@]+|https://[^\s]+)", bruto["contato"]):
            o["contato"] = bruto["contato"]
        if isinstance(bruto.get("tipos"), dict):
            for k in PADROES:
                if k in bruto["tipos"]:
                    o["tipos"][k] = bruto["tipos"][k] is True
        if isinstance(bruto.get("agentes_pergunta"), list):
            o["agentes_pergunta"] = [str(a).strip().lower() for a in bruto["agentes_pergunta"] if str(a).strip()]
        if isinstance(bruto.get("imediatos"), list):
            o["imediatos"] = [k for k in PADROES if k in bruto["imediatos"]]
    return o


# ---------------------------------------------------------------- detector (puro: não faz E/S)
def situacao_pr(pr, sugestoes=None):
    """pronto | conflito | reprovado | espera (mesma regra do painel de PRs, `situacao` do prs.js).
    sugestoes: o GET /api/sugestoes do servidor (`sugestoes_bot.resumo()` + "pronto", o PRONTO da thread de validações).
    Revisão aprovada só vira "pronto" sem sugestão segurando o merge e, com bots/revisor configurados (`ativo`), com o
    --pronto OK calculado para o commit atual do PR. Sem sugestões configuradas (ou sem a fonte), vale só a revisão."""
    if pr.get("rascunho"):
        return "espera"
    if pr.get("conflito"):
        return "conflito"
    g = str(pr.get("revisao") or pr.get("guardiao") or "").upper()
    if g == "SUCCESS":
        sg = sugestoes if isinstance(sugestoes, dict) else {}
        n = str(pr.get("numero"))
        if (sg.get("seguram_merge") or {}).get(n):
            return "espera"
        p = (sg.get("pronto") or {}).get(n)
        if sg.get("ativo") and (not isinstance(p, dict) or (pr.get("sha") and p.get("sha") and p["sha"] != pr["sha"])):
            return "espera"
        if isinstance(p, dict) and not p.get("ok"):
            return "espera"
        return "pronto"
    if g in ("FAILURE", "ERROR"):
        return "reprovado"
    return "espera"


def _lista_prs(nums, limite=6):
    nums = sorted(nums)
    txt = ", ".join(f"#{n}" for n in nums[:limite])
    return txt + (f" e mais {len(nums) - limite}" if len(nums) > limite else "")


def _alerta(tipo, titulo, corpo, chave, detalhe=""):
    painel = next((t["painel"] for t in TIPOS if t["id"] == tipo), "")
    return {"tipo": tipo, "titulo": titulo, "corpo": corpo, "detalhe": detalhe, "chave": chave, "url": PAINEIS.get(painel, "/")}


def _repetido(est, chave, agora, janela):
    """True se o alerta com essa chave já saiu há menos de `janela` s. Registra o instante quando não repete."""
    ult = est.setdefault("ultimo", {})
    if agora - ult.get(chave, 0) < janela:
        return True
    ult[chave] = agora
    return False


def _detectar_prs(est, d, agora, opc, novos, sugestoes=None):
    base = est.setdefault("base", {})
    registro, atual = est.setdefault("prs", {}), {}
    primeira = not base.get("prs")
    prontos, problemas, titulos = [], {}, {}
    for pr in d["prs"]:
        if not isinstance(pr, dict) or not isinstance(pr.get("numero"), int):
            continue
        n, s = pr["numero"], situacao_pr(pr, sugestoes)
        ant = registro.get(str(n))
        antes = ant.get("s") if ant else None
        atual[str(n)] = {"s": s, "desde": ((ant.get("desde") or agora) if antes == "pronto" else agora) if s == "pronto" else 0}
        titulos[n] = str(pr.get("titulo") or "")
        if primeira:
            continue
        if s == "pronto" and antes != "pronto":
            prontos.append(n)
        elif s in ("conflito", "reprovado") and antes != s:
            problemas[n] = s
    est["prs"], base["prs"] = atual, True   # PRs que sumiram (mergeados/fechados) saem do estado
    prontos = [n for n in prontos if not _repetido(est, f"pr_pronto:{n}", agora, REPETICAO_PR)]
    problemas = {n: s for n, s in problemas.items() if not _repetido(est, f"pr_problema:{n}:{s}", agora, REPETICAO_PR)}
    if prontos:
        um = len(prontos) == 1
        novos.append(_alerta("pr_pronto", "PR pronto para o seu merge" if um else f"{len(prontos)} PRs prontos para o seu merge",
                             (f"PR #{prontos[0]} foi aprovado e está sem conflito. Falta o seu merge." if um
                              else f"{_lista_prs(prontos)} foram aprovados e estão sem conflito. Faltam os seus merges."),
                             "pr_pronto:" + ",".join(map(str, sorted(prontos))),
                             "; ".join(f"#{n} {titulos[n]}" for n in sorted(prontos))[:300]))
    if problemas:
        partes = []
        for n, s in sorted(problemas.items()):
            partes.append(f"PR #{n} com conflito" if s == "conflito" else f"PR #{n} reprovado na revisão")
        novos.append(_alerta("pr_problema", "PR com conflito ou reprovado" if len(problemas) == 1 else f"{len(problemas)} PRs com problema",
                             "; ".join(partes[:4]) + (f" e mais {len(partes) - 4}" if len(partes) > 4 else "") + ".",
                             "pr_problema:" + ",".join(f"{n}{s[0]}" for n, s in sorted(problemas.items())),
                             "; ".join(f"#{n} {titulos[n]}" for n in sorted(problemas))[:300]))
    # lembrete: PR pronto esperando há mais de N horas, no máximo 1 vez por dia
    limite = opc["lembrete_horas"] * 3600
    velhos = [int(n) for n, r in atual.items() if r["s"] == "pronto" and r["desde"] and agora - r["desde"] > limite]
    if velhos and agora - est.get("lembrete", 0) >= LEMBRETE_INTERVALO:
        est["lembrete"] = agora
        um = len(velhos) == 1
        novos.append(_alerta("lembrete", "Lembrete: PR esperando o seu merge",
                             (f"PR #{velhos[0]} está pronto há mais de {opc['lembrete_horas']} h." if um
                              else f"{_lista_prs(velhos)} estão prontos há mais de {opc['lembrete_horas']} h."),
                             "lembrete:" + time.strftime("%Y-%m-%d", time.localtime(agora))))


def _prs_do_placar(placar, campo):
    return {x.get("pr") for a in placar["agentes"].values() if isinstance(a, dict)
            for x in (a.get(campo) or []) if isinstance(x, dict) and isinstance(x.get("pr"), int)}


def _detectar_placar(est, placar, agora, novos):
    base = est.setdefault("base", {})
    for campo, titulo_um, titulo_n, corpo_um in (
            ("auditoria", "Auditoria vermelha nova", "{n} auditorias vermelhas novas", "PR #{n} teve os pontos zerados e precisa da sua revisão."),
            ("conferir", "Novo item para conferir", "{n} itens novos para conferir", "PR #{n} entrou na lista Para conferir.")):
        atuais = _prs_do_placar(placar, campo)
        novos_prs = sorted(atuais - set(est.get(campo, [])))
        est[campo] = sorted(atuais)   # quem sai da lista (resolvido) e voltar depois alerta de novo
        if novos_prs and base.get(campo):
            um = len(novos_prs) == 1
            novos.append(_alerta(campo, titulo_um if um else titulo_n.format(n=len(novos_prs)),
                                 corpo_um.format(n=novos_prs[0]) if um else f"{_lista_prs(novos_prs)}: veja o Placar.",
                                 f"{campo}:" + ",".join(map(str, novos_prs))))
        base[campo] = True


def _detectar_escalonamentos(est, registro, novos):
    base = est.setdefault("base", {})
    vistos = est.setdefault("esc", {})
    atuais = {}
    for semana, itens in registro.items():
        for it in itens if isinstance(itens, list) else []:
            if isinstance(it, dict) and it.get("cartao") is not None:
                atuais[f"{semana}:{it['cartao']}:{it.get('aberto', '')}"] = (it, "fechado" if it.get("fechado") else "aberto")
    for chave, (it, status) in atuais.items():
        if base.get("esc") and vistos.get(chave) != status:
            card = _push.sanear(str(it["cartao"]), 20)
            if status == "aberto":
                novos.append(_alerta("escalonamento", "Escalonamento aberto", f"O Diretor abriu um escalonamento no cartão {card}.",
                                     f"esc:{chave}:aberto", _push.sanear(it.get("motivo", ""), 200)))
            else:
                novos.append(_alerta("escalonamento", "Escalonamento fechado", f"O escalonamento do cartão {card} foi fechado.",
                                     f"esc:{chave}:fechado", _push.sanear(it.get("resultado", ""), 200)))
    est["esc"] = {c: s for c, (_, s) in atuais.items()}
    base["esc"] = True


def _detectar_saude(est, sd, agora, novos):
    """Fonte "saude" (saude.resumo): duplicados fortes novos, agentes em círculo e PRs parados. Alerta já na 1ª leitura
    (como a cota): é um fato do presente que custa tokens enquanto ninguém olha, não uma novidade a ignorar."""
    # sem "duplicados"/"parados" (GitHub fora do ar: só os círculos) o estado deles fica como está (sem alerta repetido depois)
    fortes = [d for d in (sd.get("duplicados") or {}).get("fortes") or [] if isinstance(d, dict) and d.get("branches")]
    chaves = {",".join(d["branches"]): d for d in fortes}
    antes = set(est.get("dup", []))
    novas = [d for k, d in sorted(chaves.items()) if k not in antes] if "duplicados" in sd else []
    if "duplicados" in sd:
        est["dup"] = sorted(chaves)   # o que sumiu (juntado, fechado) e voltar alerta de novo
    if novas:
        um = len(novas) == 1
        novos.append(_alerta("duplicado", "Trabalho duplicado" if um else f"{len(novas)} trabalhos duplicados",
                             (f"{novas[0]['motivo'][:1].upper()}{novas[0]['motivo'][1:]}: {' e '.join(novas[0]['branches'][:3])}." if um else
                              "; ".join(d["motivo"] for d in novas[:3]) + "."),
                             "duplicado:" + ";".join(sorted(",".join(d["branches"]) for d in novas))[:200],
                             "; ".join(", ".join(d["branches"]) for d in novas)[:300]))
    for c in sd.get("circulos") or []:
        if not isinstance(c, dict) or _repetido(est, f"circulo:{c.get('agente')}:{c.get('arquivo')}", agora, REPETICAO_CIRCULO):
            continue
        quem = _push.sanear(str(c.get("agente") or "?"), 30)
        novos.append(_alerta("circulo", f"{quem} andando em círculos",
                             f"{quem} editou {_push.sanear(str(c.get('arquivo')), 40)} {c.get('edicoes')} vezes e rodou o mesmo "
                             f"comando {c.get('comandos')} vezes em {_saude.JANELA_CIRCULO_MIN} min. Vale parar e repensar a causa.",
                             f"circulo:{c.get('agente')}:{c.get('arquivo')}:{int(agora // REPETICAO_CIRCULO)}",
                             _push.sanear(str(c.get("comando") or ""), 200)))
    vistos = est.setdefault("parado", {})   # {PR: atualizado já avisado}; só esquece quando o PR fecha
    if isinstance(sd.get("abertos"), list):
        abertos = {str(n) for n in sd["abertos"]}
        for n in [n for n in vistos if n not in abertos]:
            del vistos[n]
    for x in sd.get("parados") or []:
        if not isinstance(x, dict) or not isinstance(x.get("numero"), int):
            continue
        n, quando = str(x["numero"]), str(x.get("atualizado") or "")
        if vistos.get(n) != quando:
            vistos[n] = quando
            novos.append(_alerta("pr_parado", f"PR #{n} parado há {x.get('horas')} h",
                                 f"Ninguém mexeu no PR #{n} há {x.get('horas')} h: retomar, fechar ou pedir ajuda ao líder.",
                                 f"pr_parado:{n}:{quando}", _push.sanear(str(x.get("titulo") or ""), 200)))


PRIORIDADES_ALERTA = ("P0", "P1")


def _detectar_sugestoes(est, resumo, novos):
    """Sugestão P0/P1 nova do bot de revisão (sugestoes_bot.resumo(): só as abertas). Na 1ª leitura só registra."""
    base = est.setdefault("base", {})
    itens = [x for x in resumo["itens"] if isinstance(x, dict) and x.get("id") is not None and x.get("prioridade") in PRIORIDADES_ALERTA]
    atuais = sorted({str(x["id"]) for x in itens})
    ids_novos = set(atuais) - set(est.get("sug", []))
    est["sug"] = atuais   # quem sai (tratada, PR fechado) e voltar depois alerta de novo
    if ids_novos and base.get("sug"):
        novas = [x for x in itens if str(x["id"]) in ids_novos]
        prios = sorted({x["prioridade"] for x in novas})
        prs_ = sorted({x["pr"] for x in novas if isinstance(x.get("pr"), int)})
        um = len(novas) == 1
        titulo = f"Sugestão {prios[0]} do bot de revisão" if um else f"{len(novas)} sugestões {'/'.join(prios)} do bot de revisão"
        corpo = (f"O bot apontou uma sugestão {prios[0]} no PR #{prs_[0]}." if um and prs_ else
                 f"O bot apontou {len(novas)} sugestões {'/'.join(prios)} em {_lista_prs(prs_) or 'PRs abertos'}.")
        novos.append(_alerta("sugestao", titulo, corpo, "sugestao:" + ",".join(sorted(ids_novos))[:120],
                             "; ".join(f"#{x.get('pr')} {x['prioridade']} {x.get('titulo', '')}" for x in novas)[:300]))
    base["sug"] = True


def _detectar_cota(est, cota, novos):
    """Cota do GitHub baixa (cota.Vigia.resumo()): um alerta por janela de 1 h e por recurso (GraphQL/REST) quando restam menos
    de 20% do limite. A 1ª leitura também alerta (cota baixa é fato do presente, não novidade a ignorar)."""
    avisados = est.setdefault("cota", {})   # {recurso: reset da janela já avisada}
    for chave, rotulo in (("graphql", "GraphQL"), ("core", "REST")):
        r = cota.get(chave)
        if not isinstance(r, dict) or not all(isinstance(r.get(k), int) for k in ("limit", "remaining", "reset")) or r["limit"] <= 0:
            continue
        if r["remaining"] < 0.2 * r["limit"] and avisados.get(chave) != r["reset"]:
            avisados[chave] = r["reset"]
            volta = time.strftime("%H:%M", time.localtime(r["reset"]))
            esgotada = r["remaining"] <= 0
            novos.append(_alerta("cota", f"Cota do GitHub baixa ({rotulo})",
                                 (f"A cota {rotulo} do GitHub esgotou; volta às {volta}." if esgotada else
                                  f"Restam {r['remaining']} de {r['limit']} pontos {rotulo} do GitHub; a cota volta às {volta}."),
                                 f"cota:{chave}:{r['reset']}",
                                 "Prefira a API REST (gh api repos/...) e leituras em lote a gh pr/issue --json e gh project."))
    for chave in list(avisados):
        if chave not in ("graphql", "core"):
            del avisados[chave]


def eh_pergunta(texto):
    t = str(texto or "").strip()
    return t.upper().startswith("PERGUNTA") or "pergunta ao desenvolvedor" in t.lower()


def _detectar_eventos(est, total, eventos, opc, novos):
    base = est.setdefault("base", {})
    if base.get("eventos") and total >= est.get("eventos", 0):
        for ev in eventos:
            if not isinstance(ev, dict) or ev.get("tipo") != "fala":
                continue
            texto = ev.get("texto") or ev.get("resumo") or ""
            quem = str(ev.get("agente") or "").strip()
            if not eh_pergunta(texto) or (opc["agentes_pergunta"] and quem.lower() not in opc["agentes_pergunta"]):
                continue
            novos.append(_alerta("pergunta", "Pergunta de escopo para você", "Há uma pergunta esperando a sua resposta"
                                 + (f" ({_push.sanear(quem, 30)})." if quem else "."), f"pergunta:{ev.get('ts', '')}:{quem}",
                                 str(texto).strip()[:300]))
    est["eventos"], base["eventos"] = total, True


def detectar(est, entradas, agora, opc):
    """Compara as entradas com o estado `est` (alterado no lugar) e devolve a lista de alertas novos (sem id/ts).
    entradas: {"prs": dict do /prs, "placar": dict do /xp, "eventos": (total, [eventos novos]), "escalonamentos": dict,
    "sugestoes": dict do /api/sugestoes (com "pronto"), "cota": dict do vigia da cota}.
    Fonte ausente, com erro ou vazia por falha não apaga o estado (nada de alerta falso quando o gh cai)."""
    novos = []
    d, sg = entradas.get("prs"), entradas.get("sugestoes")
    # com bots/revisor ativos, o PRONTO ainda não calculado (logo depois de reiniciar) não conta: sem ele todo PR aprovado
    # viraria "espera" e voltaria a "pronto" na rodada seguinte, repetindo o pr_pronto e zerando o lembrete
    esperando_pronto = isinstance(sg, dict) and sg.get("ativo") and sg.get("pronto_carregado") is False
    if (isinstance(d, dict) and not d.get("erro") and d.get("configurado") is not False and isinstance(d.get("prs"), list)
            and not esperando_pronto):
        _detectar_prs(est, d, agora, opc, novos, sg if isinstance(sg, dict) else None)
    p = entradas.get("placar")
    if isinstance(p, dict) and not p.get("erro") and p.get("ativo") is not False and isinstance(p.get("agentes"), dict):
        _detectar_placar(est, p, agora, novos)
    e = entradas.get("escalonamentos")
    if isinstance(e, dict):
        _detectar_escalonamentos(est, e, novos)
    ev = entradas.get("eventos")
    if isinstance(ev, tuple) and len(ev) == 2:
        _detectar_eventos(est, ev[0], ev[1], opc, novos)
    if isinstance(sg, dict) and sg.get("ativo") is not False and isinstance(sg.get("itens"), list):
        _detectar_sugestoes(est, sg, novos)
    ct = entradas.get("cota")
    if isinstance(ct, dict):
        _detectar_cota(est, ct, novos)
    sd = entradas.get("saude")
    if isinstance(sd, dict) and not sd.get("erro"):
        _detectar_saude(est, sd, agora, novos)
    ult = est.get("ultimo", {})   # esquece chaves com mais de 2 dias
    est["ultimo"] = {k: v for k, v in ult.items() if agora - v < 2 * 86400}
    return novos


# ---------------------------------------------------------------- serviço (E/S, fila, envio)
_TOAST_PS = (
    "$ErrorActionPreference='Stop';"
    "[Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,ContentType=WindowsRuntime]|Out-Null;"
    "$x=[Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
    "$t=$x.GetElementsByTagName('text');"
    "$t.Item(0).AppendChild($x.CreateTextNode($env:OFFICE_ALERTA_T))|Out-Null;"
    "$t.Item(1).AppendChild($x.CreateTextNode($env:OFFICE_ALERTA_C))|Out-Null;"
    "$n=[Windows.UI.Notifications.ToastNotification]::new($x);"
    "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe').Show($n)")


def toast_windows(titulo, corpo, esperar=False):
    """Toast do Windows via PowerShell (sem dependências). Título e corpo vão por variáveis de ambiente (nada é
    interpretado como comando). Devolve o código de saída quando `esperar`, senão None. Só no Windows."""
    if sys.platform != "win32":
        return None
    env = dict(os.environ, OFFICE_ALERTA_T=_push.sanear(titulo, 60), OFFICE_ALERTA_C=_push.sanear(corpo, 120))
    try:
        p = subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", _TOAST_PS],
                             env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return p.wait(timeout=30) if esperar else None
    except (OSError, subprocess.SubprocessError):
        return -1


class Alertas:
    """Fila, estado e entrega. `fontes`: {"prs": fn(), "placar": fn(), "eventos": fn(desde) -> (total, lista),
    "escalonamentos": fn() ou None}. `titulo`: fn() com o nome do escritório (vai no título do push)."""

    def __init__(self, pasta_dados, fontes, opcoes=None, titulo=lambda: "Escritório", rede=None, enviar_http=None):
        self.pasta = Path(pasta_dados)
        self.fontes, self.titulo, self.rede = fontes, titulo, rede
        self.opcoes = normalizar_opcoes(opcoes)
        self.push = _push.Push(self.pasta, self.opcoes["contato"], self.opcoes["limite_push_hora"], enviar_http)
        self.arq_estado, self.arq_fila = self.pasta / "alertas_estado.json", self.pasta / "alertas.jsonl"
        self.trava = threading.RLock()
        self.estado = self._ler_estado()

    # ------------------------------------------------------------ estado e fila
    def _ler_estado(self):
        try:
            e = json.loads(self.arq_estado.read_text(encoding="utf-8"))
            return e if isinstance(e, dict) else {}
        except (OSError, ValueError):
            return {}

    def _gravar_estado(self):
        self.pasta.mkdir(parents=True, exist_ok=True)
        tmp = self.arq_estado.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.estado, ensure_ascii=False, indent=1), encoding="utf-8")
        _push.trocar_arquivo(tmp, self.arq_estado)

    def _fila(self):
        try:
            linhas = self.arq_fila.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        saida = []
        for t in linhas:
            try:
                x = json.loads(t)
            except ValueError:
                continue
            if isinstance(x, dict) and isinstance(x.get("id"), int):
                saida.append(x)
        return saida[-MAX_FILA:]

    def listar(self, desde=0):
        """(alertas com id > desde, último id)."""
        fila = self._fila()
        ultimo = max([x["id"] for x in fila] + [self.estado.get("proximo_id", 1) - 1])
        return [x for x in fila if x["id"] > desde], ultimo

    def _entrar_na_fila(self, alerta, agora):
        with self.trava:
            alerta = dict(alerta, id=self.estado.get("proximo_id", 1), ts=round(agora, 1))
            self.estado["proximo_id"] = alerta["id"] + 1
            fila = self._fila() + [alerta]
            self.pasta.mkdir(parents=True, exist_ok=True)
            tmp = self.arq_fila.with_suffix(".tmp")
            tmp.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in fila[-MAX_FILA:]), encoding="utf-8")
            _push.trocar_arquivo(tmp, self.arq_fila)
        return alerta

    # ------------------------------------------------------------ entrega
    def _payload_do_alerta(self, alerta):
        """Só o necessário (o Web Push sanitiza de novo): o título leva o nome do escritório."""
        return dict(alerta, titulo=f"{self.titulo()}: {alerta['titulo']}"[:_push.LIMITE_TITULO])

    def entregar(self, alerta, so_aparelho=None, ignorar_tipos=False):
        """Web Push (e toast do Windows, se ligado). Devolve o resultado do envio."""
        res = self.push.enviar(self._payload_do_alerta(alerta), so_aparelho, self.opcoes["tipos"], ignorar_tipos)
        if self.opcoes["toast_windows"] and self.opcoes["tipos"].get(alerta["tipo"], alerta["tipo"] == "teste"):
            toast_windows(alerta["titulo"], alerta["corpo"])
        return res

    def alerta_teste(self, aparelho):
        """Alerta do botão de teste: entra na fila (a página mostra) e vai ao push só do aparelho que pediu."""
        with self.trava:
            a = self._entrar_na_fila({"tipo": "teste", "titulo": "Alerta de teste", "corpo": "Se você está vendo isto, os alertas funcionam.",
                                      "detalhe": "", "chave": "teste", "url": "/"}, time.time())
            self._gravar_estado()
        if self.opcoes["toast_windows"]:
            toast_windows(a["titulo"], a["corpo"])
        return a, self.push.enviar(self._payload_do_alerta(a), so_aparelho=aparelho, ignorar_tipos=True)

    # ------------------------------------------------------------ ciclo
    def passo(self, agora=None):
        """Uma leitura do detector. Devolve os alertas que saíram. Falha de uma fonte não derruba as outras."""
        agora = time.time() if agora is None else agora
        ent = {}
        for nome in ("prs", "placar", "escalonamentos", "sugestoes", "cota", "saude"):
            fn = self.fontes.get(nome)
            if fn:
                try:
                    ent[nome] = fn()
                except Exception as e:   # fonte fora do ar: segue sem ela
                    print(f"[alertas] fonte {nome}: {str(e)[:120]}", flush=True)
        if self.fontes.get("eventos"):
            try:
                ent["eventos"] = self.fontes["eventos"](self.estado.get("eventos", 0))
            except Exception as e:
                print(f"[alertas] fonte eventos: {str(e)[:120]}", flush=True)
        with self.trava:
            novos = [dict(a, resumo=a["tipo"] not in self.opcoes["imediatos"]) for a in detectar(self.estado, ent, agora, self.opcoes)]
            saida = [self._entrar_na_fila(a, agora) for a in novos]
            self._contar([a for a in saida if self.opcoes["tipos"].get(a["tipo"])], agora)
            pend = self.estado.setdefault("resumo_pendente", [])
            pend += [{"tipo": a["tipo"], "titulo": a["titulo"]} for a in saida if a["resumo"]]
            if pend and "resumo_desde" not in self.estado:
                self.estado["resumo_desde"] = agora   # a janela do resumo começa no 1º aviso de rotina (ou no estado antigo sem ela)
            resumo = self._fechar_resumo(agora)
            self._gravar_estado()
        if resumo:
            try:
                r = self.push.enviar(self._payload_do_alerta(resumo), padroes=self.opcoes["tipos"])
                if self.opcoes["toast_windows"] and any(self.opcoes["tipos"].get(t) for t in resumo["tipos"]):
                    toast_windows(resumo["titulo"], resumo["corpo"])
                print(f"[alertas] resumo: {resumo['corpo'][:80]} (push: {r['enviados']} enviado(s))", flush=True)
            except Exception as e:
                print(f"[alertas] resumo falhou: {str(e)[:120]}", flush=True)
        for a in [x for x in saida if not x["resumo"]]:
            try:
                r = self.entregar(a)
                print(f"[alertas] {a['tipo']}: {a['corpo'][:80]} (push: {r['enviados']} enviado(s), {r['falhas']} falha(s), "
                      f"{r['limitados']} limitado(s))", flush=True)
            except Exception as e:
                print(f"[alertas] entrega falhou: {str(e)[:120]}", flush=True)
        if self.rede is not None:
            try:
                self.push.podar([d["id"] for d in self.rede.listar()])
            except Exception:
                pass
        return saida

    def _contar(self, saida, agora):
        """Contagem por dia (imediatos x resumo) dos últimos DIAS_CONTAGEM dias, para medir o volume de avisos."""
        cont = self.estado.setdefault("contagem", {})
        dia = time.strftime("%Y-%m-%d", time.localtime(agora))
        c = cont.setdefault(dia, {"imediatos": 0, "resumo": 0})
        for a in saida:
            c["resumo" if a["resumo"] else "imediatos"] += 1
        for d in sorted(cont)[:-DIAS_CONTAGEM]:
            del cont[d]

    def hoje(self, agora=None):
        """{"imediatos": n, "resumo": m} de hoje (GET /api/alertas)."""
        dia = time.strftime("%Y-%m-%d", time.localtime(time.time() if agora is None else agora))
        return dict({"imediatos": 0, "resumo": 0}, **self.estado.get("contagem", {}).get(dia, {}))

    def _fechar_resumo(self, agora):
        """Junta os avisos de rotina pendentes num só (tipo "resumo", com `tipos` para o filtro de cada aparelho)
        resumo_horas depois do 1º aviso pendente; None se ainda não é hora ou não há nada. Não entra na fila: cada aviso
        já está lá."""
        pend = self.estado.get("resumo_pendente") or []
        if not pend or agora - self.estado.get("resumo_desde", agora) < self.opcoes["resumo_horas"] * 3600:
            return None
        self.estado["resumo_pendente"] = []
        self.estado.pop("resumo_desde", None)
        rotulos = {t["id"]: t["rotulo"] for t in TIPOS}
        por_tipo = {}
        for x in pend:
            por_tipo[x["tipo"]] = por_tipo.get(x["tipo"], 0) + 1
        partes = [f"{n}× {rotulos.get(t, t).split(' (')[0].lower()}" for t, n in sorted(por_tipo.items(), key=lambda x: (-x[1], x[0]))]
        return {"tipo": "resumo", "tipos": sorted(por_tipo), "titulo": f"Resumo: {len(pend)} aviso(s)",
                "corpo": "; ".join(partes), "detalhe": "", "chave": "resumo", "url": "/", "id": 0}

    def laco(self, parar, intervalo=INTERVALO, atraso=8):
        """Thread do detector. `parar`: threading.Event."""
        if parar.wait(atraso):
            return
        while not parar.is_set():
            try:
                self.passo()
            except Exception as e:
                print(f"[alertas] erro no detector: {str(e)[:160]}", flush=True)
            parar.wait(intervalo)

    def iniciar(self):
        """Sobe a thread do detector (daemon). Devolve o Event para parar."""
        parar = threading.Event()
        if self.opcoes["ativo"]:
            threading.Thread(target=self.laco, args=(parar,), daemon=True, name="alertas").start()
        return parar
