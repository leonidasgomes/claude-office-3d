// Retomada por cartão; sessão e worktree vêm da reserva no servidor.
export function formularioRetomada(projeto,tarefa,atualizar){
  const detalhes=document.createElement('details');
  const titulo=document.createElement('summary');titulo.textContent=`Retomar #${tarefa.cartao}`;detalhes.append(titulo);
  const form=document.createElement('form');detalhes.append(form);
  const aviso=document.createElement('p');
  aviso.textContent='No PC, confira a sessão, os agentes e o worktree antes de retomar. A prévia não executa modelos; a retomada usa o modelo cloud configurado e pode consumir sua cota.';form.append(aviso);
  const conferir=document.createElement('button');conferir.type='button';conferir.textContent='Conferir retomada';form.append(conferir);
  const label=document.createElement('label');label.textContent='Conferi os agentes e ferramentas da sessão anterior no console';
  const checkbox=document.createElement('input');checkbox.type='checkbox';checkbox.disabled=true;label.append(checkbox);form.append(label);
  const enviar=document.createElement('button');enviar.type='submit';enviar.textContent='Retomar sessão';enviar.disabled=true;form.append(enviar);
  const status=document.createElement('p');status.setAttribute('aria-live','polite');form.append(status);
  let previa=null,ocupado=false;
  const base={projeto_id:projeto.id,versao:projeto.politica_versao,cartao:Number(tarefa.cartao)};
  function botoes(){conferir.disabled=ocupado;checkbox.disabled=ocupado||!previa;enviar.disabled=ocupado||!previa||!checkbox.checked;}
  async function pedido(campos){
    const r=await fetch('/api/gestao/retomar',{method:'POST',headers:{'Content-Type':'application/json','X-Office-Acao':'1'},body:JSON.stringify({...base,...campos})});
    const d=await r.json();if(!r.ok)throw Error(d.erro||'Retomada indisponível');return d;
  }
  checkbox.addEventListener('change',botoes);
  conferir.addEventListener('click',async()=>{
    if(ocupado)return;previa=null;checkbox.checked=false;ocupado=true;botoes();status.textContent='Conferindo reserva e Kanban…';
    try{
      const d=await pedido({acao:'previa'});
      if(!d.apenas_previa||d.cartao!==base.cartao||!/^[0-9a-f]{64}$/.test(d.confirmacao||'')||typeof d.console!=='string'||typeof d.equipe!=='string')throw Error('Prévia inválida');
      previa=d;status.textContent=`#${d.cartao} · ${d.equipe} · ${d.console}: prévia conferida. Declare a conferência dos agentes para retomar.`;
    }catch(e){status.textContent='Não foi possível conferir: '+e.message;}
    finally{ocupado=false;botoes();}
  });
  form.addEventListener('submit',async ev=>{
    ev.preventDefault();if(ocupado||!previa||!checkbox.checked)return;
    ocupado=true;botoes();status.textContent='Enviando retomada…';
    try{
      const d=await pedido({acao:'executar',confirmacao:previa.confirmacao,agentes_conciliados:true});
      if(!/^[0-9a-f]{32}$/.test(d.pedido_id||''))throw Error('Pedido inválido');
      status.textContent='Retomada '+d.pedido_id.slice(0,8)+' recebida. Acompanhe o pedido e o cartão em Gestão.';
      previa=null;checkbox.checked=false;detalhes.open=false;await atualizar();
    }catch(e){previa=null;checkbox.checked=false;status.textContent='Não foi possível retomar: '+e.message;}
    finally{ocupado=false;botoes();}
  });
  return detalhes;
}

export function renderizarRetomadas(dados,pai,linha){
  if(!dados)return;
  if(dados.problemas)linha('p','Pedidos de retomada indisponíveis; confira no PC.',pai);
  if(dados.limitado)linha('p','Exibição limitada às dez retomadas recentes.',pai);
  const estados={recebida:'Retomada recebida',executando:'Retomada acompanhada; confirme o console',concluida:'Retomada retornou',conciliada:'Acompanhamento conciliado; reserva preservada',incerto:'Retomada incerta; exige conciliação no PC'};
  for(const p of dados.itens||[]){
    const retorno=p.resultado==='revisao'?' · cartão em revisão':p.resultado==='bloqueado'?' · cartão bloqueado':'';
    linha('p',`#${p.cartao} · ${estados[p.estado]||'Estado desconhecido'}${retorno}${p.codigo==null?'':' · saída '+p.codigo}`,pai);
  }
}


export function botaoConciliarRetomada(projeto,pedido,atualizar){
  const caixa=document.createElement('div'),botao=document.createElement('button'),status=document.createElement('p');
  botao.type='button';botao.textContent=`Conferir retorno da retomada #${pedido.cartao}`;
  status.setAttribute('aria-live','polite');caixa.append(botao,status);
  let evidencia=null,enviando=false;
  botao.addEventListener('click',async()=>{
    if(enviando)return;enviando=true;botao.disabled=true;
    const aplicar=evidencia!==null;
    status.textContent=aplicar?'Conciliando acompanhamento…':'Conferindo retorno vinculado…';
    try{
      const campos={projeto_id:projeto.id,versao:projeto.politica_versao,pedido_id:pedido.id,acao:aplicar?'aplicar':'previa'};
      if(aplicar)campos.evidencia_sha256=evidencia;
      const r=await fetch('/api/gestao/retomada/conciliar',{method:'POST',headers:{'Content-Type':'application/json','X-Office-Acao':'1'},body:JSON.stringify(campos)});
      const d=await r.json();if(!r.ok)throw Error(d.erro||'Retorno indisponível');
      if(aplicar){
        if(d.estado!=='conciliada')throw Error('Conciliação sem confirmação');
        status.textContent='Acompanhamento conciliado. Reserva, processos e Kanban preservados.';await atualizar();
      }else{
        if(d.pedido_id!==pedido.id||d.cartao!==Number(pedido.cartao)||!/^[0-9a-f]{64}$/.test(d.evidencia_sha256||'')
          ||!['bloqueado','revisao'].includes(d.resultado)||!Number.isSafeInteger(d.codigo))throw Error('Evidência inválida');
        evidencia=d.evidencia_sha256;botao.textContent='Confirmar conciliação';botao.disabled=false;
        status.textContent=`Retorno da tentativa vinculada: ${d.resultado} · saída ${d.codigo}. Confirme para encerrar somente o acompanhamento deste pedido.`;
      }
    }catch(e){evidencia=null;botao.textContent=`Conferir retorno da retomada #${pedido.cartao}`;botao.disabled=false;status.textContent='Conciliação não aplicada: '+e.message;}
    finally{enviando=false;}
  });return caixa;
}
