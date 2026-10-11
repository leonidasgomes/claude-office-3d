// Cadastro da Gestão é a fonte da cena. Config antigo fornece apenas aparência/aliases.
const chave = n => String(n||'').trim().toLowerCase().replace(/[-\s]/g,'_');
const cores = {claude:'#e5484d',codex:'#3b82f6',opencode:'#a855f7',gemini:'#22c55e'};
export function projetosDaCena(dados) {
  return (dados?.projetos||[]).filter(p=>p.ativo && !p.erro && /^[a-f0-9]{20}$/.test(p.id));
}
export function selecionarProjeto(projetos, id) {
  return projetos.find(p=>p.id===id) || projetos[0] || null;
}
export function mesasDoProjeto(p, antigos=[]) {
  if (!p) return [];
  const mesa=(nome,tipo,e,especialidade='',lider=false)=>{
    const antigo=tipo==='Equipe' ? antigos.find(a=>[a.nome,a.titulo,a.time_kanban,...(a.outros_nomes||[])].some(n=>chave(n)===chave(nome))) : null;
    return {...(antigo||{}),nome,titulo:nome,cargo:tipo,lider,auxiliar:tipo==='Diretor',
      console:e?.console,modelo:e?.modelo||'',projeto_id:p.id,
      cor:antigo?.cor || cores[e?.console] || '#64748b',
      mesa:lider?'lider':antigo?.mesa||'padrao',sala:['CEO','Diretor'].includes(tipo)?'diretoria':'',
      outros_nomes:tipo==='CEO'?['main','lead','leader','team_lead']:
        [...new Set([antigo?.nome,...(antigo?.outros_nomes||[])].filter(Boolean))],
      funcao:`${tipo} · ${e?.console||'console não informado'}${e?.execucao==='local'?' local':''}${especialidade?' · '+especialidade:''}`.slice(0,200),
      time_kanban:tipo==='Equipe'?nome:''};
  };
  return [mesa('CEO','CEO',p.ceo,'',true),mesa('Diretor','Diretor',p.diretor),
    ...(p.equipes||[]).map(e=>mesa(e.nome,'Equipe',e.executor,e.especialidade))];
}
export function destinoEvento(ev, projetoId, demo=false) {
  if (!projetoId || demo) return 'cena';
  if (!ev?.projeto_id) return 'historico';
  return ev.projeto_id===projetoId?'cena':'outro_projeto';
}
export function mudarProjeto(id, local=globalThis.location, armazenamento=globalThis.localStorage) {
  if (!/^[a-f0-9]{20}$/.test(id)) return;
  try { armazenamento?.setItem('office.projeto_cena',id); } catch {}
  const url=new URL(local.href);url.searchParams.set('projeto',id);url.searchParams.delete('agente');
  local.assign(url.href);
}
