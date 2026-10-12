"""Operações de arquivos compatíveis com Python 3.9+, sem dependências extras."""
import hashlib
import stat


def is_junction(caminho):
    """Reconhece junctions também antes de Path.is_junction (Python 3.12).

    lstat não segue a junction; st_reparse_tag está disponível no Windows desde
    Python 3.8. Erros de acesso continuam bloqueando o chamador.
    """
    nativo = getattr(caminho, 'is_junction', None)
    if nativo is not None:
        return nativo()
    try:
        info = caminho.lstat()
    except (FileNotFoundError, NotADirectoryError):
        return False
    return getattr(info, 'st_reparse_tag', None) == getattr(stat, 'IO_REPARSE_TAG_MOUNT_POINT', 0xA0000003)


def sha256_arquivo(arquivo):
    """Calcula SHA-256 em blocos sem exigir hashlib.file_digest (Python 3.11)."""
    resumo = hashlib.sha256()
    for bloco in iter(lambda: arquivo.read(1024 * 1024), b''):
        resumo.update(bloco)
    return resumo.hexdigest()
