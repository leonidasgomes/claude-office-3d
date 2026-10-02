// Painel "📱 Celular" (só no PC, em localhost): passo 1 instalar o certificado da CA local (uma vez por celular),
// passo 2 parear (QR de código de uso único, vale 10 min, com a permissão escolhida), mais a lista de aparelhos
// pareados com "Revogar". Os QR são gerados aqui mesmo (qr.js, sem internet). O código só aparece neste painel; o
// servidor só atende /rede/* para 127.0.0.1.
import { LOCAL } from './movel.js';
import { qrCanvas } from './qr.js';

const COMO_LIGAR = 'abrir_escritorio.bat celular';   // (Linux/macOS: ./abrir_escritorio.sh celular) sobe com --rede-local
const NOME_REGRA = 'Claude Office 3D (celular)';   // nome da regra de firewall sugerida
const $ = (id) => document.getElementById(id);
const botao = $('btnCelular'), painel = $('celular'), corpo = $('celularCorpo');
let ajudaAberta = false, timer = null, codigo = null, vistos = null, permEscolhida = 'ver', iEnd = 0, ultimo = null;

function el(tag, classe, texto) {
  const e = document.createElement(tag);
  if (classe) e.className = classe;
  if (texto != null) e.textContent = texto;
  return e;
}
async function pegar(url) {
  const r = await fetch(url, { cache: 'no-store' });
  if (!r.ok) throw new Error('HTTP ' + r.status);
  return r.json();
}
async function postar(url, dados) {
  const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Office-Acao': '1' }, body: JSON.stringify(dados) });
  let j = null; try { j = await r.json(); } catch (e) { /* sem corpo */ }
  if (!r.ok || !j || !j.ok) throw new Error((j && j.erro) || 'HTTP ' + r.status);
  return j;
}
const quando = (t) => (t ? new Date(t * 1000).toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }) : '—');
const dia = (t) => (t ? new Date(t * 1000).toLocaleDateString('pt-BR') : '—');

function aviso(https) {
  return el('p', 'aviso', https
    ? 'Só funciona em redes privadas. O tráfego vai criptografado (HTTPS com a CA local, que só vale para IPs privados). '
      + 'O celular só pode ver e, se você permitir, marcar PR como conferido: tudo fica no histórico e dá para desfazer. Fora de casa, use o Tailscale.'
    : 'Só funciona em redes privadas. SEM HTTPS a conexão não é criptografada: quem estiver no seu Wi-Fi poderia ver o tráfego e '
      + 'até copiar o cookie do celular pareado. Por isso o celular só pode ver e, se você permitir, marcar PR como conferido '
      + '(tudo fica no histórico e dá para desfazer). Fora de casa, use o Tailscale.');
}

function desenharQr(alvo, texto) {
  const canvas = document.createElement('canvas');
  try { qrCanvas(canvas, texto, 260); alvo.replaceChildren(canvas); } catch (e) { alvo.replaceChildren(el('p', null, 'QR: ' + e.message)); }
}
function fingerprint(rotulo, v) {
  const d = el('div', 'impressao'); d.append(el('span', 'msg', rotulo + ': '), el('code', null, v || '—')); return d;
}

// Rótulo do endereço na lista: o primeiro é o da placa com gateway padrão (o servidor ordena assim); virtual não serve
function rotuloEnd(e, i, s) {
  if ((s.virtuais || []).includes(e)) return ' (virtual — não use)';
  if ((s.tailscale || []).includes(e)) return ' (Tailscale)';
  return i === 0 ? ' (rede principal)' : '';
}

function secaoRede(s, todos) {
  const sec = el('div', 'rede');
  if (todos.length > 1) {
    const sel = document.createElement('select');
    todos.forEach((e, i) => { const o = el('option', null, e + rotuloEnd(e, i, s)); o.value = i; sel.append(o); });
    sel.value = iEnd;
    sel.addEventListener('change', () => { iEnd = +sel.value; atualizar(); });
    sec.append(el('p', 'msg', 'Rede em que o celular está:'), sel);
  }
  return sec;
}

// Copia texto (clipboard quando disponível; senão seleciona num campo temporário)
async function copiar(texto) {
  try { await navigator.clipboard.writeText(texto); return true; } catch (e) { /* sem permissão: cai no plano B */ }
  const t = document.createElement('textarea'); t.value = texto; t.style.position = 'fixed'; t.style.opacity = '0';
  document.body.append(t); t.select();
  let ok = false; try { ok = document.execCommand('copy'); } catch (e) { /* sem cópia */ }
  t.remove(); return ok;
}

// "Não abriu no celular?": 4 checagens em ordem e o comando do firewall pronto (caminho do python e portas deste servidor)
function secaoAjuda(s, todos) {
  const det = el('details', 'ajuda'), ip = todos[iEnd] || '';
  const portas = (s.portas && s.portas.length ? s.portas : [s.porta + 1, s.porta + 2]).join(',');
  const py = s.python || '<caminho do python.exe>';
  const cmd = 'New-NetFirewallRule -DisplayName "' + NOME_REGRA + '" -Direction Inbound -Program "' + py + '" -Protocol TCP -LocalPort '
    + portas + ' -Profile Private -Action Allow';
  det.id = 'celularAjuda';
  det.open = ajudaAberta;   // o painel se redesenha a cada 5 s: lembra se estava aberto
  det.addEventListener('toggle', () => { ajudaAberta = det.open; });
  det.append(el('summary', null, 'Não abriu no celular?'));
  const ol = el('ol');
  const li = (...partes) => { const x = el('li'); x.append(...partes); ol.append(x); return x; };
  li('Mesma sub-rede: no celular, Configurações → Wi-Fi → detalhes. O IP do celular deve começar igual ao do PC (',
    el('code', null, ip.split('.').slice(0, 3).join('.') + '.x'), '). Repetidor em modo roteador cria outra sub-rede.');
  li('Rede do Windows como Privada: no PowerShell, ', el('code', null, 'Get-NetConnectionProfile'), ' deve mostrar NetworkCategory = Private.');
  const c3 = li('Falta regra de entrada no Firewall (a regra antiga "Python" só no perfil Público não vale na rede Privada). '
    + 'Abra o PowerShell como Administrador e rode:');
  const caixa = el('code', 'comando', cmd); caixa.id = 'celularComando';
  const b = el('button', null, 'Copiar comando');
  b.id = 'celularCopiar';
  b.addEventListener('click', async () => {
    const ok = await copiar(cmd);
    b.textContent = ok ? 'Copiado ✓' : 'Selecione e copie o texto acima';
    setTimeout(() => { b.textContent = 'Copiar comando'; }, 2500);
  });
  c3.append(caixa, b);
  li('Isolamento de AP/clientes ligado no repetidor/roteador (Wi-Fi não fala com cabo): desligue. Teste no celular: abra ',
    el('code', null, 'http://' + ip + ':' + (s.https ? s.porta_ca : s.porta) + '/'), '.');
  det.append(ol, el('p', 'msg', 'Ignore endereços "virtuais" (vEthernet/WSL/Hyper-V): use o IP da placa real do PC.'));
  return det;
}

function secaoCertificado(s, todos) {
  const sec = el('div', 'passo'), qr = el('div'); qr.id = 'celularQrCa';
  sec.append(el('h4', null, '1. Instalar o certificado (uma vez por celular)'));
  const url = 'http://' + todos[iEnd] + ':' + s.porta_ca + '/';
  desenharQr(qr, url);
  const end = el('div'); end.id = 'celularEnderecoCa'; end.textContent = url;
  sec.append(el('p', 'msg', 'Aponte a câmera para este QR e siga as instruções da página (iPhone: perfil em Ajustes; Android: certificado de CA). '
    + 'Sem instalar, dá para aceitar o aviso do navegador uma vez conferindo a impressão digital.'), qr, end);
  sec.append(fingerprint('CA SHA-256', s.tls.ca_sha256), fingerprint('Servidor SHA-256', s.tls.servidor_sha256),
    el('div', 'msg', 'CA vale até ' + dia(s.tls.ca_expira) + ' · certificado do servidor até ' + dia(s.tls.servidor_expira) + ' · método: ' + (s.tls.metodo || '—')));
  const b = el('button', null, 'Recriar certificados');
  b.addEventListener('click', async () => {
    if (!confirm('Recriar a CA e o certificado? Todos os celulares precisarão instalar a CA de novo.')) return;
    try { await postar('/rede/tls/recriar', {}); codigo = null; atualizar(); } catch (e) { alert('Não consegui recriar: ' + e.message); }
  });
  sec.append(b);
  return sec;
}

function secaoGerar(s, todos) {
  const sec = el('div', 'passo gerar'), qr = el('div'), info = el('div', 'msg');
  qr.id = 'celularQr';
  sec.append(el('h4', null, (s.https ? '2. ' : '') + 'Parear o celular'));
  const sel = document.createElement('select'); sel.id = 'celularPerm';
  [['ver', 'Só ver'], ['conferir', 'Ver e conferir']].forEach(([v, t]) => { const o = el('option', null, t); o.value = v; sel.append(o); });
  sel.value = permEscolhida;
  sel.addEventListener('change', () => { permEscolhida = sel.value; });
  const gerar = el('button', null, 'Gerar QR code');
  gerar.addEventListener('click', async () => {
    gerar.disabled = true;
    try {
      const j = await postar('/rede/codigo', { permissao: sel.value });
      codigo = { urls: j.urls_pareamento, enderecos: j.enderecos, expira: j.expira_em * 1000, perm: j.permissao };
      atualizar();
    } catch (e) { info.textContent = 'Não consegui gerar o código: ' + e.message; }
    gerar.disabled = false;
  });
  sec.append(el('p', null, 'Permissão do novo aparelho:'), sel, gerar, qr, info);
  qr.hidden = true;
  if (!codigo || codigo.expira <= Date.now()) {
    codigo = null;
    info.textContent = 'Escolha a permissão e gere um QR code. Cada código vale uma vez e expira em 10 minutos.';
    return sec;
  }
  const i = Math.min(iEnd, codigo.urls.length - 1);
  qr.hidden = false;
  desenharQr(qr, codigo.urls[i]);
  const falta = Math.max(0, Math.round((codigo.expira - Date.now()) / 1000));
  info.append(el('div', null, 'Aponte a câmera do celular' + (s.https ? ' (com o certificado já instalado)' : '') + '. Vale uma vez · expira em '
    + Math.floor(falta / 60) + ':' + String(falta % 60).padStart(2, '0')));
  const end = el('div'); end.id = 'celularEndereco'; end.textContent = (s.https ? 'https://' : 'http://') + todos[i] + ':' + (s.https ? s.porta_https : s.porta) + '/';
  info.append(end);
  return sec;
}

function secaoAparelhos(s) {
  const sec = el('div', 'aparelhos'), ds = s.dispositivos || [];
  sec.append(el('h4', null, 'Aparelhos pareados · ' + ds.length));
  if (!ds.length) sec.append(el('p', 'msg', 'Nenhum ainda.'));
  for (const d of ds) {
    const li = el('div', 'aparelho'), t = el('div');
    t.append(el('b', null, d.nome), el('span', 'perm', d.permissao === 'conferir' ? ' · ver e conferir' : ' · só ver'));
    t.append(el('div', 'msg', 'pareado ' + quando(d.criado) + ' · último acesso ' + quando(d.ultimo_acesso) + ' · ' + (d.ultimo_ip || '—')));
    const b = el('button', null, 'Revogar');
    b.addEventListener('click', async () => {
      if (!confirm('Revogar "' + d.nome + '"? Ele perde o acesso na próxima requisição.')) return;
      try { await postar('/rede/revogar', { id: d.id }); atualizar(); } catch (e) { alert('Não consegui revogar: ' + e.message); }
    });
    li.append(t, b); sec.append(li);
  }
  if (ds.length > 1) {
    const b = el('button', null, 'Revogar todos');
    b.addEventListener('click', async () => {
      if (!confirm('Revogar TODOS os aparelhos pareados?')) return;
      try { await postar('/rede/revogar', { todos: true }); atualizar(); } catch (e) { alert('Não consegui revogar: ' + e.message); }
    });
    sec.append(b);
  }
  return sec;
}

async function atualizar() {
  let s;
  try { s = await pegar('/rede/status'); } catch (e) {
    corpo.replaceChildren(el('p', null, 'Não consegui consultar o servidor (' + e.message + '). Reinicie o escritório.'));
    return;
  }
  ultimo = s;
  if (!s.ativo) {
    const p = el('p');
    p.append('O acesso pelo celular está desligado (padrão, por segurança). Para ligar, feche o escritório e abra com ');
    p.append(el('code', null, COMO_LIGAR));
    p.append(' (ou ', el('code', null, 'servidor.py --rede-local'), '). Depois volte a este botão.');
    corpo.replaceChildren(p, aviso(true));
    return;
  }
  const todos = s.enderecos.concat(s.tailscale || []);
  if (!todos.length) {
    corpo.replaceChildren(el('p', null, 'Ligado, mas não achei o endereço desta máquina na rede privada. Conecte o PC ao Wi-Fi/cabo e abra de novo.'), aviso(s.https));
    return;
  }
  iEnd = Math.min(iEnd, todos.length - 1);
  const n = (s.dispositivos || []).length;
  if (codigo && vistos !== null && n > vistos) codigo = null;   // alguém pareou: o código foi consumido
  vistos = n;
  const partes = [];
  if (!s.https && s.tls && s.tls.erro) partes.push(el('p', 'aviso', 'HTTPS indisponível: ' + s.tls.erro + ' — usando HTTP na rede local (menos seguro).'));
  partes.push(secaoRede(s, todos));
  if (s.https) partes.push(secaoCertificado(s, todos));
  partes.push(secaoGerar(s, todos), secaoAparelhos(s), secaoAjuda(s, todos), aviso(s.https));
  corpo.replaceChildren(...partes);
}

function abrir() { painel.hidden = false; vistos = null; atualizar(); timer = setInterval(() => { if (!document.hidden) atualizar(); }, 5000); }
function fechar() {   // some da tela e do DOM (o QR leva o código)
  painel.hidden = true; clearInterval(timer); codigo = null; corpo.replaceChildren();
}

if (LOCAL && botao && painel) {
  botao.hidden = false;
  botao.addEventListener('click', () => (painel.hidden ? abrir() : fechar()));
  $('celularFechar').addEventListener('click', fechar);
  window.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !painel.hidden) fechar(); });
}
