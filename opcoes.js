// Menu ⚙️ Opções do painel lateral: Visão geral, Apelidos, Animações, Som, Demo e Celular (só no PC) num popover; no
// cabeçalho ficam só os painéis. Os botões das opções são os mesmos de antes (mesmos ids e handlers do escritorio.js,
// celular.js e placar.js); aqui só abre/fecha, posiciona e cuida do teclado. No celular (html.compacto) as opções viram
// a seção "⚙️ Opções" do menu ☰ (movel.js), sempre visível dentro dele.
// Teclado: Enter/Espaço/↓ no ⚙️ abre e foca o 1º item (↑: o último); ↑/↓/Home/End andam; Tab circula dentro do menu;
// Esc fecha e devolve o foco ao ⚙️; clique fora fecha. Opção de estado (Apelidos, Animações, Som, Demo) mantém o menu
// aberto para ver o estado novo; ação (Visão geral, Celular) fecha.
import './movel.js';   // html.compacto e o resize do movel antes dos deste módulo (não depender da ordem do escritorio.js)

const $ = (id) => document.getElementById(id);
const caixa = $('opcoes'), botao = $('btnOpcoes'), menu = $('menuOpcoes');
const compacto = () => document.documentElement.classList.contains('compacto');
let aberto = false;

const itens = () => [...menu.querySelectorAll('[role="menuitem"], [role="menuitemcheckbox"]')].filter((b) => !b.hidden && !b.disabled);

function posicionar() {   // fixo na tela (o painel lateral corta o que passa da borda dele)
  const r = botao.getBoundingClientRect(), w = menu.offsetWidth || 240, h = menu.offsetHeight || 260;
  const W = window.innerWidth, H = window.innerHeight;
  menu.style.left = Math.max(8, Math.min(W - w - 8, r.right - w)) + 'px';
  menu.style.top = Math.max(8, r.bottom + 6 + h > H - 8 ? r.top - h - 6 : r.bottom + 6) + 'px';
}
function abrir(foco = 'primeiro') {
  if (compacto()) return;
  aberto = true; menu.hidden = false; botao.setAttribute('aria-expanded', 'true');
  posicionar();
  const l = itens();
  const alvo = foco === 'ultimo' ? l[l.length - 1] : l[0];
  if (alvo) alvo.focus();
}
function fechar(devolverFoco = true) {
  if (!aberto) return;
  aberto = false; menu.hidden = true; botao.setAttribute('aria-expanded', 'false');
  if (devolverFoco) botao.focus();
}
function aplicarModo() {   // celular: seção do menu ☰ (sempre visível nele); PC: popover fechado
  const c = compacto();
  menu.classList.toggle('secao', c);
  if (c) { aberto = false; menu.hidden = false; menu.style.left = menu.style.top = ''; botao.setAttribute('aria-expanded', 'false'); }
  else if (!aberto) menu.hidden = true;
}

if (caixa && botao && menu) {
  aplicarModo();
  botao.addEventListener('click', () => (aberto ? fechar() : abrir()));
  botao.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); abrir('primeiro'); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); abrir('ultimo'); }
  });
  menu.addEventListener('keydown', (e) => {
    const l = itens(); if (!l.length) return;
    const i = l.indexOf(document.activeElement);
    const ir = (k) => { e.preventDefault(); l[(k + l.length) % l.length].focus(); };
    if (e.key === 'ArrowDown') ir(i + 1);
    else if (e.key === 'ArrowUp') ir(i - 1);
    else if (e.key === 'Home') ir(0);
    else if (e.key === 'End') ir(l.length - 1);
    else if (e.key === 'Tab' && aberto) ir(i + (e.shiftKey ? -1 : 1));   // foco circula dentro do menu aberto
    else if (e.key === 'Escape' && aberto) { e.preventDefault(); e.stopPropagation(); fechar(true); }
  });
  menu.addEventListener('click', (e) => {
    const b = e.target.closest('button');
    if (b && b.dataset.fecha && aberto) fechar(true);   // ação: o foco volta ao ⚙️ (com o teclado não fica num item escondido)
  });
  document.addEventListener('pointerdown', (e) => { if (aberto && !caixa.contains(e.target)) fechar(false); });
  window.addEventListener('resize', () => { aplicarModo(); if (aberto) posicionar(); });
  window.addEventListener('keydown', (e) => { if (e.key === 'Escape' && aberto) fechar(true); });
  window.__opcoes = { abrir, fechar, get aberto() { return aberto; } };
}
