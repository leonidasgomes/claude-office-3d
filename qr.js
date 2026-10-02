// Gerador de QR Code em JavaScript puro, sem dependências nem rede (implementação própria, ISO/IEC 18004).
// Modo byte (UTF-8), correção de erro M (ou L), versões 1 a 10, escolha automática da máscara.
// Uso: import { qrMatriz, qrCanvas } from './qr.js';  const m = qrMatriz('texto'); // m[y][x] === true -> módulo escuro

// Tabelas por versão (índice 0 não usado): bytes de correção por bloco e número de blocos.
const ECC_BLOCO = { L: [0, 7, 10, 15, 20, 26, 18, 20, 24, 30, 18], M: [0, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26] };
const N_BLOCOS = { L: [0, 1, 1, 1, 1, 1, 2, 2, 2, 2, 4], M: [0, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5] };
const BITS_NIVEL = { L: 1, M: 0 };
export const VERSAO_MAX = 10;

const modulosBrutos = (v) => {
  let r = (16 * v + 128) * v + 64;
  if (v >= 2) { const n = Math.floor(v / 7) + 2; r -= (25 * n - 10) * n - 55; if (v >= 7) r -= 36; }
  return r;
};
const codewordsDeDados = (v, n) => Math.floor(modulosBrutos(v) / 8) - ECC_BLOCO[n][v] * N_BLOCOS[n][v];
// bytes de texto que cabem na versão v (modo byte: 4 bits de modo + contador de 8/16 bits)
export const capacidade = (v, n = 'M') => codewordsDeDados(v, n) - (v < 10 ? 2 : 3);

// Aritmética de Reed-Solomon em GF(256), polinômio 0x11D
const EXP = new Uint8Array(512), LOG = new Uint8Array(256);
for (let i = 0, x = 1; i < 255; i++) { EXP[i] = x; LOG[x] = i; x <<= 1; if (x & 0x100) x ^= 0x11d; }
for (let i = 255; i < 512; i++) EXP[i] = EXP[i - 255];
const mul = (a, b) => (a && b ? EXP[LOG[a] + LOG[b]] : 0);

function divisor(grau) {
  const r = new Array(grau).fill(0); r[grau - 1] = 1;
  let raiz = 1;
  for (let i = 0; i < grau; i++) {
    for (let j = 0; j < grau; j++) { r[j] = mul(r[j], raiz); if (j + 1 < grau) r[j] ^= r[j + 1]; }
    raiz = mul(raiz, 2);
  }
  return r;
}
function resto(dados, div) {
  const r = new Array(div.length).fill(0);
  for (const b of dados) {
    const f = b ^ r.shift(); r.push(0);
    for (let i = 0; i < div.length; i++) r[i] ^= mul(div[i], f);
  }
  return r;
}

function utf8(texto) { return Array.from(new TextEncoder().encode(texto)); }

function codewordsDoTexto(bytes, v, n) {
  const bits = [];
  const poe = (val, len) => { for (let i = len - 1; i >= 0; i--) bits.push((val >>> i) & 1); };
  poe(0b0100, 4); poe(bytes.length, v < 10 ? 8 : 16);
  for (const b of bytes) poe(b, 8);
  const total = codewordsDeDados(v, n) * 8;
  poe(0, Math.min(4, total - bits.length));
  poe(0, (8 - bits.length % 8) % 8);
  for (let pad = 0xec; bits.length < total; pad ^= 0xec ^ 0x11) poe(pad, 8);
  const cw = [];
  for (let i = 0; i < bits.length; i += 8) cw.push(parseInt(bits.slice(i, i + 8).join(''), 2));
  return cw;
}

function intercalar(dados, v, n) {
  const nb = N_BLOCOS[n][v], eccLen = ECC_BLOCO[n][v];
  const brutos = Math.floor(modulosBrutos(v) / 8);
  const curtos = nb - brutos % nb, tamCurto = Math.floor(brutos / nb);
  const div = divisor(eccLen), blocos = [];
  for (let i = 0, k = 0; i < nb; i++) {
    const d = dados.slice(k, k + tamCurto - eccLen + (i < curtos ? 0 : 1)); k += d.length;
    const ecc = resto(d, div);
    if (i < curtos) d.push(0);
    blocos.push(d.concat(ecc));
  }
  const saida = [];
  for (let i = 0; i < blocos[0].length; i++)
    blocos.forEach((b, j) => { if (i !== tamCurto - eccLen || j >= curtos) saida.push(b[i]); });
  return saida;
}

function posicoesAlinhamento(v) {
  if (v === 1) return [];
  const n = Math.floor(v / 7) + 2, tam = v * 4 + 17;
  const passo = Math.ceil((v * 4 + 4) / (n * 2 - 2)) * 2;
  const r = [6];
  for (let pos = tam - 7; r.length < n; pos -= passo) r.splice(1, 0, pos);
  return r;
}

function novaGrade(v) {
  const tam = v * 4 + 17;
  const mod = Array.from({ length: tam }, () => new Array(tam).fill(false));
  const fn = Array.from({ length: tam }, () => new Array(tam).fill(false));
  const set = (x, y, escuro) => { if (x >= 0 && y >= 0 && x < tam && y < tam) { mod[y][x] = escuro; fn[y][x] = true; } };
  for (let i = 0; i < tam; i++) { set(6, i, i % 2 === 0); set(i, 6, i % 2 === 0); }
  const finder = (cx, cy) => {
    for (let dy = -4; dy <= 4; dy++) for (let dx = -4; dx <= 4; dx++) {
      const d = Math.max(Math.abs(dx), Math.abs(dy));
      set(cx + dx, cy + dy, d !== 2 && d !== 4);
    }
  };
  finder(3, 3); finder(tam - 4, 3); finder(3, tam - 4);
  const al = posicoesAlinhamento(v);
  al.forEach((cy, i) => al.forEach((cx, j) => {
    if ((i === 0 && j === 0) || (i === 0 && j === al.length - 1) || (i === al.length - 1 && j === 0)) return;
    for (let dy = -2; dy <= 2; dy++) for (let dx = -2; dx <= 2; dx++) set(cx + dx, cy + dy, Math.max(Math.abs(dx), Math.abs(dy)) !== 1);
  }));
  desenharFormato(mod, fn, tam, 0, 0, true);   // só reserva a área
  if (v >= 7) {
    let r = v;
    for (let i = 0; i < 12; i++) r = (r << 1) ^ ((r >>> 11) * 0x1f25);
    const bits = (v << 12) | r;
    for (let i = 0; i < 18; i++) {
      const b = ((bits >>> i) & 1) === 1, a = tam - 11 + i % 3, c = Math.floor(i / 3);
      set(a, c, b); set(c, a, b);
    }
  }
  return { mod, fn, tam };
}

function desenharFormato(mod, fn, tam, nivelBits, mascara, reservar = false) {
  const dados = (nivelBits << 3) | mascara;
  let r = dados;
  for (let i = 0; i < 10; i++) r = (r << 1) ^ ((r >>> 9) * 0x537);
  const bits = ((dados << 10) | r) ^ 0x5412;
  const bit = (i) => !reservar && ((bits >>> i) & 1) === 1;
  const set = (x, y, b) => { mod[y][x] = b; fn[y][x] = true; };
  for (let i = 0; i <= 5; i++) set(8, i, bit(i));
  set(8, 7, bit(6)); set(8, 8, bit(7)); set(7, 8, bit(8));
  for (let i = 9; i < 15; i++) set(14 - i, 8, bit(i));
  for (let i = 0; i < 8; i++) set(tam - 1 - i, 8, bit(i));
  for (let i = 8; i < 15; i++) set(8, tam - 15 + i, bit(i));
  set(8, tam - 8, true);
}

function colocarDados(g, cw) {
  const { mod, fn, tam } = g;
  let i = 0;
  for (let dir = tam - 1; dir >= 1; dir -= 2) {
    if (dir === 6) dir = 5;
    for (let vert = 0; vert < tam; vert++) for (let j = 0; j < 2; j++) {
      const x = dir - j, y = ((dir + 1) & 2) === 0 ? tam - 1 - vert : vert;
      if (!fn[y][x] && i < cw.length * 8) { mod[y][x] = ((cw[i >>> 3] >>> (7 - (i & 7))) & 1) === 1; i++; }
    }
  }
}

const MASCARAS = [
  (x, y) => (x + y) % 2 === 0, (x, y) => y % 2 === 0, (x, y) => x % 3 === 0, (x, y) => (x + y) % 3 === 0,
  (x, y) => (Math.floor(x / 3) + Math.floor(y / 2)) % 2 === 0, (x, y) => (x * y) % 2 + (x * y) % 3 === 0,
  (x, y) => ((x * y) % 2 + (x * y) % 3) % 2 === 0, (x, y) => ((x + y) % 2 + (x * y) % 3) % 2 === 0,
];
function aplicarMascara(g, m) {
  for (let y = 0; y < g.tam; y++) for (let x = 0; x < g.tam; x++) if (!g.fn[y][x] && MASCARAS[m](x, y)) g.mod[y][x] = !g.mod[y][x];
}

function penalidade(mod, tam) {
  let p = 0, escuros = 0;
  const varrer = (get) => {
    for (let a = 0; a < tam; a++) {
      let corrida = 1;
      for (let b = 1; b <= tam; b++) {
        if (b < tam && get(a, b) === get(a, b - 1)) corrida++;
        else { if (corrida >= 5) p += corrida - 2; corrida = 1; }
      }
      for (let b = 0; b + 11 <= tam; b++) {   // padrão tipo localizador 1:1:3:1:1 com 4 claros de um lado
        let t = '';
        for (let k = 0; k < 11; k++) t += get(a, b + k) ? '1' : '0';
        if (t === '10111010000' || t === '00001011101') p += 40;
      }
    }
  };
  varrer((y, x) => mod[y][x]);
  varrer((x, y) => mod[y][x]);
  for (let y = 0; y < tam; y++) for (let x = 0; x < tam; x++) {
    if (mod[y][x]) escuros++;
    if (x + 1 < tam && y + 1 < tam && mod[y][x] === mod[y][x + 1] && mod[y][x] === mod[y + 1][x] && mod[y][x] === mod[y + 1][x + 1]) p += 3;
  }
  p += Math.floor(Math.abs(escuros * 20 - tam * tam * 10) / (tam * tam)) * 10;
  return p;
}

// Devolve a matriz de módulos (array de linhas de booleanos). Lança Error se o texto não couber na versão 10.
export function qrMatriz(texto, nivel = 'M') {
  const bytes = utf8(String(texto));
  let v = 1;
  while (v <= VERSAO_MAX && bytes.length > capacidade(v, nivel)) v++;
  if (v > VERSAO_MAX) throw new Error('texto grande demais para o QR (máx. ' + capacidade(VERSAO_MAX, nivel) + ' bytes)');
  const cw = intercalar(codewordsDoTexto(bytes, v, nivel), v, nivel);
  let melhor = null, melhorP = Infinity;
  for (let m = 0; m < 8; m++) {
    const g = novaGrade(v);
    colocarDados(g, cw);
    aplicarMascara(g, m);
    desenharFormato(g.mod, g.fn, g.tam, BITS_NIVEL[nivel], m);
    const p = penalidade(g.mod, g.tam);
    if (p < melhorP) { melhorP = p; melhor = g.mod; }
  }
  return melhor;
}

// Desenha a matriz num <canvas> (fundo branco, margem de 4 módulos, módulos inteiros em pixels).
export function qrCanvas(canvas, texto, tamanho = 240, nivel = 'M') {
  const m = qrMatriz(texto, nivel), n = m.length, borda = 4;
  const px = Math.max(2, Math.floor(tamanho / (n + 2 * borda)));
  canvas.width = canvas.height = px * (n + 2 * borda);
  const c = canvas.getContext('2d');
  c.fillStyle = '#fff'; c.fillRect(0, 0, canvas.width, canvas.height);
  c.fillStyle = '#000';
  for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) if (m[y][x]) c.fillRect((x + borda) * px, (y + borda) * px, px, px);
  canvas.style.width = canvas.style.height = canvas.width + 'px';
  return m;
}
