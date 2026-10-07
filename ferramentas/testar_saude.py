"""Teste da saúde do time (saude.py) e do orçamento de atenção (alertas.Alertas.passo). Roda sem rede e sem GitHub.

Uso: python -W error ferramentas/testar_saude.py
Cobre: número e nome da tarefa na branch; duplicados fortes e fracos (só PR aberto ou branch local com commit < 48 h);
círculos (mesmo agente, mesmo arquivo >= 6 e mesmo comando >= 4 em 45 min; o início de comando não conta); selo de
risco do PR; PR parado; branches locais (git for-each-ref numa pasta temporária); `--pendentes`; os alertas
duplicado/circulo/pr_parado com fontes falsas (sem PRs: só círculos, estado de duplicado/parado preservado; PR parado não
repete enquanto aberto); imediatos x resumo (push falso, resumo `resumo_horas` depois do 1º aviso pendente, `conferir` chega
pelo resumo a quem ligou, contagem de hoje); `servidor.saude_atual` (sem `projetos`/`github.repo`, GitHub fora, PRONTO não
carregado, PR segurado por sugestão vira parado) e `servidor.saude_laco`; config e vigia.
"""
import io
import json
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
import alertas  # noqa: E402
import configuracao  # noqa: E402
import saude  # noqa: E402
import vigia_lider  # noqa: E402

feitos = []
H = 3600
T0 = 1_800_000_000


def ok(nome):
    feitos.append(nome)
    print("  ok:", nome)


def iso_local(t):
    """ts dos eventos como o registrar_evento grava (hora local, sem fuso)."""
    return datetime.fromtimestamp(t).isoformat(timespec="seconds")


def iso_utc(t):
    """updated_at do GitHub."""
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ev(t, agente, ferramenta, detalhe, **k):
    return dict({"ts": iso_local(t), "agente": agente, "tipo": "trabalho", "ferramenta": ferramenta, "detalhe": detalhe}, **k)


# ---------------------------------------------------------------- nomes de branch
def testar_nomes():
    nb, sb = saude.numero_da_branch, saude.slug_da_branch
    assert nb("feat/444-login-form") == 444 and nb("444-login-form") == 444 and nb("fix/login-12") == 12
    assert nb("main") is None and nb("") is None and nb(None) is None
    assert nb("feat/2026-10-07-relatorio") is None and nb("feat/20261007-relatorio") is None, "data não é número de issue"
    assert nb("feat/2026-10-07-55-relatorio") == 55
    assert nb("feat/123456-x") is None, "número com mais de 5 dígitos não é issue"
    ok("numero_da_branch: 1º número do nome (sem prefixo); datas e números longos não contam")
    assert sb("feat/444-login-form") == "login-form" and sb("fix/445-login-form-v2") == "login-form"
    assert sb("feat/444-login-form-l1") == "login-form-l1" and sb("Feat/444-Login_Form") == "login-form"
    assert sb("feat/444-docs") == "", "nome curto demais (< MIN_SLUG) não serve para comparar"
    assert sb("feat/2026-10-07-relatorio-mensal") == "relatorio-mensal" and sb(None) == ""
    ok("slug_da_branch: sem prefixo, número, data e -vN; curto demais = ''")


# ---------------------------------------------------------------- duplicados
def testar_duplicados():
    agora = T0
    recente, velho = agora - 2 * H, agora - 49 * H
    prs = [{"numero": 10, "branch": "feat/444-login-form", "fecha": [444]},
           {"numero": 11, "branch": "fix/450-login-form-v2", "fecha": []}]
    d = saude.duplicados(prs, [], agora)
    assert len(d["fortes"]) == 1 and d["fortes"][0]["branches"] == ["feat/444-login-form", "fix/450-login-form-v2"], d
    assert d["fortes"][0]["prs"] == [10, 11] and "login-form" in d["fortes"][0]["motivo"] and d["fracos"] == []
    ok("forte: o mesmo nome de tarefa em dois PRs com números de issue diferentes")
    prs = [{"numero": 20, "branch": "feat/500-cadastro-usuario", "fecha": [500]},
           {"numero": 21, "branch": "feat/outra-coisa-qualquer", "fecha": [500]}]
    d = saude.duplicados(prs, [], agora)
    assert [x["prs"] for x in d["fortes"]] == [[20, 21]] and "#500" in d["fortes"][0]["motivo"], d
    ok("forte: dois PRs abertos para a mesma issue (pelo número da branch ou pelo 'Closes #n')")
    locais = [{"branch": "feat/600-exportar-planilha", "quando": recente},
              {"branch": "feat/600-exportar-planilha-parte2", "quando": recente}]
    d = saude.duplicados([], locais, agora)
    assert d["fortes"] == [] and len(d["fracos"]) == 1 and "#600" in d["fracos"][0]["motivo"], d
    ok("fraco: duas branches ativas com o mesmo número (parte 1 e parte 2) não viram alerta")
    locais = [{"branch": "feat/700-relatorio-mensal", "quando": recente}, {"branch": "feat/701-relatorio-mensal", "quando": velho},
              {"branch": "feat/702-relatorio-mensal", "quando": recente}]
    d = saude.duplicados([], locais, agora)
    assert len(d["fortes"]) == 1 and d["fortes"][0]["branches"] == ["feat/700-relatorio-mensal", "feat/702-relatorio-mensal"], d
    assert d["fortes"][0]["prs"] == []
    ok("branch local com commit há mais de 48 h não conta (só trabalho em andamento)")
    prs = [{"numero": 30, "branch": "feat/800-importar-dados", "fecha": [800]}]
    locais = [{"branch": "feat/800-importar-dados", "quando": recente}, {"branch": "main", "quando": recente},
              {"branch": "feat/sem-numero-importar-dados", "quando": recente}]
    d = saude.duplicados(prs, locais, agora)
    assert d == {"fortes": [], "fracos": []}, d
    assert saude.duplicados(None, None, agora) == {"fortes": [], "fracos": []}
    assert saude.duplicados([{"numero": 1}, "lixo", {"branch": ""}], [], agora) == {"fortes": [], "fracos": []}
    ok("a branch local do próprio PR não duplica; branch sem número e entradas ruins são ignoradas")
    prs = [{"numero": 40, "branch": "feat/900-login-form", "fecha": [900, 901]},
           {"numero": 41, "branch": "feat/901-login-form-v2", "fecha": [901]}]
    d = saude.duplicados(prs, [], agora)
    assert [x["motivo"] for x in d["fortes"]] == ["2 PRs abertos para a issue #901"], d
    locais = [{"branch": "feat/910-tela-de-busca", "quando": recente}, {"branch": "fix/910-tela-de-busca-v2", "quando": recente}]
    d = saude.duplicados([], locais, agora)
    assert d["fortes"] == [] and len(d["fracos"]) == 1, "mesmo nome com issue em comum: só fraco (não é 'números diferentes')"
    ok("forte por nome só quando não há issue comum a todos; issue comum cai na regra de PRs/branches da mesma issue")


# ---------------------------------------------------------------- círculos
def testar_circulos():
    agora = T0
    base = agora - 30 * 60
    evs = [ev(base + i * 60, "Dev", "Edit", "file_path: C:\\proj\\src\\App.py") for i in range(6)]
    evs += [ev(base + 400 + i * 60, "Dev", "Bash", "command: pytest  -q\ntests/test_app.py") for i in range(4)]
    c = saude.circulos(evs, agora)
    assert len(c) == 1 and c[0]["agente"] == "Dev" and c[0]["arquivo"] == "app.py" and c[0]["edicoes"] == 6, c
    assert c[0]["comandos"] == 4 and c[0]["comando"] == "pytest -q tests/test_app.py" and c[0]["desde"] == round(base), c
    ok("círculo: o mesmo arquivo editado 6x e o mesmo comando 4x pelo mesmo agente em 45 min")
    assert saude.circulos(evs[:5] + evs[6:], agora) == [], "5 edições não bastam"
    assert saude.circulos(evs[:9], agora) == [], "3 comandos não bastam"
    assert saude.circulos(evs[:6], agora) == [] and saude.circulos(evs[6:], agora) == [], "só editar ou só rodar não é círculo"
    ok("abaixo de 6 edições ou de 4 comandos (ou só um dos dois) não é círculo")
    inicio = [ev(base + 400 + i * 60, "Dev", "Bash", "command: pytest -q tests/test_app.py", inicio=True, espera_s=120) for i in range(4)]
    assert saude.circulos(evs[:6] + evs[6:8] + inicio, agora) == [], "início de comando (PreToolUse) não conta"
    ok("eventos 'inicio' (PreToolUse) não contam: o mesmo comando não vale dois")
    velhos = [dict(e, ts=iso_local(agora - 50 * 60)) for e in evs[:3]]
    assert saude.circulos(velhos + evs[3:], agora) == [], "edições fora da janela de 45 min não contam"
    outro = [dict(e, agente="Pesquisa") for e in evs[6:]]
    assert saude.circulos(evs[:6] + outro, agora) == [], "agentes diferentes não somam"
    ruins = [{"ts": "x", "tipo": "trabalho", "ferramenta": "Edit", "detalhe": "file_path: a"}, "lixo", None,
             ev(base, "Dev", "Read", "file_path: a.py"), {"tipo": "fala", "texto": "oi"}]
    assert saude.circulos(evs + ruins, agora)[0]["edicoes"] == 6 and saude.circulos(None, agora) == []
    ok("janela de 45 min, por agente; ts inválido, Read, fala e lixo são ignorados")
    nb = [ev(base + i * 60, "Dev", "NotebookEdit", "notebook_path: analise.ipynb") for i in range(6)]
    c = saude.circulos(nb + evs[6:], agora)
    assert len(c) == 1 and c[0]["arquivo"] == "analise.ipynb", c
    ok("NotebookEdit (notebook_path) conta como edição")


# ---------------------------------------------------------------- risco e parados
def testar_risco_e_parados():
    r = saude.risco_pr
    assert r({"linhas": 299, "arquivos": 9})["nivel"] == "ok" and r({"linhas": 300, "arquivos": 1})["nivel"] == "medio"
    assert r({"linhas": 10, "arquivos": 10})["nivel"] == "medio" and r({"linhas": 800, "arquivos": 1})["nivel"] == "grande"
    assert r({"linhas": 1, "arquivos": 25})["nivel"] == "grande" and r({"linhas": 900, "arquivos": 3})["dica"] == "dividir em PRs menores"
    x = r({"linhas": 5, "arquivos": 1, "checks": {"ci": "FAILURE", "lint": "error", "rev": "SUCCESS", "x": "PENDING", "t": "TIMED_OUT",
                                                  "c": "CANCELLED", "a": "ACTION_REQUIRED", "s": "STARTUP_FAILURE", "n": "NEUTRAL"}})
    assert x["nivel"] == "ok" and x["falhas"] == 6 and x["dica"] == "corrigir os checks antes", x
    assert r({"linhas": None, "arquivos": 3})["nivel"] == "?" and r({})["nivel"] == "?" and r({"checks": {"a": "FAILURE"}})["falhas"] == 1
    ok("risco_pr: médio a partir de 300 linhas ou 10 arquivos, grande a partir de 800 ou 25; checks FAILURE/ERROR/TIMED_OUT/CANCELLED/ACTION_REQUIRED/STARTUP_FAILURE; '?' sem tamanho")
    agora = T0
    prs = [{"numero": 1, "titulo": "velho", "atualizado": iso_utc(agora - 30 * H)},
           {"numero": 2, "titulo": "novo", "atualizado": iso_utc(agora - 2 * H)},
           {"numero": 3, "titulo": "rascunho", "rascunho": True, "atualizado": iso_utc(agora - 90 * H)},
           {"numero": 4, "titulo": "pronto", "revisao": "SUCCESS", "atualizado": iso_utc(agora - 90 * H)},
           {"numero": 5, "titulo": "data ruim", "atualizado": "ontem"}, {"numero": "6", "atualizado": iso_utc(0)}]
    p = saude.parados(prs, agora, 24, alertas.situacao_pr)
    assert [(x["numero"], x["horas"]) for x in p] == [(1, 30)], p
    assert [x["numero"] for x in saude.parados(prs, agora, 24)] == [1, 4], "sem a regra de situação, o pronto também conta"
    assert [x["numero"] for x in saude.parados(prs, agora, 1, alertas.situacao_pr)] == [1, 2]
    ok("parados: PR aberto sem atualização há mais de N h, fora rascunho e pronto; data ruim é ignorada")
    segurado = {"numero": 7, "revisao": "SUCCESS", "sha": "abc", "atualizado": iso_utc(agora - 30 * H)}
    sg = {"ativo": True, "pronto": {"7": {"ok": True, "sha": "abc"}}, "seguram_merge": {"7": 1}}
    assert [x["numero"] for x in saude.parados([segurado], agora, 24, lambda pr: alertas.situacao_pr(pr, sg))] == [7]
    sg["seguram_merge"] = {}
    assert saude.parados([segurado], agora, 24, lambda pr: alertas.situacao_pr(pr, sg)) == []
    ok("parados com a regra do painel: aprovado mas segurado por sugestão conta como parado; pronto de verdade não")
    r0 = saude.resumo(None, [{"branch": "feat/1-x", "quando": agora}], [], agora)
    assert set(r0) == {"ts", "circulos", "sem_prs"} and r0["sem_prs"] is True, r0
    r1 = saude.resumo([{"numero": 3, "branch": "a"}, {"numero": "x"}, "lixo"], [], [], agora)
    assert r1["abertos"] == [3] and "duplicados" in r1 and "parados" in r1, r1
    ok("resumo: sem PRs (None) só círculos e sem_prs; com PRs traz 'abertos'")


# ---------------------------------------------------------------- git e linha de comando
def testar_branches_locais():
    with tempfile.TemporaryDirectory() as tmp:
        assert saude.branches_locais(tmp) == [], "pasta que não é repositório: []"
        assert saude.branches_locais(Path(tmp) / "nao-existe") == []
        if not shutil.which("git"):
            ok("branches_locais: sem git no PATH, só o caso de pasta comum")
            return
        def git(*a):
            subprocess.run(["git", "-C", tmp, *a], check=True, capture_output=True)
        git("init", "-q")
        git("-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "--allow-empty", "-m", "inicio")
        git("branch", "feat/12-tela-de-login")
        b = saude.branches_locais(tmp)
        nomes = sorted(x["branch"] for x in b)
        assert "feat/12-tela-de-login" in nomes and len(nomes) == 2, b
        assert all(abs(x["quando"] - time.time()) < 3600 for x in b), b
    ok("branches_locais: git for-each-ref com a data do último commit; pasta comum ou inexistente = []")


def rodar_cli(arq, argv):
    antigo_arq, antigo_out, antigo_argv = saude.ARQ, sys.stdout, sys.argv
    buf = io.BytesIO()
    saida = io.TextIOWrapper(buf, encoding="utf-8")
    sys.stdout = saida
    try:
        saude.ARQ, sys.argv = arq, ["saude.py"] + argv
        rc = saude.main()
        saida.flush()
        texto = buf.getvalue().decode("utf-8").strip()
    finally:
        saude.ARQ, sys.stdout, sys.argv = antigo_arq, antigo_out, antigo_argv
        saida.detach()
    return rc, texto


def testar_pendentes():
    agora = time.time()
    edits = [ev(agora - 60, "Dev", "Edit", "file_path: a/b.py")]
    cmd = [ev(agora - 60, "Dev", "Bash", "command: make")]
    prs = [{"numero": 1, "branch": "feat/1-tela-de-login"}, {"numero": 2, "branch": "feat/2-tela-de-login"}]
    dados = saude.resumo(prs, [], edits * 6 + cmd * 4, agora)
    linhas = saude.pendentes(dados, agora)
    assert len(linhas) == 2 and linhas[0].startswith("duplicado:") and "feat/1-tela-de-login" in linhas[0], linhas
    assert linhas[1].startswith("círculo: Dev edita b.py") and "6" not in linhas[1] and "4" not in linhas[1], linhas
    mais = saude.resumo(prs, [], edits * 9 + cmd * 7, agora)
    assert saude.pendentes(mais, agora) == linhas, "sem contagens: a mesma situação dá a mesma saída (o vigia não reacorda)"
    assert saude.pendentes(dados, agora + saude.VALIDADE_ARQ + 1) == [], "arquivo velho (servidor parado) não avisa"
    assert saude.pendentes(None, agora) == [] and saude.pendentes({"ts": agora}, agora) == []
    sem = saude.resumo(None, [], edits * 6 + cmd * 4, agora)
    assert len(saude.pendentes(sem, agora)) == 1, "sem PRs: só o círculo"
    ok("pendentes: duplicados fortes e círculos, sem contagens; nada com arquivo velho, vazio ou ausente")
    with tempfile.TemporaryDirectory() as tmp:
        arq = Path(tmp) / "saude.json"
        assert rodar_cli(arq, ["--pendentes"]) == (0, "NADA"), "sem arquivo: NADA"
        arq.write_text("{quebrado", encoding="utf-8")
        assert rodar_cli(arq, ["--pendentes"]) == (0, "NADA")
        arq.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
        rc, saida = rodar_cli(arq, ["--pendentes"])
        assert rc == 0 and saida.splitlines() == linhas, saida
        rc, saida = rodar_cli(arq, [])
        assert rc == 0 and "--pendentes" in saida
    ok("python saude.py --pendentes: lê dados/saude.json e imprime as linhas ou NADA (sem arquivo ou quebrado)")


# ---------------------------------------------------------------- alertas com fontes falsas
class PushFalso:
    """Registra os envios em vez de cifrar e mandar."""

    def __init__(self):
        self.enviados = []

    def enviar(self, alerta, so_aparelho=None, padroes=None, ignorar_tipos=False, validar=True):
        self.enviados.append(dict(alerta))
        return {"enviados": 1, "falhas": 0, "limitados": 0, "removidos": 0, "motivo": ""}

    def podar(self, ids):
        pass

    def tipos(self):
        return [a["tipo"] for a in self.enviados]


def eventos_circulo(agora):
    return [ev(agora - 600, "Dev", "Edit", "file_path: src/app.py")] * 6 + [ev(agora - 300, "Dev", "Bash", "command: npm test")] * 4


def saude_falsa(agora, dup=True, circ=True, parado=True, pronto12=False):
    """PRs com datas fixas (como no GitHub): #10 e #11 duplicados, #12 parado desde T0 - 30 h."""
    pr12 = {"numero": 12, "branch": "feat/460-relatorio", "titulo": "<b>relatório</b>", "atualizado": iso_utc(T0 - 30 * H)}
    if pronto12:
        pr12.update(revisao="SUCCESS", sha="s12")
    prs = [{"numero": 10, "branch": "feat/444-tela-de-login", "titulo": "login", "atualizado": iso_utc(T0 - 2 * H)},
           {"numero": 11, "branch": "fix/450-tela-de-login", "titulo": "login de novo", "atualizado": iso_utc(T0 - 2 * H)}, pr12]
    if not dup:
        prs = prs[2:]
    if not parado:
        prs = [p for p in prs if p["numero"] != 12]
    return saude.resumo(prs, [], eventos_circulo(agora) if circ else [], agora, alertas.situacao_pr, 24)


def novo_alertas(tmp, fontes, opcoes=None, push_falso=True, enviar_http=None):
    a = alertas.Alertas(tmp, fontes, dict({"limite_push_hora": 200}, **(opcoes or {})), enviar_http=enviar_http)
    if push_falso:
        a.push = PushFalso()
    return a


def tipos_de(r):
    return sorted(x["tipo"] for x in r)


def testar_alertas_saude():
    with tempfile.TemporaryDirectory() as tmp:
        est = {"sd": saude_falsa(T0)}
        a = novo_alertas(tmp, {"saude": lambda: est["sd"]})
        r = a.passo(T0)
        assert tipos_de(r) == ["circulo", "duplicado", "pr_parado"], r
        assert all(x["resumo"] is True for x in r), "duplicado, círculo e PR parado são de rotina (vão no resumo)"
        dup = next(x for x in r if x["tipo"] == "duplicado")
        assert dup["corpo"].startswith("Mesma tarefa (tela-de-login)") and "fix/450-tela-de-login" in dup["corpo"], dup
        circ = next(x for x in r if x["tipo"] == "circulo")
        assert circ["titulo"] == "Dev andando em círculos" and "app.py" in circ["corpo"] and "npm test" in circ["detalhe"], circ
        assert f"{saude.JANELA_CIRCULO_MIN} min" in circ["corpo"]
        par = next(x for x in r if x["tipo"] == "pr_parado")
        assert "#12" in par["titulo"] and "30 h" in par["titulo"] and par["url"] == alertas.PAINEIS.get("prs", "/"), par
        assert a.push.enviados == [], "rotina: nada na hora"
        ok("fonte saude: duplicado, círculo e PR parado alertam já na 1ª leitura (fato do presente), marcados resumo")
        for i in range(1, 6):   # o servidor guarda o cálculo por 5 min: o detector lê o mesmo resultado a cada 60 s
            assert a.passo(T0 + i * 60) == [], f"leitura {i}: não repete"
        est["sd"] = saude_falsa(T0 + 3600)
        assert a.passo(T0 + 3600) == [], "1 h depois, ainda em círculo: não repete antes de 2 h"
        est["sd"] = saude_falsa(T0 + 2 * H + 60)
        assert tipos_de(a.passo(T0 + 2 * H + 60)) == ["circulo"]
        ok("sem repetição a cada 60 s; círculo que continua avisa de novo só depois de 2 h")
        est["sd"] = {"erro": "x"}
        assert a.passo(T0 + 2 * H + 120) == []

        def falha():
            raise RuntimeError("fora")
        a.fontes["saude"] = falha
        assert a.passo(T0 + 2 * H + 180) == []
        a.fontes["saude"] = lambda: est["sd"]
        est["sd"] = saude.resumo(None, [], [], T0 + 2 * H + 240)   # GitHub fora: só círculos
        assert a.passo(T0 + 2 * H + 240) == []
        assert a.estado["dup"] and a.estado["parado"] == {"12": iso_utc(T0 - 30 * H)}, "sem PRs: estado de duplicado/parado intacto"
        est["sd"] = saude_falsa(T0 + 2 * H + 300, circ=False)
        assert a.passo(T0 + 2 * H + 300) == [], "a fonte voltou: nada repete"
        ok("fonte com erro, exceção ou sem PRs (só círculos): estado de duplicado/parado preservado, nada repete quando volta")
        est["sd"] = saude.resumo(None, [], eventos_circulo(T0 + 5 * H), T0 + 5 * H)
        assert tipos_de(a.passo(T0 + 5 * H)) == ["circulo"], "sem PRs, o círculo ainda alerta"
        ok("sem PRs (GitHub fora): círculo continua sendo detectado")
        est["sd"] = saude_falsa(T0 + 6 * H, dup=False, circ=False)
        assert a.passo(T0 + 6 * H) == []
        est["sd"] = saude_falsa(T0 + 6 * H + 60, circ=False)
        assert tipos_de(a.passo(T0 + 6 * H + 60)) == ["duplicado"], "duplicado que some e volta alerta de novo"
        ok("duplicado que some e volta alerta de novo")
        est["sd"] = saude_falsa(T0 + 6 * H + 120, circ=False, pronto12=True)   # aberto, mas saiu dos parados
        assert a.passo(T0 + 6 * H + 120) == [] and "12" in a.estado["parado"]
        est["sd"] = saude_falsa(T0 + 6 * H + 180, circ=False)
        assert a.passo(T0 + 6 * H + 180) == [], "PR aberto que sai e volta aos parados com a mesma data não repete"
        est["sd"] = saude_falsa(T0 + 6 * H + 240, circ=False, parado=False)   # fechado: some de "abertos"
        assert a.passo(T0 + 6 * H + 240) == [] and "12" not in a.estado["parado"]
        est["sd"] = saude_falsa(T0 + 6 * H + 300, circ=False)
        assert tipos_de(a.passo(T0 + 6 * H + 300)) == ["pr_parado"], "reaberto (estava fora de 'abertos'): alerta de novo"
        ok("PR parado: presente/ausente/presente enquanto aberto não repete; fechado e reaberto alerta de novo")
        b = novo_alertas(tmp, {"saude": lambda: est["sd"]})
        assert b.passo(T0 + 6 * H + 360) == [], "estado em disco: reiniciar o servidor não repete"
        assert len(json.dumps(b.estado)) < 20000, "estado não cresce sem limite"
        ok("estado da saúde persiste em alertas_estado.json (reinício não repete)")


def testar_orcamento():
    with tempfile.TemporaryDirectory() as tmp:
        prs_d = {"prs": [{"numero": 70, "titulo": "t", "revisao": "PENDING", "sha": "a"}], "erro": ""}
        est = {"sd": None}
        a = novo_alertas(tmp, {"prs": lambda: prs_d, "saude": lambda: est["sd"]}, {"resumo_horas": 3})
        assert a.passo(T0) == [] and a.push.enviados == []   # baseline dos PRs; saúde ausente
        prs_d["prs"][0] = {"numero": 70, "titulo": "t", "revisao": "SUCCESS", "sha": "a"}
        est["sd"] = saude_falsa(T0 + 60, circ=False, parado=False)
        r = a.passo(T0 + 60)
        assert {x["tipo"]: x["resumo"] for x in r} == {"pr_pronto": False, "duplicado": True}, r
        assert a.push.tipos() == ["pr_pronto"] and a.estado["resumo_desde"] == T0 + 60, a.push.tipos()
        fila, _ = a.listar(0)
        assert {x["tipo"]: x["resumo"] for x in fila} == {"pr_pronto": False, "duplicado": True}, "a fila guarda resumo=True"
        ok("imediato (pr_pronto) vai na hora; rotina (duplicado) fica pendente, marcada resumo na fila")
        a.push.enviados.clear()
        est["sd"] = saude_falsa(T0 + 120, parado=False)
        assert tipos_de(a.passo(T0 + 120)) == ["circulo"]
        est["sd"] = saude_falsa(T0 + H, circ=False)
        assert tipos_de(a.passo(T0 + H)) == ["pr_parado"]
        assert a.passo(T0 + 3 * H + 59) == [] and a.push.enviados == [], "ainda não fez 3 h desde o 1º aviso pendente"
        assert a.passo(T0 + 3 * H + 60) == [] and a.push.tipos() == ["resumo"], a.push.tipos()
        res = a.push.enviados[0]
        assert res["tipos"] == ["circulo", "duplicado", "pr_parado"] and res["titulo"].endswith("Resumo: 3 aviso(s)"), res
        assert a.estado["resumo_pendente"] == [] and "resumo_desde" not in a.estado
        a.push.enviados.clear()
        assert a.passo(T0 + 9 * H) == [] and a.push.enviados == [], "sem pendentes: nenhum resumo vazio"
        est["sd"] = saude_falsa(T0 + 10 * H)   # novo círculo (passou 2 h): a janela recomeça neste aviso
        assert tipos_de(a.passo(T0 + 10 * H)) == ["circulo"] and a.push.enviados == [] and a.estado["resumo_desde"] == T0 + 10 * H
        est["sd"] = saude_falsa(T0 + 13 * H, circ=False)
        assert a.passo(T0 + 13 * H) == [] and a.push.tipos() == ["resumo"] and a.push.enviados[0]["tipos"] == ["circulo"]
        ok("resumo sai resumo_horas depois do 1º aviso pendente, com todos juntos; a janela recomeça no próximo aviso")
        dia = lambda t: time.strftime("%Y-%m-%d", time.localtime(t))   # noqa: E731
        esperado = {"imediatos": 1 if dia(T0 + 60) == dia(T0 + H) else 0,
                    "resumo": sum(dia(t) == dia(T0 + H) for t in (T0 + 60, T0 + 120, T0 + H, T0 + 10 * H))}
        assert a.hoje(T0 + H) == esperado, (a.hoje(T0 + H), esperado)
        assert a.hoje(T0 + 30 * 86400) == {"imediatos": 0, "resumo": 0}
        for i in range(20):
            a._contar([], T0 + i * 86400)
        assert len(a.estado["contagem"]) == alertas.DIAS_CONTAGEM
        ok("contagem de hoje (imediatos x resumo) e só os últimos 14 dias guardados")
    with tempfile.TemporaryDirectory() as tmp:   # estado antigo: pendentes sem resumo_desde
        (Path(tmp) / "alertas_estado.json").write_text(json.dumps({"resumo_pendente": [{"tipo": "lembrete", "titulo": "x"}],
                                                                    "resumo_ultimo": 0}), encoding="utf-8")
        a = novo_alertas(tmp, {})
        assert a.passo(T0) == [] and a.push.enviados == [] and a.estado["resumo_desde"] == T0, "não sai na hora"
        assert a.passo(T0 + 3 * H - 1) == [] and a.push.enviados == []
        a.passo(T0 + 3 * H)
        assert a.push.tipos() == ["resumo"] and a.push.enviados[0]["tipos"] == ["lembrete"]
        assert json.loads((Path(tmp) / "alertas_estado.json").read_text(encoding="utf-8")).get("resumo_pendente") == []
        ok("estado antigo com pendentes e sem resumo_desde: a janela começa na 1ª leitura e o resumo sai depois")
    with tempfile.TemporaryDirectory() as tmp:   # imediatos configurável: duplicado na hora
        est = {"sd": saude_falsa(T0, circ=False, parado=False)}
        a = novo_alertas(tmp, {"saude": lambda: est["sd"]}, {"imediatos": ["duplicado", "zzz"]})
        assert a.opcoes["imediatos"] == ["duplicado"]
        r = a.passo(T0)
        assert [(x["tipo"], x["resumo"]) for x in r] == [("duplicado", False)] and a.push.tipos() == ["duplicado"], a.push.tipos()
        ok("alertas.imediatos configurável (tipo desconhecido é descartado)")


def testar_conferir_pelo_resumo():
    """`conferir` (desligado no padrão global) chega pelo resumo ao aparelho que o ligou, e só a ele (push real, HTTP falso)."""
    import push
    if push.CRIPTO_ERRO:
        ok("conferir pelo resumo: sem 'cryptography', parte do push real pulada")
        return
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    def assinatura(n):
        pub = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        return {"endpoint": f"https://fcm.googleapis.com/fcm/send/aparelho{n}",
                "keys": {"p256dh": push.b64u(pub), "auth": push.b64u(bytes(range(16)))}}
    destinos = []

    def http(endpoint, corpo, cab):
        destinos.append(endpoint.rsplit("/", 1)[-1])
        return 201
    with tempfile.TemporaryDirectory() as tmp:
        est = {"placar": {"agentes": {"A": {"conferir": []}}}}
        a = novo_alertas(tmp, {"placar": lambda: est["placar"]}, push_falso=False, enviar_http=http)
        assert a.opcoes["tipos"]["conferir"] is False
        assert a.push.inscrever("p1", "quer conferir", assinatura(1), {"conferir": True})[0]
        assert a.push.inscrever("p2", "padrão", assinatura(2), {})[0]
        assert a.passo(T0) == []
        est["placar"] = {"agentes": {"A": {"conferir": [{"pr": 5}]}}}
        r = a.passo(T0 + 60)
        assert [(x["tipo"], x["resumo"]) for x in r] == [("conferir", True)] and destinos == []
        assert a.hoje(T0 + 60) == {"imediatos": 0, "resumo": 0}, "contagem só dos tipos ligados no global"
        a.passo(T0 + 60 + 3 * H)
        assert destinos == ["aparelho1"], destinos
    ok("conferir (desligado no global) chega pelo push de resumo ao aparelho que o ligou, e só a ele; fora da contagem")


# ---------------------------------------------------------------- push com `tipos`
def testar_push_tipos():
    import push
    quer = push.Push._quer
    sub = {"tipos": {"duplicado": False, "circulo": True}}
    assert any(quer(sub, t, alertas.PADROES) for t in ["duplicado", "circulo"])
    assert not any(quer(sub, t, alertas.PADROES) for t in ["duplicado"])
    assert quer({"tipos": {}}, "pr_parado", alertas.PADROES) and not quer({"tipos": {}}, "conferir", alertas.PADROES)
    ok("push de resumo: vai a quem quer pelo menos um dos tipos agrupados (Push._quer)")


# ---------------------------------------------------------------- config, vigia e servidor
def testar_config_e_vigia():
    a = configuracao.normalizar_alertas({"imediatos": ["pr_pronto", " zzz ", ""], "resumo_horas": 99, "parado_horas": "x"})
    assert a["imediatos"] == ["pr_pronto", "zzz"] and a["resumo_horas"] == 24 and a["parado_horas"] == 24, a
    o = alertas.normalizar_opcoes(a)
    assert o["imediatos"] == ["pr_pronto"] and o["resumo_horas"] == 24, o
    assert alertas.normalizar_opcoes({"resumo_horas": 0, "parado_horas": 9999})["resumo_horas"] == 1
    d = configuracao.normalizar_alertas({})
    assert d["imediatos"] == configuracao.ALERTAS_IMEDIATOS == alertas.IMEDIATOS_PADRAO and d["resumo_horas"] == 3 and d["parado_horas"] == 24
    assert all(d["tipos"].get(t) is True for t in ("duplicado", "circulo", "pr_parado"))
    assert {t["id"] for t in alertas.TIPOS} >= {"duplicado", "circulo", "pr_parado"}
    assert alertas.normalizar_opcoes({"imediatos": "pr_pronto"})["imediatos"] == alertas.IMEDIATOS_PADRAO
    ex = json.loads((RAIZ / "config.exemplo.json").read_text(encoding="utf-8"))
    assert set(ex["alertas"]["tipos"]) == set(configuracao.ALERTAS_TIPOS) and ex["vigia"].get("saude") is True
    assert all(k in ex["alertas"] for k in ("imediatos", "resumo_horas", "parado_horas"))
    ok("config: imediatos/resumo_horas/parado_horas normalizados; config.exemplo.json com as chaves novas")
    cfg = configuracao.carregar(Path(tempfile.gettempdir()) / "nao-existe-office-saude.json")
    assert cfg["vigia"]["saude"] is True
    assert [p[0] for p in vigia_lider.passos(cfg)].count("saude") == 1
    cfg["vigia"]["saude"] = False
    assert "saude" not in [p[0] for p in vigia_lider.passos(cfg)]
    assert configuracao.normalizar_vigia({"saude": False})["saude"] is False and configuracao.normalizar_vigia({})["saude"] is True
    ok("vigia do líder: passo saude por padrão; vigia.saude false tira")


class EventoFalso:
    """threading.Event de mentira: `wait` devolve False `n` vezes (o laço segue) e depois True (parar)."""

    def __init__(self, n):
        self.n, self.esperas = n, []

    def wait(self, t):
        self.esperas.append(t)
        self.n -= 1
        return self.n < 0

    def is_set(self):
        return self.n < 0


def testar_servidor_saude():
    import servidor
    nomes = ("cfg", "prs", "PASTA", "sugestoes_para_alertas", "saude_atual")
    antes = {k: getattr(servidor, k) for k in nomes}
    ler_ev = servidor.banco.ler_eventos
    agora = time.time()
    sg_ok = {"ativo": False, "itens": [], "pronto": {}, "pronto_carregado": True}
    try:
        with tempfile.TemporaryDirectory() as tmp:
            conf = configuracao.carregar(Path(tmp) / "nao-existe.json")
            servidor.cfg, servidor.PASTA = (lambda: conf), Path(tmp)
            servidor.banco.ler_eventos = lambda desde=0, ultimos=0, maximo=500: (0, eventos_circulo(time.time()))

            def nao_chamar():
                raise AssertionError("sem github.repo não consulta PRs nem sugestões")
            servidor.prs = servidor.sugestoes_para_alertas = nao_chamar

            def novo():
                servidor._saude.update(quando=0.0, dados=None)
                return servidor.saude_atual()
            d = novo()   # sem projetos e sem github.repo
            assert d["duplicados"] == {"fortes": [], "fracos": []} and d["parados"] == [] and d["abertos"] == [], d
            assert len(d["circulos"]) == 1
            assert json.loads((Path(tmp) / "dados" / "saude.json").read_text(encoding="utf-8"))["ts"] == d["ts"]
            ok("saude_atual sem 'projetos' e sem github.repo: calcula, grava dados/saude.json, sem alerta falso")
            conf["github"]["repo"] = "dono/repo"
            servidor.sugestoes_para_alertas = lambda: sg_ok
            servidor.prs = lambda: {"erro": "gh fora", "prs": []}
            d = novo()
            assert d.get("sem_prs") is True and "parados" not in d and "duplicados" not in d and len(d["circulos"]) == 1, d

            def prs_explode():
                raise RuntimeError("gh sumiu")
            servidor.prs = prs_explode
            assert novo().get("sem_prs") is True
            ok("GitHub fora (erro ou exceção): só círculos (sem_prs), sem duplicado/parado falso e sem derrubar")
            segurado = {"numero": 5, "branch": "feat/5-tela-de-login", "revisao": "SUCCESS", "sha": "abc",
                        "atualizado": iso_utc(agora - 40 * H)}
            servidor.prs = lambda: {"erro": "", "prs": [segurado]}
            servidor.sugestoes_para_alertas = lambda: {"ativo": True, "itens": [], "pronto_carregado": False, "pronto": {}}
            assert novo().get("sem_prs") is True, "PRONTO ainda não carregado: sem a regra do painel, só círculos"
            servidor.sugestoes_para_alertas = lambda: {"ativo": True, "itens": [], "pronto_carregado": True,
                                                       "pronto": {"5": {"ok": True, "sha": "abc"}}, "seguram_merge": {"5": 2}}
            d = novo()
            assert [x["numero"] for x in d["parados"]] == [5] and d["abertos"] == [5], d
            servidor.sugestoes_para_alertas = lambda: {"ativo": True, "itens": [], "pronto_carregado": True,
                                                       "pronto": {"5": {"ok": True, "sha": "abc"}}, "seguram_merge": {}}
            assert novo()["parados"] == [], "pronto de verdade fica com o lembrete, não com o parado"

            def sg_explode():
                raise RuntimeError("caixa ilegível")
            servidor.sugestoes_para_alertas = sg_explode
            assert novo().get("sem_prs") is True
            ok("saude_atual com a regra do painel: PR segurado por sugestão vira parado; PRONTO não carregado ou caixa ilegível = só círculos")
            servidor.sugestoes_para_alertas = lambda: sg_ok
            servidor.prs = lambda: {"erro": "", "prs": []}
            servidor.banco.ler_eventos = lambda *a, **k: (_ for _ in ()).throw(OSError("banco travado"))
            d = novo()
            assert d["circulos"] == [] and d["parados"] == []
            servidor.prs = nao_chamar
            assert servidor.saude_atual() is d, "cache de 300 s"
            ok("saude_atual: banco com erro não derruba (sem círculos); resultado guardado por 300 s")
        chamadas = []

        def saude_conta():
            chamadas.append(1)
            if len(chamadas) == 2:
                raise RuntimeError("falha de uma rodada")
        servidor.saude_atual = saude_conta
        e = EventoFalso(3)
        servidor.saude_laco(e)
        v = servidor.SAUDE_VALIDADE
        assert len(chamadas) == 3 and e.esperas == [30, v, v, v], e.esperas
        e = EventoFalso(0)
        chamadas.clear()
        servidor.saude_laco(e)
        assert chamadas == [] and e.esperas == [30], "parar durante a espera inicial: não calcula"
        ok("saude_laco: 30 s e depois a cada SAUDE_VALIDADE, independente dos alertas; uma rodada com erro não para o laço")
    finally:
        for k, v in antes.items():
            setattr(servidor, k, v)
        servidor.banco.ler_eventos = ler_ev
        servidor._saude.update(quando=0.0, dados=None)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    t = time.time()
    testar_nomes()
    testar_duplicados()
    testar_circulos()
    testar_risco_e_parados()
    testar_branches_locais()
    testar_pendentes()
    testar_alertas_saude()
    testar_orcamento()
    testar_conferir_pelo_resumo()
    testar_push_tipos()
    testar_config_e_vigia()
    testar_servidor_saude()
    print(f"OK: {len(feitos)} verificações em {time.time() - t:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
