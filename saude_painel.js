// Claude Office 3D — painel "🩺 Saúde": trabalho duplicado, agentes andando em círculos, PRs parados, cartões rascunho em coluna
// de trabalho (com o comando que converte em issue), comandos repetidos (dica de script) e o risco dos PRs abertos
// (GET /saude, calculado sem tokens pelo saude.py, e GET /prs para os links e o risco). Ações: abrir no GitHub, ignorar /
// reativar (POST /api/saude/ignorar: some dos alertas e do vigia do líder) e avisar o líder (POST /api/saude/avisar: o vigia
// entrega como "[vigia saude] ... pedido do desenvolvedor: ..."). Ignorar e avisar são só do PC (rede.PERMISSAO_ROTA).
// Seção "Boas práticas do projeto" (GET /api/praticas, boas_praticas.py): o que falta em cada projeto e como corrigir.
// Consulta só com o painel aberto e a aba visível (a cada 60 s). Todo texto vindo de fora entra por textContent.

import { dica } from './dica.js';
import { CONFIG, temServidor } from './config.js';

const ATUALIZAR_MS = 60000;
const $ = (id) => document.getElementById(id);
const botao = $('btnSaude'), painel = $('saude'), corpo = $('saudeCorpo'), info = $('saudeInfo');
let dados = null, prs = null, praticas = null, sessao = null, erro = '', carregando = false, timer = null;
const abertos = new Set();   // <details> abertos (sobrevive ao redesenho a cada 60 s)
let formAberto = '';         // "acao|chave" do formulário inline aberto (ignorar / avisar)
let rascunho = '';           // texto digitado no formulário aberto (sobrevive ao redesenho)
let msgAcao = '';            // resultado da última ação
let atrasado = false;        // chegaram dados novos com o formulário aberto: redesenha ao fechá-lo (fecharForm)

function el(tag, cls, texto) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (texto != null) e.textContent = texto;
  return e;
}
function link(texto, href, cls = 'botao') {
  const a = el('a', cls, texto);
  a.href = href; a.target = '_blank'; a.rel = 'noopener';
  return a;
}
const hora = (ts) => new Date(ts * 1000).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
function ha(ts) {
  const min = Math.max(0, Math.round((Date.now() / 1000 - ts) / 60));
  return min < 60 ? `há ${min} min` : `há ${Math.floor(min / 60)} h ${min % 60} min`;
}
const ehPc = () => !!sessao && sessao.permissao === 'pc';
const repo = () => (prs && typeof prs.repo === 'string' && /^[\w.-]+\/[\w.-]+$/.test(prs.repo) ? prs.repo : '');
const prPorNumero = (n) => ((prs && prs.prs) || []).find((p) => p.numero === n);
const urlBranch = (b) => (repo() ? `https://github.com/${repo()}/tree/${b.split('/').map(encodeURIComponent).join('/')}` : '');
function urlPr(n) {
  const p = prPorNumero(n);
  if (p && /^https:\/\/github\.com\//.test(p.url || '')) return p.url;
  return repo() ? `https://github.com/${repo()}/pull/${n}` : '';
}

// triagem barata (saude_triagem.py): veredicto por chave; falso positivo não desfeito = silenciado
const veredictos = () => (dados && dados.triagem && typeof dados.triagem.veredictos === 'object' && dados.triagem.veredictos) || {};
// a mesma regra de saude.silencia: falso positivo de gravidade "alta" não silencia (vira alerta normal)
const silenciado = (k) => { const v = veredictos()[k]; return !!v && v.problema === false && !v.desfeito && v.gravidade !== 'alta'; };
const ROT_ACAO = { juntar: 'juntar', fechar_um: 'fechar um', parar_e_repensar: 'parar e repensar', retomar_pr: 'retomar o PR', nenhuma: 'nenhuma' };

// chaves estáveis (as mesmas de saude.chave_dup / chave_circulo / chave_parado / chave_rascunho / chave_repetido)
const chaveDup = (d) => 'dup:' + [...(d.branches || [])].map(String).sort().join(',');
const chaveCirculo = (c) => `circulo:${c.agente}:${c.arquivo}`;
const chaveParado = (x) => `parado:${x.numero}`;
const chaveRascunho = (r) => `rascunho:${r.item_id}`;
const chaveRepetido = (r) => `repetido:${r.agente}:${r.assinatura}`;
const MODELO_SCRIPTS = 'modelos/praticas/scripts-do-projeto.md';

// copia texto (clipboard quando disponível; senão seleciona num campo temporário, como no celular.js)
async function copiar(texto) {
  try { await navigator.clipboard.writeText(texto); return true; } catch (e) { /* sem permissão: cai no plano B */ }
  const t = document.createElement('textarea'); t.value = texto; t.style.position = 'fixed'; t.style.opacity = '0';
  document.body.append(t); t.select();
  let ok = false; try { ok = document.execCommand('copy'); } catch (e) { /* sem cópia */ }
  t.remove(); return ok;
}
function botaoCopiar(texto) {
  const b = el('button', 'botao', '📋 Copiar o comando'); b.type = 'button';
  b.addEventListener('click', async () => { b.textContent = (await copiar(texto)) ? '✔ Copiado' : '⚠️ Não copiou: selecione o texto'; });
  return b;
}

// ---------------------------------------------------------------- rede
async function pegarSessao() {
  if (!sessao) { try { sessao = await (await fetch('/api/sessao', { cache: 'no-store' })).json(); } catch (e) { sessao = null; } }
  return sessao;
}
async function postar(rota, corpoJson) {
  const s = await pegarSessao();
  const cab = { 'Content-Type': 'application/json', 'X-Office-Acao': '1' };
  if (s && s.csrf) cab['X-Office-Csrf'] = s.csrf;
  const r = await fetch(rota, { method: 'POST', headers: cab, body: JSON.stringify(corpoJson) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok || !j.ok) throw new Error(j.erro || 'falhou (' + r.status + ')');
  return j;
}
async function carregar() {
  if (carregando) return;
  carregando = true;
  if (!dados) desenhar();
  try {
    await pegarSessao();
    const [rs, rp, rb] = await Promise.all([fetch('/saude', { cache: 'no-store' }), CONFIG.github.prs ? fetch('/prs', { cache: 'no-store' }).catch(() => null) : null,
      fetch('/api/praticas', { cache: 'no-store' }).catch(() => null)]);
    const j = await rs.json();
    if (!rs.ok || !j || typeof j !== 'object') throw new Error('resposta inválida (' + rs.status + ')');
    dados = j; erro = j.erro ? String(j.erro) : '';
    if (rp && rp.ok) { try { prs = await rp.json(); } catch (e) { /* mantém o último */ } }
    if (rb && rb.ok) { try { const jb = await rb.json(); if (jb && Array.isArray(jb.projetos)) praticas = jb; } catch (e) { /* mantém o último */ } }
  } catch (e) {
    erro = 'servidor do escritório fora do ar ou sem resposta (' + e.message + ')';
  } finally {
    carregando = false;
  }
  // com o formulário aberto não redesenha embaixo de quem digita: `dados` já é o mais novo e fecharForm() redesenha com ele
  if (formAberto && dados && !erro) { atrasado = true; return; }
  desenhar();
}

// ---------------------------------------------------------------- ações
async function ignorar(chave, valor, motivo, b) {
  b.disabled = true;
  try {
    const j = await postar('/api/saude/ignorar', { chave, ignorar: valor, motivo: motivo || '' });
    if (dados) dados.ignorados = j.ignorados || {};
    formAberto = ''; rascunho = ''; atrasado = false;
    msgAcao = valor ? '🙈 Ignorado: não alerta mais nem acorda o líder (fica em "Ignorados").' : '↩️ Reativado: volta a alertar.';
  } catch (e) {
    msgAcao = '⚠️ Não deu: ' + e.message;
  }
  desenhar();
}
async function desfazerFP(chave, b) {
  b.disabled = true;
  try {
    const j = await postar('/api/saude/triagem', { chave, acao: 'desfazer' });
    if (dados && dados.triagem) dados.triagem.veredictos = j.triagem || {};
    msgAcao = '↩️ Falso positivo desfeito: o item volta a alertar e a acordar o líder.';
  } catch (e) {
    msgAcao = '⚠️ Não deu: ' + e.message;
  }
  desenhar();
}
async function avisar(chave, texto, b) {
  b.disabled = true;
  try {
    const j = await postar('/api/saude/avisar', { chave, texto: texto || '' });
    if (dados) dados.pedidos = [...(dados.pedidos || []), j.pedido].slice(-20);
    formAberto = ''; rascunho = ''; atrasado = false;
    msgAcao = '📨 Pedido gravado: o vigia do líder entrega na próxima rodada (vigia.intervalo_min, padrão 15 min).';
  } catch (e) {
    msgAcao = '⚠️ Não deu: ' + e.message;
  }
  desenhar();
}

function fecharForm() { formAberto = ''; rascunho = ''; atrasado = false; desenhar(); }

// quem fez (origem + User-Agent resumido): ignorado/pedido forjado por um processo local salta aos olhos
function resumoUA(ua) {
  const t = String(ua || '');
  if (!t) return 'sem User-Agent';
  const m = /Edg\/(\d+)/.exec(t) || /Firefox\/(\d+)/.exec(t) || /Chrome\/(\d+)/.exec(t) || /Version\/(\d+).*Safari/.exec(t);
  if (m) return (/Edg\//.test(t) ? 'Edge ' : /Firefox\//.test(t) ? 'Firefox ' : /Chrome\//.test(t) ? 'Chrome ' : 'Safari ') + m[1];
  return t.slice(0, 40);
}
function quemFez(x) {
  const ua = String(x.ua || ''), suspeito = !/^Mozilla\/5\.0 /.test(ua);
  const e = el('span', 'saude-quem' + (suspeito ? ' suspeito' : ''), `por ${x.origem || '?'} · ${resumoUA(ua)}`
    + (suspeito ? ' ⚠️ não parece um navegador: confira se foi você' : ''));
  if (ua) e.title = ua;
  return e;
}

// formulário inline (motivo de ignorar / recado ao líder): nada de prompt()
function formulario(acao, chave) {
  const f = el('form', 'saude-form');
  const ehIgn = acao === 'ignorar';
  const rot = el('label', null, ehIgn ? 'Motivo (opcional)' : 'Recado ao líder (opcional)');
  const inp = el('input');
  inp.type = 'text'; inp.maxLength = ehIgn ? 300 : 400; inp.value = rascunho;
  inp.placeholder = ehIgn ? 'ex.: parte 1 e parte 2, não é duplicado' : 'ex.: feche a v2, a v1 já está revisada';
  inp.addEventListener('input', () => { rascunho = inp.value; });
  const id = 'saudeCampo' + Math.random().toString(36).slice(2, 8);
  inp.id = id; rot.htmlFor = id;
  const ok = el('button', 'botao principal', ehIgn ? 'Ignorar' : 'Gravar pedido');
  ok.type = 'submit';
  const cancelar = el('button', 'botao', 'Cancelar');
  cancelar.type = 'button';
  cancelar.addEventListener('click', fecharForm);
  f.addEventListener('submit', (e) => {
    e.preventDefault();
    if (ehIgn) ignorar(chave, true, inp.value.trim(), ok); else avisar(chave, inp.value.trim(), ok);
  });
  const linha = el('div', 'saude-form-botoes');
  linha.append(ok, cancelar);
  f.append(rot, inp, linha);
  setTimeout(() => { if (inp.isConnected && document.activeElement !== inp) inp.focus(); }, 0);
  return f;
}

function botaoForm(acao, chave, rotulo, titulo) {
  const b = el('button', 'botao', rotulo);
  b.type = 'button'; b.title = titulo;
  b.setAttribute('aria-expanded', String(formAberto === acao + '|' + chave));
  b.addEventListener('click', () => {
    const alvo = acao + '|' + chave;
    formAberto = formAberto === alvo ? '' : alvo; rascunho = ''; msgAcao = '';
    desenhar();
  });
  return b;
}

// ações de um item: links do GitHub + (só no PC) avisar e ignorar; e a situação do último pedido ao líder
function acoes(chave, links) {
  const caixa = el('div', 'saude-acoes-caixa');
  const linha = el('div', 'saude-acoes');
  for (const [texto, href] of links) if (href) linha.append(link(texto, href));
  if (ehPc()) {
    linha.append(botaoForm('avisar', chave, '📨 Avisar o líder', 'Grava um pedido que o vigia do líder entrega (não interrompe a sessão)'),
      botaoForm('ignorar', chave, '🙈 Ignorar', 'Não alerta mais nem acorda o líder por este item (dá para reativar)'));
  }
  if (linha.childElementCount) caixa.append(linha);
  const t = linhaTriagem(chave);
  if (t) caixa.append(t);
  const ped = [...((dados && dados.pedidos) || [])].reverse().find((p) => p.chave === chave && p.tipo_pedido !== 'triagem');
  if (ped) caixa.append(linhaPedido(ped));
  if (formAberto.endsWith('|' + chave)) caixa.append(formulario(formAberto.split('|')[0], chave));
  return caixa;
}

function situacaoPedido(p) {
  return p.cancelado ? 'cancelado: resolvido antes da entrega' : p.entregue ? 'entregue pelo vigia' : 'aguardando o vigia';
}
function linhaPedido(ped) {
  const d = el('div', 'saude-pedido' + (ped.cancelado ? ' cancelado' : ''), `📨 pedido ao líder às ${hora(ped.ts)} — ${situacaoPedido(ped)}`
    + (ped.recado ? ` · recado: "${ped.recado}"` : '') + ' ');
  d.append(quemFez(ped));
  return d;
}
// veredicto da triagem barata do item (🤖) e se o líder já foi avisado automaticamente
function linhaTriagem(chave) {
  const v = veredictos()[chave];
  if (!v) return null;
  const d = el('div', 'saude-triagem' + (v.erro ? ' erro' : v.problema ? ' problema' : ' falso'));
  if (v.pendente) {
    d.textContent = '🤖 triagem em andamento — o alerta espera o veredicto (até 15 min)';
    return d;
  }
  if (v.erro) {
    d.textContent = '🤖 triagem indisponível (' + v.erro + ') — alerta normal, sem aviso automático';
    return d;
  }
  if (v.problema) {
    const aviso = [...((dados && dados.pedidos) || [])].reverse().find((p) => p.chave === chave && p.tipo_pedido === 'triagem');
    d.textContent = `🤖 triagem: problema real (gravidade ${v.gravidade}, ação sugerida: ${ROT_ACAO[v.acao] || v.acao}) — ${v.motivo}`
      + (aviso ? ` · líder avisado automaticamente às ${hora(aviso.ts)} (${situacaoPedido(aviso)})` : '')
      + (v.aviso_suprimido ? ' · sem novo aviso: a mesma chave já avisou o líder nas últimas 24 h' : '')
      + (v.erro_aviso ? ' · o aviso ao líder não foi registrado (' + v.erro_aviso + ')' : '');
    return d;
  }
  d.textContent = `🤖 triagem: falso positivo — ${v.motivo}` + (v.desfeito ? ` · desfeito por ${v.desfeito_por || '?'} às ${hora(v.desfeito)}` : '')
    + (v.gravidade === 'alta' && !v.desfeito ? ' · gravidade alta: não silencia (alerta normal)' : '');
  return d;
}

// ---------------------------------------------------------------- itens
function itemDup(d, forte) {
  const li = el('li', 'saude-item ' + (forte ? 'forte' : 'fraco'));
  li.append(el('div', 'saude-titulo', d.motivo ? d.motivo[0].toUpperCase() + d.motivo.slice(1) : 'Trabalho duplicado'));
  const meta = el('div', 'saude-meta');
  for (const b of d.branches || []) {
    const u = urlBranch(b);
    meta.append(u ? link(b, u, 'saude-branch') : el('span', 'saude-branch', b));
  }
  for (const n of d.prs || []) { const u = urlPr(n); meta.append(u ? link('PR #' + n, u, 'saude-pr') : el('span', 'saude-pr', 'PR #' + n)); }
  li.append(meta);
  const prim = (d.prs || [])[0];
  const links = prim ? [['Abrir PR #' + prim + ' ↗', urlPr(prim)]] : [['Abrir branch ↗', urlBranch((d.branches || [])[0] || '')]];
  li.append(acoes(chaveDup(d), links));
  return li;
}
function itemCirculo(c) {
  const li = el('li', 'saude-item circulo');
  li.append(el('div', 'saude-titulo', `${c.agente} edita ${c.arquivo} e roda o mesmo comando de novo e de novo`));
  const meta = el('div', 'saude-meta');
  meta.append(el('span', null, `${c.edicoes} edições · ${c.comandos} vezes o mesmo comando`));
  if (c.desde) meta.append(el('span', null, `desde ${hora(c.desde)} (${ha(c.desde)})`));
  li.append(meta);
  if (c.comando) { const code = el('code', 'saude-cmd', c.comando); li.append(code); }
  li.append(acoes(chaveCirculo(c), []));
  return li;
}
function itemParado(x) {
  const li = el('li', 'saude-item parado');
  const topo = el('div', 'saude-titulo');
  topo.append(el('b', 'saude-num', '#' + x.numero), document.createTextNode(' ' + (x.titulo || '')));
  li.append(topo, el('div', 'saude-meta', `sem atualização há ${x.horas} h`));
  li.append(acoes(chaveParado(x), [['Abrir PR #' + x.numero + ' ↗', urlPr(x.numero)]]));
  return li;
}
// cartão rascunho (sem número de issue) numa coluna de trabalho: o líder não despacha sem número; converter primeiro
function itemRascunho(r) {
  const li = el('li', 'saude-item rascunho');
  const topo = el('div', 'saude-titulo');
  topo.append(el('b', 'saude-num', '·'), document.createTextNode(' ' + (r.titulo || '(sem título)')));
  li.append(topo, el('div', 'saude-meta', `rascunho em "${r.status || '?'}": sem número de issue, não dá para despachar`));
  if (r.comando) {
    li.append(el('div', 'saude-motivo', 'Converta em issue (devolve o número e a URL) e despache pelo número:'),
      el('code', 'saude-cmd', r.comando));
  } else {
    li.append(el('div', 'saude-motivo', 'Converta em issue no GitHub: abra o cartão e use "Convert to issue" '
      + '(com github.repo no config.json o painel mostra o comando pronto).'));
  }
  const caixa = acoes(chaveRascunho(r), [['Abrir o cartão ↗', /^https:\/\/github\.com\//.test(r.url || '') ? r.url : '']]);
  if (r.comando) { const linha = el('div', 'saude-acoes'); linha.append(botaoCopiar(r.comando)); li.append(linha); }
  li.append(caixa);
  return li;
}
// o mesmo começo de comando de novo e de novo (atrás de cd/export/VAR=): dica de script do projeto ou variável de ambiente
function itemRepetido(r) {
  const li = el('li', 'saude-item repetido');
  li.append(el('div', 'saude-titulo', `${r.agente} rodou ${r.vezes} vezes comandos que começam igual`));
  const meta = el('div', 'saude-meta');
  if (r.desde) meta.append(el('span', null, `desde ${hora(r.desde)} (${ha(r.desde)})`));
  li.append(meta, el('code', 'saude-cmd', (r.prefixo || '') + '…'));
  li.append(el('div', 'saude-motivo', 'Transforme em script do projeto (ou variável de ambiente para o caminho): o agente chama '
    + `um nome curto em vez de remontar o comando. Modelo: ${MODELO_SCRIPTS}.`));
  li.append(acoes(chaveRepetido(r), []));
  return li;
}
function descreverChave(chave) {
  const [tipo, ...resto] = chave.split(':');
  if (tipo === 'dup') return 'Duplicado: ' + resto.join(':').split(',').join(', ');
  if (tipo === 'circulo') return 'Círculo: ' + resto[0] + ' em ' + resto.slice(1).join(':');
  if (tipo === 'parado') return 'PR parado #' + resto[0];
  if (tipo === 'rascunho') return 'Cartão rascunho ' + resto.join(':');
  if (tipo === 'repetido') return 'Comando repetido: ' + resto[0];
  return chave;
}
function itemIgnorado(chave, info_, ativo) {
  const li = el('li', 'saude-item ignorado');
  li.append(el('div', 'saude-titulo', descreverChave(chave)));
  const meta = el('div', 'saude-meta');
  meta.append(el('span', null, ativo ? 'ainda detectado' : 'não detectado agora'));
  if (typeof info_.quando === 'number' && info_.quando > 0) meta.append(el('span', null, 'ignorado às ' + hora(info_.quando) + ' de ' + new Date(info_.quando * 1000).toLocaleDateString('pt-BR')));
  meta.append(quemFez(info_));
  li.append(meta);
  if (info_.motivo) li.append(el('div', 'saude-motivo', 'Motivo: ' + info_.motivo));
  const linha = el('div', 'saude-acoes');
  if (chave.startsWith('parado:')) { const u = urlPr(Number(chave.slice(7))); if (u) linha.append(link('Abrir PR ↗', u)); }
  if (ehPc()) {
    const b = el('button', 'botao', '↩️ Reativar');
    b.type = 'button'; b.title = 'Volta a alertar e a acordar o líder por este item';
    b.addEventListener('click', () => ignorar(chave, false, '', b));
    linha.append(b);
  }
  if (linha.childElementCount) li.append(linha);
  return li;
}

function itemSilenciado(chave, ativo) {
  const v = veredictos()[chave] || {};
  const li = el('li', 'saude-item ignorado');
  li.append(el('div', 'saude-titulo', descreverChave(chave)));
  const meta = el('div', 'saude-meta');
  meta.append(el('span', null, ativo ? 'ainda detectado' : 'não detectado agora'));
  if (typeof v.quando === 'number') meta.append(el('span', null, 'triado às ' + hora(v.quando)));
  if (v.modelo) meta.append(el('span', null, 'modelo ' + v.modelo));
  li.append(meta, el('div', 'saude-motivo', '🤖 falso positivo (triagem): ' + (v.motivo || '')));
  if (ehPc()) {
    const linha = el('div', 'saude-acoes');
    const b = el('button', 'botao', '↩️ Desfazer falso positivo');
    b.type = 'button'; b.title = 'O item volta a alertar e a acordar o líder';
    b.addEventListener('click', () => desfazerFP(chave, b));
    linha.append(b); li.append(linha);
  }
  return li;
}
function itemResolvido(r) {
  const li = el('li', 'saude-item resolvido');
  li.append(el('div', 'saude-titulo', '✔ resolvido às ' + hora(r.quando) + ' — ' + descreverChave(r.chave)));
  if (r.desc) li.append(el('div', 'saude-meta', r.desc));
  for (const p of ((dados && dados.pedidos) || []).filter((x) => x.chave === r.chave && x.cancelado)) {
    li.append(el('div', 'saude-pedido cancelado', (p.tipo_pedido === 'triagem' ? '🤖 aviso automático' : '📨 pedido ao líder')
      + ` de ${hora(p.ts)} — cancelado: resolvido`));
  }
  return li;
}

// ---------------------------------------------------------------- seções
function secao(id, titulo, textoDica, itens, vazio, recolhida = false) {
  const wrap = recolhida ? el('details', 'saude-secao') : el('section', 'saude-secao');
  const cab = el(recolhida ? 'summary' : 'h4', 'saude-cab');
  cab.append(el('span', null, titulo), el('span', 'saude-conta' + (itens.length ? ' tem' : ''), String(itens.length)));
  if (textoDica) cab.append(dica(textoDica, titulo));
  wrap.append(cab);
  if (recolhida) {
    wrap.open = abertos.has(id);
    wrap.addEventListener('toggle', () => { if (wrap.open) abertos.add(id); else abertos.delete(id); });
  }
  const ol = el('ol', 'saude-lista');
  if (!itens.length) ol.append(el('li', 'saude-vazio', vazio));
  for (const i of itens) ol.append(i);
  wrap.append(ol);
  return wrap;
}

function blocoRisco() {
  const lista = ((prs && prs.prs) || []).filter((p) => p && p.risco);
  const sec = el('section', 'saude-secao');
  const cab = el('h4', 'saude-cab');
  cab.append(el('span', null, 'Risco dos PRs abertos'), dica('Tamanho de cada PR aberto (linhas = adições + remoções; arquivos alterados) e checks do commit '
    + 'atual em falha. Médio a partir de 300 linhas ou 10 arquivos; grande a partir de 800 linhas ou 25 arquivos. PR grande ou com '
    + 'check falhando tende a entrar menos. (saude.risco_pr, o mesmo selo do painel PRs)', 'risco dos PRs'));
  sec.append(cab);
  if (!prs) { sec.append(el('p', 'saude-msg', CONFIG.github.prs ? 'Sem a lista de PRs agora.' : 'Sem repositório configurado (github.repo no config.json).')); return sec; }
  if (prs.erro) sec.append(el('p', 'saude-aviso', '⚠️ PRs não atualizados: ' + prs.erro));
  if (!lista.length) { sec.append(el('p', 'saude-msg', 'Nenhum PR aberto.')); return sec; }
  const n = (nv) => lista.filter((p) => p.risco.nivel === nv).length;
  const falhando = lista.filter((p) => p.risco.falhas).length;
  const resumo = el('div', 'saude-risco-resumo');
  for (const [nv, rot] of [['ok', 'pequenos'], ['medio', 'médios'], ['grande', 'grandes'], ['?', 'sem tamanho']]) {
    if (n(nv) || nv !== '?') resumo.append(el('span', 'risco ' + (nv === '?' ? 'sem' : nv), `${n(nv)} ${rot}`));
  }
  resumo.append(el('span', 'risco' + (falhando ? ' grande' : ''), `${falhando} com check falhando`));
  sec.append(resumo);
  const atencao = lista.filter((p) => p.risco.nivel === 'medio' || p.risco.nivel === 'grande' || p.risco.falhas)
    .sort((a, b) => (b.risco.linhas || 0) - (a.risco.linhas || 0));
  const ol = el('ol', 'saude-lista');
  for (const p of atencao) {
    const li = el('li', 'saude-item risco-' + p.risco.nivel);
    const topo = el('div', 'saude-titulo');
    topo.append(el('b', 'saude-num', '#' + p.numero), document.createTextNode(' ' + (p.titulo || '')));
    const meta = el('div', 'saude-meta');
    meta.append(el('span', 'risco ' + (p.risco.nivel === '?' ? 'sem' : p.risco.nivel),
      p.risco.linhas != null ? `${p.risco.linhas} linhas · ${p.risco.arquivos} arq.` : 'sem tamanho'));
    if (p.risco.falhas) meta.append(el('span', null, `${p.risco.falhas} check(s) falhando`));
    if (p.risco.dica) meta.append(el('span', null, 'sugestão: ' + p.risco.dica));
    li.append(topo, meta);
    const u = urlPr(p.numero);
    if (u) { const l = el('div', 'saude-acoes'); l.append(link('Abrir PR #' + p.numero + ' ↗', u)); li.append(l); }
    ol.append(li);
  }
  if (atencao.length) sec.append(ol);
  else sec.append(el('p', 'saude-msg', 'Todos pequenos e sem check falhando. 👍'));
  return sec;
}

// ---------------------------------------------------------------- boas práticas (boas_praticas.py)
const NIVEL_PRATICA = { erro: 0, aviso: 1, dica: 2 };
const ROT_NIVEL = { erro: 'ERRO', aviso: 'aviso', dica: 'dica' };
function itemPratica(i, nomeProjeto) {
  const nivel = i.nivel in NIVEL_PRATICA ? i.nivel : 'dica';
  const li = el('li', 'saude-item pratica-' + nivel);
  const topo = el('div', 'saude-titulo');
  topo.append(el('span', 'saude-nivel ' + nivel, ROT_NIVEL[nivel]), document.createTextNode(' ' + String(i.titulo || i.id || '')));
  li.append(topo);
  const meta = el('div', 'saude-meta');
  meta.append(el('span', null, nomeProjeto), el('span', null, i.corrigivel ? 'correção automática' : 'correção manual'));
  li.append(meta);
  if (i.detalhe) li.append(el('div', 'saude-motivo', String(i.detalhe)));
  if (i.como_corrigir) li.append(el('div', 'saude-pedido', 'Como corrigir: ' + String(i.como_corrigir)));
  return li;
}
function blocoPraticas() {
  const lista = (praticas && praticas.projetos) || [];
  const itens = [];
  let erros = 0, auto = 0;
  const comandos = [];
  for (const p of lista) {
    const nome = String(p.nome || p.projeto || 'projeto');
    if (p.erro) { itens.push(el('li', 'saude-item pratica-aviso', `${nome}: não consegui validar (${p.erro})`)); continue; }
    const falhas = (Array.isArray(p.itens) ? p.itens : []).filter((i) => i && !i.ok)
      .sort((a, b) => (NIVEL_PRATICA[a.nivel] ?? 3) - (NIVEL_PRATICA[b.nivel] ?? 3));
    for (const i of falhas) { itens.push(itemPratica(i, nome)); if (i.nivel === 'erro') erros++; if (i.corrigivel) auto++; }
    const alvo = String(p.projeto || p.nome || '');
    if (falhas.some((i) => i.corrigivel)) comandos.push(`python boas_praticas.py corrigir "${alvo}"   (plano; depois --aplicar)`);
  }
  const vazio = !praticas ? 'Consultando…' : (praticas.calculando ? 'Validando os projetos… (aparece na próxima atualização)'
    : (lista.length ? 'Tudo em ordem nos projetos. 👍' : 'Nenhuma pasta em "projetos" no config.json.'));
  const sec = secao('prat', 'Boas práticas do projeto', 'O básico de que o time de agentes precisa em cada pasta de "projetos": git, '
    + '.gitignore cobrindo segredos e pastas geradas, CLAUDE.md, definição de cada agente, .venv do Python, comando de teste, grafo e CI. '
    + 'ERRO primeiro, depois aviso e dica. Recalcula no máximo a cada 10 min. As correções seguras rodam no PC, pelo terminal, '
    + 'na pasta do escritório (nunca sobrescrevem arquivo).', itens, vazio, !erros);
  if (comandos.length) {
    sec.append(el('div', 'saude-msg', `${auto} com correção automática. No terminal, na pasta do escritório:`));
    for (const c of comandos) sec.append(el('code', 'saude-cmd', c));
  }
  if (praticas && praticas.quando) sec.append(el('div', 'saude-msg', `validado às ${hora(praticas.quando)}`));
  return sec;
}

function desenhar() {
  if (painel.hidden) return;
  const partes = [];
  if (!dados && !erro) {
    corpo.replaceChildren(el('p', 'saude-msg carregando', 'Consultando a saúde do time…'));
    info.textContent = 'consultando…';
    return;
  }
  if (erro) {
    const caixa = el('div', 'saude-erro');
    caixa.append(el('p', null, '⚠️ ' + erro));
    const b = el('button', 'botao', 'Tentar de novo'); b.type = 'button';
    b.addEventListener('click', () => { erro = ''; carregar(); });
    caixa.append(b);
    partes.push(caixa);
  }
  if (msgAcao) partes.push(el('p', msgAcao.startsWith('⚠️') ? 'saude-aviso' : 'saude-bom', msgAcao));
  if (dados && !dados.erro) {
    const ign = dados.ignorados && typeof dados.ignorados === 'object' ? dados.ignorados : {};
    const fora = (k) => !(k in ign) && !silenciado(k);
    if (dados.sem_prs) partes.push(el('p', 'saude-aviso', '⏳ GitHub fora do ar ou escritório recém-iniciado: por enquanto só os círculos. '
      + 'Duplicados e PRs parados voltam em cerca de 1 minuto.'));
    const dup = dados.duplicados || { fortes: [], fracos: [] };
    const fortes = (dup.fortes || []).filter((d) => fora(chaveDup(d)));
    const fracos = (dup.fracos || []).filter((d) => fora(chaveDup(d)));
    const circ = (dados.circulos || []).filter((c) => fora(chaveCirculo(c)));
    const par = (dados.parados || []).filter((x) => fora(chaveParado(x)));
    const rasc = (dados.rascunhos || []).filter((r) => fora(chaveRascunho(r)));
    const rep = (dados.repetidos || []).filter((r) => fora(chaveRepetido(r)));
    if (!dados.sem_prs && !fortes.length && !circ.length && !par.length && !rasc.length) {
      partes.push(el('p', 'saude-bom', '✅ Nada pedindo atenção agora.'));
    }
    if (!dados.sem_prs) {
      const s = secao('dup', 'Trabalho duplicado', 'A mesma tarefa com números de issue diferentes, ou dois PRs abertos para a mesma issue. '
        + 'Conta só o que está ativo: PR aberto ou branch local com commit nas últimas 48 h. Estes alertam e acordam o líder.',
        fortes.map((d) => itemDup(d, true)), 'Nenhum trabalho duplicado. 👍');
      s.append(secao('fracos', 'Possíveis duplicados (fracos)', 'Duas branches ativas com o mesmo número de issue: pode ser parte 1 e parte 2. '
        + 'Só aparecem aqui (não alertam).', fracos.map((d) => itemDup(d, false)), 'Nenhum.', true));
      partes.push(s);
    }
    partes.push(secao('circ', 'Agentes andando em círculos', 'Nos últimos 45 min o mesmo agente editou o mesmo arquivo 6 vezes ou mais E rodou o '
      + 'mesmo comando 4 vezes ou mais (ciclo editar → rodar → editar): sinal de que trata o sintoma, não a causa.',
      circ.map(itemCirculo), 'Ninguém andando em círculos. 👍'));
    if (!dados.sem_prs) {
      partes.push(secao('par', 'PRs parados', 'PR aberto (fora rascunho e pronto para o merge, que já tem lembrete) sem atualização há mais '
        + 'de alertas.parado_horas (padrão 24 h, no config.json).', par.map(itemParado), 'Nenhum PR parado. 👍'));
    }
    partes.push(secao('rasc', 'Cartões rascunho em coluna de trabalho', 'Cartão do Kanban que é só rascunho (Draft, sem número de '
      + 'issue) numa coluna de trabalho (Todo, Ready, In Progress, Review...). Sem número não há branch, PR nem "Closes #n": converta '
      + 'em issue antes de despachar. Vai para o vigia do líder; não alerta nem manda push.', rasc.map(itemRascunho),
    Array.isArray(dados.rascunhos) ? 'Nenhum cartão rascunho em coluna de trabalho. 👍' : 'Kanban não configurado ou fora do ar agora.'));
    partes.push(secao('rep', 'Comandos repetidos', 'Dica, não alerta: o mesmo agente rodou 8 vezes ou mais, em 60 min, comandos com '
      + 'o mesmo começo atrás de cd/export/VAR= (ou com $(...)). Um script do projeto ou uma variável de ambiente economiza tokens '
      + 'e erros. O começo aparece sem caminho absoluto; não vai para o líder.', rep.map(itemRepetido), 'Nenhum. 👍', true));
    partes.push(blocoRisco(), blocoPraticas());
    const atuais = new Set([...(dup.fortes || []), ...(dup.fracos || [])].map(chaveDup)
      .concat((dados.circulos || []).map(chaveCirculo), (dados.parados || []).map(chaveParado),
        (dados.rascunhos || []).map(chaveRascunho), (dados.repetidos || []).map(chaveRepetido)));
    const chavesIgn = Object.keys(ign).sort((a, b) => (ign[b].quando || 0) - (ign[a].quando || 0));
    partes.push(secao('ign', 'Ignorados', 'Itens que você mandou ignorar: não alertam nem acordam o líder, mas continuam sendo calculados. '
      + 'Reativar volta a alertar se o problema ainda existir.', chavesIgn.map((k) => itemIgnorado(k, ign[k], atuais.has(k))),
      'Nenhum item ignorado.', true));
    const sil = Object.keys(veredictos()).filter(silenciado);
    const tm = (dados.triagem && dados.triagem.modelo) || '';
    partes.push(secao('sil', 'Silenciados pela triagem (falso positivo)', tm
      ? `Um modelo barato (${tm}) avalia cada item novo; o que ele julga falso positivo não alerta nem acorda o líder até se `
        + `resolver (se voltar depois, é avaliado de novo). Hoje: ${dados.triagem.hoje || 0} de ${dados.triagem.teto || 30} avaliações.`
      : 'Triagem desligada (sugestoes.saude_triagem ou sugestoes.triagem_modelo = "" no config.json): todo item alerta normalmente.',
    sil.map((k) => itemSilenciado(k, atuais.has(k))), 'Nenhum.', true));
    const res = (Array.isArray(dados.resolvidos) ? dados.resolvidos : []).slice().sort((a, b) => (b.quando || 0) - (a.quando || 0));
    partes.push(secao('res', 'Resolvidos (24 h)', 'Itens que estavam aqui e saíram (numa rodada com os dados completos: com o GitHub fora, '
      + 'duplicados e PRs parados não contam como resolvidos). Ignorar e o veredicto da triagem valem só para a ocorrência: '
      + 'expiram quando o item se resolve, e pedido ainda não entregue é cancelado.', res.map(itemResolvido), 'Nada resolvido nas últimas 24 h.', true));
    if (!ehPc()) partes.push(el('p', 'saude-msg', 'Ignorar e avisar o líder só pelo PC.'));
  }
  else if (praticas) partes.push(blocoPraticas());
  corpo.replaceChildren(...partes);
  info.textContent = dados && dados.ts
    ? `calculado às ${hora(dados.ts)} (recalcula a cada 5 min)` + (carregando ? ' · atualizando…' : '')
    : (carregando ? 'consultando…' : '');
}

// ---------------------------------------------------------------- abrir / fechar / poll
function agendar() {
  clearInterval(timer); timer = null;
  if (!painel.hidden) timer = setInterval(() => { if (!painel.hidden && !document.hidden) carregar(); }, ATUALIZAR_MS);
}
function abrir() { painel.hidden = false; botao.setAttribute('aria-expanded', 'true'); msgAcao = ''; desenhar(); carregar(); agendar(); }
function fechar() { painel.hidden = true; botao.setAttribute('aria-expanded', 'false'); formAberto = ''; rascunho = ''; atrasado = false; agendar(); }

if (botao && painel && temServidor) {   // sem servidor (demonstração) não há /saude: o botão fica escondido
  botao.hidden = false;
  botao.setAttribute('aria-controls', 'saude'); botao.setAttribute('aria-expanded', 'false');
  botao.addEventListener('click', () => (painel.hidden ? abrir() : fechar()));
  $('saudeFechar').addEventListener('click', fechar);
  window.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape' || painel.hidden) return;
    if (formAberto) { fecharForm(); return; }   // 1º Esc fecha o formulário (redesenha com os dados mais novos), o 2º o painel
    fechar();
  });
  document.addEventListener('visibilitychange', () => { if (!document.hidden && !painel.hidden) carregar(); });
  window.__saude = { carregar, get dados() { return dados; }, get praticas() { return praticas; } };
}
