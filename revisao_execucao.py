"""Prepara e executa revisão de um commit local, sem publicar/mesclar no GitHub."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import uuid

import gestao_projeto
import revisao_cruzada
import revisores_console


def git(pasta, *args):
    r = subprocess.run(['git', '-c', 'core.quotepath=false', '-C', str(pasta), *args], capture_output=True, text=True,
                       encoding='utf-8', errors='replace', timeout=30)
    if r.returncode:
        raise ValueError('Não foi possível ler o commit/base no Git')
    return r.stdout.strip()


def preparar(projeto, trabalho, base, equipe, aceite, escopo='implementacao', funcionario=None):
    from gestao_cli import validar_worktree
    trabalho = validar_worktree(projeto, trabalho)
    cfg = gestao_projeto.carregar(projeto)
    membro = None
    if funcionario:
        import funcionarios
        membro, autor = funcionarios.executor(projeto,funcionario,equipe,escopo)
    else:
        autor = gestao_projeto.executor(cfg, equipe=equipe, escopo=escopo)
    revisores = gestao_projeto.revisores(cfg, autor)
    if not revisores: raise ValueError('Revisão cruzada desativada')
    sha = git(trabalho, 'rev-parse', '--verify', 'HEAD^{commit}')
    inicio = git(trabalho, 'rev-parse', '--verify', '--end-of-options', base+'^{commit}')
    comparacao = git(trabalho, 'merge-base', inicio, sha)
    diff = git(trabalho, 'diff', '--no-ext-diff', '--no-textconv', '--unified=5', comparacao, sha, '--')
    raiz = Path(projeto).resolve()
    regras_arq = (raiz/cfg['fontes']['regras']).resolve()
    if not regras_arq.is_relative_to(raiz): raise ValueError('Fonte de regras fora do projeto')
    regras = regras_arq.read_text(encoding='utf-8-sig')
    if not aceite.strip() or not diff or len(diff)+len(regras)+len(aceite)>230000:
        raise ValueError('Aceite/diff ausente ou contexto grande demais; nenhum truncamento será feito')
    return cfg, autor, {'sha':sha, 'base':inicio, 'comparacao':comparacao, 'diff':diff, 'aceite':aceite, 'regras':regras,
                        'revisores':revisores, 'worktree':str(trabalho), 'funcionario':membro}


def linhas_novas(diff):
    arquivos = {}; arquivo = None; linha = None
    for texto in diff.splitlines():
        if texto.startswith('+++ '):
            nome = texto[4:]
            if nome.startswith('"'): nome = json.loads(nome)
            arquivo = nome[2:] if nome.startswith('b/') else nome
            linha = None
        elif texto.startswith('@@ '):
            m = re.search(r'\+(\d+)(?:,\d+)? @@', texto)
            linha = int(m.group(1)) if m else None
        elif arquivo and linha is not None:
            if texto.startswith(('+', ' ')):
                arquivos.setdefault(arquivo, set()).add(linha); linha += 1
    return arquivos


def executar(projeto, trabalho, base, equipe, aceite, chamar=revisores_console.chamar, escopo='implementacao', funcionario=None):
    from gestao_cli import pasta_dados
    cfg, autor, pacote = preparar(projeto, trabalho, base, equipe, aceite, escopo, funcionario)
    linhas = linhas_novas(pacote['diff'])
    def conferir_resposta(executor, prompt):
        resposta = revisao_cruzada.normalizar(chamar(executor, prompt))
        for achado in resposta['achados']:
            if achado['linha'] not in linhas.get(achado['arquivo'], set()):
                raise ValueError('Achado não corresponde ao lado novo do diff')
        return resposta
    relatorio = revisao_cruzada.revisar(cfg, autor, pacote['sha'], pacote['diff'], aceite, pacote['regras'], conferir_resposta)
    # Atualizar commit/regras/política durante a revisão invalida toda a rodada.
    novo_cfg = gestao_projeto.carregar(projeto)
    _, novo_autor, atual = preparar(projeto, trabalho, base, equipe, aceite, escopo, funcionario)
    if (pacote != atual or autor != novo_autor or cfg != novo_cfg):
        raise ValueError('Commit/contexto/política mudou durante a revisão; relatório descartado')
    relatorio['base'] = pacote['base']
    relatorio['contexto'] = hashlib.sha256(json.dumps({k:pacote[k] for k in ('diff','aceite','regras')},
                                                   sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    pasta = pasta_dados(projeto)/'revisoes'; pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta/(pacote['sha']+'.json')
    tmp = pasta/(uuid.uuid4().hex+'.tmp')
    try:
        tmp.write_text(json.dumps(relatorio, ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.replace(destino)
    finally:
        tmp.unlink(missing_ok=True)
    return relatorio
