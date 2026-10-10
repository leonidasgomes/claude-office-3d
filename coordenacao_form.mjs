// Consulta explícita pelo PC; o endpoint não despacha a seleção.
export function formularioCoordenacao(projeto, atualizar) {
  const detalhes=document.createElement('details');
  const resumo=document.createElement('summary');resumo.textContent='Consultar CEO e diretor';detalhes.append(resumo);
  const form=document.createElement('form');detalhes.append(form);
  const objetivo=document.createElement('textarea');objetivo.required=true;objetivo.maxLength=16000;
  objetivo.setAttribute('aria-label','Objetivo do marco');
  const rotulo=document.createElement('label');rotulo.textContent='Objetivo do marco';rotulo.append(objetivo);form.append(rotulo);
  const aviso=document.createElement('p');
  aviso.textContent='Disponível no PC. Informe cartões aprovados do Kanban e worktrees existentes para eles. A consulta usa os modelos cloud configurados e pode consumir sua cota. Ela não despacha agentes.';form.append(aviso);
  const campos=[];const lista=document.createElement('div');form.append(lista);
  const adicionar=document.createElement('button');adicionar.type='button';adicionar.textContent='Adicionar cartão';
  function incluir() {
    if(campos.length>=20)return;
    const linha=document.createElement('fieldset');const legenda=document.createElement('legend');legenda.textContent='Cartão candidato';linha.append(legenda);
    const numero=document.createElement('input');numero.type='number';numero.min='1';numero.step='1';numero.required=true;numero.setAttribute('aria-label','Número do cartão');
    const trabalho=document.createElement('input');trabalho.type='text';trabalho.required=true;trabalho.setAttribute('aria-label','Pasta absoluta do worktree');
    for(const [texto,input] of [['Número do cartão',numero],['Pasta absoluta do worktree',trabalho]]){
      const label=document.createElement('label');label.textContent=texto;label.append(input);linha.append(label);
    }
    const campo={numero,trabalho};
    const remover=document.createElement('button');remover.type='button';remover.textContent='Remover cartão';
    remover.addEventListener('click',()=>{
      if(enviando)return;
      if(campos.length===1){numero.value='';trabalho.value='';return;}
      campos.splice(campos.indexOf(campo),1);linha.remove();adicionar.disabled=false;
    });linha.append(remover);
    lista.append(linha);campos.push(campo);adicionar.disabled=campos.length>=20;
  }
  adicionar.addEventListener('click',()=>{if(!enviando)incluir();});incluir();form.append(adicionar);
  const enviar=document.createElement('button');enviar.type='submit';enviar.textContent='Consultar seleção';form.append(enviar);
  const status=document.createElement('p');status.setAttribute('aria-live','polite');form.append(status);
  let enviando=false;
  form.addEventListener('submit',async ev=>{
    ev.preventDefault();if(enviando)return;
    const cartoes=campos.map(c=>({cartao:Number(c.numero.value),worktree:c.trabalho.value.trim()}));
    if(!objetivo.value.trim() || cartoes.some(c=>!Number.isSafeInteger(c.cartao)||c.cartao<1||!c.worktree)
       || new Set(cartoes.map(c=>c.cartao)).size!==cartoes.length){status.textContent='Informe objetivo e cartões distintos com suas pastas.';return;}
    enviando=true;enviar.disabled=true;status.textContent='Enviando pedido de consulta…';
    try{
      const r=await fetch('/api/gestao/coordenar',{method:'POST',headers:{'Content-Type':'application/json','X-Office-Acao':'1'},
        body:JSON.stringify({projeto_id:projeto.id,versao:projeto.politica_versao,solicitacao:objetivo.value.trim(),plano:{cartoes}})});
      const d=await r.json();if(!r.ok)throw Error(d.erro||'Consulta indisponível');
      if(!/^[0-9a-f]{32}$/.test(d.pedido_id||''))throw Error('Resposta de pedido inválida');
      status.textContent='Pedido '+d.pedido_id.slice(0,8)+' recebido. Feche este formulário e atualize Gestão para acompanhar.';
      await atualizar();
    }catch(e){status.textContent='Não foi possível consultar: '+e.message;}
    finally{enviando=false;enviar.disabled=false;}
  });
  return detalhes;
}

export function renderizarPedidos(dados,pai,linha){
  if(!dados)return;
  if(dados.problemas)linha('p','Pedidos indisponíveis; confira no PC.',pai);
  if(dados.limitado)linha('p','Exibição limitada aos pedidos recentes.',pai);
  for(const p of dados.itens||[]){
    const estado={recebida:'Recebido',consultando:'Consulta registrada; confirme no PC',executando:'Despacho registrado; confirme processos no PC',concluida:'Pedido concluído; confira o recibo',conciliada:'Acompanhamento conciliado com retorno registrado; reservas preservadas',incerto:'Pedido incerto; exige conciliação no PC'}[p.estado]||'Estado desconhecido';
    linha('p',`Pedido ${p.id.slice(0,8)} · ${estado}${p.recibo_id?' · recibo '+p.recibo_id.slice(0,8):''}`,pai);
  }
}

export function botaoExecutarCoordenacao(projeto,recibo,atualizar){
  const caixa=document.createElement('div');
  const botao=document.createElement('button');botao.type='button';botao.textContent='Executar seleção '+recibo.id.slice(0,8);
  const status=document.createElement('p');status.setAttribute('aria-live','polite');caixa.append(botao,status);
  let enviando=false;
  botao.addEventListener('click',async()=>{
    if(enviando)return;enviando=true;botao.disabled=true;
    status.textContent='Solicitando execução dos cartões selecionados…';
    try{
      const r=await fetch('/api/gestao/coordenacao/executar',{method:'POST',headers:{'Content-Type':'application/json','X-Office-Acao':'1'},
        body:JSON.stringify({projeto_id:projeto.id,versao:projeto.politica_versao,recibo_id:recibo.id,plano_sha256:recibo.plano_sha256})});
      const d=await r.json();if(!r.ok)throw Error(d.erro||'Execução indisponível');
      if(!/^[0-9a-f]{32}$/.test(d.pedido_id||''))throw Error('Resposta de pedido inválida');
      status.textContent='Pedido '+d.pedido_id.slice(0,8)+' recebido. Acompanhe os retornos do lote em Gestão.';
      await atualizar();
    }catch(e){status.textContent='Não foi possível executar: '+e.message;botao.disabled=false;}
    finally{enviando=false;}
  });return caixa;
}

export function botaoConciliarPedido(projeto,pedido,atualizar){
  const caixa=document.createElement('div'),botao=document.createElement('button'),status=document.createElement('p');
  botao.type='button';botao.textContent='Conferir retorno '+pedido.id.slice(0,8);
  status.setAttribute('aria-live','polite');caixa.append(botao,status);
  let enviando=false,evidencia=null;
  botao.addEventListener('click',async()=>{
    if(enviando)return;enviando=true;botao.disabled=true;
    const aplicar=evidencia!==null;
    try{
      const body={projeto_id:projeto.id,versao:projeto.politica_versao,pedido_id:pedido.id,acao:aplicar?'aplicar':'previa'};
      if(aplicar)body.evidencia_sha256=evidencia;
      const r=await fetch('/api/gestao/coordenacao/conciliar',{method:'POST',headers:{'Content-Type':'application/json','X-Office-Acao':'1'},body:JSON.stringify(body)});
      const d=await r.json();if(!r.ok)throw Error(d.erro||'Conciliação indisponível');
      if(aplicar){status.textContent='Acompanhamento conciliado. Reservas, processos e Kanban preservados.';await atualizar();}
      else{
        if(!/^[0-9a-f]{64}$/.test(d.evidencia_sha256||''))throw Error('Evidência inválida');
        evidencia=d.evidencia_sha256;
        status.textContent='Retorno registrado: '+d.estado_recibo+'. Confirme para encerrar somente este pedido. Não libera reservas nem reexecuta tarefas.';
        botao.textContent='Confirmar conciliação';botao.disabled=false;
      }
    }catch(e){evidencia=null;status.textContent='Conciliação não aplicada: '+e.message;botao.textContent='Conferir retorno '+pedido.id.slice(0,8);botao.disabled=false;}
    finally{enviando=false;}
  });return caixa;
}
