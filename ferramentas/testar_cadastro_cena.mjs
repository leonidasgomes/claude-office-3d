import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {projetosDaCena,selecionarProjeto,mesasDoProjeto,destinoEvento,mudarProjeto} from '../cadastro_cena.mjs';
const a={id:'a'.repeat(20),nome:'Jogo',ativo:true,ceo:{console:'codex'},diretor:{console:'codex'},
  equipes:[{nome:'Team Dev',especialidade:'Gameplay',executor:{console:'codex'}}],funcionarios:[]};
const b={...a,id:'b'.repeat(20),nome:'Outro',equipes:[{nome:'Pesquisa',executor:{console:'opencode'}}]};
const lista=projetosDaCena({projetos:[a,b,{...a,erro:'invalido'}, {...a,ativo:false}]});
assert.equal(lista.length,2);assert.equal(selecionarProjeto(lista,b.id),b);
assert.equal(selecionarProjeto(lista,'removido'),a);assert.equal(selecionarProjeto([],a.id),null);
const mesas=mesasDoProjeto(a,[{nome:'Team_Dev',titulo:'Team Dev',cor:'#123456',outros_nomes:['Dev antigo']}]);
assert.deepEqual(mesas.map(m=>m.titulo),['CEO','Diretor','Team Dev']);
assert.equal(mesas[0].lider,true);assert.equal(mesas[2].lider,false);
assert.equal(mesas[2].console,'codex');assert.equal(mesas[2].cor,'#123456');
assert.ok(mesas[2].outros_nomes.includes('Team_Dev'));assert.ok(mesas[2].funcao.includes('codex'));
assert.equal(mesasDoProjeto(b).some(m=>m.titulo==='Team Dev'),false);
assert.equal(destinoEvento({projeto_id:a.id},a.id),'cena');
assert.equal(destinoEvento({projeto_id:b.id},a.id),'outro_projeto');
assert.equal(destinoEvento({agente:'Team_Dev'},a.id),'historico');
assert.equal(destinoEvento({},null),'cena');assert.equal(destinoEvento({},a.id,true),'cena');
let destino;let guardado;
mudarProjeto(b.id,{href:'http://localhost:8788/?agente=Dev',assign:u=>destino=u},{setItem:(k,v)=>guardado=v});
assert.equal(guardado,b.id);assert.equal(new URL(destino).searchParams.get('projeto'),b.id);
assert.equal(new URL(destino).searchParams.has('agente'),false);

// Executa config.js real com o servidor: todos os consumidores usam o mesmo cadastro selecionado.
const elementos={projetoCena:{children:[],append(o){this.children.push(o)},addEventListener(){}},projetoCenaInfo:{}};
const antigo={agentes:[{nome:'Team_Dev',titulo:'Team Dev',cor:'#123456'}]};
const contexto=vm.createContext({projetosDaCena,selecionarProjeto,mesasDoProjeto,mudarProjeto,
  URLSearchParams,AbortController,setTimeout,clearTimeout,location:{search:'?projeto='+b.id},localStorage:{getItem:()=>null},
  document:{getElementById:n=>elementos[n],createElement:()=>({})},
  fetch:async url=>({ok:true,json:async()=>url==='/config'?antigo:{projetos:[a,b]}})});
const fonte=fs.readFileSync(new URL('../config.js',import.meta.url),'utf8').replace(/^import .*;\r?\n/gm,'').replace(/^export /gm,'');
await vm.runInContext('(async()=>{'+fonte+';return {CONFIG,PROJETO_CENA,LIDER};})()',contexto).then(r=>{
  assert.equal(r.PROJETO_CENA.id,b.id);assert.equal(r.CONFIG.agentes.length,3);
  assert.equal(r.LIDER.nome,'CEO');assert.equal(r.CONFIG.agentes[2].console,'opencode');
});
assert.equal(elementos.projetoCena.children.length,2);
assert.ok(elementos.projetoCenaInfo.textContent.includes('3 mesas'));
console.log('OK: cadastro único, projeto selecionado, aliases e histórico sem atribuição');
