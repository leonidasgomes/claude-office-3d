"""Fontes locais de alertas vinculadas à política, sem consulta cloud ou GitHub."""
import hashlib
import sqlite3
from kanban_painel import catalogo
from politica_painel import snapshot


def fontes(base):
    import sugestoes_bot as sb
    import xp_projeto
    ativos,invalidos=catalogo(base['projetos'])
    saida={'ativo':bool(ativos or invalidos),'projetos':[]}
    for raiz,politica,publico in ativos:
        repo=politica['kanban']['repo']
        item={'projeto_id':publico['id'],'nome':publico['nome'],'repo':repo,
              'chave':publico['id']+':'+hashlib.sha256(repo.casefold().encode()).hexdigest()[:20],'entradas':{}}
        try:
            cfg,versao,_=snapshot(raiz)
            if cfg!=politica:raise ValueError('Política mudou')
            if cfg['sugestoes']['ativo']:
                c=sb.configuracao(raiz)
                resumo=sb.resumo(c)
                # Um erro de coleta não equivale a caixa vazia ou itens resolvidos.
                if not resumo.get('erro'):item['entradas']['sugestoes']=resumo
                sb.conferir_projeto(c)
            if base['xp']['ativo']:
                try:item['entradas']['placar']=xp_projeto.ler(xp_projeto.contexto(raiz,base))
                except (OSError,ValueError,TypeError):pass
            from gestao_painel import saude_projeto
            try:item['entradas']['tarefas']=saude_projeto(raiz,repo)
            except (OSError,ValueError,TypeError,sqlite3.Error):pass
            if snapshot(raiz)[1]!=versao:raise ValueError('Política mudou')
            item['politica_versao']=versao
        except (OSError,ValueError,TypeError,KeyError):
            item['entradas']={};item['erro']='Fontes do projeto indisponíveis'
        saida['projetos'].append(item)
    return saida
