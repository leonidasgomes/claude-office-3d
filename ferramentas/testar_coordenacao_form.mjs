import assert from 'node:assert/strict';
import {formularioCoordenacao,renderizarPedidos,botaoExecutarCoordenacao,botaoConciliarPedido} from '../coordenacao_form.mjs';
const criados=[];
class Elemento{
  constructor(tag){this.tag=tag;this.children=[];this.events={};this.value='';criados.push(this);}
  append(...itens){this.children.push(...itens);}
  setAttribute(k,v){this[k]=v;}
  addEventListener(k,f){this.events[k]=f;}
  set innerHTML(v){throw Error('HTML proibido');}
}
globalThis.document={createElement:t=>new Elemento(t)};
let chamadas=[],resolver,atualizou=0;
globalThis.fetch=(url,opts)=>{chamadas.push({url,opts});return new Promise(r=>resolver=r);};
formularioCoordenacao({id:'a'.repeat(20),politica_versao:'b'.repeat(64)},async()=>{atualizou++;});
const form=criados.find(e=>e.tag==='form'),campo=label=>criados.find(e=>e['aria-label']===label);
campo('Objetivo do marco').value='Selecionar trabalho aprovado';campo('Número do cartão').value='42';campo('Pasta absoluta do worktree').value='D:/worktrees/card-42';
const primeiro=form.events.submit({preventDefault(){}});
await form.events.submit({preventDefault(){}});assert.equal(chamadas.length,1);
assert.equal(chamadas[0].url,'/api/gestao/coordenar');
const payload=JSON.parse(chamadas[0].opts.body);
assert.equal(payload.versao,'b'.repeat(64));assert.equal(payload.plano.cartoes[0].cartao,42);
assert.equal('executar' in payload,false);assert.equal(chamadas[0].opts.headers['X-Office-Acao'],'1');
resolver({ok:true,json:async()=>({pedido_id:'c'.repeat(32),estado:'recebida'})});await primeiro;
assert.equal(atualizou,1);assert.match(criados.map(e=>e.textContent||'').join('\n'),/cccccccc recebido/);
const seguinte=form.events.submit({preventDefault(){}});
resolver({ok:false,json:async()=>({erro:'<script>conflito</script>'})});await seguinte;
assert.match(criados.map(e=>e.textContent||'').join('\n'),/<script>conflito/);
const linhas=[];renderizarPedidos({itens:[{id:'d'.repeat(32),estado:'incerto',recibo_id:null}]},{},(_t,s)=>linhas.push(s));
assert.match(linhas.join(' '),/conciliação no PC/);
console.log('Consulta pelo formulário: projeto/versão, sem despacho, envio único e erro textual — OK');
const caixa=botaoExecutarCoordenacao({id:'a'.repeat(20),politica_versao:'b'.repeat(64)},
  {id:'e'.repeat(32),plano_sha256:'f'.repeat(64)},async()=>{atualizou++;});
const botao=caixa.children[0],antes=chamadas.length;
const execucao=botao.events.click();await botao.events.click();assert.equal(chamadas.length,antes+1);
assert.equal(chamadas.at(-1).url,'/api/gestao/coordenacao/executar');
assert.deepEqual(Object.keys(JSON.parse(chamadas.at(-1).opts.body)).sort(),['plano_sha256','projeto_id','recibo_id','versao']);
resolver({ok:true,json:async()=>({pedido_id:'1'.repeat(32)})});await execucao;
assert.equal(botao.disabled,true);assert.equal(atualizou,2);
console.log('Execução registrada: IDs/hash/versão, sem novos caminhos e envio único — OK');
const conciliacao=botaoConciliarPedido({id:'a'.repeat(20),politica_versao:'b'.repeat(64)},{id:'2'.repeat(32)},async()=>{atualizou++;});
const conferir=conciliacao.children[0];
const previa=conferir.events.click();await conferir.events.click();
assert.equal(JSON.parse(chamadas.at(-1).opts.body).acao,'previa');
resolver({ok:true,json:async()=>({evidencia_sha256:'3'.repeat(64),estado_recibo:'organizado'})});await previa;
assert.equal(conferir.textContent,'Confirmar conciliação');assert.equal(atualizou,2);
const confirmar=conferir.events.click();
assert.equal(JSON.parse(chamadas.at(-1).opts.body).evidencia_sha256,'3'.repeat(64));
resolver({ok:true,json:async()=>({estado:'conciliada'})});await confirmar;
assert.equal(atualizou,3);assert.equal(conferir.disabled,true);
console.log('Conciliação: prévia e confirmação separadas, evidência correlacionada — OK');
