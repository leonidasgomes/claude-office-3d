"""Imprime a seção da versão no CHANGELOG.md e confere se a tag bate com o VERSION.

Uso: python ferramentas/notas_versao.py v1.0.0
"""
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def notas(versao, texto):
    m = re.search(r"^## " + re.escape(versao) + r"\s*$(.*?)(?=^## |\Z)", texto, re.S | re.M)
    mudancas = m.group(1).strip() if m else f"Versão {versao}"
    if not versao.startswith('2.'):
        return mudancas
    base = 'https://github.com/leonidasgomes/claude-office-3d'
    pacote = f'office-multi-provider-v{versao}.zip'
    return f'''**Edição 2.x para Codex e OpenCode — prévia pública.** Instale em pasta separada do Claude legado.

### Download e instalação

1. [Baixar o pacote instalável {versao}]({base}/releases/download/v{versao}/{pacote}). Em Assets, escolha esse ZIP; Source code é o código-fonte.
2. Extraia o ZIP. No Windows sem Python/consoles, execute `preparar_maquina.bat`; depois execute `instalar.bat`. Com as ferramentas instaladas, comece por `instalar.bat`.
3. Abra o atalho **Office Multi-provider** (quando disponível nesta versão), ou `abrir_escritorio.bat`. Cadastre/configure seu projeto conforme o [guia de instalação]({base}/blob/v{versao}/INSTALACAO.md) e selecione CEO, equipes e funcionários em **⚙️ → Gestão das equipes**.

Linux/macOS: use `instalar.sh` e `abrir_escritorio.sh`. Autenticação e modelos disponíveis são configurados nos consoles. A instalação não inicia tarefas automaticamente.

### Qual linha escolher?

- **Codex/OpenCode e gestão multi-provider:** esta edição 2.x. Continua em validação; disponibilidade dos modelos gratuitos depende do OpenCode.
- **Claude legado estável:** [1.19.1]({base}/releases/tag/v1.19.1). O selo Latest do GitHub aponta para o legado estável. Não instale 2.x sobre a pasta 1.x.
- O arquivo `.sha256` em Assets permite conferir a integridade do ZIP. Bancos, contas e configuração pessoal não estão no pacote; faça backup antes de atualizar uma instalação existente.

### Mudanças desta versão

{mudancas}
'''


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    tag = sys.argv[1] if len(sys.argv) > 1 else ""
    versao = (RAIZ / "VERSION").read_text(encoding="utf-8").strip()
    if tag and tag.lstrip("v") != versao:
        sys.exit(f"tag {tag} diferente do VERSION ({versao})")
    texto = (RAIZ / "CHANGELOG.md").read_text(encoding="utf-8")
    print(notas(versao, texto))


if __name__ == "__main__":
    main()
