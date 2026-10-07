// Claude Office 3D — pull requests abertos do repositório configurado, prontos para você aprovar e fazer o merge.
// O escritório só mostra e leva ao GitHub: o merge é sempre seu.
// "Aprovado" = status check github.check_revisao com SUCCESS (ou, sem check configurado, review APPROVED).
import { CONFIG, agenteConfig, LIDER, temServidor } from './config.js';
import { dica } from './dica.js';

const ATUALIZAR_MS = 60000;
const GH = CONFIG.github;
const REVISOR = GH.check_revisao ? `a revisão (${GH.check_revisao})` : 'a revisão';

const $ = (id) => document.getElementById(id);
const painel = $('prs'), lista = $('prsLista'), info = $('prsInfo'), conta = $('prsConta');
let dados = null;
let sugestoes = { itens: [], por_pr: {} };   // GET /api/sugestoes: sugestões abertas dos bots de revisão, por PR
let sessao = null;                           // GET /api/sessao: só o PC (permissao 'pc') vê os botões de tratar
const sugAbertas = new Set();                // PRs com a lista de sugestões expandida (sobrevive ao redesenho)
const COR_PRIO = { P0: '#ef4444', P1: '#f59e0b', P2: '#64748b', P3: '#475569', '?': '#475569' };
const ROTULO_ACAO = { corrigir: 'sugere corrigir', ignorar: 'sugere ignorar', discutir: 'sugere discutir' };

function el(tag, cls, texto) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (texto != null) e.textContent = texto;
  return e;
}
// rótulo do PR → agente: pelo mapa github.times (ex.: "team:dev": "Dev") ou pelo próprio nome do agente
function agenteDoPr(pr) {
  const mapa = GH.times || {};
  for (const r of pr.rotulos || []) {
    const k = Object.keys(mapa).find((x) => x.toLowerCase() === r.toLowerCase());
    const ag = agenteConfig(k ? mapa[k] : r) || agenteConfig(r.replace(/^team[:/]/i, ''));
    if (ag) return ag;
  }
  return null;
}

// Situação do PR para você: pronto, bloqueado ou aguardando
function situacao(pr) {
  if (pr.rascunho) return { classe: 'espera', rotulo: '📝 rascunho — ainda em trabalho' };
  if (pr.conflito) return { classe: 'bloqueado', rotulo: '⚠️ conflito com a base — precisa de rebase/merge da base' };
  const g = String(pr.revisao || '').toUpperCase();
  const seguram = ((sugestoes.seguram_merge || {})[String(pr.numero)]) || 0;   // sugestão do bot sem decisão ou sem correção
  if (g === 'SUCCESS' && seguram) return { classe: 'espera', rotulo: `✅ aprovado por ${REVISOR}, mas 🤖 ${seguram} sugestão(ões) do bot sem resolver — ainda não faça o merge` };
  if (g === 'SUCCESS') {
    // Verde só depois de TODAS as validações: o --pronto (bots e revisor revisaram o commit atual, nenhuma sugestão
    // pendente) calculado pelo servidor para ESTE commit. Sem bots/revisor configurados, vale só a revisão, como antes.
    const p = (sugestoes.pronto || {})[String(pr.numero)];
    if (sugestoes.ativo && (!p || (pr.sha && p.sha && p.sha !== pr.sha)))
      return { classe: 'espera', rotulo: `⏳ aprovado por ${REVISOR} — conferindo as revisões dos bots no commit atual` };
    if (p && !p.ok)
      return { classe: 'espera', rotulo: `⏳ aprovado por ${REVISOR}, mas ainda não: ${(p.motivos[0] || 'revisões pendentes').slice(0, 120)}` };
    return { classe: 'pronto', rotulo: `✅ aprovado por ${REVISOR} e revisado pelos bots no commit atual — pronto para o seu merge` };
  }
  if (g === 'FAILURE' || g === 'ERROR') return { classe: 'bloqueado', rotulo: `❌ reprovado por ${REVISOR} — volta para o time` };
  return { classe: 'espera', rotulo: `⏳ aguardando ${REVISOR}${LIDER ? ' (' + LIDER.titulo + ')' : ''}` };
}
const ordem = { pronto: 0, espera: 1, bloqueado: 2 };

// "🤖 3 (1 P1)": total de sugestões abertas dos bots e, entre parênteses, as P0/P1
function seloSugestoes(itens) {
  const n = (p) => itens.filter((x) => x.prioridade === p).length;
  const graves = ['P0', 'P1'].filter((p) => n(p)).map((p) => `${n(p)} ${p}`);
  return `🤖 ${itens.length}` + (graves.length ? ` (${graves.join(', ')})` : '');
}

async function pegarSessao() {
  if (!sessao) { try { sessao = await (await fetch('/api/sessao', { cache: 'no-store' })).json(); } catch (e) { sessao = null; } }
  return sessao;
}

async function tratar(item, acao, botao) {
  const s = await pegarSessao();
  const cab = { 'Content-Type': 'application/json', 'X-Office-Acao': '1' };
  if (s && s.csrf) cab['X-Office-Csrf'] = s.csrf;
  botao.disabled = true;
  try {
    const r = await fetch('/api/sugestoes/tratar', { method: 'POST', headers: cab, body: JSON.stringify({ id: item.id, acao }) });
    const j = await r.json().catch(() => ({}));
    if (!r.ok || !j.ok) throw new Error(j.erro || 'falhou (' + r.status + ')');
    if (j.sugestoes) sugestoes = j.sugestoes;
    desenhar(); publicar();
  } catch (e) {
    botao.disabled = false;
    botao.title = 'não deu: ' + e.message;
    info.textContent = '⚠️ não consegui tratar a sugestão (' + e.message + ')';
  }
}

function itemSugestao(item, ehPc) {
  const li = el('li', 'sug');
  const topo = el('div', 'sug-topo');
  const prio = el('span', 'prio', item.prioridade); prio.style.background = COR_PRIO[item.prioridade] || '#475569';
  const t = el('a', 'sug-titulo', item.titulo); t.href = item.link; t.target = '_blank'; t.rel = 'noopener';
  topo.append(prio, t);
  const meta = el('div', 'sug-meta');
  const autor = String(item.autor || ''), bot = /copilot/i.test(autor) ? 'Copilot' : /codex/i.test(autor) ? 'Codex'
    : /coderabbit/i.test(autor) ? 'CodeRabbit' : autor.replace(/\[bot\]$/i, '');
  if (bot) meta.append(el('span', 'sug-bot', bot));
  if (item.arquivo) meta.append(el('span', null, item.linha ? `${item.arquivo}:${item.linha}` : item.arquivo));
  else if (item.tipo === 'revisao') meta.append(el('span', null, 'revisão geral'));
  if (item.acao_sugerida) meta.append(el('span', 'sug-acao ' + item.acao_sugerida, ROTULO_ACAO[item.acao_sugerida] || item.acao_sugerida));
  if (item.situacao === 'discutir') meta.append(el('span', 'sug-acao discutir', 'em discussão'));
  li.append(topo, meta);
  if (item.motivo) li.append(el('div', 'sug-motivo', item.motivo));
  if (item.texto) { const d = el('details', 'sug-texto'); d.append(el('summary', null, 'ver o texto do bot'), el('p', null, item.texto)); li.append(d); }
  if (ehPc) {
    const ac = el('div', 'sug-acoes');
    for (const [acao, rotulo] of [['encaminhada', 'Encaminhar'], ['ignorada', 'Ignorar'], ['resolvida', 'Resolvido']]) {
      const b = el('button', 'botao', rotulo); b.title = acao === 'encaminhada' ? 'Já foi mandada ao colega' : acao === 'ignorada' ? 'Descartar a sugestão' : 'Já foi corrigida';
      b.addEventListener('click', () => tratar(item, acao, b));
      ac.append(b);
    }
    li.append(ac);
  }
  return li;
}

function blocoSugestoes(numero, itens) {
  const det = el('details', 'sugestoes' + (itens.some((x) => x.prioridade === 'P0' || x.prioridade === 'P1') ? ' grave' : ''));
  det.open = sugAbertas.has(numero);
  det.addEventListener('toggle', () => { if (det.open) sugAbertas.add(numero); else sugAbertas.delete(numero); });
  det.append(el('summary', null, seloSugestoes(itens) + ' — sugestões do bot de revisão'));
  const ehPc = !!sessao && sessao.permissao === 'pc';
  const ul = el('ul', 'sug-lista');
  itens.forEach((x) => ul.append(itemSugestao(x, ehPc)));
  det.append(ul);
  return det;
}

function desenhar() {
  if (!dados) return;
  if (dados.configurado === false) {
    conta.hidden = true;
    lista.textContent = ''; lista.append(el('li', 'vazio', '⚠️ ' + dados.erro));
    info.textContent = '';
    return;
  }
  const prs = dados.prs.map((pr) => ({ pr, s: situacao(pr) })).sort((a, b) => ordem[a.s.classe] - ordem[b.s.classe] || a.pr.numero - b.pr.numero);
  const prontos = prs.filter((x) => x.s.classe === 'pronto').length;
  conta.hidden = !prontos; conta.textContent = prontos;
  lista.textContent = '';
  if (!prs.length) lista.append(el('li', 'vazio', dados.erro ? '⚠️ ' + dados.erro : 'Nenhum PR aberto. Tudo mergeado 🎉'));
  for (const { pr, s } of prs) {
    const li = el('li', 'pr ' + s.classe);
    const ag = agenteDoPr(pr);
    li.style.borderLeftColor = ag ? ag.cor : '#475569';
    const topo = el('div', 'topo');
    topo.append(el('b', 'num', '#' + pr.numero), el('span', 'titulo', pr.titulo));
    const meta = el('div', 'meta');
    if (ag) { const t = el('span', 'time', ag.titulo); t.style.color = ag.cor; meta.append(t); }
    meta.append(el('span', null, pr.branch));
    if (pr.autor) meta.append(el('span', null, '@' + pr.autor));
    if (pr.fecha.length) meta.append(el('span', null, 'fecha ' + pr.fecha.map((n) => '#' + n).join(', ')));
    const r = pr.risco;   // saude.risco_pr: PR grande ou com checks falhando entra menos (arXiv 2601.15195)
    if (r && r.nivel !== '?') {
      const selo = el('span', 'risco ' + r.nivel, `${r.linhas} linhas · ${r.arquivos} arq.` + (r.falhas ? ` · ${r.falhas} check(s) falhando` : ''));
      const grupo = el('span', 'risco-grupo');   // limites iguais a saude.RISCO e checks iguais a saude.CHECKS_FALHOS
      grupo.append(selo, dica('Tamanho do PR: linhas = adições + remoções; arq. = arquivos alterados (GitHub). Médio a partir de 300 linhas ou '
        + '10 arquivos; grande a partir de 800 linhas ou 25 arquivos. Checks falhando = status do commit atual em falha, erro, tempo esgotado, '
        + 'cancelado, ação necessária ou falha ao iniciar. PR grande ou com check falhando tende a entrar menos. (saude.risco_pr)'
        + (r.dica ? '\n\nSugestão: ' + r.dica + '.' : ''), 'selo de tamanho e risco do PR'));
      meta.append(grupo);
    }
    const acoes = el('div', 'acoes');
    const abrir = el('a', 'botao principal', s.classe === 'pronto' ? 'Aprovar e fazer merge ↗' : 'Abrir no GitHub ↗');
    abrir.href = pr.url + (s.classe === 'pronto' ? '#partial-pull-merging' : ''); abrir.target = '_blank'; abrir.rel = 'noopener';
    const arquivos = el('a', 'botao', 'Ver arquivos ↗');
    arquivos.href = pr.url + '/files'; arquivos.target = '_blank'; arquivos.rel = 'noopener';
    acoes.append(abrir, arquivos);
    li.append(topo, el('div', 'situacao', s.rotulo), meta, acoes);
    const sg = (sugestoes.itens || []).filter((x) => x.pr === pr.numero);
    if (sg.length) li.append(blocoSugestoes(pr.numero, sg));
    lista.append(li);
  }
  info.textContent = (dados.erro && prs.length
    ? `⚠️ não consegui atualizar (${dados.erro})`
    : `${dados.repo} · ${prs.length} aberto(s), ${prontos} pronto(s) · atualizado às ${dados.atualizado}`)
    + (dados.limite ? ` · ⏳ ${dados.limite}` : '')
    + (dados.cota ? ` · ${dados.cota_baixa ? '⚠️ ' : ''}${dados.cota}` : '')
    + (sugestoes.erro ? ` · 🤖 coleta de sugestões: ${sugestoes.erro}` : '');
}

async function carregar(forcar = false) {
  if (!temServidor) {
    dados = { configurado: false, prs: [], erro: 'sem servidor: abra o escritório pelo abrir_escritorio (.bat ou .sh) para ver os PRs.' };
    return desenhar();
  }
  try {
    const r = await fetch('/prs' + (forcar ? '?forcar=1' : ''), { cache: 'no-store' });
    dados = await r.json();
  } catch (e) {
    dados = dados || { prs: [], repo: '', atualizado: '' };
    dados.erro = 'servidor do escritório fora do ar (abra pelo abrir_escritorio)';
  }
  try {   // sugestões dos bots: leitura local do servidor (não chama o GitHub)
    await pegarSessao();
    const rs = await fetch('/api/sugestoes', { cache: 'no-store' });
    const js = await rs.json();
    if (js && js.ok) sugestoes = js;
  } catch (e) { /* mantém as últimas */ }
  desenhar();
  publicar();
}
// Para o escritório 3D (tela de PRs na parede e sino do líder): situação já calculada de cada PR, só quando os dados mudam
let publicado = '';
function publicar() {
  if (!dados || !Array.isArray(dados.prs)) return;
  const prs = dados.prs.map((pr) => ({ numero: pr.numero, titulo: String(pr.titulo || ''), classe: situacao(pr).classe, risco: pr.risco || null }));
  const detail = { prs, atualizado: dados.atualizado || '', erro: dados.erro || '' };
  const chave = JSON.stringify(detail);
  if (chave === publicado) return;
  publicado = chave;
  window.dispatchEvent(new CustomEvent('prs', { detail }));
}

function abrirPainel() { painel.hidden = false; if (!dados) info.textContent = 'buscando os PRs no GitHub…'; carregar(); }
function fechar() { painel.hidden = true; }

$('btnPrs').addEventListener('click', () => (painel.hidden ? abrirPainel() : fechar()));
$('prsFechar').addEventListener('click', fechar);
$('prsAtualizar').addEventListener('click', () => { info.textContent = 'buscando…'; carregar(true); });
window.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !painel.hidden) fechar(); });
// o contador no botão fica sempre em dia, mesmo com o painel fechado (só se o repositório estiver configurado)
if (GH.prs) { carregar(); setInterval(() => { if (!document.hidden) carregar(); }, ATUALIZAR_MS); }   // aba oculta: não consulta
window.__prs = { carregar, situacao, seloSugestoes, get dados() { return dados; } };
