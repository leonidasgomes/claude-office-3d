import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
class El {
  constructor(){this.children=[];this.textContent='';this.hidden=true;this.classList={add(){},remove(){},contains(){return false;},toggle(){}};this.dataset={};}
  append(...e){this.children.push(...e);} before(){} replaceChildren(...e){this.children=e;} setAttribute(){} addEventListener(){} querySelector(){return null;} querySelectorAll(){return [];} focus(){}
}
const elements=new Map();const get=id=>{if(!elements.has(id))elements.set(id,new El());return elements.get(id);};
const pid='a'.repeat(20);let url='/saude?projeto='+pid;const pedidos=[];
const contexto={document:{getElementById:get,createElement:()=>new El(),createTextNode:t=>({textContent:t}),addEventListener(){},hidden:false,body:new El(),documentElement:new El()},window:{addEventListener(){}},CONFIG:{github:{prs:true}},temServidor:true,dica:()=>new El(),localStorage:{getItem(){return null;}},seletorProjetos:()=>({url:()=>url,receber(){},selecionar(){}}),setTimeout(){},clearTimeout(){},Date,Set,Map,console,
fetch:async u=>{pedidos.push(u);return {ok:true,status:200,json:async()=>u==='/api/sessao'?{permissao:'pc'}:u==='/api/praticas'?{projetos:[]}:{fonte:'gestao',projeto_id:pid,ts:Date.now()/1000,sem_prs:false,sem_parados:true,circulos:[],rascunhos:[],duplicados:{fortes:[],fracos:[]},prs:{prs:[{numero:1}],erro:''}}};}};
vm.createContext(contexto);const fonte=fs.readFileSync('saude_painel.js','utf8').replace(/^import .*;\r?\n/gm,'');vm.runInContext(fonte,contexto);
get('saude').hidden=false; await contexto.window.__saude.carregar();
assert(pedidos.includes(url));assert(!pedidos.includes('/prs'));
const texto=e=>[e.textContent||'',...(e.children||[]).map(texto)].join(' ');
const visivel=texto(get('saudeCorpo'));
assert(visivel.includes('1 PR(s) aberto(s)'));assert(!visivel.includes('Nenhum PR aberto.'));
assert(visivel.includes('PRs parados: avaliação pendente'));assert(!visivel.includes('GitHub fora do ar'));
assert(!visivel.includes('Silenciados pela triagem'));assert(get('saudeInfo').textContent.includes('por projeto'));
console.log('Saúde: projeto, PRs sem tamanho, avaliação parcial e legado isolado — OK');


