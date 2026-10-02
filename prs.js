// Claude Office 3D — pull requests abertos do repositório configurado, prontos para você aprovar e fazer o merge.
// O escritório só mostra e leva ao GitHub: o merge é sempre seu.
// "Aprovado" = status check github.check_revisao com SUCCESS (ou, sem check configurado, review APPROVED).
import { CONFIG, agenteConfig, LIDER, temServidor } from './config.js';

const ATUALIZAR_MS = 60000;
const GH = CONFIG.github;
const REVISOR = GH.check_revisao ? `a revisão (${GH.check_revisao})` : 'a revisão';

const $ = (id) => document.getElementById(id);
const painel = $('prs'), lista = $('prsLista'), info = $('prsInfo'), conta = $('prsConta');
let dados = null;

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
  if (g === 'SUCCESS') return { classe: 'pronto', rotulo: `✅ aprovado por ${REVISOR} — pronto para o seu merge` };
  if (g === 'FAILURE' || g === 'ERROR') return { classe: 'bloqueado', rotulo: `❌ reprovado por ${REVISOR} — volta para o time` };
  return { classe: 'espera', rotulo: `⏳ aguardando ${REVISOR}${LIDER ? ' (' + LIDER.titulo + ')' : ''}` };
}
const ordem = { pronto: 0, espera: 1, bloqueado: 2 };

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
    const acoes = el('div', 'acoes');
    const abrir = el('a', 'botao principal', s.classe === 'pronto' ? 'Aprovar e fazer merge ↗' : 'Abrir no GitHub ↗');
    abrir.href = pr.url + (s.classe === 'pronto' ? '#partial-pull-merging' : ''); abrir.target = '_blank'; abrir.rel = 'noopener';
    const arquivos = el('a', 'botao', 'Ver arquivos ↗');
    arquivos.href = pr.url + '/files'; arquivos.target = '_blank'; arquivos.rel = 'noopener';
    acoes.append(abrir, arquivos);
    li.append(topo, el('div', 'situacao', s.rotulo), meta, acoes);
    lista.append(li);
  }
  info.textContent = dados.erro && prs.length
    ? `⚠️ não consegui atualizar (${dados.erro})`
    : `${dados.repo} · ${prs.length} aberto(s), ${prontos} pronto(s) · atualizado às ${dados.atualizado}`;
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
  desenhar();
}

function abrirPainel() { painel.hidden = false; if (!dados) info.textContent = 'buscando os PRs no GitHub…'; carregar(); }
function fechar() { painel.hidden = true; }

$('btnPrs').addEventListener('click', () => (painel.hidden ? abrirPainel() : fechar()));
$('prsFechar').addEventListener('click', fechar);
$('prsAtualizar').addEventListener('click', () => { info.textContent = 'buscando…'; carregar(true); });
window.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !painel.hidden) fechar(); });
// o contador no botão fica sempre em dia, mesmo com o painel fechado (só se o repositório estiver configurado)
if (GH.prs) { carregar(); setInterval(() => { if (!document.hidden) carregar(); }, ATUALIZAR_MS); }   // aba oculta: não consulta
window.__prs = { carregar, situacao };
