// Claude Office 3D - escritório 3D onde os agentes do Claude Code trabalham.
// Cena leve: low-poly, sem sombras, materiais Lambert/Basic compartilhados.
// Time, cores, apelidos e tema vêm do config.json (lido do servidor em /config por config.js).
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { MOVEL, COMPACTO, gavetaInfo } from './movel.js';   // celular/tablet: modo leve (pixel ratio 1, sem antialias, menos confete)
const K_ROTULO = COMPACTO ? 1.45 : 1;   // balões e rótulos 3D maiores em tela pequena
import { CONFIG, chave as chaveNome, LIDER as LIDER_CFG } from './config.js';

const TEMA_SP = CONFIG.tema === 'sao-paulo';   // "sao-paulo": decoração temática; "neutro": sem ela
const AGENTES_CFG = CONFIG.agentes;
const LIDER = LIDER_CFG ? LIDER_CFG.nome : 'Lider';

// ---------------------------------------------------------------- Configuração
const ESCALA_VELOCIDADE = 3.2;      // unidades por segundo ao andar
const TEMPO_FALA = 4;               // s parado na mesa do destinatário
const TEMPO_REUNIAO = 20;           // s na sala de reunião
const JANELA_CONVOCACAO = 20;       // s: líder fala com 2+ colegas nesse intervalo = reunião
// não vão às reuniões: outra sessão, subagentes avulsos e os agentes marcados "auxiliar": true no config
const FORA_DA_REUNIAO = new Set(['Outra_Sessao', 'Assistente', ...AGENTES_CFG.filter((a) => a.auxiliar).map((a) => a.nome)]);
const DO_TIME = new Set(AGENTES_CFG.map((a) => a.nome));   // reunião para '*' chama só o time do config
const TEMPO_SUBAGENTE = 20;         // s de vida do subagente
const TEMPO_BALAO_TRABALHO = 5;     // s
const PAUSA_OCIOSO_MIN = 25;        // s ocioso (fila vazia) antes de poder ir a uma pausa
const TRABALHO_EXPIRA = 60;         // s sem eventos e o agente volta a "ocioso"
const MAX_COMANDO = 1800;           // s: teto de um comando longo em andamento (evento `inicio` do PreToolUse)
const MAX_MESAS = 10;
const INTERVALO_POLL = 2000;
const INTERVALO_POLL_OCULTO = 15000;   // aba oculta (celular com a tela apagada ou em outro app): quase não consulta
const MAX_FEED = 30;

const Z_CORREDOR = 5;               // corredor atrás das cadeiras
const SALA = { x0: 2, x1: 14, z0: 7.5, z1: 17, cx: 8, cz: 12.5 };
const ONDE_ESTOU = { porta: new THREE.Vector3(SALA.cx, 0, SALA.z0 + 0.6) };
const X_MESAS = [11, 5.8, 1.2, -3.4, -8, -12.6, -17.2, -21.8, -26.4, -31];
// Agente com "sala": "diretoria" no config: ganha uma sala fechada à direita da sala de reunião, com a mesa dele lá dentro
// (a porta fica na parede oeste). Sem nenhum agente assim, o escritório fica como sempre foi (sem a sala, piso menor).
const DIRETORIA = { x0: 18, x1: 28, z0: 7.5, z1: 17, cx: 23, mesaZ: 9.3, portaZ: 12.6, xCorredor: 16.6 };
const SALA_DE = {};                 // chave -> 'diretoria' (ver "sala" no config)
const TEM_DIRETORIA = AGENTES_CFG.some((a) => a.sala === 'diretoria');
const CORES_EXTRA = [0xa855f7, 0x14b8a6, 0xec4899, 0x06b6d4, 0x84cc16, 0xf97316];
const corHex = (c, padrao) => { const n = parseInt(String(c || '').replace('#', ''), 16); return Number.isFinite(n) ? n : padrao; };
// Por agente configurado (chave = nome em minúsculas): cor, nome de exibição + função, tipo de mesa e apelidos.
const CORES_FIXAS = { outra_sessao: 0x64748b };
const PERFIS = { outra_sessao: ['Outra sessão', 'Fora do time (outra janela do Claude)'] };
const MESA_DE = {};                 // chave -> 'lider' | 'dev' | 'design' | 'pesquisa' | 'padrao'
const ALIAS = {};                   // chave (com '_') de qualquer nome conhecido -> nome canônico
const CARGOS = { outra_sessao: 'Visita', assistente: 'Estagiário', explorador: 'Estagiária', planejador: 'Estagiário', guia_claude: 'Consultor' };
const FIXOS_BR = { assistente: 'Paulo' }, FIXOS_CINEMA = { assistente: 'Groot' };
AGENTES_CFG.forEach((ag, i) => {
  const k = String(ag.nome).toLowerCase();
  CORES_FIXAS[k] = corHex(ag.cor, CORES_EXTRA[i % CORES_EXTRA.length]);
  PERFIS[k] = [ag.titulo || ag.nome, ag.funcao || ''];
  MESA_DE[k] = ag.mesa || (i === 0 ? 'lider' : 'padrao');
  if (ag.sala === 'diretoria') SALA_DE[k] = 'diretoria';
  if (ag.cargo) CARGOS[k] = ag.cargo;
  if (ag.apelido_br) FIXOS_BR[k] = ag.apelido_br;
  if (ag.apelido_cinema) FIXOS_CINEMA[k] = ag.apelido_cinema;
  for (const o of [ag.nome, ...(ag.outros_nomes || [])]) ALIAS[chaveNome(o)] = ag.nome;
});
for (const o of ['main', 'lead', 'leader', 'team_lead']) if (!ALIAS[o]) ALIAS[o] = LIDER;
// Desconhecido: nome do evento + função do tipo.
// Subagentes avulsos (bonequinho temporário): função pelo tipo.
const FUNCOES_SUB = {
  'general-purpose': 'tarefa geral', explore: 'busca no código', plan: 'planejamento',
  'claude-code-guide': 'documentação do Claude', 'statusline-setup': 'configuração',
};
// ---------------------------------------------------------------- Apelidos (só na interface)
// Os nomes reais seguem nos eventos, no Kanban e nos PRs; aqui é só diversão. Modo guardado no navegador.
const MODOS_APELIDO = ['brasileiros', 'cinema', 'desligado'];
const ROTULO_MODO = { brasileiros: 'Apelidos: BR', cinema: 'Apelidos: cinema', desligado: 'Apelidos: off' };
const NOMES_BR = ['Ana', 'Bruno', 'Carla', 'Diego', 'Fernanda', 'Gabriel', 'Helena', 'Igor', 'Juliana', 'Kauã', 'Larissa',
  'Marcos', 'Natália', 'Otávio', 'Patrícia', 'Rafael', 'Sabrina', 'Thiago', 'Vanessa', 'Wesley', 'Yasmin', 'Zé'];
// Personagens de filme (não pessoas reais)
const NOMES_CINEMA = ['Yoda', 'Leia', 'Han', 'Ripley', 'Marty', 'Doc Brown', 'Gandalf', 'Frodo', 'Hermione', 'Shrek', 'Elsa',
  'Buzz', 'Woody', 'Furiosa', 'Ellie', 'Rocky', 'Forrest', 'Mulan', 'Jack Sparrow', 'Mary Poppins'];
// modo inicial do config.json; se você trocar no botão "Apelidos", a escolha fica guardada neste navegador
let modoApelido = MODOS_APELIDO.includes(CONFIG.apelidos) ? CONFIG.apelidos : 'desligado';
try { const m = localStorage.getItem('office.apelidos'); if (MODOS_APELIDO.includes(m)) modoApelido = m; } catch (e) {}
function hashNome(n) { let h = 0; for (const c of String(n)) h = (h * 31 + c.charCodeAt(0)) >>> 0; return h; }
function apelido(nome) {
  if (modoApelido === 'desligado') return '';
  const k = String(nome || '').toLowerCase();
  const fixos = modoApelido === 'cinema' ? FIXOS_CINEMA : FIXOS_BR, lista = modoApelido === 'cinema' ? NOMES_CINEMA : NOMES_BR;
  const pessoa = fixos[k] || lista[hashNome(k) % lista.length];
  const cargo = CARGOS[k] || (PERFIS[k] ? '' : 'Colega');   // agente do time sem "cargo" no config: só o apelido
  return (cargo ? cargo + ' ' : '') + pessoa;
}
// título mostrado: "João" em cima, "Dev · Código e testes" embaixo
function rotulos(nome, pf) {
  const ap = apelido(nome);
  return ap ? { titulo: ap, funcao: pf.titulo + (pf.funcao ? ' · ' + pf.funcao : '') } : { titulo: pf.titulo, funcao: pf.funcao };
}
function aplicarApelidos() {
  for (const a of ordemAgentes) {
    const r = rotulos(a.nome, perfil(a.nome));
    a.titulo = r.titulo; a.funcao = r.funcao;
    desenharNome(a.nomeSp, a.titulo, a.cor, a.funcao, a.xp);
    if (a.li) { a.li.querySelector('.nome').textContent = a.titulo; a.li.querySelector('.funcao').textContent = a.funcao; }
  }
  if (typeof desenharFicha === 'function') desenharFicha();
  const b = document.getElementById('btnApelidos'); if (b) b.textContent = ROTULO_MODO[modoApelido];
}

function perfil(nome, funcaoEv) {
  const k = String(nome || '').toLowerCase();
  if (PERFIS[k]) return { titulo: PERFIS[k][0], funcao: PERFIS[k][1] };
  const f = FUNCOES_SUB[String(funcaoEv || '').toLowerCase()] || funcaoEv || '';
  return { titulo: String(nome || 'Agente').replace(/_/g, ' '), funcao: f };
}
const ICONES = { bash: '⌨️', edit: '✏️', write: '✏️', multiedit: '✏️', read: '📖', grep: '🔍', glob: '🔍', task: '🤖',
  agent: '🤖', sendmessage: '💬', webfetch: '🌐', websearch: '🌐', blender: '🎨', unreal: '🎮', todowrite: '📝' };

const $ = (id) => document.getElementById(id);
let saltoRelogio = 0;                // só para depuração: __office.avancar(seg) adianta a simulação
const agora = () => performance.now() / 1000 + saltoRelogio;
const ulAgentes = $('agentes'), olFeed = $('feed');

// ---------------------------------------------------------------- Cena básica
const contCena = $('cena');
let renderer;
try {
  renderer = new THREE.WebGLRenderer({ antialias: !MOVEL, powerPreference: 'high-performance' });
} catch (e) {
  const el = $('erro'); el.hidden = false; el.textContent = 'WebGL indisponível neste navegador.';
  throw e;
}
renderer.setPixelRatio(MOVEL ? 1 : Math.min(window.devicePixelRatio || 1, 1.5));
renderer.shadowMap.enabled = false;
contCena.appendChild(renderer.domElement);

const cena = new THREE.Scene();
cena.background = new THREE.Color(0x1b2430);
const camera = new THREE.PerspectiveCamera(45, 1, 0.5, 300);
const VISAO_GERAL = TEM_DIRETORIA   // com a diretoria o escritório fica mais largo: a câmera enquadra tudo
  ? { pos: new THREE.Vector3(-3, 52, 74), alvo: new THREE.Vector3(-3, 0, 8) }
  : { pos: new THREE.Vector3(-10, 48, 68), alvo: new THREE.Vector3(-10, 0, 8) };
// em telas estreitas (retrato) a visão geral se afasta para a cena caber na largura
function posVisaoGeral() {
  const k = Math.min(2.1, Math.max(1, 0.9 / (camera.aspect || 1.5)));
  return VISAO_GERAL.alvo.clone().add(VISAO_GERAL.pos.clone().sub(VISAO_GERAL.alvo).multiplyScalar(k));
}
camera.position.copy(VISAO_GERAL.pos);
const controles = new OrbitControls(camera, renderer.domElement);
controles.target.copy(VISAO_GERAL.alvo);
controles.enableDamping = true;
controles.maxPolarAngle = Math.PI * 0.47;
controles.minDistance = 5;
controles.maxDistance = 150;

cena.add(new THREE.AmbientLight(0xffffff, 0.75));
const sol = new THREE.DirectionalLight(0xffffff, 0.8);
sol.position.set(-10, 25, 15);
cena.add(sol);

function redimensionar() {
  const w = contCena.clientWidth || 800, h = contCena.clientHeight || 600;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  ajustarGaveta();
}
// celular: a gaveta inferior cobre parte da cena; o centro da câmera sobe para o que sobra visível
function ajustarGaveta() {
  const w = contCena.clientWidth || 800, h = contCena.clientHeight || 600, d = Math.min(gavetaInfo.altura, h * 0.9);
  if (d > 0) camera.setViewOffset(w, h, 0, d / 2, w, h); else camera.clearViewOffset();
  camera.updateProjectionMatrix();
}
window.addEventListener('gaveta', ajustarGaveta);
new ResizeObserver(redimensionar).observe(contCena);
redimensionar();
camera.position.copy(posVisaoGeral());

// ---------------------------------------------------------------- Materiais e geometrias compartilhadas
const cacheMat = new Map();
function mat(cor, tipo = 'lambert') {
  const k = tipo + cor;
  if (!cacheMat.has(k)) cacheMat.set(k, tipo === 'basic' ? new THREE.MeshBasicMaterial({ color: cor }) : new THREE.MeshLambertMaterial({ color: cor }));
  return cacheMat.get(k);
}
const geoCaixa = new THREE.BoxGeometry(1, 1, 1);
function caixa(w, h, d, material, x, y, z, pai) {
  const m = new THREE.Mesh(geoCaixa, material);
  m.scale.set(w, h, d); m.position.set(x, y, z);
  (pai || cena).add(m);
  return m;
}
function cilindro(rt, rb, h, material, x, y, z, pai, seg = 12) {
  const m = new THREE.Mesh(new THREE.CylinderGeometry(rt, rb, h, seg), material);
  m.position.set(x, y, z);
  (pai || cena).add(m);
  return m;
}

// ---------------------------------------------------------------- Ambiente
function texturaPiso() {
  const c = document.createElement('canvas'); c.width = c.height = 64;
  const g = c.getContext('2d');
  g.fillStyle = '#5b6573'; g.fillRect(0, 0, 64, 64);
  g.fillStyle = '#525c6a'; g.fillRect(0, 0, 32, 32); g.fillRect(32, 32, 32, 32);
  const t = new THREE.CanvasTexture(c);
  t.wrapS = t.wrapT = THREE.RepeatWrapping; t.repeat.set(Math.round((LIM.x1 - LIM.x0) / 2), Math.round((LIM.z1 - LIM.z0) / 2)); t.magFilter = THREE.NearestFilter;
  return t;
}
const LIM = { x0: -34, x1: TEM_DIRETORIA ? 31 : 17, z0: -6, z1: 26 };  // piso ampliado: à esquerda as áreas de pausa, à frente a praça (maquete de SP no tema "sao-paulo")
(function construirAmbiente() {
  const piso = new THREE.Mesh(new THREE.PlaneGeometry(LIM.x1 - LIM.x0, LIM.z1 - LIM.z0), new THREE.MeshLambertMaterial({ map: texturaPiso() }));
  piso.rotation.x = -Math.PI / 2;
  piso.position.set((LIM.x0 + LIM.x1) / 2, 0, (LIM.z0 + LIM.z1) / 2);
  cena.add(piso);
  // tapete da sala de reunião
  const tapete = new THREE.Mesh(new THREE.PlaneGeometry(SALA.x1 - SALA.x0, SALA.z1 - SALA.z0), mat(0x3d4f66));
  tapete.rotation.x = -Math.PI / 2; tapete.position.set(SALA.cx, 0.02, (SALA.z0 + SALA.z1) / 2);
  cena.add(tapete);
  // paredes baixas (fundo, esquerda, direita)
  const par = mat(0x8a96a6), alt = 1.6, esp = 0.3;
  caixa(LIM.x1 - LIM.x0, alt, esp, par, (LIM.x0 + LIM.x1) / 2, alt / 2, LIM.z0, null);
  caixa(esp, alt, LIM.z1 - LIM.z0, par, LIM.x0, alt / 2, (LIM.z0 + LIM.z1) / 2, null);
  caixa(esp, alt, LIM.z1 - LIM.z0, par, LIM.x1, alt / 2, (LIM.z0 + LIM.z1) / 2, null);
  caixa(LIM.x1 - LIM.x0, 0.25, esp, mat(0x5f6b7b), (LIM.x0 + LIM.x1) / 2, 0.12, LIM.z1, null);
  // janelas decorativas no fundo
  for (let x = -31; x <= LIM.x1 - 3; x += 6) caixa(3.4, 0.9, 0.05, mat(0x7fb7e6, 'basic'), x, 1.0, LIM.z0 + 0.18, null);
})();

// Sala de reunião com paredes de vidro
const matVidro = new THREE.MeshBasicMaterial({ color: 0x9fd8ff, transparent: true, opacity: 0.18, depthWrite: false });
const matMoldura = mat(0xcfd8e3);
(function construirSala() {
  const h = 3, y = h / 2;
  const painel = (w, d, x, z) => { const m = caixa(w, h, d, matVidro, x, y, z, null); m.renderOrder = 2; };
  const moldura = (w, d, x, z) => caixa(w, 0.12, d, matMoldura, x, h, z, null);
  // lado de trás e laterais
  painel(SALA.x1 - SALA.x0, 0.06, SALA.cx, SALA.z1);
  painel(0.06, SALA.z1 - SALA.z0, SALA.x0, (SALA.z0 + SALA.z1) / 2);
  painel(0.06, SALA.z1 - SALA.z0, SALA.x1, (SALA.z0 + SALA.z1) / 2);
  // frente com porta (vão de 2.4 em torno de cx)
  const vao = 1.2;
  painel((SALA.cx - vao) - SALA.x0, 0.06, (SALA.x0 + SALA.cx - vao) / 2, SALA.z0);
  painel(SALA.x1 - (SALA.cx + vao), 0.06, (SALA.x1 + SALA.cx + vao) / 2, SALA.z0);
  moldura(SALA.x1 - SALA.x0, 0.12, SALA.cx, SALA.z1);
  moldura(SALA.x1 - SALA.x0, 0.12, SALA.cx, SALA.z0);
  moldura(0.12, SALA.z1 - SALA.z0, SALA.x0, (SALA.z0 + SALA.z1) / 2);
  moldura(0.12, SALA.z1 - SALA.z0, SALA.x1, (SALA.z0 + SALA.z1) / 2);
  // mesa redonda + cadeiras
  cilindro(1.9, 1.9, 0.14, mat(0xb9855a), SALA.cx, 1.0, SALA.cz, null, 20);
  cilindro(0.25, 0.4, 1.0, mat(0x4a4f57), SALA.cx, 0.5, SALA.cz, null, 8);
  for (let i = 0; i < 8; i++) {
    const a = ANGULO_ASSENTO(i);
    const x = SALA.cx + Math.cos(a) * 2.7, z = SALA.cz + Math.sin(a) * 2.7;
    const c = new THREE.Group(); c.position.set(x, 0, z); c.rotation.y = Math.atan2(-(Math.cos(a)), -(Math.sin(a)));
    caixa(0.8, 0.1, 0.8, mat(0x39424f), 0, 0.5, 0, c);
    caixa(0.8, 0.7, 0.1, mat(0x39424f), 0, 0.9, -0.4, c);
    caixa(0.1, 0.5, 0.1, mat(0x222831), 0, 0.25, 0, c);
    cena.add(c);
  }
  // quadro branco no fundo
  caixa(5, 1.8, 0.08, mat(0xf2f4f7), SALA.cx, 1.8, SALA.z1 - 0.3, null);
})();
function ANGULO_ASSENTO(i) { return -Math.PI / 2 + Math.PI / 8 + i * Math.PI / 4; }

function planta(x, z, esc = 1) {
  const g = new THREE.Group(); g.position.set(x, 0, z); g.scale.setScalar(esc);
  cilindro(0.4, 0.3, 0.6, mat(0x8b5a3c), 0, 0.3, 0, g, 8);
  const f = mat(0x2f9e5b);
  for (const [dx, dy, dz, r] of [[0, 1.0, 0, 0.55], [0.25, 1.4, 0.1, 0.4], [-0.2, 1.35, -0.1, 0.38]]) {
    const m = new THREE.Mesh(new THREE.IcosahedronGeometry(r, 0), f); m.position.set(dx, dy, dz); g.add(m);
  }
  cena.add(g);
}
[[-24.5, -4.5], [15.5, -4.5], [-32.5, -4.5], [15.5, 17.5], [0.2, 8.2], [15.5, 6], [-14, 8], [-3, -4.5]].forEach(([x, z]) => planta(x, z, 1 + Math.random() * 0.3));

// Impressora decorativa
caixa(1.2, 0.9, 0.9, mat(0xdde3ea), 0.4, 0.45, 17.5, null);

// ---------------------------------------------------------------- Sprites de texto
function criarSprite(w, h, escalaX, escalaY) {
  const canvas = document.createElement('canvas'); canvas.width = w; canvas.height = h;
  const tex = new THREE.CanvasTexture(canvas); tex.minFilter = THREE.LinearFilter; tex.generateMipmaps = false;
  const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: false }));
  sp.scale.set(escalaX * K_ROTULO, escalaY * K_ROTULO, 1); sp.renderOrder = 10;
  return { sprite: sp, canvas, ctx: canvas.getContext('2d'), tex };
}
function retArredondado(g, x, y, w, h, r) {
  g.beginPath(); g.moveTo(x + r, y); g.arcTo(x + w, y, x + w, y + h, r); g.arcTo(x + w, y + h, x, y + h, r);
  g.arcTo(x, y + h, x, y, r); g.arcTo(x, y, x + w, y, r); g.closePath();
}
function corCss(n) { return '#' + n.toString(16).padStart(6, '0'); }
const CORES_NIVEL = ['#9ca3af', '#60a5fa', '#34d399', '#f59e0b', '#e879f9'];   // 1 Estagiário .. 5 Mestre
const estrelas = (n, max = 5) => '★'.repeat(Math.max(0, Math.min(max, n))) + '☆'.repeat(Math.max(0, max - Math.min(max, n)));
function progressoXp(x) {   // 0..1 até o próximo nível (1 no nível máximo)
  if (!x || x.xp_proximo == null) return 1;
  const base = x.xp_base || 0, span = x.xp_proximo - base;
  return span > 0 ? Math.max(0, Math.min(1, (x.xp - base) / span)) : 1;
}
function desenharNome(s, texto, cor, funcao = '', xp = null) {
  const g = s.ctx; g.clearRect(0, 0, s.canvas.width, s.canvas.height);
  const H = s.canvas.height, W = s.canvas.width;
  g.font = 'bold 30px "Segoe UI", sans-serif'; const wNome = g.measureText(texto).width;
  g.font = '22px "Segoe UI", sans-serif'; const wFun = funcao ? g.measureText(funcao).width : 0;
  const linhaXp = xp ? estrelas(xp.nivel) + ' ' + xp.titulo + ' · ' + xp.xp + ' XP' : '';
  g.font = 'bold 22px "Segoe UI", sans-serif'; const wXp = linhaXp ? g.measureText(linhaXp).width : 0;
  const w = Math.min(W - 8, Math.max(wNome + 36, wFun + 24, wXp + 24));
  const alto = (funcao ? 78 : 46) + (xp ? 38 : 0), x = (W - w) / 2, y0 = H - alto - 6;
  g.fillStyle = 'rgba(15,20,25,0.84)'; retArredondado(g, x, y0, w, alto, 20); g.fill();
  g.fillStyle = corCss(cor); g.beginPath(); g.arc(x + 20, y0 + 23, 8, 0, 7); g.fill();
  g.textBaseline = 'middle'; g.textAlign = 'left';
  g.font = 'bold 30px "Segoe UI", sans-serif'; g.fillStyle = '#fff'; g.fillText(texto, x + 34, y0 + 24, w - 44);
  if (funcao) { g.font = '22px "Segoe UI", sans-serif'; g.fillStyle = '#b8c4d2'; g.fillText(funcao, x + 12, y0 + 58, w - 22); }
  if (xp) {
    const yl = y0 + (funcao ? 92 : 62), cn = CORES_NIVEL[Math.max(0, Math.min(4, xp.nivel - 1))];
    g.font = 'bold 22px "Segoe UI", sans-serif'; g.fillStyle = cn; g.fillText(linhaXp, x + 12, yl, w - 22);
    g.fillStyle = 'rgba(255,255,255,0.16)'; retArredondado(g, x + 12, yl + 17, w - 24, 6, 3); g.fill();
    const pw = Math.max(6, (w - 24) * progressoXp(xp));
    g.fillStyle = cn; retArredondado(g, x + 12, yl + 17, pw, 6, 3); g.fill();
  }
  s.tex.needsUpdate = true;
}
function quebrarTexto(g, texto, largura, maxLinhas) {
  const palavras = String(texto).split(/\s+/), linhas = []; let atual = '';
  for (const p of palavras) {
    const t = atual ? atual + ' ' + p : p;
    if (g.measureText(t).width > largura && atual) { linhas.push(atual); atual = p; } else atual = t;
  }
  if (atual) linhas.push(atual);
  if (linhas.length > maxLinhas) { linhas.length = maxLinhas; linhas[maxLinhas - 1] = linhas[maxLinhas - 1].replace(/.{0,2}$/, '…'); }
  return linhas;
}
function desenharBalao(s, texto, icone, cor) {
  const g = s.ctx, W = s.canvas.width, H = s.canvas.height;
  g.clearRect(0, 0, W, H);
  g.font = 'bold 32px "Segoe UI", sans-serif';
  const linhas = quebrarTexto(g, texto || '', W - 150, 2);
  const hb = 34 + linhas.length * 40;
  const y0 = H - hb - 22;
  g.fillStyle = 'rgba(255,255,255,0.96)'; retArredondado(g, 6, y0, W - 12, hb, 20); g.fill();
  g.lineWidth = 5; g.strokeStyle = corCss(cor); g.stroke();
  g.fillStyle = 'rgba(255,255,255,0.96)'; g.beginPath(); g.moveTo(W / 2 - 14, y0 + hb - 2); g.lineTo(W / 2, H - 4); g.lineTo(W / 2 + 14, y0 + hb - 2); g.fill();
  g.font = '48px "Segoe UI Emoji", "Apple Color Emoji", sans-serif'; g.textBaseline = 'middle'; g.textAlign = 'center'; g.fillStyle = '#000';
  g.fillText(icone || '💬', 60, y0 + hb / 2);
  g.font = 'bold 32px "Segoe UI", sans-serif'; g.textAlign = 'left'; g.fillStyle = '#111820';
  linhas.forEach((l, i) => g.fillText(l, 112, y0 + 34 + 20 + i * 40 - (linhas.length === 1 ? 10 : 0)));
  s.tex.needsUpdate = true;
}

// ---------------------------------------------------------------- Áreas de pausa (descanso, refeitório, banheiro)
// Cada "lugar" tem vagas (SLOTS) com ponto de assento, rota de entrada a partir do corredor e balões possíveis.
const SLOTS = [];
const V3 = (x, z) => new THREE.Vector3(x, 0, z);
const PORTA_BANHEIRO = { x: -30, zFrente: 8.4 };
// Cabines: o boneco para em zFrente, a porta abre (ABRIR s) e só então ele entra; a porta fica aberta enquanto o ocupante
// está visível na faixa da porta (z0..z1), inclusive ao sair ou ao ser chamado de volta no meio da pausa.
const CABINE = { zFrente: 14.9, z0: 14.3, z1: 17.4, aberta: 1.35, ABRIR: 0.55 };
function novoSlot(lugar, x, z, yaw, sentar, entX, rota, baloes) {
  const s = { lugar, pos: V3(x, z), yaw, sentar, entX, rota: rota.map(([a, b]) => V3(a, b)), baloes, ocupante: null };
  SLOTS.push(s);
  return s;
}
function criarPlaquinha(texto, cor, x, y, z, W = 384) {
  const s = criarSprite(W, 96, 5.0 * W / 384, 1.25);
  const g = s.ctx;
  g.font = 'bold 38px "Segoe UI", "Segoe UI Emoji", sans-serif';
  const w = Math.min(W - 8, g.measureText(texto).width + 70), x0 = (W - w) / 2, y0 = 16, h = 64;
  g.fillStyle = 'rgba(15,20,25,0.84)'; retArredondado(g, x0, y0, w, h, 22); g.fill();
  g.fillStyle = corCss(cor); g.beginPath(); g.arc(x0 + 24, y0 + h / 2, 9, 0, 7); g.fill();
  g.textBaseline = 'middle'; g.textAlign = 'left'; g.fillStyle = '#fff';
  g.fillText(texto, x0 + 44, y0 + h / 2 + 2, w - 54);
  s.tex.needsUpdate = true;
  s.sprite.position.set(x, y, z); cena.add(s.sprite);
  return s.sprite;
}
// TV: uma única textura de canvas, redesenhada só ao trocar de canal (a cada ~8-12 s).
const TV_W = 512, TV_H = 264;
const canvasTV = document.createElement('canvas'); canvasTV.width = TV_W; canvasTV.height = TV_H;
const texTV = new THREE.CanvasTexture(canvasTV); texTV.minFilter = THREE.LinearFilter; texTV.generateMipmaps = false;
const matTV = new THREE.MeshBasicMaterial({ map: texTV });
const FONTE_TV = '"Segoe UI", "Segoe UI Emoji", sans-serif';
// Textos da TV: temáticos de SP no tema "sao-paulo", genéricos no "neutro"
const TXT_TV = TEMA_SP
  ? { jornal: 'SP AGORA', manchete: 'Trânsito na Marginal: 12 km de lentidão', placar: "Timão 1 x 1 Verdão  67'", novela: 'Amor em SP · capítulo 128',
    desenho: 'Turma da Garoa', tempo: 'garoa em SP 🌧️ 18°', tempoSub: 'Máx 21° · Mín 15° · leve frio', receita: 'Receita de pastel', chef: 'com a Chef Dona Maria' }
  : { jornal: 'JORNAL 24H', manchete: 'Mercado de tecnologia em alta nesta semana', placar: "Azuis 1 x 1 Verdes  67'", novela: 'Amor & Código · capítulo 128',
    desenho: 'Turma do Pixel', tempo: 'parcialmente nublado ⛅ 22°', tempoSub: 'Máx 25° · Mín 16° · tempo firme', receita: 'Receita de bolo', chef: 'com a Chef da casa' };
const CANAIS_TV = [
  { nome: 'jornal', aoVivo: true, desenhar(g, W, H) {
    const gr = g.createLinearGradient(0, 0, W, H); gr.addColorStop(0, '#12306b'); gr.addColorStop(1, '#2563eb'); g.fillStyle = gr; g.fillRect(0, 0, W, H);
    g.fillStyle = '#0b1b3f'; [[300, 120, 40], [345, 90, 30], [380, 140, 44], [430, 100, 36], [470, 125, 34]].forEach(([x, h, w]) => g.fillRect(x, H - 70 - h, w, h));
    g.fillStyle = '#1f2937'; g.beginPath(); g.moveTo(70, H - 70); g.quadraticCurveTo(150, 105, 230, H - 70); g.fill();
    g.fillStyle = '#f1c7a0'; g.beginPath(); g.arc(150, 92, 34, 0, 7); g.fill(); g.fillStyle = '#2b2118'; g.fillRect(116, 54, 68, 18);
    g.fillStyle = '#dc2626'; g.fillRect(0, H - 70, W, 32); g.fillStyle = '#fff'; g.fillRect(0, H - 38, W, 38);
    g.textBaseline = 'middle'; g.textAlign = 'left'; g.font = 'bold 24px ' + FONTE_TV; g.fillText(TXT_TV.jornal, 16, H - 54);
    g.fillStyle = '#111'; g.font = 'bold 21px ' + FONTE_TV; g.fillText(TXT_TV.manchete, 12, H - 19, W - 24); } },
  { nome: 'futebol', aoVivo: true, desenhar(g, W, H) {
    for (let i = 0; i < 8; i++) { g.fillStyle = i % 2 ? '#2f9e44' : '#37b24d'; g.fillRect(i * W / 8, 0, W / 8, H); }
    g.strokeStyle = '#fff'; g.lineWidth = 4; g.strokeRect(24, 36, W - 48, H - 62); g.beginPath(); g.moveTo(W / 2, 36); g.lineTo(W / 2, H - 26); g.stroke();
    g.beginPath(); g.arc(W / 2, H / 2 + 5, 38, 0, 7); g.stroke(); g.strokeRect(24, H / 2 - 50, 60, 100); g.strokeRect(W - 84, H / 2 - 50, 60, 100);
    [[150, 100, '#facc15'], [200, 170, '#facc15'], [270, 120, '#16a34a'], [330, 190, '#16a34a'], [380, 110, '#facc15'], [230, 140, '#16a34a']].forEach(([x, y, c]) => { g.fillStyle = c; g.beginPath(); g.arc(x, y, 9, 0, 7); g.fill(); });
    g.fillStyle = '#fff'; g.beginPath(); g.arc(255, 150, 6, 0, 7); g.fill();
    g.fillStyle = 'rgba(0,0,0,0.75)'; g.fillRect(14, 8, 250, 34); g.fillStyle = '#fff'; g.textBaseline = 'middle'; g.textAlign = 'left';
    g.font = 'bold 22px ' + FONTE_TV; g.fillText(TXT_TV.placar, 22, 26); } },
  { nome: 'novela', aoVivo: false, desenhar(g, W, H) {
    const gr = g.createLinearGradient(0, 0, 0, H); gr.addColorStop(0, '#9d174d'); gr.addColorStop(1, '#4c1d95'); g.fillStyle = gr; g.fillRect(0, 0, W, H);
    for (const [x, pele, cab] of [[150, '#f1c7a0', '#3b2314'], [362, '#d9a273', '#e8c26a']]) {
      g.fillStyle = '#1f2937'; g.beginPath(); g.moveTo(x - 80, H); g.quadraticCurveTo(x, 130, x + 80, H); g.fill();
      g.fillStyle = cab; g.beginPath(); g.arc(x, 112, 46, 0, 7); g.fill(); g.fillStyle = pele; g.beginPath(); g.arc(x, 120, 38, 0, 7); g.fill();
    }
    g.fillStyle = '#ff4d6d'; g.beginPath(); g.moveTo(256, 130); g.bezierCurveTo(200, 70, 230, 40, 256, 70); g.bezierCurveTo(282, 40, 312, 70, 256, 130); g.fill();
    g.fillStyle = 'rgba(0,0,0,0.6)'; g.fillRect(0, H - 40, W, 40); g.fillStyle = '#fff'; g.textBaseline = 'middle'; g.textAlign = 'center';
    g.font = 'bold 22px ' + FONTE_TV; g.fillText(TXT_TV.novela, W / 2, H - 20); } },
  { nome: 'desenho', aoVivo: false, desenhar(g, W, H) {
    g.fillStyle = '#7dd3fc'; g.fillRect(0, 0, W, H); g.fillStyle = '#4ade80'; g.fillRect(0, H - 70, W, 70);
    g.fillStyle = '#facc15'; g.beginPath(); g.arc(70, 60, 34, 0, 7); g.fill();
    ['#f43f5e', '#8b5cf6', '#f97316'].forEach((c, i) => { const x = 130 + i * 120 + Math.random() * 20, y = H - 110 - Math.random() * 40;
      g.fillStyle = c; g.beginPath(); g.arc(x, y, 38, 0, 7); g.fill(); g.fillStyle = '#fff'; g.beginPath(); g.arc(x - 12, y - 8, 11, 0, 7); g.arc(x + 12, y - 8, 11, 0, 7); g.fill();
      g.fillStyle = '#111'; g.beginPath(); g.arc(x - 10, y - 8, 5, 0, 7); g.arc(x + 14, y - 8, 5, 0, 7); g.fill(); g.strokeStyle = '#111'; g.lineWidth = 4; g.beginPath(); g.arc(x, y + 8, 14, 0.1, Math.PI - 0.1); g.stroke(); });
    g.fillStyle = '#111'; g.font = 'bold 28px ' + FONTE_TV; g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText(TXT_TV.desenho, W / 2, 36); } },
  { nome: 'tempo', aoVivo: false, desenhar(g, W, H) {
    const gr = g.createLinearGradient(0, 0, 0, H); gr.addColorStop(0, '#475569'); gr.addColorStop(1, '#94a3b8'); g.fillStyle = gr; g.fillRect(0, 0, W, H);
    g.fillStyle = '#e2e8f0'; g.beginPath(); g.arc(140, 100, 40, 0, 7); g.arc(190, 80, 50, 0, 7); g.arc(245, 105, 38, 0, 7); g.fill(); g.fillRect(140, 100, 105, 40);
    g.strokeStyle = '#38bdf8'; g.lineWidth = 4; for (let i = 0; i < 12; i++) { const x = 120 + i * 12, y = 150 + (i % 3) * 14; g.beginPath(); g.moveTo(x, y); g.lineTo(x - 6, y + 18); g.stroke(); }
    g.fillStyle = '#fff'; g.textBaseline = 'middle'; g.textAlign = 'left'; g.font = 'bold 34px ' + FONTE_TV; g.fillText(TXT_TV.tempo, 20, H - 70);
    g.font = '24px ' + FONTE_TV; g.fillText(TXT_TV.tempoSub, 20, H - 30); } },
  { nome: 'culinaria', aoVivo: false, desenhar(g, W, H) {
    g.fillStyle = '#fde68a'; g.fillRect(0, 0, W, H); g.fillStyle = '#92400e'; g.fillRect(0, H - 90, W, 90);
    g.fillStyle = '#e0a030'; g.beginPath(); g.arc(256, H - 90, 80, Math.PI, 0); g.fill();
    g.strokeStyle = '#a16207'; g.lineWidth = 4; for (let i = 0; i < 9; i++) { g.beginPath(); g.moveTo(186 + i * 17, H - 90); g.lineTo(190 + i * 17, H - 100); g.stroke(); }
    g.fillStyle = '#fff'; g.fillRect(40, 30, 70, 30); g.beginPath(); g.arc(75, 30, 28, Math.PI, 0); g.fill();
    g.fillStyle = '#7c2d12'; g.textBaseline = 'middle'; g.textAlign = 'center'; g.font = 'bold 36px ' + FONTE_TV; g.fillText(TXT_TV.receita, W / 2, 44);
    g.fillStyle = '#fff'; g.font = '22px ' + FONTE_TV; g.fillText(TXT_TV.chef, W / 2, H - 40); } },
];
let canalTV = -1, tvProx = 0;
function trocarCanalTV(t) {
  let n; do { n = Math.floor(Math.random() * CANAIS_TV.length); } while (n === canalTV);
  canalTV = n; tvProx = t + 8 + Math.random() * 4;
  const g = canvasTV.getContext('2d'); g.clearRect(0, 0, TV_W, TV_H);
  CANAIS_TV[n].desenhar(g, TV_W, TV_H);
  texTV.needsUpdate = true;
}
trocarCanalTV(0);
const matArcade = new THREE.MeshBasicMaterial({ color: 0xf43f5e });
let seloAoVivo = null;
const bolaPP = new THREE.Mesh(new THREE.SphereGeometry(0.06, 8, 6), mat(0xfff1c9, 'basic'));
bolaPP.visible = false;
(function construirAreasPausa() {
  const tapete = (cx, cz, w, d, cor) => {
    const m = new THREE.Mesh(new THREE.PlaneGeometry(w, d), mat(cor));
    m.rotation.x = -Math.PI / 2; m.position.set(cx, 0.02, cz); cena.add(m);
  };
  const par = mat(0x8a96a6), claro = mat(0xdde3ea), escuro = mat(0x2b313a);

  // ---------- Descanso: sofá, pufes, TV, fliperama e plantas (x -13..-2)
  const CXD = -7.5, ZTV = 9.3;
  tapete(CXD, 13.6, 10.6, 9.6, 0x5a4a7a);
  caixa(3.4, 0.7, 0.8, mat(0x3a3f47), CXD, 0.35, ZTV);
  caixa(3.1, 1.75, 0.12, mat(0x0b0f14), CXD, 1.65, ZTV);
  caixa(2.8, 1.45, 0.04, matTV, CXD, 1.65, ZTV + 0.08);
  const cb = document.createElement('canvas'); cb.width = 128; cb.height = 40;
  const gb = cb.getContext('2d'); gb.fillStyle = '#dc2626'; retArredondado(gb, 2, 2, 124, 36, 10); gb.fill(); gb.fillStyle = '#fff'; gb.font = 'bold 24px "Segoe UI", sans-serif';
  gb.textAlign = 'center'; gb.textBaseline = 'middle'; gb.fillText('● AO VIVO', 64, 21);
  seloAoVivo = new THREE.Mesh(new THREE.PlaneGeometry(0.6, 0.19), new THREE.MeshBasicMaterial({ map: new THREE.CanvasTexture(cb), transparent: true }));
  seloAoVivo.position.set(CXD + 1.05, 2.27, ZTV + 0.105); cena.add(seloAoVivo);
  const sg = new THREE.Group(); sg.position.set(CXD, 0, 13.4); cena.add(sg);
  const sofa = mat(0x6b4f8a), sofaEsc = mat(0x57406f);
  caixa(4.2, 0.5, 1.2, sofa, 0, 0.25, 0, sg);
  caixa(4.2, 0.85, 0.25, sofaEsc, 0, 0.8, 0.55, sg);
  caixa(0.3, 0.75, 1.2, sofaEsc, -2.25, 0.55, 0, sg); caixa(0.3, 0.75, 1.2, sofaEsc, 2.25, 0.55, 0, sg);
  const olhaTV = (x, z) => yawPara(V3(x, z), V3(CXD, ZTV));
  const baloesTV = [['☕', 'pausa'], ['📺', 'assistindo TV']];
  const rotaD = (x) => [[-10.8, 11.4], [x, 11.4]];
  for (const dx of [-1.2, 0, 1.2]) novoSlot('descanso', CXD + dx, 13.3, Math.PI, true, -10.8, rotaD(CXD + dx), baloesTV);
  cilindro(0.6, 0.6, 0.5, mat(0xe0884a), -3.8, 0.25, 13.6, null, 10);
  cilindro(0.6, 0.6, 0.5, mat(0x4aa3e0), -3.8, 0.25, 15.6, null, 10);
  novoSlot('descanso', -3.8, 13.6, olhaTV(-3.8, 13.6), true, -10.8, rotaD(-3.8), baloesTV);
  novoSlot('descanso', -3.8, 15.6, olhaTV(-3.8, 15.6), true, -10.8, [[-10.8, 11.4], [-2.2, 11.4], [-2.2, 15.6]], baloesTV);
  // fliperama (tela voltada para o jogador, que fica de frente para ele)
  const fg = new THREE.Group(); fg.position.set(-2.9, 0, 8.9); cena.add(fg);
  caixa(1.1, 2.0, 0.9, mat(0x1e3a8a), 0, 1.0, 0, fg);
  caixa(0.8, 0.55, 0.04, matArcade, 0, 1.55, 0.47, fg);
  caixa(1.0, 0.12, 0.5, mat(0x0f172a), 0, 1.0, 0.6, fg);
  caixa(0.08, 0.2, 0.08, mat(0xfacc15), -0.25, 1.15, 0.6, fg);
  novoSlot('descanso', -2.9, 10.3, Math.PI, false, -10.8, rotaD(-2.9), [['🎮', 'fliperama']]);
  planta(-12.4, 9.4, 1); planta(-12.4, 18.2, 1.1); planta(-2.3, 18.3, 1);
  // mesa de ping-pong (jogam 2 agentes em pausa, um de cada lado)
  const PPX = -9.2, PPZ = 16.9, verdePP = mat(0x1f7a4d);
  caixa(2.4, 0.08, 1.3, verdePP, PPX, 0.95, PPZ);
  caixa(0.03, 0.01, 1.3, mat(0xffffff), PPX, 0.996, PPZ);
  caixa(2.4, 0.01, 0.03, mat(0xffffff), PPX, 0.996, PPZ);
  caixa(0.02, 0.2, 1.45, mat(0xe5e7eb), PPX, 1.1, PPZ);
  for (const dx of [-1.0, 1.0]) caixa(0.08, 0.9, 1.0, escuro, PPX + dx, 0.45, PPZ);
  cena.add(bolaPP);
  const sA = novoSlot('descanso', -11.3, PPZ, Math.PI / 2, false, -10.8, [[-10.8, 11.4], [-10.8, PPZ]], [['🏓', 'ping-pong']]); sA.pp = 'A';
  const sB = novoSlot('descanso', -6.9, PPZ, -Math.PI / 2, false, -10.8, [[-10.8, 11.4], [-10.8, 15.0], [-6.9, 15.0]], [['🏓', 'ping-pong']]); sB.pp = 'B';

  // ---------- Refeitório: mesas com cadeiras e balcão (x -25..-14)
  const CXR = -19.5;
  tapete(CXR, 13.6, 11, 9.6, 0x6e665a);
  const cadeira = mat(0x2d3643), tampo = mat(0xb08a5e);
  for (const tcx of [-22.2, -16.8]) {
    caixa(2.6, 0.12, 1.4, tampo, tcx, 0.95, 12.5);
    caixa(0.25, 0.9, 0.9, escuro, tcx, 0.45, 12.5);
    for (const dx of [-0.7, 0.7]) {
      for (const frente of [true, false]) {
        const z = frente ? 11.2 : 13.8, costas = frente ? -0.31 : 0.31;   // frente: olha +z; costas: olha -z
        caixa(0.7, 0.08, 0.7, cadeira, tcx + dx, 0.5, z);
        caixa(0.7, 0.7, 0.08, cadeira, tcx + dx, 0.88, z + costas);
        caixa(0.1, 0.5, 0.1, escuro, tcx + dx, 0.25, z);
        const rota = frente ? [[CXR, 10.3], [tcx, 10.3], [tcx, 11.2]] : [[CXR, 14.6], [tcx, 14.6], [tcx, 13.8]];
        novoSlot('refeitorio', tcx + dx, z, frente ? 0 : Math.PI, true, CXR, rota, [['🍽️', 'lanche'], ['☕', 'café']]);
      }
    }
  }
  caixa(8.2, 1.0, 0.9, mat(0x5a6573), CXR, 0.5, 18.3);
  caixa(8.4, 0.08, 1.0, mat(0xcbd2da), CXR, 1.04, 18.3);
  caixa(0.45, 0.55, 0.4, mat(0x222831), -20.5, 1.35, 18.3);                          // cafeteira
  caixa(0.1, 0.1, 0.02, mat(0xff4d4d, 'basic'), -20.5, 1.55, 18.08);
  caixa(0.9, 0.5, 0.6, mat(0xd7dde5), -18.2, 1.33, 18.3);                            // micro-ondas
  caixa(0.55, 0.35, 0.02, mat(0x1b2430, 'basic'), -18.35, 1.33, 17.99);
  caixa(1.0, 2.1, 0.9, mat(0xe6ecf2), -24.4, 1.05, 18.3);                            // geladeira
  caixa(0.06, 0.7, 0.06, mat(0x7a8594), -24.0, 1.3, 17.82);
  for (const x of [-20.5, -18.2]) novoSlot('refeitorio', x, 17.0, 0, false, CXR, [[CXR, 15.6], [x, 15.6]], [['☕', 'café'], ['🍽️', 'lanche']]);
  planta(-14.3, 18.2, 1);

  // ---------- Banheiro: porta com plaquinha, 2 pias e 2 cabines (x -34..-26)
  const alt = 1.6;
  tapete(-30, 13.7, 7.6, 10.4, 0x7aa0b8);
  caixa(3, alt, 0.25, par, -32.5, alt / 2, 8.4); caixa(3, alt, 0.25, par, -27.5, alt / 2, 8.4);
  caixa(0.25, alt, 10.6, par, -26.0, alt / 2, 13.7);
  caixa(7.8, 0.9, 0.2, par, -30, 0.45, 19.0);
  caixa(0.25, 2.3, 0.35, claro, -31.1, 1.15, 8.4); caixa(0.25, 2.3, 0.35, claro, -28.9, 1.15, 8.4);
  caixa(2.45, 0.3, 0.35, claro, -30, 2.25, 8.4);
  const pivo = new THREE.Group(); pivo.position.set(-28.95, 0, 8.4); pivo.rotation.y = 1.2; cena.add(pivo);   // porta entreaberta
  caixa(1.0, 1.9, 0.06, mat(0x4a8fd6), -0.5, 0.95, 0, pivo);
  criarPlaquinha('🚻 Banheiro', 0x38bdf8, -30, 3.3, 8.6);
  caixa(0.8, 0.9, 4.2, claro, -33.4, 0.45, 12.0);                                    // bancada com 2 pias
  caixa(0.05, 1.0, 3.6, mat(0xbfe3ff, 'basic'), -33.75, 1.7, 12.0);                  // espelho
  for (const z of [11.2, 12.8]) {
    caixa(0.5, 0.08, 0.6, mat(0x93c5fd), -33.35, 0.92, z);
    caixa(0.1, 0.2, 0.1, mat(0xbfc7d1), -33.6, 1.05, z);
  }
  [-32.4, -29.7, -27.0].forEach((x) => caixa(0.08, 2.0, 3.1, mat(0xcfd8e3), x, 1.0, 17.35));
  [[-31.05, 0x4a8fd6, 11.2], [-28.35, 0xf59e0b, 12.8]].forEach(([cx, cor, zPia], i) => {
    const dobradica = new THREE.Group(); dobradica.position.set(cx - 1.3, 0, 15.8); cena.add(dobradica);   // porta da cabine (abre para fora)
    caixa(2.6, 1.7, 0.06, mat(cor), 1.3, 1.05, 0, dobradica);
    caixa(0.6, 0.4, 0.7, mat(0xf2f4f7), cx, 0.2, 18.4); caixa(0.6, 0.6, 0.25, mat(0xf2f4f7), cx, 0.7, 18.75);
    const s = novoSlot('banheiro', cx, 17.2, Math.PI, false, PORTA_BANHEIRO.x, [[PORTA_BANHEIRO.x, 9.8], [cx, 14.4]], [['🚻', 'banheiro']]);
    s.pia = V3(-32.4, zPia);
    s.frente = V3(cx, CABINE.zFrente);
    s.porta = { dobradica, x: cx };
  });

  criarPlaquinha('🛋️ Descanso', 0x8b5cf6, CXD, 3.3, 8.7);
  criarPlaquinha('🍽️ Refeitório', 0xf59e0b, CXR, 3.3, 8.7);
})();
let tPortas = 0;
function animarPortasCabine(t) {
  const dt = Math.min(0.1, Math.max(0, t - tPortas)); tPortas = t;
  for (const s of SLOTS) {
    if (!s.porta) continue;
    const o = s.ocupante;
    const perto = o && o.fig.dentro.visible && Math.abs(o.pos.x - s.porta.x) < 1.3 && o.pos.z > CABINE.z0 && o.pos.z < CABINE.z1;
    const r = s.porta.dobradica.rotation, alvo = perto ? CABINE.aberta : 0;
    r.y += (alvo - r.y) * Math.min(1, dt * 9);
  }
}
function animarAreas(t) {
  animarPortasCabine(t);
  if (t >= tvProx) trocarCanalTV(t);
  matTV.color.setScalar(0.92 + 0.08 * Math.sin(t * 3.1));
  if (seloAoVivo) seloAoVivo.visible = CANAIS_TV[canalTV].aoVivo && Math.floor(t * 1.6) % 2 === 0;   // "AO VIVO" pisca
  matArcade.color.setHSL((t * 0.4) % 1, 0.8, 0.5 + 0.1 * Math.sin(t * 8));
}

// ---------------------------------------------------------------- Decoração de São Paulo (só no tema "sao-paulo")
// Placa/quadro plano com textura desenhada em canvas (barato: 1 malha, material Basic).
function placaCanvas(w, h, cw, ch, x, y, z, desenhar, rotY = 0) {
  const c = document.createElement('canvas'); c.width = cw; c.height = ch;
  desenhar(c.getContext('2d'), cw, ch);
  const tex = new THREE.CanvasTexture(c); tex.minFilter = THREE.LinearFilter; tex.generateMipmaps = false;
  const m = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({ map: tex }));
  m.position.set(x, y, z); m.rotation.y = rotY; cena.add(m);
  return m;
}
function placaRua(texto, sub) { // placa azul paulistana, texto branco
  return (g, W, H) => {
    g.fillStyle = '#1a5fb4'; g.fillRect(0, 0, W, H);
    g.strokeStyle = '#fff'; g.lineWidth = 8; g.strokeRect(10, 10, W - 20, H - 20);
    g.fillStyle = '#fff'; g.textAlign = 'center'; g.textBaseline = 'middle';
    g.font = 'bold 66px "Segoe UI", sans-serif'; g.fillText(texto, W / 2, H * 0.43, W - 50);
    g.font = '34px "Segoe UI", sans-serif'; g.fillText(sub, W / 2, H * 0.78, W - 50);
  };
}
function placaMetro(g, W, H) { // losango/logo + linhas 1-azul, 2-verde, 3-vermelha
  g.fillStyle = '#1b2a41'; g.fillRect(0, 0, W, H);
  g.strokeStyle = '#fff'; g.lineWidth = 6; g.strokeRect(8, 8, W - 16, H - 16);
  g.fillStyle = '#0455a1'; g.beginPath(); g.moveTo(70, 30); g.lineTo(125, 100); g.lineTo(70, 170); g.lineTo(15, 100); g.closePath(); g.fill();
  g.fillStyle = '#fff'; g.font = 'bold 66px "Segoe UI", sans-serif'; g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText('M', 70, 104);
  g.textAlign = 'left'; g.font = '30px "Segoe UI", sans-serif'; g.fillText('METRÔ · Estação', 145, 62);
  g.font = 'bold 54px "Segoe UI", sans-serif'; g.fillText('Paulista', 145, 112);
  [['1', '#0455a1'], ['2', '#007e5e'], ['3', '#ee1c25']].forEach(([n, cor], i) => {
    g.fillStyle = cor; g.beginPath(); g.arc(165 + i * 70, 158, 26, 0, 7); g.fill();
    g.fillStyle = '#fff'; g.font = 'bold 34px "Segoe UI", sans-serif'; g.textAlign = 'center'; g.fillText(n, 165 + i * 70, 160);
  });
}
function posterSkyline(g, W, H) { // pôr do sol, prédios e o MASP vermelho suspenso
  const c = g.createLinearGradient(0, 0, 0, H); c.addColorStop(0, '#1e2a5a'); c.addColorStop(0.65, '#f08a4b'); c.addColorStop(1, '#f7c873');
  g.fillStyle = c; g.fillRect(0, 0, W, H);
  g.fillStyle = '#141b2b';
  [[8, 110, 34], [46, 80, 28], [78, 120, 40], [200, 90, 30], [236, 70, 34], [276, 105, 38]].forEach(([x, h, w]) => g.fillRect(x, H - 36 - h, w, h));
  g.fillStyle = '#d32f2f'; g.fillRect(112, H - 36 - 70, 104, 24);                       // MASP
  g.fillRect(118, H - 36 - 46, 10, 46); g.fillRect(200, H - 36 - 46, 10, 46);
  g.fillStyle = '#0b0f19'; g.fillRect(0, H - 36, W, 36);
  g.fillStyle = '#fff'; g.font = 'bold 26px "Segoe UI", sans-serif'; g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText('SÃO PAULO', W / 2, H - 18);
}
function mosaicoPaulista(g, W, H) { // calçadão da Paulista: ondas portuguesas e o mapa do estado de SP, em preto e branco
  g.fillStyle = '#f4f4f4'; g.fillRect(0, 0, W, H);
  g.strokeStyle = '#111'; g.lineWidth = 9;
  for (let y = 18; y < H; y += 30) { g.beginPath(); for (let x = 0; x <= W; x += 8) { const yy = y + Math.sin(x / 22 + y) * 9; x ? g.lineTo(x, yy) : g.moveTo(x, yy); } g.stroke(); }
  const P = [[.05, .30], [.12, .22], [.22, .25], [.35, .12], [.50, .10], [.62, .14], [.78, .12], [.90, .22], [.95, .35], [.85, .45], [.78, .58],
    [.66, .70], [.55, .82], [.45, .90], [.36, .84], [.30, .72], [.22, .62], [.12, .52], [.04, .42]];
  g.beginPath(); P.forEach(([u, v], i) => { const x = W * 0.16 + u * W * 0.68, y = H * 0.08 + v * H * 0.84; i ? g.lineTo(x, y) : g.moveTo(x, y); }); g.closePath();
  g.lineJoin = 'round'; g.strokeStyle = '#f4f4f4'; g.lineWidth = 26; g.stroke(); g.fillStyle = '#111'; g.fill();
  g.strokeStyle = '#111'; g.lineWidth = 12; g.strokeRect(6, 6, W - 12, H - 12);
}
function ipe(x, z, esc = 1) { // ipê-amarelo pequeno
  const g = new THREE.Group(); g.position.set(x, 0, z); g.scale.setScalar(esc);
  cilindro(0.08, 0.13, 1.6, mat(0x6b4a2f), 0, 0.8, 0, g, 6);
  const f1 = mat(0xfacc15), f2 = mat(0xfde047);
  for (const [dx, dy, dz, r, f] of [[0, 2.0, 0, 0.75, f1], [0.45, 1.65, 0.1, 0.5, f2], [-0.4, 1.7, -0.1, 0.5, f2], [0.05, 2.5, 0.05, 0.45, f1]]) {
    const m = new THREE.Mesh(new THREE.IcosahedronGeometry(r, 0), f); m.position.set(dx, dy, dz); g.add(m);
  }
  cena.add(g);
}
function maquete(cx, cz) {
  const mq = new THREE.Group(); mq.position.set(cx, 1.15, cz); cena.add(mq);
  const M = (w, h, d, cor, u, y, v, rot = 0, pai = mq) => { const m = caixa(w, h, d, mat(cor), u, y, v, pai); m.rotation.y = rot; return m; };
  // mesa
  caixa(8.6, 0.14, 4.8, mat(0x7a5230), cx, 1.0, cz);
  for (const [dx, dz] of [[-4.0, -2.2], [4.0, -2.2], [-4.0, 2.2], [4.0, 2.2]]) caixa(0.22, 1.0, 0.22, mat(0x2b313a), cx + dx, 0.5, cz + dz);
  M(8.2, 0.08, 4.4, 0x9ca3af, 0, -0.04, 0);                                   // chão da cidade (as frestas viram ruas cinza)
  M(8.2, 0.04, 0.5, 0x3b82c4, 0, 0.02, -1.95);                                // rio Tietê
  M(0.5, 0.04, 4.4, 0x3b82c4, -3.2, 0.02, 0);                                 // rio Pinheiros
  M(5.6, 0.035, 0.24, 0xe5e7eb, 0.25, 0.02, -0.9, 0.18);                      // Av. Paulista
  // Parque Ibirapuera + lago + Obelisco
  M(2.0, 0.04, 1.3, 0x2f9e5b, 2.8, 0.02, 1.2); M(0.7, 0.045, 0.45, 0x3b82c4, 3.15, 0.025, 1.35);
  M(0.07, 0.5, 0.07, 0xe5e7eb, 1.95, 0.25, 0.8);
  for (const [u, v] of [[2.2, 1.6], [2.6, 0.85], [3.5, 0.8], [2.0, 1.2]]) M(0.2, 0.24, 0.2, 0x1f7a43, u, 0.14, v);
  // MASP: caixa vermelha suspensa sobre dois pórticos, com o vão livre embaixo
  const masp = new THREE.Group(); masp.position.set(0.25, 0, -0.88); masp.rotation.y = 0.18; mq.add(masp);
  M(1.1, 0.2, 0.42, 0xd32f2f, 0, 0.46, 0, 0, masp);
  M(0.1, 0.36, 0.42, 0xd32f2f, -0.52, 0.18, 0, 0, masp); M(0.1, 0.36, 0.42, 0xd32f2f, 0.52, 0.18, 0, 0, masp);
  M(0.9, 0.1, 0.36, 0xbfd8ee, 0, 0.06, 0, 0, masp);
  // Edifício Copan: curva em "S" feita de 4 segmentos
  [[-1.65, -0.108, 0.5], [-1.233, -0.25, 0.15], [-0.788, -0.25, -0.15], [-0.368, -0.108, -0.5]].forEach(([u, v, r]) => M(0.47, 0.62, 0.17, 0xe7dfc9, u, 0.31, v, r));
  // Edifício Itália
  M(0.34, 0.95, 0.3, 0x7c8794, -0.55, 0.475, 0.6); M(0.42, 0.05, 0.36, 0x4b5563, -0.55, 0.97, 0.6); M(0.02, 0.14, 0.02, 0xdddddd, -0.55, 1.07, 0.6);
  // Banespa / Altino Arantes: torre escalonada com pináculo
  M(0.32, 0.5, 0.32, 0xc7b99a, -2.05, 0.25, 0.55); M(0.24, 0.4, 0.24, 0xc7b99a, -2.05, 0.7, 0.55);
  cilindro(0, 0.07, 0.3, mat(0xb0a07c), -2.05, 1.05, 0.55, mq, 6);
  // Catedral da Sé: nave, duas torres e cúpula verde-acinzentada
  const verde = mat(0x3f8a64);
  M(0.8, 0.25, 0.5, 0x8d9aa5, -1.1, 0.125, 1.65);
  for (const dx of [-0.25, 0.25]) { M(0.15, 0.55, 0.15, 0x8d9aa5, -1.1 + dx, 0.27, 1.85); cilindro(0, 0.1, 0.22, verde, -1.1 + dx, 0.66, 1.85, mq, 6); }
  cilindro(0.1, 0.24, 0.2, verde, -1.1, 0.35, 1.6, mq, 8);
  // Ponte Estaiada: mastro em X sobre o Pinheiros + cabos (1 malha de linhas)
  M(1.5, 0.06, 0.22, 0xd1d5db, -3.2, 0.1, 0.9);
  for (const s of [1, -1]) { const m = M(0.05, 1.05, 0.05, 0xf3f4f6, -3.2, 0.62, 0.9); m.rotation.x = s * 0.3; }
  const pts = [];
  for (const sv of [1, -1]) for (let k = 0; k < 7; k++) {
    const u = -3.95 + k * 0.25; if (Math.abs(u + 3.2) < 0.1) continue;
    pts.push(-3.2, 1.1, 0.9 + sv * 0.3, u, 0.13, 0.9 + sv * 0.09);
  }
  const gc = new THREE.BufferGeometry(); gc.setAttribute('position', new THREE.Float32BufferAttribute(pts, 3));
  mq.add(new THREE.LineSegments(gc, new THREE.LineBasicMaterial({ color: 0xffffff })));
  // prédios genéricos: uma única InstancedMesh, altura maior perto da Paulista
  let semente = 7; const rnd = () => (semente = (semente * 16807) % 2147483647) / 2147483647;
  const cores = [0x9aa4b2, 0xb8b2a7, 0x7d8a99, 0xc9c2b4, 0x6f7f93, 0xd4cfc4, 0x8f9aa8].map((c) => new THREE.Color(c));
  const livres = [];
  for (let u = -2.45; u < 4.0; u += 0.55) for (let v = -1.5; v < 2.05; v += 0.5) {
    const pu = u + (rnd() - 0.5) * 0.08, pv = v + (rnd() - 0.5) * 0.08;
    const dPaulista = Math.abs(-(pu - 0.25) * Math.sin(0.18) * -1 + (pv + 0.9) * Math.cos(0.18)) ;   // distância aproximada à avenida
    const noParque = pu > 1.7 && pv > 0.5, perto = (x, z, r) => Math.hypot(pu - x, pv - z) < r;
    if (dPaulista < 0.3 || noParque || perto(0.25, -0.88, 0.2) || perto(-1.0, -0.19, 1.0) || perto(-0.55, 0.6, 0.35) || perto(-2.05, 0.55, 0.35) || perto(-1.1, 1.7, 0.7)) continue;
    livres.push([pu, pv, dPaulista]);
  }
  const predios = new THREE.InstancedMesh(geoCaixa, mat(0xffffff), livres.length);
  const dummy = new THREE.Object3D();
  livres.forEach(([u, v, d], i) => {
    const h = 0.12 + rnd() * 0.3 + Math.max(0, 0.9 - d) * 0.35;
    dummy.position.set(u, h / 2, v); dummy.scale.set(0.34 + rnd() * 0.1, h, 0.3 + rnd() * 0.1); dummy.updateMatrix();
    predios.setMatrixAt(i, dummy.matrix); predios.setColorAt(i, cores[Math.floor(rnd() * cores.length)]);
  });
  predios.frustumCulled = false; mq.add(predios);
  criarPlaquinha('🏙️ Maquete — São Paulo', 0x38bdf8, cx, 3.0, cz - 2.6, 512).scale.multiplyScalar(0.7);
}
function construirDecoracaoSP() {
  const zParede = LIM.z0 + 0.19;
  // placas azuis, estação de metrô e pôster, nos vãos entre as janelas do fundo
  placaCanvas(2.2, 0.55, 440, 110, -28, 1.0, zParede, placaRua('R. Augusta', 'CEP 01305'));
  placaCanvas(2.2, 0.55, 440, 110, -22, 1.0, zParede, placaRua('Av. Paulista', 'CEP 01310'));
  placaCanvas(2.4, 1.15, 420, 200, -16, 0.95, zParede, placaMetro);
  placaCanvas(2.2, 0.55, 440, 110, -10, 1.0, zParede, placaRua('R. da Consolação', 'CEP 01302'));
  caixa(1.7, 1.25, 0.03, mat(0x1b2430), -4, 0.95, zParede - 0.01, null);
  placaCanvas(1.55, 1.1, 330, 235, -4, 0.95, zParede + 0.01, posterSkyline);
  // calçadão paulista como tapete + orelhão + ipês
  placaCanvas(7, 4.6, 512, 336, -3.5, 0.03, 22.6, mosaicoPaulista).rotation.x = -Math.PI / 2;
  const o = new THREE.Group(); o.position.set(-8.8, 0, 21); cena.add(o);
  caixa(0.14, 1.3, 0.14, mat(0x6b7280), 0, 0.65, -0.05, o);
  const dome = new THREE.SphereGeometry(0.5, 10, 6, 0, Math.PI * 2, 0, Math.PI / 2);
  const casca = new THREE.Mesh(dome, mat(0xf97316)); casca.position.y = 1.45; casca.rotation.x = -Math.PI / 2; o.add(casca);
  const dentro = new THREE.Mesh(dome, new THREE.MeshLambertMaterial({ color: 0x2563eb, side: THREE.BackSide })); dentro.scale.setScalar(0.96);
  dentro.position.y = 1.45; dentro.rotation.x = -Math.PI / 2; o.add(dentro);
  caixa(0.3, 0.4, 0.1, mat(0x9ca3af), 0, 1.45, -0.28, o); caixa(0.06, 0.3, 0.06, mat(0x111111), 0.2, 1.4, -0.2, o);
  ipe(13.2, 20.8, 1.1); ipe(-11.5, 23.5, 1); ipe(-31.5, 21.5, 1.15);
  planta(15.5, 25, 1.1); planta(-32.5, 25, 1.1); planta(-14.5, 20.3, 1);
  maquete(6.5, 22.3);
  // refeitório: vitrine de coxinha e pão de queijo + lousa do cafezinho
  const vit = mat(0xf2e3c2);
  caixa(1.0, 0.1, 0.6, mat(0x8b5a2b), -16.4, 1.13, 18.1);
  for (const dx of [-0.3, 0, 0.3]) cilindro(0.0, 0.11, 0.22, mat(0xe0a030), -16.4 + dx, 1.29, 18.0, null, 6);                // coxinhas
  for (const dx of [-0.3, 0, 0.3]) caixa(0.1, 0.1, 0.1, vit, -16.4 + dx, 1.23, 18.25);                                      // pães de queijo
  const v = caixa(1.0, 0.36, 0.6, matVidro, -16.4, 1.36, 18.1); v.renderOrder = 2;
  caixa(0.06, 0.7, 0.06, mat(0x2b313a), -18.3, 1.4, 18.72); caixa(0.06, 0.7, 0.06, mat(0x2b313a), -15.6, 1.4, 18.72);
  placaCanvas(2.9, 0.6, 580, 120, -16.95, 1.95, 18.68, (g, W, H) => {
    g.fillStyle = '#7f1d1d'; g.fillRect(0, 0, W, H); g.strokeStyle = '#facc15'; g.lineWidth = 6; g.strokeRect(8, 8, W - 16, H - 16);
    g.fillStyle = '#fde68a'; g.font = 'bold 50px "Segoe UI", sans-serif'; g.textAlign = 'center'; g.textBaseline = 'middle';
    g.fillText('Coxinha & Pão de Queijo', W / 2, H / 2 + 2, W - 40);
  });
  placaCanvas(0.9, 0.5, 240, 130, -21.5, 1.38, 17.97, (g, W, H) => {
    g.fillStyle = '#243b2f'; g.fillRect(0, 0, W, H); g.strokeStyle = '#d6b88a'; g.lineWidth = 8; g.strokeRect(5, 5, W - 10, H - 10);
    g.fillStyle = '#fff'; g.font = 'bold 40px "Segoe UI", sans-serif'; g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText('☕ Cafezinho', W / 2, H / 2 + 2, W - 24);
  });
}
// Tema "neutro": no lugar das placas, da maquete e do orelhão, só um quadro com o nome do escritório, plantas
// e um jardim de inverno na frente. Áreas de pausa, refeitório, ping-pong e TV continuam iguais.
function construirDecoracaoNeutra() {
  const zParede = LIM.z0 + 0.19;
  caixa(4.6, 1.25, 0.03, mat(0x1b2430), -16, 0.95, zParede - 0.01, null);
  placaCanvas(4.4, 1.05, 640, 152, -16, 0.95, zParede + 0.01, (g, W, H) => {
    const gr = g.createLinearGradient(0, 0, W, 0); gr.addColorStop(0, '#1e3a5f'); gr.addColorStop(1, '#334e7a');
    g.fillStyle = gr; g.fillRect(0, 0, W, H);
    g.fillStyle = '#fff'; g.textAlign = 'center'; g.textBaseline = 'middle';
    g.font = 'bold 54px "Segoe UI", sans-serif'; g.fillText(CONFIG.titulo, W / 2, H * 0.42, W - 40);
    g.font = '28px "Segoe UI", sans-serif'; g.fillStyle = '#b8c4d2'; g.fillText('agentes do Claude Code trabalhando', W / 2, H * 0.78, W - 40);
  });
  const tapete = new THREE.Mesh(new THREE.PlaneGeometry(12, 4.6), mat(0x4b5a49));
  tapete.rotation.x = -Math.PI / 2; tapete.position.set(2, 0.02, 22.6); cena.add(tapete);
  for (const [x, z, e] of [[-2.5, 21.5, 1.2], [1, 23.5, 1], [4.5, 21.5, 1.3], [7, 23.4, 1.1], [13.2, 20.8, 1.1], [-11.5, 23.5, 1],
    [-31.5, 21.5, 1.15], [15.5, 25, 1.1], [-32.5, 25, 1.1], [-14.5, 20.3, 1]]) planta(x, z, e);
  const banco = mat(0x7a5230);
  for (const x of [-1, 5]) { caixa(2.4, 0.12, 0.7, banco, x, 0.5, 22.5); caixa(0.12, 0.5, 0.6, mat(0x2b313a), x - 1, 0.25, 22.5); caixa(0.12, 0.5, 0.6, mat(0x2b313a), x + 1, 0.25, 22.5); }
}
if (TEMA_SP) construirDecoracaoSP(); else construirDecoracaoNeutra();

// ---------------------------------------------------------------- Quadro Kanban na parede (só com "github.kanban")
// Quadro branco em cima da mureta do fundo, perto da sala de reunião: colunas, contagem e post-its (#n, cor do agente) dos
// cartões, redesenhado quando o kanban.js lê o /kanban (evento "kanban"). Clique abre o painel Kanban.
const QUADRO_KB = { x: 8, w: 5.6, h: 2.8, CW: 1024, CH: 512, MAX_COL: 5 };
const CORES_COL_KB = ['#64748b', '#2563eb', '#9333ea', '#0891b2', '#16a34a'];
const canvasKB = document.createElement('canvas'); canvasKB.width = QUADRO_KB.CW; canvasKB.height = QUADRO_KB.CH;
const texKB = new THREE.CanvasTexture(canvasKB); texKB.minFilter = THREE.LinearFilter; texKB.generateMipmaps = false;
function desenharQuadroKanban(d) {
  const g = canvasKB.getContext('2d'), W = QUADRO_KB.CW, H = QUADRO_KB.CH, K = window.__kanban;
  const PRIO = { P0: 0, P1: 1, P2: 2, high: 0, medium: 1, low: 2 };
  const cartoes = (d && d.cartoes) || [];
  g.fillStyle = '#f8fafc'; g.fillRect(0, 0, W, H);
  g.textBaseline = 'middle'; g.textAlign = 'left'; g.fillStyle = '#1e293b'; g.font = 'bold 40px "Segoe UI", "Segoe UI Emoji", sans-serif';
  g.fillText('📋 Kanban', 28, 42);
  g.textAlign = 'right'; g.fillStyle = '#64748b'; g.font = '24px "Segoe UI", "Segoe UI Emoji", sans-serif';
  g.fillText(!cartoes.length || !K ? 'sem dados do quadro' : (d.erro ? '⚠️ desatualizado · ' : 'atualizado ') + (d.atualizado || ''), W - 28, 44);
  if (!cartoes.length || !K) { texKB.needsUpdate = true; return; }
  const cols = K.colunas(cartoes).slice(0, QUADRO_KB.MAX_COL);
  const cw = (W - 56) / cols.length, y0 = 84;
  cols.forEach((status, i) => {
    const x0 = 28 + i * cw, lista = cartoes.filter((c) => c.status === status), concl = K.ehConcluida(status);
    const cor = concl ? '#16a34a' : CORES_COL_KB[Math.min(i, CORES_COL_KB.length - 2)];
    if (i) { g.strokeStyle = '#cbd5e1'; g.lineWidth = 3; g.beginPath(); g.moveTo(x0, y0); g.lineTo(x0, H - 20); g.stroke(); }
    g.textAlign = 'center'; g.fillStyle = '#334155'; g.font = 'bold 28px "Segoe UI", sans-serif'; g.fillText(status, x0 + cw / 2, y0 + 22, cw - 12);
    g.fillStyle = cor; g.font = 'bold 84px "Segoe UI", sans-serif'; g.fillText(String(lista.length), x0 + cw / 2, y0 + 104);
    if (concl) return;   // concluídos só contam
    // post-its: até 6 cartões, mais urgentes primeiro; o 6º vira "+N" quando sobra
    const ord = lista.slice().sort((a, b) => (PRIO[a.prioridade] ?? 3) - (PRIO[b.prioridade] ?? 3) || (a.numero || 0) - (b.numero || 0));
    const pw = (cw - 42) / 2, ph = 66;
    ord.slice(0, 6).forEach((c, k) => {
      const px = x0 + 14 + (k % 2) * (pw + 14), py = y0 + 168 + Math.floor(k / 2) * (ph + 12);
      const mais = k === 5 && ord.length > 6, urgente = PRIO[c.prioridade] === 0;
      g.fillStyle = mais ? '#e2e8f0' : K.infoTime(c.time).cor; g.fillRect(px, py, pw, ph);
      g.fillStyle = mais ? '#334155' : '#fff'; g.font = 'bold 30px "Segoe UI", sans-serif';
      g.fillText(mais ? '+' + (ord.length - 5) : (c.numero ? '#' + c.numero : '·') + (urgente ? ' !' : ''), px + pw / 2, py + ph / 2 + 1, pw - 8);
    });
  });
  texKB.needsUpdate = true;
}
if (CONFIG.github.kanban) (function construirQuadroKanban() {
  const { x, w, h } = QUADRO_KB, y = 1.6 + 0.12 + h / 2, z = LIM.z0, aluminio = mat(0xb8c0cc);
  caixa(w + 0.16, h + 0.16, 0.1, aluminio, x, y, z);                     // moldura apoiada na mureta
  caixa(w * 0.5, 0.06, 0.18, aluminio, x, y - h / 2 - 0.06, z + 0.1);     // aparador das canetas
  const tela = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({ map: texKB }));
  tela.position.set(x, y, z + 0.06); tela.userData.kanban = true; cena.add(tela);
  desenharQuadroKanban(window.__kanban && window.__kanban.dados());
})();

// ---------------------------------------------------------------- Sala da diretoria (opcional: "sala": "diretoria")
// Sala fechada pequena: paredes de madeira (parte de baixo) e vidro (em cima, para ver lá dentro), porta na parede oeste,
// mesa grande de madeira (criada junto das outras mesas), poltrona, estante, quadros e plaquinha.
function construirDiretoria() {
  const D = DIRETORIA, h = 2.8, hBaixo = 1.1, esp = 0.18, zc = (D.z0 + D.z1) / 2, larg = D.x1 - D.x0, prof = D.z1 - D.z0;
  const madeira = mat(0x6b4a32), escura = mat(0x3b2314), dourado = mat(0xd4a017), couro = mat(0x5b2a1c);
  // piso de madeira clara e tapete vinho
  const piso = new THREE.Mesh(new THREE.PlaneGeometry(larg, prof), mat(0xa9824f));
  piso.rotation.x = -Math.PI / 2; piso.position.set(D.cx, 0.015, zc); cena.add(piso);
  const tap = new THREE.Mesh(new THREE.PlaneGeometry(6.4, 5.2), mat(0x6e1f2b));
  tap.rotation.x = -Math.PI / 2; tap.position.set(D.cx, 0.025, 12.2); cena.add(tap);
  const parede = (w, d, x, z, vidro) => {
    caixa(w, hBaixo, d, madeira, x, hBaixo / 2, z, null);
    if (vidro) { const v = caixa(w, h - hBaixo, d * 0.4, matVidro, x, hBaixo + (h - hBaixo) / 2, z, null); v.renderOrder = 2; }
    else caixa(w, h - hBaixo, d, madeira, x, hBaixo + (h - hBaixo) / 2, z, null);
    caixa(w + 0.04, 0.1, d + 0.04, escura, x, h + 0.05, z, null);   // rodateto
  };
  parede(larg, esp, D.cx, D.z0, false);                 // fundo (sólida, com a estante)
  parede(esp, prof, D.x1, zc, false);                   // lado leste (sólida, com o quadro)
  parede(larg, esp, D.cx, D.z1, true);                  // frente, voltada para a câmera (vidro)
  // lado oeste com porta (vão de 2,4 em torno de portaZ), em vidro
  const vao = 1.2, zPortaA = D.portaZ - vao, zPortaB = D.portaZ + vao;
  parede(esp, zPortaA - D.z0, D.x0, (D.z0 + zPortaA) / 2, true);
  parede(esp, D.z1 - zPortaB, D.x0, (zPortaB + D.z1) / 2, true);
  caixa(esp + 0.04, 0.35, zPortaB - zPortaA, escura, D.x0, h - 0.17, D.portaZ, null);   // verga da porta
  // estante cheia de livros no fundo
  const ez = D.z0 + 0.4, ex = D.cx + 2.9;
  caixa(2.6, 2.4, 0.5, escura, ex, 1.2, ez, null);
  const cores = [0x7f1d1d, 0x1e3a8a, 0x14532d, 0xa16207, 0x581c87, 0x0f766e];
  for (let n = 0; n < 4; n++) {
    caixa(2.4, 0.05, 0.46, madeira, ex, 0.45 + n * 0.55, ez + 0.02, null);
    for (let i = 0; i < 9; i++) caixa(0.2, 0.38, 0.3, mat(cores[(i + n * 2) % cores.length]), ex - 1.0 + i * 0.25, 0.68 + n * 0.55, ez + 0.1, null);
  }
  // quadros com moldura dourada: horizonte na parede do fundo e mapa na parede leste
  const quadro = (cx, cy, z, rotY, w, hh, desenhar) => {
    const m = caixa(w + 0.18, hh + 0.18, 0.05, dourado, cx, cy, z, null); m.rotation.y = rotY;
    const dz = Math.cos(rotY) * 0.04, dx = -Math.sin(rotY) * 0.04;
    placaCanvas(w, hh, 320, Math.round(320 * hh / w), cx + dx, cy, z + dz, desenhar, rotY);
  };
  quadro(D.cx - 2.9, 1.95, D.z0 + 0.12, 0, 2.4, 1.3, (g, W, H) => {
    g.fillStyle = '#1b2a41'; g.fillRect(0, 0, W, H);
    g.fillStyle = '#f5c518'; g.beginPath(); g.arc(W * 0.72, H * 0.3, 26, 0, 7); g.fill();
    g.fillStyle = '#0b1320';
    [[18, 110, 34], [58, 70, 40], [104, 95, 30], [140, 55, 44], [190, 88, 36], [236, 62, 40], [280, 100, 30]].forEach(([x, y, w]) => g.fillRect(x, y * H / 160, w, H));
  });
  quadro(D.x1 - 0.12, 1.95, D.z1 - 4.2, -Math.PI / 2, 2.2, 1.3, (g, W, H) => {
    g.fillStyle = '#e9dfc2'; g.fillRect(0, 0, W, H);
    g.strokeStyle = '#7a6a4a'; g.lineWidth = 3;
    for (let i = 20; i < W; i += 40) { g.beginPath(); g.moveTo(i, 0); g.lineTo(i, H); g.stroke(); }
    for (let i = 20; i < H; i += 40) { g.beginPath(); g.moveTo(0, i); g.lineTo(W, i); g.stroke(); }
    g.fillStyle = '#8bb7e0'; g.fillRect(40, H * 0.58, W - 80, 22); g.fillStyle = '#d32f2f'; g.beginPath(); g.arc(W * 0.55, H * 0.4, 12, 0, 7); g.fill();
  });
  // poltrona de visita (couro) virada para a mesa, mesinha de canto, plantas e globo
  const pol = new THREE.Group(); pol.position.set(26.0, 0, 14.6); pol.rotation.y = Math.atan2(D.cx - 26.0, 10.2 - 14.6) + Math.PI; cena.add(pol);
  caixa(1.1, 0.45, 1.0, couro, 0, 0.3, 0, pol); caixa(1.1, 0.8, 0.22, couro, 0, 0.75, 0.42, pol);
  caixa(0.22, 0.6, 1.0, escura, -0.6, 0.55, 0, pol); caixa(0.22, 0.6, 1.0, escura, 0.6, 0.55, 0, pol);
  cilindro(0.35, 0.35, 0.55, madeira, 27.2, 0.28, 16.2, null, 10); cilindro(0.1, 0.1, 0.16, mat(0xf2f4f7), 27.2, 0.63, 16.2, null, 8);
  planta(19.1, 16.2, 1.15); planta(27.2, 8.4, 0.9); planta(29.5, 25, 1.1); planta(29.5, -4.5, 1.1);
  cilindro(0.04, 0.04, 0.95, mat(0x4a4f57), 19.2, 0.48, 8.4, null, 6);
  const globo = new THREE.Mesh(new THREE.SphereGeometry(0.34, 12, 9), mat(0x2f6fb5)); globo.position.set(19.2, 1.2, 8.4); cena.add(globo);
  // plaquinha "Diretoria" sobre a porta
  criarPlaquinha('🏛️ Diretoria', 0xf5c518, D.x0, 3.6, D.portaZ);
}
if (TEM_DIRETORIA) construirDiretoria();

// ---------------------------------------------------------------- Mesas
const COR_TECLAS = 0x4b5563, corTmp = new THREE.Color();
const mesas = [];     // {x, accent, monitores:[mats], kind}
// tipo de mesa do config ("mesa"): lider (mesa grande, 2 monitores), dev (2 monitores), design (monitor + mesa
// digitalizadora), pesquisa (monitor + mapa); qualquer outro / agente desconhecido: mesa simples
function tipoMesa(nome) {
  return MESA_DE[nome.toLowerCase()] || 'padrao';
}
function texturaMapa() {
  const c = document.createElement('canvas'); c.width = c.height = 64;
  const g = c.getContext('2d'); g.fillStyle = '#e9dfc2'; g.fillRect(0, 0, 64, 64);
  g.fillStyle = '#9ccc8a'; g.fillRect(6, 8, 26, 20); g.fillStyle = '#8bb7e0'; g.fillRect(36, 30, 24, 28);
  g.strokeStyle = '#7a6a4a'; g.lineWidth = 2; for (let i = 8; i < 64; i += 14) { g.beginPath(); g.moveTo(i, 0); g.lineTo(i, 64); g.moveTo(0, i); g.lineTo(64, i); g.stroke(); }
  return new THREE.CanvasTexture(c);
}
function criarMesa(indice, nome, cor, dir = false) {   // dir: mesa dentro da diretoria (agente com "sala": "diretoria")
  const kind = dir ? 'diretoria' : tipoMesa(nome), boss = kind === 'lider';
  const x = dir ? DIRETORIA.cx : X_MESAS[indice], z0 = dir ? DIRETORIA.mesaZ : 0;
  const g = new THREE.Group(); g.position.set(x, 0, z0); cena.add(g);
  const largura = dir ? 5.2 : boss ? 4.2 : 3.2, prof = dir ? 2.1 : boss ? 1.9 : 1.6;
  const tampo = mat(dir ? 0x5a3a22 : boss ? 0x7a5230 : 0xb08a5e), pe = mat(dir ? 0x2a1a10 : 0x2b313a);
  caixa(largura, 0.12, prof, tampo, 0, 1.0, 0, g);
  caixa(0.12, 1.0, prof - 0.2, pe, -largura / 2 + 0.15, 0.5, 0, g);
  caixa(0.12, 1.0, prof - 0.2, pe, largura / 2 - 0.15, 0.5, 0, g);
  caixa(largura - 0.3, 0.5, 0.06, pe, 0, 0.8, -prof / 2 + 0.2, g); // painel frontal
  const monitores = [];
  const novoMonitor = (dx, dz, w, h, rotY = 0) => {
    const m = new THREE.MeshBasicMaterial({ color: 0x111827 });
    const tela = caixa(w, h, 0.06, m, dx, 1.06 + h / 2 + 0.25, dz, g); tela.rotation.y = rotY;
    caixa(w + 0.06, h + 0.06, 0.04, mat(0x0b0f14), dx, 1.06 + h / 2 + 0.25, dz - 0.04, g).rotation.y = rotY;
    caixa(0.12, 0.28, 0.12, pe, dx, 1.2, dz - 0.02, g);
    monitores.push(m);
  };
  if (kind === 'dev') { novoMonitor(-0.85, -0.35, 1.25, 0.75); novoMonitor(0.85, -0.35, 1.25, 0.75); }
  else if (kind === 'design') {
    novoMonitor(-0.5, -0.4, 1.4, 0.85);
    const m = new THREE.MeshBasicMaterial({ color: 0x111827 }); monitores.push(m);
    const tab = caixa(0.9, 0.04, 0.6, m, 0.85, 1.12, 0.2, g); tab.rotation.x = -0.18;
    caixa(0.05, 0.02, 0.5, mat(0xdddddd), 0.25, 1.1, 0.4, g); // caneta
  } else if (kind === 'pesquisa') {
    novoMonitor(-0.8, -0.4, 1.3, 0.8);
    const mapa = new THREE.Mesh(new THREE.PlaneGeometry(1.1, 0.8), new THREE.MeshLambertMaterial({ map: texturaMapa() }));
    mapa.rotation.x = -Math.PI / 2; mapa.position.set(0.8, 1.07, 0.15); g.add(mapa);
  } else if (dir) {
    novoMonitor(-1.0, -0.5, 1.5, 0.9); novoMonitor(0.7, -0.5, 1.5, 0.9);
    caixa(0.7, 0.1, 0.3, mat(0xffd34d), -1.9, 1.11, 0.55, g); // plaquinha dourada
    caixa(0.5, 0.04, 0.38, mat(0xf2f4f7), 1.7, 1.08, 0.2, g); // papéis
    cilindro(0.1, 0.08, 0.2, mat(0x7f1d1d), 1.95, 1.18, -0.5, g, 8); // porta-canetas
  } else if (boss) {
    novoMonitor(-0.6, -0.5, 1.5, 0.9); novoMonitor(1.0, -0.5, 1.0, 0.7);
    caixa(0.5, 0.08, 0.3, mat(0xffd34d), -1.7, 1.1, 0.4, g); // plaquinha dourada
  } else novoMonitor(0, -0.4, 1.3, 0.8);
  // teclado (corpo escuro + faixa de teclas que pisca quando o agente trabalha) e mouse com mousepad
  const teclas = new THREE.MeshBasicMaterial({ color: COR_TECLAS });
  const [kx, mx] = { dev: [0, 0.62], design: [-0.5, 0.1], pesquisa: [-0.8, -0.2], lider: [0.2, 0.85], diretoria: [-0.1, 0.8] }[kind] || [0, 0.6];
  caixa(0.7, 0.03, 0.24, mat(0x1b2027), kx, 1.085, 0.32, g);
  caixa(0.64, 0.012, 0.17, teclas, kx, 1.107, 0.32, g);
  caixa(0.28, 0.01, 0.24, mat(0x111827), mx, 1.067, 0.32, g);
  caixa(0.09, 0.035, 0.14, mat(0x20262e), mx, 1.09, 0.32, g);
  // cadeira (assento na altura 0.5, atrás da mesa no lado +z)
  const cad = new THREE.Group(); cad.position.set(0, 0, 1.5); g.add(cad);
  const mc = mat(dir ? 0x3b1e12 : boss ? 0x7f1d1d : 0x2d3643);
  caixa(0.85, 0.1, 0.85, mc, 0, 0.5, 0, cad);
  caixa(0.85, dir ? 1.25 : 0.85, 0.1, mc, 0, dir ? 1.1 : 0.95, 0.42, cad);   // poltrona da diretoria: encosto alto
  cilindro(0.06, 0.06, 0.45, pe, 0, 0.25, 0, cad, 6);
  caixa(0.7, 0.05, 0.7, pe, 0, 0.03, 0, cad);
  // faixa colorida do agente na frente da mesa
  caixa(largura - 0.3, 0.1, 0.04, mat(cor, 'basic'), 0, 0.98 - 0.02, prof / 2 + 0.02, g);
  const mesa = { indice, x, cor, kind, monitores, teclas, assento: new THREE.Vector3(x, 0, z0 + 1.6), visita: new THREE.Vector3(x + 1.2, 0, 3.0) };
  // Rotas: saida = do assento até o corredor; entrada = o inverso; acesso = do corredor até o ponto de visita.
  // Mesa comum: reta pelo corredor. Diretoria: pela porta da parede oeste.
  mesa.saida = [new THREE.Vector3(x, 0, Z_CORREDOR)]; mesa.entrada = mesa.saida;
  mesa.acesso = [new THREE.Vector3(mesa.visita.x, 0, Z_CORREDOR), mesa.visita];
  mesa.sub = new THREE.Vector3(x - 1.6, 0, 2.6); mesa.foco = new THREE.Vector3(x, 1, 1.5);
  if (dir) {
    const D = DIRETORIA, xc = D.xCorredor, zp = D.portaZ;
    mesa.visita = new THREE.Vector3(21.0, 0, 12.0);
    mesa.saida = [new THREE.Vector3(21.2, 0, zp), new THREE.Vector3(D.x0 + 1.2, 0, zp), new THREE.Vector3(xc, 0, zp), new THREE.Vector3(xc, 0, Z_CORREDOR)];
    mesa.entrada = [...mesa.saida].reverse();
    mesa.acesso = [new THREE.Vector3(xc, 0, Z_CORREDOR), new THREE.Vector3(xc, 0, zp), new THREE.Vector3(D.x0 + 1.2, 0, zp), mesa.visita];
    mesa.sub = new THREE.Vector3(26.8, 0, 11.8); mesa.foco = new THREE.Vector3(x, 1, z0 + 1.2);
  }
  mesas.push(mesa);
  return mesa;
}

// ---------------------------------------------------------------- Figuras (bonecos)
const geoCorpo = new THREE.CylinderGeometry(0.3, 0.34, 0.9, 8);
const geoCabeca = new THREE.SphereGeometry(0.28, 10, 8);
function criarFigura(cor, escala = 1) {
  const raiz = new THREE.Group();
  const dentro = new THREE.Group(); raiz.add(dentro);
  const corpo = new THREE.Mesh(geoCorpo, mat(cor)); corpo.position.y = 1.07; dentro.add(corpo);
  const cabeca = new THREE.Mesh(geoCabeca, mat(0xf1c7a0)); cabeca.position.y = 1.78; dentro.add(cabeca);
  caixa(0.5, 0.14, 0.5, mat(0x2b2118), 0, 1.98, -0.02, dentro); // cabelo/boné
  const olhos = mat(0x111111);
  caixa(0.05, 0.06, 0.05, olhos, -0.1, 1.82, 0.26, dentro); caixa(0.05, 0.06, 0.05, olhos, 0.1, 1.82, 0.26, dentro);
  const braco = (lado) => {
    const p = new THREE.Group(); p.position.set(lado * 0.4, 1.45, 0); dentro.add(p);
    caixa(0.14, 0.6, 0.14, mat(cor), 0, -0.28, 0, p);
    return p;
  };
  const bracoE = braco(-1), bracoD = braco(1);
  const perna = (lado) => {
    const p = new THREE.Group(); p.position.set(lado * 0.16, 0.62, 0); dentro.add(p);
    caixa(0.2, 0.62, 0.22, mat(0x2c3a52), 0, -0.31, 0, p);
    return p;
  };
  const pernaE = perna(-1), pernaD = perna(1);
  raiz.scale.setScalar(escala);
  return { raiz, dentro, cabeca, bracoE, bracoD, pernaE, pernaD };
}
function posturaSentado(f, sentado) {
  f.dentro.position.y = sentado ? -0.1 : 0;
  f.pernaE.rotation.x = f.pernaD.rotation.x = sentado ? -Math.PI / 2 : 0;
}

// ---------------------------------------------------------------- Agentes
const agentes = new Map();   // nome -> agente
const ordemAgentes = [];
let extras = 0, mesasComuns = 0, mesaDiretoria = null;

function normalizarNome(n) {
  const s = String(n || '').trim();
  // endereço de outra sessão do Claude (pipe/socket/ponte) vira uma mesa só, não uma por endereço
  if (/^(uds:|bridge:)|\\pipe\\/i.test(s)) return 'Outra_Sessao';
  const conhecido = ALIAS[chaveNome(s)];   // nome do config ou um dos "outros_nomes" (main/lead = líder)
  if (conhecido) return conhecido;
  // id interno de subagente (ex.: a9e249cd8979806e3) não vira mesa própria
  if (s === 'Subagente' || /^a[0-9a-f]{12,}$/i.test(s)) return 'Assistente';
  // subagente numerado (Dev_235, Dev_66b: um por tarefa) cai na mesa do agente (mesma regra do registrar_evento.py)
  const semNumero = s.replace(/[_-]\d+[a-z]?$/i, '');
  return ALIAS[chaveNome(semNumero)] || semNumero || s;
}
function corDoAgente(nome) {
  const k = nome.toLowerCase();
  return CORES_FIXAS[k] ?? CORES_EXTRA[extras++ % CORES_EXTRA.length];
}
function garantirAgente(nome) {
  nome = normalizarNome(nome) || 'Desconhecido';
  if (agentes.has(nome)) return agentes.get(nome);
  const naDiretoria = TEM_DIRETORIA && SALA_DE[nome.toLowerCase()] === 'diretoria' && !mesaDiretoria;   // uma mesa só na diretoria
  if (!naDiretoria && mesasComuns >= MAX_MESAS) return null; // sem mesa disponível
  const cor = corDoAgente(nome);
  const mesa = criarMesa(naDiretoria ? 7 : mesasComuns++, nome, cor, naDiretoria);
  if (naDiretoria) mesaDiretoria = mesa;
  const fig = criarFigura(cor);
  cena.add(fig.raiz);
  const pf = rotulos(nome, perfil(nome));
  const nomeSp = criarSprite(384, 136, 5.0, 1.77); desenharNome(nomeSp, pf.titulo, cor, pf.funcao);
  const balaoSp = criarSprite(640, 220, 7.0, 2.4); balaoSp.sprite.visible = false;
  fig.raiz.add(nomeSp.sprite); nomeSp.sprite.position.y = 3.55;
  fig.raiz.add(balaoSp.sprite); balaoSp.sprite.position.y = 5.6;
  const a = {
    nome, cor, mesa, fig, nomeSp, balaoSp, fila: [], atual: null,
    pos: mesa.assento.clone(), yaw: Math.PI, sentado: true,
    estado: 'ocioso', base: 'ocioso', ultimoTrabalho: 0, ultimoEvento: null, balao: null, balaoDesenhado: null,
    hist: [], agoraFaz: null, xp: null, festa: null, titulo: pf.titulo, funcao: pf.funcao,
    pausa: null, ociosoDesde: null, proxPausa: agora() + PAUSA_OCIOSO_MIN + Math.random() * 35,
  };
  fig.raiz.traverse((o) => { o.userData.agente = a; });
  fig.raiz.position.copy(a.pos); fig.raiz.rotation.y = a.yaw; posturaSentado(fig, true);
  agentes.set(nome, a); ordemAgentes.push(a);
  criarLinhaPainel(a);
  return a;
}
// o time do config já começa sentado nas mesas (até MAX_MESAS); os demais ganham mesa quando aparecem nos eventos
AGENTES_CFG.slice(0, MAX_MESAS).forEach((ag) => garantirAgente(ag.nome));

// Ações da fila: {t:'caminho', pts, estado, sentarAoFinal, yawFinal} | {t:'esperar', dur, estado, balao} | {t:'fn', fn}
function enfileirar(a, acao) {
  if (a.fila.length > 14) a.fila.splice(0, a.fila.length - 14, ...[]); // evita fila infinita
  a.fila.push(acao);
}
function caminhoParaCorredor(a, de) { return [new THREE.Vector3(de.x, 0, Z_CORREDOR)]; }
function caminhoMesaAMesa(a, destino) {
  // de onde o agente estiver (mesa ou corredor) -> corredor -> frente da mesa do destinatário
  return [...a.mesa.saida, ...destino.acesso];
}
function caminhoVoltar(a, mesaVisitada) {
  return [...[...mesaVisitada.acesso].reverse(), ...a.mesa.entrada, a.mesa.assento.clone()];
}
function pontoAssento(i) {
  const ang = ANGULO_ASSENTO(i);
  return new THREE.Vector3(SALA.cx + Math.cos(ang) * 3.0, 0, SALA.cz + Math.sin(ang) * 3.0);
}
function caminhoParaSala(a, iAssento) {
  const pts = [...a.mesa.saida, new THREE.Vector3(SALA.cx, 0, Z_CORREDOR), new THREE.Vector3(SALA.cx, 0, SALA.z0 + 1.2)];
  // contorna a mesa pelo anel, no sentido mais curto, partindo do ângulo da porta (-90°)
  const alvo = ANGULO_ASSENTO(iAssento), porta = -Math.PI / 2;
  let d = alvo - porta; d = Math.atan2(Math.sin(d), Math.cos(d));
  const passos = Math.max(1, Math.ceil(Math.abs(d) / (Math.PI / 4)));
  for (let k = 1; k <= passos; k++) {
    const ang = porta + d * (k / passos);
    pts.push(new THREE.Vector3(SALA.cx + Math.cos(ang) * 3.4, 0, SALA.cz + Math.sin(ang) * 3.4));
  }
  pts.push(pontoAssento(iAssento));
  return pts;
}
function caminhoDaSala(a, iAssento) {
  const alvo = ANGULO_ASSENTO(iAssento), porta = -Math.PI / 2;
  let d = alvo - porta; d = Math.atan2(Math.sin(d), Math.cos(d));
  const passos = Math.max(1, Math.ceil(Math.abs(d) / (Math.PI / 4)));
  const pts = [];
  for (let k = passos - 1; k >= 0; k--) {
    const ang = porta + d * (k / passos);
    pts.push(new THREE.Vector3(SALA.cx + Math.cos(ang) * 3.4, 0, SALA.cz + Math.sin(ang) * 3.4));
  }
  pts.push(new THREE.Vector3(SALA.cx, 0, SALA.z0 + 1.2), new THREE.Vector3(SALA.cx, 0, Z_CORREDOR), ...a.mesa.entrada, a.mesa.assento.clone());
  return pts;
}
function acaoFim(a) { return { t: 'fn', fn: () => { a.estado = a.base; a.sentado = true; a.yawAlvo = Math.PI; } }; }
function yawPara(de, para) { return Math.atan2(para.x - de.x, para.z - de.z); }

// ---------------------------------------------------------------- Itens na mão (comida, bebida, raquete)
const geoCil = new THREE.CylinderGeometry(1, 1, 1, 10), geoCone = new THREE.CylinderGeometry(0, 1, 1, 8);
const matVapor = new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.5, depthWrite: false });
function cilM(g, r, h, material, x, y, z, cone) {
  const m = new THREE.Mesh(cone ? geoCone : geoCil, material); m.scale.set(r, h, r); m.position.set(x, y, z); g.add(m); return m;
}
function itemMao(tipo) {
  const g = new THREE.Group(); g.position.set(0, -0.62, 0.03);
  const branco = mat(0xf5f5f5), cafe = mat(0x4a2c17), dourado = mat(0xe0a030);
  const vapor = () => { g.userData.vapor = caixa(0.03, 0.1, 0.03, matVapor, 0, 0.22, 0, g); };
  if (tipo === 'xicara') { cilM(g, 0.09, 0.1, branco, 0, 0.06, 0); cilM(g, 0.075, 0.012, cafe, 0, 0.112, 0); caixa(0.07, 0.03, 0.015, branco, 0.11, 0.06, 0, g); vapor(); }
  else if (tipo === 'copo') { cilM(g, 0.07, 0.17, mat(0xdbe4ec), 0, 0.09, 0); cilM(g, 0.06, 0.12, cafe, 0, 0.075, 0); vapor(); }
  else if (tipo === 'coxinha') { cilM(g, 0.17, 0.02, branco, 0, 0.01, 0); cilM(g, 0.075, 0.15, dourado, 0, 0.095, 0, true); }
  else if (tipo === 'pao') { cilM(g, 0.17, 0.02, branco, 0, 0.01, 0); for (const [x, z] of [[-0.06, 0], [0.06, 0.03], [0, -0.06]]) caixa(0.08, 0.08, 0.08, mat(0xf2c46d), x, 0.06, z, g); }
  else if (tipo === 'pastel') { caixa(0.28, 0.015, 0.18, branco, 0, 0.01, 0, g); const m = caixa(0.24, 0.05, 0.12, mat(0xd9a441), 0, 0.045, 0, g); m.rotation.y = 0.3; }
  else if (tipo === 'sanduiche') { caixa(0.2, 0.04, 0.14, mat(0xd9a066), 0, 0.03, 0, g); caixa(0.2, 0.02, 0.14, mat(0xc0392b), 0, 0.06, 0, g);
    caixa(0.21, 0.015, 0.15, mat(0x5aa84a), 0, 0.077, 0, g); caixa(0.2, 0.05, 0.14, mat(0xd9a066), 0, 0.11, 0, g); }
  else if (tipo === 'raquete') { caixa(0.03, 0.12, 0.03, mat(0x8b5a2b), 0, 0.06, 0, g); const d = cilM(g, 0.12, 0.02, mat(0xdc2626), 0, 0.2, 0); d.rotation.x = Math.PI / 2; }
  return g;
}
function pegarItem(a, tipo) {
  soltarItem(a);
  a.mao = itemMao(tipo); a.maoTipo = tipo; a.fig.bracoD.add(a.mao);
}
function soltarItem(a) { if (a.mao) { a.mao.parent.remove(a.mao); a.mao = null; a.maoTipo = null; } }

// ---------------------------------------------------------------- Ping-pong
function tickPingPong(t) {
  const sA = SLOTS.find((s) => s.pp === 'A'), sB = SLOTS.find((s) => s.pp === 'B');
  const A = sA.ocupante, B = sB.ocupante;
  if (A) A.swing = 0; if (B) B.swing = 0;
  const joga = A && B && [A, B].every((q) => q.pausa && !q.pausa.pedirVolta && q.atual && q.atual.t === 'esperar' && q.atual.pp);
  bolaPP.visible = !!joga;
  if (!joga) return;
  const per = 1.0, k = Math.floor(t / per), p = t / per - k, deA = k % 2 === 0;
  const x0 = deA ? -10.9 : -7.5, x1 = deA ? -7.5 : -10.9;
  bolaPP.position.set(x0 + (x1 - x0) * p, 1.0 + 0.55 * Math.sin(Math.PI * p), 16.9 + 0.12 * Math.sin(t * 3));
  const forca = Math.max(0, 1 - Math.min(p, 1 - p) * per / 0.22);
  const batedor = p < 0.5 ? (deA ? A : B) : (deA ? B : A);
  batedor.swing = forca;
}

// ---------------------------------------------------------------- Conversas nas pausas
// "o líder" e "o dev" usam o nome de exibição do líder e do primeiro colega do config
const NOME_LIDER = (LIDER_CFG && LIDER_CFG.titulo) || 'Líder';
const NOME_DEV = ((AGENTES_CFG.find((a) => !a.lider) || {}).titulo) || 'Dev';
const FALAS_COMUNS = [
  [`Viu que o ${NOME_DEV} quebrou o build de novo? 😂`, 'Quebrou? Foi o terceiro hoje!', 'Mas consertou rapidinho…'],
  [`O ${NOME_LIDER} pediu mais uma revisão…`, 'De novo?! Já é a quinta da semana 😅'],
  ['O teste tá rodando desde ontem…', 'Ontem?! Isso é teste ou meditação? 🧘'],
  ['Qual o café do programador?', 'Hmm… qual?', 'Java ☕', 'Pior piada do mês, parabéns 👏'],
  ['Por que o programador foi ao médico?', 'Não sei, por quê?', 'Estava com bug no estômago! 🤣', 'Ai, essa doeu 😂'],
  ['Fala baixo que vem gente 🤫', `Quem? O ${NOME_LIDER}?`, 'Ele mesmo… finge que tá trabalhando 😅'],
  ['Esse bug só acontece na minha máquina…', 'Clássico! Na dos outros funciona 🙃'],
  ['Tem café fresquinho?', 'Acabei de passar, aproveita ☕', 'Você é meu herói 🦸'],
  ['Sexta-feira já?', 'Só se for sexta de outro mês 😭'],
  ['Vi um commit com a mensagem "arrumei"…', 'Arrumou o quê?', 'Ninguém sabe 🤷'],
  ['Acharam mais um bug…', 'Esse é feature, confia 😎', 'kkkkk não acredito!'],
  ['Quem escreveu essa regex?', 'Foi você, mês passado 🙃', 'Não me lembro de nada…'],
  ['O merge deu conflito em 40 arquivos', 'Respira fundo… um de cada vez 😮‍💨'],
];
// só no tema "sao-paulo"
const FALAS_SP = [
  ['a Marginal parada de novo', 'Nem me fala, 2 horas de volta 😩', 'Home office é a solução!'],
  ['garoa e frio, típico de SP', 'Cinco minutos atrás tava um sol de rachar 🌦️'],
  ['bora num pastel de feira depois?', 'Bora! Com caldo de cana? 🥤', 'Fechado!'],
  ['Tá chovendo em SP?', 'Garoa… mas o trânsito já é dilúvio 🌧️', 'Verdade…'],
  ['Quem pegou a última coxinha?', 'Não fui eu… 😇', 'Tá com farelo na camisa, hein kkkk'],
];
const FALAS = TEMA_SP ? [...FALAS_COMUNS, ...FALAS_SP] : FALAS_COMUNS;
const FALAS_PP = [
  ['ponto! 🏓', 'foi sorte!'], ['essa foi na rede 😅', 'saca de novo, vai!'],
  ['vai perder, hein? 😏', 'só se o build quebrar antes 😂'], ['10 a 9!', 'ainda dá pra virar 💪'],
  ['que smash! 🔥', 'quase me acertou na cara kkkk'],
];
const convs = {}, proxConv = {}, ultimaFala = {};
const GRUPOS_CONV = ['descanso', 'refeitorio', 'pp'];
function fimConversa(k, t) {
  const c = convs[k];
  if (c) for (const q of c.quem) { q.emConversa = false; if (k !== 'pp' && q.pausa) q.yawAlvo = q.pausa.slot.yaw; }
  delete convs[k];
  if (t !== undefined) proxConv[k] = t + 5 + Math.random() * 6; else delete proxConv[k];
}
function tickConversas(t) {
  const grupos = {};
  for (const a of ordemAgentes) {
    a.emConversa = false;
    const p = a.pausa, x = a.atual;
    if (!p || p.pedirVolta || !x || x.t !== 'esperar' || !x.pausa || p.slot.lugar === 'banheiro' || !a.fig.dentro.visible) continue;
    (grupos[p.slot.pp ? 'pp' : p.slot.lugar] ||= []).push(a);
  }
  for (const k of GRUPOS_CONV) {
    const g = grupos[k] || [], c = convs[k];
    if (g.length < 2) { if (c) fimConversa(k); delete proxConv[k]; continue; }
    if (!c) {
      if (proxConv[k] === undefined) proxConv[k] = t + 2.5;
      if (t < proxConv[k]) continue;
      const banco = k === 'pp' ? FALAS_PP : FALAS;
      let i; do { i = Math.floor(Math.random() * banco.length); } while (banco.length > 1 && i === ultimaFala[k]);
      ultimaFala[k] = i;
      const par = g.slice().sort(() => Math.random() - 0.5).slice(0, 2);
      convs[k] = { linhas: banco[i], i: 0, quem: par, prox: t };
    }
    const cv = convs[k];
    if (!cv.quem.every((q) => g.includes(q))) { fimConversa(k, t); continue; }
    cv.quem.forEach((q) => { q.emConversa = true; });
    if (t < cv.prox) continue;
    if (cv.i >= cv.linhas.length) { fimConversa(k, t); continue; }
    const fala = cv.quem[cv.i % 2], ouve = cv.quem[(cv.i + 1) % 2], texto = cv.linhas[cv.i], dur = 3.3;
    const riso = /k{3,}|😂|🤣|😅/i.test(texto);
    fala.balao = { texto, icone: k === 'pp' ? '🏓' : '💬', ate: t + dur };
    fala.gesto = { ate: t + dur, tipo: 'fala', riso }; ouve.gesto = { ate: t + dur, tipo: 'ouve', riso };
    if (k !== 'pp') { fala.yawAlvo = yawPara(fala.pos, ouve.pos); ouve.yawAlvo = yawPara(ouve.pos, fala.pos); }
    cv.i++; cv.prox = t + dur + 0.1 + Math.random() * 0.7;
  }
}
function tickSocial(t) { animarAreas(t); tickPingPong(t); tickConversas(t); }

// ---------------------------------------------------------------- Pausas (descanso, refeitório, banheiro)
const ROTULO_LUGAR = { descanso: 'descanso', refeitorio: 'refeitório', banheiro: 'banheiro' };
const DUR_PAUSA = { descanso: [15, 30], refeitorio: [10, 20], banheiro: [6, 10] };
const emDemo = () => demoForcada || demoAuto;
function lugarNormalizado(l) {
  return String(l || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
}
// Itens da pausa levam pausa:true; 'sair' diz por onde voltar ao corredor se a pausa for interrompida.
function itemVolta(a, pts) {
  return { t: 'caminho', pausa: true, volta: true, pts: [...pts, ...a.mesa.entrada, a.mesa.assento.clone()],
    estado: 'em pausa · voltando', sentarAoFinal: true, yawFinal: Math.PI };
}
function itemParaSlot(s, icone) {
  if (s.lugar !== 'refeitorio') return null;
  const lista = icone === '☕' ? ['xicara', 'copo'] : (TEMA_SP ? ['coxinha', 'pao', 'pastel', 'sanduiche'] : ['pao', 'pastel', 'sanduiche']);
  return lista[Math.floor(Math.random() * lista.length)];
}
// Monta a fila da pausa (ida, item na mão, espera, volta). 'prefixo' = pontos para sair de outro lugar de pausa.
function planejarPausa(a, s, prefixo, durFixa) {
  s.ocupante = a;
  a.pausa = { slot: s, pedirVolta: false };
  const estado = 'em pausa · ' + ROTULO_LUGAR[s.lugar];
  const [d0, d1] = DUR_PAUSA[s.lugar], dur = durFixa || d0 + Math.random() * (d1 - d0);
  const [icone, texto] = s.baloes[Math.floor(Math.random() * s.baloes.length)];
  const destino = s.frente || s.pos;   // cabine: primeiro para na frente da porta
  const ida = prefixo ? [...prefixo, ...s.rota, destino] : [...a.mesa.saida, V3(s.entX, Z_CORREDOR), ...s.rota, destino];
  const saida = [...s.rota].reverse().concat([V3(s.entX, Z_CORREDOR)]);
  enfileirar(a, { t: 'caminho', pausa: true, pts: ida, estado, sentarAoFinal: s.sentar, yawFinal: s.frente ? 0 : s.yaw, sair: (i) => ida.slice(0, i).reverse() });
  const item = s.pp ? 'raquete' : itemParaSlot(s, icone);
  if (item) enfileirar(a, { t: 'fn', pausa: true, fn: () => pegarItem(a, item) });
  let volta = saida;
  if (s.pia) { // banheiro: espera a porta da cabine abrir, entra e some; ao sair a porta abre de novo; depois lava as mãos
    const porta = [V3(PORTA_BANHEIRO.x, 9.8), V3(PORTA_BANHEIRO.x, Z_CORREDOR)];
    const deDentro = [s.frente, ...saida];
    enfileirar(a, { t: 'esperar', pausa: true, dur: CABINE.ABRIR, estado, sair: saida });
    enfileirar(a, { t: 'caminho', pausa: true, pts: [s.pos], estado, yawFinal: s.yaw, sair: () => deDentro });
    enfileirar(a, { t: 'fn', pausa: true, fn: () => { a.fig.dentro.visible = false; } });
    enfileirar(a, { t: 'esperar', pausa: true, dur, estado, balao: { texto, icone }, sair: deDentro });
    enfileirar(a, { t: 'fn', pausa: true, fn: () => { a.fig.dentro.visible = true; } });
    enfileirar(a, { t: 'esperar', pausa: true, dur: CABINE.ABRIR, estado, sair: deDentro });
    enfileirar(a, { t: 'caminho', pausa: true, pts: [s.frente, s.rota[s.rota.length - 1], s.pia], estado, yawFinal: -Math.PI / 2, sair: () => porta });
    enfileirar(a, { t: 'esperar', pausa: true, dur: 2.5, estado, balao: { texto: 'lavando as mãos', icone: '🧼' }, sair: porta });
    volta = porta;
  } else {
    enfileirar(a, { t: 'esperar', pausa: true, pp: !!s.pp, dur, estado, balao: { texto, icone }, sair: saida });
  }
  enfileirar(a, itemVolta(a, volta));
  enfileirar(a, { ...acaoFim(a), pausa: true });
  enfileirar(a, { t: 'fn', pausa: true, fn: () => encerrarPausa(a) });
}
const slotsPP = () => [SLOTS.find((s) => s.pp === 'A'), SLOTS.find((s) => s.pp === 'B')];
function parceiroPP(a) { // alguém já em pausa no descanso (parado, fora do ping-pong)
  const [sA, sB] = slotsPP();
  if (sA.ocupante || sB.ocupante) return null;
  return ordemAgentes.find((b) => b !== a && b.pausa && b.pausa.slot.lugar === 'descanso' && !b.pausa.slot.pp && !b.pausa.pedirVolta
    && b.atual && b.atual.t === 'esperar' && b.atual.pausa) || null;
}
function iniciarPartida(a, b) { // a e b jogam ping-pong; b pode estar em outra pausa do descanso
  const [sA, sB] = slotsPP();
  if (sA.ocupante || sB.ocupante || a.pausa) return false;
  const dur = 22 + Math.random() * 12;
  let prefixo = null;
  if (b.pausa) { // b larga o lugar atual e vai para a mesa
    const antigo = b.pausa.slot; antigo.ocupante = null; prefixo = [...antigo.rota].reverse();
    b.fila = b.fila.filter((i) => !i.pausa); b.atual = null; b.balao = null; b.pausa = null; soltarItem(b);
  }
  planejarPausa(b, sB, prefixo, dur);
  planejarPausa(a, sA, null, dur);
  return true;
}
function iniciarPausa(a, lugar) {
  if (a.pausa) return false;
  lugar = lugar ? lugarNormalizado(lugar) : '';
  let livres = SLOTS.filter((s) => !s.ocupante && !s.pp && (!lugar || s.lugar === lugar));
  if (!livres.length) return false;
  if (!lugar) { // sorteia o lugar primeiro, para as três áreas serem visitadas de forma equilibrada
    const lugares = [...new Set(livres.map((s) => s.lugar))];
    const l = lugares[Math.floor(Math.random() * lugares.length)];
    livres = livres.filter((s) => s.lugar === l);
  }
  const s = livres[Math.floor(Math.random() * livres.length)];
  if (s.lugar === 'descanso' && Math.random() < (emDemo() ? 0.8 : 0.6)) { // às vezes vão jogar ping-pong
    const b = parceiroPP(a);
    if (b && iniciarPartida(a, b)) return true;
  }
  planejarPausa(a, s);
  return true;
}
function encerrarPausa(a) {
  if (a.pausa) { a.pausa.slot.ocupante = null; a.pausa = null; }
  a.fig.dentro.visible = true; soltarItem(a); a.gesto = null; a.swing = 0;
  a.proxPausa = agora() + (30 + Math.random() * 30) * (emDemo() ? 0.3 : 1);
}
// Evento real para quem está em pausa: pede para voltar à mesa (aplicado pelo laço do agente).
function interromperPausa(a) {
  if (!a || !a.pausa) return;
  if (a.emConversa && !a.pausa.pedirVolta) a.balaoSaida = agora() + 2.5;   // sai da conversa dizendo que foi chamado
  a.pausa.pedirVolta = true;
}
function aplicarInterrupcao(a) {
  const p = a.pausa, x = a.atual;
  if (x && x.volta) { p.pedirVolta = false; return; }                // já está voltando
  if (!x && a.fila.some((i) => i.pausa)) return;                     // espera o próximo item começar
  let sair = [];
  if (x && x.t === 'caminho' && x.pausa) {                           // termina o trecho atual e volta dali
    sair = x.sair(x.i); x.pts.length = x.i + 1; x.sentarAoFinal = false; x.yawFinal = undefined;
  } else if (x && x.t === 'esperar' && x.pausa) {                    // levanta na hora
    sair = x.sair; a.atual = null; a.balao = null;
  }
  a.fila = a.fila.filter((i) => !i.pausa);
  a.fila.unshift(itemVolta(a, sair), { ...acaoFim(a), pausa: true }, { t: 'fn', pausa: true, fn: () => encerrarPausa(a) });
  p.pedirVolta = false;
  a.fig.dentro.visible = true;
  a.estado = 'em pausa · voltando';
  if (a.balaoSaida) { a.balao = { texto: 'fui, me chamaram', icone: '🏃', ate: a.balaoSaida }; a.balaoSaida = 0; }
  a.gesto = null;
}

function falar(a, destino, resumo, ferr) {
  if (!destino || destino === a) { balao(a, resumo, ferr, TEMPO_FALA + 1); return; }
  interromperPausa(destino);
  const pts = caminhoMesaAMesa(a, destino.mesa);
  const dirOlhar = yawPara(destino.mesa.visita, destino.mesa.assento);
  enfileirar(a, { t: 'caminho', pts, estado: 'conversando', yawFinal: dirOlhar });
  enfileirar(a, { t: 'esperar', dur: TEMPO_FALA, estado: 'conversando', balao: { texto: resumo, icone: iconeDe(ferr, 'sendmessage') } });
  enfileirar(a, { t: 'caminho', pts: caminhoVoltar(a, destino.mesa), estado: 'conversando', sentarAoFinal: true, yawFinal: Math.PI });
  enfileirar(a, acaoFim(a));
}
function reuniao(participantes, falante, resumo, ferr) {
  participantes.forEach(interromperPausa);
  participantes.forEach((a, i) => {
    enfileirar(a, { t: 'caminho', pts: caminhoParaSala(a, i), estado: 'em reunião', yawFinal: yawPara(pontoAssento(i), new THREE.Vector3(SALA.cx, 0, SALA.cz)) });
    enfileirar(a, { t: 'esperar', dur: TEMPO_REUNIAO, estado: 'em reunião',
      balao: { texto: a === falante ? resumo : '…', icone: a === falante ? iconeDe(ferr, 'sendmessage') : '👥' } });
    enfileirar(a, { t: 'caminho', pts: caminhoDaSala(a, i), estado: 'em reunião', sentarAoFinal: true, yawFinal: Math.PI });
    enfileirar(a, acaoFim(a));
  });
}
function iconeDe(ferr, padrao) {
  const k = String(ferr || '').toLowerCase();
  if (ICONES[k]) return ICONES[k];
  for (const c of Object.keys(ICONES)) if (k.includes(c)) return ICONES[c];
  return padrao ? ICONES[padrao] : '🔧';
}
function balao(a, texto, ferr, dur = TEMPO_BALAO_TRABALHO) {
  a.balao = { texto: String(texto || '').slice(0, 90), icone: iconeDe(ferr), ate: agora() + dur };
}

// ---------------------------------------------------------------- XP, nível e comemoração
// Dados vêm do placar.js (GET /xp ou demonstração). Aqui só desenhamos: rótulo da mesa, pulinhos, balão e confete.
const TEMPO_FESTA = 4;
const N_CONFETE = MOVEL ? 50 : 140, confeteInfo = { vivos: 0 };
const confPos = new Float32Array(N_CONFETE * 3), confCor = new Float32Array(N_CONFETE * 3);
const confVel = new Float32Array(N_CONFETE * 3), confVida = new Float32Array(N_CONFETE);
const confGeo = new THREE.BufferGeometry();
confGeo.setAttribute('position', new THREE.BufferAttribute(confPos, 3));
confGeo.setAttribute('color', new THREE.BufferAttribute(confCor, 3));
const confete = new THREE.Points(confGeo, new THREE.PointsMaterial({ size: 0.22, vertexColors: true, depthWrite: false }));
confete.frustumCulled = false; confete.visible = false; cena.add(confete);
const CORES_CONFETE = ['#ef4444', '#f59e0b', '#facc15', '#22c55e', '#3b82f6', '#a855f7', '#ec4899'].map((c) => new THREE.Color(c));
function soltarConfete(x, z, n = MOVEL ? 16 : 45) {
  let k = 0;
  for (let i = 0; i < N_CONFETE && k < n; i++) {
    if (confVida[i] > 0) continue;
    const c = CORES_CONFETE[(Math.random() * CORES_CONFETE.length) | 0], j = i * 3;
    confPos[j] = x + (Math.random() - 0.5) * 2.2; confPos[j + 1] = 4.2 + Math.random() * 1.6; confPos[j + 2] = z + (Math.random() - 0.5) * 2.2;
    confVel[j] = (Math.random() - 0.5) * 1.6; confVel[j + 1] = 1 + Math.random() * 2.2; confVel[j + 2] = (Math.random() - 0.5) * 1.6;
    confCor[j] = c.r; confCor[j + 1] = c.g; confCor[j + 2] = c.b;
    confVida[i] = TEMPO_FESTA * (0.7 + Math.random() * 0.3); k++;
  }
  confeteInfo.vivos = 1; confete.visible = true;
  confGeo.attributes.color.needsUpdate = true;
}
function tickConfete(dt) {
  if (!confeteInfo.vivos) return;
  let vivos = 0;
  for (let i = 0; i < N_CONFETE; i++) {
    const j = i * 3;
    if (confVida[i] <= 0) { confPos[j + 1] = -50; continue; }
    confVida[i] -= dt; vivos++;
    confVel[j + 1] -= 3.2 * dt;
    if (confVel[j + 1] < -2.2) confVel[j + 1] = -2.2;   // cai devagar, como papel
    confPos[j] += confVel[j] * dt; confPos[j + 1] += confVel[j + 1] * dt; confPos[j + 2] += confVel[j + 2] * dt;
    if (confPos[j + 1] < 0.05) { confPos[j + 1] = 0.05; confVel[j] = confVel[j + 2] = 0; }
  }
  confGeo.attributes.position.needsUpdate = true;
  if (!vivos) { confeteInfo.vivos = 0; confete.visible = false; }
}
function xpDefinir(nome, info) {   // info: {nivel, titulo, xp, xp_base, xp_proximo} ou null
  const a = agentes.get(normalizarNome(nome)); if (!a) return false;
  a.xp = info || null;
  desenharNome(a.nomeSp, a.titulo, a.cor, a.funcao, a.xp);
  return true;
}
function comemorar(nome, titulo) {
  const a = agentes.get(normalizarNome(nome)); if (!a) return false;
  const t = agora(), tit = titulo || (a.xp && a.xp.titulo) || 'um novo nível';
  a.festa = { ate: t + TEMPO_FESTA };
  a.balao = { texto: 'subiu para ' + tit + '!', icone: '🎉', ate: t + TEMPO_FESTA };
  soltarConfete(a.pos.x, a.pos.z);
  return true;
}

// Subagentes
const subagentes = [];
function criarSubagente(pai, resumo, ferr, nomeSub, funcaoSub) {
  const cor = pai.cor;
  const fig = criarFigura(cor, 0.6);
  const pf = rotulos(nomeSub || 'Assistente', perfil(nomeSub || 'Assistente', funcaoSub));
  const rot = criarSprite(384, 96, 4.2, 1.05); desenharNome(rot, pf.titulo, cor, pf.funcao);
  rot.sprite.position.y = 2.6; fig.raiz.add(rot.sprite);
  const indice = subagentes.filter((s) => s.pai === pai).length % 3;
  fig.raiz.position.set(pai.mesa.sub.x - indice * 0.9, 0, pai.mesa.sub.z);
  fig.raiz.rotation.y = Math.PI * 0.9;
  const bal = criarSprite(640, 220, 7.0, 2.4);
  bal.sprite.position.y = 4.9;
  desenharBalao(bal, resumo || 'subagente', iconeDe(ferr, 'task'), cor);
  fig.raiz.add(bal.sprite);
  cena.add(fig.raiz);
  const s = { pai, fig, bal, nasc: agora(), fase: Math.random() * 6 };
  subagentes.push(s);
  if (subagentes.length > 12) removerSubagente(subagentes[0]);
}
function removerSubagente(s) {
  const i = subagentes.indexOf(s); if (i >= 0) subagentes.splice(i, 1);
  cena.remove(s.fig.raiz);
  s.bal.tex.dispose(); s.bal.sprite.material.dispose();
}

function atualizarAgente(a, dt, t) {
  const f = a.fig;
  // fila
  if (!a.atual && a.fila.length) {
    a.atual = a.fila.shift();
    const x = a.atual;
    if (x.estado) a.estado = x.estado;
    if (x.t === 'caminho') { a.sentado = false; x.i = 0; posturaSentado(f, false); }
    if (x.t === 'esperar') { x.fim = t + x.dur; if (x.balao) a.balao = { texto: x.balao.texto, icone: x.balao.icone, ate: t + x.dur }; }
    if (x.t === 'fn') { a.atual = null; x.fn(); }   // atual já nulo: os fn podem testar !a.atual para atualizar o estado
  }
  const x = a.atual;
  let andando = false;
  if (x && x.t === 'caminho') {
    const alvo = x.pts[x.i];
    const dx = alvo.x - a.pos.x, dz = alvo.z - a.pos.z, dist = Math.hypot(dx, dz);
    const passo = ESCALA_VELOCIDADE * dt;
    if (dist <= passo) {
      a.pos.set(alvo.x, 0, alvo.z); x.i++;
      if (x.i >= x.pts.length) {
        a.atual = null;
        if (x.sentarAoFinal) { a.sentado = true; posturaSentado(f, true); }
        if (x.yawFinal !== undefined) a.yawAlvo = x.yawFinal;
      }
    } else {
      a.pos.x += dx / dist * passo; a.pos.z += dz / dist * passo;
      a.yawAlvo = Math.atan2(dx, dz);
      andando = true;
    }
  } else if (x && x.t === 'esperar') {
    if (t >= x.fim) a.atual = null;
  }
  // rotação suave
  if (a.yawAlvo !== undefined) {
    let d = a.yawAlvo - a.yaw; d = Math.atan2(Math.sin(d), Math.cos(d));
    a.yaw += d * Math.min(1, dt * 10);
  }
  f.raiz.position.copy(a.pos); f.raiz.rotation.y = a.yaw;
  // animação
  if (andando) {
    const w = t * 9;
    f.pernaE.rotation.x = Math.sin(w) * 0.7; f.pernaD.rotation.x = -Math.sin(w) * 0.7;
    f.bracoE.rotation.x = -Math.sin(w) * 0.6; f.bracoD.rotation.x = Math.sin(w) * 0.6;
    f.dentro.position.y = Math.abs(Math.sin(w)) * 0.06; f.dentro.rotation.x = 0;
  } else if (a.sentado) {
    if (a.base === 'trabalhando') {
      f.bracoE.rotation.x = -1.1 + Math.sin(t * 17 + 1) * 0.08; f.bracoD.rotation.x = -1.1 + Math.sin(t * 15) * 0.08;
      f.dentro.rotation.x = 0.08; f.cabeca.rotation.x = 0.05;
    } else { // relaxado: recosta e balança de leve
      f.bracoE.rotation.x = f.bracoD.rotation.x = -0.2;
      f.dentro.rotation.x = -0.14 + Math.sin(t * 1.2 + a.mesa.indice) * 0.02; f.cabeca.rotation.x = -0.12;
    }
    f.dentro.position.y = -0.1;
  } else {
    f.pernaE.rotation.x = f.pernaD.rotation.x = 0; f.bracoE.rotation.x = f.bracoD.rotation.x = 0; f.dentro.rotation.x = 0;
    f.dentro.position.y = Math.sin(t * 2 + a.mesa.indice) * 0.01;
    if (x && x.t === 'esperar') f.bracoD.rotation.x = -0.8 + Math.sin(t * 6) * 0.25; // gesticula
  }
  // item na mão (levar à boca de vez em quando / raquete) e gestos de conversa
  f.cabeca.rotation.z = 0;
  if (a.mao) {
    let ang = -1.2;
    if (a.maoTipo === 'raquete') ang = -1.0 - 0.9 * (a.swing || 0);
    else { const ph = (t + a.mesa.indice * 1.7) % 7; if (ph < 1.4) ang -= 1.1 * Math.sin(Math.PI * ph / 1.4); }
    f.bracoD.rotation.x = ang; a.mao.rotation.x = -ang;
    const v = a.mao.userData.vapor; if (v) v.position.y = 0.2 + ((t * 0.5) % 1) * 0.12;
  }
  const g = a.gesto;
  if (g && t < g.ate && !andando) {
    if (g.tipo === 'fala') { f.bracoE.rotation.x = -0.9 + Math.sin(t * 8) * 0.45; f.cabeca.rotation.z = Math.sin(t * 6) * 0.1; }
    else f.cabeca.rotation.x += Math.sin(t * 5) * 0.08;
    if (g.riso) f.dentro.position.y += Math.abs(Math.sin(t * 13)) * 0.08;
  }
  if (a.festa) {   // comemoração: pulinhos com os braços para cima
    if (t < a.festa.ate) {
      f.dentro.position.y += Math.abs(Math.sin(t * 8)) * 0.45;
      f.bracoE.rotation.x = f.bracoD.rotation.x = -2.9 + Math.sin(t * 16) * 0.3;
    } else a.festa = null;
  }
  // pausas: atende pedido de volta e decide quando um agente ocioso vai descansar
  if (a.pausa && a.pausa.pedirVolta && (a.atual || !a.fila.some((i) => i.pausa))) aplicarInterrupcao(a);
  const livre = a.base === 'ocioso' && !a.atual && !a.fila.length && !a.pausa && a.sentado;
  if (!livre) a.ociosoDesde = null;
  else {
    if (a.ociosoDesde == null) a.ociosoDesde = t;
    const demo = emDemo();
    const prox = demo ? Math.min(a.proxPausa, a.ociosoDesde + 10 + a.mesa.indice * 4) : a.proxPausa;
    if (t - a.ociosoDesde >= PAUSA_OCIOSO_MIN * (demo ? 0.25 : 1) && t >= prox && !iniciarPausa(a)) a.proxPausa = t + 8;
  }
  // expiração do trabalho
  if (a.base === 'trabalhando' && t - a.ultimoTrabalho > TRABALHO_EXPIRA && t > (a.ocupadoAte || 0)) { a.base = 'ocioso'; if (!a.atual && !a.fila.length) a.estado = 'ocioso'; }
  // monitores
  const acende = a.base === 'trabalhando';
  for (const m of a.mesa.monitores) {
    if (acende) m.color.setHex(a.cor).multiplyScalar(0.55 + 0.45 * Math.sin(t * 7 + a.mesa.indice * 2) * 0.5 + 0.22);
    else m.color.setHex(0x161e2b);
  }
  // teclas piscam de leve enquanto trabalha
  a.mesa.teclas.color.setHex(COR_TECLAS);
  if (acende && a.sentado) a.mesa.teclas.color.lerp(corTmp.setHex(a.cor), 0.45 * (0.5 + 0.5 * Math.sin(t * 19 + a.mesa.indice)));
  // balão
  const b = a.balaoSp;
  if (a.balao && t < a.balao.ate) {
    const chave = a.balao.texto + a.balao.icone;
    if (a.balaoDesenhado !== chave) { desenharBalao(b, a.balao.texto, a.balao.icone, a.cor); a.balaoDesenhado = chave; }
    b.sprite.visible = true;
  } else { b.sprite.visible = false; a.balao = null; a.balaoDesenhado = null; }
}

// ---------------------------------------------------------------- Painel
const CORES_ESTADO = { trabalhando: '#22c55e', conversando: '#3b82f6', 'em reunião': '#a855f7', 'em pausa': '#eab308', ocioso: '#6b7280' };
function criarLinhaPainel(a) {
  const li = document.createElement('li');
  li.innerHTML = '<span class="ponto"></span><div class="info"><div class="nome"></div><div class="funcao"></div><div class="sub"></div></div><div class="hora">--:--:--</div>';
  li.querySelector('.nome').textContent = a.titulo;
  li.querySelector('.funcao').textContent = a.funcao;
  li.querySelector('.nome').style.color = corCss(a.cor);
  li.addEventListener('click', () => { focarAgente(a); abrirFicha(a); });
  ulAgentes.appendChild(li);
  a.li = li; a.liPonto = li.querySelector('.ponto'); a.liSub = li.querySelector('.sub'); a.liHora = li.querySelector('.hora');
  a.ultimaLinha = '';
}
function atualizarPainel() {
  for (const a of ordemAgentes) {
    const e = a.estado;
    if (a.ultimaLinha !== e + '|' + a.ultimoEvento) {
      a.liSub.textContent = e; a.liPonto.style.background = CORES_ESTADO[e.split(' · ')[0]] || '#6b7280';
      a.liHora.textContent = a.ultimoEvento || '--:--:--'; a.ultimaLinha = e + '|' + a.ultimoEvento;
    }
  }
}
// resumo da gaveta no celular ("4 agentes · 2 trabalhando")
const elResumo = $('resumo');
let resumoAtual = '';
function atualizarResumo() {
  if (!elResumo) return;
  const n = ordemAgentes.length, w = ordemAgentes.filter((a) => String(a.estado).startsWith('trabalhando')).length;
  const txt = `${n} agente${n === 1 ? '' : 's'} · ${w} trabalhando`;
  if (txt !== resumoAtual) { resumoAtual = txt; elResumo.textContent = txt; }
}
function horaDe(ev) {
  const m = /(\d{2}:\d{2}:\d{2})/.exec(String(ev && ev.ts || ''));
  return m ? m[1] : new Date().toTimeString().slice(0, 8);
}
function adicionarFeed(ev, ag) {
  const li = document.createElement('li');
  const cor = ag ? corCss(ag.cor) : '#666';
  li.style.borderLeftColor = cor;
  const t = document.createElement('span'); t.className = 't'; t.textContent = horaDe(ev);
  const n = document.createElement('b'); n.style.color = cor; n.textContent = String(ev.agente || '?').replace(/_/g, ' ');
  const para = Array.isArray(ev.para) && ev.para.length ? ' → ' + ev.para.join(', ') : '';
  const rest = document.createTextNode(` ${iconeDe(ev.ferramenta)}${para}: ${String(ev.resumo || ev.tipo || '').slice(0, 120)}`);
  li.append(t, n, rest);
  olFeed.prepend(li);
  while (olFeed.children.length > MAX_FEED) olFeed.lastChild.remove();
}

// ---------------------------------------------------------------- Ficha do agente (clique no painel ou no boneco)
const MAX_HIST = 120;
const fichaEl = $('ficha');
let fichaAberta = null, abaFicha = 'trabalho';
function guardarHist(a, ev, papel) {
  a.hist.push({ ev, papel });
  if (a.hist.length > MAX_HIST) a.hist.splice(0, a.hist.length - MAX_HIST);
}
function abrirFicha(a) { fichaAberta = a; fichaEl.hidden = false; desenharFicha(); }
function fecharFicha() { fichaAberta = null; fichaEl.hidden = true; }
function el(tag, cls, texto) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (texto != null) e.textContent = texto;
  return e;
}
function desenharFicha() {
  const a = fichaAberta; if (!a) return;
  const cor = corCss(a.cor);
  fichaEl.style.borderTopColor = cor;
  $('fichaNome').textContent = a.titulo + (a.funcao ? ' — ' + a.funcao : ''); $('fichaNome').style.color = cor;
  $('fichaEstado').textContent = a.estado + (a.ultimoEvento ? ' · último evento ' + a.ultimoEvento : '');
  const f = a.agoraFaz;
  $('fichaAgora').textContent = f ? iconeDe(f.ferramenta) + ' ' + (f.ferramenta || '') + ' — ' + (f.resumo || '') : 'sem trabalho em andamento';
  document.querySelectorAll('#ficha .abas button').forEach((b) => b.classList.toggle('ativo', b.dataset.aba === abaFicha));
  const lista = $('fichaLista'); lista.textContent = '';
  if (abaFicha === 'xp') { desenharAbaXp(lista, a); return; }
  if (abaFicha === 'cartoes') { desenharAbaCartoes(lista, a); return; }
  const conversa = (x) => x.ev.tipo === 'fala' || x.ev.tipo === 'reuniao';
  const itens = a.hist.filter((x) => (abaFicha === 'conversas' ? conversa(x) : !conversa(x))).slice().reverse();
  if (!itens.length) lista.append(el('li', 'vazio', abaFicha === 'conversas' ? 'Nenhuma conversa ainda.' : 'Nenhum trabalho registrado ainda.'));
  for (const item of itens) {
    const ev = item.ev, papel = item.papel;
    const li = el('li', papel);
    const topo = el('div', 'topo');
    topo.append(el('span', 't', horaDe(ev)));
    if (conversa(item)) {
      const quem = papel === 'fez' ? '→ ' + ((ev.para || []).join(', ') || 'todos') : '← ' + String(ev.agente || '?');
      topo.append(el('b', null, (ev.tipo === 'reuniao' ? '👥 reunião ' : '💬 ') + quem.replace(/_/g, ' ')));
    } else {
      topo.append(el('b', null, iconeDe(ev.ferramenta) + ' ' + (ev.ferramenta || ev.tipo || '')));
    }
    li.append(topo, el('div', 'resumo', ev.resumo || ''));
    const extra = conversa(item) ? ev.texto : ev.detalhe;
    if (extra && extra !== ev.resumo) li.append(el('pre', 'detalhe', extra));
    lista.append(li);
  }
}
function desenharAbaXp(lista, a) {
  const P = window.__placar, d = P && P.agente ? P.agente(a.nome) : null;
  if (!d) { lista.append(el('li', 'vazio', P && P.indisponivel ? 'Placar indisponível.' : 'Sem pontos registrados para este agente ainda.')); return; }
  const cn = CORES_NIVEL[Math.max(0, Math.min(4, d.nivel - 1))];
  const li = el('li', 'xp-resumo'); li.style.borderLeftColor = cn;
  const t = el('div', 'xp-titulo'); t.style.color = cn; t.textContent = estrelas(d.nivel) + '  ' + d.titulo_nivel + ' · nível ' + d.nivel;
  const barra = el('div', 'xp-barra'), enc = el('i'); enc.style.width = Math.round(progressoXp(a.xp || d) * 100) + '%'; enc.style.background = cn; barra.append(enc);
  const falta = d.xp_proximo == null ? 'nível máximo' : 'faltam ' + Math.max(0, d.xp_proximo - d.xp) + ' XP para ' + (d.titulo_proximo || 'o próximo nível');
  li.append(t, el('div', 'xp-linha', d.xp + ' XP · ' + (d.prs || 0) + ' PR(s) pontuado(s)'), barra, el('div', 'xp-linha dim', falta));
  lista.append(li);
  const secao = (txt) => lista.append(el('li', 'xp-secao', txt));
  secao('Últimos pontos');
  if (!(d.ultimos || []).length) lista.append(el('li', 'vazio', 'Nenhum ponto ainda.'));
  for (const u of d.ultimos || []) {
    const x = el('li', 'xp-ponto' + (u.faixa === 'vermelho' ? ' faixa-vermelho' : u.faixa === 'amarelo' ? ' faixa-amarelo' : '')), topo = el('div', 'topo');
    topo.append(el('b', null, u.pr != null ? 'PR #' + u.pr : 'Skills'), el('span', u.pontos < 0 ? 'neg' : 'pos', (u.pontos > 0 ? '+' : '') + u.pontos));
    if (u.data) topo.append(el('span', 't', String(u.data).slice(0, 10)));
    x.append(topo);
    for (const m of u.motivos || []) x.append(el('div', /[-−]\s*\d+\s*$/.test(m) ? 'motivo neg' : 'motivo pos', m));
    lista.append(x);
  }
  if ((d.auditoria || []).length) {
    secao('⚠️ Auditorias abertas');
    for (const u of d.auditoria) { const x = el('li', 'xp-auditoria'); x.append(el('b', null, '🔴 PR #' + u.pr), el('span', null, ' — ' + u.motivo + ' (pontos zerados)')); const bt = P.botao && P.botao('liberar', u.pr); if (bt) x.append(bt); lista.append(x); }
    if (P.nota && P.nota('liberar')) lista.append(el('li', 'xp-linha dim', P.nota('liberar')));
  }
  if ((d.conferir || []).length) {
    secao('🟡 Para conferir');
    for (const u of d.conferir) { const x = el('li', 'xp-conferir'); x.append(el('b', null, '🟡 PR #' + u.pr), el('span', null, ' — ' + u.motivo + ' (pontos normais)')); const bt = P.botao && P.botao('conferido', u.pr); if (bt) x.append(bt); lista.append(x); }
    if (P.nota && P.nota('conferido')) lista.append(el('li', 'xp-linha dim', P.nota('conferido')));
  }
  secao('Skills');
  lista.append(el('li', 'xp-linha', (d.skills_autor || []).length ? 'Autoria: ' + d.skills_autor.join(', ') : 'Nenhuma skill de autoria ainda.'));
  lista.append(el('li', 'xp-linha', 'Reusadas por outros agentes: ' + (d.skills_reusadas_por_outros || 0)));
}
// Aba "Cartões": os cartões ativos do agente no Kanban (todas as colunas menos a primeira, o backlog, e as concluídas),
// pelo campo "time" do cartão e o mapa github.times; dados do kanban.js, lidos do /kanban.
function desenharAbaCartoes(lista, a) {
  const K = window.__kanban, d = K && K.dados();
  if (!d || (!(d.cartoes || []).length && d.erro)) {
    lista.append(el('li', 'vazio', d ? 'Kanban indisponível: ' + d.erro : 'Carregando o quadro…')); return;
  }
  const meus = d.cartoes.filter((c) => { const ag = K.agenteDoTime(c.time); return ag && chaveNome(ag.nome) === chaveNome(a.nome); });
  const ordem = K.colunas(d.cartoes), ativas = ordem.filter((s, i) => !K.ehConcluida(s) && (i > 0 || ordem.length <= 2));
  const PRIO = { P0: 0, P1: 1, P2: 2, high: 0, medium: 1, low: 2 }, cores = K.CORES_PRIORIDADE || {};
  for (const status of ativas) {
    const cs = meus.filter((c) => c.status === status)
      .sort((x, y) => (PRIO[x.prioridade] ?? 3) - (PRIO[y.prioridade] ?? 3) || (x.numero || 0) - (y.numero || 0));
    lista.append(el('li', 'xp-secao', `${status} · ${cs.length}`));
    if (!cs.length) lista.append(el('li', 'vazio', 'Nenhum cartão.'));
    for (const c of cs) {
      const li = el('li', 'cartao'), topo = el('div', 'topo');
      li.style.borderLeftColor = corCss(a.cor);
      const num = el('a', null, c.numero ? '#' + c.numero : 'rascunho');
      if (c.url) { num.href = c.url; num.target = '_blank'; num.rel = 'noopener'; }
      topo.append(num);
      if (c.prioridade) { const p = el('span', 'prio', c.prioridade); p.style.background = cores[c.prioridade] || '#475569'; topo.append(p); }
      li.append(topo, el('div', 'resumo', c.titulo));
      lista.append(li);
    }
  }
  if (d.erro) lista.append(el('li', 'xp-linha dim', '⚠️ quadro de ' + (d.atualizado || '?') + ' (não consegui atualizar)'));
}
$('abaCartoes').hidden = !CONFIG.github.kanban;
window.addEventListener('kanban', (e) => {
  desenharQuadroKanban(e.detail);
  if (fichaAberta && abaFicha === 'cartoes') desenharFicha();
});
$('fichaFechar').addEventListener('click', fecharFicha);
document.querySelectorAll('#ficha .abas button').forEach((b) => b.addEventListener('click', () => { abaFicha = b.dataset.aba; desenharFicha(); }));
window.addEventListener('keydown', (e) => { if (e.key === 'Escape') fecharFicha(); });
// clique no boneco na cena 3D (ignora arrasto da câmera)
const raio = new THREE.Raycaster(), ponteiro = new THREE.Vector2();
// Toque: um dedo gira, dois dão zoom/arrastam (OrbitControls). Só vale como "toque no boneco" um dedo que não
// andou (tolerância maior no toque), foi rápido e não teve um segundo dedo no meio (pinça não abre ficha).
let apertou = null, dedos = new Set(), multitoque = false;
const el3d = renderer.domElement;
el3d.addEventListener('pointerdown', (e) => {
  dedos.add(e.pointerId);
  if (dedos.size > 1) { multitoque = true; apertou = null; return; }
  multitoque = false; apertou = { x: e.clientX, y: e.clientY, t: performance.now(), toque: e.pointerType !== 'mouse' };
});
const soltou = (e) => { dedos.delete(e.pointerId); if (!dedos.size) setTimeout(() => { multitoque = false; }, 0); };
el3d.addEventListener('pointercancel', (e) => { apertou = null; soltou(e); });
el3d.addEventListener('pointerup', (e) => {
  const a = apertou; apertou = null;
  const outro = multitoque; soltou(e);
  if (!a || outro) return;
  if (Math.hypot(e.clientX - a.x, e.clientY - a.y) > (a.toque ? 12 : 5) || performance.now() - a.t > 700) return;
  const r = el3d.getBoundingClientRect();
  ponteiro.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
  raio.setFromCamera(ponteiro, camera);
  const visivel = (o) => { for (; o; o = o.parent) if (!o.visible) return false; return true; };
  const acertos = raio.intersectObjects(cena.children, true).filter((i) => visivel(i.object));   // o raio do three acerta até o invisível
  let ag = (acertos.find((i) => i.object.userData.agente) || {}).object;
  ag = ag && ag.userData.agente;
  if (!ag && a.toque) {   // dedo gordo: o boneco mais perto do toque (até 40 px), medido na cabeça
    let melhor = 40;
    for (const x of ordemAgentes) {
      if (!x.fig || !x.fig.dentro || !x.fig.dentro.visible) continue;
      const p = x.pos.clone().add(new THREE.Vector3(0, 1.2, 0)).project(camera);
      const d = Math.hypot((p.x * 0.5 + 0.5) * r.width - (e.clientX - r.left), (-p.y * 0.5 + 0.5) * r.height - (e.clientY - r.top));
      if (p.z < 1 && d < melhor) { melhor = d; ag = x; }
    }
  }
  if (ag) { focarAgente(ag); abrirFicha(ag); }
  else if (acertos.length && acertos[0].object.userData.kanban && window.__kanban) window.__kanban.abrir();   // quadro da parede
});

// Foco de câmera
let foco = null;
function focarAgente(a) {
  const alvo = a.mesa.foco.clone();
  iniciarFoco(alvo, alvo.clone().add(new THREE.Vector3(0, 6, 9)));
}
function iniciarFoco(alvo, pos) {
  foco = { t0: agora(), de: camera.position.clone(), deAlvo: controles.target.clone(), pos, alvo };
}
$('btnVisao').addEventListener('click', () => iniciarFoco(VISAO_GERAL.alvo.clone(), posVisaoGeral()));

// ---------------------------------------------------------------- Eventos
function processar(ev, animar = true) {
  if (!ev || typeof ev !== 'object') return;
  const nome = normalizarNome(ev.agente) || 'Desconhecido';
  const tipo = String(ev.tipo || 'trabalho').toLowerCase();
  let para = ev.para; if (typeof para === 'string') para = [para];
  para = Array.isArray(para) ? para.map(normalizarNome).filter(Boolean) : [];
  const ferr = String(ev.ferramenta || ''), resumo = String(ev.resumo || '').trim();
  const a = garantirAgente(nome);
  para.filter((p) => p !== '*').forEach(garantirAgente);
  adicionarFeed(ev, a);
  if (!a) return;
  a.ultimoEvento = horaDe(ev);
  guardarHist(a, ev, 'fez');
  if (tipo === 'trabalho') a.agoraFaz = ev;
  else if (tipo === 'ocioso') a.agoraFaz = null;
  // comando longo em andamento (PreToolUse, `inicio`): o PostToolUse só chega no fim; até lá o agente segue trabalhando.
  // Qualquer outro evento do agente (o fim do comando, ocioso) encerra a espera.
  if (ev.inicio) {
    const resta = Math.min(Number(ev.espera_s) || 120, MAX_COMANDO) - (Date.now() - Date.parse(ev.ts)) / 1000;
    a.ocupadoAte = resta > 0 && resta <= MAX_COMANDO ? agora() + resta : 0;
  } else a.ocupadoAte = 0;
  if (!animar && a.ocupadoAte) { a.base = 'trabalhando'; a.ultimoTrabalho = agora(); a.estado = 'trabalhando'; }
  const recebem = para.includes('*') ? ordemAgentes.filter((x) => x !== a)
    : para.map((n) => agentes.get(n)).filter((x) => x && x !== a);
  if (tipo === 'fala' || tipo === 'reuniao') recebem.forEach((r) => guardarHist(r, ev, 'recebeu'));
  if (fichaAberta && (fichaAberta === a || recebem.includes(fichaAberta))) desenharFicha();
  if (!animar) return;
  const t = agora();
  if (tipo !== 'ocioso') interromperPausa(a);   // evento real: quem está em pausa volta à mesa antes de agir

  if (tipo === 'ocioso') {
    enfileirar(a, { t: 'fn', fn: () => { a.base = 'ocioso'; a.balao = null; if (!a.atual) a.estado = 'ocioso'; } });
  } else if (tipo === 'subagente') {
    const alvoNome = para.find((p) => p !== '*') || '';
    const temMesa = PERFIS[alvoNome.toLowerCase()] && alvoNome.toLowerCase() !== 'outra_sessao';
    const dest = temMesa ? agentes.get(alvoNome) : null;
    if (dest && dest !== a) {
      falar(a, dest, 'tarefa: ' + (resumo || 'nova tarefa'), ferr);
      interromperPausa(dest);
      enfileirar(dest, { t: 'fn', fn: () => { dest.base = 'trabalhando'; dest.ultimoTrabalho = agora(); balao(dest, resumo || 'nova tarefa', ferr); } });
    } else {
      criarSubagente(a, resumo || ferr || 'tarefa', ferr, alvoNome, ev.funcao);
    }
  } else if (tipo === 'reuniao' || (tipo === 'fala' && (para.includes('*') || para.filter((p) => p !== nome).length >= 2))) {
    let nomes = para.includes('*') || !para.length
      ? ordemAgentes.map((x) => x.nome).filter((n) => DO_TIME.has(n) && !FORA_DA_REUNIAO.has(n)) : [nome, ...para];
    const part = [...new Set(nomes)].map((n) => agentes.get(n)).filter(Boolean).slice(0, 8);
    if (!part.includes(a)) part.unshift(a);
    reuniao(part, a, resumo || 'reunião', ferr);
  } else if (tipo === 'fala') {
    const dest = agentes.get(para.find((p) => p !== nome) || '');
    // líder chamando 2+ colegas em sequência (uma mensagem para cada) = reunião na sala
    a.convocados = (a.convocados || []).filter((c) => t - c.t < JANELA_CONVOCACAO && c.dest !== dest);
    if (dest && !FORA_DA_REUNIAO.has(dest.nome)) a.convocados.push({ dest, t });
    if (a.nome === LIDER && a.convocados.length >= 2) {
      reuniao([a, ...a.convocados.map((c) => c.dest)], a, resumo || 'reunião', ferr);
      a.convocados = [];
    } else {
      falar(a, dest, resumo || 'mensagem', ferr);
    }
  } else { // trabalho (e qualquer tipo desconhecido)
    const ultimo = a.fila[a.fila.length - 1];
    const acao = { t: 'fn', trab: true, fn: () => {
      a.base = 'trabalhando'; a.ultimoTrabalho = agora(); if (!a.atual) a.estado = 'trabalhando';
      balao(a, resumo || ferr || 'trabalhando', ferr);
    } };
    if (ultimo && ultimo.trab) a.fila[a.fila.length - 1] = acao; else enfileirar(a, acao);
  }
}

// ---------------------------------------------------------------- Fonte de eventos: servidor ou demonstração
let desde = 0, iniciou = false, demoForcada = false, demoAuto = false, falhas = 0;
const selo = $('selo'), btnDemo = $('btnDemo');
function atualizarSelo() {
  const ativo = demoForcada || demoAuto;
  selo.hidden = !ativo; btnDemo.classList.toggle('ativo', demoForcada);
}
btnDemo.addEventListener('click', () => { demoForcada = !demoForcada; atualizarSelo(); });
$('btnApelidos').addEventListener('click', () => {
  modoApelido = MODOS_APELIDO[(MODOS_APELIDO.indexOf(modoApelido) + 1) % MODOS_APELIDO.length];
  try { localStorage.setItem('office.apelidos', modoApelido); } catch (e) {}
  aplicarApelidos();
});
$('btnApelidos').textContent = ROTULO_MODO[modoApelido];
$('tituloEscritorio').textContent = CONFIG.titulo;

let pollTimer = null, pollando = false;
async function poll() {
  if (pollando) return;
  pollando = true;
  try {
    if (!iniciou) {
      const r = await fetch('/eventos?desde=0&ultimos=' + MAX_FEED, { cache: 'no-store' });
      const j = await r.json();
      (j.eventos || []).forEach((e) => processar(e, false));
      desde = j.total || 0; iniciou = true;
    } else {
      const r = await fetch('/eventos?desde=' + desde, { cache: 'no-store' });
      const j = await r.json();
      if (typeof j.total === 'number') {
        if (j.total < desde) desde = 0; else { (j.eventos || []).forEach((e) => processar(e, true)); desde = j.total; }
      }
    }
    falhas = 0; demoAuto = false;
  } catch (e) {
    falhas++; if (falhas >= 1) demoAuto = true;
  }
  atualizarSelo();
  pollando = false;
  pollTimer = setTimeout(poll, document.hidden ? INTERVALO_POLL_OCULTO : INTERVALO_POLL);
}

// Demonstração: eventos falsos plausíveis
const agoraIso = () => { const d = new Date(); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 19); };
const demoEv = (agente, tipo, ferramenta, resumo, para = []) => {
  // na demonstração, poupa quem está em pausa (na maior parte das vezes) para dar tempo de ver comer, jogar e conversar
  if (tipo !== 'ocioso') {
    const envolvidos = [agente, ...para].map((n) => agentes.get(normalizarNome(n))).filter(Boolean);
    const emPausa = tipo === 'reuniao' ? ordemAgentes.filter((x) => x.pausa).length >= 2 : envolvidos.some((x) => x.pausa);
    if (emPausa && Math.random() < 0.8) return;
  }
  processar({ ts: agoraIso(), agente, tipo, para, ferramenta, resumo });
};
// os papéis da demonstração: o líder e os 3 primeiros colegas do config (repete se houver menos)
const COLEGAS_DEMO = AGENTES_CFG.filter((a) => a.nome !== LIDER);
const D = (i) => (COLEGAS_DEMO.length ? COLEGAS_DEMO[i % COLEGAS_DEMO.length].nome : LIDER);
const L = LIDER, DV = D(0), DS = D(1), PQ = D(2);
const roteiros = [
  () => { demoEv(L, 'fala', 'SendMessage', 'Pegue a tarefa: corrigir o login quebrado', [DV]);
    setTimeout(() => demoEv(DV, 'trabalho', 'Read', 'lê auth_service.py'), 9000);
    setTimeout(() => demoEv(DV, 'trabalho', 'Bash', 'Rodando a suíte de testes'), 14000);
    setTimeout(() => demoEv(DV, 'fala', 'SendMessage', 'Testes passando, tarefa pronta', [L]), 24000); },
  () => demoEv(DS, 'trabalho', 'Edit', 'edita tela_inicial.css'),
  () => demoEv(PQ, 'trabalho', 'WebSearch', 'pesquisando a documentação da API'),
  () => demoEv(DV, 'trabalho', 'Edit', 'edita api/rotas.ts'),
  () => demoEv(DV, 'subagente', 'Task', 'Revisando os imports do módulo'),
  () => demoEv(L, 'trabalho', 'Grep', 'conferindo tarefas pendentes'),
  () => demoEv(DS, 'fala', 'SendMessage', 'Protótipo da tela pronto para revisão', [PQ]),
  () => demoEv(L, 'reuniao', 'SendMessage', 'Alinhamento rápido da sprint', []),
  () => demoEv(PQ, 'ocioso', '', 'aguardando'),
  () => demoEv(DS, 'subagente', 'Task', 'Otimizando as imagens'),
];
let proxDemo = 0, nDemo = 0;
function tickDemo(t) {
  if (!(demoForcada || demoAuto) || t < proxDemo) return;
  proxDemo = t + 2.5 + Math.random() * 3;
  nDemo++;
  if (nDemo === 1) return roteiros[0]();
  if (nDemo % 14 === 0) return roteiros[7]();
  if (nDemo % 5 === 3) { // dois agentes livres vão juntos ao ping-pong ou ao mesmo lugar de pausa (para conversar)
    const livres = ordemAgentes.filter((x) => !x.pausa && !x.atual && !x.fila.length && x.sentado).sort(() => Math.random() - 0.5);
    if (livres.length >= 2) {
      if (Math.random() < 0.5) iniciarPartida(livres[0], livres[1]);
      else { const l = Math.random() < 0.5 ? 'descanso' : 'refeitorio'; iniciarPausa(livres[0], l); iniciarPausa(livres[1], l); }
    }
  }
  if (nDemo % 4 === 0) return demoEv(ordemAgentes[Math.floor(Math.random() * ordemAgentes.length)].nome, 'ocioso', '', 'aguardando');
  roteiros[1 + Math.floor(Math.random() * (roteiros.length - 1))]();
}

// ---------------------------------------------------------------- Loop principal
let anterior = agora();
let oculto = document.hidden;
document.addEventListener('visibilitychange', () => {
  oculto = document.hidden;
  if (!oculto) { anterior = agora(); clearTimeout(pollTimer); poll(); }   // voltou: não acumula tempo e atualiza já
});
function quadro() {
  requestAnimationFrame(quadro);
  if (oculto) return;   // aba oculta: não gasta bateria desenhando
  const t = agora(), dt = Math.min(0.1, t - anterior); anterior = t;
  tickDemo(t);
  tickSocial(t); tickConfete(dt);
  for (const a of ordemAgentes) atualizarAgente(a, dt, t);
  for (const s of subagentes.slice()) {
    const idade = t - s.nasc;
    if (idade > TEMPO_SUBAGENTE) { removerSubagente(s); continue; }
    s.fig.dentro.position.y = Math.abs(Math.sin(t * 3 + s.fase)) * 0.05;
    s.bal.sprite.visible = idade < 6;
    const aparece = Math.min(1, idade * 3, (TEMPO_SUBAGENTE - idade) * 2);
    s.fig.raiz.scale.setScalar(0.6 * Math.max(0.05, aparece));
  }
  if (foco) {
    const k = Math.min(1, (t - foco.t0) / 1.0), e = k * k * (3 - 2 * k);
    camera.position.lerpVectors(foco.de, foco.pos, e);
    controles.target.lerpVectors(foco.deAlvo, foco.alvo, e);
    if (k >= 1) foco = null;
  }
  controles.update();
  atualizarPainel();
  atualizarResumo();
  renderer.render(cena, camera);
}
requestAnimationFrame(quadro);
poll();
window.__office = { agentes, processar, ficha: (nome, aba) => { const a = agentes.get(normalizarNome(nome)); if (!a) return false; if (aba) abaFicha = aba; focarAgente(a); abrirFicha(a); return true; }, xpDefinir, comemorar, emDemo, CORES_NIVEL, estrelas, progressoXp, atualizarFicha: () => desenharFicha(), camera, controles, iniciarFoco, VISAO_GERAL, SLOTS,
  pausar: (nome, lugar) => { const a = agentes.get(normalizarNome(nome)); return !!a && !a.atual && !a.fila.length && a.sentado && iniciarPausa(a, lugar); },
  pingpong: (n1, n2) => { const a = agentes.get(normalizarNome(n1)), b = agentes.get(normalizarNome(n2)); return !!a && !!b && iniciarPartida(a, b); },
  voltar: (nome) => interromperPausa(agentes.get(normalizarNome(nome))),
  avancar: (seg) => { for (let k = 0; k < seg / 0.05; k++) { saltoRelogio += 0.05; const t = agora(); tickDemo(t); tickSocial(t); for (const a of ordemAgentes) atualizarAgente(a, 0.05, t); } } }; // ajuda para depuração
