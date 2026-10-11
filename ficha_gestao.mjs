// Dados registrados da mesa; consultar não despacha nem retoma trabalho.
export function tarefasDaMesa(dados, projetoId, mesa) {
  const projeto=dados?.projetos?.find(p=>p.id===projetoId && p.ativo && !p.erro);
  if (!projeto) return [];
  const funcionario=/^Office_([0-9a-f]{32})$/.exec(mesa)?.[1];
  const equipe=(projeto.equipes||[]).find(e=>e.nome===mesa);
  if (!funcionario && !equipe) return [];
  return (projeto.tarefas||[]).filter(t=>funcionario?t.funcionario_id===funcionario:t.equipe===equipe.nome)
    .slice(0,10);
}

export function leitorGestao(fetcher=globalThis.fetch, agora=()=>Date.now()) {
  let dados=null, instante=0, pendente=null;
  const ler=async()=>{
    if(dados && agora()-instante<30000)return dados;
    if(pendente)return pendente;
    pendente=(async()=>{
      const controle=new AbortController(),timer=setTimeout(()=>controle.abort(),5000);
      try {
        const r=await fetcher('/api/gestao',{cache:'no-store',signal:controle.signal});
        if(!r.ok)throw Error('Gestão indisponível');
        const novo=await r.json();
        if(!Array.isArray(novo?.projetos))throw Error('Gestão inválida');
        dados=novo;instante=agora();return dados;
      } finally {clearTimeout(timer);}
    })();
    try{return await pendente;}finally{pendente=null;}
  };
  ler.invalidar=()=>{instante=-Infinity;};
  return ler;
}

export function desenharTrabalhoMesa(pai,tarefas,documento=globalThis.document) {
  const adicionar=(tag,texto,alvo=pai)=>{const e=documento.createElement(tag);e.textContent=texto;alvo.append(e);return e;};
  if(!tarefas.length){adicionar('li','Nenhum cartão vinculado a esta mesa no diário do escritório.');return;}
  for(const t of tarefas){
    const li=adicionar('li',''),cp=t.checkpoint;
    adicionar('b',`#${t.cartao} · ${t.estado}`,li);
    // Reserva em execução não comprova processo ativo; mantém sinais separados.
    adicionar('p',`Console observado: ${t.atividade?.console_observado===true?'sim':'não confirmado'} · estado registrado: ${t.atividade?.estado||'sem medição'}`,li);
    for(const op of t.operacoes||[]){
      const tempo=Number.isFinite(op.duracao_seg)?`${Math.round(op.duracao_seg)} s observados`:'duração não informada';
      adicionar('p',`${op.ferramenta} · ${op.estado} · ${tempo} · saída ${op.codigo??'não informada'}`,li);
    }
    if(cp){
      if(cp.branch)adicionar('p',`Branch: ${cp.branch}`,li);
      adicionar('p',`Worktree: ${cp.worktree_vinculado?'vinculado':'não confirmado'}`,li);
      if(cp.ultima_tentativa)adicionar('p',`Última tentativa: ${cp.ultima_tentativa.tipo||'não informada'} · ${cp.ultima_tentativa.resultado||'sem resultado'} · saída ${cp.ultima_tentativa.codigo??'sem retorno'}`,li);
      adicionar('p',cp.acao,li);
      if(cp.entrega && /^https:\/\/github\.com\/[^/]+\/[^/]+\/pull\/\d+$/.test(cp.entrega.url||'')){
        const a=adicionar('a',`PR #${cp.entrega.pr} · ${String(cp.entrega.head||'').slice(0,8)}`,li);
        a.href=cp.entrega.url;a.target='_blank';a.rel='noopener';
      }
    }
    const abrir=adicionar('button','Conferir em Gestão',li);abrir.type='button';
    abrir.addEventListener('click',()=>globalThis.window.dispatchEvent(new CustomEvent('office-gestao-abrir')));
  }
}
