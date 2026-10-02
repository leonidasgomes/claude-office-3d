// Modo leve para celular/tablet: toque (pointer: coarse) ou tela estreita. Importado por escritorio.js e celular.js.
export const MOVEL = matchMedia('(pointer: coarse)').matches || window.innerWidth < 760;
if (MOVEL) document.documentElement.classList.add('movel');
// Só o PC (aberto em localhost) mostra o botão e o QR do celular.
export const LOCAL = ['localhost', '127.0.0.1', '[::1]', '::1'].includes(location.hostname);
