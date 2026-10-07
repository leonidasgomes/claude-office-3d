// Claude Office 3D — dica acessível (ⓘ): explica como uma métrica é calculada.
// Abre com o mouse em cima, com o foco do teclado (Tab) e com toque/clique (fixa até tocar fora ou apertar Esc).
// Um balão só para a página toda (position: fixed, fica acima de painéis com rolagem); o texto de cada ⓘ também fica
// num <span> escondido ligado por aria-describedby, para o leitor de tela ler sem depender do balão.
// Uso: import { dica } from './dica.js';  el.append(dica('Texto de como é calculado', 'Nome da métrica'));
//      dica(...) devolve o <button>; textos com quebra de linha (\n) aparecem em linhas separadas.

let seq = 0, aberto = null, fixo = false, fecharTimer = null, semFoco = false;
const balao = document.createElement('div');
balao.id = 'dicaBalao'; balao.setAttribute('role', 'tooltip'); balao.hidden = true;
document.body.append(balao);
balao.addEventListener('pointerenter', () => clearTimeout(fecharTimer));   // dá para levar o mouse até o balão
balao.addEventListener('pointerleave', () => { if (!fixo) agendarFechar(); });

function posicionar(botao) {
  const r = botao.getBoundingClientRect(), m = 8, W = window.innerWidth, H = window.innerHeight;
  balao.style.maxWidth = Math.min(340, W - 2 * m) + 'px';
  balao.style.left = '0px'; balao.style.top = '0px';
  const b = balao.getBoundingClientRect();
  let x = r.left + r.width / 2 - b.width / 2;
  x = Math.max(m, Math.min(W - b.width - m, x));
  let y = r.bottom + 6;
  if (y + b.height > H - m && r.top - 6 - b.height >= m) y = r.top - 6 - b.height;   // sem espaço embaixo: abre em cima
  y = Math.max(m, Math.min(H - b.height - m, y));
  balao.style.left = Math.round(x) + 'px'; balao.style.top = Math.round(y) + 'px';
}
let peloMouse = false;   // aberto só pelo mouse em cima: o Esc fecha sem mexer no foco de quem está digitando
function mostrar(botao, fixar, mouse = false) {
  clearTimeout(fecharTimer);
  peloMouse = mouse && !fixar;
  if (aberto && aberto !== botao) aberto.setAttribute('aria-expanded', 'false');
  aberto = botao; fixo = !!fixar;
  balao.textContent = botao._dicaTexto;
  balao.hidden = false;
  botao.setAttribute('aria-expanded', 'true');
  posicionar(botao);
}
function esconder() {
  clearTimeout(fecharTimer);
  if (aberto) aberto.setAttribute('aria-expanded', 'false');
  aberto = null; fixo = false; balao.hidden = true;
}
function agendarFechar() { clearTimeout(fecharTimer); fecharTimer = setTimeout(esconder, 120); }

export function dica(texto, rotulo) {
  const b = document.createElement('button');
  b.type = 'button'; b.className = 'dica'; b.textContent = 'ⓘ';
  b.setAttribute('aria-label', 'Como é calculado' + (rotulo ? ': ' + rotulo : ''));
  b.setAttribute('aria-expanded', 'false');
  b._dicaTexto = String(texto || '');
  const id = 'dica-' + (++seq), sr = document.createElement('span');
  sr.id = id; sr.className = 'so-leitor'; sr.textContent = b._dicaTexto;
  b.setAttribute('aria-describedby', id);
  b.append(sr);
  b.addEventListener('pointerenter', (e) => { if (e.pointerType === 'mouse' && !fixo) mostrar(b, false, true); });
  b.addEventListener('pointerleave', (e) => { if (e.pointerType === 'mouse' && !fixo && aberto === b) agendarFechar(); });
  b.addEventListener('focus', () => { if (!semFoco && (!fixo || aberto !== b)) mostrar(b, false); });
  b.addEventListener('blur', () => { if (!fixo && aberto === b) agendarFechar(); });
  b.addEventListener('click', (e) => {
    e.stopPropagation(); e.preventDefault();   // não abre a ficha nem o <details> de quem contém o ⓘ
    if (aberto === b && fixo) esconder(); else mostrar(b, true);
  });
  return b;
}

// Esc fecha o balão antes do painel (fase de captura na window: os outros "Esc fecha" ficam na fase de bolha)
window.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape' || !aberto) return;
  const b = aberto, mouse = peloMouse; esconder();
  if (mouse) return;   // só o mouse em cima: o mesmo Esc segue e fecha o painel, e o foco fica onde estava
  e.stopPropagation(); if (b.isConnected) { semFoco = true; b.focus(); semFoco = false; }
}, true);
document.addEventListener('pointerdown', (e) => { if (aberto && !aberto.contains(e.target) && !balao.contains(e.target)) esconder(); });
window.addEventListener('resize', esconder);
document.addEventListener('scroll', () => { if (aberto) { if (aberto.isConnected) posicionar(aberto); else esconder(); } }, true);
// painel redesenhado (a cada 60 s) com o balão aberto: o botão antigo sai do DOM e o balão não pode ficar órfão
setInterval(() => { if (aberto && !aberto.isConnected) esconder(); }, 1000);
