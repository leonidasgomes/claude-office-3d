import assert from 'node:assert/strict';
import { formularioAgenteNativo } from '../agentes_nativos_form.mjs';
const criados=[];
class E {
  constructor(tag){this.tag=tag;this.children=[];this.events={};criados.push(this);}
  append(...es){this.children.push(...es);} setAttribute(k,v){this[k]=v;}
  addEventListener(k,v){this.events[k]=v;}
  set innerHTML(_){throw Error('HTML externo proibido');}
}
globalThis.document={createElement:t=>new E(t)};
let chamadas=[];let estado='ausente',falha=false;
globalThis.fetch=async(url,opts)=>{
  chamadas.push(JSON.parse(opts.body));assert.equal(url,'/api/gestao/funcionarios/perfil');
  assert.equal(opts.headers['X-Office-Acao'],'1');
  return {ok:!falha,status:409,json:async()=>falha?{erro:'Prévia mudou'}:{arquivo:'.claude/agents/office-id.md',estado:JSON.parse(opts.body).aplicar?'atual':estado,conteudo:'<script>texto</script>',confirmacao:'a'.repeat(64),limite:'Não inicia modelos',criado:true}};
};
formularioAgenteNativo({id:'projeto'},{id:'funcionario',nome:'<script>História</script>'});
const botoes=criados.filter(e=>e.tag==='button');
assert.equal(chamadas.length,0);assert.equal(botoes[1].disabled,true);
await botoes[0].events.click();assert.equal(chamadas[0].aplicar,false);assert.equal(botoes[1].disabled,false);
assert.match(criados.find(e=>e.tag==='pre').textContent,/<script>texto<\/script>/);
await botoes[1].events.click();assert.equal(chamadas[1].confirmacao,'a'.repeat(64));assert.equal(chamadas[1].aplicar,true);
assert.ok(criados.some(e=>e.tag==='p' && e.textContent.includes('Estado do perfil: arquivo corresponde às fontes atuais')));
assert.equal(botoes[1].disabled,true);await botoes[1].events.click();assert.equal(chamadas.length,2);
estado='divergente';await botoes[0].events.click();assert.equal(botoes[1].disabled,true);
estado='ausente';await botoes[0].events.click();falha=true;await botoes[1].events.click();
assert.equal(botoes[1].disabled,true);assert.match(criados.find(e=>e.role==='status').textContent,/Prévia mudou/);
const antes=chamadas.length;
for(const [estado,texto] of Object.entries({ausente:'ainda não criado',atual:'fontes atuais',divergente:'arquivo preservado',indisponivel:'não foi possível conferir',gerenciado:'modelo local'})) {
  const inicio=criados.length;
  formularioAgenteNativo({id:'projeto'},{id:'funcionario',nome:'Especialista',perfil_nativo:{estado}});
  assert.ok(criados.slice(inicio).some(e=>e.tag==='p' && e.textContent.includes(texto)));
  assert.ok(criados.slice(inicio).some(e=>e.tag==='p' && e.textContent.includes('Não comprova descoberta')));
  if(estado==='gerenciado')assert.equal(criados.slice(inicio).filter(e=>e.tag==='button').length,0);
}
assert.equal(chamadas.length,antes);
console.log('Perfis: estado canônico, prévia/criação, versão, conflitos, sem escrita automática e texto literal — OK');
