/**
 * AquaSmart Service Worker
 * ─────────────────────────────────────────────────────────────────────────
 * Strategy:
 *   - Static assets (CSS, JS, fonts) → Cache First
 *   - HTML pages                     → Network First + offline fallback
 *   - API / POST requests            → Network only, show offline toast if fail
 *
 * Offline capability (read-only):
 *   - Dashboard, Pond list, Batch list, Alert list → served from cache
 *   - POST/write actions → blocked with friendly offline message
 */

const CACHE_NAME   = 'aquasmart-v1.1.0';   // bump version to force refresh
const OFFLINE_PAGE = '/offline/';

// ── Pages to pre-cache on install ────────────────────────────────────────────
const PRECACHE_URLS = [
  '/',
  '/offline/',
  '/ponds/',
  '/batches/',
  '/alerts/',
  '/feed-log/',
  '/analytics/',
  '/static/css/styles.css',
  '/static/pwa/pwa.js',
  '/static/pwa/icons/icon-192x192.png',
  '/static/pwa/icons/icon-512x512.png',
  'https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600&family=Syne:wght@700;800&display=swap',
  'https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js',
];

// ── Routes that must always go to network (auth pages) ───────────────────────
const NETWORK_ONLY_PATHS = [
  '/accounts/login/',
  '/accounts/logout/',
  '/accounts/register/',
  '/admin/',
];

// ── Install: pre-cache core pages & assets ────────────────────────────────────
self.addEventListener('install', function (event) {
  console.log('[SW] Installing AquaSmart Service Worker v1.1.0…');
  event.waitUntil(
    caches.open(CACHE_NAME).then(function (cache) {
      return Promise.allSettled(
        PRECACHE_URLS.map(url =>
          cache.add(url).catch(e => console.warn('[SW] Pre-cache failed:', url, e))
        )
      );
    }).then(() => self.skipWaiting())
  );
});

// ── Activate: remove old caches ───────────────────────────────────────────────
self.addEventListener('activate', function (event) {
  event.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(
        keys.filter(k => k !== CACHE_NAME).map(k => {
          console.log('[SW] Deleting old cache:', k);
          return caches.delete(k);
        })
      );
    }).then(() => self.clients.claim())
  );
});

// ── Fetch handler ─────────────────────────────────────────────────────────────
self.addEventListener('fetch', function (event) {
  const url = new URL(event.request.url);

  // Skip non-http
  if (!url.protocol.startsWith('http')) return;

  // Skip auth/admin — always network
  if (NETWORK_ONLY_PATHS.some(p => url.pathname.startsWith(p))) return;

  // POST / write requests — try network, if offline return friendly JSON error
  if (event.request.method !== 'GET') {
    event.respondWith(
      fetch(event.request).catch(() =>
        new Response(
          JSON.stringify({ error: 'offline', message: 'You are offline. Please reconnect to save changes.' }),
          { status: 503, headers: { 'Content-Type': 'application/json' } }
        )
      )
    );
    return;
  }

  // Static assets (CSS, JS, fonts, images) → Cache First
  if (
    url.pathname.startsWith('/static/') ||
    url.hostname === 'fonts.googleapis.com' ||
    url.hostname === 'fonts.gstatic.com' ||
    url.hostname === 'cdn.jsdelivr.net'
  ) {
    event.respondWith(cacheFirst(event.request));
    return;
  }

  // HTML pages → Network First, fallback to cache, then offline page
  if (event.request.headers.get('accept')?.includes('text/html')) {
    event.respondWith(networkFirstHTML(event.request));
    return;
  }

  // Everything else → Network First with cache fallback
  event.respondWith(networkFirst(event.request));
});

// ── Strategy: Cache First ─────────────────────────────────────────────────────
async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) return cached;
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(CACHE_NAME);
      cache.put(request, response.clone());
    }
    return response;
  } catch (e) {
    return new Response('', { status: 408 });
  }
}

// ── Strategy: Network First ───────────────────────────────────────────────────
async function networkFirst(request) {
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(CACHE_NAME);
      cache.put(request, response.clone());
    }
    return response;
  } catch (e) {
    const cached = await caches.match(request);
    if (cached) return cached;
    return new Response(
      JSON.stringify({ error: 'Offline', cached: false }),
      { status: 503, headers: { 'Content-Type': 'application/json' } }
    );
  }
}

// ── Strategy: Network First for HTML — cache visited pages ───────────────────
async function networkFirstHTML(request) {
  try {
    const response = await fetch(request);
    if (response.ok) {
      // Cache every HTML page the user visits so it's available offline
      const cache = await caches.open(CACHE_NAME);
      cache.put(request, response.clone());
    }
    return response;
  } catch (e) {
    // Try cache first
    const cached = await caches.match(request);
    if (cached) {
      console.log('[SW] Serving cached page:', request.url);
      return cached;
    }
    // Fallback to offline page
    const offlinePage = await caches.match(OFFLINE_PAGE);
    if (offlinePage) return offlinePage;

    // Last resort inline offline page
    return new Response(
      `<html><body style="background:#0a1628;color:#e8f4ff;font-family:sans-serif;
       display:flex;align-items:center;justify-content:center;height:100vh;margin:0">
       <div style="text-align:center">
         <div style="font-size:48px">📡</div>
         <h2>You are offline</h2>
         <p style="color:#7a95b8">Please check your internet connection.</p>
         <button onclick="location.reload()"
           style="background:#00e5b4;color:#0a1628;border:none;padding:10px 20px;
                  border-radius:8px;cursor:pointer;font-size:14px;font-weight:700;margin-top:12px">
           Retry
         </button>
       </div></body></html>`,
      { status: 503, headers: { 'Content-Type': 'text/html' } }
    );
  }
}

// ── Push notifications ────────────────────────────────────────────────────────
self.addEventListener('push', function (event) {
  if (!event.data) return;
  let data = {};
  try { data = event.data.json(); } catch (e) { data = { title: 'AquaSmart Alert' }; }

  event.waitUntil(
    self.registration.showNotification(data.title || 'AquaSmart Alert', {
      body:    data.body || 'You have a new farm alert.',
      icon:    '/static/pwa/icons/icon-192x192.png',
      badge:   '/static/pwa/icons/icon-72x72.png',
      vibrate: [200, 100, 200],
      data:    { url: data.url || '/' },
      actions: [
        { action: 'view',    title: '👁 View Alert' },
        { action: 'dismiss', title: '✕ Dismiss'    },
      ],
      tag:      data.tag || 'aquasmart-alert',
      renotify: true,
    })
  );
});

self.addEventListener('notificationclick', function (event) {
  event.notification.close();
  if (event.action === 'dismiss') return;
  const url = event.notification.data?.url || '/';
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function (clientList) {
      for (const client of clientList) {
        if (client.url === url && 'focus' in client) return client.focus();
      }
      if (clients.openWindow) return clients.openWindow(url);
    })
  );
});

console.log('[SW] AquaSmart Service Worker v1.1.0 loaded ✓');