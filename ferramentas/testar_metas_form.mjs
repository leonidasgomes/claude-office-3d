import assert from 'node:assert/strict';
import {formularioMetas,renderizarMetas} from '../metas_form.mjs';
class E {children=[];listeners={};value='';textContent='';open=true;disabled=false;checked=false;
  append(...x){this.children.push(...x);}setAttribute(){}addEventListener(n,f){this.listeners[n]=f;}
  set innerHTML(_){throw Error('HTML proibido');}}
globalThis.document={createElement:()=>new E()};
let chamadas=[],refresh=0;
globalThis.fetch=async(url,opts)=>{chamadas.push({url,body:JSON.parse(opts.body)});return {ok:true,json:async()=>({versao:'c'.repeat(64),alterado:true})};};
const d=formularioMetas({id:'p',politica_versao:'b'.repeat(64),metas_config:{ativo:false,tempo_min:60,tokens:100000}},async()=>refresh++);
const f=d.children[1],ativo=f.children[0].children[0],tempo=f.children[1].children[0],tokens=f.children[2].children[0];
tokens.value='999';await f.listeners.submit({preventDefault(){}});assert.equal(chamadas.length,0);
tokens.value='100000';tempo.value='1.5';await f.listeners.submit({preventDefault(){}});assert.equal(chamadas.length,0);
tempo.value='45';ativo.checked=true;await f.listeners.submit({preventDefault(){}});
assert.deepEqual(chamadas[0],{url:'/api/gestao/metas',body:{projeto_id:'p',versao:'b'.repeat(64),metas:{ativo:true,tempo_min:45,tokens:100000}}});
assert.equal(refresh,1);
const alvo=new E();renderizarMetas({itens:[{cartao:42,equipe:'Dev',estado:'em_revisao',objetivo:'<script>abc',objetivo_gdd:'Navegar',limites:{tempo_min:45,tokens:100000},tokens_observados:null,atualizado:1}]},alvo,(tag,text,parent)=>{const e=new E();e.textContent=text;parent.append(e);});
assert.match(alvo.children[1].children[3].textContent,/não significa zero/);
console.log('OK: metas configuráveis, envio restrito, limites e consumo ausente.');
