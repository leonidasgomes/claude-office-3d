// Claude Office 3D — quadro Kanban do GitHub Projects (lido pelo servidor em /kanban).
// Módulo separado do escritorio.js: abre por cima da cena no botão "Kanban".
// Quadro, campo do "time" e mapa time → agente vêm do config.json (chave "github").
// Com o Kanban ligado, também lê o /kanban em segundo plano e avisa a cena com o evento "kanban" (quadro na parede e aba
// Cartões da ficha); o servidor responde do cache, então isso não gasta a cota do GitHub.
import { CONFIG, agenteConfig, temServidor } from './config.js';
import { seletorProjetos } from './kanban_projetos.mjs';

const MAX_CONCLUIDO = 15;           // a coluna de concluídos cresce sem parar: mostra só os mais recentes
const ATUALIZAR_MS = 60000;
const CONCLUIDAS = ['feito', 'done', 'concluído', 'concluido', 'pronto'];
const CORES_PRIORIDADE = { P0: '#ef4444', P1: '#f59e0b', P2: '#64748b', high: '#ef4444', medium: '#f59e0b', low: '#64748b' };
const GH = CONFIG.github;

const $ = (id) => document.getElementById(id);
const painel = $('kanban'), colunasEl = $('kanbanColunas'), filtrosEl = $('kanbanFiltros'), infoEl = $('kanbanInfo');
let dados = null, filtro = '', timer = null;
let requisicao = 0;
const seletor = seletorProjetos(infoEl, () => {
  filtro = '';
  dados = {cartoes: [], projeto: '', atualizado: '', erro: 'Carregando o projeto selecionado…'};
  window.dispatchEvent(new CustomEvent('kanban', {detail: dados}));
  desenhar(); carregar();
});
$('kanbanTitulo').textContent = 'Kanban — ' + CONFIG.titulo;

function el(tag, cls, texto) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (texto != null) e.textContent = texto;
  return e;
}
// valor do campo "time" do cartão → agente do config (pelo mapa github.times ou pelo próprio nome), ou null
function agenteDoTime(t) {
  if (!t) return null;
  const mapa = GH.times || {};
  const chaveMapa = Object.keys(mapa).find((k) => k.toLowerCase() === String(t).toLowerCase());
  return agenteConfig(chaveMapa ? mapa[chaveMapa] : t);
}
// valor do campo "time" do cartão → agente do escritório (mesma cor da mesa)
function infoTime(t) {
  if (!t) return { agente: 'Sem time', cor: '#475569' };
  const ag = agenteDoTime(t);
  return ag ? { agente: ag.titulo, cor: ag.cor } : { agente: t, cor: '#64748b' };
}
const ehConcluida = (s) => dados?.fonte === 'gestao' ? s === dados.concluido : CONCLUIDAS.includes(String(s || '').toLowerCase());
// ordem das colunas: github.colunas, ou a ordem em que aparecem com as concluídas no fim
function colunas(cartoes) {
  if (dados?.fonte === 'gestao') return dados.colunas || [];
  if (GH.colunas && GH.colunas.length) return GH.colunas;
  return [...new Set(cartoes.map((c) => c.status))].sort((a, b) => ehConcluida(a) - ehConcluida(b));
}

function desenharFiltros() {
  filtrosEl.textContent = '';
  const contagem = {};
  for (const c of dados.cartoes) if (!ehConcluida(c.status)) contagem[c.time || ''] = (contagem[c.time || ''] || 0) + 1;
  const botao = (valor, rotulo, cor) => {
    const b = el('button', 'filtro' + (filtro === valor ? ' ativo' : ''), rotulo);
    if (cor) b.style.borderColor = cor;
    b.addEventListener('click', () => { filtro = valor; desenhar(); });
    filtrosEl.append(b);
  };
  botao('', 'Todos');
  Object.keys(contagem).sort((a, b) => contagem[b] - contagem[a])
    .forEach((t) => { const i = infoTime(t); botao(t || '(sem time)', `${i.agente} · ${contagem[t]}`, i.cor); });
}

function cartaoEl(c) {
  const i = infoTime(c.time);
  const a = el('a', 'cartao');
  a.href = c.url || '#'; a.target = '_blank'; a.rel = 'noopener';
  a.style.borderLeftColor = i.cor;
  const topo = el('div', 'topo');
  topo.append(el('span', 'num', c.numero ? '#' + c.numero : (c.tipo === 'DraftIssue' ? 'rascunho' : '')));
  if (c.prioridade) { const p = el('span', 'prio', c.prioridade); p.style.background = CORES_PRIORIDADE[c.prioridade] || CORES_PRIORIDADE[c.prioridade.toLowerCase()] || '#475569'; topo.append(p); }
  a.append(topo, el('div', 'titulo', c.titulo));
  const rodape = el('div', 'rodape');
  const quem = el('span', 'quem', i.agente); quem.style.color = i.cor;
  rodape.append(quem);
  a.append(rodape);
  return a;
}

function aviso(texto) {
  filtrosEl.textContent = ''; colunasEl.textContent = '';
  colunasEl.append(el('div', 'vazio aviso', texto));
}

function desenhar() {
  if (!dados) return;
  $('kanbanLink').hidden = !dados.projeto;
  if (dados.projeto) $('kanbanLink').href = dados.projeto;
  if (dados.configurado === false || (!dados.cartoes.length && dados.erro)) {
    aviso('⚠️ ' + dados.erro + (dados.limite ? ' — ⏳ ' + dados.limite : ''));
    infoEl.textContent = '';
    return;
  }
  desenharFiltros();
  colunasEl.textContent = '';
  const visiveis = dados.cartoes.filter((c) => !filtro || (c.time || '(sem time)') === filtro);
  const ordem = colunas(dados.cartoes);
  const extras = [...new Set(visiveis.map((c) => c.status))].filter((s) => !ordem.includes(s));
  const todas = [...ordem, ...extras];
  colunasEl.style.gridTemplateColumns = `repeat(${Math.max(1, todas.length)}, minmax(200px, 1fr))`;
  for (const status of todas) {
    let lista = visiveis.filter((c) => c.status === status);
    const total = lista.length;
    if (ehConcluida(status)) lista = lista.slice().sort((x, y) => (y.numero || 0) - (x.numero || 0)).slice(0, MAX_CONCLUIDO);
    const col = el('section', 'coluna');
    col.append(el('h4', null, `${status} · ${total}`));
    const corpo = el('div', 'cartoes');
    if (!lista.length) corpo.append(el('div', 'vazio', '—'));
    lista.forEach((c) => corpo.append(cartaoEl(c)));
    if (ehConcluida(status) && total > lista.length) corpo.append(el('div', 'vazio', `+ ${total - lista.length} mais antigos`));
    col.append(corpo);
    colunasEl.append(col);
  }
  infoEl.textContent = dados.erro
    ? `⚠️ não consegui atualizar (${dados.erro}) — mostrando o último quadro${dados.atualizado ? ' de ' + dados.atualizado : ''}`
    : `atualizado às ${dados.atualizado} · ${dados.cartoes.length} cartões`;
  if (dados.limite) infoEl.textContent += ` · ⏳ ${dados.limite}`;   // limite do GitHub estourado: o servidor diz até quando
  if (dados.cota) infoEl.textContent += ` · ${dados.cota_baixa ? '⚠️ ' : ''}${dados.cota}`;   // vigia da cota (ex.: GraphQL: 3.200/5.000 (volta 11:25))
}

async function carregar() {
  const atual = ++requisicao;
  if (!temServidor) {
    dados = { configurado: false, cartoes: [], erro: 'sem servidor: abra o escritório pelo abrir_escritorio (.bat ou .sh) para ver o Kanban.' };
    return desenhar();
  }
  try {
    const r = await fetch(seletor.url(), { cache: 'no-store' });
    if (!r.ok) throw new Error('HTTP');
    const recebido = await r.json();
    if (atual !== requisicao) return;
    dados = recebido; seletor.receber(dados);
  } catch (e) {
    if (atual !== requisicao) return;
    dados = dados || { cartoes: [], atualizado: '', projeto: '' };
    dados.erro = 'servidor do escritório fora do ar (abra pelo abrir_escritorio)';
  }
  window.dispatchEvent(new CustomEvent('kanban', { detail: dados }));
  if (!painel.hidden) desenhar();
}

function abrir() {
  painel.hidden = false;
  if (!dados) infoEl.textContent = 'carregando o quadro do GitHub…';
  else desenhar();
  carregar();
}
function fechar() { painel.hidden = true; }
if (temServidor && GH.kanban) {
  carregar();
  timer = setInterval(() => { if (!document.hidden) carregar(); }, ATUALIZAR_MS);
}

$('btnKanban').addEventListener('click', () => (painel.hidden ? abrir() : fechar()));
$('kanbanFechar').addEventListener('click', fechar);
window.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !painel.hidden) fechar(); });
window.__kanban = { abrir, fechar, carregar, dados: () => dados, infoTime, agenteDoTime, colunas, ehConcluida, CORES_PRIORIDADE };
