// Claude Office 3D — painel "🩺 Saúde": trabalho duplicado, agentes andando em círculos, PRs parados e o risco dos PRs abertos
// (GET /saude, calculado sem tokens pelo saude.py, e GET /prs para os links e o risco). Ações: abrir no GitHub, ignorar /
// reativar (POST /api/saude/ignorar: some dos alertas e do vigia do líder) e avisar o líder (POST /api/saude/avisar: o vigia
// entrega como "[vigia saude] ... pedido do desenvolvedor: ..."). Ignorar e avisar são só do PC (rede.PERMISSAO_ROTA).
// Consulta só com o painel aberto e a aba visível (a cada 60 s). Todo texto vindo de fora entra por textContent.

import { dica } from './dica.js';
import { CONFIG, temServidor } from './config.js';

const ATUALIZAR_MS = 60000;
const $ = (id) => document.getElementById(id);
const botao = $('btnSaude'), painel = $('saude'), corpo = $('saudeCorpo'), info = $('saudeInfo');
let dados = null, prs = null, sessao = null, erro = '', carregando = false, timer = null;
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

// chaves estáveis (as mesmas de saude.chave_dup / chave_circulo / chave_parado)
const chaveDup = (d) => 'dup:' + [...(d.branches || [])].map(String).sort().join(',');
const chaveCirculo = (c) => `circulo:${c.agente}:${c.arquivo}`;
const chaveParado = (x) => `parado:${x.numero}`;

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
    const [rs, rp] = await Promise.all([fetch('/saude', { cache: 'no-store' }), CONFIG.github.prs ? fetch('/prs', { cache: 'no-store' }).catch(() => null) : null]);
    const j = await rs.json();
    if (!rs.ok || !j || typeof j !== 'object') throw new Error('resposta inválida (' + rs.status + ')');
    dados = j; erro = j.erro ? String(j.erro) : '';
    if (rp && rp.ok) { try { prs = await rp.json(); } catch (e) { /* mantém o último */ } }
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
  const ped = [...((dados && dados.pedidos) || [])].reverse().find((p) => p.chave === chave);
  if (ped) {
    const d = el('div', 'saude-pedido', `📨 pedido ao líder às ${hora(ped.ts)} — ${ped.entregue ? 'entregue pelo vigia' : 'aguardando o vigia'}`
      + (ped.recado ? ` · recado: "${ped.recado}"` : '') + ' ');
    d.append(quemFez(ped));
    caixa.append(d);
  }
  if (formAberto.endsWith('|' + chave)) caixa.append(formulario(formAberto.split('|')[0], chave));
  return caixa;
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
function descreverChave(chave) {
  const [tipo, ...resto] = chave.split(':');
  if (tipo === 'dup') return 'Duplicado: ' + resto.join(':').split(',').join(', ');
  if (tipo === 'circulo') return 'Círculo: ' + resto[0] + ' em ' + resto.slice(1).join(':');
  if (tipo === 'parado') return 'PR parado #' + resto[0];
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
    const fora = (k) => !(k in ign);
    if (dados.sem_prs) partes.push(el('p', 'saude-aviso', '⏳ GitHub fora do ar ou escritório recém-iniciado: por enquanto só os círculos. '
      + 'Duplicados e PRs parados voltam em cerca de 1 minuto.'));
    const dup = dados.duplicados || { fortes: [], fracos: [] };
    const fortes = (dup.fortes || []).filter((d) => fora(chaveDup(d)));
    const fracos = (dup.fracos || []).filter((d) => fora(chaveDup(d)));
    const circ = (dados.circulos || []).filter((c) => fora(chaveCirculo(c)));
    const par = (dados.parados || []).filter((x) => fora(chaveParado(x)));
    if (!dados.sem_prs && !fortes.length && !circ.length && !par.length) partes.push(el('p', 'saude-bom', '✅ Nada pedindo atenção agora.'));
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
    partes.push(blocoRisco());
    const atuais = new Set([...(dup.fortes || []), ...(dup.fracos || [])].map(chaveDup)
      .concat((dados.circulos || []).map(chaveCirculo), (dados.parados || []).map(chaveParado)));
    const chavesIgn = Object.keys(ign).sort((a, b) => (ign[b].quando || 0) - (ign[a].quando || 0));
    partes.push(secao('ign', 'Ignorados', 'Itens que você mandou ignorar: não alertam nem acordam o líder, mas continuam sendo calculados. '
      + 'Reativar volta a alertar se o problema ainda existir.', chavesIgn.map((k) => itemIgnorado(k, ign[k], atuais.has(k))),
      'Nenhum item ignorado.', true));
    if (!ehPc()) partes.push(el('p', 'saude-msg', 'Ignorar e avisar o líder só pelo PC.'));
  }
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
  window.__saude = { carregar, get dados() { return dados; } };
}
