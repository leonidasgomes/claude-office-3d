// Claude Office 3D — Placar do time: XP e nível dos agentes (GET /xp), painel, rótulos nas mesas e comemoração.
// Sem ranking competitivo: só nome ou nível como ordem, sem medalhas. Se /xp não existir, usa uma demonstração.

import { CONFIG } from './config.js';

const ATUALIZAR_MS = 60000;
const CHAVE_NIVEIS = 'office.xp.niveis', CHAVE_ORDEM = 'office.placar.ordem';
const NIVEIS_BASE = [{ nivel: 1, titulo: 'Estagiário', xp: 0 }, { nivel: 2, titulo: 'Júnior', xp: 20 }, { nivel: 3, titulo: 'Pleno', xp: 60 },
  { nivel: 4, titulo: 'Sênior', xp: 150 }, { nivel: 5, titulo: 'Mestre', xp: 300 }];
// níveis do config.json (xp.niveis); até 5 níveis têm cor/estrela própria, acima disso repete a última
const NIVEIS_PADRAO = Array.isArray(CONFIG.xp.niveis) && CONFIG.xp.niveis.length ? CONFIG.xp.niveis : NIVEIS_BASE;

const $ = (id) => document.getElementById(id);
const xpAtivo = CONFIG.xp.ativo !== false;
const painel = $('placar'), listaEl = $('placarLista'), infoEl = $('placarInfo'), timeEl = $('placarTime'), contaEl = $('placarConta');
const office = () => window.__office;
function el(tag, cls, texto) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (texto != null) e.textContent = texto;
  return e;
}
const lerLS = (k, padrao) => { try { const v = localStorage.getItem(k); return v == null ? padrao : v; } catch (e) { return padrao; } };
const gravarLS = (k, v) => { try { localStorage.setItem(k, v); } catch (e) {} };

let real = null;          // último /xp válido (null = indisponível)
let injetado = false;     // __placar.aplicar() manual: não deixa a demonstração sobrescrever
let demo = null;          // placar falso
let atual = null;         // dados normalizados em exibição
let fonte = '';           // 'real' | 'demo' | 'injetado'
let ordem = lerLS(CHAVE_ORDEM, 'nome') === 'nivel' ? 'nivel' : 'nome';
let visto = null;         // níveis vistos em memória (demonstração)

// ---------------------------------------------------------------- Normalização
function nivelPorXp(niveis, xp) { let n = niveis[0]; for (const x of niveis) if (xp >= x.xp) n = x; return n; }
function normalizar(obj) {
  if (!obj || typeof obj !== 'object' || typeof obj.agentes !== 'object' || !obj.agentes) throw new Error('formato inesperado');
  const niveis = Array.isArray(obj.niveis) && obj.niveis.length ? obj.niveis.slice().sort((a, b) => a.nivel - b.nivel) : NIVEIS_PADRAO;
  const agentes = {};
  for (const [nome, d0] of Object.entries(obj.agentes)) {
    const d = { ...d0 }, xp = Number(d.xp) || 0;
    const porXp = nivelPorXp(niveis, xp);
    d.xp = xp; d.nivel = Number(d.nivel) || porXp.nivel;
    const def = niveis.find((x) => x.nivel === d.nivel) || porXp, prox = niveis.find((x) => x.nivel === d.nivel + 1);
    d.titulo_nivel = d.titulo_nivel || def.titulo; d.xp_base = def.xp;
    d.xp_proximo = d.xp_proximo !== undefined ? d.xp_proximo : (prox ? prox.xp : null);
    d.titulo_proximo = prox ? prox.titulo : null;
    d.ultimos = Array.isArray(d.ultimos) ? d.ultimos : []; d.auditoria = Array.isArray(d.auditoria) ? d.auditoria : [];
    d.skills_autor = Array.isArray(d.skills_autor) ? d.skills_autor : [];
    agentes[nome] = d;
  }
  return { atualizado: obj.atualizado || '', niveis, time: obj.time || {}, agentes };
}

// ---------------------------------------------------------------- Demonstração
function hash(n) { let h = 7; for (const c of String(n)) h = (h * 33 + c.charCodeAt(0)) >>> 0; return h; }
const MOTIVOS_DEMO = [['aprovado de primeira +3', 'cartão fechado +2'], ['aprovado de primeira +3'], ['cartão fechado +2', 'skill reusada +1'],
  ['aprovado após ajustes +1', 'cartão fechado +2'], ['revisão pediu mudanças -1', 'cartão fechado +2']];
function agentesDoEscritorio() {
  const o = office(); if (!o) return [];
  return [...o.agentes.keys()].filter((n) => !/^(outra_sessao|assistente)$/i.test(n));
}
function gerarAgenteDemo(nome, i) {
  const h = hash(nome), xp = [95, 42, 28, 12][i] ?? 6 + (h % 80), prs = 2 + Math.round(xp / 6);
  const somar = (m) => m.reduce((s, x) => s + (parseInt((x.match(/[+-]\d+$/) || ['0'])[0], 10) || 0), 0);
  const ultimos = [0, 1, 2].map((k) => { const m = MOTIVOS_DEMO[(h + k) % MOTIVOS_DEMO.length];
    return { pr: 230 - k * 3 - (h % 3), pontos: somar(m), motivos: m, data: new Date(Date.now() - (k * 20 + 2) * 3600e3).toISOString() }; });
  const d = { xp, prs, ultimos, auditoria: [], skills_autor: h % 2 ? ['exemplo-de-skill'] : [], skills_reusadas_por_outros: h % 4 };
  if (i === 0) d.auditoria = [{ pr: 231, motivo: 'apagou teste' }];
  return d;
}
function montarDemo() {
  const nomes = agentesDoEscritorio();
  if (!demo) demo = { atualizado: '', niveis: NIVEIS_PADRAO, time: {}, agentes: {} };
  nomes.forEach((n, i) => { if (!demo.agentes[n]) demo.agentes[n] = gerarAgenteDemo(n, i); });
  const ags = Object.values(demo.agentes);
  for (const d of ags) {
    const nv = nivelPorXp(NIVEIS_PADRAO, d.xp), px = NIVEIS_PADRAO.find((x) => x.nivel === nv.nivel + 1);
    d.nivel = nv.nivel; d.titulo_nivel = nv.titulo; d.xp_proximo = px ? px.xp : null;
  }
  demo.atualizado = new Date().toISOString();
  demo.time = { xp_total: ags.reduce((s, d) => s + d.xp, 0), prs_pontuados: ags.reduce((s, d) => s + d.prs, 0), aprovacao_primeira: 0.83,
    retrabalho_14d: 0.05, auditorias_abertas: ags.reduce((s, d) => s + d.auditoria.length, 0) };
  return demo;
}
function evoluirDemo() {   // a cada ~40 s alguém ganha pontos; metade das vezes sobe de nível (para ver a comemoração)
  if (!demo) return;
  const ags = Object.entries(demo.agentes).filter(([, d]) => d.xp_proximo != null);
  if (!ags.length) return;
  ags.sort((a, b) => (a[1].xp_proximo - a[1].xp) - (b[1].xp_proximo - b[1].xp));
  const d = (Math.random() < 0.5 ? ags[0] : ags[(Math.random() * ags.length) | 0])[1];
  d.xp += Math.random() < 0.5 ? d.xp_proximo - d.xp : 2 + ((Math.random() * 4) | 0);
  d.prs++;
  d.ultimos.unshift({ pr: (d.ultimos[0] ? d.ultimos[0].pr : 230) + 2, pontos: 5, motivos: ['aprovado de primeira +3', 'cartão fechado +2'], data: new Date().toISOString() });
  d.ultimos.length = Math.min(d.ultimos.length, 5);
}

// ---------------------------------------------------------------- Aplicar dados
function aplicar(obj, opcoes = {}) {
  const dados = normalizar(obj);
  const novaFonte = opcoes.fonte || 'real';
  const o = office();
  // níveis vistos antes: localStorage (dados reais) ou memória (demonstração)
  let anteriores = null;
  if (novaFonte === 'demo') anteriores = novaFonte !== fonte ? null : visto;
  else { try { anteriores = JSON.parse(lerLS(CHAVE_NIVEIS, 'null')); } catch (e) { anteriores = null; } }
  const novos = {}, subiram = [];
  for (const [nome, d] of Object.entries(dados.agentes)) {
    novos[nome] = d.nivel;
    if (anteriores && typeof anteriores[nome] === 'number' && d.nivel > anteriores[nome]) subiram.push([nome, d.titulo_nivel]);
  }
  fonte = novaFonte; atual = dados;
  if (novaFonte === 'demo') visto = novos; else gravarLS(CHAVE_NIVEIS, JSON.stringify({ ...(anteriores || {}), ...novos }));
  if (o) {
    for (const a of o.agentes.values()) {
      const d = dados.agentes[a.nome];
      o.xpDefinir(a.nome, d ? { nivel: d.nivel, titulo: d.titulo_nivel, xp: d.xp, xp_base: d.xp_base, xp_proximo: d.xp_proximo } : null);
    }
    subiram.forEach(([nome, titulo], i) => setTimeout(() => o.comemorar(nome, titulo), i * 700));
    o.atualizarFicha();
  }
  const aud = Number(dados.time.auditorias_abertas) || 0;
  contaEl.hidden = !aud; contaEl.textContent = aud;
  if (!painel.hidden) desenhar();
  return dados;
}

// ---------------------------------------------------------------- Painel
const pct = (v) => (typeof v === 'number' ? Math.round(v * 100) + '%' : '—');
function tile(valor, rotulo, cor, alerta) {
  const t = el('div', 'tile' + (alerta ? ' alerta' : '')); if (cor && !alerta) t.style.borderTopColor = cor;
  t.append(el('b', null, valor), el('span', null, rotulo)); return t;
}
function nomeExibido(nome) { const a = office() && office().agentes.get(nome); return a ? a.titulo : String(nome).replace(/_/g, ' '); }
function corDe(nome) { const a = office() && office().agentes.get(nome); return a ? '#' + a.cor.toString(16).padStart(6, '0') : '#64748b'; }
function desenhar() {
  const o = office(); if (!atual) return;
  const cn = (n) => (o ? o.CORES_NIVEL : ['#9ca3af'])[Math.max(0, Math.min(4, n - 1))] || '#9ca3af';
  const t = atual.time;
  timeEl.textContent = '';
  const aud = Number(t.auditorias_abertas) || 0;
  timeEl.append(tile(String(t.xp_total ?? 0), 'XP total do time', '#f59e0b'), tile(pct(t.aprovacao_primeira), 'aprovado de primeira', '#22c55e'),
    tile(pct(t.retrabalho_14d), 'retrabalho em 14 dias', '#3b82f6'), tile(String(aud), 'auditorias abertas', '#22c55e', aud > 0));
  document.querySelectorAll('#placarOrdem button').forEach((b) => b.classList.toggle('ativo', b.dataset.ordem === ordem));
  const ags = Object.entries(atual.agentes);
  ags.sort((a, b) => (ordem === 'nivel' ? b[1].nivel - a[1].nivel || b[1].xp - a[1].xp : 0) || nomeExibido(a[0]).localeCompare(nomeExibido(b[0]), 'pt-BR'));
  listaEl.textContent = '';
  if (!ags.length) listaEl.append(el('li', 'vazio', 'Nenhum agente pontuado ainda.'));
  for (const [nome, d] of ags) {
    const li = el('li', 'ag'); li.style.borderLeftColor = corDe(nome); li.title = nome;
    const topo = el('div', 'topo'), nm = el('span', 'nome', nomeExibido(nome)); nm.style.color = corDe(nome);
    const nv = el('span', 'nivel'); nv.style.color = cn(d.nivel);
    nv.append(el('span', null, '★'.repeat(Math.min(5, d.nivel))), el('span', 'vazia', '☆'.repeat(Math.max(0, 5 - d.nivel))), document.createTextNode(' ' + d.titulo_nivel));
    topo.append(nm, nv);
    if (d.auditoria.length) topo.append(el('span', 'aud', '⚠ ' + d.auditoria.length + ' auditoria(s)'));
    topo.append(el('span', 'xp', d.xp + ' XP · ' + (d.prs || 0) + ' PR(s)'));
    const barra = el('div', 'xp-barra'), enc = el('i');
    enc.style.width = Math.round((o ? o.progressoXp(d) : 0) * 100) + '%'; enc.style.background = cn(d.nivel); barra.append(enc);
    li.append(topo, barra, el('div', 'prox', d.xp_proximo == null ? 'nível máximo' : 'faltam ' + Math.max(0, d.xp_proximo - d.xp) + ' XP para ' + (d.titulo_proximo || 'o próximo nível')));
    const ul = el('ul', 'pontos');
    for (const u of d.ultimos.slice(0, 3)) {
      const ms = u.motivos || [], p = el('li');
      p.append(el('span', 'p ' + (u.pontos < 0 ? 'neg' : 'pos'), (u.pontos > 0 ? '+' : '') + u.pontos), el('span', null, (u.pr != null ? 'PR #' + u.pr : 'Skills') + ' · ' + (ms[0] || '') + (ms.length > 1 ? ' …' : '')));
      ul.append(p);
    }
    if (ul.children.length) li.append(ul);
    li.addEventListener('click', () => { if (o) o.ficha(nome, 'xp'); });
    listaEl.append(li);
  }
  const hora = atual.atualizado ? new Date(atual.atualizado).toLocaleTimeString('pt-BR') : '';
  infoEl.textContent = fonte === 'demo'
    ? (real === null ? '⚠️ placar indisponível — mostrando uma demonstração' : 'modo demonstração — pontos de mentira') + (hora ? ' · ' + hora : '')
    : 'atualizado às ' + hora + (fonte === 'injetado' ? ' · dados injetados' : '');
}
function abrir() {
  ['prs', 'kanban'].forEach((id) => { const e = $(id); if (e) e.hidden = true; });
  painel.hidden = false; desenhar();
}
function fechar() { painel.hidden = true; }
$('btnPlacar').addEventListener('click', () => (painel.hidden ? abrir() : fechar()));
$('placarFechar').addEventListener('click', fechar);
$('btnPrs').addEventListener('click', fechar);
$('btnKanban').addEventListener('click', fechar);
$('btnApelidos').addEventListener('click', () => { if (!painel.hidden) desenhar(); });
document.querySelectorAll('#placarOrdem button').forEach((b) => b.addEventListener('click', () => { ordem = b.dataset.ordem; gravarLS(CHAVE_ORDEM, ordem); desenhar(); }));
window.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !painel.hidden) fechar(); });

// ---------------------------------------------------------------- Busca periódica
async function buscar() {
  try {
    const r = await fetch('/xp', { cache: 'no-store' });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const j = await r.json();
    normalizar(j);
    real = j;
  } catch (e) { real = null; }
  decidir();
}
function decidir() {   // escolhe entre dados reais e demonstração
  if (injetado || !office()) return;
  const demonstrar = real === null || office().emDemo();
  try { aplicar(demonstrar ? montarDemo() : real, { fonte: demonstrar ? 'demo' : 'real' }); } catch (e) { console.warn('placar:', e); }
}
let ultimoModo = null;
function vigiar() {   // religa a decisão quando o botão Demo muda ou ganha mesa nova
  const o = office();
  if (o) {
    const modo = injetado ? 'i' : (real === null || o.emDemo() ? 'd' : 'r') + agentesDoEscritorio().length;
    if (modo !== ultimoModo) { ultimoModo = modo; decidir(); }
  }
  setTimeout(vigiar, 1000);
}
if (xpAtivo) {
  setInterval(() => { if (!injetado && fonte === 'demo') { evoluirDemo(); decidir(); } }, 40000);
  setInterval(buscar, ATUALIZAR_MS);
  buscar(); vigiar();
} else {   // "xp.ativo": false no config.json: sem botão, sem aba, sem rótulos de nível
  $('btnPlacar').hidden = true; $('abaXp').hidden = true;
}

window.__placar = {
  aplicar: (obj) => { injetado = true; return aplicar(obj, { fonte: 'injetado' }); },
  voltar: () => { injetado = false; ultimoModo = null; return buscar(); },
  agente: (nome) => (atual && atual.agentes[nome]) || null,
  get indisponivel() { return fonte === 'demo' && real === null; },
  get dados() { return atual; },
  buscar, evoluirDemo: () => { evoluirDemo(); decidir(); },
};
