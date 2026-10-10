import assert from 'node:assert/strict';
import fs from 'node:fs';
const criados=[];
class Elemento {
  constructor(tag){this.tag=tag;this.children=[];this.events={};this.value='';this.attrs={};criados.push(this);}
  append(...xs){this.children.push(...xs);}
  setAttribute(k,v){this.attrs[k]=v;}
  addEventListener(k,fn){this.events[k]=fn;}
  replaceChildren(...xs){this.children=xs;}
  focus(){this.focado=true;}
  reset(){this.resetado=true;}
}
globalThis.document={createElement:t=>new Elemento(t),createTextNode:t=>({textContent:t})};
const importar=async file=>import('data:text/javascript;base64,'+Buffer.from(fs.readFileSync(new URL(file,import.meta.url),'utf8')).toString('base64'));
const {formularioEquipe,botaoExcluir}=await importar('../cadastros_form.mjs');
const {formularioFuncionarios}=await importar('../funcionarios_form.js');
const projeto={id:'a'.repeat(20),politica_versao:'b'.repeat(64),ceo:{console:'codex',modelo:'modelo'},equipes:[{nome:'Dev'}],skills:[],local:{ativo:false}};
let pedidos=[],atualizado=0;
globalThis.fetch=async(url,opts)=>{pedidos.push({url,dados:JSON.parse(opts.body)});return {ok:true,json:async()=>({funcionario:{nome:'Ana'}})};};
const atualizar=async()=>{atualizado++;};
const campo=nome=>criados.findLast(x=>x.attrs['aria-label']===nome);
let details=formularioEquipe(projeto,atualizar);
campo('Nome da equipe').value='Pesquisa';campo('Especialidade e responsabilidades').value='História';campo('Console').value='codex';
await details.children[1].events.submit({preventDefault(){}});
assert.equal(pedidos.at(-1).dados.acao,'criar');assert.equal(pedidos.at(-1).dados.equipe.nome,'Pesquisa');assert.equal(atualizado,1);
const equipe={nome:'Dev',especialidade:'Código',executor:{console:'codex',modelo:'modelo',execucao:'cloud'}};
details=formularioEquipe(projeto,atualizar,equipe);assert.equal(campo('Nome da equipe').readOnly,true);
campo('Modelo').value='outro';await details.children[1].events.submit({preventDefault(){}});
assert.equal(pedidos.at(-1).dados.nome,'Dev');assert.equal(pedidos.at(-1).dados.equipe.executor.modelo,'outro');
const item={id:'c'.repeat(32),nome:'Ana',funcao:'Pesquisa',equipe:'Dev',executor:{console:'codex',modelo:'modelo',execucao:'cloud'},skills:[]};
details=formularioFuncionarios(projeto,atualizar,item);assert.equal(campo('Nome').value,'Ana');assert.equal(campo('Modelo (vazio usa padrão do console)').value,'modelo');
campo('Nome').value='Ana Maria';await details.children[1].events.submit({preventDefault(){}});
assert.equal(pedidos.at(-1).url,'/api/gestao/cadastros');assert.equal(pedidos.at(-1).dados.id,item.id);assert.deepEqual(pedidos.at(-1).dados.anterior,item);assert.equal(pedidos.at(-1).dados.funcionario.nome,'Ana Maria');
const caixa=botaoExcluir(projeto,'funcionario',item,atualizar);const [abrir,confirmacao]=caixa.children;const [,confirmar,cancelar]=confirmacao.children;
let antes=pedidos.length;abrir.events.click();assert.equal(confirmacao.hidden,false);assert.equal(cancelar.focado,true);assert.equal(pedidos.length,antes);
cancelar.events.click();assert.equal(confirmacao.hidden,true);assert.equal(pedidos.length,antes);
abrir.events.click();await confirmar.events.click();assert.equal(pedidos.at(-1).dados.acao,'excluir');assert.equal(pedidos.at(-1).dados.id,item.id);
globalThis.fetch=async()=>({ok:false,json:async()=>({erro:'Há tarefa pendente'})});
abrir.events.click();await confirmar.events.click();assert.match(caixa.children[2].textContent,/tarefa pendente/);assert.equal(confirmar.disabled,false);
console.log('Cadastros: criação/edição, identidade estável, confirmação e erro recuperável — OK');
