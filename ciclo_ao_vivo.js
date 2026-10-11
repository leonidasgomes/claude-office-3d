// Uma consulta leve por projeto; nenhum comando, modelo ou atualização de formulário.
import { PROJETO_CENA } from './config.js';
import { nomeCiclo } from './ciclo_cena.mjs';
let dados=null;
let ultimaVista='';
let fluxoAtivo=false,timer=null,consultando=false;
const agendar=ms=>{clearTimeout(timer);timer=setTimeout(consultar,ms);};
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
  criar('p',c.continuo===true?'Operação contínua':`${min} min restantes`);
}
async function consultar() {
  if(!PROJETO_CENA)return;
  if(consultando)return;
  if(document.hidden){agendar(5000);return;}
  consultando=true;
  const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),4000);
  try{
    const r=await fetch('/api/gestao/ciclo?projeto='+PROJETO_CENA.id,{cache:'no-store',signal:controller.signal});
    if(!r.ok)throw Error('Estado indisponível');
    const novo=await r.json();
    if(novo.projeto_id!==PROJETO_CENA.id)throw Error('Projeto não confirmado');
    dados=novo;
  }catch{dados={ok:false,erro:'Acompanhamento indisponível; confira Gestão. Equipes não foram interrompidas.'};}
  finally{clearTimeout(timeout);consultando=false;}
  const vista=JSON.stringify([dados?.ok,dados?.erro,dados?.ciclo?.estado,dados?.ciclo?.continuo,
    Math.ceil(((dados?.ciclo?.limite||0)-Date.now()/1000)/60)]);
  if(vista!==ultimaVista){
    ultimaVista=vista;desenhar();
  }
  agendar(fluxoAtivo?10000:2000); // Batida mantém a validade da projeção de presença.
}
window.addEventListener('office-fluxo',e=>{fluxoAtivo=e.detail?.ativo===true;agendar(0);});
window.addEventListener('office-dados-atualizados',()=>agendar(0));
desenhar();consultar();
