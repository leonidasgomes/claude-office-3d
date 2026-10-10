import assert from 'node:assert/strict';
import {renderizarCoordenacoes} from '../coordenacoes_painel.mjs';
const linhas=[];
const pai={append(e){linhas.push(e);}};
const linha=(tag,texto,p)=>{
  const e={tag,textContent:texto,set innerHTML(v){throw Error('HTML proibido');}};p.append(e);return e;
};
renderizarCoordenacoes({itens:[{id:'a'.repeat(32),estado:'consultando_ceo',atualizado:1,
  executores:{ceo:{console:'codex',modelo:'<img src=x onerror=alert(1)>'},diretor:{console:'gemini',modelo:''}},
  candidatos:[42,43],ceo:{cartoes:[42],bloqueios:0},diretor:null,lote_id:'b'.repeat(32)}],problemas:1,limitado:true},pai,linha);
const texto=linhas.map(e=>e.textContent).join('\n');
assert.match(texto,/confirme no PC/);assert.match(texto,/#42/);assert.match(texto,/sem decisão registrada/);
assert.match(texto,/<img src=x/);assert.match(texto,/dez coordenações/);assert.match(texto,/Lote vinculado/);
assert.match(texto,/indisponíveis/);assert.doesNotMatch(texto,/processo vivo/);
console.log('Recibos no painel: seleções, vínculo de lote, incerteza e texto sem HTML — OK');
