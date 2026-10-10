// Claude Office 3D — Placar do time: XP e nível dos agentes (GET /xp), painel, rótulos nas mesas e comemoração.
// Sem ranking competitivo: só nome ou nível como ordem, sem medalhas. Se /xp não existir, usa uma demonstração.

import { CONFIG } from './config.js';
import { dica } from './dica.js';
import { instalarIndicadores } from './indicadores_providers.mjs';
import { seletorProjetos } from './kanban_projetos.mjs';

const ATUALIZAR_MS = 60000;
const CHAVE_NIVEIS = 'office.xp.niveis', CHAVE_ORDEM = 'office.placar.ordem', CHAVE_PRS = 'office.xp.prs';
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
let revisaoBusca=0;
const selecaoXP=seletorProjetos(infoEl,()=>{
  real=null;injetado=false;historico=[];toastEl.hidden=true;custos=null;uso=null;
  aplicar({agentes:{},time:{}},{fonte:'real'});buscar();
},{endpoint:'/xp',nome:'Projeto do Placar'});
window.addEventListener('office-projeto-alerta',e=>{
  if(e.detail?.painel==='placar')selecaoXP.selecionar(e.detail.projeto);
});
let injetado = false;     // __placar.aplicar() manual: não deixa a demonstração sobrescrever
let demo = null;          // placar falso
let atual = null;         // dados normalizados em exibição
let fonte = '';           // 'real' | 'demo' | 'injetado'
let ordem = lerLS(CHAVE_ORDEM, 'nome') === 'nivel' ? 'nivel' : 'nome';
let visto = null;         // níveis vistos em memória (demonstração)
let vistoPrs = null;      // PRs pontuados vistos em memória (demonstração): merge novo = festa curta no escritório

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
  const regras = obj.regras && typeof obj.regras === 'object' ? obj.regras : null;   // xp.py: pesos, desde, janela, amostra (ⓘ)
  return { atualizado: obj.atualizado || '', repo: String(obj.repo || ''), niveis, regras, time: obj.time || {}, agentes,
    projeto_id:obj.projeto_id||'',fonte:obj.fonte||'',erro:obj.erro||'',
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
  else { try { anteriores = JSON.parse(lerLS(CHAVE_NIVEIS+(dados.projeto_id?'.'+dados.projeto_id:''), 'null')); } catch (e) { anteriores = null; } }
  let prsAntes = null;
  if (novaFonte === 'demo') prsAntes = novaFonte !== fonte ? null : vistoPrs;
  else { try { prsAntes = JSON.parse(lerLS(CHAVE_PRS+(dados.projeto_id?'.'+dados.projeto_id:''), 'null')); } catch (e) { prsAntes = null; } }
  const pausado = !!(o && o.emReplay && o.emReplay());   // replay aberto: não comemora nem grava como visto; a festa fica para depois
  const novos = {}, subiram = [], prsNovos = {}, mergeados = [];
  for (const [nome, d] of Object.entries(dados.agentes)) {
    novos[nome] = d.nivel;
    const subiu = !pausado && anteriores && typeof anteriores[nome] === 'number' && d.nivel > anteriores[nome];
    if (subiu) subiram.push([nome, d.titulo_nivel]);
    const n = Number(d.prs) || 0; prsNovos[nome] = n;
    // PR novo pontuado (merge atribuído a ele): festa curta; quem também subiu de nível fica só com a festa grande
    if (!pausado && !subiu && prsAntes && typeof prsAntes[nome] === 'number' && n > prsAntes[nome]) mergeados.push([nome, (d.ultimos || []).find((u) => u && u.pr) || null, n - prsAntes[nome]]);
  }
  if (!pausado) {
    if (novaFonte === 'demo') vistoPrs = prsNovos; else gravarLS(CHAVE_PRS+(dados.projeto_id?'.'+dados.projeto_id:''), JSON.stringify({ ...(prsAntes || {}), ...prsNovos }));
    if (novaFonte === 'demo') visto = novos; else gravarLS(CHAVE_NIVEIS+(dados.projeto_id?'.'+dados.projeto_id:''), JSON.stringify({ ...(anteriores || {}), ...novos }));
  }
  fonte = novaFonte; atual = dados;
  if (o) {
    for (const a of o.agentes.values()) {
      const d = dados.agentes[a.nome];
      o.xpDefinir(a.nome, d ? { nivel: d.nivel, titulo: d.titulo_nivel, xp: d.xp, xp_base: d.xp_base, xp_proximo: d.xp_proximo } : null);
    }
    subiram.forEach(([nome, titulo], i) => setTimeout(() => o.comemorar(nome, titulo), i * 700));
    if (o.merge) mergeados.forEach(([nome, u, n], i) => setTimeout(() => o.merge(nome, u && u.pr, u && u.pontos, n), (subiram.length + i) * 700));
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
const NL = String.fromCharCode(10);
// Como cada número do Placar é calculado (ⓘ de cada tile). Fontes: xp.py, custo_time.py, statusline_uso.py e banco.uso_resumo;
// ao mudar a regra num desses arquivos, ajuste o texto aqui. Pesos, data inicial, janela e amostra vêm do próprio placar.json
// (bloco "regras" que o xp.py grava a partir do config.json); o check de revisão vem de github.check_revisao.
const sinal = (v) => (Number(v) > 0 ? '+' : Number(v) < 0 ? '−' : '') + Math.abs(Number(v) || 0);
const dataBr = (iso) => (/^\d{4}-\d{2}-\d{2}/.test(String(iso || '')) ? String(iso).slice(0, 10).split('-').reverse().join('/') : '');
function descricoes(r) {
  const P = r || {}, tem = (k) => typeof P[k] === 'number';
  const J = Number(P.janela_retrabalho_dias) || 14;
  const desde = dataBr(P.desde);
  const check = CONFIG.github && CONFIG.github.check_revisao;
  const revisao = check ? `o check de revisão configurado (github.check_revisao: "${check}")` : 'a revisão (sem github.check_revisao, as reviews do PR)';
  const reprovado = check ? `reprovado pelo check de revisão configurado ("${check}")` : 'reprovado na revisão (alguma review pediu mudanças)';
  const reprovou = check ? `"${check}" em falha, erro, tempo esgotado ou cancelado em algum commit` : 'alguma review pediu mudanças';
  const pesos = ['aprovado_de_primeira', 'sem_conflito_com_testes', 'cartao_fechado', 'bug_nao_voltou_14d', 'retrabalho', 'regressao'].every(tem)
    ? `${sinal(P.aprovado_de_primeira)} aprovado de primeira, ${sinal(P.sem_conflito_com_testes)} sem merge da base no meio e com testes citados no corpo, `
      + `${sinal(P.cartao_fechado)} cartão na coluna final do Kanban, ${sinal(P.bug_nao_voltou_14d)} fix sem bug de volta em ${J} dias, `
      + `${sinal(P.retrabalho)} retrabalho, ${sinal(P.regressao)} regressão`
    : 'os pesos de xp.pesos do config.json (aprovado de primeira, testes citados, cartão fechado, fix que não voltou, retrabalho, regressão)';
  const skills = tem('skill_reusada_por_outro') && tem('skill_promovida')
    ? `Skills: ${sinal(P.skill_reusada_por_outro)} por reuso por outro agente, ${sinal(P.skill_promovida)} se promovida. `
    : 'Skills: pontos por reuso por outro agente e por skill promovida (xp.pesos). ';
  const amostra = Number(P.amostra_1_em);
  return {
    xp: `Soma do XP dos agentes. Os PRs mergeados ${desde ? 'desde ' + desde : 'desde xp.desde ou, sem ela, nos últimos 30 dias'} (até os 300 mais recentes) `
      + 'vão para um agente (cartão fechado pelo PR, Closes #n, #número citado no título, branch ou corpo, rótulo de github.times, prefixo de branch '
      + 'de xp.atribuicao ou o agente padrão; PR que não cai em nenhum agente não pontua) e cada um pontua: ' + pesos + '. ' + skills
      + 'PR na auditoria (vermelho) vale 0; o XP de um agente não fica abaixo de 0. (xp.py)',
    primeira: `PRs pontuados em que ${revisao} não reprovou nenhum commit, divididos pelo total de PRs pontuados. Reprovado = ${reprovou}. (xp.py)`,
    retrabalho: `Fração dos PRs pontuados com retrabalho: ${reprovado}, ou um PR posterior de fix, revert ou regressão citou o número `
      + `dele em até ${J} dias depois do merge. PR zerado pela auditoria entra na conta como sem retrabalho. (xp.py)`,
    auditorias: 'PRs na faixa vermelha ainda não liberados: skip/xfail incondicional em teste, teste apagado sem substituto equivalente ou mudança em '
      + 'arquivo de avaliação (xp.padroes_avaliacao). Os pontos do PR ficam zerados até alguém liberar (botão Liberar, só no PC, ou python xp.py --liberar N). (xp.py)',
    conferir: 'PRs na faixa amarela ainda não conferidos: skip condicional em teste, consolidação de testes, teste enfraquecido (menos asserções '
      + 'acrescentadas que removidas)' + (!tem('amostra_1_em') ? ' ou a amostra aleatória de xp.amostra_1_em' : amostra > 0 ? ` ou amostra aleatória de 1 em ${amostra} PRs` : '')
      + '. Os pontos contam normalmente. Com o auditor automático ligado (auditor.ativo, auditor_xp.py), ele marca como conferido o que for legítimo '
      + 'e, quando confirma a suspeita, abre uma issue para o time do autor e também tira da lista. (xp.py)',
    uso5h: 'Percentual já usado da janela de 5 horas do plano, na última leitura gravada pela statusline do Claude Code (rate_limits.five_hour). '
      + 'Some quando a janela já reiniciou. Amarelo a partir de 70%, vermelho a partir de 90%. (statusline_uso.py, banco.uso_resumo)',
    usoSemana: 'Percentual já usado do limite semanal do plano, na última leitura gravada pela statusline do Claude Code (rate_limits.seven_day). '
      + 'Some quando a semana já reiniciou. Amarelo a partir de 70%, vermelho a partir de 90%. (statusline_uso.py, banco.uso_resumo)',
    hoje: 'Pontos percentuais do limite semanal gastos hoje (dia local): soma das subidas do % semanal entre uma leitura e a seguinte; '
      + 'a queda do reset é ignorada. (banco.uso_resumo)',
    projecao: '% semanal de agora + ritmo × dias que faltam até o reset. Ritmo = quanto o % semanal subiu entre a primeira e a última leitura '
      + 'das últimas 24 h, por dia. Amarelo a partir de 85%; 100% ou mais = o limite acaba antes do reset. (banco.uso_resumo)',
    porPr: 'Custo do time na janela (sessões do Claude Code nos transcritos locais das pastas em "projetos" do config.json, rateadas por resposta, '
      + 'mais o revisor de código) dividido pelos PRs mergeados no GitHub no mesmo período (entre os 100 PRs fechados mais recentes). '
      + 'Sessão ainda aberta é estimada pelos tokens. Recalculado quando tem mais de 1 h. (custo_time.py)',
    acumulado: 'Soma do custo de todas as sessões e revisões já vistas, guardada no banco local dados/escritorio.db. Não cai quando a janela '
      + 'anda nem quando o Claude Code apaga transcritos velhos (só ajusta um pouco quando a estimativa da sessão aberta vira o custo real). '
      + '"desde" = data da sessão mais antiga registrada. (custo_time.py, banco.acumulado)',
    revisor: 'Custo das revisões do revisor de código (revisor_ia.py, [revisor-ia]) na janela, pelo custo que cada revisão grava em '
      + 'dados/revisor/estado.json. Já está somado no custo por PR. (custo_time.py)',
  };
}
function tile(valor, rotulo, cor, alerta, desc, extra) {   // alerta: true (vermelho) ou 'amarelo'; desc: texto do ⓘ; extra: números do momento
  const t = el('div', 'tile' + (alerta === 'amarelo' ? ' aviso' : alerta ? ' alerta' : '')); if (cor && !alerta) t.style.borderTopColor = cor;
  t.append(el('b', String(valor).length > 9 ? 'longo' : null, valor), el('span', null, rotulo));   // longo: US$ 1279,04 cabe sem cobrir o ⓘ
  if (desc) t.append(dica(desc + (extra ? NL + NL + extra : ''), rotulo));
  return t;
}
function nomeExibido(nome) { const a = office() && office().agentes.get(nome); return a ? a.titulo : String(nome).replace(/_/g, ' '); }
function corDe(nome) { const a = office() && office().agentes.get(nome); return a ? '#' + a.cor.toString(16).padStart(6, '0') : '#64748b'; }
// Listas das duas faixas: 🔴 auditoria (pontos zerados) e 🟡 para conferir (pontos normais), com link do PR e os botões para resolver
const faixasEl = el('div'); faixasEl.id = 'placarFaixas'; $('placarOrdem').before(faixasEl);
const legendaEl = el('span', 'legenda'); $('placarOrdem').append(legendaEl);   // ⓘ: como ler o cartão de cada agente
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
const ROTULO_HIST = { tratar: 'tratou sugestão do bot em', conferido: 'conferiu', liberar: 'liberou os pontos de', desfazer: 'desfez', parear: 'pareou o aparelho', revogar: 'revogou',
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
async function carregarHistorico() { if(real?.fonte==='gestao'){historico=[];return;}const j = await pegarJson('/api/acoes'); if(real?.fonte!=='gestao' && j && Array.isArray(j.acoes)) historico = j.acoes; if (!painel.hidden && atual) desenharFaixas(); }
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
  const escopo=real;
  const rotulo = botao ? botao.textContent : '';
  if (botao) { botao.disabled = true; botao.textContent = 'salvando…'; }
  try {
    const cab = { 'Content-Type': 'application/json', 'X-Office-Acao': '1' };
    if (sessao && sessao.csrf) cab['X-Office-Csrf'] = sessao.csrf;
    const payload={pr};if(escopo?.fonte==='gestao'){payload.projeto_id=escopo.projeto_id;payload.versao=escopo.politica_versao;}
    const r = await fetch('/api/xp/' + tipo, { method: 'POST', headers: cab, body: JSON.stringify(payload) });
    let j = null; try { j = await r.json(); } catch (e) { /* corpo vazio */ }
    if (!r.ok || !j || !j.ok) throw new Error((j && j.erro) || 'HTTP ' + r.status);
    if(real!==escopo)return;
    normalizar(j.placar);
    real = j.placar; decidir();   // aplica o placar novo sem recarregar a página
    toast('PR #' + pr + ' ' + TEXTO_ACAO[tipo], tipo === 'desfazer' ? 0 : pr);
    carregarHistorico();
  } catch (e) {
    if(real!==escopo)return;
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
let custos = null, uso = null;
const DIAS_SEM = ['dom', 'seg', 'ter', 'qua', 'qui', 'sex', 'sáb'];
function quando(epoch) {
  if (!epoch) return '';
  const d = new Date(epoch * 1000), hoje = new Date();
  const hm = d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
  return d.toDateString() === hoje.toDateString() ? hm : `${DIAS_SEM[d.getDay()]} ${hm}`;
}
// Uso do plano (rate_limits do Claude Code, gravado pela statusline): 5 h, semana, consumo de hoje e projeção no reset.
function tilesUso(u, DESC) {
  const out = [];
  if (!u) return out;
  const nivel = (p) => (p >= 90 ? true : p >= 70 ? 'amarelo' : false);
  if (u.five_pct != null) {
    out.push(tile(Math.round(u.five_pct) + '%', `uso em 5 h · reinicia ${quando(u.five_reset)}`, '#ec4899', nivel(u.five_pct), DESC.uso5h));
  }
  if (u.seven_pct != null) {
    out.push(tile(Math.round(u.seven_pct) + '%', `uso na semana · reinicia ${quando(u.seven_reset)}`, '#ec4899', nivel(u.seven_pct), DESC.usoSemana));
  }
  const dias = u.por_dia || [];
  if (dias.length) {
    const n = new Date(), hoje = `${n.getFullYear()}-${String(n.getMonth() + 1).padStart(2, '0')}-${String(n.getDate()).padStart(2, '0')}`;
    const h = dias.find((d) => d.dia === hoje);   // data local, como o banco.py agrupa
    const extra = 'Por dia:' + NL
      + dias.map((d) => `${d.dia.split('-').reverse().slice(0, 2).join('/')}: ${d.pontos.toFixed(1).replace('.', ',')}`).join(NL)
      + (u.ritmo_dia != null ? `${NL}Ritmo das últimas 24 h: ${u.ritmo_dia.toFixed(1).replace('.', ',')} pts/dia` : '');
    out.push(tile((h ? h.pontos : 0).toFixed(1).replace('.', ',') + ' pts', 'da semana gastos hoje', '#ec4899', false, DESC.hoje, extra));
  }
  if (u.projecao_reset != null) {
    const p = u.projecao_reset;
    out.push(tile('~' + Math.round(p) + '%', 'no reset, no ritmo atual', '#ec4899', p >= 100 ? true : p >= 85 ? 'amarelo' : false, DESC.projecao,
      p >= 100 ? 'No ritmo das últimas 24 h o limite semanal acaba antes do reset: reduza (modelo menor nos subagentes, menos releitura de contexto).' : ''));
  }
  return out;
}
const usd = (v) => 'US$ ' + Number(v || 0).toFixed(2).replace('.', ',');
function desenhar() {
  const o = office(); if (!atual) return;
  const cn = (n) => (o ? o.CORES_NIVEL : ['#9ca3af'])[Math.max(0, Math.min(4, n - 1))] || '#9ca3af';
  const t = atual.time;
  timeEl.textContent = '';
  const aud = Number(t.auditorias_abertas) || 0, conf = Number(t.conferir_abertos) || 0;
  const DESC = descricoes(atual.regras), J = Number(atual.regras && atual.regras.janela_retrabalho_dias) || 14;
  const nPrs = t.prs_pontuados != null ? `Agora: ${t.prs_pontuados} PR(s) pontuado(s).` : '';
  timeEl.append(tile(String(t.xp_total ?? 0), 'XP total do time', '#f59e0b', false, DESC.xp, nPrs),
    tile(pct(t.aprovacao_primeira), 'aprovado de primeira', '#22c55e', false, DESC.primeira, nPrs),
    tile(pct(t.retrabalho_14d), `retrabalho em ${J} dias`, '#3b82f6', false, DESC.retrabalho, nPrs),
    tile(String(aud), 'auditorias abertas', '#22c55e', aud > 0, DESC.auditorias),
    tile(String(conf), 'para conferir', '#22c55e', conf > 0 ? 'amarelo' : false, DESC.conferir));
  if (fonte === 'real') timeEl.append(...tilesUso(uso, DESC));
  const c = fonte === 'real' && custos;
  if (c && c.usd_por_pr != null) {
    timeEl.append(tile(usd(c.usd_por_pr), `por PR mergeado (${c.dias} d)`, '#a855f7', false, DESC.porPr,
      `Agora: ${usd(c.total_usd)} em ${c.dias} dia(s), ${c.prs_mergeados} PR(s) mergeado(s) · calculado em ${c.gerado}.`));
  }
  if (c && c.acumulado_usd != null) {
    // A janela de 7 dias anda (o custo "cai" quando sessões velhas saem); o acumulado vem do banco local e só cresce.
    timeEl.append(tile(usd(c.acumulado_usd), `acumulado desde ${(c.acumulado_desde || '').split('-').reverse().join('/')}`, '#a855f7', false, DESC.acumulado,
      `Agora: ${usd(c.total_usd)} nos últimos ${c.dias} dia(s)` + (c.sessoes_ao_vivo ? `, com ${c.sessoes_ao_vivo} sessão(ões) aberta(s) estimada(s) pelos tokens` : '') + '.'));
  }
  if (c && c.revisor && c.revisor.revisoes) {
    timeEl.append(tile(usd(c.revisor.usd), `revisor de código (${c.dias} d)`, '#0ea5e9', false, DESC.revisor,
      `Agora: ${c.revisor.revisoes} revisão(ões), ${c.revisor.achados} achado(s).`));
  }
  desenharFaixas();
  document.querySelectorAll('#placarOrdem button[data-ordem]').forEach((b) => {
    b.classList.toggle('ativo', b.dataset.ordem === ordem); b.setAttribute('aria-pressed', String(b.dataset.ordem === ordem));
  });
  const niveis = (atual.niveis || NIVEIS_PADRAO).map((x) => `${x.titulo} ${x.xp}`).join(', ');
  legendaEl.replaceChildren(dica('Cada cartão é um agente. Estrelas e título = nível pelo XP (' + niveis + ' XP; xp.niveis); a barra mostra o caminho até o próximo nível. '
    + '"XP · PR(s)" = XP do agente e PRs mergeados atribuídos a ele (xp.py). '
    + (c && c.agentes ? `US$ = custo do agente nos últimos ${c.dias} dia(s): respostas dele (líder ou colega/subagente) nos transcritos locais (custo_time.py). ` : '')
    + 'Embaixo, os últimos pontos por PR e o primeiro motivo. ⚠ = auditorias abertas, ● = para conferir. Toque no cartão para abrir a ficha de XP.', 'cartões dos agentes'));
  const ags = Object.entries(atual.agentes);
  ags.sort((a, b) => (ordem === 'nivel' ? b[1].nivel - a[1].nivel || b[1].xp - a[1].xp : 0) || nomeExibido(a[0]).localeCompare(nomeExibido(b[0]), 'pt-BR'));
  listaEl.textContent = '';
  if (!ags.length) listaEl.append(el('li', 'vazio', 'Nenhum agente pontuado ainda.'));
  for (const [nome, d] of ags) {
    const li = el('li', 'ag'); li.style.borderLeftColor = corDe(nome); li.title = nome;
    li.tabIndex = 0; li.setAttribute('role', 'button'); li.setAttribute('aria-label', nomeExibido(nome) + ': ' + d.titulo_nivel + ', ' + d.xp + ' XP. Abrir a ficha de XP');
    const topo = el('div', 'topo'), nm = el('span', 'nome', nomeExibido(nome)); nm.style.color = corDe(nome);
    const nv = el('span', 'nivel'); nv.style.color = cn(d.nivel);
    nv.append(el('span', null, '★'.repeat(Math.min(5, d.nivel))), el('span', 'vazia', '☆'.repeat(Math.max(0, 5 - d.nivel))), document.createTextNode(' ' + d.titulo_nivel));
    topo.append(nm, nv);
    if (d.auditoria.length) topo.append(el('span', 'aud', '⚠ ' + d.auditoria.length + ' auditoria(s)'));
    if (d.conferir.length) topo.append(el('span', 'conf', '● ' + d.conferir.length + ' para conferir'));
    topo.append(el('span', 'xp', d.xp + ' XP · ' + (d.prs || 0) + ' PR(s)'));
    const gasto = c && c.agentes ? c.agentes[nome] : null;
    if (gasto != null) { const g = el('span', 'xp', usd(gasto)); g.title = `custo nos últimos ${c.dias} dia(s)`; topo.append(g); }
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
    li.addEventListener('keydown', (e) => { if ((e.key === 'Enter' || e.key === ' ') && e.target === li) { e.preventDefault(); if (o) o.ficha(nome, 'xp'); } });
    listaEl.append(li);
  }
  const hora = atual.atualizado ? new Date(atual.atualizado).toLocaleTimeString('pt-BR') : '';
  if(real?.fonte==='gestao' && real.auditor?.ativo){
    const det=el('details'),rs=Array.isArray(real.auditor.pareceres)?real.auditor.pareceres:[];
    det.append(el('summary',null,'Auditor independente · pareceres consultivos'));
    det.append(el('p',null,real.auditor.erro||real.auditor.limite||'Não autoriza merge ou liberação de XP.'));
    for(const r of rs){
      det.append(el('p',null,`PR #${r.pr} · ${r.estado} · ${r.veredito} · commit ${r.sha||'desconhecido'} · ${r.quando||''}`));
      for(const p of Array.isArray(r.pareceres)?r.pareceres:[]){
        det.append(el('p',null,`${p.nome} (${p.cloud_declarada}, declarada): ${p.resposta?.motivo||''} ${p.resposta?.evidencia||''}`));
      }
    }
    listaEl.append(det);
  }
  infoEl.textContent = fonte === 'demo'
    ? (real === null ? '⚠️ placar indisponível — mostrando uma demonstração' : 'modo demonstração — pontos de mentira') + (hora ? ' · ' + hora : '')
    : (atual.erro || 'atualizado às ' + hora) + (fonte === 'injetado' ? ' · dados injetados' : '');
}
function abrir() {
  ['prs', 'kanban'].forEach((id) => { const e = $(id); if (e) e.hidden = true; });
  painel.hidden = false; if (!atual) infoEl.textContent = 'carregando o placar…'; desenhar(); carregarHistorico();
}
function fechar() { painel.hidden = true; }
$('btnPlacar').addEventListener('click', () => (painel.hidden ? abrir() : fechar()));
$('placarFechar').addEventListener('click', fechar);
$('btnPrs').addEventListener('click', fechar);
$('btnKanban').addEventListener('click', fechar);
$('btnApelidos').addEventListener('click', () => { if (!painel.hidden) desenhar(); });
document.querySelectorAll('#placarOrdem button[data-ordem]').forEach((b) => b.addEventListener('click', () => { ordem = b.dataset.ordem; gravarLS(CHAVE_ORDEM, ordem); desenhar(); }));
window.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !painel.hidden) fechar(); });

// ---------------------------------------------------------------- Busca periódica
async function buscar() {
  const sequencia=++revisaoBusca;
  try {
    const r = await fetch(selecaoXP.url(), { cache: 'no-store' });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const j = await r.json();
    if(sequencia!==revisaoBusca)return;
    selecaoXP.receber(j);if(j.fonte==='gestao')historico=[];
    custos = j.custos || null;   // custo_time.py: US$ por agente e por PR (só com dados reais)
    uso = j.uso || null;         // statusline_uso.py: % do plano na janela de 5 h e na semana, consumo por dia
    normalizar(j);
    real = j;
  } catch (e) { if(sequencia!==revisaoBusca)return;real = null; }
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
  instalarIndicadores(painel, $('placarOrdem'));
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
