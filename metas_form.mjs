export function formularioMetas(projeto,atualizar) {
  const d=document.createElement('details');
  const resumo=document.createElement('summary');resumo.textContent='Configurar metas por cartão';d.append(resumo);
  const form=document.createElement('form');d.append(form);
  function campo(texto,tipo,valor,min,max){
    const label=document.createElement('label');label.textContent=texto;
    const input=document.createElement('input');input.type=tipo;input.setAttribute('aria-label',texto);
    if(tipo==='checkbox')input.checked=valor;
    else {input.value=String(valor);input.min=String(min);input.max=String(max);input.step='1';input.required=true;}
    label.append(input);form.append(label);return input;
  }
  const cfg=projeto.metas_config;
  const ativo=campo('Usar metas vinculadas ao GDD e Kanban','checkbox',cfg.ativo);
  const tempo=campo('Tempo por tentativa do agente (minutos)','number',cfg.tempo_min,1,240);
  const tokens=campo('Limite de tokens observados por tentativa','number',cfg.tokens,1000,10000000);
  const aviso=document.createElement('p');aviso.textContent='Salve com ciclo e tarefas parados. Vale para novos despachos; não retoma cartões antigos. Tempo interrompe a árvore do console. Tokens incluem entrada (com cache) e saída observadas, sem garantia de teto de cobrança: alguns consoles só informam no fim do turno. Revisão independente mantém seus gates e não usa este orçamento.';form.append(aviso);
  const salvar=document.createElement('button');salvar.type='submit';salvar.textContent='Salvar metas';form.append(salvar);
  const status=document.createElement('p');status.setAttribute('role','status');form.append(status);
  let versao=projeto.politica_versao;
  form.addEventListener('submit',async e=>{
    e.preventDefault();if(salvar.disabled)return;salvar.disabled=true;
    try{
      const minutos=Number(tempo.value),limite=Number(tokens.value);
      if(!Number.isSafeInteger(minutos)||minutos<1||minutos>240||!Number.isSafeInteger(limite)||limite<1000||limite>10000000)
        throw Error('Informe tempo de 1 a 240 minutos e tokens de 1.000 a 10.000.000.');
      const r=await fetch('/api/gestao/metas',{method:'POST',headers:{'Content-Type':'application/json','X-Office-Acao':'1'},
        body:JSON.stringify({projeto_id:projeto.id,versao,metas:{ativo:ativo.checked,tempo_min:minutos,tokens:limite}})});
      const j=await r.json();if(!r.ok)throw Error(j.erro||'Não foi possível salvar.');
      if(!/^[a-f0-9]{64}$/.test(j.versao)||typeof j.alterado!=='boolean')throw Error('Resposta inválida; recarregue para conferir.');
      versao=j.versao;d.open=false;await atualizar();
    }catch(e){status.textContent='Alteração não salva: '+e.message;}
    finally{salvar.disabled=false;}
  });
  return d;
}

export function renderizarMetas(metas,alvo,linha){
  linha('h4','Metas por cartão',alvo);
  if(metas?.problemas)linha('p','Há registros de meta indisponíveis; confira os recibos no PC.',alvo);
  if(!metas?.itens?.length)linha('p','Nenhuma tentativa com meta registrada. Cartões antigos não ganham metas retroativas.',alvo);
  for(const m of metas?.itens||[]){
    const detalhe=document.createElement('details');alvo.append(detalhe);
    linha('summary',`#${m.cartao} · ${m.equipe} · ${m.estado}`,detalhe);
    linha('p',`${m.objetivo_gdd} · ${m.objetivo}`,detalhe);
    linha('p',`Limites da tentativa: ${m.limites.tempo_min} min · ${m.limites.tokens.toLocaleString('pt-BR')} tokens observados.`,detalhe);
    linha('p',m.tokens_observados==null ? 'Tokens ainda não informados; ausência de contador não significa zero.' :
      `Tokens observados: ${m.tokens_observados.toLocaleString('pt-BR')} · ${m.medicao}.`,detalhe);
    linha('p',`Último registro: ${new Date(m.atualizado*1000).toLocaleString()}. Registro não comprova agente ativo.`,detalhe);
    if(m.motivo)linha('p',`Motivo: ${m.motivo}`,detalhe);
    if(m.pr)linha('p',`PR #${m.pr}: encaminhamento à revisão não comprova aceite nem merge.`,detalhe);
  }
  if(metas?.limitado)linha('p','Exibição limitada às 200 tentativas mais recentes.',alvo);
}
