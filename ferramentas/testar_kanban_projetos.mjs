import assert from 'node:assert/strict';
import {seletorProjetos} from '../kanban_projetos.mjs';
class Elemento {
  children = []; textContent = ''; value = ''; hidden = false;
  append(e) {this.children.push(e);}
  replaceChildren() {this.children = [];}
  setAttribute() {}
  addEventListener(_, fn) {this.mudar = fn;}
  set innerHTML(_) {throw new Error('HTML externo proibido');}
}
globalThis.document = {createElement: () => new Elemento()};
let rotulo, chamadas = 0;
const seletor = seletorProjetos({before(e) {rotulo = e;}}, () => chamadas++);
assert.equal(seletor.url(), '/kanban'); assert.equal(rotulo.hidden, true);
seletor.receber({fonte: 'gestao', projetos: [{id:'abc', nome:'<script>um</script>'}, {id:'def',nome:'dois'}], projeto_id:''});
assert.equal(rotulo.hidden, false); assert.equal(seletor.url(), '/kanban');
const select = rotulo.children[0]; assert.equal(select.children[1].textContent, '<script>um</script> · abc');
select.value = 'def'; select.mudar(); assert.equal(chamadas, 1); assert.equal(seletor.url(), '/kanban?projeto=def');
// A resposta de outro projeto não troca a escolha explícita do usuário.
seletor.receber({fonte:'gestao',projetos:[{id:'abc',nome:'um'},{id:'def',nome:'dois'}],projeto_id:'abc'});
assert.equal(select.value, 'def');
seletor.receber({fonte:'gestao',projetos:[{id:'def',nome:'dois'}],erro:'indisponível'});
assert.equal(seletor.url(), '/kanban?projeto=def');
select.value = ''; select.mudar(); assert.equal(seletor.url(), '/kanban');
seletor.receber({fonte:'gestao',projetos:[{id:'abc',nome:'um'}],projeto_id:'abc'});
assert.equal(seletor.url(), '/kanban?projeto=abc');
seletor.receber({cartoes:[]}); assert.equal(rotulo.hidden, true);
console.log('Kanban: seleção por projeto, escolha preservada e texto seguro — OK');
