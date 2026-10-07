// Alertas: avisa quando há algo esperando por você (PR pronto, conflito, auditoria, pergunta do Diretor...).
//  * com a página aberta: toast + Notification API (aba em segundo plano) + selo no botão, lendo GET /api/alertas;
//  * com a página fechada: Web Push (sw.js) — precisa de contexto seguro (localhost no PC; HTTPS do modo rede no celular);
//  * iPhone: só funciona com o escritório na Tela de Início (iOS 16.4+).
// Nada de comando, caminho ou código vai no push; este painel só liga/desliga e testa.
// Avisos de rotina (a.resumo) entram na lista e no selo sem toast: o servidor os junta num push de resumo (alertas.py).
const POLL_MS = 10000;
const CHAVES = { visto: 'office.alertas.visto', tipos: 'office.alertas.tipos', push: 'office.alertas.push', config: 'office.alertas.config' };
const $ = (id) => document.getElementById(id);
const botao = $('btnAlertas'), painel = $('alertas'), corpo = $('alertasCorpo'), info = $('alertasInfo'), conta = $('alertasConta');

const lerLS = (k) => { try { return localStorage.getItem(k); } catch (e) { return null; } };
const gravarLS = (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* sem armazenamento */ } };
function el(tag, cls, texto) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (texto != null) e.textContent = texto;
  return e;
}

const seguro = window.isSecureContext;
const temNotif = 'Notification' in window;
const temPush = seguro && 'serviceWorker' in navigator && 'PushManager' in window && temNotif;
const ios = /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
const standalone = !!(navigator.standalone || (window.matchMedia && matchMedia('(display-mode: standalone)').matches));

let ultimo = null;               // maior id já baixado (null = ainda não baixou)
let visto = Number(lerLS(CHAVES.visto)) || 0;   // maior id que você já viu (painel aberto)
let recentes = [], tipos = [], ativo = true, pushInfo = { disponivel: true, motivo: '' }, titulo = '';
let destacar = 0;
let hoje = null;                 // {imediatos, resumo}: avisos de hoje (orçamento de atenção)
let sessao = null, estadoPush = { inscrito: false, h: '' }, mensagem = '', mensagemErro = false;
// Bloco "Tipos de alerta e push" recolhido por padrão (a lista de alertas fica no topo); lembra a escolha neste navegador
let configAberta = lerLS(CHAVES.config) === '1';

// ---------------------------------------------------------------- rede
async function pegar(url) {
  const r = await fetch(url, { cache: 'no-store' });
  if (!r.ok) throw new Error('HTTP ' + r.status);
  return r.json();
}
async function postar(url, dados) {
  if (!sessao) { try { sessao = await pegar('/api/sessao'); } catch (e) { /* segue sem csrf (PC) */ } }
  const cab = { 'Content-Type': 'application/json', 'X-Office-Acao': '1' };
  if (sessao && sessao.csrf) cab['X-Office-Csrf'] = sessao.csrf;
  const r = await fetch(url, { method: 'POST', headers: cab, body: JSON.stringify(dados || {}) });
  let j = null; try { j = await r.json(); } catch (e) { /* sem corpo */ }
  if (!r.ok || !j || !j.ok) throw new Error((j && j.erro) || 'HTTP ' + r.status);
  return j;
}

// ---------------------------------------------------------------- preferências por tipo (neste navegador)
function prefs() {
  let salvo = {}; try { salvo = JSON.parse(lerLS(CHAVES.tipos) || '{}') || {}; } catch (e) { salvo = {}; }
  const p = {};
  for (const t of tipos) p[t.id] = typeof salvo[t.id] === 'boolean' ? salvo[t.id] : !!t.padrao;
  return p;
}
function definirPref(id, valor) {
  const p = prefs(); p[id] = valor; gravarLS(CHAVES.tipos, JSON.stringify(p));
  if (estadoPush.inscrito && estadoPush.h) postar('/api/push/prefs', { h: estadoPush.h, tipos: p }).catch(() => {});
}
const querTipo = (id) => id === 'teste' || prefs()[id] !== false;

// ---------------------------------------------------------------- abrir o painel certo
function abrirPainel(nome) {
  const mapa = { prs: ['prs', 'btnPrs'], placar: ['placar', 'btnPlacar'] }, m = mapa[nome];
  if (!m) return;
  const sec = $(m[0]), b = $(m[1]);
  if (sec && b && sec.hidden) b.click();
}
function painelDaUrl(u) { const m = /alerta=([a-z]+)/.exec(String(u || '')); return m ? m[1] : ''; }
function tratarHash() {
  const p = painelDaUrl(location.hash);
  if (!p) return;
  setTimeout(() => { abrirPainel(p); history.replaceState(null, '', location.pathname + location.search); }, 600);
}
window.addEventListener('hashchange', tratarHash);
if ('serviceWorker' in navigator) navigator.serviceWorker.addEventListener('message', (e) => { if (e.data && e.data.tipo === 'abrir') abrirPainel(e.data.painel); });

// ---------------------------------------------------------------- toast e notificação
const toasts = el('div'); toasts.id = 'alertasToasts'; document.body.append(toasts);
function toast(a) {
  const t = el('div', 'toast ' + a.tipo), txt = el('div', 't');
  txt.append(el('b', null, a.titulo), el('span', null, a.corpo));
  const x = el('button', null, '×'); x.title = 'Dispensar';
  const fechar = () => t.remove();
  x.addEventListener('click', (ev) => { ev.stopPropagation(); fechar(); });
  t.addEventListener('click', () => { abrirPainel(painelDaUrl(a.url)); fechar(); });
  t.append(txt, x);
  toasts.append(t);
  while (toasts.children.length > 4) toasts.firstChild.remove();
  setTimeout(fechar, 12000);
}
function notificar(a) {
  // com o push ligado neste navegador, o service worker já mostra a notificação: não duplica
  if (!temNotif || Notification.permission !== 'granted' || estadoPush.inscrito || !document.hidden) return;
  try {
    const n = new Notification((titulo ? titulo + ': ' : '') + a.titulo, { body: a.corpo, tag: a.tipo, icon: '/icone-192.png' });
    n.onclick = () => { window.focus(); abrirPainel(painelDaUrl(a.url)); n.close(); };
  } catch (e) { /* alguns navegadores móveis só aceitam via service worker */ }
}

// ---------------------------------------------------------------- selo no botão
function selo() {
  const n = recentes.filter((a) => a.id > visto && querTipo(a.tipo)).length;
  conta.hidden = !n; conta.textContent = n > 99 ? '99+' : n;
  conta.title = n + ' alerta(s) novo(s)';
}

// ---------------------------------------------------------------- polling
async function ler() {
  let j;
  try { j = await pegar('/api/alertas?desde=' + (ultimo === null ? 0 : ultimo)); } catch (e) { return; }
  if (!j || !j.ok) return;
  ativo = j.ativo !== false; tipos = j.tipos || tipos; hoje = j.hoje || hoje; pushInfo = j.push || pushInfo; titulo = j.titulo || titulo;
  const primeira = ultimo === null;
  if (!primeira && j.ultimo < ultimo) { ultimo = j.ultimo; recentes = []; }   // fila recomeçou
  for (const a of j.alertas || []) {
    if (recentes.some((r) => r.id === a.id)) continue;
    recentes.push(a);
    if (!primeira && querTipo(a.tipo) && !a.resumo) { toast(a); notificar(a); }
  }
  recentes = recentes.slice(-50);
  if (primeira && lerLS(CHAVES.visto) === null) { visto = j.ultimo; gravarLS(CHAVES.visto, String(visto)); }
  ultimo = Math.max(ultimo || 0, j.ultimo || 0);
  if (!painel.hidden) { visto = ultimo; gravarLS(CHAVES.visto, String(visto)); }   // painel aberto: já está vendo
  selo();
  if (!painel.hidden) desenhar();
}

// ---------------------------------------------------------------- push
const b64uParaBytes = (s) => Uint8Array.from(atob(s.replace(/-/g, '+').replace(/_/g, '/').padEnd(Math.ceil(s.length / 4) * 4, '=')), (c) => c.charCodeAt(0));
async function idInscricao(endpoint) {
  const h = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(endpoint));
  return [...new Uint8Array(h)].slice(0, 6).map((b) => b.toString(16).padStart(2, '0')).join('');
}
async function inscricaoLocal() {
  if (!temPush) return null;
  const reg = await navigator.serviceWorker.getRegistration('/');
  return reg ? reg.pushManager.getSubscription() : null;
}
async function atualizarEstadoPush() {
  try {
    const sub = await inscricaoLocal();
    if (!sub) { estadoPush = { inscrito: false, h: '' }; return; }
    const h = await idInscricao(sub.endpoint), j = await pegar('/api/push/estado?h=' + h);
    estadoPush = { inscrito: !!j.inscrito, h };
    if (!j.inscrito && lerLS(CHAVES.push) === '1' && Notification.permission === 'granted') {   // o servidor perdeu a inscrição: refaz
      await postar('/api/push/inscrever', { subscription: sub.toJSON(), tipos: prefs() });
      estadoPush = { inscrito: true, h };
    }
  } catch (e) { estadoPush = { inscrito: false, h: '' }; }
}
async function ativarAlertas() {
  if (!temNotif) throw new Error('Este navegador não tem notificações.');
  let perm = Notification.permission;
  if (perm === 'default') perm = await Notification.requestPermission();
  if (perm !== 'granted') throw new Error('Permissão negada. Libere as notificações deste site nas configurações do navegador.');
  if (!temPush) return 'Notificações ligadas com o escritório aberto. Web Push (com o escritório fechado) precisa de HTTPS ou localhost' + (ios ? ' e do escritório na Tela de Início.' : '.');
  const ch = await pegar('/api/push/chave');
  if (!ch.disponivel) return 'Notificações ligadas com o escritório aberto. Web Push indisponível: ' + ch.motivo;
  const reg = await navigator.serviceWorker.ready, chave = b64uParaBytes(ch.chave);
  let sub = await reg.pushManager.getSubscription();
  if (sub && sub.options && sub.options.applicationServerKey) {
    const a = new Uint8Array(sub.options.applicationServerKey);
    if (a.length !== chave.length || a.some((v, i) => v !== chave[i])) { await sub.unsubscribe(); sub = null; }   // chave do servidor mudou
  }
  if (!sub) sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: chave });
  await postar('/api/push/inscrever', { subscription: sub.toJSON(), tipos: prefs() });
  gravarLS(CHAVES.push, '1');
  await atualizarEstadoPush();
  return 'Pronto: os alertas chegam neste aparelho mesmo com o escritório fechado.';
}
async function desligarPush() {
  const sub = await inscricaoLocal();
  if (sub) { const ep = sub.endpoint; await sub.unsubscribe(); try { await postar('/api/push/sair', { endpoint: ep }); } catch (e) { /* o servidor limpa sozinho */ } }
  gravarLS(CHAVES.push, '0');
  await atualizarEstadoPush();
  return 'Push desligado neste navegador.';
}
async function testar() {
  const j = await postar('/api/push/teste', {});
  await ler();
  const p = j.push || {};
  if (p.enviados) return 'Alerta de teste enviado: ' + p.enviados + ' push; a notificação deve chegar em instantes.';
  if (p.limitados) return 'Alerta de teste na fila, mas o limite de envios por hora foi atingido.';
  if (p.falhas) return 'Alerta de teste na fila, mas o serviço de push recusou o envio (' + p.falhas + ' falha(s)).';
  return 'Alerta de teste na fila (toast na página). Push: este navegador ainda não está inscrito.';
}

// ---------------------------------------------------------------- painel
const horaDe = (ts) => new Date(ts * 1000).toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
async function executar(fn) {
  mensagem = ''; mensagemErro = false;
  try { mensagem = await fn(); } catch (e) { mensagem = e.message || String(e); mensagemErro = true; }
  await atualizarEstadoPush(); desenhar();
}
function desenhar() {
  const topo = [], partes = [];
  const perm = temNotif ? Notification.permission : 'indisponivel';
  if (!ativo) topo.push(el('p', 'aviso', 'Os alertas estão desligados no servidor (alertas.ativo no config ou dados/alertas_config.json).'));
  if (ios && !standalone) {   // no topo: sem isso o iPhone não recebe nada, e o bloco de configuração vem recolhido
    topo.push(el('p', 'aviso', 'No iPhone/iPad as notificações só funcionam com o escritório na Tela de Início: toque em Compartilhar → "Adicionar à Tela de Início", '
      + 'abra o escritório por esse ícone e volte aqui para ativar (iOS 16.4 ou mais novo).'));
  }
  if (!seguro) partes.push(el('p', 'aviso', 'Notificações e push exigem conexão segura. No celular, use o endereço https do modo rede (com o certificado instalado); no PC, localhost serve.'));
  else if (perm === 'denied') partes.push(el('p', 'aviso', 'As notificações deste site estão bloqueadas no navegador. Libere nas configurações do site e volte aqui.'));
  if (pushInfo && !pushInfo.disponivel) partes.push(el('p', 'aviso', 'Web Push indisponível no servidor: ' + pushInfo.motivo));
  const estado = estadoPush.inscrito ? 'Push LIGADO neste aparelho (chega com o escritório fechado).'
    : perm === 'granted' ? 'Notificações ligadas com o escritório aberto; push desligado.' : 'Alertas ainda não ativados neste aparelho.';
  partes.push(el('p', estadoPush.inscrito ? 'bom' : 'msg', estado));
  if (mensagem) partes.push(el('p', mensagemErro ? 'aviso' : 'bom', mensagem));

  const acoes = el('div', 'acoes');
  if (temNotif && ativo && perm !== 'denied' && !(perm === 'granted' && (estadoPush.inscrito || !temPush))) {
    const b = el('button', null, '🔔 Ativar alertas neste aparelho'); b.id = 'alertasAtivar';
    b.addEventListener('click', () => executar(ativarAlertas));
    acoes.append(b);
  }
  if (ativo) {
    const t = el('button', null, 'Enviar alerta de teste'); t.id = 'alertasTeste';
    t.addEventListener('click', () => executar(testar));
    acoes.append(t);
  }
  if (estadoPush.inscrito) {
    const d = el('button', null, 'Desligar push'); d.id = 'alertasDesligar';
    d.addEventListener('click', () => executar(desligarPush));
    acoes.append(d);
  }
  partes.push(acoes);

  if (tipos.length) {
    const bloco = el('div', 'bloco'), p = prefs();
    bloco.append(el('h4', null, 'Quais alertas receber'));
    for (const t of tipos) {
      const l = el('label', 'tipo'), c = document.createElement('input');
      c.type = 'checkbox'; c.checked = p[t.id]; c.dataset.tipo = t.id;
      c.addEventListener('change', () => definirPref(t.id, c.checked));
      l.append(c, el('span', null, t.rotulo)); bloco.append(l);
    }
    bloco.append(el('p', 'msg', 'Vale para este navegador (toast, notificação e push).'));
    partes.push(bloco);
  }

  // configuração (push, teste e tipos) num <details> recolhido, depois da lista
  const cfg = el('details', 'config'), resumo = el('summary');
  cfg.open = configAberta;   // os botões ficam aqui dentro: o resultado deles aparece com o bloco aberto
  cfg.addEventListener('toggle', () => { configAberta = cfg.open; gravarLS(CHAVES.config, cfg.open ? '1' : '0'); });
  const ligados = tipos.length ? tipos.filter((t) => querTipo(t.id)).length : 0;
  resumo.append(el('span', null, '⚙️ Tipos de alerta e push'),
    el('span', 'estado', (estadoPush.inscrito ? 'push ligado' : perm === 'granted' ? 'notificações ligadas' : 'não ativado')
      + (tipos.length ? ` · ${ligados} de ${tipos.length} tipos` : '')));
  cfg.append(resumo, ...partes);

  const lista = el('div', 'bloco recentes'), ol = el('ol');
  lista.append(el('h4', null, 'Alertas recentes'));
  const itens = recentes.slice().reverse().slice(0, 20);
  if (!itens.length) ol.append(el('li', 'msg', 'Nada por enquanto. Quando algo esperar por você, aparece aqui.'));
  for (const a of itens) {
    const li = el('li', 'alerta' + (a.id > destacar ? ' novo' : ''));
    li.append(el('span', 'hora', horaDe(a.ts) + (querTipo(a.tipo) ? '' : ' · tipo desligado') + (a.resumo ? ' · no resumo' : '')), el('b', null, a.titulo), el('span', null, a.corpo));
    if (a.detalhe) li.append(el('span', 'det', a.detalhe));
    const destino = painelDaUrl(a.url);
    li.addEventListener('click', () => abrirPainel(destino));
    if (destino === 'prs' || destino === 'placar') {   // abre o painel do alerta: acessível pelo teclado também
      li.tabIndex = 0; li.setAttribute('role', 'button');
      li.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); abrirPainel(destino); } });
    }
    ol.append(li);
  }
  lista.append(ol);
  corpo.replaceChildren(...topo, lista, cfg);
  info.textContent = ultimo === null ? 'consultando…' : (recentes.length + ' alerta(s) guardado(s)'
    + (hoje ? ' · hoje: ' + hoje.imediatos + ' na hora, ' + hoje.resumo + ' no resumo' : ''));
}
function abrir() {
  painel.hidden = false;
  destacar = visto;   // os alertas que você ainda não tinha visto ficam marcados enquanto o painel estiver aberto
  visto = ultimo || visto; gravarLS(CHAVES.visto, String(visto));
  desenhar(); selo();
  atualizarEstadoPush().then(() => { if (!painel.hidden) desenhar(); });
}
function fechar() { painel.hidden = true; }

// ---------------------------------------------------------------- início
if (botao && painel && location.protocol !== 'file:') {
  botao.hidden = false;
  botao.addEventListener('click', () => (painel.hidden ? abrir() : fechar()));
  $('alertasFechar').addEventListener('click', fechar);
  window.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !painel.hidden) fechar(); });
  if (seguro && 'serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(() => { /* sem service worker: só toast */ });
  ler().then(() => atualizarEstadoPush());
  setInterval(ler, POLL_MS);   // sem pausar com a aba oculta: é para isso que serve (o navegador espaça o timer sozinho)
  tratarHash();
  window.__alertas = { ler, abrirPainel, get recentes() { return recentes; }, get estadoPush() { return estadoPush; } };
}
