import { LOCAL } from './movel.js';

const botao = document.getElementById('btnProvedores');
const el = (tag, texto) => {
  const n = document.createElement(tag);
  if (texto !== undefined) n.textContent = texto;
  return n;
};
async function api(url, dados) {
  const r = await fetch(url, dados ? { method: 'POST', headers: {
    'Content-Type': 'application/json', 'X-Office-Acao': '1'
  }, body: JSON.stringify(dados) } : { cache: 'no-store' });
  const j = await r.json();
  if (!r.ok || !j.ok) throw new Error(j.erro || 'HTTP ' + r.status);
  return j;
}

if (LOCAL && botao) {
  botao.hidden = false;
  const painel = el('dialog');
  painel.setAttribute('aria-label', 'Ferramentas e modelos');
  painel.style.cssText = 'width:min(640px,90vw);max-height:85vh;overflow:auto;background:#161c24;color:#eee;border:1px solid #65758a;border-radius:12px;padding:20px';
  const titulo = el('h2', '▶ Ferramentas e modelos');
  const fechar = el('button', 'Fechar'); fechar.type = 'button';
  const form = el('form');
  const ferramenta = el('select'), mesa = el('select'), modelo = el('input'), prompt = el('textarea');
  modelo.maxLength = 160; modelo.placeholder = 'Vazio usa o padrão da ferramenta';
  prompt.required = true; prompt.maxLength = 12000; prompt.rows = 6;
  const dica = el('p');
  function campo(nome, input) {
    const label = el('label', nome);
    label.style.cssText = 'display:block;margin:12px 0';
    input.style.cssText = 'display:block;width:100%;box-sizing:border-box;margin-top:6px;background:#0f1419;color:#eee;border:1px solid #65758a;border-radius:6px;padding:9px;font:inherit';
    label.append(input); return label;
  }
  const iniciar = el('button', '▶ Executar tarefa'); iniciar.type = 'submit';
  const status = el('p'); status.setAttribute('role', 'status');
  const tarefas = el('div');
  form.append(campo('Ferramenta', ferramenta), campo('Mesa do agente', mesa), campo('Modelo', modelo), dica,
    campo('Tarefa', prompt), iniciar);
  painel.append(titulo, fechar, el('p', 'Use o login e as permissões da CLI. Cada execução é uma tarefa independente. O time automático do Claude continua no lançador existente.'), form, status, tarefas);
  document.body.append(painel);
  let timer = null;
  const dicas = {
    claude: 'Claude Code: deixe o modelo vazio para usar seu padrão. Login: claude.',
    ollama: 'Ollama local: informe um modelo instalado, por exemplo qwen3.5:4b. Uma tarefa local por vez. O servidor Ollama precisa estar ligado.',
    codex: 'OpenAI: use um modelo disponível na sua conta ou deixe vazio. Login: codex login.',
    gemini: 'Gemini: use um modelo disponível na sua conta ou deixe vazio. Login: gemini.',
    opencode: 'OpenCode: modelo no formato provedor/modelo. Login: opencode auth login. Também permite outros provedores configurados na CLI.'
  };
  function atualizarDica() {
    dica.textContent = dicas[ferramenta.value] || '';
    modelo.required = ferramenta.value === 'ollama';
    modelo.value = localStorage.getItem('office-modelo-' + ferramenta.value) || '';
  }
  ferramenta.addEventListener('change', atualizarDica);
  async function atualizar() {
    try {
      const j = await api('/api/provedores/tarefas');
      tarefas.replaceChildren();
      for (const t of [...j.tarefas].reverse()) {
        const box = el('section');
        box.append(el('h3', `${t.mesa} · ${t.provedor} · ${t.estado}`));
        if (t.estado === 'executando' || t.estado === 'cancelando') {
          const cancelar = el('button', 'Parar tarefa'); cancelar.type = 'button';
          cancelar.onclick = async () => {
            cancelar.disabled = true;
            try { await api('/api/provedores/cancelar', { id: t.id }); await atualizar(); }
            catch (e) { status.textContent = e.message; cancelar.disabled = false; }
          };
          box.append(cancelar);
        }
        const resultado = el('pre', t.erro || t.resultado || 'Aguardando resposta da ferramenta…');
        resultado.style.cssText = 'white-space:pre-wrap;overflow-wrap:anywhere;max-height:250px;overflow:auto';
        box.append(resultado); tarefas.append(box);
      }
    } catch (e) { status.textContent = e.message; }
  }
  botao.onclick = async () => {
    try {
      const j = await api('/api/provedores');
      ferramenta.replaceChildren(); mesa.replaceChildren();
      for (const p of j.provedores) {
        const o = el('option', p.nome + (p.instalado ? '' : ' · CLI não encontrada'));
        o.value = p.id; o.disabled = !p.instalado; ferramenta.append(o);
      }
      for (const m of j.mesas) { const o = el('option', m); o.value = m; mesa.append(o); }
      const salvo = localStorage.getItem('office-ferramenta');
      if (j.provedores.some(p => p.id === salvo && p.instalado)) ferramenta.value = salvo;
      atualizarDica(); status.textContent = j.projeto_configurado ? '' : 'Configure uma pasta em projetos no config.json antes de executar.';
      iniciar.disabled = !j.projeto_configurado;
      painel.showModal(); await atualizar(); timer = setInterval(atualizar, 3000);
    } catch (e) { painel.showModal(); status.textContent = e.message; }
  };
  fechar.onclick = () => painel.close();
  painel.addEventListener('close', () => { clearInterval(timer); timer = null; });
  form.onsubmit = async (e) => {
    e.preventDefault(); iniciar.disabled = true;
    try {
      await api('/api/provedores/iniciar', { provedor: ferramenta.value, mesa: mesa.value,
        modelo: modelo.value.trim(), prompt: prompt.value });
      localStorage.setItem('office-ferramenta', ferramenta.value);
      localStorage.setItem('office-modelo-' + ferramenta.value, modelo.value.trim());
      status.textContent = 'Tarefa iniciada. Acompanhe o resultado aqui e os eventos na mesa.';
      await atualizar();
    } catch (erro) { status.textContent = erro.message; }
    finally { iniciar.disabled = false; }
  };
}
