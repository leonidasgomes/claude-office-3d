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
    d.conferir = Array.isArray(d.conferir) ? d.conferir : [];
    d.skills_autor = Array.isArray(d.skills_autor) ? d.skills_autor : [];
    agentes[nome] = d;
  }
  return { atualizado: obj.atualizado || '', repo: String(obj.repo || ''), niveis, time: obj.time || {}, agentes,
    resolvidos: Array.isArray(obj.resolvidos) ? obj.resolvidos.filter((x) => x && Number.isInteger(x.pr)) : [] };
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
  if (i === 1) d.conferir = [{ pr: 229, motivo: 'skip condicional em tests/test_exemplo.py' }];
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
    retrabalho_14d: 0.05, auditorias_abertas: ags.reduce((s, d) => s + d.auditoria.length, 0),
    conferir_abertos: ags.reduce((s, d) => s + (d.conferir || []).length, 0) };
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
  const aud = Number(dados.time.auditorias_abertas) || 0, conf = Number(dados.time.conferir_abertos) || 0;
  contaEl.hidden = !(aud || conf); contaEl.textContent = aud || conf;   // vermelho se houver auditoria, amarelo se só conferir
  contaEl.classList.toggle('amarelo', !aud && conf > 0);
  contaEl.title = aud ? aud + ' auditoria(s) aberta(s)' : conf + ' PR(s) para conferir';
  if (!painel.hidden) desenhar();
  return dados;
}

// ---------------------------------------------------------------- Painel
const pct = (v) => (typeof v === 'number' ? Math.round(v * 100) + '%' : '—');
function tile(valor, rotulo, cor, alerta) {   // alerta: true (tile vermelho) ou 'amarelo'
  const t = el('div', 'tile' + (alerta === 'amarelo' ? ' aviso' : alerta ? ' alerta' : '')); if (cor && !alerta) t.style.borderTopColor = cor;
  t.append(el('b', null, valor), el('span', null, rotulo)); return t;
}
function nomeExibido(nome) { const a = office() && office().agentes.get(nome); return a ? a.titulo : String(nome).replace(/_/g, ' '); }
function corDe(nome) { const a = office() && office().agentes.get(nome); return a ? '#' + a.cor.toString(16).padStart(6, '0') : '#64748b'; }
// Listas das duas faixas: 🔴 auditoria (pontos zerados) e 🟡 para conferir (pontos normais), com link do PR e os botões para resolver
const faixasEl = el('div'); faixasEl.id = 'placarFaixas'; $('placarOrdem').before(faixasEl);
function linkPr(n) {
  const repo = atual && atual.repo;
  if (!repo || !/^[\w.-]+\/[\w.-]+$/.test(repo)) return el('b', null, 'PR #' + n);
  const a = el('a', null, 'PR #' + n); a.href = 'https://github.com/' + repo + '/pull/' + n; a.target = '_blank'; a.rel = 'noopener noreferrer';
  return a;
}
// Ações de XP pelos botões (POST /api/xp/<conferido|liberar|desfazer>). O PC (localhost) pode tudo; um celular pareado com
// "conferir" só marca ✓ Conferido e desfaz o que foi conferido; com "ver" não há botões. O servidor confere tudo de novo
// (permissão, CSRF, limite): aqui é só o que mostrar.
let sessao = null;       // {nome, permissao: 'pc' | 'conferir' | 'ver', csrf}, de GET /api/sessao
let historico = [];      // GET /api/acoes, mais recentes primeiro
const ROTULO_ACAO = { conferido: '✓ Conferido', liberar: 'Liberar pontos', desfazer: 'Desfazer' };
const FLAG_ACAO = { conferido: '--conferido', liberar: '--liberar', desfazer: '--desfazer' };
const TEXTO_ACAO = { conferido: 'marcado como conferido', liberar: 'liberado da auditoria', desfazer: 'voltou a ser auditado/conferido' };
const ROTULO_HIST = { conferido: 'conferiu', liberar: 'liberou os pontos de', desfazer: 'desfez', parear: 'pareou o aparelho', revogar: 'revogou',
  inscrever: 'ligou o push de alertas em', sair: 'desligou o push de alertas em', prefs: 'mudou os tipos de alerta em', teste: 'enviou um alerta de teste de' };
let ocupado = false, toastTimer = null, resolvidosAberto = false, historicoAberto = false;
const toastEl = el('div'); toastEl.id = 'placarToast'; toastEl.hidden = true; document.body.append(toastEl);
function toast(msg, desfazerPr, erro) {
  clearTimeout(toastTimer); toastEl.textContent = ''; toastEl.hidden = false; toastEl.classList.toggle('erro', !!erro);
  toastEl.append(el('span', null, msg));
  if (desfazerPr) {
    const b = el('button', 'link', 'desfazer');
    b.addEventListener('click', () => { toastEl.hidden = true; acao('desfazer', desfazerPr); });
    toastEl.append(b);
  }
  toastTimer = setTimeout(() => { toastEl.hidden = true; }, 10000);
}
async function pegarJson(url) {
  try { const r = await fetch(url, { cache: 'no-store' }); return r.ok ? await r.json() : null; } catch (e) { return null; }
}
async function carregarSessao() { const j = await pegarJson('/api/sessao'); if (j) sessao = j; if (!painel.hidden && atual) desenhar(); }
async function carregarHistorico() { const j = await pegarJson('/api/acoes'); if (j && Array.isArray(j.acoes)) historico = j.acoes; if (!painel.hidden && atual) desenharFaixas(); }
function permitido(tipo, resolvidoTipo) {
  if (fonte !== 'real' || !sessao) return false;
  if (sessao.permissao === 'pc') return true;
  return sessao.permissao === 'conferir' && (tipo === 'conferido' || (tipo === 'desfazer' && resolvidoTipo === 'conferido'));
}
function nota(tipo) {   // por que não há botão (celular)
  if (fonte !== 'real' || !sessao || sessao.permissao === 'pc') return '';
  if (tipo === 'liberar') return 'liberar só pelo PC';
  return sessao.permissao === 'ver' ? 'ações só pelo PC' : '';
}
async function acao(tipo, pr, botao) {
  if (ocupado) return;
  ocupado = true;
  const rotulo = botao ? botao.textContent : '';
  if (botao) { botao.disabled = true; botao.textContent = 'salvando…'; }
  try {
    const cab = { 'Content-Type': 'application/json', 'X-Office-Acao': '1' };
    if (sessao && sessao.csrf) cab['X-Office-Csrf'] = sessao.csrf;
    const r = await fetch('/api/xp/' + tipo, { method: 'POST', headers: cab, body: JSON.stringify({ pr }) });
    let j = null; try { j = await r.json(); } catch (e) { /* corpo vazio */ }
    if (!r.ok || !j || !j.ok) throw new Error((j && j.erro) || 'HTTP ' + r.status);
    normalizar(j.placar);
    real = j.placar; decidir();   // aplica o placar novo sem recarregar a página
    toast('PR #' + pr + ' ' + TEXTO_ACAO[tipo], tipo === 'desfazer' ? 0 : pr);
    carregarHistorico();
  } catch (e) {
    if (botao) { botao.disabled = false; botao.textContent = rotulo; }
    toast('Não consegui salvar (PR #' + pr + '): ' + e.message, 0, true);
  } finally { ocupado = false; }
}
function botaoAcao(tipo, pr, resolvidoTipo) {   // null quando não pode agir (permissão, demonstração)
  if (!permitido(tipo, resolvidoTipo)) return null;
  const b = el('button', 'acao ' + tipo, ROTULO_ACAO[tipo]);
  b.title = 'ou pelo terminal (no PC): python xp.py ' + FLAG_ACAO[tipo] + ' ' + pr;
  b.addEventListener('click', (ev) => {
    ev.stopPropagation();
    if (tipo === 'liberar' && !confirm('Liberar os pontos do PR #' + pr + '? Confirme só depois de revisar a mudança.')) return;
    acao(tipo, pr, b);
  });
  return b;
}
function comAcao(li, b) { if (b) { const ac = el('div', 'acoes'); ac.append(b); li.append(ac); } }
function listaFaixa(titulo, classe, itens, tipo) {
  const sec = el('section', 'faixa ' + classe), ul = el('ul');
  sec.append(el('h4', null, titulo + ' · ' + itens.length));
  for (const x of itens) {
    const li = el('li');
    li.append(linkPr(x.pr), el('span', 'quem', ' · ' + nomeExibido(x.agente) + ' — '), el('span', 'por-que', x.motivo));
    comAcao(li, botaoAcao(tipo, x.pr));
    ul.append(li);
  }
  sec.append(ul);
  if (nota(tipo)) sec.append(el('div', 'nota', nota(tipo)));
  return sec;
}
function listaResolvidos(itens) {
  const det = el('details', 'faixa resolvida'), ul = el('ul');
  det.open = resolvidosAberto;
  det.addEventListener('toggle', () => { resolvidosAberto = det.open; });
  det.append(el('summary', null, '✔ Já resolvidos · ' + itens.length));
  for (const x of itens) {
    const li = el('li');
    li.append(linkPr(x.pr), el('span', 'quem', ' · ' + nomeExibido(x.agente) + ' — '),
      el('span', 'por-que', (x.tipo === 'liberado' ? 'liberado da auditoria' : 'conferido') + (x.titulo ? ': ' + x.titulo : '')));
    comAcao(li, botaoAcao('desfazer', x.pr, x.tipo));
    ul.append(li);
  }
  det.append(ul); return det;
}
function listaHistorico(itens) {
  const det = el('details', 'faixa historico'), ul = el('ul');
  det.open = historicoAberto;
  det.addEventListener('toggle', () => { historicoAberto = det.open; });
  det.append(el('summary', null, '🕘 Histórico de ações · ' + itens.length));
  for (const x of itens) {
    const li = el('li'), d = new Date(x.ts);
    const hora = isNaN(d) ? '' : d.toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
    li.append(el('span', 'hora', hora + ' · '), el('b', null, String(x.origem || '?')), el('span', null, ' ' + (ROTULO_HIST[x.acao] || x.acao) + ' '));
    if (Number.isInteger(x.pr)) li.append(linkPr(x.pr));
    if (x.detalhe) li.append(el('span', 'quem', ' (' + x.detalhe + ')'));
    const res = x.acao === 'conferido' && Number.isInteger(x.pr) && (atual.resolvidos || []).find((r) => r.pr === x.pr && r.tipo === 'conferido');
    if (res) comAcao(li, botaoAcao('desfazer', x.pr, 'conferido'));
    ul.append(li);
  }
  det.append(ul); return det;
}
function desenharFaixas() {
  faixasEl.textContent = '';
  const aud = [], conf = [], res = (atual.resolvidos || []).slice().sort((a, b) => b.pr - a.pr);
  for (const [nome, d] of Object.entries(atual.agentes)) {
    for (const x of d.auditoria) aud.push({ ...x, agente: nome });
    for (const x of d.conferir) conf.push({ ...x, agente: nome });
  }
  aud.sort((a, b) => b.pr - a.pr); conf.sort((a, b) => b.pr - a.pr);
  const hist = fonte === 'real' ? historico : [];
  faixasEl.hidden = !(aud.length || conf.length || res.length || hist.length);
  if (aud.length) faixasEl.append(listaFaixa('🔴 Auditoria (pontos zerados)', 'vermelha', aud, 'liberar'));
  if (conf.length) faixasEl.append(listaFaixa('🟡 Para conferir', 'amarela', conf, 'conferido'));
  if (res.length) faixasEl.append(listaResolvidos(res));
  if (hist.length) faixasEl.append(listaHistorico(hist));
}
function desenhar() {
  const o = office(); if (!atual) return;
  const cn = (n) => (o ? o.CORES_NIVEL : ['#9ca3af'])[Math.max(0, Math.min(4, n - 1))] || '#9ca3af';
  const t = atual.time;
  timeEl.textContent = '';
  const aud = Number(t.auditorias_abertas) || 0, conf = Number(t.conferir_abertos) || 0;
  timeEl.append(tile(String(t.xp_total ?? 0), 'XP total do time', '#f59e0b'), tile(pct(t.aprovacao_primeira), 'aprovado de primeira', '#22c55e'),
    tile(pct(t.retrabalho_14d), 'retrabalho em 14 dias', '#3b82f6'), tile(String(aud), 'auditorias abertas', '#22c55e', aud > 0),
    tile(String(conf), 'para conferir', '#22c55e', conf > 0 ? 'amarelo' : false));
  desenharFaixas();
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
    if (d.conferir.length) topo.append(el('span', 'conf', '● ' + d.conferir.length + ' para conferir'));
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
  painel.hidden = false; desenhar(); carregarHistorico();
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
  setInterval(() => { if (!document.hidden) buscar(); }, ATUALIZAR_MS);   // aba oculta: não consulta
  buscar(); vigiar(); carregarSessao(); carregarHistorico();
} else {   // "xp.ativo": false no config.json: sem botão, sem aba, sem rótulos de nível
  $('btnPlacar').hidden = true; $('abaXp').hidden = true;
}

window.__placar = {
  aplicar: (obj) => { injetado = true; return aplicar(obj, { fonte: 'injetado' }); },
  voltar: () => { injetado = false; ultimoModo = null; return buscar(); },
  agente: (nome) => (atual && atual.agentes[nome]) || null,
  get indisponivel() { return fonte === 'demo' && real === null; },
  get dados() { return atual; },
  get repo() { return (atual && atual.repo) || ''; },
  botao: botaoAcao, nota, get sessao() { return sessao; },
  buscar, evoluirDemo: () => { evoluirDemo(); decidir(); },
};
