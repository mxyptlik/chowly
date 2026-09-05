const VERSION = "v2";
const STATIC_CACHE = `chowly-static-${VERSION}`;
const SHELL_CACHE = `chowly-shell-${VERSION}`;
const SHELL = ["/offline", "/manifest.json", "/icons/chowly.svg", "/icons/chowly-maskable.svg"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(SHELL_CACHE).then((cache) => cache.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((key) => key.startsWith("chowly-") && ![STATIC_CACHE, SHELL_CACHE].includes(key)).map((key) => caches.delete(key))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== self.location.origin) return;

  // API, authenticated, order, contact, and payment data are never stored by this worker.
  if (url.pathname.startsWith("/api/") || request.headers.has("Authorization")) return;

  if (request.mode === "navigate") {
    event.respondWith(fetch(request).catch(() => caches.match("/offline")));
    return;
  }

  const staticAsset = url.pathname.startsWith("/_next/static/") || url.pathname.startsWith("/icons/") || url.pathname === "/manifest.json";
  if (!staticAsset) return;
  event.respondWith(
    caches.open(STATIC_CACHE).then(async (cache) => {
      const cached = await cache.match(request);
      const fresh = fetch(request).then((response) => {
        if (response.ok && response.type === "basic") void cache.put(request, response.clone());
        return response;
      });
      if (cached) event.waitUntil(fresh.then(() => undefined).catch(() => undefined));
      return cached ?? fresh;
    }),
  );
});
