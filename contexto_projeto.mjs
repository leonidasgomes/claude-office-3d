// Referências somente leitura. Todo conteúdo externo é texto, nunca HTML.
const texto = (v, n = 500) => String(v ?? '').slice(0, n);
const data = v => { const d = new Date(v); return Number.isFinite(d.getTime()) ? d.toLocaleString('pt-BR') : 'não informada'; };
const linkPR = v => typeof v === 'string' && /^https:\/\/github\.com\/[A-Za-z0-9][A-Za-z0-9-]{0,99}\/[A-Za-z0-9_.-]{1,100}\/pull\/[1-9][0-9]{0,9}$/.test(v) && !['.', '..'].includes(v.split('/')[4]);

export function criarContextoProjeto() {
  const criar = (tag, valor, pai) => {
    const el = document.createElement(tag);
    if (valor != null) el.textContent = valor;
    pai?.append(el); return el;
  };
  const painel = criar('dialog', null, document.body);
  painel.className = 'gestaoPainel contextoProjeto';
  painel.setAttribute('aria-label', 'Pesquisar contexto do projeto');
  const topo = criar('header', null, painel); topo.className = 'gestaoCabecalho';
  const titulo = criar('h2', 'Contexto do projeto', topo);
  const fechar = criar('button', 'Fechar contexto', topo); fechar.type = 'button';
  const corpo = criar('div', null, painel); corpo.className = 'gestaoCorpo';
  criar('p', 'Consulte documentos canônicos atuais e referências de merges registrados. Histórico não substitui regras atuais nem comprova aceite do usuário.', corpo);
  const form = criar('form', null, corpo);
  const label = criar('label', 'Buscar neste projeto ', form);
  const campo = criar('input', null, label); campo.type = 'search'; campo.maxLength = 160;
  campo.minLength = 2; campo.required = true; campo.autocomplete = 'off';
  const buscar = criar('button', 'Pesquisar', form); buscar.type = 'submit';
  const estado = criar('p', null, corpo); estado.setAttribute('role', 'status');
  const resultados = criar('div', null, corpo);
  let projeto = '', geracao = 0, controller = null, retorno = null;
  function limpar() {
    geracao++; controller?.abort(); controller = null; buscar.disabled = false;
    resultados.replaceChildren(); estado.textContent = '';
  }
  function encerrar() {
    limpar(); campo.value = '';
    if (painel.open) painel.close();
    if (retorno?.isConnected) retorno.focus();
  }
  fechar.addEventListener('click', encerrar);
  painel.addEventListener('cancel', e => { e.preventDefault(); encerrar(); });
  painel.addEventListener('close', () => { if (!painel.open) { limpar(); campo.value = ''; } });
  async function pesquisar(e) {
    e?.preventDefault();
    const consulta = campo.value.trim();
    limpar();
    if (!painel.open || !/^[0-9a-f]{20}$/.test(projeto)) return;
    if (consulta.length < 2 || consulta.length > 160) { estado.textContent = 'Digite de 2 a 160 caracteres.'; return; }
    const atual = geracao, id = projeto;
    controller = new AbortController(); const req = controller;
    buscar.disabled = true; estado.textContent = 'Pesquisando fontes deste projeto…';
    try {
      const resposta = await fetch(`/api/gestao/contexto?projeto=${encodeURIComponent(id)}&q=${encodeURIComponent(consulta)}`,
        { cache: 'no-store', signal: req.signal });
      if (resposta.status === 403) throw new Error('Consulta disponível somente no PC do escritório.');
      if (!resposta.ok) throw new Error('Consulta indisponível. Confira o projeto ou tente novamente.');
      const dados = await resposta.json();
      if (atual !== geracao || projeto !== id || !painel.open) return;
      if (!dados.ok || dados.projeto_id !== id || !Array.isArray(dados.resultados) || !Array.isArray(dados.fontes))
        throw new Error('Resposta não corresponde ao projeto consultado.');
      estado.textContent = dados.resultados.length ? `${Math.min(dados.resultados.length, 20)} referência(s) encontrada(s).` : 'Nenhuma referência encontrada nas fontes consultadas.';
      criar('p', texto(dados.limite, 1000), resultados);
      if (dados.limitado || dados.resultados.length > 20) criar('p', 'Cobertura parcial: fontes ou histórico podem não ter sido pesquisados por completo.', resultados);
      for (const fonte of dados.fontes.slice(0, 4)) {
        const nome = fonte.tipo === 'entrega' ? 'Histórico de entregas' : `Documento: ${texto(fonte.papel, 40)}`;
        criar('p', `${nome} · ${fonte.estado === 'disponivel' ? 'consultado' : 'indisponível ou excluído; não pesquisado'}${fonte.omitidos ? ' · registros inválidos ou excluídos foram omitidos' : ''}`, resultados);
        if (fonte.motivo === 'repositorio_nao_configurado') criar('p', 'Histórico não pesquisado: este projeto não tem repositório configurado.', resultados);
      }
      for (const hit of dados.resultados.slice(0, 20)) {
        const card = criar('article', null, resultados); card.className = 'gestaoCadastro';
        criar('h3', texto(hit.fonte, 240), card);
        const documental = hit.tipo === 'documento';
        criar('p', documental ? `Documento canônico · ${texto(hit.papel, 40)} · snapshot da árvore de trabalho atual` : 'Entrega com merge registrado · não comprova aceite do usuário', card);
        criar('p', `${documental ? 'SHA-256 do conteúdo' : 'Commit de merge'}: ${texto(hit.revisao, 64)}`, card);
        criar('p', `${documental ? 'Modificação local' : 'Merge registrado'}: ${data(hit.data)} · Linha ${texto(hit.linha, 12)}`, card);
        if (!documental) {
          criar('p', `Head: ${texto(hit.head, 40)} · Objetivo GDD: ${texto(hit.objetivo_gdd, 20)} · GDD SHA-256: ${texto(hit.gdd_sha256, 64)}`, card);
          criar('p', `Proveniência: conclusão registrada · Evidência SHA-256: ${texto(hit.evidencia_sha256, 64)}`, card);
        }
        criar('pre', texto(hit.trecho, 400), card);
        if (hit.trecho_truncado) criar('p', 'Trecho limitado.', card);
        if (!documental && linkPR(hit.url)) {
          const link = criar('a', 'Abrir PR de origem', card);
          link.href = hit.url; link.target = '_blank'; link.rel = 'noopener noreferrer';
        }
      }
    } catch (erro) {
      if (atual === geracao && painel.open) estado.textContent = texto(erro.message);
    } finally {
      if (atual === geracao) { buscar.disabled = false; controller = null; }
    }
  }
  form.addEventListener('submit', pesquisar);
  return {
    get aberta() { return painel.open; },
    fechar: encerrar,
    abrir(id, nome = id, origem = null) {
      limpar(); campo.value = ''; projeto = id; retorno = origem;
      titulo.textContent = `Contexto do projeto · ${texto(nome, 200)}`;
      estado.textContent = 'Busca sob demanda nas fontes configuradas. Digite um termo para começar.';
      if (!painel.open) painel.showModal();
      campo.focus();
    },
  };
}
