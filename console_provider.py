"""Launcher da nova versão: consoles com sessão e eventos padronizados."""
import argparse
import errno
import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
import uuid
from dataclasses import asdict
from contextlib import ExitStack
from pathlib import Path

from providers_console import Eventos, selecionar, sessao_nativa
from skills_compartilhados import contexto, preparar_codex

RAIZ = Path(__file__).resolve().parent


def pipe_entrada(operacao,*args):
    """Mesmo tratamento de pipe fechado usado por Popen.communicate()."""
    try:return operacao(*args)
    except BrokenPipeError:pass
    except OSError as exc:
        if exc.errno not in (errno.EPIPE,errno.EINVAL):raise


def encerrar_processo(processo):
    """Encerra e recolhe apenas o processo iniciado por este launcher."""
    if processo is None or processo.poll() is not None:
        return
    processo.terminate()
    try:
        processo.wait(timeout=5)
    except subprocess.TimeoutExpired:
        processo.kill()
        processo.wait(timeout=5)


def executar(provider, exe, projeto, mesa, prompt=None, modelo=None, sessao=None, agente=None, banco=None,
             adaptar_local=None, politica_local=None, ao_sessao=None, skills_nativas=None, ao_skills=None, ao_processo=None,projeto_consumo=None,ao_evento=None,tentativa_consumo=None):
    import emit_evento
    projeto_medicao=Path(projeto if projeto_consumo is None else projeto_consumo).resolve()
    if projeto_consumo is not None and not projeto_medicao.is_dir():raise ValueError('Projeto de consumo não existe')
    if provider.nome in ("claude", "codex", "gemini", "opencode") and prompt is not None and not politica_local:
        prompt = contexto(projeto,provider.nome) + "\n\nTarefa:\n" + prompt
    args = provider.comando(exe, projeto, prompt, modelo, sessao, agente)
    entrada = None
    if provider.nome == "codex" and prompt is not None:
        # Catálogo extenso não cabe na linha de comando do Windows. O CLI lê '-'.
        entrada = prompt
        args[-1] = "-"
    elif provider.nome == "claude" and prompt is not None:
        entrada = prompt
    elif provider.nome == "gemini" and prompt is not None:
        entrada = prompt
        args[-1] = "Siga a tarefa e as regras recebidas na entrada padrão."
    elif provider.nome == "opencode" and prompt is not None:
        # run lê o pipe junto da mensagem; evita limite de argumentos no Windows.
        entrada = prompt
        args[-1] = "Siga a tarefa e as referências recebidas na entrada padrão."
    env = os.environ.copy()
    funcionario_cloud = bool(re.fullmatch(r'Office_[0-9a-f]{32}',mesa))
    if adaptar_local:
        args = adaptar_local(args, env)
    if provider.nome == 'claude':
        # Never inherit ownership from a parent office execution into a TUI.
        for chave in ('OFFICE_CLAUDE_STREAM_HOOK', 'OFFICE_CLAUDE_STREAM_SESSION'):
            env.pop(chave, None)
        if provider.capacidades.eventos_json and prompt is not None:
            ident = sessao or str(uuid.uuid4())
            if not sessao:
                args += ['--session-id', ident]
            env['OFFICE_CLAUDE_STREAM_HOOK'] = str((RAIZ / 'registrar_evento.py').resolve())
            env['OFFICE_CLAUDE_STREAM_SESSION'] = ident
    if provider.nome == "opencode":
        env.update(OFFICE_EMIT=str(RAIZ / "emit_evento.py"), OFFICE_AGENTE=mesa,
                   OFFICE_PYTHON=sys.executable, OFFICE_PROJETOS=str(projeto),
                   OFFICE_CONSUMO_PROJETO=str(projeto_medicao))
        if politica_local:
            env["OFFICE_FONTE"] = "opencode_local"
        else:
            env.setdefault("OFFICE_FONTE", "opencode")
        if banco:
            env["OFFICE_BANCO"] = str(banco)
        # Launcher observa o pai no JSON; plugin continua observando os filhos.
        env["OFFICE_STREAM_OWNER"] = "launcher" if prompt is not None else "plugin"
        if prompt is None and not (projeto / ".opencode" / "plugins" / "office.js").is_file():
            print("Aviso: instale o plugin com importar_opencode.py --aplicar para telemetria da TUI.", file=sys.stderr)
    stream = provider.capacidades.eventos_json and prompt is not None
    evidencia_skills=None
    if skills_nativas:
        if provider.nome!='claude' or not stream or politica_local:
            raise ValueError('Evidência de skills nativas exige Claude cloud com stream')
        from skills_execucao import EvidenciaClaude
        evidencia_skills=EvidenciaClaude(skills_nativas,ident)
    eventos = Eventos(provider.nome, mesa)
    from consumo_providers import Coletor, ColetorRollout
    import banco as banco_modulo
    coletor = Coletor((Path(banco) if banco else banco_modulo.ARQ).parent / 'consumo_providers.db',
                     provider.nome, projeto_medicao, mesa, modelo, rotulo=provider.nome+'_local' if politica_local else None,
                     sessao_claude_nova=ident if provider.nome=='claude' and stream and not sessao and not politica_local else None,
                     sessao_claude_retomada=sessao if provider.nome=='claude' and stream and sessao and not politica_local else None,
                     tentativa=tentativa_consumo)

    def emitir(ev,nativo=False):
        if politica_local:
            ev['fonte'] = provider.nome+'_local'
        try:
            normalizado=emit_evento.normalizar(ev)
            if nativo and ao_evento is not None:ao_evento(normalizado)
            emit_evento.gravar(normalizado, banco)
        except Exception:
            pass  # falha de telemetria nunca derruba o console

    if provider.nome != "claude" or stream or politica_local or funcionario_cloud:
        emitir(eventos.base(ferramenta="Console", resumo="console iniciado", inicio=True, espera_s=120))
    processo = None
    from retorno_console import Retorno
    retorno=Retorno(provider.nome) if stream else None
    parar = threading.Event()
    observador = None
    thread = None
    claude_observador=None
    if provider.nome=='claude' and not stream and ao_sessao is not None and prompt is not None:
        from claude_sessao import Observador as SessaoClaude
        claude_observador=SessaoClaude(projeto,sessao=sessao,prompt=prompt)
    protecao = ExitStack()
    if provider.nome == "codex":
        from codex_observador import Observador
        observador = Observador(projeto, mesa, lambda ev:emitir(ev,True), sessao,
                                avisar=lambda s: print(s, file=sys.stderr, flush=True),
                                observar_principal=not stream,
                                criar_consumo=lambda nome, ident, novo: ColetorRollout(
                                    coletor.registro.arquivo, projeto_medicao, nome, ident, novo,
                                    rotulo=provider.nome+'_local' if politica_local else provider.nome,tentativa=tentativa_consumo))
    try:
        processo = subprocess.Popen(args, cwd=str(projeto), env=env,
                                    stdout=subprocess.PIPE if stream else None,
                                    stdin=subprocess.PIPE if entrada is not None else None,
                                    start_new_session=bool(politica_local),
                                    text=True, encoding="utf-8", errors="replace")
        if ao_processo is not None: ao_processo(processo)
        if politica_local:
            from recursos_local import vigiar
            protecao.enter_context(vigiar(processo, politica_local))
        if observador is not None:
            thread = threading.Thread(target=observador.acompanhar, args=(parar,), daemon=True)
            thread.start()
        if entrada is not None:
            pipe_entrada(processo.stdin.write,entrada)
            pipe_entrada(processo.stdin.close)
        if stream:
            sessao_notificada=None
            for linha in processo.stdout:
                print(linha, end="", flush=True)
                nova_sessao=None
                try:
                    registro = json.loads(linha)
                    if retorno is not None:retorno.consumir(registro)
                    if evidencia_skills is not None:
                        evidencia_skills.consumir(registro)
                    try:
                        coletor.consumir(registro)
                    except (ValueError, TypeError, AttributeError, OSError, sqlite3.Error):
                        pass  # Consumo indisponível não interrompe a tarefa nem vira zero.
                    if observador is not None and registro.get("type") == "thread.started":
                        observador.sessao = registro.get("thread_id") or sessao
                    for ev in eventos.converter(registro):
                        emitir(ev,True)
                    nova_sessao=sessao_nativa(provider.nome,registro)
                except (ValueError, TypeError, AttributeError):
                    pass  # versão futura ou linha não JSON
                # Falha do vínculo de gestão não é falha opcional de telemetria.
                if ao_sessao is not None and nova_sessao is not None and nova_sessao != sessao_notificada:
                    ao_sessao(nova_sessao)
                    sessao_notificada=nova_sessao
        if claude_observador is not None:
            notificada=None
            while True:
                ident=claude_observador.consultar()
                if ident and ident!=notificada:
                    ao_sessao(ident); notificada=ident
                if processo.poll() is not None: break
                parar.wait(1)
            if not notificada:
                print('Sessão Claude não identificada no transcrito; retomada automática indisponível.',file=sys.stderr)
        codigo = processo.wait()
        if evidencia_skills is not None:
            evidencia=evidencia_skills.resumo()
            if ao_skills is not None: ao_skills(evidencia)
            if not evidencia['valida']:
                print('Ativação nativa das skills não comprovada neste turno; entrega bloqueada.',file=sys.stderr)
                if codigo==0: codigo=1
        if codigo==0 and retorno is not None and not retorno.sucesso():
            if retorno is not None:
                emitir(eventos.base('erro',ferramenta='Console',resumo='Fluxo principal sem conclusão bem-sucedida',ok=False))
            print('Console não comprovou conclusão bem-sucedida do fluxo principal; entrega bloqueada.',file=sys.stderr)
            return 1
        return codigo
    except KeyboardInterrupt:
        encerrar_processo(processo)
        return 130
    except BaseException:
        try:
            encerrar_processo(processo)
        except (OSError, subprocess.TimeoutExpired):
            print('Não foi possível confirmar o encerramento do processo; concilie a execução antes de retomar.', file=sys.stderr)
        raise  # Persistência/vínculo não são falhas opcionais de telemetria.
    finally:
        parar.set()
        if thread is not None:
            thread.join(timeout=5)
        if observador is not None and not stream:
            eventos.sessao = observador.transcrito.sessao
            if observador.caminho is None:
                print("Transcrito Codex não identificado; informe o ID em --sessao para retomada exata.", file=sys.stderr)
        if processo is not None and processo.stdout is not None:
            processo.stdout.close()
        if processo is not None and processo.stdin is not None:
            pipe_entrada(processo.stdin.close)
        if provider.nome != "claude" or stream or politica_local or funcionario_cloud:
            emitir(eventos.base("ocioso", resumo="console encerrado"))
        protecao.close()


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--provider", choices=["claude", "codex", "gpt", "opencode", "gemini", "auto"])
    p.add_argument("--config", type=Path, help="JSON separado do config do escritório")
    p.add_argument("--projeto", type=Path)
    p.add_argument("--mesa")
    p.add_argument("--modelo")
    p.add_argument("--sessao", help="retomar ID nativo, sem migrar entre providers")
    p.add_argument("--agente", help="nome nativo Claude/OpenCode")
    p.add_argument("--funcionario", help="ID do especialista cadastrado neste projeto")
    prompts = p.add_mutually_exclusive_group()
    prompts.add_argument("--prompt", help="execução com telemetria estruturada em Claude/Codex/OpenCode/Gemini")
    prompts.add_argument('--prompt-arquivo', type=Path, help='tarefa ou diagnóstico em UTF-8, evitando limites da linha de comando')
    p.add_argument("--banco", type=Path, help="SQLite opcional; padrão é o do escritório")
    p.add_argument("--papel", choices=["ceo", "diretor"], help="executor definido na política do projeto")
    p.add_argument("--equipe", help="especialidade configurada no projeto")
    p.add_argument("--escopo", choices=["planejamento", "implementacao", "revisao", "simples"])
    p.add_argument("--detectar", action="store_true", help="somente diagnóstico, não inicia console")
    p.add_argument("--preparar-skills", action="store_true", help="plano de links compartilhados .agents/skills (Codex/Gemini/OpenCode)")
    p.add_argument("--aplicar", action="store_true", help="aplica somente os links de skills")
    args = p.parse_args(argv)
    try:
        config = json.loads(args.config.read_text(encoding="utf-8-sig")) if args.config else {}
        if not isinstance(config, dict):
            raise ValueError("config precisa ser objeto JSON")
        projeto = args.projeto or (Path(config["projeto"]) if config.get("projeto") else None)
        if projeto is None or not projeto.is_dir():
            raise ValueError("Informe --projeto com uma pasta existente (ou projeto no --config).")
        projeto = projeto.resolve()
        if args.aplicar and not args.preparar_skills:
            raise ValueError("--aplicar exige --preparar-skills")
        if args.preparar_skills:
            print(json.dumps(preparar_codex(projeto, args.aplicar), ensure_ascii=False, indent=2))
            return 0
        gestao = args.papel or args.equipe or args.escopo or args.funcionario
        contexto_gestao = ""
        modelo = args.modelo or config.get("modelo")
        if gestao:
            import gestao_projeto
            politica = gestao_projeto.carregar(projeto)
            if args.funcionario:
                if args.papel or args.equipe or args.agente:
                    raise ValueError('--funcionario não combina com --papel/--equipe/--agente')
                import funcionarios
                funcionario=funcionarios.obter(projeto,args.funcionario)
                rota=funcionario['executor']
                if rota.get('execucao','cloud') == 'local':
                    gestao_projeto.executor({**politica,'rotas':{**politica['rotas'],args.escopo or 'simples':rota}},
                                           escopo=args.escopo or 'simples')
                contexto_gestao=funcionarios.contexto(projeto,funcionario)
            else:
                rota = gestao_projeto.executor(politica, args.papel, args.equipe, args.escopo)
            if args.provider and args.provider != rota["console"]:
                raise ValueError("--provider diverge da política selecionada")
            if args.modelo and args.modelo != rota.get("modelo", ""):
                raise ValueError("--modelo diverge da política selecionada")
            provider, exe = selecionar(rota["console"])
            modelo = rota.get("modelo") or None
            if not args.funcionario:
                contexto_gestao = gestao_projeto.contexto(projeto, politica, args.papel, args.equipe)
        else:
            provider, exe = selecionar(args.provider, config)
        if args.detectar:
            print(json.dumps({"provider": provider.nome, "cli": exe,
                              "capacidades": asdict(provider.capacidades)}, ensure_ascii=False, indent=2))
            return 0
        prompt = args.prompt
        if args.prompt_arquivo:
            with args.prompt_arquivo.open(encoding='utf-8-sig') as fonte:
                prompt = fonte.read(128001)
            if len(prompt) > 128000 or not prompt.strip():
                raise ValueError('Arquivo de prompt vazio ou maior que 128 mil caracteres; divida o contexto sem truncar')
        if contexto_gestao:
            prompt = contexto_gestao + "\n\nTarefa:\n" + (prompt or "Leia o estado do projeto e indique a próxima ação dentro do seu papel.")
        if gestao and rota.get('execucao','cloud') == 'local':
            from executor_local import executar as executar_local
            return executar_local(rota,politica,provider,exe,projeto,args.mesa or (funcionarios.nome_eventos(funcionario) if args.funcionario else None) or args.equipe or args.papel or 'Dev',
                                  prompt,args.sessao,args.agente,args.banco)
        skills_nativas=[]
        if args.funcionario:
            from skills_compartilhados import resolver
            skills_nativas=[r['nome'] for r in resolver(projeto,funcionario['skills'],politica,provider.nome)
                           if r.get('ativacao_nativa')=='Skill']
        return executar(provider, exe, projeto, args.mesa or (funcionarios.nome_eventos(funcionario) if args.funcionario else None) or args.equipe or args.papel or config.get("mesa") or "Dev", prompt,
                        modelo, args.sessao, args.agente, args.banco,skills_nativas=skills_nativas)
    except (OSError, ValueError) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
