// Telemetria recente não comprova processo vivo. Histórico permanece no feed.
export function eventoRecente(ev, agoraMs, expira = 60, maxComando = 1800) {
  const ms = Date.parse(ev?.ts);
  if (!Number.isFinite(ms) || !Number.isFinite(agoraMs)) return false;
  const idade = (agoraMs - ms) / 1000;
  const janela = ev?.inicio ? Math.max(0, Math.min(Number(ev.espera_s) || 120, maxComando)) : expira;
  return idade >= -5 && idade < janela;
}

export function demoAutomaticaPermitida(protocolo) {
  return protocolo === 'file:';
}

export function fonteObservada(ev) {
  const fonte = {claude:'Claude',codex:'Codex',opencode:'OpenCode',gemini:'Gemini'}[ev?.fonte];
  return fonte ? fonte + (ev.origem_escritorio ? ' (ponte)' : '') : 'não identificada';
}
