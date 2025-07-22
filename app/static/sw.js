// Service Worker for full offline support and data caching

const CACHE_NAME = 'scout-app-cache-v1';
const API_CACHE = 'scout-app-api-cache-v1';
const STATIC_ASSETS = [
  '/',
  '/static/css/styles.css',
  '/static/css/theme-management.css',
  '/static/css/theme-overrides.css',
  '/static/js/scripts.js',
  '/static/js/modern-ui.js',
  '/static/js/offline.js',
  '/static/js/qrcode.min.js',
  '/static/js/pit_scouting_offline.js',
  '/static/js/game-config.js',
  '/static/js/dark-mode-handlers.js',
  '/static/js/activity-logger.js',
  '/static/js/modal-fix.js',
  '/static/js/modal-override.js',
  '/static/manifest.json',
  // Add more static files as needed
];

// Install event: cache static assets
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      return cache.addAll(STATIC_ASSETS);
    })
  );
  self.skipWaiting();
});

// Activate event: cleanup old caches
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys => {
      return Promise.all(
        keys.filter(key => key !== CACHE_NAME && key !== API_CACHE)
          .map(key => caches.delete(key))
      );
    })
  );
  self.clients.claim();
});

// Fetch event: cache-first for static, network-first for API
self.addEventListener('fetch', event => {
  const req = event.request;
  const url = new URL(req.url);

  // API requests (adjust path as needed)
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/app/api/')) {
    event.respondWith(networkFirstAPI(req));
  } else if (STATIC_ASSETS.some(asset => url.pathname.endsWith(asset.replace('/static', '')) || url.pathname === asset)) {
    // Static assets
    event.respondWith(cacheFirst(req));
  } else {
    // Fallback: try cache, then network
    event.respondWith(
      caches.match(req).then(res => res || fetch(req))
    );
  }
});

// Cache-first strategy for static assets
async function cacheFirst(req) {
  const cache = await caches.open(CACHE_NAME);
  const cached = await cache.match(req);
  return cached || fetch(req);
}

// Network-first strategy for API requests, fallback to cache
async function networkFirstAPI(req) {
  const cache = await caches.open(API_CACHE);
  try {
    const fresh = await fetch(req);
    // Clone and store in cache
    cache.put(req, fresh.clone());
    // Store in IndexedDB for offline use
    const data = await fresh.clone().json().catch(() => null);
    if (data) {
      saveAPIDataToIDB(req.url, data);
    }
    return fresh;
  } catch (e) {
    // Offline: try cache
    const cached = await cache.match(req);
    if (cached) return cached;
    // Try IndexedDB as last resort
    const idbData = await getAPIDataFromIDB(req.url);
    if (idbData) {
      return new Response(JSON.stringify(idbData), { headers: { 'Content-Type': 'application/json' } });
    }
    return new Response('Offline and no cached data', { status: 503 });
  }
}

// IndexedDB helpers for API data
function saveAPIDataToIDB(key, data) {
  const open = indexedDB.open('ScoutAppDB', 1);
  open.onupgradeneeded = () => {
    open.result.createObjectStore('api', { keyPath: 'url' });
  };
  open.onsuccess = () => {
    const db = open.result;
    const tx = db.transaction('api', 'readwrite');
    tx.objectStore('api').put({ url: key, data });
    tx.oncomplete = () => db.close();
  };
}

function getAPIDataFromIDB(key) {
  return new Promise(resolve => {
    const open = indexedDB.open('ScoutAppDB', 1);
    open.onupgradeneeded = () => {
      open.result.createObjectStore('api', { keyPath: 'url' });
    };
    open.onsuccess = () => {
      const db = open.result;
      const tx = db.transaction('api', 'readonly');
      const req = tx.objectStore('api').get(key);
      req.onsuccess = () => {
        resolve(req.result ? req.result.data : null);
        db.close();
      };
      req.onerror = () => {
        resolve(null);
        db.close();
      };
    };
    open.onerror = () => resolve(null);
  });
}

