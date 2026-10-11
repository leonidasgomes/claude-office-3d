export function formularioCiclo(projeto,atualizar) {
  const d=document.createElement('details');
  const resumo=document.createElement('summary');resumo.textContent='Configurar operação automática';d.append(resumo);
  const form=document.createElement('form');d.append(form);
  const label=document.createElement('label');label.textContent='Duração do próximo ciclo (minutos)';
  const minutos=document.createElement('input');minutos.type='number';minutos.min='1';minutos.max='240';minutos.step='1';
  minutos.required=true;minutos.value=String(projeto.ciclo_config.duracao_min);minutos.setAttribute('aria-label',label.textContent);
  label.append(minutos);form.append(label);
  const modo=document.createElement('label');modo.textContent='Operação contínua enquanto houver trabalho e acesso ao provider';
  const continuo=document.createElement('input');continuo.type='checkbox';continuo.checked=projeto.ciclo_config.continuo===true;
  continuo.setAttribute('aria-label',modo.textContent);modo.append(continuo);form.append(modo);
  const aviso=document.createElement('p');aviso.textContent='Vale para o próximo ciclo. O modo contínuo exige metas por cartão habilitadas e dispensa o prazo global. Mantém execução sequencial, gates e pausas por erro. Sem mudanças no quadro, espera sem chamar IA. Salvar não inicia trabalho nem altera a sessão atual.';form.append(aviso);
  const salvar=document.createElement('button');salvar.type='submit';salvar.textContent='Salvar operação';form.append(salvar);
  const status=document.createElement('p');status.setAttribute('role','status');form.append(status);
  let versao=projeto.politica_versao;
  form.addEventListener('submit',async e=>{
    e.preventDefault();if(salvar.disabled)return;salvar.disabled=true;
    try{
      const n=Number(minutos.value);
      if(!Number.isSafeInteger(n)||n<1||n>240)throw Error('Informe entre 1 e 240 minutos.');
      const r=await fetch('/api/gestao/ciclo',{method:'POST',headers:{'Content-Type':'application/json','X-Office-Acao':'1'},
        body:JSON.stringify({projeto_id:projeto.id,versao,ciclo:{duracao_min:n,continuo:continuo.checked}})});
      const j=await r.json();if(!r.ok)throw Error(j.erro||'Não foi possível salvar.');
      if(!/^[a-f0-9]{64}$/.test(j.versao)||typeof j.alterado!=='boolean')throw Error('Resposta inválida; recarregue para conferir.');
      versao=j.versao;d.open=false;await atualizar();
    }catch(e){status.textContent='Alteração não salva: '+e.message;}
    finally{salvar.disabled=false;}
  });
  if(projeto.ciclo?.pausa_configuravel && /^[a-f0-9]{32}$/.test(projeto.ciclo.id||'') &&
     ['iniciando','consultando','diretor','investigando','preparando','implementando','replanejando','aguardando'].includes(projeto.ciclo.estado)) {
    const pausar=document.createElement('button');pausar.type='button';pausar.textContent='Pausar após o despacho atual';d.append(pausar);
    pausar.addEventListener('click',async()=>{
      if(pausar.disabled)return;pausar.disabled=true;
      try {
        const r=await fetch('/api/gestao/ciclo',{method:'POST',headers:{'Content-Type':'application/json','X-Office-Acao':'1'},
          body:JSON.stringify({projeto_id:projeto.id,versao,acao:'pausar',sessao:projeto.ciclo.id})});
        const j=await r.json();if(!r.ok)throw Error(j.erro||'Não foi possível pedir a pausa.');
        if(j.estado!=='pausa_solicitada'||j.sessao!==projeto.ciclo.id)throw Error('Resposta inválida; confira Gestão.');
        status.textContent='Pausa solicitada. O despacho atual termina antes da pausa; confira o estado em Trabalho.';
      }catch(e){status.textContent='Pausa não confirmada: '+e.message;pausar.disabled=false;}
    });
  }
  return d;
}
