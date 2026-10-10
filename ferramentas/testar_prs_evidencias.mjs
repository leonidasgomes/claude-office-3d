import assert from 'node:assert/strict';
import {detalhesEvidencias} from '../prs_evidencias.mjs';
class Elemento {
  children=[]; events={}; textContent=''; open=false;
  append(...e) {this.children.push(...e);}
  replaceChildren() {this.children=[];}
  addEventListener(n,f) {this.events[n]=f;}
  set innerHTML(_) {throw new Error('HTML externo proibido');}
}
globalThis.document={createElement:()=>new Elemento()};
let chamadas=[], resposta, resolver;
globalThis.fetch=(url,opts)=>{chamadas.push([url,opts]);return new Promise(r=>resolver=r);};
const pr={numero:42,sha:'a'.repeat(40)}; const projeto='b'.repeat(20);
let ativo=true;
const det=detalhesEvidencias(projeto,pr,()=>ativo);
const corpo=det.children[1],botao=det.children[2];
const texto=()=>corpo.children.map(e=>e.textContent).join('\n');
det.open=true;det.events.toggle();
assert.equal(chamadas.length,1);assert.equal(botao.disabled,true);
det.events.toggle();assert.equal(chamadas.length,1);
assert.match(chamadas[0][0],new RegExp('projeto='+projeto+'&numero=42&sha='+pr.sha));
resposta={ok:true,projeto_id:projeto,numero:42,sha:pr.sha,checks:[{nome:'<script>CI</script>',estado:'success',tipo:'check',app_id:10}],
  gates:[{nome:'CI',estado:'ambíguo'}],revisoes:[{autor:'qa',estado:'APPROVED',sha:'c'.repeat(40),commit_atual:false}],mergeavel:null,
  regras_branch:{estado:'consultado',branch:'release/<script>',sha_base:'e'.repeat(40),
    regras:[{tipo:'pull_request',ruleset_id:9,origem:'Organization',aprovacoes_exigidas:2,require_code_owner_review:true,required_review_thread_resolution:true}],
    gates:[{nome:'CI',estado:'success',app_id:10}],limite:'Proteção clássica ainda pendente.'},
  pendencias_revisao:{estado:'consultado',decisao_revisao:'REVIEW_REQUIRED',threads_total:3,threads_pendentes:2,threads_pendentes_desatualizadas:1,
    protecao_classica:{estado:'consultado',aprovacoes_exigidas:2,requiresCodeOwnerReviews:true,requiresConversationResolution:true,
      checks:[{nome:'CI',estado:'success',app_id:10}]},limite:'Threads desatualizadas continuam pendentes.'}};
resolver({ok:true,json:async()=>resposta});await new Promise(setImmediate);
assert.match(texto(),/CI · ambíguo/); assert.match(texto(),/<script>CI<\/script>/);
assert.match(texto(),/outro commit/);assert.match(texto(),/Mergeabilidade ainda não informada/);
assert.match(texto(),/não autorizam merge/); assert.equal(botao.disabled,false);
assert.match(texto(),/Rulesets ativos da base release\/<script>/);
assert.match(texto(),/Aprovações exigidas: 2/);assert.match(texto(),/Não comprova cumprimento/);
assert.match(texto(),/Check do GitHub: CI · success · App 10/);
assert.match(texto(),/REVIEW_REQUIRED/);assert.match(texto(),/2 pendente\(s\) de 3; 1 pendente\(s\) em trechos desatualizados/);
assert.match(texto(),/Check da proteção clássica: CI · success · App 10/);
det.events.toggle();assert.equal(chamadas.length,1); // Reabrir não gera nova coleta automaticamente.
const pendente=botao.events.click();
ativo=false;resolver({ok:true,json:async()=>resposta});await pendente;
assert.doesNotMatch(texto(),/success/);assert.match(texto(),/Seleção ou commit mudou/);
ativo=true;
const errado=botao.events.click();resolver({ok:true,json:async()=>({...resposta,sha:'d'.repeat(40)})});await errado;
assert.match(texto(),/outro projeto ou commit/);assert.doesNotMatch(texto(),/success/);
const erro=botao.events.click();resolver({ok:true,json:async()=>({ok:false,erro:'Coleta incompleta'})});await erro;
assert.equal(texto(),'Coleta incompleta');
const semRegras=botao.events.click();resolver({ok:true,json:async()=>({...resposta,regras_branch:{estado:'indisponivel',regras:[],gates:[]}})});await semRegras;
assert.match(texto(),/isso não significa ausência de proteção/);assert.doesNotMatch(texto(),/Check do GitHub:/);
const semPendencias=botao.events.click();resolver({ok:true,json:async()=>({...resposta,pendencias_revisao:{estado:'indisponivel'}})});await semPendencias;
assert.match(texto(),/não presuma aprovação/);assert.doesNotMatch(texto(),/Conversas de revisão: 0/);
console.log('Evidências PR: projeto/SHA vinculados, resposta antiga descartada, texto seguro e consulta sob demanda — OK');
