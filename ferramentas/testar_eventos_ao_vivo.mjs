import assert from 'node:assert/strict';
import {fluxoEventos} from '../eventos_ao_vivo.mjs';
class Fonte {
  constructor(url){this.url=url;this.listeners={};Fonte.instancia=this;}
  addEventListener(tipo,fn){this.listeners[tipo]=fn;}
  close(){this.fechado=true;}
}
let cursor=3,recebidos=[],estados=[],gestao=0,reinicios=0;
const f=fluxoEventos({cursor:()=>cursor,receber:(ev,id)=>{cursor=id;recebidos.push(ev);},
  gestao:()=>gestao++,reiniciar:()=>reinicios++,conexao:v=>estados.push(v),EventSource:Fonte});
f.abrir();const fonte=Fonte.instancia;assert.match(fonte.url,/desde=3/);
fonte.onopen();assert.equal(f.ativo,true);
fonte.listeners.evento({lastEventId:'4',data:'{"tipo":"fala"}'});
fonte.listeners.evento({lastEventId:'4',data:'{"tipo":"fala"}'});
fonte.listeners.evento({lastEventId:'5',data:'invalido'});
assert.equal(recebidos.length,1);assert.equal(cursor,4);
fonte.onerror();assert.equal(f.ativo,false);assert.deepEqual(estados,[true,false]);
fonte.listeners.gestao({});assert.equal(gestao,1);
fonte.listeners.reiniciar({});assert.equal(reinicios,1);assert.equal(fonte.fechado,true);
console.log('SSE: cursor, duplicação, falha, invalidação e reinício verificados');
