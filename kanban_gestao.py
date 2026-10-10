"""GitHub Projects por REST: projeção em cache, escrita explícita e sem GraphQL.

Não cria projetos/campos nem altera regras de merge. Autenticação pertence ao gh.
"""
import json
from pathlib import Path
import re
import subprocess
import time


def api(caminho, metodo="GET", dados=None, paginar=False, campo=None):
    if campo is not None and (not paginar or campo != 'check_runs'):
        raise ValueError('Coleção REST paginada incompatível')
    args = ["gh", "api", caminho, "--method", metodo]
    if paginar:
        if metodo != 'GET':
            raise ValueError('Paginação permitida somente na leitura')
        args += ['--paginate', '--slurp']
    entrada = None
    if dados is not None:
        args += ["--input", "-"]
        entrada = json.dumps(dados, ensure_ascii=False)
    r = subprocess.run(args, input=entrada, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=30)
    if r.returncode:
        raise ValueError("GitHub indisponível para gestão; confira acesso e cota do gh")
    resposta = json.loads(r.stdout) if r.stdout.strip() else None
    if paginar:
        if campo:
            if (not isinstance(resposta,list) or not resposta or len(resposta)>1000 or
                any(not isinstance(p,dict) or not isinstance(p.get(campo),list) or
                    type(p.get('total_count')) is not int or p['total_count']<0 for p in resposta)):
                raise ValueError('Envelope REST paginado inválido')
            total=resposta[0]['total_count']
            itens=[item for p in resposta for item in p[campo]]
            if any(p['total_count']!=total for p in resposta) or len(itens)!=total:
                raise ValueError('Coleção REST incompleta ou alterada durante paginação')
            return itens
        if not isinstance(resposta, list) or len(resposta) > 1000 or any(not isinstance(p, list) for p in resposta):
            raise ValueError('Formato/paginação REST do Projects incompatível')
        return [item for pagina in resposta for item in pagina]
    return resposta


class Kanban:
    def __init__(self, politica, cache, chamar=api, sem_escrita=False):
        self.cfg = politica["kanban"]
        self.cache, self.chamar = Path(cache), chamar
        self.sem_escrita = sem_escrita
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", self.cfg["repo"]):
            raise ValueError("Configure kanban.repo (owner/repo) no projeto")
        if not re.fullmatch(r"[\w.-]+", self.cfg["owner"]) or self.cfg["numero"] < 1:
            raise ValueError("Configure owner e número do Kanban do projeto")
        self.base = f"{self.cfg['tipo_owner']}/{self.cfg['owner']}/projectsV2/{self.cfg['numero']}"

    def _paginas(self, caminho):
        sep = '&' if '?' in caminho else '?'
        url = f'{caminho}{sep}per_page=100'
        # Projects usa cursores no Link; gh segue esses links, sem inventar page=N.
        # Um leitor injetado fornece a coleção completa (usado também pelos testes).
        dados = api(url, paginar=True) if self.chamar is api else self.chamar(url)
        if not isinstance(dados, list):
            raise ValueError('Formato REST do Projects incompatível')
        return dados

    def quadro(self, ao_vivo=False, somente_cache=False):
        if not ao_vivo and self.cache.is_file():
            try:
                dados = json.loads(self.cache.read_text(encoding="utf-8"))
                idade = time.time() - dados["gravado_em"]
                if (dados["base"] == self.base and dados["repo"] == self.cfg["repo"] and 0 <= idade < 600
                        and dados.get('campos_consultados') == self._nomes_campos()):
                    return dados
            except (ValueError, KeyError, TypeError):
                pass
        if somente_cache:
            raise ValueError("Quadro ainda não disponível em cache válido")
        campos = self._paginas(f"{self.base}/fields")
        por_nome = {c['name']: c['id'] for c in campos}
        if any(nome not in por_nome for nome in (self.cfg['campo_status'], self.cfg['campo_time'])):
            raise ValueError('Campo de Status ou Time ausente no Kanban')
        ids = ','.join(str(por_nome[n]) for n in self._nomes_campos() if n in por_nome)
        itens = self._paginas(f"{self.base}/items?fields={ids}")
        dados = {"base": self.base, "repo": self.cfg["repo"], "gravado_em": time.time(),
                 "campos": campos, "itens": itens, 'campos_consultados': self._nomes_campos()}
        if self.sem_escrita:
            return dados
        self.cache.parent.mkdir(parents=True, exist_ok=True)
        # Atomicidade evita um JSON parcial em leitores concorrentes.
        import uuid
        tmp = self.cache.with_name(self.cache.name + "." + uuid.uuid4().hex + ".tmp")
        try:
            tmp.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.cache)
        finally:
            tmp.unlink(missing_ok=True)
        return dados

    def _nomes_campos(self):
        return sorted({nome for nome in (self.cfg['campo_status'], self.cfg['campo_time'],
                      self.cfg['campo_prioridade'], self.cfg['campo_etapa']) if nome})

    def cartao(self, numero, ao_vivo=False):
        quadro = self.quadro(ao_vivo)
        url = f"https://github.com/{self.cfg['repo']}/issues/{numero}"
        item = next((i for i in quadro["itens"] if (i.get("content") or {}).get("html_url") == url), None)
        if not item:
            raise ValueError("Issue não encontrada no Kanban deste repositório")
        return self._descrever(item, quadro['campos'])

    def _descrever(self, item, lista_campos):
        campos = {c["name"]: c for c in lista_campos}
        por_id = {c["id"]: c for c in item.get("fields", [])}
        def valor(nome):
            v = por_id.get(campos.get(nome, {}).get("id"), {}).get("value")
            if isinstance(v, dict):
                v = v.get("name") or v.get("raw") or ""
            if isinstance(v, dict):
                v = v.get("raw", "")
            return str(v or "")
        return {"item": item, "status": valor(self.cfg["campo_status"]),
                "equipe": valor(self.cfg["campo_time"]), "prioridade": valor(self.cfg["campo_prioridade"]),
                "etapa": valor(self.cfg["campo_etapa"]), "campos": campos}

    def cartoes(self, ao_vivo=False):
        quadro = self.quadro(ao_vivo)
        padrao = re.compile(r'https://github\.com/' + re.escape(self.cfg['repo']) + r'/issues/([1-9][0-9]*)$', re.I)
        saida = []
        for item in quadro['itens']:
            m = padrao.fullmatch((item.get('content') or {}).get('html_url') or '')
            if m:
                descrito = self._descrever(item, quadro['campos'])
                saida.append({'numero': int(m[1]), 'status': descrito['status'], 'equipe': descrito['equipe'],
                              'prioridade':descrito['prioridade'], 'etapa':descrito['etapa']})
        return saida

    def issue(self, numero):
        if type(numero) is not int or numero < 1:
            raise ValueError("Número de issue inválido")
        return self.chamar(f"repos/{self.cfg['repo']}/issues/{numero}")

    def bloqueadores(self, numero):
        if type(numero) is not int or numero < 1:
            raise ValueError('Número de issue inválido')
        return self._paginas(f"repos/{self.cfg['repo']}/issues/{numero}/dependencies/blocked_by")

    def entrega(self, numero, branch):
        from urllib.parse import quote
        owner = self.cfg["repo"].split("/", 1)[0]
        prs = self.chamar(f"repos/{self.cfg['repo']}/pulls?state=open&head={quote(owner + ':' + branch, safe='')}")
        if not isinstance(prs, list):
            raise ValueError("Resposta de PRs incompatível")
        padrao = re.compile(rf"(?:Closes|Fixes|Resolves|Parte de)\s+#\s*{numero}\b", re.I)
        return next((pr for pr in prs if (pr.get("head") or {}).get("ref") == branch
                     and not pr.get("draft") and padrao.search(pr.get("body") or "")), None)

    def mover(self, numero, status):
        if status not in {self.cfg[x] for x in ("backlog", "andamento", "revisao", "feito")}:
            raise ValueError("Status não configurado na política do projeto")
        cartao = self.cartao(numero, ao_vivo=True)
        campo = cartao["campos"].get(self.cfg["campo_status"])
        if not campo:
            raise ValueError("Campo de status ausente no Kanban")
        opcao = next((o for o in campo.get("options", []) if
                      (o["name"].get("raw") if isinstance(o["name"], dict) else o["name"]) == status), None)
        if not opcao:
            raise ValueError("Opção de status ausente no Kanban")
        self.chamar(f"{self.base}/items/{cartao['item']['id']}", "PATCH",
                    {"fields": [{"id": campo["id"], "value": opcao["id"]}]})
        self.cache.unlink(missing_ok=True)
