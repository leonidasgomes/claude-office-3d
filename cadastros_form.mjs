// Cadastros explícitos; nenhuma ação inicia agentes ou modifica cartões.
async function enviar(projeto, dados) {
  const r=await fetch('/api/gestao/cadastros',{method:'POST',headers:{'Content-Type':'application/json','X-Office-Acao':'1'},body:JSON.stringify({projeto_id:projeto.id,versao:projeto.politica_versao,...dados})});
  const d=await r.json();if(!r.ok)throw Error(d.erro||'Não foi possível salvar o cadastro.');return d;
}

export function formularioEquipe(projeto, atualizar, equipe=null) {
  const details=document.createElement('details'),summary=document.createElement('summary');
  summary.textContent=equipe?`Editar ${equipe.nome}`:'Cadastrar equipe';details.append(summary);
  const form=document.createElement('form');details.append(form);
  function campo(titulo,tag='input',opcoes=[]) {
    const label=document.createElement('label'),el=document.createElement(tag);label.textContent=titulo;
    el.setAttribute('aria-label',titulo);label.append(el);form.append(label);
    for(const valor of opcoes){const o=document.createElement('option');o.value=valor;o.textContent=valor;el.append(o);}return el;
  }
  const nome=campo('Nome da equipe');nome.required=true;nome.maxLength=64;nome.value=equipe?.nome||'';nome.readOnly=!!equipe;
  const especialidade=campo('Especialidade e responsabilidades','textarea');especialidade.required=true;especialidade.maxLength=2000;especialidade.value=equipe?.especialidade||'';
  const console=campo('Console','select',['codex','opencode','claude','gemini']);console.value=equipe?.executor.console||projeto.ceo.console;
  const modelo=campo('Modelo');modelo.maxLength=200;modelo.value=equipe?.executor.modelo||(!equipe?projeto.ceo.modelo:'')||'';
  const execucao=campo('Execução','select',projeto.local.ativo?['cloud','local']:['cloud']);execucao.value=equipe?.executor.execucao||'cloud';
  const cloud=campo('Fornecedor real do modelo OpenCode (opcional)');cloud.maxLength=100;cloud.value=equipe?.executor.cloud||'';
  const sandbox=campo('Sandbox Codex','select',['','read-only','workspace-write']);sandbox.value=equipe?.executor.sandbox||'';
  const aviso=document.createElement('p');aviso.textContent='O nome identifica a equipe no Kanban e não pode ser renomeado aqui. Salvar não inicia agentes. Cadastre o mesmo nome no campo Time do seu quadro quando necessário.';form.append(aviso);
  console.addEventListener('change',()=>{modelo.value='';sandbox.value='';cloud.value='';});
  const botao=document.createElement('button');botao.type='submit';botao.textContent=equipe?'Salvar equipe':'Cadastrar equipe';form.append(botao);
  const status=document.createElement('p');status.setAttribute('role','status');form.append(status);
  form.addEventListener('submit',async e=>{
    e.preventDefault();botao.disabled=true;
    try {
      const executor={console:console.value,modelo:modelo.value.trim(),execucao:execucao.value};
      if(executor.console==='opencode'&&execucao.value==='cloud'&&cloud.value.trim())executor.cloud=cloud.value.trim();
      if(executor.console==='codex'&&execucao.value==='cloud'&&sandbox.value)executor.sandbox=sandbox.value;
      await enviar(projeto,{tipo:'equipe',acao:equipe?'editar':'criar',...(equipe?{nome:equipe.nome}:{}),equipe:{nome:nome.value.trim(),especialidade:especialidade.value.trim(),executor}});
      details.open=false;await atualizar();
    }catch(err){status.textContent=err.message;}finally{botao.disabled=false;}
  });return details;
}

export function botaoExcluir(projeto,tipo,item,atualizar) {
  const caixa=document.createElement('div'),botao=document.createElement('button'),status=document.createElement('p');
  botao.type='button';botao.textContent=tipo==='equipe'?'Excluir equipe':'Excluir funcionário';botao.className='gestaoExcluir';
  const confirmacao=document.createElement('div');confirmacao.hidden=true;confirmacao.setAttribute('role','group');confirmacao.setAttribute('aria-label','Confirmar exclusão de '+item.nome);
  const aviso=document.createElement('p');aviso.textContent=`Excluir ${item.nome}? `+(tipo==='equipe'?'A equipe será removida da configuração. Cartões do Kanban e histórico serão preservados.':'O funcionário sairá da equipe e da cena. O cadastro será arquivado e seu histórico preservado.');
  const confirmar=document.createElement('button'),cancelar=document.createElement('button');confirmar.type=cancelar.type='button';confirmar.textContent='Confirmar exclusão';confirmar.className='gestaoExcluir';cancelar.textContent='Manter cadastro';
  confirmacao.append(aviso,confirmar,cancelar);status.setAttribute('role','status');caixa.append(botao,confirmacao,status);
  botao.addEventListener('click',()=>{confirmacao.hidden=false;cancelar.focus();});
  cancelar.addEventListener('click',()=>{confirmacao.hidden=true;status.textContent='';botao.focus();});
  confirmar.addEventListener('click',async()=>{
    botao.disabled=confirmar.disabled=cancelar.disabled=true;
    try{await enviar(projeto,{tipo,acao:'excluir',...(tipo==='equipe'?{nome:item.nome}:{id:item.id,anterior:item})});await atualizar();}
    catch(err){status.textContent=err.message;}finally{botao.disabled=confirmar.disabled=cancelar.disabled=false;}
  });return caixa;
}
