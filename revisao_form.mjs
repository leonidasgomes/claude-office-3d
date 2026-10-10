// Revisão opcional na política do projeto, sem executar revisores ao salvar.
export function formularioRevisao(projeto, atualizar) {
  const details=document.createElement('details');
  const summary=document.createElement('summary');summary.textContent='Configurar revisão deste projeto';details.append(summary);
  const form=document.createElement('form');details.append(form);
  function campo(titulo,tipo) {
    const label=document.createElement('label');label.textContent=titulo;
    const el=document.createElement('input');el.type=tipo;el.setAttribute('aria-label',titulo);label.append(el);form.append(label);return el;
  }
  const ativo=campo('Exigir revisão por IA','checkbox');ativo.checked=projeto.revisao.ativo;
  const clouds=campo('Quantidade de fornecedores distintos','number');clouds.min='1';clouds.step='1';clouds.value=String(projeto.revisao.clouds_distintas);
  const separar=campo('Revisor de fornecedor diferente do autor','checkbox');separar.checked=projeto.revisao.separar_autor;
  function estado(){clouds.disabled=separar.disabled=!ativo.checked;}ativo.addEventListener('change',estado);estado();
  const aviso=document.createElement('p');aviso.textContent='Vale somente para este projeto. Desativar dispensa a revisão por IA e preserva os revisores cadastrados. Checks do GitHub e regras de merge continuam obrigatórios. Reativar exige fornecedores suficientes na política; login e disponibilidade são conferidos na execução. Auditor ativo exige revisão com dois fornecedores e separação do autor. Execuções em curso precisam de nova conferência após mudança de política.';form.append(aviso);
  const salvar=document.createElement('button');salvar.type='submit';salvar.textContent='Salvar política de revisão';form.append(salvar);
  const status=document.createElement('p');status.setAttribute('role','status');form.append(status);
  let versao=projeto.politica_versao,ocupado=false;
  form.addEventListener('submit',async ev=>{
    ev.preventDefault();if(ocupado)return;ocupado=true;salvar.disabled=true;
    try {
      const revisao={ativo:ativo.checked,clouds_distintas:Number(clouds.value),separar_autor:separar.checked};
      if(!Number.isSafeInteger(revisao.clouds_distintas)||revisao.clouds_distintas<1)throw new Error('Informe uma quantidade inteira positiva.');
      const r=await fetch('/api/gestao/revisao',{method:'POST',headers:{'Content-Type':'application/json','X-Office-Acao':'1'},body:JSON.stringify({projeto_id:projeto.id,versao,revisao})});
      const d=await r.json();if(!r.ok)throw new Error(d.erro||`Servidor respondeu ${r.status}`);
      if(!/^[0-9a-f]{64}$/.test(d.versao)||typeof d.alterado!=='boolean')throw new Error('Resposta inválida; recarregue para conferir.');
      versao=d.versao;status.textContent=d.alterado?'Política de revisão salva.':'A política já está com esta configuração.';details.open=false;await atualizar();
    }catch(e){status.textContent=`Alteração não salva: ${e.message}`;}
    finally{ocupado=false;salvar.disabled=false;}
  });
  return details;
}
