import assert from 'node:assert/strict';
import { linhasCota, linhasConsumo, linhasVisaoGeral, instalarIndicadores } from '../indicadores_providers.mjs';

const ausente = linhasCota({provider: 'codex', disponivel: false, limites: []}).join('\n');
assert.match(ausente, /não informada/);
assert.doesNotMatch(ausente, /0%/);
assert.match(linhasConsumo({grupos: [{provider: 'codex', modelo: 'x', origem_modelo: 'configurado', agente: 'Dev', amostras: 2, entrada: 20, com_entrada: 1, saida: null, total: null}]}).join('\n'), /20 \(parcial\).*saída não informado/);
assert.doesNotMatch(linhasConsumo({}).join('\n'), /US\$ ?0/);
assert.match(linhasConsumo({}).join('\n'), /sessões cloud novas do launcher/);
assert.match(linhasConsumo({}).join('\n'), /Retomada sem baseline: o primeiro agregado apenas estabelece referência/);
assert.match(linhasConsumo({}).join('\n'), /TUI, local e outras sessões\/team permanecem fora/);
assert.match(linhasConsumo({}).join('\n'), /Agregado de filhos pertence ao papel da sessão principal/);
const estimado = linhasConsumo({grupos:[{provider:'codex',modelo:'x',agente:'Dev',amostras:2,
  equivalente_api_usd:'2.5',com_preco:1}]}).join('\n');
assert.match(estimado,/USD 2.5 · 1\/2 amostras com preço · parcial/);
assert.match(estimado,/Não é cobrança da assinatura nem fatura/);
assert.match(linhasConsumo({precos:{estado:'catálogo inválido'}}).join('\n'),/cálculo suspenso/);
const texto = linhasCota({provider: 'codex', disponivel: true, desatualizado: true, coletado_em: 100,
  limites: [{nome: '<script>conta</script>', janelas: [{duracao_min: 10080, usado_pct: 90,
    restante_pct: 10, expirado: true, renova_em: 200}]}]}).join('\n');
assert.match(texto, /semana: 90% usado · 10% restante/);
assert.match(texto, /desatualizada/);
assert.match(texto, /anterior à renovação/);
assert.doesNotMatch(texto, /US\$/);
assert.match(linhasCota({provider: 'codex', limites: [{nome: 'x', janelas: [{usado_pct: null}]}]}).join('\n'), /uso indisponível/);

const grupo = (provider, total, amostras = 1, cobertura = 1) => ({provider, amostras,
  entrada: total, cache: total, saida: null, total,
  com_entrada: cobertura, com_saida: 0, com_total: cobertura});
const geral = linhasVisaoGeral({grupos: [grupo('codex', 100, 2), grupo('gemini', 200),
  grupo('codex_local', 50)], providers: [{usado_pct: 90}, {usado_pct: 80}]}).join('\n');
assert.match(geral, /Cloud observado: entrada 300 \(2\/3 amostras com dado · parcial\), saída não informado, total 300/);
assert.match(geral, /Local observado: entrada 50 \(1\/1 amostras com dado\)/);
assert.doesNotMatch(geral, /170%|350|600|US\$ ?0/); // Cota, local e cache não inflam o total cloud.
assert.match(geral, /não representa todo o uso/);
assert.match(geral, /tokenizadores diferentes/);
assert.match(linhasVisaoGeral({grupos: [grupo('codex', 0)]}).join('\n'), /entrada 0 \(1\/1/);
assert.match(linhasVisaoGeral({grupos: [grupo('codex', null, 1, 0)]}).join('\n'), /total não informado/);
assert.match(linhasVisaoGeral({}).join('\n'), /Sem consumo observado/);
assert.match(linhasVisaoGeral({erro: 'x', grupos: [grupo('codex', 10)]}).join('\n'), /indisponível/);
assert.match(linhasVisaoGeral({grupos: [grupo('codex', 10, -1)]}).join('\n'), /cobertura inválida/);
assert.match(linhasVisaoGeral({grupos: [grupo('codex', Number.MAX_SAFE_INTEGER),
  grupo('gemini', Number.MAX_SAFE_INTEGER)]}).join('\n'), /18\.014\.398\.509\.481\.982/);

const oc = linhasConsumo({grupos: [{...grupo('opencode', 122), modelo:'openai/modelo',
  origem_modelo:'configurado', provider_modelo:'openai', origem_provider_modelo:'configurado', agente:'Dev'}]}).join('\n');
assert.match(oc, /opencode · openai\/modelo.*provider do modelo: openai \(configurado\)/);
assert.match(oc, /não comprova o backend real/);
assert.match(linhasConsumo({grupos:[{...grupo('opencode',10),modelo:'não informado'}]}).join('\n'),
             /provider do modelo: não informado/);

// O painel fechado/aba oculta não consulta. Dados externos só passam por textContent.
class Elemento {
  children = []; textContent = '';
  append(e) { this.children.push(e); }
  setAttribute() {}
  replaceChildren() { this.children = []; }
  set innerHTML(_) { throw new Error('HTML externo proibido'); }
}
const painel = {hidden: true}; let secao, observar, intervalo, chamadas = 0;
globalThis.document = {hidden: false, createElement: () => new Elemento(), addEventListener() {}};
globalThis.MutationObserver = class { constructor(fn) { observar = fn; } observe() {} };
globalThis.setInterval = (fn) => { intervalo = fn; };
globalThis.fetch = async () => { chamadas++; return {ok: true, json: async () => ({providers: [{provider: 'codex', disponivel: false}]})}; };
instalarIndicadores(painel, {before(e) { secao = e; }});
assert.equal(chamadas, 0);
painel.hidden = false; document.hidden = true; await observar(); assert.equal(chamadas, 0);
document.hidden = false; await observar(); assert.equal(chamadas, 1);
await intervalo(); assert.equal(chamadas, 1); // Atualização limitada a uma por minuto.
assert.match(secao.children.map(e => e.textContent).join('\n'), /Percentuais não são somados/);
assert.match(secao.children.map(e => e.textContent).join('\n'), /Claude/);
console.log('Indicadores: cotas separadas, ausência explícita e consultas só com painel visível — OK');
