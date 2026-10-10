import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
class Elemento {
  constructor(tag) { this.tag=tag; this.children=[]; this.open=false; this.textContent=''; this.dataset={}; }
  append(...filhos) { this.children.push(...filhos); }
  replaceChildren(...filhos) { this.children=filhos; }
  setAttribute() {}
  addEventListener() {}
  querySelector(seletor) {
    const id=/section\[data-projeto="([0-9a-f]{20})"\]/.exec(seletor)?.[1];
    return id ? this.children.find(e=>e.dataset.projeto===id) || null : null;
  }
  focus() { this.focado=true; }
  scrollIntoView() { this.rolado=true; }
  showModal() { this.open=true; }
  querySelectorAll() { return []; }
  set innerHTML(v) { throw Error('HTML externo proibido'); }
}
const body=new Elemento('body');
const dados={projetos:[{id:'a'.repeat(20),nome:'Projeto',ativo:true,ceo:{console:'codex'},diretor:{console:'gemini'},
  politica_versao:'b'.repeat(64),pedidos_retomada:{itens:[{cartao:44,estado:'concluida',resultado:'bloqueado',codigo:0},{id:'c'.repeat(32),cartao:45,estado:'incerto',resultado:null,codigo:null}]},consumo:{escopo:'projeto',grupos:[{provider:'codex',modelo:'modelo deste projeto',origem_modelo:'informado',agente:'CEO',amostras:1,entrada:12,com_entrada:1,saida:2,com_saida:1,total:14,com_total:1}]},local:{ativo:false},merge:'manual',merge_config:{modo:'manual',checks:[],rotulos_manuais:['merge-manual']},equipes:[],funcionarios:[],tarefas:[{cartao:42,equipe:'Dev',console:'claude',estado:'executando',
    atividade:{estado:'acompanhando',ultimo_sinal:Date.now()/1000-.1,console_observado:true,codigo_console:null,eventos:{ultimo_evento:Date.now()/1000-.2,total:3,eventos_filhos:1,ultimo_tipo:'<script>fala</script>'}}},{cartao:44,equipe:'Dev',console:'codex',estado:'bloqueado',atividade:{estado:'encerrado',ultimo_sinal:Date.now()/1000,codigo_console:0}}],
  desempenho:{historico_sem_vinculo:true,limitado:false,grupos:[{console:'claude',modelo:'anterior',
    origem_modelo:'configurado',execucao:'cloud',tentativas:2,com_intervalo:1,media_seg:5,
    saida_zero:0,saida_nao_zero:1,sem_retorno:1}]},
  saude_tarefas:{consultadas:200,limitado:true,pendencias:[{cartao:42,equipe:'<script>teste</script>',
    console:'claude',codigo:9,sinais:['bloqueada','falha']},{cartao:43,equipe:'Dev',console:'opencode',
    codigo:null,sinais:['sem_retorno']}]} }]};
dados.ponte_eventos={estado:'parcial',fontes:[{origem:'<script>Legado</script>',estado:'interrompida',importados:3,descartados:1}]};
Object.assign(dados.projetos[0].desempenho.grupos[0],{tentativas_com_consumo:1,consumo_observado:{amostras:2,total:20,com_total:1,equivalente_api_usd:'0.01',com_preco:1}});
Object.assign(dados.projetos[0].desempenho.grupos[0],{equipe:'<script>Equipe</script>',despachos:1,retomadas:1,tipo_nao_informado:0,sem_resultado:1,
  resultados:{revisao_aprovada:0,revisao_desativada:0,revisao_reprovada:0,falha_console:1,sem_entrega:0,gate_bloqueado:0}});
dados.projetos[0].tarefas[0].ultima_execucao={duracao_seg:5,codigo:0,consumo:{grupos:[{provider:'gemini',modelo:'<script>modelo nativo</script>',origem_modelo:'informado',agente:'Dev',amostras:1,entrada:10,com_entrada:1,saida:2,com_saida:1,total:12,com_total:1,equivalente_api_usd:'0.02',com_preco:1}]}};
const vazio=()=>new Elemento('details');
dados.projetos[0].funcionarios=[{id:'f'.repeat(32),nome:'História <script>',funcao:'Pesquisa',equipe:'Dev',executor:{console:'claude'},perfil_nativo:{estado:'divergente'}}];
dados.projetos.push({id:'d'.repeat(20),nome:'Projeto inativo',ativo:false,documentacao:{
  fontes:[{papel:'regras',caminho:'<script>REGRAS.md</script>',estado:'ausente'}],
  instrucoes_consoles:[{arquivo:'AGENTS.md',consoles:['codex','opencode'],estado:'presente',necessario:false,cita_regras:true}],
  limite:'Presença não comprova concordância das regras'}});
const eventos={};
const contexto=vm.createContext({document:{body,hidden:false,createElement:t=>new Elemento(t),addEventListener(){}},
  window:{addEventListener:(nome,fn)=>{eventos[nome]=fn;},dispatchEvent:e=>eventos[e.type]?.(e)},
  CustomEvent:class {constructor(type,opts={}){this.type=type;this.detail=opts.detail;}},
  fetch:async()=>({ok:true,json:async()=>dados}),formularioFuncionarios:vazio,formularioExecutores:vazio,
  formularioCoordenacao:vazio,renderizarCoordenacoes(){},renderizarPedidos(){},
  botaoExecutarCoordenacao:vazio,botaoConciliarPedido:vazio,clearInterval(){},setInterval(){},location:{}});
const fonte=fs.readFileSync(new URL('../gestao_painel.js',import.meta.url),'utf8').replace(/^import .*;\r?\n/gm,'');
vm.runInContext(fs.readFileSync(new URL('../retomada_form.mjs',import.meta.url),'utf8').replace(/^export /gm,''),contexto);
vm.runInContext(fs.readFileSync(new URL('../merge_form.mjs',import.meta.url),'utf8').replace(/^export /gm,''),contexto);
vm.runInContext(fs.readFileSync(new URL('../indicadores_providers.mjs',import.meta.url),'utf8').replace(/^export /gm,''),contexto);
vm.runInContext(fs.readFileSync(new URL('../agentes_nativos_form.mjs',import.meta.url),'utf8').replace(/^export /gm,''),contexto);
vm.runInContext(fonte,contexto);
await vm.runInContext('painel.open=true; carregar()',contexto);
const texto=e=>[e.textContent,...e.children.map(texto)].join('\n');
const resultado=texto(body);
assert.match(resultado,/Consumo deste projeto/);
assert.match(resultado,/Acompanhamento de outras instalações/);
assert.match(resultado,/Ponte: algumas fontes interrompidas/);
assert.match(resultado,/<script>Legado<\/script>.*3 eventos importados nesta execução.*1 descartados/);
assert.match(resultado,/não comprova agente ativo/);
assert.match(resultado,/Perfil nativo de História <script>/);
assert.match(resultado,/Estado do perfil: divergente ou desatualizado; arquivo preservado/);
assert.match(resultado,/Fontes comuns e instruções dos consoles/);
assert.match(resultado,/<script>REGRAS.md<\/script>.*ausente/);
assert.match(resultado,/AGENTS.md.*console não selecionado.*cita a fonte de regras/);
assert.match(resultado,/Presença não comprova concordância das regras/);
assert.match(resultado,/modelo deste projeto/);
assert.match(resultado,/total 14 tokens/);
assert.match(resultado,/Configurar merge deste projeto/);
assert.match(resultado,/200 reservas mais recentes/);
assert.match(resultado,/anteriores aos últimos 7 dias/);
assert.match(resultado,/#42.*<script>teste<\/script>.*tarefa bloqueada.*saída 9/);
assert.match(resultado,/#43.*tentativa sem retorno registrado/);
assert.match(resultado,/Retomada explícita exige prévia/);
assert.match(resultado,/Retomar #44/);assert.match(resultado,/#44.*cartão bloqueado/);
assert.match(resultado,/Conferir retomada/);assert.match(resultado,/Retomar sessão/);assert.match(resultado,/Conferir retorno da retomada #45/);
assert.match(resultado,/Processo principal observado em execução/);
assert.match(resultado,/Eventos recebidos nesta tentativa: 3 · com vínculo de filho: 1/);
assert.match(resultado,/<script>fala<\/script>/);
assert.match(resultado,/ausência de eventos não prova inatividade/);
assert.match(resultado,/não comprova progresso, qualidade/);
assert.doesNotMatch(resultado,/Gestão indisponível/);
assert.match(resultado,/tentativas antigas sem vínculo de projeto recuperável/);
assert.match(resultado,/histórico pode estar incompleto/);
assert.match(resultado,/claude · anterior.*2 tentativa\(s\).*intervalo médio 5 s/);
assert.doesNotMatch(resultado,/Cobertura limitada às 1.000 tentativas/);
assert.match(resultado,/Saída zero não comprova aceite/);
assert.match(resultado,/Consumo ligado a 1\/2 tentativas: total 20 \(1\/2 amostras com total\)/);
assert.match(resultado,/USD 0.01 \(1\/2 amostras com preço\)/);
assert.match(resultado,/Consumo observado da última tentativa/);
assert.match(resultado,/<script>modelo nativo<\/script>/);
assert.match(resultado,/USD 0.02/);
assert.match(resultado,/Histórico sem vínculo não é reatribuído/);
eventos['office-projeto-alerta']({detail:{painel:'prs',projeto:'a'.repeat(20)}});
assert.equal(vm.runInContext('projetoAlerta',contexto),'');
eventos['office-projeto-alerta']({detail:{painel:'gestao',projeto:'D:/segredo'}});
assert.equal(vm.runInContext('projetoAlerta',contexto),'');
eventos['office-projeto-alerta']({detail:{painel:'gestao',projeto:'a'.repeat(20)}});
await new Promise(resolve=>setImmediate(resolve));
assert.equal(vm.runInContext('corpo.children.find(e=>e.dataset.projeto=== "'+ 'a'.repeat(20)+'").focado',contexto),true);
assert.equal(vm.runInContext('projetoAlerta',contexto),'');
const alertas=fs.readFileSync(new URL('../alertas.js',import.meta.url),'utf8');
vm.runInContext(alertas.slice(alertas.indexOf('function abrirPainel(nome)'),alertas.indexOf('function tratarHash()')),contexto);
vm.runInContext('abrirAlerta("/#alerta=gestao&projeto='+ 'a'.repeat(20)+'")',contexto);
await new Promise(resolve=>setImmediate(resolve));
assert.equal(vm.runInContext('projetoAlerta',contexto),'');
assert.equal(vm.runInContext('painel.open',contexto),true);
console.log('Gestão real: pendências antigas, cobertura limitada, consoles e texto seguro — OK');
assert.match(resultado,/<script>Equipe<\/script>/);
assert.match(resultado,/1 despacho\(s\) · 1 retomada\(s\)/);
assert.match(resultado,/1 falha\(s\) de console/);
assert.match(resultado,/Encaminhamento à revisão não comprova merge/);
