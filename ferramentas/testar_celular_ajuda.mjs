// Executa a UI real com DOM e /rede/status simulados; não inicia servidor nem altera firewall.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

class Elemento {
  constructor(tag) { this.tag = tag; this.children = []; this.events = {}; this.hidden = true; this.style = {}; }
  set textContent(valor) { this.children = [String(valor)]; }
  get textContent() { return this.children.map(x => typeof x === 'string' ? x : x.textContent).join(''); }
  append(...filhos) { this.children.push(...filhos); }
  replaceChildren(...filhos) { this.children = filhos; }
  addEventListener(nome, fn) { this.events[nome] = fn; }
  set innerHTML(_) { throw new Error('Use texto, não HTML'); }
}
const ids = new Map(['btnCelular', 'celular', 'celularCorpo', 'celularFechar'].map(id => [id, new Elemento('div')]));
const corpo = ids.get('celularCorpo'), painel = ids.get('celular');
const pedidos = [], copias = [], timers = new Map(), janela = new Elemento('window');
let status = { ativo: false }, proximoTimer = 0;
const navigator = {
  clipboard: { async writeText(texto) { copias.push(texto); } },
  get platform() { throw new Error('Não inferir o sistema do servidor pelo navegador'); },
  get userAgent() { throw new Error('Não inferir o sistema do servidor pelo navegador'); },
  get userAgentData() { throw new Error('Não inferir o sistema do servidor pelo navegador'); }
};
const contexto = vm.createContext({
  LOCAL: true, qrCanvas() {}, navigator, window: janela,
  document: { hidden: false, createElement: tag => new Elemento(tag), getElementById: id => ids.get(id) },
  async fetch(url, opcoes) {
    pedidos.push({ url, opcoes });
    assert.equal(url, '/rede/status');
    assert.equal(opcoes.method, undefined, 'A ajuda só pode consultar o status');
    return { ok: true, json: async () => status };
  },
  setInterval(fn) { timers.set(++proximoTimer, fn); return proximoTimer; },
  clearInterval(id) { timers.delete(id); }, setTimeout() {}
});
const fonte = fs.readFileSync(new URL('../celular.js', import.meta.url), 'utf8');
vm.runInContext(fonte.replace(/^import .*;\r?\n/gm, ''), contexto);
const tick = () => new Promise(resolve => setImmediate(resolve));
const localizar = (e, id) => e.id === id ? e : e.children.filter(x => typeof x !== 'string').map(x => localizar(x, id)).find(Boolean);
const clique = async () => { ids.get('btnCelular').events.click(); await tick(); };

await clique();
assert.equal(painel.hidden, false);
assert.match(corpo.textContent, /desligado \(padrão, por segurança\)/);
assert.match(corpo.textContent, /Linux\/macOS \(terminal\): sh abrir_escritorio\.sh celular/);
assert.match(corpo.textContent, /Windows: abrir_escritorio\.bat celular/);
assert.equal(timers.size, 1);
await clique();
assert.equal(painel.hidden, true);
assert.equal(corpo.textContent, '');
assert.equal(timers.size, 0);

status = { ativo: true, https: true, porta: 9100, porta_https: 9101, porta_ca: 9102,
  portas: [9101, 9102], python: '/opt/office/.venv/bin/python', tls: {}, enderecos: ['192.168.1.10'] };
await clique();
let ajuda = localizar(corpo, 'celularAjuda');
assert.match(ajuda.textContent, /Linux: confira o firewall/);
assert.match(ajuda.textContent, /portas TCP deste servidor são 9101,9102/);
assert.match(ajuda.textContent, /Não desative o firewall/);
assert.match(ajuda.textContent, /PowerShell acima são apenas para Windows/);
assert.match(ajuda.textContent, /macOS: confira/);
assert.match(ajuda.textContent, /Windows: falta regra/);
assert.match(ajuda.textContent, /Get-NetConnectionProfile/);
assert.match(localizar(corpo, 'celularComando').textContent, /-LocalPort 9101,9102 -Profile Private/);
await localizar(corpo, 'celularCopiar').events.click();
assert.equal(copias[0], localizar(corpo, 'celularComando').textContent);

ajuda.open = true; ajuda.events.toggle();
timers.values().next().value(); await tick();
assert.equal(localizar(corpo, 'celularAjuda').open, true, 'Ajuda aberta sobrevive ao refresh');
assert.equal(timers.size, 1);
status = { ...status, https: false, portas: [9100] };
timers.values().next().value(); await tick();
ajuda = localizar(corpo, 'celularAjuda');
assert.match(ajuda.textContent, /portas TCP deste servidor são 9100\./);
assert.match(localizar(corpo, 'celularComando').textContent, /-LocalPort 9100 -Profile Private/);
assert.match(corpo.textContent, /SEM HTTPS/);
janela.events.keydown({ key: 'Escape' });
assert.equal(painel.hidden, true);
assert.equal(corpo.textContent, '');
assert.equal(timers.size, 0);
await clique();
ids.get('celularFechar').events.click();
assert.equal(painel.hidden, true);
assert.equal(timers.size, 0);
assert.equal(pedidos.length, 5);
console.log('Celular: ajuda Linux/macOS e Windows, portas HTTPS/HTTP, cópia, refresh e reabertura — OK');
