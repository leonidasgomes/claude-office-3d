// Cadastro explícito; carregar o painel não cria funcionários nem inicia consoles.
export function formularioFuncionarios(projeto, atualizar) {
  const detalhes = document.createElement('details');
  const resumo = document.createElement('summary'); resumo.textContent = 'Cadastrar especialista'; detalhes.append(resumo);
  const form = document.createElement('form'); detalhes.append(form);
  function campo(titulo, elemento) {
    elemento.setAttribute('aria-label',titulo);
    const label = document.createElement('label'); label.append(document.createTextNode(titulo + ' '), elemento);
    form.append(label); return elemento;
  }
  function texto(titulo, tamanho, multiline = false) {
    const e = document.createElement(multiline ? 'textarea' : 'input');
    e.required = true; e.maxLength = tamanho; return campo(titulo, e);
  }
  function escolha(titulo, valores) {
    const e = document.createElement('select');
    for (const [valor, nome] of valores) { const o = document.createElement('option'); o.value = valor; o.textContent = nome; e.append(o); }
    return campo(titulo, e);
  }
  const nome = texto('Nome', 64), funcao = texto('Função e responsabilidades', 2000, true);
  const equipe = escolha('Equipe', projeto.equipes.map(e => [e.nome, e.nome]));
  const console = escolha('Console', ['claude', 'codex', 'opencode', 'gemini'].map(v => [v, v]));
  const modelo = campo('Modelo (vazio usa padrão do console)', document.createElement('input'));
  modelo.maxLength = 200;
  const execucao = escolha('Execução', projeto.local.ativo ? [['cloud','Cloud'],['local','Local']] : [['cloud','Cloud']]);
  const origem = escolha('Cloud do modelo (OpenCode)', [['','Não informada (não comprova diversidade na revisão cruzada)'],['anthropic','Anthropic'],['openai','OpenAI'],['google','Google'],['outro','Outro']]);
  const skills = document.createElement('fieldset'); const legend = document.createElement('legend'); legend.textContent = 'Skills compartilhados'; skills.append(legend); form.append(skills);
  const selecionados = [];
  const compatibilidades = [];
  for (const skill of projeto.skills || []) {
    const label = document.createElement('label'), input = document.createElement('input'); input.type = 'checkbox'; input.value = skill.nome;
    label.title = skill.descricao; label.append(input, document.createTextNode(skill.nome)); skills.append(label); selecionados.push(input);
    compatibilidades.push({label,input,skill});
  }
  function atualizarSkills() {
    const chave = (console.value || 'claude') + (execucao.value === 'local' ? '_local' : '');
    for (const {label,input,skill} of compatibilidades) {
      const d = skill.compatibilidade?.[chave];
      input.disabled = !!d?.pendencias?.length;
      if (input.disabled) input.checked = false;
      const aviso = input.disabled ? ' · adaptação pendente: ' + d.pendencias.join(', ') : '';
      label.replaceChildren(input, document.createTextNode(skill.nome + aviso));
    }
  }
  console.addEventListener('change', () => {modelo.value = ''; origem.value = ''; atualizarSkills();});
  execucao.addEventListener('change', atualizarSkills);
  atualizarSkills();
  const aviso = document.createElement('p'); aviso.textContent = 'Herda as permissões nativas do console e as regras do projeto. Cadastro não inicia trabalho. Local exige modelo instalado e respeita a proteção de recursos.'; form.append(aviso);
  const enviar = document.createElement('button'); enviar.type = 'submit'; enviar.textContent = 'Salvar especialista'; form.append(enviar);
  const status = document.createElement('p'); status.setAttribute('role','status'); form.append(status);
  form.addEventListener('submit', async ev => {
    ev.preventDefault(); enviar.disabled = true;
    const executor = {console: console.value, modelo: modelo.value.trim(), execucao: execucao.value};
    if (console.value === 'opencode' && execucao.value === 'cloud' && origem.value) executor.cloud = origem.value;
    try {
      const r = await fetch('/api/gestao/funcionarios', {method:'POST', headers:{'Content-Type':'application/json','X-Office-Acao':'1'}, body:JSON.stringify({projeto_id:projeto.id, funcionario:{nome:nome.value.trim(),funcao:funcao.value.trim(),equipe:equipe.value,executor,skills:selecionados.filter(e=>e.checked).map(e=>e.value)}})});
      const dados = await r.json(); if (!r.ok) throw new Error(dados.erro || `Servidor respondeu ${r.status}`);
      status.textContent = `Especialista ${dados.funcionario.nome} salvo.`; form.reset(); await atualizar();
    } catch(e) { status.textContent = `Cadastro indisponível: ${e.message}`; }
    finally { enviar.disabled = false; }
  });
  return detalhes;
}
