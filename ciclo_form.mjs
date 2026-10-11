export function formularioCiclo(projeto,atualizar) {
  const d=document.createElement('details');
  const resumo=document.createElement('summary');resumo.textContent='Configurar duração do ciclo';d.append(resumo);
  const form=document.createElement('form');d.append(form);
  const label=document.createElement('label');label.textContent='Duração do próximo ciclo (minutos)';
  const minutos=document.createElement('input');minutos.type='number';minutos.min='1';minutos.max='240';minutos.step='1';
  minutos.required=true;minutos.value=String(projeto.ciclo_config.duracao_min);minutos.setAttribute('aria-label',label.textContent);
  label.append(minutos);form.append(label);
  const aviso=document.createElement('p');aviso.textContent='Vale para o próximo ciclo. Não altera o prazo da sessão em andamento, não inicia trabalho e mantém os limites de cartões e os gates.';form.append(aviso);
  const salvar=document.createElement('button');salvar.type='submit';salvar.textContent='Salvar duração';form.append(salvar);
  const status=document.createElement('p');status.setAttribute('role','status');form.append(status);
  let versao=projeto.politica_versao;
  form.addEventListener('submit',async e=>{
    e.preventDefault();if(salvar.disabled)return;salvar.disabled=true;
    try{
      const n=Number(minutos.value);
      if(!Number.isSafeInteger(n)||n<1||n>240)throw Error('Informe entre 1 e 240 minutos.');
      const r=await fetch('/api/gestao/ciclo',{method:'POST',headers:{'Content-Type':'application/json','X-Office-Acao':'1'},
        body:JSON.stringify({projeto_id:projeto.id,versao,ciclo:{duracao_min:n}})});
      const j=await r.json();if(!r.ok)throw Error(j.erro||'Não foi possível salvar.');
      if(!/^[a-f0-9]{64}$/.test(j.versao)||typeof j.alterado!=='boolean')throw Error('Resposta inválida; recarregue para conferir.');
      versao=j.versao;d.open=false;await atualizar();
    }catch(e){status.textContent='Alteração não salva: '+e.message;}
    finally{salvar.disabled=false;}
  });
  return d;
}
