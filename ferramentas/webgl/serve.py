"""Serve the real Office routes with disposable data; no background integrations."""
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
# This process receives no account environment or usable provider CLI path.
with tempfile.TemporaryDirectory(prefix="office-webgl-") as directory:
    temporary = Path(directory)
    home = temporary / "home"
    home.mkdir()
    empty_bin = temporary / "empty-bin"
    empty_bin.mkdir()
    os.environ.clear()
    os.environ.update(HOME=str(home), PATH=str(empty_bin),
                      CODEX_HOME=str(home / ".codex"),
                      OFFICE_CONFIG=str(temporary / "config.json"))
    sys.path.insert(0, str(ROOT))
    os.chdir(ROOT)

    def isolate(event, args):
        if event in {"subprocess.Popen", "os.system", "os.posix_spawn", "os.exec",
                     "os.spawn", "socket.connect", "socket.sendto", "socket.sendmsg"}:
            raise OSError("Visual harness forbids subprocesses and outbound connections")

    sys.addaudithook(isolate)
    import configuracao
    import funcionarios
    import gestao_projeto
    # Test-harness-only integration isolation; production source stays unchanged.
    configuracao.localizar_gh = lambda: None
    projects = []
    for label, team, person in [("Projeto-Sintetico-A", "Desenvolvimento", "Ana Teste"),
                                ("Projeto-Sintetico-B", "Design", "Bia Teste")]:
        project = temporary / label
        (project / ".office").mkdir(parents=True)
        executor = {"console": "codex", "modelo": "synthetic-no-execution"}
        policy = gestao_projeto.validar({"ativo": True, "ceo": executor,
            "diretor": executor, "equipes": [{"nome": team,
            "especialidade": "Validacao visual", "executor": executor}]})
        (project / ".office/projeto.json").write_text(json.dumps(policy), encoding="utf-8")
        funcionarios.cadastrar(project, {"nome": person, "funcao": "Validacao visual",
            "equipe": team, "executor": executor, "skills": []})
        projects.append(str(project))
    config = {"porta": 8765, "titulo": "Office Linux - validacao sintetica",
        "projetos": projects, "github": {"repo": "", "bots_revisao": []},
        "alertas": {"ativo": False}, "grafo": {"ativo": False},
        "sugestoes": {"triagem_modelo": ""}, "revisor": {"ativo": False},
        "auditor": {"ativo": False}, "xp": {"ativo": False}, "rede_local": False}
    (temporary / "config.json").write_text(json.dumps(config), encoding="utf-8")
    import servidor
    # Use real server + Handler, deliberately not main's account/background loops.
    server, extras = servidor.abrir_servidores([], 8765, False, False, False)
    assert server is not None and not extras
    assert server.server_address[0] == "127.0.0.1"
    # Register the real read-only alerts endpoint, without starting a worker.
    alerts = servidor.criar_alertas(servidor.Handler.rede)
    assert alerts.opcoes["ativo"] is False
    print("Synthetic Office ready on loopback; background integrations disabled", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
