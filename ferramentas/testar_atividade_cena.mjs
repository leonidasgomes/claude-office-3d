import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {eventoRecente, demoAutomaticaPermitida, fonteObservada} from '../atividade_cena.mjs';

const agora = Date.parse('2026-01-01T12:00:00Z');
const ev = segundos => ({ts:new Date(agora-segundos*1000).toISOString(), fonte:'claude'});
assert.equal(eventoRecente(ev(30), agora), true);
assert.equal(eventoRecente(ev(60), agora), false);
assert.equal(eventoRecente(ev(3600), agora), false);
assert.equal(eventoRecente(ev(-60), agora), false);
assert.equal(eventoRecente({ts:'invalida'}, agora), false);
assert.equal(eventoRecente({...ev(90),inicio:true,espera_s:120}, agora), true);
assert.equal(eventoRecente({...ev(130),inicio:true,espera_s:120}, agora), false);
assert.equal(eventoRecente({...ev(1900),inicio:true,espera_s:99999}, agora), false);
assert.equal(demoAutomaticaPermitida('http:'), false);
assert.equal(demoAutomaticaPermitida('https:'), false);
assert.equal(demoAutomaticaPermitida('file:'), true);
assert.equal(fonteObservada({...ev(30),origem_escritorio:{nome:'legado'}}), 'Claude (ponte)');
assert.equal(fonteObservada({fonte:'codex'}), 'Codex');
assert.equal(fonteObservada({}), 'não identificada');

// Executa a função real da cena: cadastro e histórico não viram status de sessão viva.
const fonte = fs.readFileSync(new URL('../escritorio.js', import.meta.url),'utf8');
const inicio=fonte.indexOf('function linhaAgente(a) {');
const fim=fonte.indexOf('function atualizarPainel()',inicio);
const contexto=vm.createContext({PROJETO_CENA:null,eventoRecente,fonteObservada,TRABALHO_EXPIRA:60,MAX_COMANDO:1800,
  relogioMs:()=>agora, rodandoComando:a=>!!a.ocupadoAte,haQuanto:()=> 'há 1 h'});
vm.runInContext(fonte.slice(inicio,fim),contexto);
let linha=contexto.linhaAgente({estado:'ocioso'});
assert.equal(linha.sub,'Cadastrado no escritório');
assert.equal(linha.rel,'sem atividade observada');
linha=contexto.linhaAgente({estado:'ocioso',ultimoEventoMs:agora-3600000,eventoObservado:ev(3600),ultimoResumo:'evento antigo'});
assert.equal(linha.rel,'sem atividade recente · Claude');
assert.equal(linha.sub,'histórico: evento antigo');
linha=contexto.linhaAgente({estado:'trabalhando',ultimoEventoMs:agora-30000,eventoObservado:{...ev(30),fonte:'codex'},agoraFaz:{resumo:'teste',fonte:'codex'}});
assert.equal(linha.sub,'teste');
assert.ok(linha.exata.includes('Codex'));
console.log('OK: cadastro, histórico, telemetria recente, comando longo e demo explícita');
