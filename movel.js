// Modo celular/tablet. Importado por escritorio.js e celular.js.
//  * "movel": toque (pointer: coarse) ou tela pequena -> modo leve (pixel ratio 1, sem antialias) e alvos de toque grandes;
//  * "compacto": tela estreita (< 760 px) ou baixa (paisagem de celular, < 480 px) -> cena em tela cheia, painel de
//    agentes/feed vira uma "gaveta" inferior (recolhida / meio / cheia, arrastável), botões num menu "☰" e painéis
//    (Placar, PRs, Kanban, ficha, Celular) em tela cheia.
const coarse = matchMedia('(pointer: coarse)').matches;
const eCompacto = () => window.innerWidth < 760 || window.innerHeight < 480;
export const MOVEL = coarse || eCompacto();
export const COMPACTO = eCompacto();   // no momento do carregamento (o CSS acompanha a janela ao vivo)
// Só o PC (aberto em localhost) mostra o botão e o QR do celular.
export const LOCAL = ['localhost', '127.0.0.1', '[::1]', '::1'].includes(location.hostname);
// Altura (px) que a gaveta cobre da cena; escritorio.js desloca o centro da câmera para o que sobra visível.
export const gavetaInfo = { altura: 0 };

const raiz = document.documentElement;
function classes() {
  raiz.classList.toggle('movel', coarse || eCompacto());
  raiz.classList.toggle('compacto', eCompacto());
}
classes();

const $ = (id) => document.getElementById(id);
const painel = $('painel'), alca = $('gavetaAlca'), cab = painel && painel.querySelector('header');
const btnMenu = $('btnMenu'), menu = $('menuBotoes');
const MIN = 58;
let estado = 'min', alturaAtual = MIN, arrasto = null;

const alturaDe = (e) => {
  const H = window.innerHeight;
  return e === 'min' ? MIN : e === 'meio' ? Math.max(210, Math.round(H * 0.42)) : Math.max(260, Math.round(H * 0.86));
};
function aplicar(h, animar) {
  alturaAtual = h;
  gavetaInfo.altura = eCompacto() ? h : 0;
  painel.style.setProperty('--gaveta-h', h + 'px');
  painel.classList.toggle('arrastando', !animar);
  window.dispatchEvent(new CustomEvent('gaveta'));
}
function irPara(e) {
  estado = e; painel.dataset.estado = e;
  aplicar(alturaDe(e), true);
}
function fecharMenu() {
  if (!painel) return;
  painel.classList.remove('menu');
  if (btnMenu) btnMenu.setAttribute('aria-expanded', 'false');
}

if (painel && alca && cab && btnMenu && menu) {
  const proximo = () => (estado === 'min' ? 'meio' : estado === 'meio' ? 'cheia' : 'min');
  const inicio = (ev) => {
    if (!eCompacto() || ev.target.closest('button')) return;
    arrasto = { y0: ev.clientY, h0: alturaAtual, yUlt: ev.clientY, tUlt: performance.now(), vel: 0, moveu: false };
    ev.currentTarget.setPointerCapture(ev.pointerId);
  };
  const mover = (ev) => {
    if (!arrasto) return;
    const dy = arrasto.y0 - ev.clientY;
    if (Math.abs(dy) > 6) arrasto.moveu = true;
    if (!arrasto.moveu) return;
    const agora = performance.now();
    if (agora > arrasto.tUlt) arrasto.vel = (arrasto.yUlt - ev.clientY) / (agora - arrasto.tUlt);   // px/ms, positivo = para cima
    arrasto.yUlt = ev.clientY; arrasto.tUlt = agora;
    aplicar(Math.max(MIN, Math.min(alturaDe('cheia'), arrasto.h0 + dy)), false);
  };
  const fim = () => {
    if (!arrasto) return;
    const a = arrasto; arrasto = null;
    if (!a.moveu) return irPara(proximo());   // toque simples: avança recolhida -> meio -> cheia -> recolhida
    const alvo = alturaAtual + a.vel * 160;
    let melhor = 'min';
    for (const e of ['min', 'meio', 'cheia']) if (Math.abs(alturaDe(e) - alvo) < Math.abs(alturaDe(melhor) - alvo)) melhor = e;
    irPara(melhor);
  };
  for (const alvo of [alca, cab]) {
    alvo.addEventListener('pointerdown', inicio);
    alvo.addEventListener('pointermove', mover);
    alvo.addEventListener('pointerup', fim);
    alvo.addEventListener('pointercancel', fim);
  }
  alca.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); irPara(proximo()); } });

  btnMenu.addEventListener('click', () => {
    const abrir = !painel.classList.contains('menu');
    painel.classList.toggle('menu', abrir);
    btnMenu.setAttribute('aria-expanded', String(abrir));
  });
  menu.addEventListener('click', (e) => { if (e.target.closest('button')) fecharMenu(); });
  document.addEventListener('pointerdown', (e) => {
    if (painel.classList.contains('menu') && !menu.contains(e.target) && !btnMenu.contains(e.target)) fecharMenu();
  });
  window.addEventListener('keydown', (e) => { if (e.key === 'Escape') fecharMenu(); });
  window.addEventListener('resize', () => { classes(); fecharMenu(); irPara(estado); });
  irPara('min');
} else {
  window.addEventListener('resize', classes);
}
