# -*- coding: utf-8 -*-
"""Binário que o seu worktree muda e que outro PR aberto também muda (risco de um colega sobrescrever o trabalho do outro).

Por quê: binário (imagem, modelo 3D, áudio, asset de motor de jogo...) não se funde; no conflito, quem resolve escolhe um
lado e o trabalho do outro some sem aviso. O `git lfs lock` não resolve quando todos os agentes usam a mesma conta do
GitHub: a trava do LFS é por conta. Este script só olha os PRs abertos (REST, sem tokens de modelo) e avisa antes.

Uso: python binarios_em_pr.py [--wt <worktree>] [--base origin/main] [--repo dono/nome] [--ext .png,.blend] [arquivo ...]
  sem arquivos: os binários que o worktree muda contra a base (commits + não commitados).
  com arquivos: confere só esses (antes de começar a editar um asset, por exemplo).
  --repo: padrão github.repo do config.json; --base: padrão o branch padrão do origin (origin/HEAD) ou origin/main;
  --ext: padrão as extensões que o .gitattributes do worktree manda para o LFS (`*.ext filter=lfs`) ou, sem elas, BINARIOS.
Saída: código 0 sem choque; 1 com a lista "arquivo -> #PR (branch)"; 2 erro (gh, git ou config).
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))
import configuracao  # noqa: E402

# Padrão sem .gitattributes de LFS: os binários mais comuns (imagem, modelo 3D, áudio, vídeo, fonte, asset de motor)
BINARIOS = {".png", ".jpg", ".jpeg", ".tga", ".exr", ".psd", ".blend", ".fbx", ".glb", ".obj", ".wav", ".mp3", ".ogg",
            ".mp4", ".ttf", ".otf", ".uasset", ".umap", ".unity", ".prefab", ".asset", ".tres", ".res"}
MAX_PAGINAS = 30   # 3000 arquivos por PR, o teto da própria API
RX_LFS = re.compile(r"^\*(\.[\w.-]+)\s.*\bfilter=lfs\b", re.M)


def git(wt, *args):
    r = subprocess.run(["git", "-c", "core.quotepath=off", "-C", wt, *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()[:200]}")
    return r.stdout


def extensoes_lfs(wt):
    """Extensões `*.ext ... filter=lfs` do .gitattributes da raiz do worktree (minúsculas); vazio se não houver."""
    try:
        texto = (Path(wt) / ".gitattributes").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    return {e.lower() for e in RX_LFS.findall(texto)}


def base_padrao(wt):
    try:
        return git(wt, "symbolic-ref", "--short", "refs/remotes/origin/HEAD").strip() or "origin/main"
    except RuntimeError:
        return "origin/main"


def binario(caminho, exts):
    return PurePosixPath(caminho).suffix.lower() in exts


def gh_json(gh, rota):
    r = subprocess.run([gh, "api", rota], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90)
    if r.returncode != 0:
        raise RuntimeError(f"gh api {rota}: {r.stderr.strip()[:200]}")
    return json.loads(r.stdout or "null")


def mudados_no_worktree(wt, base, exts):
    # --no-renames: renomeação vira apagado + novo, e os dois nomes entram
    nomes = set(git(wt, "diff", "--name-only", "--no-renames", f"{base}...HEAD").splitlines())
    for linha in git(wt, "status", "--porcelain", "-uall").splitlines():
        nomes.update(n.strip('"') for n in linha[3:].split(" -> ") if n.strip('"'))
    return {n for n in nomes if binario(n, exts)}


def arquivos_do_pr(gh, repo, n):
    nomes, pagina = set(), 1
    while pagina <= MAX_PAGINAS:
        lote = gh_json(gh, f"repos/{repo}/pulls/{n}/files?per_page=100&page={pagina}") or []
        nomes.update(n for f in lote for n in (f["filename"], f.get("previous_filename")) if n)
        if len(lote) < 100:
            break
        pagina += 1
    return nomes


def choques(meus, ramo, prs, arquivos_de):
    """{arquivo: [(n, branch), ...]} dos PRs abertos (menos o do próprio branch e os rascunhos) que mudam um dos `meus`."""
    saida = {}
    for p in prs:
        if p["head"]["ref"] == ramo or p.get("draft"):
            continue
        for nome in sorted(meus & arquivos_de(p["number"])):
            saida.setdefault(nome, []).append((p["number"], p["head"]["ref"]))
    return saida


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(description="Binário do seu worktree que outro PR aberto também muda.")
    ap.add_argument("arquivos", nargs="*", help="confere só estes caminhos (relativos à raiz do repo)")
    ap.add_argument("--wt", default=".", help="worktree (padrão: o diretório atual)")
    ap.add_argument("--base", default="", help="padrão: origin/HEAD ou origin/main")
    ap.add_argument("--repo", default="", help="dono/nome (padrão: github.repo do config.json)")
    ap.add_argument("--ext", default="", help="extensões separadas por vírgula (padrão: as do LFS no .gitattributes)")
    args = ap.parse_args()
    try:
        exts = ({("." + e.strip().lstrip(".")).lower() for e in args.ext.split(",") if e.strip()}
                or extensoes_lfs(args.wt) or BINARIOS)
        base = args.base or base_padrao(args.wt)
        meus = ({a.replace("\\", "/") for a in args.arquivos if binario(a, exts)} if args.arquivos
                else mudados_no_worktree(args.wt, base, exts))
        if not meus:
            print("nenhum binário para conferir")
            return 0
        repo = args.repo.strip() or configuracao.carregar()["github"]["repo"]
        if not repo:
            raise RuntimeError("sem repositório: passe --repo dono/nome ou preencha github.repo no config.json")
        gh = configuracao.localizar_gh() or "gh"
        ramo = git(args.wt, "rev-parse", "--abbrev-ref", "HEAD").strip()
        prs = gh_json(gh, f"repos/{repo}/pulls?state=open&per_page=100") or []
        achados = choques(meus, ramo, prs, lambda n: arquivos_do_pr(gh, repo, n))
    except (RuntimeError, OSError, subprocess.SubprocessError, ValueError) as e:
        print(f"ERRO: {e}")
        return 2
    if not achados:
        print(f"{len(meus)} binário(s) conferido(s) contra {len(prs)} PR(s) aberto(s): nenhum choque")
        return 0
    print(f"CHOQUE: {len(achados)} binário(s) também mudado(s) em outro PR aberto. Não resolva escolhendo um lado: "
          "combine com o dono (ou o líder) quem muda primeiro; o outro refaz a mudança sobre a versão mergeada.")
    for nome, quem in achados.items():
        print(f"  {nome} -> " + ", ".join(f"#{n} ({ref})" for n, ref in quem))
    return 1


if __name__ == "__main__":
    sys.exit(main())
