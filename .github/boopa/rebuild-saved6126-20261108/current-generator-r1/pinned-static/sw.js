/* Fresh pages/assets online, last successful shell response offline.
   Price JSONs and cross-origin product/API data are never stored here. */
const CACHE = 'boopadb-shell-v2';
const PREFIX = 'boopadb-shell-';
const scope = new URL(self.registration.scope);
self.addEventListener('install', (event) => event.waitUntil(self.skipWaiting()));
self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const current = await caches.open(CACHE);
    const oldKeys = (await caches.keys()).filter(key => key.startsWith(PREFIX) && key !== CACHE);
    for (const key of oldKeys) {
      const old = await caches.open(key);
      for (const request of await old.keys()) {
        const url = new URL(request.url);
        if (url.origin !== scope.origin || !url.pathname.startsWith(scope.pathname) || url.pathname.endsWith('.json')) continue;
        if (!await current.match(request)) {
          const response = await old.match(request);
          if (response && response.ok) await current.put(request, response);
        }
      }
      // Delete only after every copy succeeds; a failed migration retains v1.
      await caches.delete(key);
    }
    await self.clients.claim();
  })());
});
self.addEventListener('fetch', (event) => {
  const req = event.request, url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== scope.origin || !url.pathname.startsWith(scope.pathname)) return;
  if (url.pathname.endsWith('/sw.js')) return;
  if (url.pathname.endsWith('.json')) {
    event.respondWith(fetch(req, {cache: 'no-store'}));
    return;
  }
  // Never turn a freshness probe into a cached response.
  if (url.searchParams.has('__boopadb_check')) return;
  const keyURL = new URL(url);
  keyURL.searchParams.delete('__boopadb_update');
  const key = keyURL.href;
  const cache = caches.open(CACHE);
  const network = fetch(req, {cache: 'no-store'}).then(response => {
    if (response.ok) {
      const copy = response.clone();
      event.waitUntil(cache.then(c => c.put(key, copy)).catch(() => {}));
      return response;
    }
    // Do not replace the good offline copy with a transient server failure.
    if (response.status >= 500) throw new Error('Temporary server error');
    return response;
  });
  event.respondWith(network.catch(async () => {
    const c = await cache;
    const hit = await c.match(key);
    if (hit) return hit;
    if (req.mode === 'navigate') {
      const home = await c.match(new URL('index.html', scope).href) || await c.match(scope.href);
      if (home) return home;
    }
    return Response.error();
  }));
});
