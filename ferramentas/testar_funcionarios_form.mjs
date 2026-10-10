import assert from 'node:assert/strict';
import fs from 'node:fs';
const fonte=fs.readFileSync(new URL('../funcionarios_form.js',import.meta.url),'utf8');
const {formularioFuncionarios}=await import('data:text/javascript;base64,'+Buffer.from(fonte).toString('base64'));
const criados=[];
class Elemento {
  constructor(tag) {this.tag=tag;this.children=[];this.events={};this.value='';criados.push(this);}
  append(...itens) {this.children.push(...itens);if(this.tag==='select'&&!this.value) this.value=itens[0]?.value||'';}
  replaceChildren(...itens) {this.children=itens;}
  setAttribute(nome,valor) {this[nome]=valor;}
  addEventListener(nome,fn) {this.events[nome]=fn;}
  reset() {}
  set innerHTML(_) {throw new Error('HTML externo proibido');}
}
globalThis.document={createElement:tag=>new Elemento(tag),createTextNode:texto=>({textContent:texto})};
const pendente={estado:'adaptacao-pendente',pendencias:['hooks']},livre={estado:'instrucoes',pendencias:[]};
formularioFuncionarios({id:'projeto',equipes:[{nome:'Dev'}],local:{ativo:true},skills:[
  {nome:'restrita',descricao:'Claude',compatibilidade:{claude:livre,codex:pendente,claude_local:pendente}},
  {nome:'simples',descricao:'Comum',compatibilidade:{claude:livre,codex:livre,codex_local:livre}}
]},async()=>{});
const campo=t=>criados.find(e=>e['aria-label']===t);
const consoleCli=campo('Console'),modelo=campo('Modelo (vazio usa padrão do console)'),execucao=campo('Execução');
const restrita=criados.find(e=>e.type==='checkbox'&&e.value==='restrita');
const simples=criados.find(e=>e.type==='checkbox'&&e.value==='simples');
assert.equal(restrita.disabled,false);restrita.checked=true;modelo.value='modelo-claude';
consoleCli.value='codex';consoleCli.events.change();
assert.equal(modelo.value,'');assert.equal(restrita.disabled,true);assert.equal(restrita.checked,false);
assert.equal(simples.disabled,false);
assert.match(criados.filter(e=>e.tag==='label').flatMap(e=>e.children).map(e=>e.textContent||'').join('\n'),/adaptação pendente: hooks/);
consoleCli.value='claude';consoleCli.events.change();assert.equal(restrita.disabled,false);
execucao.value='local';execucao.events.change();assert.equal(restrita.disabled,true);
execucao.value='cloud';consoleCli.value='opencode';consoleCli.events.change();
modelo.value='opencode/space-bunny-free';campo('Nome').value='Historiadora';campo('Função e responsabilidades').value='Pesquisa';
let enviado;
globalThis.fetch=async(url,opts)=>{
  assert.equal(url,'/api/gestao/funcionarios');enviado=JSON.parse(opts.body);
  return {ok:true,json:async()=>({funcionario:{nome:'Historiadora'}})};
};
await criados.find(e=>e.tag==='form').events.submit({preventDefault(){}});
assert.equal(enviado.funcionario.executor.modelo,'opencode/space-bunny-free');
assert.equal(Object.hasOwn(enviado.funcionario.executor,'cloud'),false);
console.log('Cadastro: compatibilidade por console/local, skill desmarcada ao perder suporte e modelo limpo — OK');
