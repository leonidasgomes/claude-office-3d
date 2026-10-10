// Projeção do cadastro, sem nomes/aliases que possam substituir agentes legados.
export function distribuirFuncionarios(dados, limite = 30) {
  const lista = [], vistos = new Set();
  const cores = {claude:'#e5484d',codex:'#3b82f6',opencode:'#a855f7',gemini:'#22c55e'};
  for (const p of dados?.projetos || []) {
    if (!p.ativo || p.erro) continue;
    for (const f of p.funcionarios || []) {
      if (!/^[0-9a-f]{32}$/.test(f.id) || vistos.has(f.id) || typeof f.nome !== 'string' || typeof f.funcao !== 'string' || !cores[f.executor?.console]) continue;
      vistos.add(f.id);
      lista.push({nome:`Office_${f.id}`,titulo:f.nome.slice(0,64),funcao:`${f.equipe} · ${f.executor.console} · ${f.funcao}`.slice(0,200),
        cor:cores[f.executor.console],mesa:'padrao',cargo:'Especialista',outros_nomes:[],funcionario_id:f.id,
        projeto:p.nome,console:f.executor.console});
    }
  }
  return lista.slice(0,limite);
}

export async function buscarFuncionarios(fetcher = globalThis.fetch) {
  const controle = new AbortController(), timer = setTimeout(() => controle.abort(), 5000);
  try {
    const r = await fetcher('/api/gestao',{cache:'no-store',signal:controle.signal});
    return r.ok ? distribuirFuncionarios(await r.json()) : [];
  } catch { return []; } // indisponibilidade do cadastro preserva a cena legada
  finally { clearTimeout(timer); }
}

// Os dez lugares existentes não mudam. Novos assentos ficam na extensão à esquerda.
export function assentosFuncionarios(funcionarios) {
  return new Map(funcionarios.map((f,i) => [f.nome,10+i]));
}
export function xMesa(indice) {
  const legado = [11,5.8,1.2,-3.4,-8,-12.6,-17.2,-21.8,-26.4,-31];
  return indice<10 ? legado[indice] : -31-(indice-9)*4.6;
}
export function limiteEsquerdo(funcionarios) {
  return funcionarios.length ? xMesa(9+funcionarios.length)-3 : -34;
}

export function tituloFuncionario(nome, funcionarios) {
  const f=funcionarios.find(f=>f.nome.toLowerCase()===String(nome).toLowerCase());
  return f ? `${f.titulo} · ${f.console}` : String(nome || '?').replace(/_/g,' ');
}
