/* Cache only the public application shell and immutable build assets, never API responses. */
const CACHE = "synchrohq-shell-v6";
self.addEventListener("install", event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(["/", "/collect", "/inbox", "/reports", "/forms", "/profile", "/administration", "/analytics", "/map", "/map", "/analytics", "/icon.svg", "/manifest.webmanifest"].map(path => new Request(path, { cache: "reload" })))));
  self.skipWaiting();
});
self.addEventListener("activate", event => { event.waitUntil(Promise.all([self.clients.claim(), caches.keys().then(keys => Promise.all(keys.filter(key => key.startsWith("synchrohq-shell-") && key !== CACHE).map(key => caches.delete(key))))])); });
self.addEventListener("fetch", event => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/")) return;
  if (url.pathname.startsWith("/_next/static/")) {
    event.respondWith(caches.open(CACHE).then(async cache => {
      const cached = await cache.match(request);
      if (cached) return cached;
      const response = await fetch(request);
      if (response.ok) await cache.put(request, response.clone());
      return response;
    }));
  } else if (request.mode === "navigate" && ["/", "/collect", "/inbox", "/reports", "/forms", "/profile", "/administration"].includes(url.pathname)) {
    event.respondWith(caches.open(CACHE).then(async cache => {
      try {
        const response = await fetch(request);
        if (response.ok) await cache.put(url.pathname, response.clone());
        return response;
      } catch {
        return await cache.match(url.pathname) || Response.error();
      }
    }));
  }
});
self.addEventListener("message", event => {
  if (event.data?.type !== "CACHE_ASSETS") return;
  event.waitUntil(caches.open(CACHE).then(async cache => {
    let ready = true;
    for (const value of event.data.urls ?? []) {
      const url = new URL(value, self.location.origin);
      if (url.origin === self.location.origin && url.pathname.startsWith("/_next/static/")) {
        try { await cache.add(url.href); } catch { ready = false; }
      }
    }
    event.ports[0]?.postMessage({ ready });
  }));
});
