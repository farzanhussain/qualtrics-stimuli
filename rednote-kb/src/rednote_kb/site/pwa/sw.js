// Service worker for 小红书 KB.
// Strategy:
//   - app shell (HTML / CSS / JS / manifest / icon): cache-first
//   - posts.json: network-first w/ cache fallback (latest data wins, offline OK)
//   - per-post HTML under /p/: stale-while-revalidate
//   - everything else (e.g. xiaohongshu.com images): pass through, no cache

const VERSION    = 'v1';
const SHELL_CACHE = 'shell-' + VERSION;
const DATA_CACHE  = 'data-'  + VERSION;

const SHELL = [
  './',
  './index.html',
  './static/style.css',
  './static/search.js',
  './manifest.webmanifest',
  './icon.svg',
  './icon-180.png',
  './icon-192.png',
  './icon-512.png',
];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(SHELL_CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter(k => !k.endsWith(VERSION)).map(k => caches.delete(k)));
    await self.clients.claim();
  })());
});

function isPostsJson(url) {
  return url.pathname.endsWith('/posts.json');
}
function isPostHtml(url) {
  return /\/p\/[^/]+\.html$/.test(url.pathname);
}
function isSameOrigin(url) {
  return url.origin === self.location.origin;
}

// QuotaExceededError on cache.put would otherwise reject the fetch promise and
// surface as a broken page even though the network response was fine. Swallow
// cache write failures — losing a cache entry is acceptable; losing the page is not.
async function safePut(cache, req, res) {
  try { await cache.put(req, res); } catch (_err) { /* quota / blocked: skip */ }
}

async function networkFirst(req, cacheName) {
  const cache = await caches.open(cacheName);
  try {
    const fresh = await fetch(req, { cache: 'no-cache' });
    if (fresh && fresh.ok) await safePut(cache, req, fresh.clone());
    return fresh;
  } catch (err) {
    const cached = await cache.match(req);
    if (cached) return cached;
    throw err;
  }
}

async function staleWhileRevalidate(req, cacheName) {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(req);
  const fetchPromise = fetch(req).then(async res => {
    if (res && res.ok) await safePut(cache, req, res.clone());
    return res;
  }).catch(() => cached);
  return cached || fetchPromise;
}

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || !isSameOrigin(url)) return;

  if (isPostsJson(url))     { e.respondWith(networkFirst(e.request, DATA_CACHE)); return; }
  if (isPostHtml(url))      { e.respondWith(staleWhileRevalidate(e.request, DATA_CACHE)); return; }

  // shell — cache-first, fall back to network, fall back to root on nav.
  e.respondWith((async () => {
    const cache = await caches.open(SHELL_CACHE);
    const hit = await cache.match(e.request);
    if (hit) return hit;
    try {
      const res = await fetch(e.request);
      if (res && res.ok) await safePut(cache, e.request, res.clone());
      return res;
    } catch (err) {
      if (e.request.mode === 'navigate') return cache.match('./index.html');
      throw err;
    }
  })());
});
