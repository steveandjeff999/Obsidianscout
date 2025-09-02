// Service Worker for ObsidianScout - Simplified version without offline analytics

const CACHE_NAME = 'scout-app-cache-v2';
const STATIC_ASSETS = [
  '/',
  '/static/css/styles.css',
  '/static/css/theme-management.css',
  '/static/css/theme-overrides.css',
  '/static/js/scripts.js',
  '/static/js/modern-ui.js',
  '/static/js/qrcode.min.js',
  '/static/js/game-config.js',
  '/static/js/dark-mode-handlers.js',
  '/static/js/modal-fix.js',
  '/static/js/modal-override.js',
  '/static/manifest.json',
  '/static/js/pit_scouting_offline.js'
];

// Install event: cache static assets
self.addEventListener('install', event => {
  console.log('Service Worker installing...');
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      console.log('Caching static assets');
      return cache.addAll(STATIC_ASSETS);
    })
  );
  // Force immediate activation
  self.skipWaiting();
});

// Activate event: cleanup old caches
self.addEventListener('activate', event => {
  console.log('Service Worker activating...');
  event.waitUntil(
    caches.keys().then(keys => {
      return Promise.all(
        keys.filter(key => key !== CACHE_NAME)
          .map(key => {
            console.log('Deleting old cache:', key);
            return caches.delete(key);
          })
      );
    })
  );
  // Take control of all pages immediately
  return self.clients.claim();
});

// Fetch event: simplified strategy without offline analytics
self.addEventListener('fetch', event => {
  const req = event.request;
  const url = new URL(req.url);

  // Skip non-GET requests
  if (req.method !== 'GET') {
    return;
  }

  // Skip analytics routes - always go to network
  if (url.pathname.startsWith('/analytics') || 
      url.pathname.includes('analytics') || 
      url.pathname.startsWith('/api/analytics') ||
      url.pathname.startsWith('/app/api/analytics')) {
    return; // Let the browser handle it normally
  }

  // For static assets, use cache-first strategy
  if (STATIC_ASSETS.some(asset => url.pathname === asset || url.pathname.endsWith(asset.replace('/static', '')))) {
    event.respondWith(cacheFirst(req));
    return;
  }

  // For all other requests, try network first, fallback to cache for offline
  event.respondWith(networkFirst(req));
});

// Cache-first strategy for static assets
async function cacheFirst(req) {
  try {
    const cache = await caches.open(CACHE_NAME);
    const cached = await cache.match(req);
    if (cached) {
      return cached;
    }
    const fresh = await fetch(req);
    cache.put(req, fresh.clone());
    return fresh;
  } catch (error) {
    console.warn('Cache-first failed:', error);
    return fetch(req);
  }
}

// Network-first strategy for dynamic content
async function networkFirst(req) {
  try {
    const fresh = await fetch(req);
    // Only cache successful responses for HTML pages
    if (fresh.ok && req.url.endsWith('/') || req.url.includes('.html')) {
      const cache = await caches.open(CACHE_NAME);
      cache.put(req, fresh.clone());
    }
    return fresh;
  } catch (error) {
    console.warn('Network failed, trying cache:', error);
    const cache = await caches.open(CACHE_NAME);
    const cached = await cache.match(req);
    if (cached) {
      return cached;
    }
    // Return a generic offline page if available
    return new Response('Offline - Please check your connection', { 
      status: 503,
      headers: { 'Content-Type': 'text/plain' }
    });
  }
}

