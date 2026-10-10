import assert from 'node:assert/strict';
import {formularioExecutores} from '../executores_form.mjs';
class E {
  children=[];listeners={};value='';textContent='';disabled=false;open=true;
  constructor(tag){this.tag=tag;}
  append(...els){this.children.push(...els);}
  replaceChildren(...els){this.children=els;}
  setAttribute(){}
  addEventListener(t,fn){this.listeners[t]=fn;}
  set innerHTML(_){throw Error('HTML externo proibido');}
}
globalThis.document={createElement:t=>new E(t),createTextNode:t=>({textContent:t})};
let chamadas=[],atualizacoes=0,erro=false;
globalThis.fetch=async(url,opts)=>{chamadas.push({url,opts,body:JSON.parse(opts.body)});return {ok:!erro,json:async()=>erro?{erro:'Política mudou; recarregue'}:{versao:'novo',alterado:true}};};
const projeto={id:'registrado',politica_versao:'atual',ceo:{console:'claude',modelo:'sonnet'},diretor:{console:'codex',modelo:''},local:{ativo:false},equipes:[{nome:'Dev<script>',executor:{console:'gemini',modelo:''}}]};
const d=formularioExecutores(projeto,async()=>atualizacoes++);
const form=d.children[1],fs=form.children[0];
const seletor=fs.children[1].children[1],modelo=fs.children[2].children[1];
seletor.value='gemini';seletor.listeners.change();assert.equal(modelo.value,'');
await form.listeners.submit({preventDefault(){}});
assert.equal(chamadas.length,1);assert.equal(chamadas[0].url,'/api/gestao/executores');
assert.equal(chamadas[0].opts.headers['X-Office-Acao'],'1');
assert.equal(chamadas[0].body.projeto_id,'registrado');assert.equal(chamadas[0].body.versao,'atual');
assert.equal(chamadas[0].body.executores.ceo.console,'gemini');assert.equal(chamadas[0].body.executores.equipes[0].nome,'Dev<script>');
assert.equal(atualizacoes,1);assert.equal(d.open,false);
erro=true;await form.listeners.submit({preventDefault(){}});
assert.equal(chamadas[1].body.versao,'novo');assert.equal(atualizacoes,1);
assert.match(form.children.at(-1).textContent,/Política mudou/);
assert.equal(form.children.at(-2).disabled,false);
const outro=formularioExecutores({...projeto,ceo:{console:'opencode',modelo:'opencode/anterior',cloud:'declarada'}},async()=>{});
const campo=outro.children[1].children[0],catalogo=campo.children[6],consultar=catalogo.children[0],lista=catalogo.children[1];
const inputModelo=campo.children[2].children[1],inputCloud=campo.children[4].children[1];
assert.equal(catalogo.hidden,false);
globalThis.fetch=async(url,opts)=>{
  assert.equal(url,'/api/gestao/modelos');assert.deepEqual(JSON.parse(opts.body),{console:'opencode'});
  assert.equal(opts.headers['X-Office-Acao'],'1');
  return {ok:true,json:async()=>({ok:true,modelos:[{id:'opencode/free',nome:'<script>Modelo</script>'}],limite:'Custo declarado; disponibilidade não comprovada.'})};
};
await consultar.listeners.click();
assert.equal(inputModelo.value,'opencode/anterior');assert.equal(inputCloud.value,'declarada');
assert.equal(lista.children[1].textContent,'<script>Modelo</script> · opencode/free');
lista.value='opencode/free';lista.listeners.change();
assert.equal(inputModelo.value,'opencode/free');assert.equal(inputCloud.value,'');
let enviado;
globalThis.fetch=async(url,opts)=>{
  assert.equal(url,'/api/gestao/executores');enviado=JSON.parse(opts.body);
  return {ok:true,json:async()=>({versao:'nova',alterado:true})};
};
await outro.children[1].listeners.submit({preventDefault(){}});
assert.equal(enviado.executores.ceo.modelo,'opencode/free');
assert.equal(Object.hasOwn(enviado.executores.ceo,'cloud'),false);
globalThis.fetch=async()=>({ok:false,json:async()=>({erro:'Consulta falhou'})});
await consultar.listeners.click();
assert.equal(lista.hidden,true);assert.equal(inputModelo.value,'opencode/free');assert.equal(consultar.disabled,false);
console.log('Executores: fonte por projeto, modelo limpo ao trocar console, versão/conflicto e texto seguro — OK');
