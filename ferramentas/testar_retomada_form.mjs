import assert from 'node:assert/strict';
import {formularioRetomada,renderizarRetomadas,botaoConciliarRetomada} from '../retomada_form.mjs';
const criados=[];
class Elemento{
  constructor(tag){this.tag=tag;this.children=[];this.events={};this.checked=false;criados.push(this);}
  append(...itens){this.children.push(...itens);}
  setAttribute(k,v){this[k]=v;}
  addEventListener(k,f){this.events[k]=f;}
  set innerHTML(v){throw Error('HTML proibido');}
}
globalThis.document={createElement:t=>new Elemento(t)};
let chamadas=[],resolver,atualizou=0;
globalThis.fetch=(url,opts)=>{chamadas.push({url,opts});return new Promise(r=>resolver=r);};
const detalhes=formularioRetomada({id:'a'.repeat(20),politica_versao:'b'.repeat(64)},{cartao:'42'},async()=>atualizou++);
const form=criados.find(e=>e.tag==='form'),conferir=criados.find(e=>e.textContent==='Conferir retomada'),
      enviar=criados.find(e=>e.textContent==='Retomar sessão'),checkbox=criados.find(e=>e.type==='checkbox');
assert.equal(enviar.disabled,true);assert.equal(checkbox.disabled,true);
await form.events.submit({preventDefault(){}});assert.equal(chamadas.length,0);
const primeira=conferir.events.click();await conferir.events.click();assert.equal(chamadas.length,1);
assert.equal(chamadas[0].url,'/api/gestao/retomar');assert.equal(chamadas[0].opts.headers['X-Office-Acao'],'1');
assert.deepEqual(JSON.parse(chamadas[0].opts.body),{projeto_id:'a'.repeat(20),versao:'b'.repeat(64),cartao:42,acao:'previa'});
resolver({ok:true,json:async()=>({apenas_previa:true,cartao:42,equipe:'<script>Equipe</script>',console:'codex',confirmacao:'c'.repeat(64)})});await primeira;
assert.equal(checkbox.disabled,false);assert.equal(enviar.disabled,true);
checkbox.checked=true;checkbox.events.change();assert.equal(enviar.disabled,false);
const envio=form.events.submit({preventDefault(){}});await form.events.submit({preventDefault(){}});assert.equal(chamadas.length,2);
assert.deepEqual(JSON.parse(chamadas[1].opts.body),{projeto_id:'a'.repeat(20),versao:'b'.repeat(64),cartao:42,acao:'executar',confirmacao:'c'.repeat(64),agentes_conciliados:true});
resolver({ok:true,json:async()=>({pedido_id:'d'.repeat(32),estado:'recebida'})});await envio;
assert.equal(atualizou,1);assert.equal(detalhes.open,false);assert.equal(enviar.disabled,true);assert.equal(checkbox.checked,false);
const repetida=conferir.events.click();resolver({ok:false,json:async()=>({erro:'<script>Prévia mudou</script>'})});await repetida;
assert.equal(enviar.disabled,true);assert.equal(checkbox.disabled,true);
assert.match(criados.map(e=>e.textContent||'').join('\n'),/<script>Prévia mudou/);
const invalida=conferir.events.click();resolver({ok:true,json:async()=>({apenas_previa:true,cartao:43,confirmacao:'e'.repeat(64),equipe:'Dev',console:'codex'})});await invalida;
assert.equal(enviar.disabled,true);assert.equal(checkbox.disabled,true);
const linhas=[];renderizarRetomadas({problemas:1,limitado:true,itens:[{cartao:42,estado:'concluida',resultado:'bloqueado',codigo:0},{cartao:43,estado:'incerto',resultado:null,codigo:null}]},{},(_t,s)=>linhas.push(s));
assert.match(linhas.join(' '),/cartão bloqueado/);assert.match(linhas.join(' '),/incerta/);assert.match(linhas.join(' '),/dez retomadas/);
console.log('OK: prévia sem execução, confirmação, envio único, payload sem paths/sessões, estados e texto seguro');

const inicio=criados.length;
botaoConciliarRetomada({id:'a'.repeat(20),politica_versao:'b'.repeat(64)},{id:'f'.repeat(32),cartao:42},async()=>atualizou++);
const conciliar=criados.slice(inicio).find(e=>e.tag==='button');
const pre=conciliar.events.click();await conciliar.events.click();const req=chamadas.at(-1);
assert.equal(req.url,'/api/gestao/retomada/conciliar');
assert.deepEqual(JSON.parse(req.opts.body),{projeto_id:'a'.repeat(20),versao:'b'.repeat(64),pedido_id:'f'.repeat(32),acao:'previa'});
resolver({ok:true,json:async()=>({pedido_id:'f'.repeat(32),cartao:42,resultado:'bloqueado',codigo:0,evidencia_sha256:'1'.repeat(64)})});await pre;
assert.equal(conciliar.textContent,'Confirmar conciliação');assert.equal(conciliar.disabled,false);
const con=conciliar.events.click();const req2=JSON.parse(chamadas.at(-1).opts.body);
assert.equal(req2.acao,'aplicar');assert.equal(req2.evidencia_sha256,'1'.repeat(64));
assert.equal('sessao' in req2,false);assert.equal('worktree' in req2,false);
resolver({ok:true,json:async()=>({estado:'conciliada'})});await con;assert.equal(conciliar.disabled,true);assert.equal(atualizou,2);
const outroInicio=criados.length;botaoConciliarRetomada({id:'a',politica_versao:'b'},{id:'f'.repeat(32),cartao:42},async()=>{});
const outro=criados.slice(outroInicio).find(e=>e.tag==='button');const falhou=outro.events.click();
resolver({ok:false,json:async()=>({erro:'<script>retorno ausente</script>'})});await falhou;
assert.equal(outro.disabled,false);assert.match(outro.textContent,/Conferir retorno/);
assert.match(criados.map(e=>e.textContent||'').join(' '),/<script>retorno ausente/);
console.log('OK: conciliação explícita/hash/envio único sem comandos ou vínculos privados');
