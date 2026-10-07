// Claude Office 3D — painel "🗺️ Arquitetura": grafo de sistemas do projeto (GET /grafo: index do grafo/grafo.py, drift e validação)
// com quem está mexendo onde, ao vivo (eventos do escritório: file_path de Edit/Write/Read, comando que falhou, círculos da /saude).
// SVG gerado aqui (createElementNS + textContent; nada de innerHTML com dado de fora). Colunas por camada na ordem das
// may_depend_on (quem não depende de ninguém à esquerda); no celular vira lista por camada. Sem custo por quadro: o desenho
// só muda quando chegam dados (no máximo 1 vez por segundo) e a cada 30 s com o painel aberto (o anel de 10 min expira).

import { CONFIG, temServidor } from './config.js';

const $ = (id) => document.getElementById(id);
const NS = 'http://www.w3.org/2000/svg';
const RECENTE_MS = 10 * 60 * 1000, ATUALIZAR_GRAFO_MS = 30 * 60 * 1000, ATUALIZAR_ABERTO_MS = 5 * 60 * 1000;
const FERR_EDICAO = new Set(['Edit', 'Write', 'MultiEdit', 'NotebookEdit']), FERR_LEITURA = new Set(['Read']);
const FERR_COMANDO = new Set(['Bash', 'PowerShell']);
const COL_W = 230, LIN_H = 74, TOPO = 46, MARGEM = 20, MAX_PAGINAS_HOJE = 3;
const botao = $('btnArquitetura'), painel = $('arquitetura'), infoEl = $('arqInfo'), corpoEl = $('arqCorpo'), fichaEl = $('arqFicha');
const btnModo = $('arqModo');

let dados = null, erro = '', carregadoEm = 0, carregando = false;
let modoLista = null;                  // null = automático (lista no celular)
let selecionado = '';
let arquivosMin = new Map(), prefixos = [], cacheSistema = new Map();
const hoje = { dia: '', sistemas: new Map(), vistos: new Set(), carregado: false };   // sid -> {edicoes, porAgente: Map(nome -> {n, ms})}
const toque = new Map();               // sid -> {agente, ms, leitura}
const falhaSis = new Map();            // sid -> {ms, agente, cmd, codigo}
let circulos = [];                     // [{agente, arquivo}] não ignorados (/saude)
let nos = new Map();                   // sid -> {g, anel, badge, falha, circ} (SVG atual)
let timerAberto = null, refazer = false;

function el(tag, cls, texto) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (texto != null) e.textContent = texto;
  return e;
}
function svg(tag, attrs = {}, pai = null) {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, String(v));
  if (pai) pai.append(e);
  return e;
}
const curto = (sid) => String(sid || '').replace(/^sys\./, '');
const hhmm = (ms) => new Date(ms).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
const diaLocal = (d = new Date()) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const sistemas = () => (dados && dados.index && dados.index.sistemas) || {};
const nomeDe = (sid) => String((sistemas()[sid] && sistemas()[sid].nome) || curto(sid));
function corAgente(nome) {
  const o = window.__office, a = o && o.agentes && o.agentes.get(nome);
  return a ? '#' + a.cor.toString(16).padStart(6, '0') : '#e2e8f0';
}
function tituloAgente(nome) {
  const o = window.__office, a = o && o.agentes && o.agentes.get(nome);
  return a ? a.titulo : String(nome || '?').replace(/_/g, ' ');
}

// ---------------------------------------------------------------- arquivo -> sistema (mesma normalização do grafo)
export function normalizarArquivo(p) {
  let s = String(p || '').trim().replace(/\\/g, '/').toLowerCase();
  s = s.replace(/^.*?\/\.claude\/worktrees\/[^/]+\//, '');   // worktree do Claude Code (<projeto>/.claude/worktrees/<nome>/)
  const raiz = raizProjeto();
  if (raiz && s.startsWith(raiz + '/')) s = s.slice(raiz.length + 1);   // caminho absoluto dentro do projeto (1ª pasta de "projetos")
  return s.replace(/^\.\//, '');
}
function raizProjeto() {   // pasta do projeto, como o servidor informa no /grafo (minúsculas, com /)
  return String((dados && dados.raiz) || '').replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase();
}
function globRe(p) {
  const r = p.replace(/[.+^${}()|[\]\\]/g, '\\$&').replace(/\*\*\/?/g, '\u0000').replace(/\*/g, '[^/]*').replace(/\?/g, '[^/]').replace(/\u0000/g, '.*');
  return new RegExp('^' + r + '(/.*)?$');
}
function prepararMapa() {
  arquivosMin = new Map(); prefixos = []; cacheSistema = new Map();
  const idx = dados && dados.index;
  if (!idx) return;
  for (const [f, sid] of Object.entries(idx.arquivos || {})) arquivosMin.set(String(f).toLowerCase(), sid);
  for (const [sid, s] of Object.entries(idx.sistemas || {})) {
    for (const p of s.paths || []) {
      const pl = String(p).toLowerCase().replace(/\/+$/, '');
      if (!pl) continue;
      if (/[*?]/.test(pl)) prefixos.push({ re: globRe(pl), sid, n: pl.length });
      else prefixos.push({ p: pl, sid, n: pl.length });
    }
  }
  prefixos.sort((a, b) => b.n - a.n);   // o caminho mais longo vence (como o owner do grafo)
}
export function sistemaDe(caminho) {
  if (!dados || !dados.index || !caminho) return null;
  const s = normalizarArquivo(caminho);
  if (cacheSistema.has(s)) return cacheSistema.get(s);
  let sid = arquivosMin.get(s) || null;
  if (!sid) {
    for (const x of prefixos) {
      if (x.re ? x.re.test(s) : (s === x.p || s.startsWith(x.p + '/'))) { sid = x.sid; break; }
    }
  }
  if (cacheSistema.size > 3000) cacheSistema.clear();
  cacheSistema.set(s, sid);
  return sid;
}
function arquivoDoEvento(ev) {
  const m = /(?:^|\n)(?:file_path|notebook_path): *([^\n]+)/.exec(String(ev.detalhe || ''));
  return m ? m[1].trim() : '';
}

// ---------------------------------------------------------------- eventos ao vivo e do dia
function chaveEv(ev) { return [ev.ts, ev.agente, ev.ferramenta, ev.detalhe, ev.resumo, ev.ok].join('|'); }
function zerarDia() {
  hoje.dia = diaLocal(); hoje.sistemas = new Map(); hoje.vistos = new Set(); hoje.carregado = false;
}
function registrar(ev, aoVivo) {
  if (!ev || typeof ev !== 'object' || String(ev.tipo || 'trabalho') !== 'trabalho' || !dados || !dados.index) return false;
  const ms = Date.parse(ev.ts);
  if (!Number.isFinite(ms)) return false;
  if (diaLocal() !== hoje.dia) zerarDia();   // virou o dia: recomeça a contagem
  if (diaLocal(new Date(ms)) !== hoje.dia) return false;   // evento de outro dia (replay, carga atrasada)
  const k = chaveEv(ev);
  if (hoje.vistos.has(k)) return false;
  hoje.vistos.add(k);
  const nome = String(ev.agente || '?'), ferr = String(ev.ferramenta || '');
  let mudou = false;
  if ((FERR_EDICAO.has(ferr) || FERR_LEITURA.has(ferr)) && !ev.inicio) {
    const sid = sistemaDe(arquivoDoEvento(ev));
    if (sid) {
      const t = toque.get(sid);
      if (!t || t.ms <= ms) toque.set(sid, { agente: nome, ms, leitura: !FERR_EDICAO.has(ferr) });
      if (FERR_EDICAO.has(ferr)) {
        let h = hoje.sistemas.get(sid); if (!h) { h = { edicoes: 0, porAgente: new Map() }; hoje.sistemas.set(sid, h); }
        h.edicoes++;
        const pa = h.porAgente.get(nome) || { n: 0, ms: 0 }; pa.n++; pa.ms = Math.max(pa.ms, ms); h.porAgente.set(nome, pa);
      }
      mudou = true;
    }
  }
  if (FERR_COMANDO.has(ferr) && !ev.inicio && typeof ev.ok === 'boolean') {
    // aproximação: comando de teste/build que cita um caminho do sistema (casado inteiro, com fronteira) → ✖ no sistema;
    // sucesso do mesmo tipo depois limpa. grep/findstr/git diff --quiet saem com 1 sem ser erro: não contam.
    const det = String(ev.detalhe || ''), m = /^command: *([\s\S]*)$/m.exec(det);
    const cmd = normalizarComando(m ? m[1] : det);
    if (!RE_TESTE_BUILD.test(cmd) || benigno(cmd, ev.codigo)) return mudou && aoVivo ? (agendarDesenho(), true) : mudou;
    for (const x of prefixos) {
      if (x.re || x.p.length < 6 || !citaCaminho(cmd, x.p)) continue;
      if (ev.ok === false) falhaSis.set(x.sid, { ms, agente: nome, cmd: cmd.slice(0, 160), codigo: ev.codigo });
      else if (falhaSis.has(x.sid) && falhaSis.get(x.sid).ms <= ms) falhaSis.delete(x.sid);
      mudou = true;
    }
  }
  if (mudou && aoVivo) agendarDesenho();
  return mudou;
}
const RE_TESTE_BUILD = /(^|[\s"'/\\&;|(])(pytest|unittest|ctest|test|tests|testar_\w+|test_\w+|\w+_test|build|build-\w+|package-\w+|compil\w*|msbuild|gradle|mvn|cargo|make|npm|jest|vitest|cmake|ninja|validate\w*|lint)([\s"'./\\&;|)]|$)/i;
const RE_BENIGNO = /^\s*(grep|rg|findstr|select-string|git\s+(diff|status|log|show|grep)|diff|fc|cmp|where|which|test\s+-\w|\[)(?=\s|$)/i;
function benigno(cmd, codigo) {   // o código de saída é o do último comando da cadeia (cd x && grep y; a | grep b)
  const partes = String(cmd).split(/&&|\|\||[;|\n]/).map((x) => x.trim()).filter(Boolean);
  if (!partes.length) return false;
  if (RE_BENIGNO.test(partes[partes.length - 1])) return true;
  return Number(codigo) === 1 && partes.some((x) => RE_BENIGNO.test(x));   // saída 1 com grep/diff em qualquer ponto da cadeia
}
function citaCaminho(cmd, p) {   // p aparece como caminho inteiro (não como pedaço de outro nome)
  let i = cmd.indexOf(p);
  while (i >= 0) {
    let ini = i;
    if (ini >= 2 && cmd.slice(ini - 2, ini) === './') ini -= 2;   // "./caminho" também vale
    const antes = ini === 0 ? ' ' : cmd[ini - 1], depois = cmd[i + p.length] || ' ';
    if (/[\s"'=(:]/.test(antes) && /[\s"'/;:),&|]/.test(depois)) return true;
    i = cmd.indexOf(p, i + 1);
  }
  return false;
}
function normalizarComando(c) {
  let s = String(c || '').replace(/\\/g, '/').toLowerCase().replace(/[^\s"']*\/\.claude\/worktrees\/[^/\s"']+\//g, '');
  const raiz = raizProjeto();
  if (raiz) s = s.split(raiz + '/').join('');   // caminhos absolutos do projeto viram relativos
  return s;
}
async function carregarHoje() {
  if (hoje.carregado || location.protocol === 'file:' || !dados || !dados.index) return;   // sem o mapa ainda: tenta quando o /grafo chegar
  if (diaLocal() !== hoje.dia) zerarDia();
  hoje.carregado = true;
  try {
    let apos = 0;
    for (let pag = 0; pag < MAX_PAGINAS_HOJE; pag++) {
      const r = await fetch('/eventos?de=' + hoje.dia + (apos ? '&apos=' + apos : ''), { cache: 'no-store' });
      if (!r.ok) break;
      const j = await r.json();
      for (const ev of j.eventos || []) registrar(ev, false);
      if (!j.proximo) break;
      apos = j.proximo;
    }
  } catch (e) { hoje.carregado = false; }
  agendarDesenho();
}
function receberSaude(d) {
  if (!d || typeof d !== 'object' || d.erro) return;
  const ign = d.ignorados && typeof d.ignorados === 'object' ? d.ignorados : {};
  circulos = (Array.isArray(d.circulos) ? d.circulos : []).filter((c) => c && !ign['circulo:' + c.agente + ':' + c.arquivo])
    .map((c) => ({ agente: String(c.agente || '?'), arquivo: String(c.arquivo || '').toLowerCase() }));
  agendarDesenho();
}
function circulosDe(sid) {   // a /saude só traz o nome do arquivo: casa pelo nome com os arquivos do sistema
  if (!circulos.length || !dados || !dados.index) return [];
  const arqs = Object.entries(dados.index.arquivos || {}).filter(([, s]) => s === sid).map(([f]) => f.toLowerCase().split('/').pop());
  return circulos.filter((c) => arqs.includes(c.arquivo));
}

// ---------------------------------------------------------------- dados do servidor
async function carregar() {
  if (carregando || location.protocol === 'file:') return;
  carregando = true;
  try {
    const r = await fetch('/grafo', { cache: 'no-store' });
    const j = await r.json();
    if (!r.ok) throw new Error(j && j.erro ? j.erro : 'HTTP ' + r.status);
    if (j && typeof j === 'object') {
      const mudouIndex = !dados || !dados.index || !j.index || dados.index.assinatura !== j.index.assinatura || dados.commit !== j.commit;
      const erroAntes = erro;
      dados = j; erro = j.erro || '';
      if (mudouIndex) {   // mapa arquivo → sistema novo: recomeça a contagem do dia (recontada do /eventos ao abrir o painel)
        prepararMapa(); nos = new Map(); zerarDia(); toque.clear(); falhaSis.clear(); refazer = true;
      }
      if (erro !== erroAntes) refazer = true;
    }
  } catch (e) {
    const novo = 'não consegui ler /grafo: ' + String(e && e.message || e).slice(0, 120);
    if (novo !== erro) refazer = true;
    erro = novo;
  }
  carregando = false; carregadoEm = Date.now();
  if (!painel.hidden) {
    if (refazer || !nos.size) desenhar(); else { desenharInfo(); atualizarAoVivo(); }   // sem mudança: não refaz o SVG (nem perde a rolagem)
    refazer = false;
    carregarHoje();
  }
  if (window.__office && window.__office.atualizarFicha) window.__office.atualizarFicha();   // "sistema atual" na ficha do agente
}

// ---------------------------------------------------------------- desenho
function ordemCamadas(camadas) {
  const nomes = Object.keys(camadas || {}), feitas = [], resta = new Set(nomes);
  while (resta.size) {   // quem só depende de camadas já colocadas vai na próxima coluna (Kahn; ciclo: ordem do arquivo)
    const prox = [...resta].filter((c) => (camadas[c].may_depend_on || []).every((d) => !resta.has(d) || d === c));
    const lote = prox.length ? prox : [[...resta][0]];
    lote.sort((a, b) => nomes.indexOf(a) - nomes.indexOf(b));
    for (const c of lote) { feitas.push(c); resta.delete(c); }
  }
  return feitas;
}
function problemas() {
  const v = (dados && dados.validacao) || {};
  const erros = v.erros || [];
  const camadaReal = new Set(erros.filter((e) => e.codigo === 'camada_real' && e.de && e.para).map((e) => e.de + '>' + e.para));
  const ciclo = new Set(); erros.filter((e) => e.codigo === 'ciclo_real').forEach((e) => (e.sistemas || []).forEach((s) => ciclo.add(s)));
  return { erros, camadaReal, ciclo };
}
function layout() {
  const idx = dados.index, sis = idx.sistemas || {};
  const ordem = ordemCamadas(idx.camadas);
  const colunas = ordem.map((c) => ({ camada: c, itens: [] }));
  const semCamada = { camada: '', itens: [] };
  for (const sid of Object.keys(sis).sort((a, b) => nomeDe(a).localeCompare(nomeDe(b), 'pt-BR') || a.localeCompare(b))) {
    const col = colunas.find((c) => c.camada === sis[sid].camada) || semCamada;
    col.itens.push(sid);
  }
  if (semCamada.itens.length) colunas.push(semCamada);
  const pos = new Map();
  colunas.forEach((c, i) => c.itens.forEach((sid, j) => pos.set(sid, { x: MARGEM + i * COL_W + COL_W / 2, y: TOPO + 30 + j * LIN_H, col: i })));
  const alto = TOPO + 30 + Math.max(1, ...colunas.map((c) => c.itens.length)) * LIN_H;
  return { colunas, pos, largura: MARGEM * 2 + colunas.length * COL_W, alto };
}
function raio(sid) { return 9 + Math.min(16, Math.sqrt(Math.max(0, (sistemas()[sid] || {}).arquivos || 0)) * 2); }
function curva(a, b, mesmaColuna) {
  if (mesmaColuna) { const dx = 60 + Math.abs(b.y - a.y) * 0.15; return `M${a.x},${a.y} C${a.x + dx},${a.y} ${b.x + dx},${b.y} ${b.x},${b.y}`; }
  const mx = (a.x + b.x) / 2;
  return `M${a.x},${a.y} C${mx},${a.y} ${mx},${b.y} ${b.x},${b.y}`;
}
function desenharGrafo() {
  const idx = dados.index, sis = idx.sistemas || {}, L = layout(), P = problemas();
  const s = svg('svg', { viewBox: `0 0 ${L.largura} ${L.alto}`, width: L.largura, height: L.alto, role: 'group',
    'aria-label': `Grafo de arquitetura: ${Object.keys(sis).length} sistemas em ${L.colunas.length} camadas` });
  const defs = svg('defs', {}, s);
  for (const [id, cor] of [['seta', '#64748b'], ['setaR', '#ef4444'], ['setaC', '#f97316']]) {
    const m = svg('marker', { id: 'arq-' + id, viewBox: '0 0 10 10', refX: 9, refY: 5, markerWidth: 6, markerHeight: 6, orient: 'auto-start-reverse' }, defs);
    svg('path', { d: 'M0,0 L10,5 L0,10 z', fill: cor }, m);
  }
  L.colunas.forEach((c, i) => {
    const x = MARGEM + i * COL_W;
    svg('rect', { x: x + 6, y: 8, width: COL_W - 12, height: L.alto - 14, rx: 10, class: 'arq-coluna' }, s);
    const t = svg('text', { x: x + COL_W / 2, y: 30, 'text-anchor': 'middle', class: 'arq-camada' }, s);
    t.textContent = c.camada || 'sem camada';
    const cor = c.camada && idx.camadas[c.camada] ? idx.camadas[c.camada].cor : '#94a3b8';
    svg('rect', { x: x + COL_W / 2 - 24, y: 36, width: 48, height: 3, rx: 1.5, fill: cor }, s);
  });
  const arestas = svg('g', { class: 'arq-arestas' }, s);
  const borda = (sid) => { const p = L.pos.get(sid); return p ? { ...p } : null; };
  const ligar = (a, b, cls, marca, titulo) => {
    const pa = borda(a), pb = borda(b); if (!pa || !pb || a === b) return;
    const ra = raio(a), rb = raio(b), mesma = pa.col === pb.col;
    const dir = mesma ? 1 : Math.sign(pb.x - pa.x) || 1;
    const p = svg('path', { d: curva({ x: pa.x + (mesma ? ra : dir * ra), y: pa.y }, { x: pb.x - (mesma ? -rb : dir * rb), y: pb.y }, mesma), class: cls,
      'marker-end': `url(#arq-${marca})` }, arestas);
    if (titulo) svg('title', {}, p).textContent = titulo;
  };
  for (const [a, b] of (idx.arestas && idx.arestas.declaradas) || []) ligar(a, b, 'arq-decl', 'seta', `${nomeDe(a)} depende de ${nomeDe(b)} (declarado)`);
  for (const r of (idx.arestas && idx.arestas.reais) || []) {
    const viol = P.camadaReal.has(r.de + '>' + r.para), ciclo = P.ciclo.has(r.de) && P.ciclo.has(r.para) && r.tipo !== 'evento';
    if (r.tipo !== 'nao_declarada' && !viol && !ciclo) continue;
    ligar(r.de, r.para, ciclo ? 'arq-ciclo' : 'arq-real', ciclo ? 'setaC' : 'setaR',
      `${viol ? 'CAMADA VIOLADA no código' : ciclo ? 'parte de um CICLO real' : 'import real NÃO declarado'}: ${nomeDe(r.de)} → ${nomeDe(r.para)} (${r.refs} ref.; ex.: ${r.exemplo})`);
  }
  nos = new Map();
  for (const [sid, p] of L.pos) {
    const info = sis[sid] || {}, r = raio(sid);
    const g = svg('g', { class: 'arq-no' + (info.status === 'deprecated' ? ' deprecated' : '') + (P.ciclo.has(sid) ? ' em-ciclo' : '') + (sid === selecionado ? ' sel' : ''),
      transform: `translate(${p.x},${p.y})`, tabindex: 0, role: 'button', 'data-sid': sid }, s);
    const anel = svg('circle', { r: r + 6, class: 'arq-anel' }, g);
    if (P.ciclo.has(sid)) svg('circle', { r: r + 3, class: 'arq-anel-ciclo' }, g);
    svg('circle', { r, fill: info.cor || '#94a3b8', class: 'arq-bola' }, g);
    const nome = svg('text', { y: r + 16, 'text-anchor': 'middle', class: 'arq-nome' }, g);
    const n = info.nome || curto(sid); nome.textContent = n.length > 26 ? n.slice(0, 25) + '…' : n;
    const badge = svg('text', { x: r + 4, y: -r + 2, class: 'arq-calor' }, g);
    const falha = svg('text', { x: -r - 4, y: -r + 4, 'text-anchor': 'end', class: 'arq-falha' }, g);
    const circ = svg('text', { x: 0, y: -r - 6, 'text-anchor': 'middle', class: 'arq-circ' }, g);
    const tit = svg('title', {}, g);
    g.addEventListener('click', () => abrirSistema(sid));
    g.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); abrirSistema(sid); } });
    nos.set(sid, { g, anel, badge, falha, circ, tit });
  }
  const caixa = el('div', 'arq-grafo'); caixa.append(s);
  return caixa;
}
function estadoAoVivo(sid) {
  const agora = Date.now(), t = toque.get(sid), h = hoje.sistemas.get(sid), f = falhaSis.get(sid), c = circulosDe(sid);
  return { recente: t && agora - t.ms < RECENTE_MS ? t : null, edicoes: h ? h.edicoes : 0, falha: f || null, circ: c };
}
function textoNo(sid, e) {
  const info = sistemas()[sid] || {};
  const partes = [`${info.nome || curto(sid)} (${sid}) — camada ${info.camada || '?'}, ${info.arquivos || 0} arquivo(s)` + (info.status === 'deprecated' ? ', deprecated' : '')];
  if (e.recente) partes.push(`${tituloAgente(e.recente.agente)} ${e.recente.leitura ? 'leu' : 'mexeu'} às ${hhmm(e.recente.ms)}`);
  if (e.edicoes) partes.push(`${e.edicoes} edição(ões) hoje`);
  if (e.falha) partes.push(`✖ comando falhou às ${hhmm(e.falha.ms)}`);
  if (e.circ.length) partes.push(`🔁 ${e.circ.map((c) => tituloAgente(c.agente)).join(', ')} em círculos`);
  return partes.join('; ');
}
function atualizarAoVivo() {   // só os enfeites dos nós (anel, calor, ✖, 🔁): o SVG não é refeito
  let maxCalor = 1;
  for (const h of hoje.sistemas.values()) maxCalor = Math.max(maxCalor, h.edicoes);
  for (const [sid, n] of nos) {
    const e = estadoAoVivo(sid);
    n.anel.setAttribute('stroke', e.recente ? corAgente(e.recente.agente) : 'transparent');
    n.anel.setAttribute('stroke-dasharray', e.recente && e.recente.leitura ? '4 3' : '');
    n.badge.textContent = e.edicoes ? '✎' + e.edicoes : '';
    n.badge.setAttribute('fill-opacity', String(0.45 + 0.55 * (e.edicoes / maxCalor)));
    n.falha.textContent = e.falha ? '✖' : '';
    n.circ.textContent = e.circ.length ? '🔁' : '';
    const t = textoNo(sid, e);
    n.tit.textContent = t; n.g.setAttribute('aria-label', t);
  }
  const lista = corpoEl.querySelectorAll('.arq-linha');
  lista.forEach((li) => {
    const sid = li.dataset.sid, e = estadoAoVivo(sid);
    li.querySelector('.vivo').textContent = [e.recente ? '● ' + tituloAgente(e.recente.agente) : '', e.edicoes ? '✎' + e.edicoes : '', e.falha ? '✖' : '', e.circ.length ? '🔁' : ''].filter(Boolean).join(' ');
    li.style.setProperty('--anel', e.recente ? corAgente(e.recente.agente) : 'transparent');
    li.setAttribute('aria-label', textoNo(sid, e));
  });
  if (selecionado && !fichaEl.hidden) desenharFicha();
}
function desenharLista() {
  const idx = dados.index, sis = idx.sistemas || {}, caixa = el('div', 'arq-lista');
  const ordem = ordemCamadas(idx.camadas);
  const grupos = [...ordem, ''].map((c) => [c, Object.keys(sis).filter((sid) => (c ? sis[sid].camada === c : !ordem.includes(sis[sid].camada)))
    .sort((a, b) => nomeDe(a).localeCompare(nomeDe(b), 'pt-BR'))]).filter(([, l]) => l.length);
  for (const [camada, lista] of grupos) {
    const sec = el('section', 'arq-grupo');
    const h = el('h4', null, (camada || 'sem camada') + ' · ' + lista.length);
    const cor = camada && idx.camadas[camada] ? idx.camadas[camada].cor : '#94a3b8'; h.style.borderLeftColor = cor;
    sec.append(h);
    const ul = el('ul');
    for (const sid of lista) {
      const s = sis[sid], li = el('li', 'arq-linha' + (s.status === 'deprecated' ? ' deprecated' : '')), b = el('button');
      li.dataset.sid = sid; b.type = 'button';
      const ponto = el('i', 'ponto'); ponto.style.background = s.cor || cor;
      b.append(ponto, el('span', 'nome', s.nome || curto(sid)), el('span', 'arqs', (s.arquivos || 0) + ' arq.'), el('span', 'vivo'));
      b.addEventListener('click', () => abrirSistema(sid));
      li.append(b); ul.append(li);
    }
    sec.append(ul); caixa.append(sec);
  }
  return caixa;
}
function usarLista() { return modoLista != null ? modoLista : document.documentElement.classList.contains('compacto'); }
function desenharInfo() {
  const d = dados || {}, dr = d.drift || {}, v = d.validacao || {};
  const partes = [];
  if (d.ref) partes.push(d.ref + (d.commit ? ' @' + String(d.commit).slice(0, 7) : ''));
  if (d.ts) partes.push('atualizado ' + hhmm(d.ts * 1000));
  if (dr.arquivos_cobertos != null) partes.push(`${dr.arquivos_cobertos} arquivos (${dr.pct_com_dono}% com dono)`);
  if (dr.arestas_nao_declaradas != null) partes.push(`${dr.arestas_nao_declaradas} import(s) não declarado(s)`);
  if (dr.ciclos_reais) partes.push(`${dr.ciclos_reais} ciclo(s)`);
  if (dr.camadas_violadas_reais) partes.push(`${dr.camadas_violadas_reais} camada(s) violada(s)`);
  if (v.n_erros != null) partes.push(`validate: ${v.n_erros} erro(s), ${v.n_avisos} aviso(s)`);
  if (d.atualizando) partes.push('atualizando…');
  infoEl.textContent = partes.join(' · ') || (carregando ? 'carregando…' : '');
}
function desenhar() {
  if (painel.hidden) return;
  desenharInfo();
  const g0 = corpoEl.querySelector('.arq-grafo'), rolagem = { y: corpoEl.scrollTop, gx: g0 ? g0.scrollLeft : 0, gy: g0 ? g0.scrollTop : 0 };
  corpoEl.textContent = '';
  if (erro && !(dados && dados.sem_grafo && !dados.index)) { const p = el('p', 'arq-aviso', '⚠️ ' + erro + (dados && dados.index ? ' — mostrando o último grafo gerado.' : '')); p.setAttribute('role', 'status'); corpoEl.append(p); }
  if (!dados || !dados.index) {
    if (dados && dados.ativo === false) {
      corpoEl.append(el('p', 'arq-msg', 'Painel desligado ("grafo": {"ativo": false} no config.json).'));
    } else if (dados && dados.sem_grafo) {   // o projeto ainda não tem grafo: como criar um
      const box = el('div', 'arq-msg');
      box.append(el('p', null, 'Este projeto ainda não tem um grafo de arquitetura. Para criar um:'));
      const pre = el('pre', 'arq-cmd', 'python grafo/grafo.py init --raiz <pasta do projeto> --saida docs/ARCHITECTURE_GRAPH.yaml\n'
        + 'python grafo/grafo.py validate --raiz <pasta do projeto>');
      box.append(pre, el('p', null, 'Revise nomes, camadas e descrições, faça commit e push para a ref do config.json (grafo.ref, padrão '
        + 'origin/main). O painel atualiza na próxima rodada (grafo.intervalo_min). Veja "Grafo de arquitetura" no INSTALACAO.md.'));
      corpoEl.append(box);
    } else {
      corpoEl.append(el('p', 'arq-msg', carregando ? 'carregando o grafo…' : 'O grafo ainda não foi gerado (o servidor gera na partida e a cada grafo.intervalo_min).'));
    }
    btnModo.hidden = true; fichaEl.hidden = true; return;
  }
  btnModo.hidden = false;
  const lista = usarLista();
  btnModo.textContent = lista ? '🕸️ Grafo' : '☰ Lista'; btnModo.setAttribute('aria-pressed', String(lista));
  nos = new Map();
  corpoEl.append(lista ? desenharLista() : desenharGrafo(), legenda());
  corpoEl.scrollTop = rolagem.y;   // redesenho (dados novos, troca de modo) mantém a rolagem
  const g1 = corpoEl.querySelector('.arq-grafo'); if (g1) { g1.scrollLeft = rolagem.gx; g1.scrollTop = rolagem.gy; }
  atualizarAoVivo();
}
function legenda() {
  const idx = dados.index, d = el('div', 'arq-legenda');
  for (const c of ordemCamadas(idx.camadas)) { const s = el('span'), i = el('i'); i.style.background = idx.camadas[c].cor; s.append(i, document.createTextNode(c)); d.append(s); }
  for (const [cls, txt] of [['l-decl', 'depende (declarado)'], ['l-real', 'import real não declarado / camada violada'], ['l-ciclo', 'ciclo real'],
    ['l-vivo', 'anel: agente que mexeu nos últimos 10 min'], ['l-calor', '✎ edições hoje · ✖ comando falhou · 🔁 em círculos']]) {
    d.append(el('span', cls, txt));
  }
  return d;
}
let timerDesenho = null;
function agendarDesenho() {   // eventos em rajada: no máximo 1 atualização por segundo, só com o painel aberto
  if (painel.hidden || timerDesenho) return;
  timerDesenho = setTimeout(() => { timerDesenho = null; if (!painel.hidden) atualizarAoVivo(); }, 1000);
}

// ---------------------------------------------------------------- ficha do sistema
function chips(lista, vazio) {
  const d = el('div', 'arq-chips');
  if (!lista.length) d.append(el('span', 'dim', vazio));
  for (const sid of lista) {
    const b = el('button', 'chip', nomeDe(sid)); b.type = 'button'; b.title = sid;
    const cor = (sistemas()[sid] || {}).cor; if (cor) b.style.setProperty('--cor', cor);
    b.addEventListener('click', () => abrirSistema(sid));
    d.append(b);
  }
  return d;
}
function secao(titulo, ...filhos) { const s = el('section', 'arq-sec'); s.append(el('h5', null, titulo), ...filhos); return s; }
function desenharFicha() {
  const idx = dados && dados.index, s = idx && idx.sistemas[selecionado];
  if (!s) { fichaEl.hidden = true; return; }
  fichaEl.hidden = false; fichaEl.textContent = '';
  const topo = el('header');
  const h = el('h4', null, s.nome || curto(selecionado)); h.style.borderLeftColor = s.cor || '#94a3b8';
  const fechar = el('button', 'arq-fechar-ficha', '×'); fechar.type = 'button'; fechar.title = 'Fechar a ficha do sistema'; fechar.setAttribute('aria-label', 'Fechar a ficha do sistema');
  fechar.addEventListener('click', () => { selecionado = ''; fichaEl.hidden = true; nos.forEach((n) => n.g.classList.remove('sel')); });
  topo.append(h, fechar);
  fichaEl.append(topo, el('div', 'dim', `${selecionado} · camada ${s.camada || '?'} · ${s.status || 'sem status'}`));
  if (s.resumo) fichaEl.append(el('p', null, s.resumo));
  const e = estadoAoVivo(selecionado), h2 = hoje.sistemas.get(selecionado);
  const vivo = el('div', 'arq-vivo');
  if (e.recente) vivo.append(el('div', null, `● agora: ${tituloAgente(e.recente.agente)} ${e.recente.leitura ? 'leu' : 'mexeu'} às ${hhmm(e.recente.ms)}`));
  if (e.falha) vivo.append(el('div', 'falha', `✖ comando falhou às ${hhmm(e.falha.ms)}${e.falha.codigo != null ? ' (exit ' + Number(e.falha.codigo) + ')' : ''} — ${tituloAgente(e.falha.agente)}: ${e.falha.cmd}`));
  for (const c of e.circ) vivo.append(el('div', 'circ', `🔁 ${tituloAgente(c.agente)} em círculos em ${c.arquivo}`));
  if (vivo.childNodes.length) fichaEl.append(vivo);
  const quem = el('ul', 'arq-quem');
  if (h2) [...h2.porAgente.entries()].sort((a, b) => b[1].n - a[1].n).forEach(([nome, x]) => {
    const li = el('li'); const i = el('i'); i.style.background = corAgente(nome);
    li.append(i, document.createTextNode(`${tituloAgente(nome)}: ${x.n} edição(ões), última às ${hhmm(x.ms)}`)); quem.append(li);
  });
  fichaEl.append(secao('Quem mexeu hoje', h2 ? quem : el('p', 'dim', hoje.carregado ? 'Ninguém editou hoje.' : 'carregando os eventos de hoje…')));
  const arqs = Object.entries(idx.arquivos || {}).filter(([, sid]) => sid === selecionado).map(([f]) => f).sort();
  const ul = el('ul', 'arq-arqs'); arqs.slice(0, 8).forEach((f) => ul.append(el('li', null, f)));
  if (arqs.length > 8) ul.append(el('li', 'dim', `+${arqs.length - 8} arquivo(s)`));
  fichaEl.append(secao(`Arquivos · ${s.arquivos || arqs.length}`, arqs.length ? ul : el('p', 'dim', (s.paths || []).join(', ') || 'nenhum')));
  fichaEl.append(secao('Depende de', chips(s.depends_on || [], 'nada')), secao('Usado por', chips(s.usado_por || [], 'ninguém')));
  const reais = ((idx.arestas && idx.arestas.reais) || []).filter((r) => r.tipo === 'nao_declarada' && (r.de === selecionado || r.para === selecionado));
  if (reais.length) {
    const u = el('ul', 'arq-reais');
    reais.forEach((r) => u.append(el('li', null, `${nomeDe(r.de)} → ${nomeDe(r.para)} (${r.refs} ref.; ex.: ${r.exemplo})`)));
    fichaEl.append(secao('Imports reais não declarados', u));
  }
  const probl = problemas().erros.filter((x) => x.de === selecionado || x.para === selecionado || (x.sistemas || []).includes(selecionado));
  if (probl.length) { const u = el('ul', 'arq-probl'); probl.slice(0, 6).forEach((x) => u.append(el('li', null, x.msg))); fichaEl.append(secao('⚠️ Problemas no validate', u)); }
  const evs = [...(s.eventos_produz || []).map((x) => '→ ' + x), ...(s.eventos_consome || []).map((x) => '← ' + x)];
  if (evs.length) { const u = el('ul'); evs.forEach((x) => u.append(el('li', null, x))); fichaEl.append(secao('Eventos (→ produz, ← consome)', u)); }
  const tes = (s.testes || []).map((t) => t + (idx.testes && idx.testes[t] && idx.testes[t].command ? ' — ' + idx.testes[t].command : ''));
  if (s.test_cmd) tes.unshift('test_cmd: ' + s.test_cmd);
  if (tes.length) { const u = el('ul', 'arq-testes'); tes.forEach((x) => u.append(el('li', null, x))); fichaEl.append(secao('Testes', u)); }
  const adrs = (s.adrs || []).map((a) => a + (idx.adrs && idx.adrs[a] ? ' — ' + idx.adrs[a].title : ''));
  if (adrs.length) { const u = el('ul'); adrs.forEach((x) => u.append(el('li', null, x))); fichaEl.append(secao('ADRs', u)); }
}
function abrirSistema(sid) {
  selecionado = sid;
  nos.forEach((n, k) => n.g.classList.toggle('sel', k === sid));
  desenharFicha();
  fichaEl.scrollTop = 0;
  if (usarLista()) fichaEl.scrollIntoView({ block: 'start' });
}

// ---------------------------------------------------------------- abrir / fechar
function agendar() {
  clearInterval(timerAberto); timerAberto = null;
  if (!painel.hidden) timerAberto = setInterval(() => {
    if (painel.hidden || document.hidden) return;
    if (Date.now() - carregadoEm > ATUALIZAR_ABERTO_MS) carregar(); else atualizarAoVivo();   // expira o anel de 10 min
  }, 30000);
}
function abrir() {
  painel.hidden = false; botao.setAttribute('aria-expanded', 'true');
  desenhar(); agendar(); carregarHoje();
  if (!dados || Date.now() - carregadoEm > ATUALIZAR_ABERTO_MS) carregar();
}
function fechar() { painel.hidden = true; botao.setAttribute('aria-expanded', 'false'); agendar(); }

if (botao && painel && temServidor && !(CONFIG.grafo && CONFIG.grafo.ativo === false)) {   // sem servidor ou desligado: botão escondido
  zerarDia();
  botao.hidden = false;
  botao.setAttribute('aria-controls', 'arquitetura'); botao.setAttribute('aria-expanded', 'false');
  botao.addEventListener('click', () => (painel.hidden ? abrir() : fechar()));
  $('arqFechar').addEventListener('click', fechar);
  btnModo.addEventListener('click', () => { modoLista = !usarLista(); desenhar(); });
  window.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape' || painel.hidden) return;
    if (selecionado && !fichaEl.hidden) { selecionado = ''; fichaEl.hidden = true; nos.forEach((n) => n.g.classList.remove('sel')); return; }   // 1º Esc fecha a ficha
    fechar();
  });
  window.addEventListener('office-evento', (e) => registrar(e.detail, true));
  window.addEventListener('office-saude', (e) => receberSaude(e.detail));
  document.addEventListener('visibilitychange', () => { if (!document.hidden && Date.now() - carregadoEm > ATUALIZAR_GRAFO_MS) carregar(); });
  setTimeout(carregar, 3000);   // o mapa arquivo → sistema serve à ficha do agente mesmo com o painel fechado
  setInterval(() => { if (!document.hidden && painel.hidden && Date.now() - carregadoEm > ATUALIZAR_GRAFO_MS) carregar(); }, 60000);
  window.__arquitetura = { carregar, sistemaDe, nomeDe, normalizarArquivo, get dados() { return dados; }, abrirSistema: (sid) => { if (painel.hidden) abrir(); abrirSistema(sid); } };
}
