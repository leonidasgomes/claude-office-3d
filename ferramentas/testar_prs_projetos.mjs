import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
const raiz=path.resolve(import.meta.dirname,'..');
const fonte=fs.readFileSync(path.join(raiz,fs.existsSync(path.join(raiz,'office one')) ? 'office one/prs.js' : 'prs.js'),'utf8');
class Elemento {
  hidden=true; children=[]; style={}; textContent='';
  append(...filhos) {this.children.push(...filhos);}
  addEventListener() {}
  setAttribute() {}
  set innerHTML(_) {throw new Error('HTML externo proibido');}
}
const elementos=new Map();const chamadas=[];const respostas=[];
const janela={addEventListener(){},dispatchEvent(){}};
let escolhido='um';
const contexto=vm.createContext({
  console,CONFIG:{github:{prs:false,times:{},check_revisao:'legado'}},LIDER:null,temServidor:true,
  agenteConfig:()=>null,dica:()=>new Elemento(),detalhesEvidencias:()=>new Elemento(),
  document:{hidden:false,createElement:()=>new Elemento(),getElementById:id=>{
    if(!elementos.has(id)) elementos.set(id,new Elemento());return elementos.get(id);
  }},window:janela,CustomEvent:class {},setInterval(){},
  seletorProjetos:()=>({url:()=>'/prs?projeto='+escolhido,receber(){}}),
  fetch:url=>{chamadas.push(url);return new Promise(resolve=>respostas.push(resolve));}
});
vm.runInContext(fonte.replace(/^import .*;\r?\n/gm,''),contexto);
const inicial=respostas.length;
const um=janela.__prs.carregar();escolhido='dois';const dois=janela.__prs.carregar(true);
const dados=repo=>({fonte:'gestao',configurado:true,repo,prs:[{
  numero:42,titulo:repo,url:'https://github.com/'+repo+'/pull/42',branch:'feat/x',rascunho:false,
  rotulos:[],fecha:[],revisao:'SUCCESS',validacao:'Revisões pendentes'
}],atualizado:'12:00'});
respostas[inicial+1]({json:async()=>dados('owner/dois')});await dois;
respostas[inicial]({json:async()=>dados('owner/um')});await um;
assert.equal(janela.__prs.dados.repo,'owner/dois');
assert.equal(janela.__prs.situacao(janela.__prs.dados.prs[0]).classe,'espera');
assert.deepEqual(chamadas.slice(inicial),['/prs?projeto=um','/prs?projeto=dois&forcar=1']);
assert.equal(elementos.get('prsConta').hidden,true);
console.log('PRs: resposta antiga descartada, seleção preservada e aprovação/sugestões legadas isoladas — OK');
