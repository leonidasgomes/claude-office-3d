// Escritório 3D — plugin do OpenCode: cada ferramenta usada vira um evento na cena.
//
// Instalação: copie para `.opencode/plugins/office.js` do projeto e configure o ambiente:
//
//   OFFICE_EMIT=D:/escritorios/meu-app/emit_evento.py  (obrigatório)
//   OFFICE_AGENTE=Dev          (mesa do escritório; padrão: OpenCode)
//   OFFICE_PROJETOS=D:/projetos/meu-app,D:/projetos/outro   (opcional: só emite dentro destas pastas)
//   OFFICE_PYTHON=python       (opcional)
//   OFFICE_BANCO=...           (só testes: SQLite temporário no lugar do escritório)
//
// Sem OFFICE_EMIT o plugin não faz nada. Nunca bloqueia o agente: o emit roda solto
// (sem saída) e qualquer erro é tratado. Hook V1, usado pelo OpenCode 1.x.
// Erros de ferramentas são observados pelo evento message.part.updated.
import { spawn } from "node:child_process";
import path from "node:path";

const PYTHON = process.env.OFFICE_PYTHON || "python";
const EMIT = process.env.OFFICE_EMIT || "";
const AGENTE = process.env.OFFICE_AGENTE || "OpenCode";
const FONTE = process.env.OFFICE_FONTE || "opencode";
const BANCO = process.env.OFFICE_BANCO || "";
const CONSUMO_PROJETO = process.env.OFFICE_CONSUMO_PROJETO || "";
const PROJETOS = (process.env.OFFICE_PROJETOS || "")
  .split(",")
  .map((s) => s.trim().replace(/\\/g, "/").toLowerCase().replace(/\/$/, ""))
  .filter(Boolean);

function noProjeto(dir) {
  if (!PROJETOS.length) return true;
  const d = String(dir || "").replace(/\\/g, "/").toLowerCase().replace(/\/$/, "");
  return PROJETOS.some((q) => d === q || d.startsWith(q + "/"));
}

let fila = Promise.resolve();
function emitir(ev) {
  if (!EMIT || (process.env.OFFICE_STREAM_OWNER === "launcher" && !ev.sessao_pai)) return;
  // Ordem de início/fim preservada sem aguardar Python no hook do agente.
  fila = fila.then(() => new Promise((resolve) => {
    try {
      const args = BANCO ? [EMIT, "--banco", BANCO] : [EMIT];
      const filho = spawn(PYTHON, args, { stdio: ["pipe", "ignore", "ignore"], windowsHide: true });
      filho.on("error", resolve);
      filho.on("close", resolve);
      filho.stdin.on("error", () => {});
      filho.stdin.end(JSON.stringify(ev));
    } catch { resolve(); }
  })).catch(() => {});
}

let filaConsumo = Promise.resolve();
function consumo(dados) {
  if (!EMIT) return;
  filaConsumo = filaConsumo.then(() => new Promise((resolve) => {
    try {
      const args = [path.join(path.dirname(EMIT), "consumo_providers.py"), "--opencode"];
      if (BANCO) args.push("--banco", path.join(path.dirname(BANCO), "consumo_providers.db"));
      const filho = spawn(PYTHON, args, { stdio: ["pipe", "ignore", "ignore"], windowsHide: true });
      const prazo = setTimeout(() => { filho.kill(); resolve(); }, 10000);
      filho.on("error", () => { clearTimeout(prazo); resolve(); });
      filho.on("close", () => { clearTimeout(prazo); resolve(); });
      filho.stdin.on("error", () => {});
      filho.stdin.end(JSON.stringify(dados));
    } catch { resolve(); }
  })).catch(() => {});
}

function curto(v, limite = 90) {
  return String(v ?? "").split(/\s+/).join(" ").slice(0, limite);
}

function baseNome(caminho) {
  const partes = String(caminho || "").split(/[/\\]/);
  return partes[partes.length - 1] || "";
}

const CHAVES_RESUMO = ["description", "summary", "filePath", "file_path", "path", "pattern", "prompt", "command", "url", "query"];

// A tool `skill` do OpenCode vira ferramenta `Skill` com `skill: nome`: o `skills.py
// contar-uso` do escritório só conta esse formato (igual ao hook do Claude Code).
function ferramentaDe(tool, args) {
  if (tool === "skill" && (args || {}).name) return "Skill";
  return String(tool);
}

function resumoDe(tool, args) {
  args = args || {};
  if (tool === "skill" && args.name) return curto(`usa a skill ${args.name}`);
  if (args.skill) return curto(`usa a skill ${args.skill}`);
  for (const chave of CHAVES_RESUMO) {
    if (args[chave]) {
      if (chave === "filePath" || chave === "file_path" || chave === "path") {
        const verbo = tool === "read" ? "lê" : tool === "edit" || tool === "write" ? "edita" : "usa";
        return curto(`${verbo} ${baseNome(args[chave])}`);
      }
      return curto(args[chave]);
    }
  }
  return String(tool);
}

function detalheDe(tool, args) {
  const partes = [];
  if (ferramentaDe(tool, args) === "Skill") partes.push(`skill: ${args.name}`);
  for (const chave of ["skill", "args", "command", "filePath", "file_path", "path", "pattern", "query", "prompt", "url"]) {
    const v = (args || {})[chave];
    if (v) partes.push(`${chave}: ${v}`);
  }
  return partes.join("\n").slice(0, 400);
}

export const Office = async ({ directory }) => {
  const pendentes = new Map();
  const finalizados = new Set();
  const sessoes = new Map();
  const modelos = new Map();
  const chaveDe = (input) => `${input.sessionID || ""}:${input.callID || ""}`;
  const registrar = (info) => {
    if (!info?.id) return;
    const anterior = sessoes.get(info.id) || {};
    const pai = info.parentID || anterior.parentID;
    const papel = info.agent || anterior.agent || info.title || "Agente";
    sessoes.set(info.id, { ...anterior, ...info, parentID: pai, agent: papel,
      mesa: anterior.mesa || (pai ? `OpenCode_${String(papel).replace(/[^\w-]/g, "_").slice(0, 40)}_${info.id}` : AGENTE) });
  };
  const base = (input) => {
    const id = input.sessionID || "";
    const sessao = sessoes.get(id);
    return { agente: sessao?.mesa || AGENTE, fonte: FONTE, sessao: id, para: [],
      ...(sessao?.parentID ? { sessao_pai: sessao.parentID,
        agente_pai: sessoes.get(sessao.parentID)?.mesa || AGENTE, funcao: sessao.agent } : {}) };
  };
  return {
    // Início de comando que pode demorar (equivale ao PreToolUse do Claude Code).
    "tool.execute.before": async (input, output) => {
      if (!noProjeto(directory)) return;
      const args = output.args || input.args || {};
      pendentes.set(chaveDe(input), args);
      if (input.tool !== "bash") return;
      emitir({ ...base(input), tipo: "trabalho", ferramenta: ferramentaDe(input.tool, args), inicio: true, espera_s: 120, resumo: resumoDe(input.tool, args), detalhe: detalheDe(input.tool, args) });
    },
    // No after os argumentos ficam em input; output contém title/output/metadata.
    "tool.execute.after": async (input, output) => {
      if (!noProjeto(directory)) return;
      const chave = chaveDe(input);
      const args = input.args || pendentes.get(chave) || {};
      pendentes.delete(chave);
      finalizados.add(chave);
      if (finalizados.size > 2048) finalizados.delete(finalizados.values().next().value);
      const ev = { ...base(input), tipo: "trabalho", ferramenta: ferramentaDe(input.tool, args), resumo: resumoDe(input.tool, args), detalhe: detalheDe(input.tool, args) };
      const metadata = output.metadata || {};
      const codigo = metadata.exit ?? metadata.exitCode ?? metadata.exit_code;
      if (Number.isInteger(codigo)) { ev.codigo = codigo; ev.ok = codigo === 0; }
      if (input.tool === "task") {
        if (metadata.sessionId) registrar({ id: metadata.sessionId,
          parentID: metadata.parentSessionId || input.sessionID, agent: args.subagent_type });
        ev.tipo = "subagente";
        ev.para = [sessoes.get(metadata.sessionId)?.mesa || args.subagent_type || "Assistente"];
        if (metadata.sessionId) ev.sessao_filho = metadata.sessionId;
        ev.funcao = args.description || args.subagent_type || "";
      }
      emitir(ev);
    },
    event: async ({ event }) => {
      if (!noProjeto(directory)) return;
      const props = event.properties || {};
      if (event.type === "session.created" || event.type === "session.updated") {
        registrar(props.info);
      } else if (event.type === "message.updated") {
        const info = props.info;
        if (info?.role === "assistant" && typeof info.id === "string") {
          const valido = v => typeof v === "string" && v.length > 0 && v.length <= 256;
          modelos.set(info.id, { sessao: info.sessionID,
            modelo: valido(info.providerID) && valido(info.modelID) ? `${info.providerID}/${info.modelID}` : null });
          if (modelos.size > 4096) modelos.delete(modelos.keys().next().value);
        }
      } else if (event.type === "session.idle") {
        emitir({ ...base(props), tipo: "ocioso", ferramenta: "", resumo: "aguardando" });
      } else if (event.type === "session.error") {
        emitir({ ...base(props), tipo: "trabalho", ferramenta: "Console", ok: false,
          resumo: "erro do console", erro: curto(props.error?.data?.message || props.error?.message || "erro", 120) });
      } else if (event.type === "message.part.updated") {
        const part = props.part || {};
        if (part.type === "step-finish") {
          const sessao = sessoes.get(part.sessionID);
          // Pai do run pertence ao launcher; plugin observa filhos e a TUI.
          if (process.env.OFFICE_STREAM_OWNER === "launcher" && !sessao?.parentID) return;
          const modelo = modelos.get(part.messageID);
          consumo({ projeto: CONSUMO_PROJETO || directory, agente: base(part).agente,
            modelo: modelo?.sessao === part.sessionID ? modelo.modelo : null,
            rotulo: FONTE === "opencode_local" ? FONTE : "opencode",
            evento: { type: "step_finish", sessionID: part.sessionID, part: {
              type: "step-finish", id: part.id, sessionID: part.sessionID, tokens: part.tokens } } });
          return;
        }
        if (part.type !== "tool" || part.state?.status !== "error") return;
        const chave = chaveDe(part);
        if (finalizados.has(chave)) return;
        finalizados.add(chave);
        if (finalizados.size > 2048) finalizados.delete(finalizados.values().next().value);
        const args = part.state.input || pendentes.get(chave) || {};
        pendentes.delete(chave);
        emitir({ ...base(part), tipo: "trabalho", ferramenta: ferramentaDe(part.tool, args),
          resumo: resumoDe(part.tool, args), detalhe: detalheDe(part.tool, args), ok: false,
          erro: curto(part.state.error || "erro", 120) });
      }
    },
  };
};
