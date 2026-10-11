// Animação de lazer é independente do estado registrado pelo controlador.
const livres = new Set(['revisao','bloqueado','concluido','cancelado','liberado']);
const ativos = new Set(['iniciando','consultando','diretor','investigando','preparando','implementando','replanejando','aguardando']);
const nomes = {diretor:'Diretor avaliando',investigando:'Investigando bloqueios',preparando:'Preparando equipe',
  implementando:'Equipe despachada',replanejando:'Replanejando',aguardando:'Aguardando mudanças',
  limite:'Janela encerrada',erro:'Erro — confira Gestão',pausado:'Pausado',consultando:'Consultando Kanban',
  iniciando:'Iniciando',desligado:'Automação desligada',concluido:'Concluído'};
export const nomeCiclo = e => nomes[e] || 'Estado desconhecido';
export function estadoNaCena(dados, nome, agoraMs=Date.now()) {
  if (!dados?.ok || !Number.isFinite(dados.ts) || agoraMs-dados.ts*1000>15000 || dados.ts*1000-agoraMs>5000)
    return {livre:false,texto:'Estado da Gestão indisponível',cor:'#64748b'};
  const ciclo = dados.ciclo || {};
  if (['CEO','Diretor'].includes(nome) && ativos.has(ciclo.estado))
    return {livre:false,texto:nome==='CEO'?'Coordenando pelo host':ciclo.estado==='diretor'?'Classificando cartões':'Acompanhando o ciclo',cor:'#3b82f6'};
  const tarefas = (dados.tarefas||[]).filter(t=>t.equipe===nome);
  const ocupadas = tarefas.filter(t=>!livres.has(t.estado));
  if (ocupadas.length) return {livre:false,texto:ocupadas.map(t=>`#${t.cartao} · ${t.estado}`).join(' / '),cor:'#22c55e'};
  const texto = tarefas.length ? tarefas.map(t=>`#${t.cartao} · ${t.estado==='revisao'?'em revisão':t.estado}`).join(' / ') : 'Aguardando despacho';
  return {livre:true,texto,cor:tarefas.some(t=>t.estado==='bloqueado')?'#f59e0b':'#64748b'};
}
