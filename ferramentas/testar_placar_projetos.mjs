// Executa o módulo real do Placar; controla respostas atrasadas e troca de projeto.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const criados=[],ids=new Map(),storage=new Map(),pedidos=[];
class E{
  constructor(tag){this.tag=tag;this.children=[];this.events={};this.style={};this.hidden=true;this.value='';this.classList={toggle(){},add(){},remove(){}};criados.push(this);}
  append(...xs){this.children.push(...xs);}before(x){this.anterior=x;}
  replaceChildren(...xs){this.children=xs;}setAttribute(k,v){this[k]=v;}
  addEventListener(k,f){this.events[k]=f;}
}
const office={CORES_NIVEL:['#aaa'],progressoXp:()=>0,agentes:new Map([['Time A',{cor:0xaaaaaa}]]),emDemo:()=>false,xpDefinir(){},atualizarFicha(){},comemorar(){},merge(){}};
const win={__office:office,events:{},addEventListener(k,f){this.events[k]=f;}};
const doc={body:new E('body'),hidden:false,getElementById(id){if(!ids.has(id))ids.set(id,new E('div'));return ids.get(id);},createElement:t=>new E(t),createTextNode:t=>t,querySelectorAll:()=>[]};
const fetch=(url,opts)=>{
  if(url==='/api/sessao')return Promise.resolve({ok:true,json:async()=>({permissao:'pc'})});
  if(url==='/api/acoes')return Promise.resolve({ok:true,json:async()=>({acoes:[]})});
  return new Promise(resolve=>pedidos.push({url,opts,resolve}));
};
const contexto=vm.createContext({document:doc,window:win,localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v)},
  fetch,console,setTimeout:()=>0,clearTimeout(){},setInterval:()=>0,confirm:()=>true});
const stubs={
  './config.js':'export const CONFIG={xp:{ativo:true,niveis:[]},agentes:[{nome:"Time A"}]};',
  './dica.js':'export const dica=(x)=>x;',
  './indicadores_providers.mjs':'export const instalarIndicadores=()=>{};'
};
const module=new vm.SourceTextModule(fs.readFileSync(new URL('../placar.js',import.meta.url),'utf8'),{context:contexto});
await module.link(async nome=>new vm.SourceTextModule(stubs[nome]||fs.readFileSync(new URL('../kanban_projetos.mjs',import.meta.url),'utf8'),{context:contexto}));
await module.evaluate();
const tick=()=>new Promise(r=>setImmediate(r));
const a='a'.repeat(20),b='b'.repeat(20),versao='c'.repeat(64),projetos=[{id:a,nome:'A'},{id:b,nome:'B'}];
const resposta=(id,repo,xp)=>({fonte:'gestao',projetos,projeto_id:id,politica_versao:versao,repo,agentes:{'Time A':{xp,conferir:[{pr:42}]}},time:{}});
pedidos[0].resolve({ok:true,json:async()=>({fonte:'gestao',projetos,agentes:{},erro:'Selecione o projeto'})});await tick();
const select=criados.find(x=>x['aria-label']==='Projeto do Placar');assert.ok(select);
select.value=a;select.events.change();const pedidoA=pedidos.at(-1);
select.value=b;select.events.change();const pedidoB=pedidos.at(-1);
assert.equal(pedidoA.url,'/xp?projeto='+a);assert.equal(pedidoB.url,'/xp?projeto='+b);
pedidoB.resolve({ok:true,json:async()=>resposta(b,'owner/b',42)});await tick();
pedidoA.resolve({ok:true,json:async()=>resposta(a,'owner/a',999)});await tick();
assert.equal(win.__placar.repo,'owner/b');assert.equal(win.__placar.agente('Time A').xp,42);
assert.ok(storage.has('office.xp.niveis.'+b));assert.equal(storage.has('office.xp.niveis.'+a),false);
const botao=win.__placar.botao('conferido',42);assert.ok(botao);
botao.events.click({stopPropagation(){}});const acao=pedidos.at(-1);
assert.deepEqual(JSON.parse(acao.opts.body),{pr:42,projeto_id:b,versao});
select.value=a;select.events.change();const novoA=pedidos.at(-1);
novoA.resolve({ok:true,json:async()=>resposta(a,'owner/a',5)});await tick();
acao.resolve({ok:true,json:async()=>({ok:true,placar:resposta(b,'owner/b',42)})});await tick();
assert.equal(win.__placar.repo,'owner/a');assert.equal(win.__placar.agente('Time A').xp,5);
assert.equal(criados.find(x=>x.id==='placarToast').hidden,true);
const antesAlerta=pedidos.length;
win.events['office-projeto-alerta']({detail:{painel:'prs',projeto:b}});assert.equal(pedidos.length,antesAlerta);
win.events['office-projeto-alerta']({detail:{painel:'placar',projeto:b}});
assert.equal(pedidos.at(-1).url,'/xp?projeto='+b);
const comAuditor=resposta(b,'owner/b',11);
comAuditor.auditor={ativo:true,limite:'Parecer histórico; não autoriza merge',pareceres:[{pr:42,sha:'d'.repeat(40),estado:'concluido',veredito:'suspeito',
  pareceres:[{nome:'Revisor',cloud_declarada:'google',resposta:{motivo:'<script>não executar</script>',evidencia:'teste.py:1'}}]}]};
pedidos.at(-1).resolve({ok:true,json:async()=>comAuditor});await tick();
assert.equal(win.__placar.repo,'owner/b');
ids.get('btnPlacar').events.click();
assert.ok(criados.some(x=>x.tag==='summary' && x.textContent==='Auditor independente · pareceres consultivos'));
assert.ok(criados.some(x=>x.tag==='p' && x.textContent?.includes('<script>não executar</script>')));
console.log('Placar real: seleção, respostas fora de ordem, storage separado e ação vinculada ao projeto — OK');
