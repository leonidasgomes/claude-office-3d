import assert from 'node:assert/strict';
import {formularioCiclo} from '../ciclo_form.mjs';
class E {
  children=[];listeners={};value='';textContent='';open=true;disabled=false;
  append(...x){this.children.push(...x);}setAttribute(){}
  addEventListener(n,f){this.listeners[n]=f;}
  set innerHTML(_){throw Error('HTML proibido');}
}
globalThis.document={createElement:()=>new E()};
let chamadas=[],atualizacoes=0;
globalThis.fetch=async(url,opts)=>{chamadas.push({url,body:JSON.parse(opts.body)});return {ok:true,json:async()=>({versao:'c'.repeat(64),alterado:true})};};
const d=formularioCiclo({id:'p',politica_versao:'b'.repeat(64),ciclo_config:{duracao_min:120}},async()=>atualizacoes++);
const form=d.children[1],minutos=form.children[0].children[0];
minutos.value='241';await form.listeners.submit({preventDefault(){}});assert.equal(chamadas.length,0);
minutos.value='60';await form.listeners.submit({preventDefault(){}});
assert.deepEqual(chamadas[0],{url:'/api/gestao/ciclo',body:{projeto_id:'p',versao:'b'.repeat(64),ciclo:{duracao_min:60}}});
assert.equal(atualizacoes,1);
console.log('OK: duração limitada, versão conferida e atualização sem despacho.');
