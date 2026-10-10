// Cotas pertencem à conta/fornecedor, nunca a um total ou ranking entre clouds.
export function linhasCota(p) {
  const nome = ({codex: 'GPT / Codex', claude: 'Claude', opencode: 'OpenCode', gemini: 'Gemini'})[p.provider] || p.provider;
  const linhas = [nome];
  if (p.erro) linhas.push(p.erro);
  if (p.coletado_em) linhas.push(`Leitura: ${new Date(p.coletado_em * 1000).toLocaleString('pt-BR')}${p.desatualizado ? ' · desatualizada' : ''}`);
  if (!p.disponivel) linhas.push('Cota não informada pelo console.');
  for (const limite of p.limites || []) {
    for (const j of limite.janelas || []) {
      const janela = j.duracao_min === 10080 ? 'semana' : `${j.duracao_min ?? '?'} minutos`;
      const pct = Number.isFinite(j.usado_pct) ? `${j.usado_pct}% usado` : 'uso indisponível';
      const restante = Number.isFinite(j.restante_pct) ? ` · ${j.restante_pct}% restante` : '';
      const reset = j.renova_em ? new Date(j.renova_em * 1000).toLocaleString('pt-BR') : 'não informada';
      linhas.push(`${limite.nome} · ${janela}: ${pct}${restante} · renovação: ${reset}${j.expirado ? ' · leitura anterior à renovação' : ''}`);
    }
  }
  return linhas;
}

export function linhasConsumo(consumo) {
  if (consumo?.erro) return [consumo.erro];
  const linhas = [];
  for (const g of consumo?.grupos || []) {
    const contador = (valor, cobertura) => valor == null ? 'não informado' :
      `${valor.toLocaleString('pt-BR')}${cobertura < g.amostras ? ' (parcial)' : ''}`;
    const agente=g.agente_nome || (/^Office_[0-9a-f]{32}$/.test(g.agente) ? 'Especialista sem cadastro disponível' : g.agente);
    const namespace = g.provider === 'opencode' || g.provider === 'opencode_local' ?
      ` · provider do modelo: ${g.provider_modelo || 'não informado'} (${g.origem_provider_modelo || 'não informado'})` : '';
    linhas.push(`${g.provider} · ${g.modelo} (${g.origem_modelo})${namespace} · ${agente}: entrada ${contador(g.entrada, g.com_entrada)}, saída ${contador(g.saida, g.com_saida)}, total ${contador(g.total, g.com_total)} tokens · ${g.amostras} amostra(s).`);
    if (typeof g.equivalente_api_usd === 'string' && /^\d+(\.\d+)?$/.test(g.equivalente_api_usd) && Number.isSafeInteger(g.com_preco) && g.com_preco > 0 && g.com_preco <= g.amostras) {
      linhas.push(`Equivalente teórico de API: USD ${g.equivalente_api_usd} · ${g.com_preco}/${g.amostras} amostras com preço${g.com_preco < g.amostras ? ' · parcial' : ''}. Não é cobrança da assinatura nem fatura.`);
    } else {
      linhas.push('Equivalente teórico de API: não informado.');
    }
  }
  if (!linhas.length) linhas.push('Nenhum consumo observado nos últimos 7 dias pelos fluxos integrados.');
  linhas.push('Consultas do CEO e diretor entram nos respectivos papéis. Claude inclui consultas isoladas e sessões cloud novas do launcher, além dos incrementos de retomadas com saldo por projeto/sessão/modelo. Retomada sem baseline: o primeiro agregado apenas estabelece referência e não entra no consumo; há lacuna até essa leitura. TUI, local e outras sessões/team permanecem fora. Esse detalhamento não representa todo o uso da conta. Agregado de filhos pertence ao papel da sessão principal, sem somá-los novamente.');
  if (consumo?.precos?.estado === 'catálogo inválido') linhas.push('Catálogo de preços inválido: cálculo suspenso; contadores preservados.');
  linhas.push('Preços dependem de catálogo configurado e modelo informado pelo console; cálculo usa a validade de cada tarifa. Cobrança real não integrada. Cache integra a entrada normalizada; não é somado novamente. OpenCode inclui raciocínio na saída normalizada. Provider/modelo configurado não comprova o backend real.');
  return linhas;
}

// Somente o histórico observado entra no resumo; cotas não são unidade de consumo.
export function linhasVisaoGeral(consumo) {
  if (consumo?.erro) return ['Resumo de consumo indisponível.'];
  const recebidos = consumo?.grupos;
  if (recebidos != null && (!Array.isArray(recebidos) || recebidos.some(g =>
      !g || !Number.isSafeInteger(g.amostras) || g.amostras <= 0))) {
    return ['Resumo de consumo indisponível: cobertura inválida.'];
  }
  const grupos = recebidos || [];
  if (!grupos.length) return ['Sem consumo observado para resumir nos últimos 7 dias.'];
  const linhas = [];
  for (const local of [false, true]) {
    const itens = grupos.filter(g => String(g.provider).endsWith('_local') === local);
    if (!itens.length) continue;
    const amostras = itens.reduce((n, g) => n + BigInt(g.amostras), 0n);
    const contagem = (campo, cobertura) => {
      let valor = 0n, presentes = 0n;
      for (const g of itens) {
        // Totais inválidos ou sem cobertura comprovada permanecem desconhecidos.
        if (Number.isSafeInteger(g[campo]) && g[campo] >= 0 &&
            Number.isSafeInteger(g[cobertura]) && g[cobertura] > 0 && g[cobertura] <= g.amostras) {
          valor += BigInt(g[campo]); presentes += BigInt(g[cobertura]);
        }
      }
      if (!presentes) return 'não informado';
      return `${valor.toLocaleString('pt-BR')} (${presentes.toLocaleString('pt-BR')}/${amostras.toLocaleString('pt-BR')} amostras com dado${presentes < amostras ? ' · parcial' : ''})`;
    };
    linhas.push(`${local ? 'Local' : 'Cloud'} observado: entrada ${contagem('entrada', 'com_entrada')}, saída ${contagem('saida', 'com_saida')}, total ${contagem('total', 'com_total')} tokens.`);
  }
  linhas.push('Cobertura limitada ao consumo coletado pelo escritório; não representa todo o uso das contas. Modelos usam tokenizadores diferentes: este volume não mede qualidade ou eficiência.');
  linhas.push('Intervalos de despacho por projeto estão no painel Gestão; não medem velocidade do modelo. Equivalente teórico de API aparece no detalhamento quando há cobertura; cobrança real não integrada. Percentuais dos planos permanecem separados por fornecedor.');
  return linhas;
}

export function instalarIndicadores(painel, antes) {
  const secao = document.createElement('section');
  secao.setAttribute('aria-label', 'Cotas por fornecedor');
  secao.setAttribute('aria-live', 'polite');
  antes.before(secao);
  let carregando = false, ultimaConsulta = 0;
  function texto(tag, valor) {
    const e = document.createElement(tag); e.textContent = valor; secao.append(e);
  }
  async function atualizar() {
    if (painel.hidden || document.hidden || carregando || Date.now() - ultimaConsulta < 60000) return;
    carregando = true;
    try {
      const r = await fetch('/api/uso/providers', {cache: 'no-store'});
      if (!r.ok) throw new Error('Cotas indisponíveis');
      const dados = await r.json();
      if (!Array.isArray(dados.providers)) throw new Error('Formato inválido');
      secao.replaceChildren();
      texto('h3', 'Cotas por fornecedor · conta real');
      texto('p', 'Claude: os indicadores do plano acima continuam usando a statusline do Claude Code.');
      for (const p of dados.providers) {
        const [titulo, ...linhas] = linhasCota(p);
        texto('h4', titulo);
        for (const linha of linhas) texto('p', linha);
      }
      texto('p', 'Gemini: cota ainda não integrada. OpenCode: a cota depende da conta do fornecedor do modelo; não há uma cota única do console.');
      texto('p', 'Percentuais não são somados entre fornecedores. Cota da assinatura, tokens e cobrança em dinheiro são indicadores separados. A leitura do Codex corresponde à conta autenticada no CLI deste PC.');
      texto('h3', 'Visão geral do escritório · consumo observado em 7 dias');
      texto('p','Este resumo inclui todos os projetos registrados no histórico deste escritório, inclusive projetos que já não estão configurados. Consulte Gestão para o consumo de cada projeto.');
      for (const linha of linhasVisaoGeral(dados.consumo)) texto('p', linha);
      texto('h3', 'Detalhamento por console, modelo e agente');
      for (const linha of linhasConsumo(dados.consumo)) texto('p', linha);
    } catch (e) {
      secao.replaceChildren(); texto('p', 'Não foi possível atualizar as cotas dos outros fornecedores. Consulte a indicação de dados reais ou demonstração dos indicadores do Claude acima.');
    } finally { carregando = false; ultimaConsulta = Date.now(); }
  }
  new MutationObserver(atualizar).observe(painel, {attributes: true, attributeFilter: ['hidden']});
  document.addEventListener('visibilitychange', atualizar);
  setInterval(atualizar, 60000);
  atualizar();
}
