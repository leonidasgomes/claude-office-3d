// Gestão por especialidade. Consulta apenas com painel aberto e aba visível.
// Toda informação externa é inserida como texto, sem HTML ou comandos executáveis.
import { formularioFuncionarios } from './funcionarios_form.js';
import { formularioAgenteNativo } from './agentes_nativos_form.mjs';
import { formularioRetomada, renderizarRetomadas, botaoConciliarRetomada } from './retomada_form.mjs';
import { formularioExecutores } from './executores_form.mjs';
import { formularioMerge } from './merge_form.mjs';
import { linhasConsumo, linhasVisaoGeral } from './indicadores_providers.mjs';
import { renderizarCoordenacoes } from './coordenacoes_painel.mjs';
import { formularioCoordenacao, renderizarPedidos, botaoExecutarCoordenacao, botaoConciliarPedido } from './coordenacao_form.mjs';
const botao = document.createElement('button');
botao.type = 'button'; botao.textContent = 'Gestão';
botao.className = 'gestaoAbrir';
botao.setAttribute('aria-haspopup', 'dialog');
document.body.append(botao);
const painel = document.createElement('dialog');
painel.className = 'gestaoPainel';
painel.setAttribute('aria-labelledby', 'gestaoTitulo');
const titulo = document.createElement('h2');
titulo.id = 'gestaoTitulo'; titulo.textContent = 'Gestão das equipes';
const fechar = document.createElement('button');
fechar.type = 'button'; fechar.textContent = 'Fechar';
const atualizar = document.createElement('button');
atualizar.type = 'button'; atualizar.textContent = 'Atualizar';
const atualizarCena = document.createElement('button');
atualizarCena.type='button'; atualizarCena.textContent='Atualizar cena 3D';
atualizarCena.addEventListener('click',()=>location.reload());
const corpo = document.createElement('div');
corpo.setAttribute('aria-live', 'polite');
painel.append(titulo, fechar, atualizar, atualizarCena, corpo); document.body.append(painel);
let timer = null, carregando = false;
let projetoAlerta = '';
function linha(tag, texto, pai = corpo) {
  const e = document.createElement(tag); e.textContent = texto; pai.append(e); return e;
}
const executor = (e) => `${e.console} · ${e.modelo || 'padrão do console'} · ${e.execucao || 'cloud'}${e.sandbox ? ' · sandbox '+e.sandbox : ''}`;
async function carregar() {
  if (!painel.open || document.hidden || carregando) return;
  if (corpo.querySelector('details[open]')) return; // preserva preenchimento durante atualização automática
  carregando = true;
  try {
    const r = await fetch('/api/gestao', { cache: 'no-store' });
    if (!r.ok) throw new Error(`Servidor respondeu ${r.status}`);
    const dados = await r.json(); corpo.replaceChildren();
    if(dados.ponte_eventos) {
      linha('h4','Acompanhamento de outras instalações');
      const estados={desligada:'desligado',nao_iniciada:'não iniciado',preparada:'preparado',aguardando:'aguardando consulta',
        acompanhando:'consultando fonte',parcial:'algumas fontes interrompidas',interrompida:'interrompido; confira no PC',
        configuracao_invalida:'configuração inválida; confira no PC',configuracao_alterada:'configuração mudou; reinicie após conferir',encerrada:'encerrado'};
      linha('p',`Ponte: ${estados[dados.ponte_eventos.estado] || 'estado indisponível'}.`);
      for(const f of dados.ponte_eventos.fontes || []) {
        linha('p',`${f.origem}: ${estados[f.estado] || 'estado indisponível'} · ${f.importados || 0} eventos importados nesta execução · ${f.descartados || 0} descartados${f.ultima_consulta?` · última leitura ${new Date(f.ultima_consulta*1000).toLocaleString()}`:''}.`);
      }
      linha('p','Estado da ponte descreve a leitura do banco; não comprova agente ativo, vínculo de projeto/tarefa ou conclusão.');
    }
    linha('p', 'As cotas por fornecedor estão no Placar do escritório.');
    if (!dados.projetos?.length) linha('p', 'Nenhum projeto configurado no escritório.');
    for (const p of dados.projetos || []) {
      const secao = document.createElement('section'); corpo.append(secao);
      secao.dataset.projeto=p.id || '';
      linha('h3', p.nome, secao);
      if (p.erro) { linha('p', p.erro, secao); continue; }
      if(p.documentacao) {
        linha('h4','Fontes comuns e instruções dos consoles',secao);
        const estados={presente:'presente',ausente:'ausente',fora_projeto:'link/caminho não permitido',tipo_invalido:'não é arquivo',acima_limite:'acima do limite de leitura',ilegivel:'não foi possível ler'};
        for(const f of p.documentacao.fontes || [])linha('p',`${f.papel}: ${f.caminho} · ${estados[f.estado] || 'indisponível'}`,secao);
        for(const f of p.documentacao.instrucoes_consoles || [])linha('p',`${f.arquivo} (${f.consoles.join(', ')}): ${estados[f.estado] || 'indisponível'} · ${f.necessario?'usado pela política':'console não selecionado'} · ${f.fonte_regras?'é a fonte de regras':f.cita_regras?'cita a fonte de regras':'referência à fonte não confirmada'}`,secao);
        linha('p',p.documentacao.limite,secao);
      }
      if (!p.ativo) { linha('p', 'Gestão ainda não habilitada neste projeto. O fluxo existente continua ativo.', secao); continue; }
      linha('p', `CEO: ${executor(p.ceo)}`, secao);
      linha('p', `Diretor: ${executor(p.diretor)}`, secao);
      linha('p', `Merge: ${p.merge} · Local: ${p.local.ativo ? (p.local.team ? 'equipes habilitadas' : 'tarefas simples') : 'desativado'}`, secao);
      if(p.revisao) {
        const r=p.revisao,habilitados=r.revisores.filter(x=>x.ativo).length;
        linha('p',r.ativo?`Revisão ativa: exige ${r.clouds_distintas} fornecedor(es) distinto(s)${r.separar_autor?' e diferentes do autor':''}. ${habilitados} revisor(es) habilitado(s) pela política.`:'Revisão cruzada desativada neste projeto.',secao);
        if(r.revisores.length)linha('p','Revisores: '+r.revisores.map(x=>`${x.nome} (${x.console}): ${x.ativo?'habilitado':'suspenso'}`).join(' · '),secao);
        linha('p','Habilitação não comprova login, cota ou disponibilidade. Se faltarem fornecedores independentes habilitados, o despacho é bloqueado antes de iniciar agentes.',secao);
      }
      const lista = linha('ul', '', secao);
      for (const equipe of p.equipes) linha('li', `${equipe.nome}: ${equipe.especialidade} — ${executor(equipe.executor)}`, lista);
      if(p.politica_versao)secao.append(formularioExecutores(p, async()=>{await carregar();}));
      if(p.politica_versao && p.merge_config)secao.append(formularioMerge(p, async()=>{await carregar();}));
      linha('h4','Consumo deste projeto · últimos 7 dias',secao);
      linha('p','Contadores observados neste projeto. Cotas de assinatura pertencem à conta do fornecedor e aparecem separadamente no Placar.',secao);
      if(p.consumo?.escopo!=='projeto')linha('p','Consumo por projeto indisponível.',secao);
      else {
        for(const texto of linhasVisaoGeral(p.consumo))linha('p',texto,secao);
        for(const texto of linhasConsumo(p.consumo))linha('p',texto,secao);
      }
      linha('h4', 'Especialistas cadastrados', secao);
      linha('p','Após cadastrar, use Atualizar cena 3D para carregar os assentos dos especialistas.',secao);
      for (const f of p.funcionarios || []) {
        linha('p', `${f.nome} · ${f.equipe} · ${executor(f.executor)} · ${f.funcao}`, secao);
        linha('code', `python console_provider.py --projeto CAMINHO --funcionario ${f.id} --prompt "Tarefa"`, secao);
        secao.append(formularioAgenteNativo(p,f));
      }
      secao.append(formularioFuncionarios(p, async () => { corpo.querySelectorAll('details').forEach(d => {d.open=false;}); await carregar(); }));
      linha('h4', 'Pendências operacionais das tarefas', secao);
      const saude = p.saude_tarefas;
      if (!saude) linha('p', 'Estado operacional indisponível.', secao);
      else {
        linha('p', `${saude.consultadas} reserva(s) consultada(s), incluindo tentativas anteriores aos últimos 7 dias.`, secao);
        if (saude.limitado) linha('p', 'Cobertura limitada às 200 reservas mais recentes. Podem existir pendências mais antigas.', secao);
        if (!saude.pendencias?.length) linha('p', 'Nenhuma pendência identificada nas reservas consultadas.', secao);
        const sinais = {bloqueada:'tarefa bloqueada', sem_retorno:'tentativa sem retorno registrado',
          falha:'última tentativa com saída diferente de zero', sem_medicao:'execução registrada sem medição'};
        for (const t of saude.pendencias || []) {
          linha('p', `#${t.cartao} · ${t.equipe} · ${t.console}: ${t.sinais.map(s => sinais[s] || s).join('; ')}${t.codigo == null ? '' : ` · saída ${t.codigo}`}.`, secao);
        }
        linha('p', 'Os registros não confirmam todos os processos ou agentes. Retomada explícita exige prévia e conferência no PC; tentativas sem retorno continuam bloqueadas.', secao);
      }
      linha('h4', 'Execuções observadas · últimos 7 dias', secao);
      const desempenho = p.desempenho || {grupos: []};
      if (!desempenho.grupos?.length) linha('p', 'Nenhuma medição de execução disponível neste período.', secao);
      if (desempenho.limitado) linha('p', 'Cobertura limitada às 1.000 tentativas recentes consultadas.', secao);
      if (desempenho.historico_sem_vinculo) linha('p', 'Há tentativas antigas sem vínculo de projeto recuperável neste banco. Elas foram excluídas dos agregados; o histórico pode estar incompleto.', secao);
      if(desempenho.consumo_erro)linha('p',desempenho.consumo_erro,secao);
      for (const g of desempenho.grupos || []) {
        const media = g.media_seg == null ? 'não informado' : `${g.media_seg.toLocaleString('pt-BR')} s`;
        linha('p', `${g.equipe || 'não informado'} · ${g.console} · ${g.modelo} (${g.origem_modelo}) · ${g.execucao}: ${g.tentativas} tentativa(s), intervalo médio ${media} (${g.com_intervalo}/${g.tentativas} com medição).`, secao);
        linha('p', `${g.saida_zero} retorno(s) com saída zero · ${g.saida_nao_zero} com saída diferente de zero · ${g.sem_retorno} sem retorno registrado.`, secao);
        if(g.resultados){
          const r=g.resultados;
          linha('p',`${g.despachos} despacho(s) · ${g.retomadas} retomada(s) · ${g.tipo_nao_informado} com tipo não informado.`,secao);
          linha('p',`${r.revisao_aprovada} encaminhada(s) com revisão aprovada · ${r.revisao_desativada} com revisão desativada · ${r.revisao_reprovada} reprovada(s) na revisão.`,secao);
          linha('p',`${r.falha_console} falha(s) de console · ${r.sem_entrega} sem entrega · ${r.gate_bloqueado} bloqueio(s) nos gates · ${g.sem_resultado} sem resultado registrado.`,secao);
        }
        if(g.consumo_observado) {
          const c=g.consumo_observado;
          const total=c.total==null?'não informado':`${c.total.toLocaleString('pt-BR')} (${c.com_total}/${c.amostras} amostras com total)`;
          linha('p',`Consumo ligado a ${g.tentativas_com_consumo}/${g.tentativas} tentativas: total ${total} tokens.`,secao);
          linha('p',c.equivalente_api_usd==null?'Equivalente teórico de API dessas tentativas: não informado.':`Equivalente teórico de API dessas tentativas: USD ${c.equivalente_api_usd} (${c.com_preco}/${c.amostras} amostras com preço). Não é cobrança real.`,secao);
        }
      }
      linha('p', 'Intervalo do despacho inclui ferramentas e esperas; não mede velocidade ou qualidade do modelo. Saída zero não comprova aceite. Encaminhamento à revisão não comprova merge; retomada não é medida de retrabalho. Atribuição e resultados anteriores ausentes permanecem não informados. Modelo do grupo é o configurado; modelos observados aparecem na tentativa. Consumo vinculado cobre apenas amostras coletadas, não todo o trabalho de filhos. Histórico sem vínculo não é reatribuído. Cotas da conta estão no Placar; cobrança real não integrada.', secao);
      renderizarCoordenacoes(p.coordenacoes,secao,linha);
      renderizarPedidos(p.pedidos_coordenacao,secao,linha);
      for(const pedido of p.pedidos_coordenacao?.itens || []){
        if(pedido.estado==='incerto' && p.politica_versao)
          secao.append(botaoConciliarPedido(p,pedido,async()=>{await carregar();}));
      }
      for(const recibo of p.coordenacoes?.itens || []){
        if(recibo.estado==='organizado' && recibo.plano_sha256 && p.politica_versao)
          secao.append(botaoExecutarCoordenacao(p,recibo,async()=>{await carregar();}));
      }
      if(p.politica_versao)secao.append(formularioCoordenacao(p,async()=>{await carregar();}));
      linha('h4', 'Lotes do diretor', secao);
      const lotes = p.lotes || {itens: []};
      if (!lotes.itens?.length) linha('p', 'Nenhum relatório de lote disponível.', secao);
      if (lotes.problemas) linha('p', 'Há relatórios indisponíveis ou inconsistentes. Confira no PC antes de retomar.', secao);
      if (lotes.limitado) linha('p', 'Exibição limitada aos relatórios recentes consultados.', secao);
      const estadosLote = {
        preparado: 'Preparado', executando: 'Execução registrada; confirme o processo no PC',
        processado: 'Cartões encaminhados à revisão', interrompido: 'Interrompido', incerto: 'Execução incerta; requer conciliação'
      };
      for (const lote of lotes.itens || []) {
        linha('p', `Lote ${lote.id.slice(0, 8)} · ${estadosLote[lote.estado] || 'Estado desconhecido'} · ${lote.resultados.length}/${lote.cartoes.length} retornos`, secao);
        const atualizado = new Date(lote.atualizado * 1000);
        if (Number.isFinite(atualizado.getTime())) linha('p', `Último registro: ${atualizado.toLocaleString()}`, secao);
        if (lote.paralelismo) linha('p', `Paralelismo: até ${lote.paralelismo} cartões. Pendentes de retorno/conciliação: ${lote.cartoes_em_execucao.map(n => '#' + n).join(', ') || 'nenhum'}. O registro não confirma processos vivos.`, secao);
        if (lote.cartao_em_execucao) linha('p', `Último cartão iniciado: #${lote.cartao_em_execucao}. O registro não confirma que o agente continua ativo.`, secao);
        for (const resultado of lote.resultados) {
          linha('p', `#${resultado.cartao} · ${resultado.estado === 'revisao' ? 'Em revisão' : 'Bloqueado'} · saída ${resultado.codigo}`, secao);
        }
      }
      linha('h4', 'Tarefas despachadas', secao);
      renderizarRetomadas(p.pedidos_retomada,secao,linha);
      for(const pedido of p.pedidos_retomada?.itens || []){
        if(pedido.estado==='incerto' && p.politica_versao)secao.append(botaoConciliarRetomada(p,pedido,async()=>{await carregar();}));
      }
      if (!p.tarefas.length) linha('p', 'Nenhuma tarefa despachada pelo controle comum.', secao);
      for (const t of p.tarefas) {
        linha('p', `#${t.cartao} · ${t.equipe} · ${t.console} · ${t.estado}`, secao);
        if(t.estado==='bloqueado' && p.politica_versao)secao.append(formularioRetomada(p,t,async()=>{await carregar();}));
        if (t.ultima_execucao) {
          const e = t.ultima_execucao;
          linha('p', e.duracao_seg == null ? 'Tentativa sem intervalo final registrado; confirme a execução no PC.' : `Intervalo do último despacho observado: ${e.duracao_seg.toLocaleString('pt-BR')} s · saída ${e.codigo}.`, secao);
          if(e.consumo) {
            const detalhe=document.createElement('details');secao.append(detalhe);
            linha('summary','Consumo observado da última tentativa',detalhe);
            for(const texto of linhasConsumo(e.consumo))linha('p',texto,detalhe);
          } else linha('p','Consumo da última tentativa sem vínculo observado.',secao);
        }
        if (t.atividade) {
          const a=t.atividade, idade=(Date.now()/1000)-a.ultimo_sinal;
          const recente=idade>=0 && idade<=60 && a.estado==='acompanhando';
          const descricao=a.codigo_console!=null ? `Processo principal retornou saída ${a.codigo_console}.` :
            recente && a.console_observado ? 'Processo principal observado em execução no último sinal.' :
            recente ? 'Controlador envia sinais; processo principal ainda não observado.' :
            a.estado==='acompanhando' ? 'Sinal do controlador desatualizado; confira no PC.' : 'Acompanhamento encerrado ou interrompido.';
          linha('p', `${descricao} Último sinal: ${new Date(a.ultimo_sinal*1000).toLocaleString()}.`, secao);
          linha('p', 'O sinal não comprova progresso, qualidade ou encerramento de ferramentas e agentes filhos.', secao);
          if(a.eventos) {
            const e=a.eventos;
            linha('p', `Eventos recebidos nesta tentativa: ${e.total} · com vínculo de filho: ${e.eventos_filhos}. Último evento: ${new Date(e.ultimo_evento*1000).toLocaleString()} · ${e.ultimo_tipo}.`,secao);
            linha('p', 'Eventos indicam comunicação observada, sem comprovar avanço, aceite ou execução de todos os filhos.',secao);
          } else linha('p','Sem eventos nativos acompanhados nesta tentativa; ausência de eventos não prova inatividade.',secao);
        }
        if (t.funcionario_nome) linha('p', `Responsável no despacho: ${t.funcionario_nome}`, secao);
        if (t.revisao_sha) linha('p', `Última revisão cruzada: ${t.revisao_aprovada ? 'aprovada' : 'reprovada/indisponível'} · PR #${t.revisao_pr} · commit ${t.revisao_sha.slice(0, 12)}.`, secao);
      }
    }
    if (projetoAlerta) {
      const alvo=corpo.querySelector(`section[data-projeto="${projetoAlerta}"]`);
      if (alvo) { alvo.tabIndex=-1; alvo.scrollIntoView({block:'start'}); alvo.focus(); projetoAlerta=''; }
    }
  } catch (e) { corpo.replaceChildren(); linha('p', `Gestão indisponível: ${e.message}`); }
  finally { carregando = false; }
}
function abrirGestao() {
  if (!painel.open) painel.showModal();
  carregar(); clearInterval(timer); timer=setInterval(carregar,60000);
}
botao.addEventListener('click', abrirGestao);
window.addEventListener('office-gestao-abrir', abrirGestao);
window.addEventListener('office-projeto-alerta', (e) => {
  if (e.detail?.painel!=='gestao' || !/^[0-9a-f]{20}$/.test(e.detail?.projeto || '')) return;
  projetoAlerta=e.detail.projeto; abrirGestao();
});
fechar.addEventListener('click', () => painel.close());
atualizar.addEventListener('click', carregar);
painel.addEventListener('close', () => { clearInterval(timer); timer = null; botao.focus(); });
document.addEventListener('visibilitychange', () => { if (!document.hidden) carregar(); });
