// Service worker dos alertas (escopo "/"): recebe o Web Push com o escritório fechado e mostra a notificação.
// O servidor só manda título curto, corpo de até 120 caracteres e o painel a abrir (nunca comando, caminho, código ou token).
// Toque na notificação: abre/foca o escritório e leva ao painel certo (PRs ou Placar).
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));

self.addEventListener('push', (event) => {
  let d = {};
  try { d = event.data ? event.data.json() : {}; } catch (e) { d = {}; }
  if (!d || typeof d !== 'object') d = {};
  const titulo = String(d.t || 'Escritório: algo espera por você').slice(0, 80);
  // Safari/iOS exige mostrar uma notificação a cada push (senão revoga a inscrição): sempre mostramos
  event.waitUntil(self.registration.showNotification(titulo, {
    body: String(d.c || 'Abra o escritório para ver.').slice(0, 160),
    icon: '/icone-192.png',
    badge: '/icone-192.png',
    tag: String(d.k || 'alerta').slice(0, 30),   // uma notificação por tipo: agrupa em vez de empilhar
    renotify: true,
    vibrate: [120, 60, 120],
    data: { u: typeof d.u === 'string' && d.u.startsWith('/') ? d.u : '/', i: d.i || 0 },
  }));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const alvo = new URL((event.notification.data && event.notification.data.u) || '/', self.location.origin);
  const m = /alerta=([a-z]+)/.exec(alvo.hash);
  const painel = m ? m[1] : '';
  event.waitUntil((async () => {
    const janelas = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    for (const c of janelas) {
      if (new URL(c.url).origin === self.location.origin) {
        try { await c.focus(); } catch (e) { /* sem foco: a mensagem ainda abre o painel */ }
        c.postMessage({ tipo: 'abrir', painel, url: alvo.pathname+alvo.search+alvo.hash });
        return;
      }
    }
    await self.clients.openWindow(alvo.href);
  })());
});
