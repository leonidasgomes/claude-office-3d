import assert from 'node:assert/strict';
import {estadoNaCena,nomeCiclo} from '../ciclo_cena.mjs';
import fs from 'node:fs';
import vm from 'node:vm';
const agora=100000,dados={ok:true,ts:100,ciclo:{estado:'diretor'},tarefas:[]};
assert.equal(estadoNaCena(dados,'Team QA',agora).livre,true);
assert.equal(estadoNaCena(dados,'CEO',agora).livre,false);
assert.equal(estadoNaCena(dados,'Diretor',agora).texto,'Classificando cartões');
const ocupado={...dados,tarefas:[{cartao:36,equipe:'Team Dev',estado:'executando'}]};
assert.equal(estadoNaCena(ocupado,'Team Dev',agora).livre,false);
assert.equal(estadoNaCena({...ocupado,tarefas:[{cartao:36,equipe:'Team Dev',estado:'revisao'}]},'Team Dev',agora).livre,true);
for(const e of ['incerto','preparando','reservado','estado-novo'])
  assert.equal(estadoNaCena({...ocupado,tarefas:[{cartao:36,equipe:'Team Dev',estado:e}]},'Team Dev',agora).livre,false);
assert.equal(estadoNaCena({...dados,tarefas:[{cartao:628,equipe:'Arch',estado:'bloqueado'}]},'Arch',agora).texto,'#628 · bloqueado');
assert.equal(estadoNaCena({...dados,ok:false},'QA',agora).livre,false);
assert.equal(estadoNaCena(dados,'QA',agora+16000).livre,false);
assert.equal(estadoNaCena({...dados,ciclo:{estado:'limite'}},'CEO',agora).livre,true);
assert.equal(nomeCiclo('imprevisto'),'Estado desconhecido');
// Reutiliza a interrupção real: sai do lazer e preserva a tarefa na fila.
const fonte=fs.readFileSync(new URL('../escritorio.js',import.meta.url),'utf8');
const inicio=fonte.indexOf('function interromperPausa(a)');
const fim=fonte.indexOf('// Uma linha da mensagem',inicio);
const contexto=vm.createContext({agora:()=>100,itemVolta:(a,pts)=>({t:'caminho',volta:true,pts}),
  acaoFim:()=>({t:'sentar'}),encerrarPausa:()=>{}});
vm.runInContext(fonte.slice(inicio,fim),contexto);
const personagem={pausa:{pedirVolta:false},atual:{t:'esperar',pausa:true,sair:['corredor']},
  fila:[{t:'esperar',pausa:true},{t:'trabalho',cartao:36}],fig:{dentro:{visible:false}}};
if(!estadoNaCena(ocupado,'Team Dev',agora).livre)contexto.interromperPausa(personagem);
assert.equal(personagem.pausa.pedirVolta,true);
contexto.aplicarInterrupcao(personagem);
assert.equal(personagem.fig.dentro.visible,true);
assert.equal(personagem.fila[0].volta,true);
assert.equal(personagem.fila.at(-1).cartao,36);
console.log('OK: lazer separado do host, despacho interrompe pausa, reservas incertas e dados antigos falham fechados.');
