// Transporte apenas: identidade, presença e conclusão continuam no núcleo Office.
export function fluxoEventos({cursor, receber, gestao, reiniciar, conexao, EventSource: Fonte=globalThis.EventSource}) {
  let fonte=null, ativo=false, vigilancia=null;
  const vigiar=()=>{
    clearTimeout(vigilancia);
    vigilancia=setTimeout(()=>{fonte?.close();fonte=null;ativo=false;conexao(false);},35000);
  };
  return {
    get ativo(){return ativo;},
    abrir(){
      if(fonte || !Fonte)return;
      fonte=new Fonte(`/eventos/ao-vivo?desde=${cursor()}`);
      fonte.onopen=()=>{ativo=true;vigiar();conexao(true);};
      fonte.onerror=()=>{ativo=false;clearTimeout(vigilancia);conexao(false);}; // Reconexão nativa usa Last-Event-ID.
      fonte.addEventListener('batida',()=>vigiar());
      fonte.addEventListener('evento',e=>{
        const id=Number(e.lastEventId);
        if(!Number.isSafeInteger(id)||id<=cursor())return;
        try{const ev=JSON.parse(e.data);if(ev && typeof ev==='object' && !Array.isArray(ev))receber(ev,id);}catch{}
      });
      fonte.addEventListener('gestao',()=>gestao());
      fonte.addEventListener('reiniciar',()=>{this.fechar();reiniciar();});
    },
    fechar(){clearTimeout(vigilancia);fonte?.close();fonte=null;ativo=false;},
  };
}
