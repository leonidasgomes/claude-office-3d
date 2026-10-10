// Projeção de recibos locais; não inicia consultas, despachos ou retomadas.
export function renderizarCoordenacoes(dados, pai, linha) {
  const registros = dados || {itens: []};
  linha('h4', 'Coordenações do CEO e diretor', pai);
  linha('p', 'Estados são registros locais; confirme consultas e processos no PC antes de repetir ou retomar.', pai);
  if (!registros.itens?.length) linha('p', 'Nenhuma coordenação registrada.', pai);
  if (registros.problemas) linha('p', 'Há recibos indisponíveis ou inconsistentes; confira no PC.', pai);
  if (registros.limitado) linha('p', 'Exibição limitada às dez coordenações recentes deste projeto.', pai);
  const estados = {preparado:'Preparação registrada', consultando_ceo:'Consulta CEO registrada; confirme no PC',
    ceo_registrado:'Decisão CEO registrada', consultando_diretor:'Consulta diretor registrada; confirme no PC',
    diretor_registrado:'Decisão diretor registrada', organizado:'Seleção organizada, sem despacho',
    despachando:'Despacho registrado; confira o lote e os processos no PC',
    processado:'Seleção encaminhada à revisão', interrompido:'Lote interrompido',
    bloqueado:'Seleção bloqueada', incerto:'Coordenação incerta; requer conciliação'};
  for (const r of registros.itens || []) {
    linha('p', `Coordenação ${r.id.slice(0,8)} · ${estados[r.estado] || 'Estado desconhecido'}`, pai);
    const data=new Date(r.atualizado*1000);
    if (Number.isFinite(data.getTime())) linha('p', `Último registro: ${data.toLocaleString()}`, pai);
    linha('p', `Candidatos: ${r.candidatos.map(n=>'#'+n).join(', ')}`, pai);
    for (const papel of ['ceo','diretor']) {
      const e=r.executores[papel];const d=r[papel];
      linha('p', `${papel==='ceo'?'CEO':'Diretor'}: ${e.console} · ${e.modelo || 'padrão do console'} · ${d ? 'seleção '+(d.cartoes.map(n=>'#'+n).join(', ') || 'vazia')+' · '+d.bloqueios+' bloqueio(s)' : 'sem decisão registrada'}`, pai);
    }
    if (r.lote_id) linha('p', `Lote vinculado: ${r.lote_id.slice(0,8)}. Consulte os retornos em Lotes do diretor.`, pai);
  }
}
