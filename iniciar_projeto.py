"""Prepara a nova instalação e a política de um projeto em um comando."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import sys

import configuracao
import configurar_gestao
import instalar


def preparar(projeto, destino, politica, porta=8765, cadastrar_projeto=False):
    raiz, app = Path(projeto).resolve(), Path(destino).resolve()
    if app.is_relative_to(raiz) or raiz.is_relative_to(app):
        raise ValueError('Separe a pasta do escritório da pasta do projeto')
    if type(porta) is not int or not 1024 <= porta <= 65535:
        raise ValueError('Porta deve estar entre 1024 e 65535')
    instalar.validar_edicao(app)
    politica_plano = configurar_gestao.preparar(raiz, politica)
    arq = app/'config.json'
    existente = arq.exists()
    config_versao=None;cadastro_novo=False
    if existente:
        for nome in instalar.PACOTE:
            arquivo = app/nome
            if not arquivo.is_file() or not arquivo.resolve().is_relative_to(app):
                raise ValueError('Instalação existente incompleta; confira/repare os arquivos antes de cadastrar o projeto')
        if arq.is_symlink() or arq.stat().st_size > 1024*1024:
            raise ValueError('Configuração existente inválida')
        bruto=arq.read_bytes()
        if len(bruto)>1024*1024:raise ValueError('Configuração existente inválida')
        config_versao=hashlib.sha256(bruto).hexdigest()
        cfg = json.loads(bruto.decode('utf-8-sig'))
        if not isinstance(cfg, dict):
            raise ValueError('Configuração existente inválida')
        normal = configuracao.normalizar(cfg)
        if not any(Path(p).resolve() == raiz for p in normal['projetos']):
            if not cadastrar_projeto:
                raise ValueError('Escritório já configurado para outros projetos; use --cadastrar-projeto para cadastro explícito ou escolha nova pasta')
            projetos=cfg.get('projetos',[])
            if isinstance(projetos,str):projetos=[projetos]
            if not isinstance(projetos,list) or any(not isinstance(p,str) or not p.strip() for p in projetos):
                raise ValueError('Lista de projetos inválida; confira antes de cadastrar')
            cfg={**cfg,'projetos':projetos+[str(raiz)]};cadastro_novo=True
        if normal['porta'] != porta:
            raise ValueError('Porta existente preservada; informe a mesma porta')
    else:
        # Não transformar uma instalação parcial/com arquivos pessoais em instalação nova.
        if app.exists() and any(app.iterdir()):
            raise ValueError('Para a primeira instalação, escolha uma pasta vazia')
        cfg = configuracao.normalizar({'titulo':'Office Multi-provider', 'projetos':[str(raiz)], 'porta':porta})
    return {'projeto':str(raiz), 'destino':str(app), 'config':cfg,
            'politica_plano':politica_plano, 'existente':existente,
            'config_versao':config_versao,'cadastro_novo':cadastro_novo}


def gravar_cadastro(plano):
    """Atualiza apenas a lista de projetos, com backup exato e compare antes de substituir."""
    app=Path(plano['destino']);arq=app/'config.json';lock=app/'cadastro.edicao.lock';tmp=None
    conteudo=(json.dumps(plano['config'],ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    if len(conteudo)>1024*1024:raise ValueError('Configuração nova excede 1 MiB')
    def original():
        if arq.is_symlink() or not arq.resolve().is_relative_to(app):raise ValueError('Configuração fora da instalação')
        with arq.open('rb') as f:bruto=f.read(1024*1024+1)
        if hashlib.sha256(bruto).hexdigest()!=plano['config_versao']:
            raise ValueError('Configuração mudou; refaça a prévia do cadastro')
        return bruto
    try:
        with lock.open('x',encoding='utf-8') as f:f.write(str(os.getpid()))
    except FileExistsError as exc:raise ValueError('Outro cadastro está em andamento; confira antes de repetir') from exc
    try:
        bruto=original();hist=app/'dados/historico-config'
        if not hist.resolve().is_relative_to(app):raise ValueError('Histórico fora da instalação')
        hist.mkdir(parents=True,exist_ok=True);backup=hist/(plano['config_versao']+'.json')
        try:
            with backup.open('xb') as f:f.write(bruto)
        except FileExistsError:
            if backup.is_symlink() or backup.read_bytes()!=bruto:raise ValueError('Cópia anterior inconsistente')
        with tempfile.NamedTemporaryFile(dir=app,prefix='cadastro-',suffix='.tmp',delete=False) as f:
            tmp=Path(f.name);f.write(conteudo);f.flush();os.fsync(f.fileno())
        original();os.replace(tmp,arq);tmp=None
    finally:
        if tmp:tmp.unlink(missing_ok=True)
        lock.unlink(missing_ok=True)


def aplicar(plano):
    atual = preparar(plano['projeto'], plano['destino'], plano['politica_plano']['politica'],
                     configuracao.normalizar(plano['config'])['porta'],plano['cadastro_novo'])
    if atual != plano:
        raise ValueError('Instalação/projeto mudou desde a prévia; refaça o plano')
    if not plano['existente']:
        instalar.aplicar({'destino':plano['destino'], 'config':plano['config'], 'hook':'nenhum',
                         'statusline':False, 'venv':False, 'revisao':False,
                         'three_offline':False, 'praticas':{}}, SimpleNamespace(settings_usuario=None))
    escritos = configurar_gestao.aplicar(plano['projeto'], plano['politica_plano'])
    if plano['cadastro_novo']:gravar_cadastro(plano)
    return {'destino':plano['destino'], 'arquivos_projeto':escritos,
            'instalacao_criada':not plano['existente'],'projeto_cadastrado':plano['cadastro_novo']}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--projeto', required=True, type=Path)
    p.add_argument('--destino', required=True, type=Path)
    p.add_argument('--politica', type=Path, help='JSON revisado; sem ele abre assistente de CEO/diretor/equipes')
    p.add_argument('--porta', type=int, default=8765, help='porta da nova instalação, padrão 8765')
    p.add_argument('--aplicar', action='store_true', help='cria a instalação e os arquivos novos do projeto')
    p.add_argument('--exigir-requisitos', action='store_true', help='não aplica se requisitos locais selecionados estiverem ausentes')
    p.add_argument('--cadastrar-projeto', action='store_true', help='permite adicionar este projeto à instalação nova existente, preservando os demais')
    args = p.parse_args(argv)
    try:
        dados = (json.loads(args.politica.read_text(encoding='utf-8-sig')) if args.politica
                 else configurar_gestao.guiado(args.projeto))
        plano = preparar(args.projeto, args.destino, dados, args.porta,args.cadastrar_projeto)
        from diagnostico_instalacao import verificar
        diagnostico=verificar(plano['politica_plano']['politica'],args.porta)
        previa = {'projeto':plano['projeto'], 'destino':plano['destino'],
                  'porta':configuracao.normalizar(plano['config'])['porta'],
                  'existente':plano['existente'], 'cadastro_novo':plano['cadastro_novo'], 'politica':plano['politica_plano']['politica'],
                  'arquivos_novos_projeto':list(plano['politica_plano']['arquivos'])}
        print(json.dumps({'consoles':configurar_gestao.detectar(), 'requisitos':diagnostico, 'plano':previa},ensure_ascii=False,indent=2))
        if args.exigir_requisitos and not diagnostico['requisitos_locais_disponiveis']:
            print('Requisitos locais pendentes: '+', '.join(diagnostico['faltam'])+'. Nenhuma aplicação realizada.',file=sys.stderr)
            return 3
        if args.aplicar:
            print(json.dumps(aplicar(plano),ensure_ascii=False,indent=2))
            print('Abra abrir_escritorio.bat (Windows) ou abrir_escritorio.sh na pasta de destino.')
        else:
            print('Prévia sem alterações. Repita com --aplicar para criar.')
        if not diagnostico['requisitos_locais_disponiveis']:
            print('Configuração preparável; execução depende dos requisitos listados e do login no console escolhido.')
        return 0
    except (OSError, ValueError, EOFError, KeyboardInterrupt) as exc:
        print('Inicialização não concluída: '+str(exc)+'. Confira o destino e refaça a prévia antes de repetir.',file=sys.stderr)
        return 2


if __name__ == '__main__': sys.exit(main())
