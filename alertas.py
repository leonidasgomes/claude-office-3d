"""Alertas do escritório: avisa o desenvolvedor quando há algo esperando por ele (somente biblioteca padrão + push.py).

O detector roda numa thread a cada 60 s, usa os dados que o servidor já tem (PRs em cache, placar de XP, eventos,
escalonamentos) e compara com o estado guardado em dados/alertas_estado.json para NÃO repetir o mesmo alerta.
Cada alerta novo vai para a fila dados/alertas.jsonl (últimos 200), para o Web Push (push.py) e, no Windows e se
ligado, para um toast do sistema. A página lê a fila em GET /api/alertas?desde=<id>.

Tipos: pr_pronto, pr_problema, auditoria, conferir, escalonamento, pergunta, lembrete (e "teste", do botão de teste).
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
]
PADROES = {t["id"]: t["padrao"] for t in TIPOS}
OPCOES_PADRAO = {"ativo": True, "lembrete_horas": 24, "limite_push_hora": 20, "toast_windows": False,
                 "contato": _push.CONTATO_PADRAO, "tipos": dict(PADROES), "agentes_pergunta": []}


def tipos_publicos(opcoes):
    """Lista de tipos para a página, com o padrão de cada um já vindo das opções do servidor."""
    return [dict(t, padrao=bool(opcoes["tipos"].get(t["id"], t["padrao"]))) for t in TIPOS]


def normalizar_opcoes(bruto):
    """Opções com tipos corrigidos e padrões; nunca levanta exceção por valor ruim."""
    o = json.loads(json.dumps(OPCOES_PADRAO))
    if isinstance(bruto, dict):
        o["ativo"] = bruto.get("ativo") is not False
        o["toast_windows"] = bruto.get("toast_windows") is True
        for k, minimo, maximo in (("lembrete_horas", 1, 24 * 14), ("limite_push_hora", 1, 200)):
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
    return o


# ---------------------------------------------------------------- detector (puro: não faz E/S)
def situacao_pr(pr):
    """pronto | conflito | reprovado | espera (mesma regra do painel de PRs)."""
    if pr.get("rascunho"):
        return "espera"
    if pr.get("conflito"):
        return "conflito"
    g = str(pr.get("revisao") or pr.get("guardiao") or "").upper()
    if g == "SUCCESS":
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


def _detectar_prs(est, d, agora, opc, novos):
    base = est.setdefault("base", {})
    registro, atual = est.setdefault("prs", {}), {}
    primeira = not base.get("prs")
    prontos, problemas, titulos = [], {}, {}
    for pr in d["prs"]:
        if not isinstance(pr, dict) or not isinstance(pr.get("numero"), int):
            continue
        n, s = pr["numero"], situacao_pr(pr)
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
    entradas: {"prs": dict do /prs, "placar": dict do /xp, "eventos": (total, [eventos novos]), "escalonamentos": dict}.
    Fonte ausente, com erro ou vazia por falha não apaga o estado (nada de alerta falso quando o gh cai)."""
    novos = []
    d = entradas.get("prs")
    if isinstance(d, dict) and not d.get("erro") and d.get("configurado") is not False and isinstance(d.get("prs"), list):
        _detectar_prs(est, d, agora, opc, novos)
    p = entradas.get("placar")
    if isinstance(p, dict) and not p.get("erro") and p.get("ativo") is not False and isinstance(p.get("agentes"), dict):
        _detectar_placar(est, p, agora, novos)
    e = entradas.get("escalonamentos")
    if isinstance(e, dict):
        _detectar_escalonamentos(est, e, novos)
    ev = entradas.get("eventos")
    if isinstance(ev, tuple) and len(ev) == 2:
        _detectar_eventos(est, ev[0], ev[1], opc, novos)
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
        for nome in ("prs", "placar", "escalonamentos"):
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
            novos = detectar(self.estado, ent, agora, self.opcoes)
            saida = [self._entrar_na_fila(a, agora) for a in novos]
            self._gravar_estado()
        for a in saida:
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
