// Service worker CèpeRadar : coquille applicative en cache, prévisions toujours rafraîchies.
const VERSION = "ceperadar-v1";
self.addEventListener("install", (e) => { self.skipWaiting(); });
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== VERSION).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET") return;
  const sameOrigin = url.origin === self.location.origin;
  const isForecast = sameOrigin && (url.pathname.includes("/data/forecast/") || url.pathname.endsWith("status.json") || url.pathname.endsWith("history.json") || url.pathname.endsWith("status_failed.json"));
  const isTile = url.hostname === "data.geopf.fr";
  if (isForecast || (sameOrigin && (url.pathname.endsWith("/") || url.pathname.endsWith(".html")))) {
    // réseau d'abord, cache en secours (hors ligne)
    e.respondWith(fetch(e.request).then((r) => { const c = r.clone(); caches.open(VERSION).then((ca) => ca.put(e.request, c)); return r; }).catch(() => caches.match(e.request)));
  } else if (sameOrigin || isTile || url.hostname.endsWith("gstatic.com") || url.hostname.endsWith("googleapis.com")) {
    // cache d'abord (ressources versionnées, couches statiques, tuiles de fond)
    e.respondWith(caches.match(e.request).then((m) => m || fetch(e.request).then((r) => {
      if (r.ok || r.type === "opaque") { const c = r.clone(); caches.open(VERSION).then((ca) => ca.put(e.request, c)); }
      return r;
    })));
  }
});
