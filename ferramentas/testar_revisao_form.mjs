import assert from 'node:assert/strict';
import {formularioRevisao} from '../revisao_form.mjs';
class E {
  children=[];listeners={};value='';textContent='';open=true;
  append(...x){this.children.push(...x);}setAttribute(){}
  addEventListener(n,fn){this.listeners[n]=fn;}
  set innerHTML(_){throw Error('HTML externo proibido');}
}
globalThis.document={createElement:()=>new E()};
let chamadas=[],atualizacoes=0,soltar;
globalThis.fetch=async(url,opts)=>{chamadas.push({url,opts,body:JSON.parse(opts.body)});await new Promise(r=>soltar=r);return {ok:true,json:async()=>({versao:'c'.repeat(64),alterado:true})};};
const d=formularioRevisao({id:'p',politica_versao:'b'.repeat(64),revisao:{ativo:true,clouds_distintas:2,separar_autor:true}},async()=>atualizacoes++);
const form=d.children[1],ativo=form.children[0].children[0],clouds=form.children[1].children[0],separar=form.children[2].children[0];
const enviar=()=>form.listeners.submit({preventDefault(){}});
clouds.value='1.5';await enviar();assert.equal(chamadas.length,0);
ativo.checked=false;ativo.listeners.change();assert.equal(clouds.disabled,true);assert.equal(separar.disabled,true);
clouds.value='2';const pendente=enviar();await enviar();assert.equal(chamadas.length,1);soltar();await pendente;
assert.equal(chamadas[0].url,'/api/gestao/revisao');assert.equal(chamadas[0].opts.headers['X-Office-Acao'],'1');
assert.deepEqual(chamadas[0].body,{projeto_id:'p',versao:'b'.repeat(64),revisao:{ativo:false,clouds_distintas:2,separar_autor:true}});
assert.equal(atualizacoes,1);assert.equal(d.open,false);
ativo.checked=true;ativo.listeners.change();assert.equal(clouds.disabled,false);
globalThis.fetch=async(_url,opts)=>{assert.equal(JSON.parse(opts.body).versao,'c'.repeat(64));return {ok:false,json:async()=>({erro:'Política mudou <script>'})};};
await enviar();assert.match(form.children.at(-1).textContent,/Política mudou <script>/);assert.equal(atualizacoes,1);
console.log('Revisão opcional: payload, validação, concorrência e preservação OK');
