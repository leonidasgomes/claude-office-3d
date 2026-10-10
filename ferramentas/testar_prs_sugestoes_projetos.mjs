import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const criados=[],ids=new Map(),pedidos=[];
class E{
  constructor(tag){this.tag=tag;this.children=[];this.events={};this.style={};this.hidden=true;this.value='';this.classList={toggle(){},add(){},remove(){}};criados.push(this);}
  append(...xs){this.children.push(...xs);}before(x){this.anterior=x;}
  replaceChildren(...xs){this.children=xs;}setAttribute(k,v){this[k]=v;}addEventListener(k,f){this.events[k]=f;}
  set textContent(v){this.texto=v;this.children=[];}get textContent(){return this.texto||'';}
}
const win={events:{},addEventListener(k,f){this.events[k]=f;},dispatchEvent(){}};
const doc={hidden:false,getElementById(id){if(!ids.has(id))ids.set(id,new E('div'));return ids.get(id);},createElement:t=>new E(t)};
const fetch=(url,opts)=>url==='/api/sessao'?Promise.resolve({ok:true,json:async()=>({permissao:'pc'})}):new Promise(resolve=>pedidos.push({url,opts,resolve}));
const contexto=vm.createContext({document:doc,window:win,fetch,console,setInterval:()=>0,CustomEvent:class{},confirm:()=>true});
const stubs={
  './config.js':'export const CONFIG={github:{prs:true}};export const agenteConfig=()=>null;export const LIDER={};export const temServidor=true;',
  './dica.js':'export const dica=(x)=>x;',
  './prs_evidencias.mjs':'export const detalhesEvidencias=()=>null;'
};
const module=new vm.SourceTextModule(fs.readFileSync(new URL('../prs.js',import.meta.url),'utf8'),{context:contexto});
await module.link(async nome=>new vm.SourceTextModule(stubs[nome]||fs.readFileSync(new URL('../kanban_projetos.mjs',import.meta.url),'utf8'),{context:contexto}));await module.evaluate();
const tick=()=>new Promise(r=>setImmediate(r)),a='a'.repeat(20),b='b'.repeat(20),versao='c'.repeat(64),projetos=[{id:a,nome:'A'},{id:b,nome:'B'}];
const pr={numero:42,titulo:'Mudança',branch:'feat/42',fecha:[],rotulos:[],revisao:'SUCCESS',sha:'d'.repeat(40),url:'https://github.com/owner/a/pull/42'};
const dados=id=>({fonte:'gestao',projeto_id:id,projetos,repo:'owner/'+(id===a?'a':'b'),prs:[pr]});
const caixa=(id,n=1)=>({ok:true,fonte:'gestao',projeto_id:id,politica_versao:versao,repo:'owner/'+(id===a?'a':'b'),ativo:true,
  itens:[{id:'7',pr:42,prioridade:'P1',titulo:'Revisão',situacao:'nova'}],seguram_merge:{42:n},por_pr:{42:{total:n}},pronto:{}});
pedidos[0].resolve({ok:true,json:async()=>dados(a)});await tick();const caixaA=pedidos.at(-1);assert.equal(caixaA.url,'/api/sugestoes?projeto='+a);
const select=criados.find(e=>e['aria-label']==='Projeto dos PRs');select.value=b;select.events.change();
pedidos.at(-1).resolve({ok:true,json:async()=>dados(b)});await tick();const caixaB=pedidos.at(-1);assert.equal(caixaB.url,'/api/sugestoes?projeto='+b);
caixaB.resolve({ok:true,json:async()=>caixa(b,2)});await tick();caixaA.resolve({ok:true,json:async()=>caixa(a,99)});await tick();
assert.match(win.__prs.situacao(pr).rotulo,/2 sugestão/);
const resolver=criados.findLast(e=>e.tag==='button' && e.textContent==='Resolvido');assert.ok(resolver);
const tratando=resolver.events.click();await tick();const acao=pedidos.at(-1);
assert.deepEqual(JSON.parse(acao.opts.body),{id:'7',acao:'resolvida',projeto_id:b,versao});
select.value=a;select.events.change();pedidos.at(-1).resolve({ok:true,json:async()=>dados(a)});await tick();
pedidos.at(-1).resolve({ok:true,json:async()=>caixa(a,1)});await tick();
acao.resolve({ok:true,json:async()=>({ok:true,sugestoes:caixa(b,20)})});await tratando;
assert.equal(win.__prs.dados.repo,'owner/a');assert.match(win.__prs.situacao(pr).rotulo,/1 sugestão/);
assert.equal(pedidos.some(p=>p.url==='/api/sugestoes'),false);
const antes=pedidos.length;
win.events['office-projeto-alerta']({detail:{painel:'placar',projeto:b}});assert.equal(pedidos.length,antes);
win.events['office-projeto-alerta']({detail:{painel:'prs',projeto:'caminho/invalido'}});assert.equal(pedidos.length,antes);
win.events['office-projeto-alerta']({detail:{painel:'prs',projeto:b}});assert.equal(pedidos.at(-1).url,'/prs?projeto='+b);
pedidos.at(-1).resolve({ok:true,json:async()=>dados(b)});await tick();
pedidos.at(-1).resolve({ok:true,json:async()=>caixa(b,3)});await tick();
assert.equal(win.__prs.dados.projeto_id,b);assert.match(win.__prs.situacao(pr).rotulo,/3 sugestão/);
console.log('PRs reais: caixa por projeto, busca fora de ordem e tratamento com ID/versão sem trocar seleção — OK');
