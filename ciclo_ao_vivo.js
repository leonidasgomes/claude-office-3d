// Uma consulta leve por projeto; nenhum comando, modelo ou atualização de formulário.
import { PROJETO_CENA } from './config.js';
import { nomeCiclo } from './ciclo_cena.mjs';
let dados=null;
let ultimaVista='';
export const estadoDoEscritorio = () => dados;
const painel=document.createElement('section');painel.id='cicloAoVivo';painel.hidden=!PROJETO_CENA;
painel.setAttribute('aria-label','Acompanhamento ao vivo');
document.getElementById('gavetaCorpo').prepend(painel);
const criar=(tag,texto,pai=painel)=>{const e=document.createElement(tag);e.textContent=texto;pai.append(e);return e;};
function desenhar() {
  painel.replaceChildren();criar('h2','Acompanhamento ao vivo');
  if(!dados?.ok){criar('p',dados?.erro||'Consultando estado local…');return;}
  const c=dados.ciclo||{},min=Math.max(0,Math.ceil(((c.limite||Date.now()/1000)-Date.now()/1000)/60));
  criar('strong',nomeCiclo(c.estado));
  criar('p',`${min} min restantes${c.objetivo?' · último objetivo GDD: '+c.objetivo:''}`);
  if(c.estado==='implementando')criar('p',(c.cartoes||[]).map(t=>`#${t.cartao} · ${t.equipe}`).join(', '));
  else if((c.cartoes||[]).length)criar('small',`${c.cartoes.length} candidatos em avaliação; não são equipes em execução.`);
  const detalhes=document.createElement('details');painel.append(detalhes);criar('summary','Entregas e bloqueios',detalhes);
  if(c.proxima_acao)criar('p',c.proxima_acao,detalhes);
  if(c.motivo&&['erro','aguardando','investigando','limite','pausado'].includes(c.estado))criar('p',c.motivo,detalhes);
  for(const t of dados.tarefas||[])criar('p',`#${t.cartao} · ${t.equipe} · ${t.estado}`,detalhes);
  for(const p of dados.publicacoes||[]){const a=criar('a',`#${p.cartao} — abrir PR`,detalhes);a.href=p.pr;a.target='_blank';a.rel='noopener';}
  criar('small','Estado registrado pelo host; lazer na cena não é execução de agente.',detalhes);
}
async function consultar() {
  if(!PROJETO_CENA)return;
  if(document.hidden){setTimeout(consultar,5000);return;}
  const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),4000);
  const aberto=!!painel.querySelector('details[open]');
  try{
    const r=await fetch('/api/gestao/ciclo?projeto='+PROJETO_CENA.id,{cache:'no-store',signal:controller.signal});
    if(!r.ok)throw Error('Estado indisponível');
    const novo=await r.json();
    if(novo.projeto_id!==PROJETO_CENA.id)throw Error('Projeto não confirmado');
    dados=novo;
  }catch{dados={ok:false,erro:'Acompanhamento indisponível; confira Gestão. Equipes não foram interrompidas.'};}
  finally{clearTimeout(timeout);}
  const vista=JSON.stringify([dados?.ok,dados?.erro,dados?.ciclo,dados?.tarefas,dados?.publicacoes,
    Math.ceil(((dados?.ciclo?.limite||0)-Date.now()/1000)/60)]);
  if(vista!==ultimaVista){
    ultimaVista=vista;desenhar();if(aberto&&painel.querySelector('details'))painel.querySelector('details').open=true;
  }
  setTimeout(consultar,2000);
}
desenhar();consultar();
