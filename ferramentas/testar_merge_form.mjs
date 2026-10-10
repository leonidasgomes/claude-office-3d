import assert from 'node:assert/strict';
import {formularioMerge} from '../merge_form.mjs';
class E {
  children=[];listeners={};value='';textContent='';open=true;
  append(...x){this.children.push(...x);}setAttribute(){}
  addEventListener(n,fn){this.listeners[n]=fn;}
  set innerHTML(_){throw Error('HTML externo proibido');}
}
globalThis.document={createElement:()=>new E()};
let chamadas=[],atualizacoes=0,soltar;
globalThis.fetch=async(url,opts)=>{chamadas.push({url,opts,body:JSON.parse(opts.body)});await new Promise(r=>soltar=r);return {ok:true,json:async()=>({versao:'c'.repeat(64),alterado:true})};};
const d=formularioMerge({id:'p',politica_versao:'b'.repeat(64),merge_config:{modo:'manual',checks:[],rotulos_manuais:['merge-manual']}},async()=>atualizacoes++);
const form=d.children[1],modo=form.children[0].children[0],checks=form.children[1].children[0],rotulos=form.children[2].children[0];
const enviar=()=>form.listeners.submit({preventDefault(){}});
modo.value='automatico';await enviar();assert.equal(chamadas.length,0);
assert.match(form.children.at(-1).textContent,/ao menos um check/);
checks.value='CI\n CI';await enviar();assert.equal(chamadas.length,0);
checks.value='CI\r\n<script>nome</script>\n';rotulos.value='merge-manual';
const pendente=enviar();await enviar();assert.equal(chamadas.length,1);soltar();await pendente;
assert.equal(chamadas[0].url,'/api/gestao/merge');
assert.equal(chamadas[0].opts.headers['X-Office-Acao'],'1');
assert.deepEqual(chamadas[0].body,{projeto_id:'p',versao:'b'.repeat(64),merge:{modo:'automatico',checks:['CI','<script>nome</script>'],rotulos_manuais:['merge-manual']}});
assert.equal(atualizacoes,1);assert.equal(d.open,false);
globalThis.fetch=async(_url,opts)=>{assert.equal(JSON.parse(opts.body).versao,'c'.repeat(64));return {ok:false,json:async()=>({erro:'Política mudou <script>'})};};
await enviar();assert.match(form.children.at(-1).textContent,/Política mudou <script>/);assert.equal(atualizacoes,1);
console.log('Merge por projeto: payload, validação, concorrência e texto seguro OK');
