import assert from "node:assert/strict";
import { readFile, mkdtemp, mkdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const tmp = await mkdtemp(path.join(tmpdir(), "office-plugin-"));
await mkdir(path.join(tmp, "projeto"));
await mkdir(path.join(tmp, "principal"));
process.env.OFFICE_CONSUMO_PROJETO = path.join(tmp, "principal");
process.env.OFFICE_EMIT = path.join(root, "emit_evento.py");
process.env.OFFICE_PYTHON = process.env.TEST_PYTHON || "python";
process.env.OFFICE_AGENTE = "Dev";
process.env.OFFICE_BANCO = path.join(tmp, "office.db");
process.env.OFFICE_PROJETOS = path.join(tmp, "projeto");
const source = await readFile(path.join(root, "opencode", "office.js"), "utf8");
const { Office } = await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);
const hooks = await Office({ directory: path.join(tmp, "projeto") });
await hooks["tool.execute.before"]({ tool: "bash", sessionID: "s", callID: "1" }, { args: { command: "pytest -q" } });
await hooks["tool.execute.after"]({ tool: "bash", sessionID: "s", callID: "1", args: { command: "pytest -q" } }, { metadata: { exit: 1 } });
await hooks["tool.execute.after"]({ tool: "skill", sessionID: "s", callID: "2", args: { name: "teste" } }, { output: "loaded" });
await hooks.event({ event: { type: "message.part.updated", properties: { part: {
  type: "tool", tool: "bash", callID: "3", sessionID: "s", state: { status: "error", input: { command: "falha" }, error: "Exit code 2" }
} } } });
await hooks.event({ event: { type: "session.idle", properties: { sessionID: "s" } } });
const script = "import sqlite3,json,sys; c=sqlite3.connect(sys.argv[1]); print(json.dumps([json.loads(r[0]) for r in c.execute('SELECT dados FROM evento ORDER BY id')])); c.close()";
let eventos = [];
for (let n = 0; n < 80; n++) {
  await new Promise((r) => setTimeout(r, 100));
  try { eventos = JSON.parse(execFileSync(process.env.OFFICE_PYTHON, ["-c", script, process.env.OFFICE_BANCO], { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] })); } catch {}
  if (eventos.length === 5) break;
}
assert.equal(eventos.length, 5);
assert.equal(eventos[0].inicio, true);
assert.equal(eventos[1].detalhe, "command: pytest -q");
assert.equal(eventos[1].ok, false);
assert.equal(eventos[2].ferramenta, "Skill");
assert.equal(eventos[2].detalhe, "skill: teste");
assert.equal(eventos[3].ok, false);
assert.equal(eventos[4].tipo, "ocioso");
assert.equal(eventos[4].sessao, "s");
process.env.OFFICE_STREAM_OWNER = "launcher";
await hooks["tool.execute.after"]({ tool: "read", callID: "4", args: {} }, {});
process.env.OFFICE_STREAM_OWNER = "plugin";
const fora = await Office({ directory: path.join(tmp, "projeto-outro") });
await fora["tool.execute.after"]({ tool: "read", callID: "5", args: {} }, {});
await new Promise((r) => setTimeout(r, 150));
eventos = JSON.parse(execFileSync(process.env.OFFICE_PYTHON, ["-c", script, process.env.OFFICE_BANCO], { encoding: "utf8" }));
assert.equal(eventos.length, 5, "não duplica launcher nem registra projeto fora do filtro");
process.env.OFFICE_STREAM_OWNER = "launcher";
await hooks.event({ event: { type: "session.created", properties: { info: { id: "child", parentID: "s", agent: "qa" } } } });
await hooks["tool.execute.after"]({ tool: "read", sessionID: "child", callID: "6", args: { path: "README.md" } }, {});
await hooks.event({ event: { type: "session.idle", properties: { sessionID: "child" } } });
for (let n = 0; n < 80; n++) {
  await new Promise((r) => setTimeout(r, 100));
  eventos = JSON.parse(execFileSync(process.env.OFFICE_PYTHON, ["-c", script, process.env.OFFICE_BANCO], { encoding: "utf8" }));
  if (eventos.length === 7) break;
}
assert.equal(eventos.length, 7, "launcher preserva ferramentas dos filhos via plugin");
assert.equal(eventos[5].agente, "OpenCode_qa_child");
assert.equal(eventos[5].sessao_pai, "s");
assert.equal(eventos[5].agente_pai, "Dev");
assert.equal(eventos[6].agente, eventos[5].agente);
process.env.OFFICE_STREAM_OWNER = "plugin";
// Contadores TUI e filhos usam a ponte Python real, sem texto/cost e sem duplicação.
const atualizarModelo = async (id, sessionID, providerID) => hooks.event({event:{type:"message.updated",
  properties:{info:{id,sessionID,role:"assistant",providerID,modelID:"modelo",content:"NÃO ARMAZENAR"}}}});
const etapa = (sessionID,id,messageID) => ({event:{type:"message.part.updated",properties:{part:{
  type:"step-finish",sessionID,id,messageID,cost:999,tokens:{input:10,output:2,reasoning:3,cache:{read:20,write:1}}}}}});
await atualizarModelo("m1","s","google");
await hooks.event(etapa("s","p1","m1")); await hooks.event(etapa("s","p1","m1"));
process.env.OFFICE_STREAM_OWNER = "launcher";
await hooks.event(etapa("s","p2","m1")); // Principal permanece com o launcher.
await atualizarModelo("m2","child","openai");
await hooks.event(etapa("child","p3","m2")); await hooks.event(etapa("child","p3","m2"));
await fora.event(etapa("s","fora","m1"));
const scriptConsumo = "import sys,json; sys.path.insert(0,sys.argv[1]); from consumo_providers import Registro; print(json.dumps(Registro(sys.argv[2]).resumo()))";
let consumo;
for (let n=0;n<80;n++) {
  await new Promise(r=>setTimeout(r,100));
  consumo=JSON.parse(execFileSync(process.env.OFFICE_PYTHON,["-c",scriptConsumo,root,path.join(tmp,"consumo_providers.db")],{encoding:"utf8"}));
  if (consumo.grupos.reduce((n,g)=>n+g.amostras,0)===2) break;
}
assert.equal(consumo.grupos.reduce((n,g)=>n+g.amostras,0),2);
assert.equal(consumo.grupos.reduce((n,g)=>n+g.total,0),72);
assert.deepEqual(new Set(consumo.grupos.map(g=>g.provider_modelo)),new Set(["google","openai"]));
assert.ok(consumo.grupos.every(g=>g.origem_modelo==="informado" && g.entrada===31 && g.saida===5));
assert.equal(consumo.cobranca_usd,null);
const filtrar = "import sys,json; sys.path.insert(0,sys.argv[1]); from consumo_providers import Registro,identidade_projeto; print(json.dumps(Registro(sys.argv[2]).resumo(projeto_hash=identidade_projeto(sys.argv[3]))))";
const porProjeto = p => JSON.parse(execFileSync(process.env.OFFICE_PYTHON,["-c",filtrar,root,path.join(tmp,"consumo_providers.db"),path.join(tmp,p)],{encoding:"utf8"}));
assert.equal(porProjeto("principal").grupos.reduce((n,g)=>n+g.total,0),72);
assert.deepEqual(porProjeto("projeto").grupos,[],"cwd continua filtrando eventos; consumo usa projeto cadastrado");
assert.doesNotMatch(JSON.stringify(consumo),/NÃO ARMAZENAR|p1|p3|messageID|999/);
eventos=JSON.parse(execFileSync(process.env.OFFICE_PYTHON,["-c",script,process.env.OFFICE_BANCO],{encoding:"utf8"}));
assert.equal(eventos.length,7,"consumo não é evento de trabalho nem altera tabela Claude");
process.env.OFFICE_STREAM_OWNER = "plugin";
delete process.env.OFFICE_CONSUMO_PROJETO;
const { Office: Direto } = await import(`data:text/javascript;base64,${Buffer.from(source + "\n// direto").toString("base64")}`);
const direto=await Direto({directory:path.join(tmp,"projeto")});
await direto.event(etapa("direto","p-direto","m-direto"));
let consumoDireto;
for(let n=0;n<80;n++) {
  await new Promise(r=>setTimeout(r,100));
  consumoDireto=porProjeto("projeto");
  if(consumoDireto.grupos.length)break;
}
assert.equal(consumoDireto.grupos.reduce((n,g)=>n+g.total,0),36,"sem configuração, consumo continua na pasta de execução");
assert.equal(porProjeto("principal").grupos.reduce((n,g)=>n+g.total,0),72);
// ENOENT chega assincronamente: o plugin não pode derrubar o OpenCode.
process.env.OFFICE_PYTHON = path.join(tmp, "nao-existe");
const { Office: Missing } = await import(`data:text/javascript;base64,${Buffer.from(source + "\n// missing").toString("base64")}`);
await (await Missing({ directory: path.join(tmp, "projeto") }))["tool.execute.after"]({ tool: "read", args: {} }, {});
await new Promise((r) => setTimeout(r, 100));
console.log("OK: consumo TUI/filhos sem duplicação e plugin OpenCode (argumentos, ordem, falha, Skill, sessão, filtro, duplicação, ENOENT)");
