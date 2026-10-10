// Perfis derivados: prévia explícita antes de criar; conteúdo tratado como texto.
export function formularioAgenteNativo(projeto,funcionario) {
  const d=document.createElement('details'),s=document.createElement('summary');
  s.textContent=`Perfil nativo de ${funcionario.nome}`;d.append(s);
  const estados={ausente:'ainda não criado',atual:'arquivo corresponde às fontes atuais',
    divergente:'divergente ou desatualizado; arquivo preservado',
    indisponivel:'não foi possível conferir; revise cadastro, fontes e arquivos',
    gerenciado:'modelo local: use o despacho gerenciado para proteger recursos'};
  const observado=document.createElement('p');
  function mostrarEstado(estado) {
    observado.textContent=`Estado do perfil: ${estados[estado] || 'ainda não consultado'}. Não comprova descoberta ou execução no console.`;
  }
  mostrarEstado(funcionario.perfil_nativo?.estado);
  d.append(observado);
  if(funcionario.perfil_nativo?.estado==='gerenciado')return d;
  const aviso=document.createElement('p');
  aviso.textContent='Cria uma definição para descoberta pelo console cloud. Não inicia trabalho nem muda permissões. Perfis existentes divergentes são preservados.';d.append(aviso);
  const previa=document.createElement('button');previa.type='button';previa.textContent='Conferir perfil';
  const aplicar=document.createElement('button');aplicar.type='button';aplicar.textContent='Criar perfil conferido';aplicar.disabled=true;
  const conteudo=document.createElement('pre'),status=document.createElement('p');status.setAttribute('role','status');
  d.append(previa,conteudo,aplicar,status);let plano=null;
  async function pedir(gravar) {
    previa.disabled=true;aplicar.disabled=true;
    try {
      const r=await fetch('/api/gestao/funcionarios/perfil',{method:'POST',headers:{'Content-Type':'application/json','X-Office-Acao':'1'},
        body:JSON.stringify({projeto_id:projeto.id,funcionario_id:funcionario.id,aplicar:gravar,...(gravar?{confirmacao:plano.confirmacao}:{})})});
      const dados=await r.json();if(!r.ok)throw new Error(dados.erro||`Servidor respondeu ${r.status}`);
      mostrarEstado(dados.estado);
      plano=gravar?null:dados;conteudo.textContent=`${dados.arquivo} · ${dados.estado}\n\n${dados.conteudo}`;
      status.textContent=gravar?(dados.criado?'Perfil criado. Reinicie/recarregue agentes no console para conferir descoberta.':'Perfil já estava atualizado.') : dados.limite;
      aplicar.disabled=gravar||dados.estado!=='ausente';
    } catch(e) {plano=null;mostrarEstado('indisponivel');status.textContent=`Perfil indisponível: ${e.message}`;}
    finally {previa.disabled=false;}
  }
  previa.addEventListener('click',()=>pedir(false));
  aplicar.addEventListener('click',()=>plano?pedir(true):undefined);
  return d;
}
