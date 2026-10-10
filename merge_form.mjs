// Edição por projeto; salvar política não executa merge.
export function formularioMerge(projeto, atualizar) {
  const details=document.createElement('details');
  const summary=document.createElement('summary');summary.textContent='Configurar merge deste projeto';details.append(summary);
  const form=document.createElement('form');details.append(form);
  function campo(titulo,tag) {
    const label=document.createElement('label');label.textContent=titulo;
    const el=document.createElement(tag);el.setAttribute('aria-label',titulo);label.append(el);form.append(label);return el;
  }
  const modo=campo('Modo de merge','select');
  for(const [valor,texto] of [['manual','Manual'],['automatico','Automático após os gates configurados']]) {
    const o=document.createElement('option');o.value=valor;o.textContent=texto;modo.append(o);
  }
  modo.value=projeto.merge_config.modo;
  const checks=campo('Checks obrigatórios (um nome exato por linha)','textarea');
  const rotulos=campo('Rótulos que exigem merge manual (um por linha)','textarea');
  checks.value=projeto.merge_config.checks.join('\n');rotulos.value=projeto.merge_config.rotulos_manuais.join('\n');
  checks.maxLength=rotulos.maxLength=20100;
  const aviso=document.createElement('p');
  aviso.textContent='Esta escolha vale somente para este projeto. Projetos novos começam em modo manual. Salvar altera a política usada pelo controlador; não faz merge. O modo automático exige checks e preserva as regras de revisão e validação do commit. Mudanças de política exigem nova conferência das execuções em curso.';form.append(aviso);
  const salvar=document.createElement('button');salvar.type='submit';salvar.textContent='Salvar política de merge';form.append(salvar);
  const status=document.createElement('p');status.setAttribute('role','status');form.append(status);
  let versao=projeto.politica_versao,ocupado=false;
  function nomes(campo) {
    const v=campo.value.split(/\r?\n/).map(x=>x.trim()).filter(Boolean);
    if(v.length>100 || v.some(x=>Array.from(x).length>200) || new Set(v).size!==v.length)throw new Error('Use até 100 nomes distintos de até 200 caracteres por campo.');
    return v;
  }
  form.addEventListener('submit',async ev=>{
    ev.preventDefault();if(ocupado)return;ocupado=true;salvar.disabled=true;
    try {
      const merge={modo:modo.value,checks:nomes(checks),rotulos_manuais:nomes(rotulos)};
      if(!['manual','automatico'].includes(merge.modo))throw new Error('Modo inválido.');
      if(merge.modo==='automatico'&&!merge.checks.length)throw new Error('Informe ao menos um check obrigatório para o modo automático.');
      const r=await fetch('/api/gestao/merge',{method:'POST',headers:{'Content-Type':'application/json','X-Office-Acao':'1'},body:JSON.stringify({projeto_id:projeto.id,versao,merge})});
      const d=await r.json();if(!r.ok)throw new Error(d.erro||`Servidor respondeu ${r.status}`);
      if(!/^[0-9a-f]{64}$/.test(d.versao)||typeof d.alterado!=='boolean')throw new Error('Resposta inválida; recarregue para conferir a política.');
      versao=d.versao;status.textContent=d.alterado?'Política de merge salva.':'A política já está com esta configuração.';
      details.open=false;await atualizar();
    }catch(e){status.textContent=`Alteração não salva: ${e.message}`;}
    finally{ocupado=false;salvar.disabled=false;}
  });
  return details;
}
