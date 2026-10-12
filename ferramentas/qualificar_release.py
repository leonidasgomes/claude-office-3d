"""Qualificação fail-closed da tag, pacote e publicação (sem consulta a CI anterior)."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import stat
import sys
import tempfile
from urllib.parse import quote
import zipfile

RAIZ = Path(__file__).resolve().parent.parent
EDICAO = {"edicao": "office-multi-provider", "formato": 1}


def exigir(condicao, mensagem):
    if not condicao:
        raise ValueError(mensagem)


def identidade(tag, sha, head, ci_resultado, ci_sha, versao, edicao):
    exigir(ci_resultado == 'success', 'CI da própria execução ausente ou não aprovado')
    exigir(bool(re.fullmatch(r'[0-9a-f]{40}', sha)), 'SHA inválido')
    exigir(sha == head == ci_sha, 'CI, checkout e evento precisam do mesmo commit')
    exigir(bool(re.fullmatch(r'2\.[0-9]+\.[0-9]+-[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)*', versao)),
           'A linha 2.x permanece pré-release; versão inválida ou sem sufixo')
    exigir(tag == 'v' + versao, 'Tag diferente de VERSION')
    exigir(edicao == EDICAO, 'Identidade da edição inválida')


def pacote(raiz, tag):
    import build
    nome = 'office-multi-provider-' + tag
    arquivo = raiz / 'dist' / (nome + '.zip')
    checksum = arquivo.with_suffix('.zip.sha256')
    digest = hashlib.sha256(arquivo.read_bytes()).hexdigest()
    exigir(checksum.read_text(encoding='utf-8') == f'{digest}  {arquivo.name}\n',
           'Checksum ou nome do pacote incorreto')
    arquivos = build.arquivos_pacote(raiz)
    with zipfile.ZipFile(arquivo) as z:
        exigir(z.testzip() is None, 'ZIP corrompido')
        exigir(sorted(z.namelist()) == sorted(nome + '/' + f for f in arquivos),
               'Conteúdo ou raiz do ZIP diferente do manifesto')
        exigir(all(not stat.S_ISLNK(i.external_attr >> 16) for i in z.infolist()),
               'Link simbólico no ZIP')
        for f in arquivos:
            exigir(z.read(nome + '/' + f) == (raiz / f).read_bytes(),
                   'Arquivo do pacote diferente do checkout: ' + f)
        exigir(z.read(nome + '/VERSION').decode().strip() == tag[1:], 'VERSION do ZIP incorreto')
        exigir(json.loads(z.read(nome + '/EDICAO.json')) == EDICAO, 'Edição do ZIP incorreta')
    return arquivo, checksum


SMOKE = r'''
import http.client,json,threading,sys
from pathlib import Path
from functools import partial
from http.server import ThreadingHTTPServer
app=Path(sys.argv[1]); sys.path.insert(0,str(app))
import servidor,configuracao,rede,banco
if not Path(servidor.__file__).resolve().is_relative_to(app.resolve()):
    raise RuntimeError('Importação fora do ZIP')
servidor.cfg=lambda:configuracao.normalizar({'projetos':[]})
banco.ARQ=app.parent/'smoke.db'
servidor.Handler.rede=rede.Rede(app.parent,False,False)
srv=ThreadingHTTPServer(('127.0.0.1',0),partial(servidor.Handler,directory=str(app)))
t=threading.Thread(target=srv.serve_forever,daemon=True); t.start()
c=http.client.HTTPConnection('127.0.0.1',srv.server_address[1],timeout=10)
try:
    for path in ('/api/gestao','/gestao_painel.js'):
        c.request('GET',path); r=c.getresponse(); body=r.read()
        if r.status!=200 or not body: raise RuntimeError('Smoke falhou: '+path)
        if path=='/api/gestao': json.loads(body)
finally:
    c.close(); srv.shutdown(); srv.server_close(); t.join()
'''


def smoke(arquivo):
    with tempfile.TemporaryDirectory(prefix='office-release-') as tmp:
        destino = Path(tmp)
        with zipfile.ZipFile(arquivo) as z:
            # pacote() validou todos os nomes contra o manifesto antes desta extração.
            z.extractall(destino)
        app = destino / arquivo.stem
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(('OFFICE_', 'PYTHON')) and k not in ('GH_TOKEN', 'GITHUB_TOKEN')}
        env.update(HOME=str(destino), USERPROFILE=str(destino))
        subprocess.run([sys.executable, '-I', '-c', SMOKE, str(app)], cwd=app,
                       env=env, check=True, timeout=40)


def executar(args):
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout


def api(caminho, executar=executar, ausente=False):
    # --include permite distinguir 404 real de falha de rede/permissão/rate limit.
    try:
        resposta = executar(['gh', 'api', '--include', caminho])
    except subprocess.CalledProcessError as exc:
        resposta = exc.stdout or ''
        if not ausente or not re.match(r'HTTP/\S+ 404(?:\s|$)', resposta):
            raise
    cabecalho, separador, corpo = resposta.replace('\r\n', '\n').partition('\n\n')
    status = re.match(r'HTTP/\S+ (\d{3})(?:\s|$)', cabecalho)
    exigir(bool(separador and status), 'Resposta da API sem status HTTP válido')
    codigo = int(status.group(1))
    if codigo == 404 and ausente:
        return None
    exigir(codigo == 200, 'API recusou a leitura: ' + str(codigo))
    dados = json.loads(corpo)
    exigir(isinstance(dados, dict), 'Resposta da API precisa ser um objeto')
    return dados


def publicar(raiz, tag, sha, arquivo, checksum, executar=executar):
    repo = os.environ['GITHUB_REPOSITORY']
    exigir(bool(re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo)), 'Repositório inválido')
    base = 'repos/' + repo
    existente = api(base + '/releases/tags/' + quote(tag, safe=''), executar, ausente=True)
    if existente is not None:
        exigir(existente.get('tag_name') == tag and existente.get('draft') is False
               and existente.get('prerelease') is True and existente.get('assets') == [],
               'Só é permitido completar a pré-release pública vazia da tag exata')
    # Revalida imediatamente antes da primeira escrita, nos dois caminhos.
    ref = api(base + '/git/ref/tags/' + quote(tag, safe=''), executar)
    exigir(ref.get('ref') == 'refs/tags/' + tag and ref.get('object', {}).get('type') == 'commit'
           and ref['object'].get('sha') == sha,
           'Tag remota mudou ou não é uma tag leve do commit qualificado')
    exigir(pacote(raiz, tag) == (arquivo, checksum), 'Pacote mudou antes da publicação')
    titulo = 'Office Multi-provider ' + tag + ' — prévia pública (Codex e OpenCode)'
    comuns = ['--repo', repo]
    if existente is None:
        executar(['gh', 'release', 'create', tag, str(arquivo), str(checksum), '--verify-tag',
                  '--title', titulo, '--notes-file', str(raiz / 'NOTAS.md'),
                  '--prerelease', '--latest=false'] + comuns)
    else:
        executar(['gh', 'release', 'upload', tag, str(arquivo), str(checksum)] + comuns)
        executar(['gh', 'release', 'edit', tag, '--title', titulo,
                  '--notes-file', str(raiz / 'NOTAS.md'), '--prerelease', '--latest=false'] + comuns)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('acao', choices=['identidade', 'pacote', 'publicar'])
    args = p.parse_args()
    tag = os.environ.get('GITHUB_REF_NAME', '')
    sha = os.environ.get('GITHUB_SHA', '')
    exigir(os.environ.get('GITHUB_REF_TYPE') == 'tag', 'Evento precisa ser uma tag')
    head = executar(['git', 'rev-parse', 'HEAD']).strip()
    identidade(tag, sha, head, os.environ.get('CI_RESULTADO'), os.environ.get('CI_SHA'),
               (RAIZ / 'VERSION').read_text(encoding='utf-8').strip(),
               json.loads((RAIZ / 'EDICAO.json').read_text(encoding='utf-8')))
    executar(['git', 'diff', '--exit-code', 'HEAD', '--'])
    if args.acao != 'identidade':
        arquivo, checksum = pacote(RAIZ, tag)
        if args.acao == 'pacote':
            smoke(arquivo)
        else:
            publicar(RAIZ, tag, sha, arquivo, checksum)
    print('Qualificação aprovada: ' + args.acao)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError, zipfile.BadZipFile) as exc:
        sys.exit('Release bloqueada: ' + str(exc))
