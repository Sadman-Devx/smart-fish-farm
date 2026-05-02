/**
 * AquaSmart Service Worker
 * ─────────────────────────────────────────────────────────────────────────
 * Strategy:
 *   - Static assets (CSS, JS, fonts) → Cache First
 *   - API endpoints                  → Network First (fresh data)
 *   - HTML pages                     → Network First + offline fallback
 *   - Images                         → Cache First with fallback
 *
 * Offline capability:
 *   - Dashboard, Pond list, Alert list → served from cache
 *   - Forms (POST) → queued in IndexedDB, synced when online
 */

const CACHE_NAME    = 'aquasmart-v1.0.0';
const API_CACHE     = 'aquasmart-api-v1';
const OFFLINE_PAGE  = '/offline/';

// ── Assets to pre-cache on install ───────────────────────────────────────────
const PRECACHE_URLS = [
  '/',
  '/offline/',
  '/static/css/styles.css',
  'https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600&family=Syne:wght@700;800&display=swap',
  'https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js',
];

// ── Routes that should always go to network ───────────────────────────────────
const NETWORK_ONLY = [
  '/accounts/login/',
  '/accounts/logout/',
  '/accounts/register/',
  '/admin/',
];

// ── Install: pre-cache core assets ────────────────────────────────────────────
self.addEventListener('install', function(event) {
  console.log('[SW] Installing AquaSmart Service Worker…');
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(function(cache) {
        console.log('[SW] Pre-caching core assets');
        // Add one by one to avoid failing entire install on one miss
        return Promise.allSettled(
          PRECACHE_URLS.map(url => cache.add(url).catch(e => {
            console.warn('[SW] Pre-cache failed for:', url, e);
          }))
        );
      })
      .then(function() {
        console.log('[SW] Pre-cache complete');
        return self.skipWaiting();
      })
  );
});

// ── Activate: clean old caches ────────────────────────────────────────────────
self.addEventListener('activate', function(event) {
  console.log('[SW] Activating…');
  event.waitUntil(
    caches.keys().then(function(cacheNames) {
      return Promise.all(
        cacheNames
          .filter(name => name !== CACHE_NAME && name !== API_CACHE)
          .map(name => {
            console.log('[SW] Deleting old cache:', name);
            return caches.delete(name);
          })
      );
    }).then(function() {
      console.log('[SW] Active and controlling all clients');
      return self.clients.claim();
    })
  );
});

// ── Fetch: routing strategy ───────────────────────────────────────────────────
self.addEventListener('fetch', function(event) {
  const url = new URL(event.request.url);

  // Skip non-GET and non-http requests
  if (event.request.method !== 'GET') return;
  if (!url.protocol.startsWith('http')) return;

  // Skip network-only routes
  if (NETWORK_ONLY.some(path => url.pathname.startsWith(path))) return;

  // API endpoints → Network First
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(networkFirst(event.request, API_CACHE));
    return;
  }

  // Static assets → Cache First
  if (
    url.pathname.startsWith('/static/') ||
    url.hostname === 'fonts.googleapis.com' ||
    url.hostname === 'fonts.gstatic.com' ||
    url.hostname === 'cdn.jsdelivr.net'
  ) {
    event.respondWith(cacheFirst(event.request));
    return;
  }

  // HTML pages → Network First with offline fallback
  if (event.request.headers.get('accept')?.includes('text/html')) {
    event.respondWith(networkFirstWithOfflineFallback(event.request));
    return;
  }

  // Default → Network First
  event.respondWith(networkFirst(event.request, CACHE_NAME));
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
    console.warn('[SW] Cache first fetch failed:', request.url);
    return new Response('', { status: 408 });
  }
}

// ── Strategy: Network First ───────────────────────────────────────────────────
async function networkFirst(request, cacheName) {
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(cacheName);
      cache.put(request, response.clone());
    }
    return response;
  } catch (e) {
    const cached = await caches.match(request);
    if (cached) {
      console.log('[SW] Serving from cache (offline):', request.url);
      return cached;
    }
    return new Response(JSON.stringify({ error: 'Offline', cached: false }), {
      status: 503,
      headers: { 'Content-Type': 'application/json' },
    });
  }
}

// ── Strategy: Network First with HTML offline fallback ────────────────────────
async function networkFirstWithOfflineFallback(request) {
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(CACHE_NAME);
      cache.put(request, response.clone());
    }
    return response;
  } catch (e) {
    // Try cache
    const cached = await caches.match(request);
    if (cached) return cached;

    // Last resort: offline page
    const offlinePage = await caches.match(OFFLINE_PAGE);
    if (offlinePage) return offlinePage;

    return new Response(
      '<html><body style="background:#0a1628;color:#e8f4ff;font-family:sans-serif;'
      + 'display:flex;align-items:center;justify-content:center;height:100vh;margin:0">'
      + '<div style="text-align:center"><div style="font-size:48px">📡</div>'
      + '<h2>You are offline</h2>'
      + '<p style="color:#7a95b8">Please check your internet connection.</p>'
      + '<button onclick="location.reload()" '
      + 'style="background:#00e5b4;color:#0a1628;border:none;padding:10px 20px;'
      + 'border-radius:8px;cursor:pointer;font-size:14px;font-weight:700;margin-top:12px">'
      + 'Retry</button></div></body></html>',
      { status: 503, headers: { 'Content-Type': 'text/html' } }
    );
  }
}

// ── Background Sync: queue failed POSTs ───────────────────────────────────────
self.addEventListener('sync', function(event) {
  if (event.tag === 'sync-feed-logs') {
    event.waitUntil(syncFeedLogs());
  }
  if (event.tag === 'sync-water-records') {
    event.waitUntil(syncWaterRecords());
  }
});

async function syncFeedLogs() {
  console.log('[SW] Background sync: feed logs');
  // IndexedDB sync logic handled by client-side JS
}

async function syncWaterRecords() {
  console.log('[SW] Background sync: water records');
}

// ── Push notifications ────────────────────────────────────────────────────────
self.addEventListener('push', function(event) {
  if (!event.data) return;

  let data = {};
  try { data = event.data.json(); } catch(e) { data = { title: 'AquaSmart Alert' }; }

  const options = {
    body:    data.body    || 'You have a new farm alert.',
    icon:    '/static/pwa/icons/icon-192x192.png',
    badge:   '/static/pwa/icons/icon-72x72.png',
    vibrate: [200, 100, 200],
    data:    { url: data.url || '/' },
    actions: [
      { action: 'view',    title: '👁 View Alert' },
      { action: 'dismiss', title: '✕ Dismiss'    },
    ],
    tag:     data.tag || 'aquasmart-alert',
    renotify: true,
  };

  event.waitUntil(
    self.registration.showNotification(data.title || 'AquaSmart Alert', options)
  );
});

self.addEventListener('notificationclick', function(event) {
  event.notification.close();
  if (event.action === 'dismiss') return;

  const url = event.notification.data?.url || '/';
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true })
      .then(function(clientList) {
        for (const client of clientList) {
          if (client.url === url && 'focus' in client) {
            return client.focus();
          }
        }
        if (clients.openWindow) return clients.openWindow(url);
      })
  );
});

console.log('[SW] AquaSmart Service Worker loaded ✓');