// A seleção pertence a esta página; não altera a configuração nem o board de outro usuário.
export function seletorProjetos(antes, mudar, {endpoint='/kanban', nome='Projeto do Kanban'} = {}) {
  const rotulo = document.createElement('label');
  rotulo.textContent = nome + ': ';
  rotulo.hidden = true;
  const select = document.createElement('select');
  select.setAttribute('aria-label', nome);
  rotulo.append(select); antes.before(rotulo);
  let escolhido = '';
  select.addEventListener('change', () => { escolhido = select.value; mudar(); });
  return {
    selecionar(id) {
      if (typeof id !== 'string' || !/^[0-9a-f]{20}$/.test(id)) return false;
      escolhido=id; select.value=id; mudar(); return true;
    },
    url: () => escolhido ? `${endpoint}?projeto=${encodeURIComponent(escolhido)}` : endpoint,
    receber(dados) {
      rotulo.hidden = dados.fonte !== 'gestao';
      if (rotulo.hidden) return;
      const projetos = dados.projetos || [];
      select.replaceChildren();
      const vazio = document.createElement('option'); vazio.value = ''; vazio.textContent = 'Selecione um projeto'; select.append(vazio);
      for (const p of projetos) {
        const opcao = document.createElement('option'); opcao.value = p.id; opcao.textContent = `${p.nome} · ${p.id.slice(0, 6)}`; select.append(opcao);
      }
      escolhido = escolhido || dados.projeto_id || '';
      select.value = escolhido;
    },
  };
}
