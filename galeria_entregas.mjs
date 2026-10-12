// Somente leitura. O servidor lê os blobs do commit registrado, nunca o worktree.
const MAX_ITENS = 100, MAX_ARQUIVOS = 100, MAX_TEXTO = 200000, MAX_CONTEUDO = 24 * 1024 * 1024;
const texto = (valor, limite = 500) => String(valor ?? 'não registrado').slice(0, limite);
const estadoLegivel = valor => ({nao_registrada:'não registrada',nao_registrado:'não registrado',nao_informada:'não informada',nao_comprovado:'não comprovado',sem_retorno:'sem retorno registrado',sem_aprovacao:'sem aprovação',falha_console:'falha do console',sem_entrega:'sem entrega',revisao_aprovada:'revisão aprovada',revisao_desativada:'revisão desativada',revisao_reprovada:'revisão reprovada',gate_bloqueado:'gate bloqueado'}[valor] || texto(valor));
const dataRegistro = valor => { const d = new Date(typeof valor === 'number' ? valor * 1000 : valor); return Number.isFinite(d.getTime()) ? d.toLocaleString('pt-BR') : 'não informada'; };
const imagemSegura = mime => /^(image\/png|image\/jpeg|image\/gif|image\/webp)$/.test(mime);

export function criarGaleriaEntregas() {
  const painel = document.createElement('dialog');
  painel.className = 'gestaoPainel galeriaEntregas';
  painel.setAttribute('aria-label', 'Galeria de entregas');
  const criar = (tag, valor, pai) => {
    const el = document.createElement(tag);
    if (valor != null) el.textContent = valor;
    pai?.append(el); return el;
  };
  const topo = criar('header', null, painel); topo.className = 'gestaoCabecalho';
  const titulo = criar('h2', 'Galeria de entregas', topo);
  const fechar = criar('button', 'Fechar galeria', topo); fechar.type = 'button';
  const corpo = criar('div', null, painel); corpo.className = 'gestaoCorpo';
  corpo.setAttribute('aria-live', 'polite');
  document.body.append(painel);
  let geracao = 0, projeto = '', retorno = null;
  const requisicoes = new Set(), urls = new Set();
  function limpar() {
    geracao++;
    for (const req of requisicoes) req.abort();
    requisicoes.clear();
    for (const url of urls) URL.revokeObjectURL(url);
    urls.clear();
  }
  function encerrar() {
    limpar(); corpo.replaceChildren();
    if (painel.open) painel.close();
    if (retorno?.isConnected) retorno.focus();
  }
  fechar.addEventListener('click', encerrar);
  painel.addEventListener('cancel', e => { e.preventDefault(); encerrar(); });
  // O evento close pode chegar depois de uma reabertura rápida do dialog.
  painel.addEventListener('close', () => { if (!painel.open) { limpar(); corpo.replaceChildren(); } });
  async function consulta(url) {
    const controller = new AbortController(); requisicoes.add(controller);
    try {
      const r = await fetch(url, { cache: 'no-store', signal: controller.signal });
      if (r.status === 403) throw new Error('Acesso permitido somente no PC do escritório.');
      if (!r.ok) throw new Error(`Servidor respondeu ${r.status}.`);
      const dados = await r.json();
      if (!dados.ok) throw new Error(texto(dados.erro || 'Resposta indisponível.'));
      return dados;
    } finally { requisicoes.delete(controller); }
  }
  function mostrar(dados, historico = false) {
    limpar(); const atual = geracao;
    corpo.replaceChildren();
    criar('p', 'Versões registradas no manifesto da tentativa e vinculadas ao commit. Não é uma busca em todos os arquivos do projeto.', corpo);
    criar('p', 'Execução, revisão e merge são registros separados. Integridade dos bytes não comprova qualidade, aprovação visual ou aceite do usuário. Ausência de registro não significa aprovação.', corpo);
    const alternar = criar('button', historico ? 'Ocultar histórico arquivado' : 'Mostrar histórico arquivado', corpo);
    alternar.type = 'button'; alternar.setAttribute('aria-pressed', String(historico));
    alternar.addEventListener('click', () => mostrar(dados, !historico));
    const todos = dados.itens.slice(0, MAX_ITENS), itens = todos.filter(i => historico || !i.arquivada);
    criar('p', `${itens.length} entrega(s) exibida(s)${historico ? ', incluindo histórico arquivado' : ''}.`, corpo);
    if (dados.limitado || dados.itens.length > MAX_ITENS) criar('p', 'Lista limitada aos registros retornados mais recentes. O histórico pode estar incompleto.', corpo);
    if (!itens.length) criar('p', 'Nenhuma entrega registrada nesta seleção. Arquivos fora do manifesto não aparecem aqui.', corpo);
    for (const item of itens) {
      const card = criar('article', null, corpo); card.className = 'gestaoCadastro';
      criar('h3', `Cartão ${texto(item.cartao)} · tentativa ${texto(item.tentativa)}`, card);
      criar('p', `Manifesto ${texto(item.id)}${item.arquivada ? ' · Arquivada (histórico)' : ''} · Registro: ${dataRegistro(item.criado)}`, card);
      criar('p', `PR ${texto(item.pr)} · Commit ${texto(item.sha)}`, card);
      criar('p', `Execução: ${estadoLegivel(item.execucao?.estado)} · código: ${texto(item.execucao?.codigo)} · resultado: ${estadoLegivel(item.execucao?.resultado)}`, card);
      criar('p', `Revisão: ${estadoLegivel(item.revisao?.estado)} · Merge: ${estadoLegivel(item.merge?.estado)}`, card);
      criar('p', `Aprovação visual: ${estadoLegivel(item.aprovacao_visual)} · Aceite do usuário: ${estadoLegivel(item.aceite_usuario)}`, card);
      const arquivos = Array.isArray(item.arquivos) ? item.arquivos : [];
      if (!arquivos.length) criar('p', 'Manifesto sem arquivos registrados.', card);
      if (arquivos.length > MAX_ARQUIVOS) criar('p', 'Exibição limitada a 100 arquivos deste manifesto.', card);
      for (const arquivo of arquivos.slice(0, MAX_ARQUIVOS)) {
        const grupo = criar('section', null, card);
        criar('h4', texto(arquivo.nome), grupo);
        criar('p', `${texto(arquivo.mime)} · ${texto(arquivo.tamanho)} bytes · SHA-256: ${texto(arquivo.sha256)}`, grupo);
        const estado = criar('p', 'Integridade: ainda não consultada.', grupo);
        const preview = criar('div', null, grupo); preview.className = 'galeriaPreview';
        const ver = criar('button', 'Visualizar', grupo); ver.type = 'button';
        ver.hidden = !['texto', 'imagem'].includes(arquivo.preview);
        const baixar = criar('button', 'Baixar versão registrada', grupo); baixar.type = 'button';
        let ocupado = false, urlImagem = null;
        async function carregarArquivo(download) {
          if (ocupado || atual !== geracao || !painel.open) return;
          ocupado = true; ver.disabled = baixar.disabled = true;
          estado.textContent = 'Verificando arquivo registrado…';
          try {
            const dado = await consulta(`/api/gestao/entregas/arquivo?projeto=${encodeURIComponent(projeto)}&arquivo=${encodeURIComponent(arquivo.id)}`);
            if (atual !== geracao || !painel.open) return;
            if (dado.sha256 !== arquivo.sha256 || dado.tamanho !== arquivo.tamanho || dado.nome !== arquivo.nome || dado.mime !== arquivo.mime || dado.preview !== arquivo.preview)
              throw new Error('Resposta não corresponde à versão registrada.');
            if (typeof dado.conteudo !== 'string' || dado.conteudo.length > MAX_CONTEUDO) throw new Error('Conteúdo ausente ou acima do limite de visualização.');
            const bytes = dado.preview === 'texto' ? new TextEncoder().encode(dado.conteudo) : Uint8Array.from(atob(dado.conteudo), c => c.charCodeAt(0));
            if (bytes.byteLength !== dado.tamanho) throw new Error('Tamanho diferente da versão registrada.');
            if (download) {
              const url = URL.createObjectURL(new Blob([bytes], { type: 'application/octet-stream' })); urls.add(url);
              const link = criar('a', null, grupo); link.href = url;
              link.download = texto(dado.nome).split(/[\\/]/).pop() || 'entrega';
              link.click(); link.remove();
              setTimeout(() => { if (urls.delete(url)) URL.revokeObjectURL(url); }, 1000);
            } else {
              preview.replaceChildren();
              if (urlImagem) { URL.revokeObjectURL(urlImagem); urls.delete(urlImagem); urlImagem = null; }
              if (dado.preview === 'texto') {
                criar('pre', dado.conteudo.slice(0, MAX_TEXTO), preview);
                if (dado.conteudo.length > MAX_TEXTO) criar('p', 'Prévia truncada. Baixe para ler o arquivo completo.', preview);
              } else if (dado.preview === 'imagem' && imagemSegura(dado.mime)) {
                urlImagem = URL.createObjectURL(new Blob([bytes], { type: dado.mime })); urls.add(urlImagem);
                const img = criar('img', null, preview); img.alt = texto(dado.nome); img.src = urlImagem;
                img.addEventListener('error', () => { if (atual === geracao) estado.textContent = 'Bytes verificados; formato de imagem não pôde ser exibido.'; });
              } else throw new Error('Formato disponível somente para download.');
            }
            estado.textContent = 'Integridade: bytes verificados pelo servidor contra o SHA-256 registrado. Não constitui aceite.';
          } catch (e) {
            if (atual === geracao && painel.open) estado.textContent = `Arquivo indisponível: ${texto(e.message)}`;
          } finally { ocupado = false; ver.disabled = baixar.disabled = false; }
        }
        ver.addEventListener('click', () => carregarArquivo(false));
        baixar.addEventListener('click', () => carregarArquivo(true));
      }
    }
  }
  return {
    get aberta() { return painel.open; },
    fechar: encerrar,
    async abrir(id, nome = id, origem = null) {
      limpar(); const atual = geracao; projeto = id; retorno = origem;
      titulo.textContent = `Galeria de entregas · ${texto(nome)}`;
      corpo.replaceChildren(); criar('p', 'Consultando manifestos registrados…', corpo);
      if (!painel.open) painel.showModal();
      try {
        const dados = await consulta(`/api/gestao/entregas?projeto=${encodeURIComponent(id)}`);
        if (atual !== geracao || !painel.open) return;
        if (!Array.isArray(dados.itens)) throw new Error('Lista de entregas inválida.');
        mostrar(dados);
      } catch (e) {
        if (atual === geracao && painel.open) { corpo.replaceChildren(); criar('p', `Galeria indisponível: ${texto(e.message)}`, corpo); }
      }
    },
  };
}
