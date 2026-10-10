// Office Multi-provider — configuração da página, lida do servidor (GET /config) antes de montar a cena.
// Os três módulos (escritorio.js, kanban.js, prs.js) importam daqui e recebem o MESMO objeto.
// Sem servidor (index.html aberto direto do disco) vale o padrão abaixo e a página entra em modo demonstração.

const PADRAO = {
  titulo: 'Office Multi-provider',
  tema: 'neutro',
  apelidos: 'desligado',
  agentes: [
    { nome: 'Lider', titulo: 'Líder', funcao: 'Coordena o time e revisa', cor: '#e5484d', apelido_br: 'Lia', apelido_cinema: 'Morpheus', cargo: '', mesa: 'lider', lider: true,
      outros_nomes: ['main', 'lead', 'leader', 'team-lead', 'team_lead'] },
    { nome: 'Dev', titulo: 'Dev', funcao: 'Código e testes', cor: '#3b82f6', apelido_br: 'João', apelido_cinema: 'Neo', cargo: '', mesa: 'dev', outros_nomes: [] },
    { nome: 'Designer', titulo: 'Designer', funcao: 'Interface e modelagem', cor: '#f59e0b', apelido_br: 'Maria', apelido_cinema: 'Trinity', cargo: '', mesa: 'design', outros_nomes: [] },
    { nome: 'Pesquisa', titulo: 'Pesquisa', funcao: 'Busca e documentação', cor: '#22c55e', apelido_br: 'Aquiles', apelido_cinema: 'Indiana', cargo: '', mesa: 'pesquisa', outros_nomes: [] },
  ],
  github: { repo: '', kanban: false, prs: false, projeto_owner: '', projeto_numero: 0, check_revisao: '', times: {}, colunas: [] },
  xp: { ativo: true, niveis: [] },   // sem servidor: o placar mostra uma demonstração
  gh_disponivel: false,
  three_local: false,
};

let lido = null;
try {
  const r = await fetch('/config', { cache: 'no-store' });
  if (r.ok) lido = await r.json();
} catch (e) { /* sem servidor: usa o padrão */ }

export const temServidor = !!lido;
export const CONFIG = { ...PADRAO, ...(lido || {}), github: { ...PADRAO.github, ...((lido && lido.github) || {}) },
  xp: { ...PADRAO.xp, ...((lido && lido.xp) || {}) } };
if (!Array.isArray(CONFIG.agentes) || !CONFIG.agentes.length) CONFIG.agentes = PADRAO.agentes;

// chave comparável de um nome de agente (igual à do configuracao.py)
export const chave = (n) => String(n || '').trim().toLowerCase().replace(/[-\s]/g, '_');
// agente configurado pelo nome (ou por um dos outros_nomes), ou null
export function agenteConfig(nome) {
  const k = chave(nome);
  return CONFIG.agentes.find((a) => chave(a.nome) === k || (a.outros_nomes || []).some((o) => chave(o) === k)) || null;
}
export const corDe = (nome, padrao = '#475569') => (agenteConfig(nome) || {}).cor || padrao;
export const tituloDe = (nome) => { const a = agenteConfig(nome); return a ? a.titulo : String(nome || '').replace(/_/g, ' '); };
if (!CONFIG.agentes.some((a) => a.lider)) CONFIG.agentes[0].lider = true;
// líder: marcado "lider": true (ou o primeiro). A sessão principal do Claude Code aparece na mesa dele.
export const LIDER = CONFIG.agentes.find((a) => a.lider);

document.title = CONFIG.titulo;
