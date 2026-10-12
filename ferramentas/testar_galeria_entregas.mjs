import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { criarGaleriaEntregas } from '../galeria_entregas.mjs';
class Elemento {
  children = []; events = {}; attributes = {}; textContent = ''; open = false; isConnected = true;
  constructor(tag) { this.tag = tag; }
  append(...els) { for (const el of els) { el.parent = this; this.children.push(el); } }
  replaceChildren(...els) { this.children = []; this.append(...els); }
  addEventListener(event, callback) { this.events[event] = callback; }
  setAttribute(name, value) { this.attributes[name] = value; }
  showModal() { this.open = true; }
  close() { this.open = false; this.events.close?.(); }
  focus() { this.focused = true; }
  click() { if (this.tag === 'a') downloads.push({ href: this.href, download: this.download }); return this.events.click?.(); }
  remove() { this.parent.children = this.parent.children.filter(el => el !== this); }
  set innerHTML(_) { throw new Error('HTML externo proibido'); }
}
const downloads = [], revogadas = [], criadas = [];
globalThis.document = { body: new Elemento('body'), createElement: tag => new Elemento(tag) };
const createOriginal = URL.createObjectURL, revokeOriginal = URL.revokeObjectURL;
URL.createObjectURL = blob => { const url = `blob:teste-${criadas.length}`; criadas.push({ url, blob }); return url; };
URL.revokeObjectURL = url => revogadas.push(url);
const chamadas = [];
globalThis.fetch = (url, options) => new Promise(resolve => chamadas.push({ url, options, resolve }));
const responder = (body, status = 200, chamada = chamadas.at(-1)) => chamada.resolve({ ok: status === 200, status, json: async () => body });
const pausa = () => new Promise(setImmediate);
const elementos = el => [el, ...el.children.flatMap(elementos)];
const texto = el => elementos(el).map(e => e.textContent).join('\n');
const achar = (el, nome) => elementos(el).find(e => e.tag === 'button' && e.textContent === nome);
const arquivo = { id: 'arq-1', nome: '<script>alert(1)</script>.md', mime: 'text/markdown', tamanho: 26, sha256: 'a'.repeat(64), preview: 'texto' };
const conteudo = '<script>alert(1)</script>!';
assert.equal(new TextEncoder().encode(conteudo).length, arquivo.tamanho);
const registro = { id: 'manifesto-1', cartao: 42, tentativa: 't-1', pr: 7, sha: 'b'.repeat(40), criado: '2026-01-02', arquivos: [arquivo], execucao: { estado: 'encerrada', codigo: 0, resultado: 'registrado' }, revisao: { estado: 'pendente' }, merge: { estado: 'nao_confirmado' }, aprovacao_visual: 'nao_registrada', aceite_usuario: 'nao_registrado' };
const dados = { ok: true, itens: [registro, { ...registro, id: 'historico-1', arquivada: true, arquivos: [] }], limitado: false };
const galeria = criarGaleriaEntregas(), painel = document.body.children[0], origem = new Elemento('button');
assert.equal(chamadas.length, 0, 'Criar galeria não consulta a API');
let tarefa = galeria.abrir('projeto A&', 'Projeto <img>', origem);
assert.equal(galeria.aberta, true);
assert.equal(chamadas[0].url, '/api/gestao/entregas?projeto=projeto%20A%26');
responder(dados); await tarefa;
painel.events.close(); // Evento atrasado de um fechamento anterior não apaga a sessão aberta.
assert.match(texto(painel), /1 entrega\(s\)/);
assert.doesNotMatch(texto(painel), /historico-1/);
assert.match(texto(painel), /código: 0/);
assert.match(texto(painel), /Aprovação visual: não registrada/);
assert.match(texto(painel), /Aceite do usuário: não registrado/);
assert.match(texto(painel), /não significa aprovação/);
assert.equal(chamadas.length, 1, 'Arquivos não são buscados automaticamente');
let visualizacao = achar(painel, 'Visualizar').click();
assert.equal(chamadas.length, 2);
achar(painel, 'Visualizar').click(); assert.equal(chamadas.length, 2, 'Clique repetido não duplica requisição');
responder({ ok: true, ...arquivo, conteudo }); await visualizacao;
assert.equal(elementos(painel).find(el => el.tag === 'pre').textContent, conteudo);
assert.equal(elementos(painel).some(el => el.tag === 'script' || el.tag === 'iframe'), false);
assert.match(texto(painel), /bytes verificados pelo servidor/);
let download = achar(painel, 'Baixar versão registrada').click();
responder({ ok: true, ...arquivo, conteudo }); await download;
assert.equal(downloads.length, 1); assert.equal(criadas[0].blob.type, 'application/octet-stream');
assert.match(downloads[0].href, /^blob:/);
assert.equal(downloads[0].download, 'script>.md');
assert.equal(await criadas[0].blob.text(), conteudo);
visualizacao = achar(painel, 'Visualizar').click();
responder({ ok: true, ...arquivo, sha256: 'c'.repeat(64), conteudo }); await visualizacao;
assert.match(texto(painel), /não corresponde à versão registrada/);
achar(painel, 'Mostrar histórico arquivado').click();
assert.match(texto(painel), /2 entrega\(s\)/); assert.match(texto(painel), /historico-1/);
assert.equal(revogadas.includes(criadas[0].url), true);
visualizacao = achar(painel, 'Visualizar').click(); const antiga = chamadas.at(-1);
achar(painel, 'Ocultar histórico arquivado').click();
assert.equal(antiga.options.signal.aborted, true);
responder({ ok: true, ...arquivo, conteudo }, 200, antiga); await visualizacao;
assert.equal(elementos(painel).some(el => el.tag === 'pre'), false);
// Troca de projeto descarta a lista antiga mesmo que o fetch ignore abort.
let primeira = galeria.abrir('antigo'); const antigaLista = chamadas.at(-1);
let segunda = galeria.abrir('novo');
assert.equal(antigaLista.options.signal.aborted, true);
responder({ ok: true, itens: [] }); await segunda;
responder(dados, 200, antigaLista); await primeira;
assert.match(texto(painel), /Nenhuma entrega registrada/); assert.doesNotMatch(texto(painel), /Cartão 42/);
// Fechar durante consulta, Escape e reabrir não deixam estado ou downloads tardios.
tarefa = galeria.abrir('fechar', 'Fechar', origem); const aoFechar = chamadas.at(-1);
let prevenido = false; painel.events.cancel({ preventDefault() { prevenido = true; } });
assert.equal(prevenido, true); assert.equal(galeria.aberta, false); assert.equal(origem.focused, true);
assert.equal(aoFechar.options.signal.aborted, true);
responder(dados, 200, aoFechar); await tarefa;
assert.doesNotMatch(texto(painel), /Cartão 42/);
tarefa = galeria.abrir('sem-permissao'); responder({}, 403); await tarefa;
assert.match(texto(painel), /somente no PC/);
tarefa = galeria.abrir('falha'); responder({ ok: false, erro: '<img onerror=alert(1)>' }); await tarefa;
assert.match(texto(painel), /<img onerror=alert\(1\)>/);
tarefa = galeria.abrir('sem-lista'); responder({ ok: true }); await tarefa;
assert.match(texto(painel), /Lista de entregas inválida/);
// Imagens são Blob raster; URLs são revogadas em substituição e fechamento.
const img = { ...arquivo, nome: 'captura.png', mime: 'image/png', tamanho: 3, preview: 'imagem' };
tarefa = galeria.abrir('imagens'); responder({ ok: true, itens: [{ ...registro, arquivos: [img] }] }); await tarefa;
for (let i = 0; i < 2; i++) {
  visualizacao = achar(painel, 'Visualizar').click(); responder({ ok: true, ...img, conteudo: 'YWJj' }); await visualizacao;
}
assert.equal(criadas.at(-1).blob.type, 'image/png');
assert.equal(elementos(painel).find(el => el.tag === 'img').src, criadas.at(-1).url);
assert.equal(revogadas.includes(criadas.at(-2).url), true);
galeria.fechar(); assert.equal(revogadas.includes(criadas.at(-1).url), true);
const svg = { ...img, nome: 'ativo.svg', mime: 'image/svg+xml' };
tarefa = galeria.abrir('svg'); responder({ ok: true, itens: [{ ...registro, arquivos: [svg] }] }); await tarefa;
visualizacao = achar(painel, 'Visualizar').click(); responder({ ok: true, ...svg, conteudo: 'YWJj' }); await visualizacao;
assert.match(texto(painel), /somente para download/); assert.equal(elementos(painel).some(el => el.tag === 'img'), false);
download = achar(painel, 'Baixar versão registrada').click(); const downloadPendente = chamadas.at(-1);
galeria.fechar(); responder({ ok: true, ...svg, conteudo: 'YWJj' }, 200, downloadPendente); await download;
assert.equal(downloads.length, 1, 'Download tardio após fechar é descartado');
// Texto grande é truncado somente na prévia; tamanho divergente é recusado.
const longo = 'á'.repeat(200001);
const arquivoLongo = { ...arquivo, nome: 'longo.txt', tamanho: new TextEncoder().encode(longo).length };
tarefa = galeria.abrir('texto-grande'); responder({ ok: true, itens: [{ ...registro, arquivos: [arquivoLongo] }] }); await tarefa;
visualizacao = achar(painel, 'Visualizar').click(); responder({ ok: true, ...arquivoLongo, conteudo: longo }); await visualizacao;
assert.equal(elementos(painel).find(el => el.tag === 'pre').textContent.length, 200000);
assert.match(texto(painel), /Prévia truncada/);
visualizacao = achar(painel, 'Visualizar').click(); responder({ ok: true, ...arquivoLongo, conteudo: 'curto' }); await visualizacao;
assert.match(texto(painel), /Tamanho diferente/);
galeria.fechar();
// Limites e status ausentes não fabricam aprovação.
tarefa = galeria.abrir('limites'); responder({ ok: true, itens: Array.from({ length: 101 }, (_, i) => ({ id: i, arquivos: [] })) }); await tarefa;
assert.match(texto(painel), /Lista limitada/);
assert.equal(elementos(painel).filter(el => el.tag === 'article').length, 100);
assert.match(texto(painel), /Revisão: não registrado · Merge: não registrado/);
galeria.fechar();
// Integração mantém a galeria fora do corpo recriado pelo polling.
const gestao = readFileSync(new URL('../gestao_painel.js', import.meta.url), 'utf8');
assert.match(gestao, /galeriaEntregas\.abrir\(p\.id,p\.nome,botaoEntregas\)/);
assert.match(gestao, /carregando \|\| galeriaEntregas\.aberta/);
assert.match(gestao, /if \(galeriaEntregas\.aberta \|\| !painel\.open\) return/);
URL.createObjectURL = createOriginal; URL.revokeObjectURL = revokeOriginal;
console.log('Galeria de entregas: leitura sob demanda, histórico, status, segurança de previews/downloads, limites, troca de projeto, Escape, cancelamento e limpeza — OK');
