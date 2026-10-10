// Um formulário por projeto, com revisão otimista da política; salvar não executa agentes.
export function formularioExecutores(projeto, atualizar) {
  const details=document.createElement('details');
  const summary=document.createElement('summary'); summary.textContent='Escolher consoles do CEO, diretor e equipes';details.append(summary);
  const form=document.createElement('form');details.append(form);
  function campo(pai,titulo,el) {
    const label=document.createElement('label');el.setAttribute('aria-label',titulo);
    label.append(document.createTextNode(titulo+' '),el);pai.append(label);return el;
  }
  function escolha(pai,titulo,opcoes,valor) {
    const el=document.createElement('select');
    for(const v of opcoes) {const o=document.createElement('option');o.value=v;o.textContent=v;el.append(o);}
    el.value=valor;return campo(pai,titulo,el);
  }
  function editor(nome,e,papel=false) {
    const fs=document.createElement('fieldset'),leg=document.createElement('legend');leg.textContent=nome;fs.append(leg);form.append(fs);
    const console=escolha(fs,'Console',['claude','codex','opencode','gemini'],e.console);
    const modelo=campo(fs,'Modelo (vazio usa padrão)',document.createElement('input'));modelo.maxLength=200;modelo.value=e.modelo||'';
    const execucao=escolha(fs,'Execução',papel?['cloud']:(projeto.local.ativo?['cloud','local']:['cloud']),e.execucao||'cloud');
    const cloud=campo(fs,'Fornecedor real do modelo OpenCode (opcional fora da revisão cruzada)',document.createElement('input'));cloud.maxLength=100;cloud.value=e.cloud||'';
    const aviso=document.createElement('p');aviso.textContent='Alterar o console limpa o modelo anterior. Autenticação e disponibilidade são verificadas no console.';fs.append(aviso);
    const catalogo=document.createElement('div');fs.append(catalogo);
    const consultar=document.createElement('button');consultar.type='button';consultar.textContent='Consultar modelos free do OpenCode';catalogo.append(consultar);
    const lista=document.createElement('select');lista.setAttribute('aria-label','Modelo com custo zero declarado');lista.hidden=true;catalogo.append(lista);
    const mensagem=document.createElement('p');mensagem.setAttribute('role','status');catalogo.append(mensagem);
    const visibilidade=()=>{catalogo.hidden=console.value!=='opencode'||execucao.value!=='cloud';};
    visibilidade();console.addEventListener('change',visibilidade);execucao.addEventListener('change',visibilidade);
    lista.addEventListener('change',()=>{if(lista.value){modelo.value=lista.value;cloud.value='';}});
    consultar.addEventListener('click',async()=>{
      consultar.disabled=true;lista.hidden=true;mensagem.textContent='Consultando catálogo local do CLI…';
      try {
        const r=await fetch('/api/gestao/modelos',{method:'POST',headers:{'Content-Type':'application/json','X-Office-Acao':'1'},body:JSON.stringify({console:'opencode'})});
        const dados=await r.json();if(!r.ok||!dados.ok)throw new Error(dados.erro||'Catálogo indisponível');
        lista.replaceChildren();const vazio=document.createElement('option');vazio.value='';vazio.textContent='Selecione explicitamente um modelo';lista.append(vazio);
        for(const m of dados.modelos||[]){const o=document.createElement('option');o.value=m.id;o.textContent=`${m.nome} · ${m.id}`;lista.append(o);}
        lista.hidden=!(dados.modelos||[]).length;
        const quando=new Date(dados.consultado_em*1000);
        const data=Number.isFinite(quando.getTime())?` Consulta: ${quando.toLocaleString()}.`:'';
        mensagem.textContent=lista.hidden?'Nenhum modelo com custo zero e ferramentas foi declarado pelo CLI.':`${dados.modelos.length} modelo(s) declarado(s).${data} ${dados.limite} Fornecedor real não preenchido automaticamente. Sem essa identidade, o modelo não comprova diversidade na revisão cruzada.`;
      }catch(e){mensagem.textContent=`Consulta indisponível: ${e.message}`;}
      finally{consultar.disabled=false;}
    });
    console.addEventListener('change',()=>{modelo.value='';cloud.value='';});
    return ()=>{
      const r={console:console.value,modelo:modelo.value.trim(),execucao:execucao.value};
      if(r.console==='opencode'&&r.execucao==='cloud'&&cloud.value.trim()) r.cloud=cloud.value.trim();
      return r;
    };
  }
  const ceo=editor('CEO',projeto.ceo,true),diretor=editor('Diretor',projeto.diretor,true);
  const equipes=projeto.equipes.map(e=>({nome:e.nome,ler:editor(e.nome,e.executor)}));
  const aviso=document.createElement('p');aviso.textContent='Salva na política única do projeto. Preserva regras, Kanban, revisores, rotas por escopo, especialistas e merge. Rotas por escopo podem prevalecer sobre o executor da equipe; especialistas mantêm o executor cadastrado. Não inicia agentes. Execuções em curso precisam ser conciliadas se a política mudar.';form.append(aviso);
  const salvar=document.createElement('button');salvar.type='submit';salvar.textContent='Salvar executores';form.append(salvar);
  const status=document.createElement('p');status.setAttribute('role','status');form.append(status);
  let versao=projeto.politica_versao;
  form.addEventListener('submit',async ev=>{
    ev.preventDefault();salvar.disabled=true;
    try {
      const r=await fetch('/api/gestao/executores',{method:'POST',headers:{'Content-Type':'application/json','X-Office-Acao':'1'},
        body:JSON.stringify({projeto_id:projeto.id,versao,executores:{ceo:ceo(),diretor:diretor(),equipes:equipes.map(e=>({nome:e.nome,executor:e.ler()}))}})});
      const d=await r.json();if(!r.ok)throw new Error(d.erro||`Servidor respondeu ${r.status}`);
      versao=d.versao;status.textContent=d.alterado?'Executores salvos.':'A política já está com esses executores.';
      details.open=false;await atualizar();
    }catch(e){status.textContent=`Alteração não salva: ${e.message}`;}
    finally{salvar.disabled=false;}
  });
  return details;
}
