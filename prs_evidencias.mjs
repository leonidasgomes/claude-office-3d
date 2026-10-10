// Evidências sob demanda, sempre vinculadas ao projeto/PR/SHA mostrado.
export function detalhesEvidencias(projeto, pr, vigente) {
  const det = document.createElement('details');
  const resumo = document.createElement('summary'); resumo.textContent = 'Conferir checks e revisões deste commit';
  const corpo = document.createElement('div');
  const botao = document.createElement('button'); botao.className = 'botao'; botao.textContent = 'Consultar novamente';
  det.append(resumo, corpo, botao);
  let carregando = false, consultado = false;
  function linha(texto) { const e = document.createElement('p'); e.textContent = texto; corpo.append(e); }
  async function consultar() {
    if (carregando || !vigente()) return;
    carregando = true; botao.disabled = true; corpo.replaceChildren(); linha('Consultando evidências no GitHub…');
    try {
      const qs = new URLSearchParams({projeto, numero:String(pr.numero), sha:pr.sha});
      const r = await fetch('/api/gestao/pr?' + qs, {cache:'no-store'});
      const d = await r.json();
      if (!vigente()) { corpo.replaceChildren(); linha('Seleção ou commit mudou. Consulte a lista atual.'); return; }
      if (!r.ok || !d.ok) throw new Error(d.erro || 'Evidências indisponíveis.');
      if (d.projeto_id !== projeto || d.numero !== pr.numero || d.sha !== pr.sha ||
          !Array.isArray(d.checks) || !Array.isArray(d.gates) || !Array.isArray(d.revisoes)) throw new Error('Resposta de outro projeto ou commit.');
      corpo.replaceChildren(); linha(`Commit consultado: ${d.sha}`);
      if (!d.gates.length) linha('Nenhum check obrigatório declarado na política do escritório.');
      for (const g of d.gates) linha(`Check da política: ${g.nome} · ${g.estado}`);
      if (!d.checks.length) linha('Nenhum check ou status observado para este commit.');
      for (const c of d.checks) linha(`${c.tipo}: ${c.nome} · ${c.estado}${c.app_id ? ' · App ' + c.app_id : ''}`);
      const regras=d.regras_branch;
      if(regras?.estado==='consultado'&&Array.isArray(regras.regras)&&Array.isArray(regras.gates)) {
        linha(`Rulesets ativos da base ${regras.branch} · ${regras.sha_base}`);
        if(!regras.regras.length)linha('Nenhuma regra ativa de ruleset retornada; proteção clássica ainda precisa ser conferida.');
        for(const regra of regras.regras){
          linha(`Regra GitHub: ${regra.tipo} · ruleset ${regra.ruleset_id} · ${regra.origem}`);
          if(regra.aprovacoes_exigidas!==undefined)linha(`Aprovações exigidas: ${regra.aprovacoes_exigidas}; CODEOWNERS: ${regra.require_code_owner_review?'sim':'não'}; threads resolvidas: ${regra.required_review_thread_resolution?'sim':'não'}. Não comprova cumprimento.`);
          if(regra.parametros_adicionais)linha('Esta regra tem parâmetros adicionais que ainda não foram avaliados pelo escritório.');
          if(regra.base_atualizada_exigida!==undefined)linha(`Base atualizada exigida pelos checks: ${regra.base_atualizada_exigida?'sim':'não'}. Cumprimento ainda precisa ser conferido.`);
        }
        for(const g of regras.gates)linha(`Check do GitHub: ${g.nome} · ${g.estado}${g.app_id?' · App '+g.app_id:''}`);
        linha(regras.limite);
      }else linha('Regras da base indisponíveis; isso não significa ausência de proteção.');
      const pendencias=d.pendencias_revisao;
      if(pendencias?.estado==='consultado') {
        linha(`Decisão de revisão informada pelo GitHub: ${pendencias.decisao_revisao||'não informada'}. Não atesta clouds independentes.`);
        linha(`Conversas de revisão: ${pendencias.threads_pendentes} pendente(s) de ${pendencias.threads_total}; ${pendencias.threads_pendentes_desatualizadas} pendente(s) em trechos desatualizados.`);
        const classica=pendencias.protecao_classica;
        if(classica?.estado==='ausente')linha('GitHub não retornou proteção clássica para esta base; rulesets continuam sendo conferidos separadamente.');
        else if(classica?.estado==='consultado') {
          linha(`Proteção clássica: aprovações exigidas ${classica.aprovacoes_exigidas??'não informadas'}; CODEOWNERS ${classica.requiresCodeOwnerReviews?'sim':'não'}; resolver conversas ${classica.requiresConversationResolution?'sim':'não'}. Não comprova cumprimento.`);
          for(const g of classica.checks||[])linha(`Check da proteção clássica: ${g.nome} · ${g.estado}${g.app_id?' · App '+g.app_id:''}`);
        }
        linha(pendencias.limite);
      }else linha('Conversas, decisão de revisão e proteção clássica indisponíveis; não presuma aprovação.');
      if (!d.revisoes.length) linha('Nenhuma revisão registrada no PR.');
      for (const v of d.revisoes) linha(`@${v.autor}: ${v.estado} · ${v.commit_atual ? 'commit atual' : v.sha ? 'outro commit' : 'commit não informado'}${v.enviada_em ? ' · ' + v.enviada_em : ''}`);
      linha(d.mergeavel === false ? 'GitHub informou conflito de merge.' : d.mergeavel == null ? 'Mergeabilidade ainda não informada pelo GitHub.' : 'GitHub informou ausência de conflito; isso não comprova todos os gates.');
      linha(d.aviso || 'Evidências não autorizam merge.');
      consultado = true;
    } catch (e) {
      if (!vigente()) return;
      corpo.replaceChildren(); linha(e.message || 'Evidências indisponíveis.');
    } finally { carregando = false; botao.disabled = false; }
  }
  det.addEventListener('toggle', () => { if (det.open && !consultado) consultar(); });
  botao.addEventListener('click', consultar);
  return det;
}
