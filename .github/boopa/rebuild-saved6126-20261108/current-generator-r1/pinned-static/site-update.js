/* Resume-safe updates for browser tabs and installed iPad/PWA windows.
   Never clear user bookmarks, history, or unrelated origin caches. */
(function () {
  'use strict';
  const loadedAt = Date.parse(document.lastModified);
  const marker = '__boopadb_update';
  const here = new URL(location.href);
  const attemptKey = 'boopadb_update_attempt:' + here.pathname;
  let attempted = here.searchParams.get(marker) || '';
  try {
    if (attempted) sessionStorage.setItem(attemptKey, attempted);
    else attempted = sessionStorage.getItem(attemptKey) || '';
  } catch (_) {}
  if (here.searchParams.has(marker)) {
    here.searchParams.delete(marker);
    history.replaceState(history.state, '', here.href);
  }
  let registration, busy = false, lastCheck = 0;
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('sw.js', {updateViaCache: 'none'})
      .then(reg => { registration = reg; reg.update().catch(() => {}); })
      .catch(() => {});
  }
  function isEditing() {
    const lens=document.getElementById('lensView');
    if(lens && !lens.hidden)return true;
    const search=document.getElementById('searchPage'),catalog=document.getElementById('spCatalogStatus');
    if(search && search.classList && search.classList.contains('open'))return true;
    if(catalog && catalog.dataset && catalog.dataset.loading==='true')return true;
    const el = document.activeElement;
    return el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName));
  }
  async function check() {
    if (busy || document.hidden || navigator.onLine === false || isEditing() || Date.now() - lastCheck < 30000) return;
    if (!Number.isFinite(loadedAt)) return;
    busy = true;
    lastCheck = Date.now();
    if (registration) registration.update().catch(() => {});
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);
    try {
      // Track separately deployed banner/data assets as well as the document.
      const targets = [location.href, new URL('lists_full.json', location.href).href];
      const banner = document.querySelector('img[src*="banner.jpg"]');
      if (banner) targets.push(new URL(banner.getAttribute('src'), location.href).href);
      const revisions = await Promise.all(targets.map(async target => {
        const probe = new URL(target);
        probe.hash = '';
        probe.searchParams.delete(marker);
        probe.searchParams.set('__boopadb_check', String(Date.now()));
        const response = await fetch(probe.href, {method: 'HEAD', cache: 'no-store', signal: controller.signal});
        return {target, ok: response.ok, modified: Date.parse(response.headers.get('Last-Modified')), etag: response.headers.get('ETag') || ''};
      }));
      if (revisions.some(r => !r.ok || !Number.isFinite(r.modified))) return;
      const fresh = revisions;
      const newer = fresh.some(r => r.modified > loadedAt);
      // Persist the attempted server revision across documents. HEAD can be newer
      // than GET during CDN propagation; never repeatedly reload that same revision.
      const signature = fresh.map(r => r.target.split('#')[0] + ':' + r.modified + ':' + r.etag).join('|');
      let hash = 2166136261;
      for (let i = 0; i < signature.length; i++) hash = Math.imul(hash ^ signature.charCodeAt(i), 16777619);
      const revision = (hash >>> 0).toString(36);
      if (newer && revision !== attempted && !document.hidden && !isEditing()) {
        attempted = revision;
        try { sessionStorage.setItem(attemptKey, revision); } catch (_) {}
        const next = new URL(location.href);
        next.searchParams.set(marker, revision);
        // A unique URL also escapes an older worker/HTTP cache during migration.
        location.replace(next.href);
      }
    } catch (_) { /* Offline/resume failures retain the working page. */ }
    finally { clearTimeout(timeout); busy = false; }
  }
  window.addEventListener('pageshow', check);
  window.addEventListener('boopa:lens-close', check);
  window.addEventListener('boopa:search-close', check);
  window.addEventListener('boopa:catalog-ready', check);
  window.addEventListener('online', check);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) check(); });
  setInterval(check, 120000);
  check();
})();
