import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { criarContextoProjeto } from '../contexto_projeto.mjs';
class Elemento {
  children = []; events = {}; attributes = {}; textContent = ''; open = false; isConnected = true; value = '';
  constructor(tag) { this.tag = tag; }
  append(...els) { for (const el of els) { el.parent = this; this.children.push(el); } }
  replaceChildren(...els) { this.children = []; this.append(...els); }
  addEventListener(event, callback) { this.events[event] = callback; }
  setAttribute(name, value) { this.attributes[name] = value; }
  showModal() { this.open = true; }
  close() { this.open = false; this.events.close?.(); }
  focus() { this.focused = true; }
  click() { return this.events.click?.(); }
  set innerHTML(_) { throw new Error('HTML externo proibido'); }
}
globalThis.document = { body: new Elemento('body'), createElement: tag => new Elemento(tag) };
const chamadas = [];
globalThis.fetch = (url, options) => new Promise(resolve => chamadas.push({ url, options, resolve }));
const responder = (body, status = 200, chamada = chamadas.at(-1)) => chamada.resolve({ ok: status === 200, status, json: async () => body });
const elementos = el => [el, ...el.children.flatMap(elementos)];
const texto = el => elementos(el).map(e => e.textContent).join('\n');
const contexto = criarContextoProjeto(), painel = document.body.children[0], origem = new Elemento('button');
const campo = elementos(painel).find(e => e.tag === 'input');
const form = elementos(painel).find(e => e.tag === 'form');
const botao = elementos(painel).find(e => e.textContent === 'Pesquisar');
const pesquisar = q => { campo.value = q; return form.events.submit({ preventDefault() {} }); };
const a = 'a'.repeat(20), b = 'b'.repeat(20);
const hit = { tipo: 'documento', fonte: '<script>fonte</script>.md', papel: 'regras', revisao: 'a'.repeat(64),
  data: '2026-10-12T18:00:00Z', linha: 2, trecho: '<img src=x onerror=alert(1)>pesquisa', trecho_truncado: true };
const dados = { ok: true, projeto_id: a, resultados: [hit], fontes: [{ tipo: 'documento', papel: 'regras', estado: 'disponivel' },
  { tipo: 'entrega', estado: 'indisponivel_ou_excluida' }], limitado: true, limite: 'Histórico exige 32 MiB e Python 3.11+.' };
assert.equal(chamadas.length, 0);
contexto.abrir(a, 'Projeto <img>', origem);
assert.equal(chamadas.length, 0, 'Abrir contexto não busca documentos automaticamente');
assert.equal(contexto.aberta, true);
assert.equal(campo.focused, true);
await pesquisar('a'); assert.equal(chamadas.length, 0);
let tarefa = pesquisar('pesquisa & regra');
assert.equal(chamadas.at(-1).url, `/api/gestao/contexto?projeto=${a}&q=pesquisa%20%26%20regra`);
assert.equal(chamadas.at(-1).options.cache, 'no-store');
assert.equal(botao.disabled, true);
responder(dados); await tarefa;
assert.equal(botao.disabled, false);
assert.match(texto(painel), /Cobertura parcial/);
assert.match(texto(painel), /Histórico de entregas · indisponível ou excluído; não pesquisado/);
assert.match(texto(painel), /snapshot da árvore de trabalho atual/);
assert.match(texto(painel), /Trecho limitado/);
assert.equal(elementos(painel).find(e => e.tag === 'pre').textContent, hit.trecho);
assert.equal(elementos(painel).some(e => ['script', 'img', 'iframe'].includes(e.tag)), false);
painel.events.close(); assert.match(texto(painel), /referência\(s\)/, 'Close tardio não limpa diálogo aberto');
// Consulta antiga não vence uma consulta mais recente.
tarefa = pesquisar('antiga'); const antiga = chamadas.at(-1);
let nova = pesquisar('nova'); assert.equal(antiga.options.signal.aborted, true);
responder({ ...dados, resultados: [{ ...hit, trecho: 'NOVA' }] }); await nova;
responder({ ...dados, resultados: [{ ...hit, trecho: 'ANTIGA' }] }, 200, antiga); await tarefa;
assert.match(texto(painel), /NOVA/); assert.doesNotMatch(texto(painel), /ANTIGA/);
// Troca de projeto limpa e invalida tudo, inclusive respostas tardias.
tarefa = pesquisar('pesquisa'); const pendente = chamadas.at(-1);
contexto.abrir(b, 'Projeto B'); assert.equal(pendente.options.signal.aborted, true);
responder(dados, 200, pendente); await tarefa;
assert.doesNotMatch(texto(painel), /<script>fonte/);
tarefa = pesquisar('pesquisa'); responder(dados); await tarefa;
assert.match(texto(painel), /não corresponde ao projeto/);
contexto.abrir(a, 'Projeto A', origem);
tarefa = pesquisar('pesquisa'); const fecharPendente = chamadas.at(-1);
painel.events.cancel({ preventDefault() {} });
assert.equal(contexto.aberta, false); assert.equal(origem.focused, true); assert.equal(campo.value, '');
responder(dados, 200, fecharPendente); await tarefa;
assert.equal(elementos(painel).some(e => e.tag === 'article'), false);
contexto.abrir(a);
tarefa = pesquisar('pesquisa'); responder({}, 403); await tarefa;
assert.match(texto(painel), /somente no PC/);
tarefa = pesquisar('pesquisa'); responder({}, 409); await tarefa;
assert.match(texto(painel), /tente novamente/);
tarefa = pesquisar('pesquisa'); responder({ ...dados, resultados: [], limitado: false }); await tarefa;
assert.match(texto(painel), /Nenhuma referência encontrada nas fontes consultadas/);
tarefa = pesquisar('pesquisa'); responder({ ...dados, fontes: [{ tipo: 'entrega', estado: 'indisponivel_ou_excluida', motivo: 'repositorio_nao_configurado' }] }); await tarefa;
assert.match(texto(painel), /Histórico não pesquisado: este projeto não tem repositório configurado/);
// Só links de PR validado; sem renderização de links existentes nos trechos.
const entrega = { ...hit, tipo: 'entrega', fonte: 'Entrega', url: 'https://github.com/o/r/pull/2', head: 'd'.repeat(40),
  objetivo_gdd: 1, gdd_sha256: 'e'.repeat(64), evidencia_sha256: 'f'.repeat(64) };
tarefa = pesquisar('pesquisa'); responder({ ...dados, resultados: [entrega] }); await tarefa;
let link = elementos(painel).find(e => e.tag === 'a'); assert.equal(link.href, entrega.url); assert.equal(link.rel, 'noopener noreferrer');
assert.match(texto(painel), /não comprova aceite do usuário/);
for (const url of ('javascript:alert(1)|https://github.com.evil/o/r/pull/2|https://github.com/o/../pull/2').split('|')) {
  tarefa = pesquisar('pesquisa'); responder({ ...dados, resultados: [{ ...entrega, url }] }); await tarefa;
  assert.equal(elementos(painel).some(e => e.tag === 'a'), false);
}
tarefa = pesquisar('pesquisa'); responder({ ...dados, resultados: Array.from({ length: 25 }, () => ({ ...hit, trecho: 'x'.repeat(1000) })) }); await tarefa;
assert.equal(elementos(painel).filter(e => e.tag === 'article').length, 20);
assert.equal(elementos(painel).find(e => e.tag === 'pre').textContent.length, 400);
contexto.fechar(); assert.equal(contexto.aberta, false);
const gestao = readFileSync(new URL('../gestao_painel.js', import.meta.url), 'utf8');
assert.match(gestao, /contextoProjeto\.abrir\(p\.id,p\.nome,botaoContexto\)/);
assert.match(gestao, /if \(contextoProjeto\.aberta\) return/);
assert.match(gestao, /contextoProjeto\.fechar\(\)/);
console.log('Contexto: busca sob demanda, escopo, proveniência, cobertura parcial, XSS, links, concorrência, troca, Escape e limpeza — OK');
