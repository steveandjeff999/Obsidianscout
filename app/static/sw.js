// Service Worker for ObsidianScout - Simplified version without offline analytics

// Increment the CACHE_VERSION to force clients to update caches when you change assets
const CACHE_VERSION = 4;
const CACHE_NAME = `scout-app-cache-v${CACHE_VERSION}`;

// Core site shell files to pre-cache. Add any top-level routes or critical files here.
const STATIC_ASSETS = [
  '/',
  // Scouting pages (explicitly precache important routes)
  '/scouting/',
  '/scouting/form',
  '/scouting/list',
  '/scouting/qr',
  '/scouting/offline',
  '/scouting/text-elements',
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
  '/static/js/pit_scouting_offline.js',
  '/static/offline.html'
];

// Install event: cache static assets
self.addEventListener('install', event => {
  // Pre-cache site shell
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      return cache.addAll(STATIC_ASSETS.map(normalizeUrlForCache))
        .catch(err => {
          // If some assets fail to cache, still allow SW to install but log for diagnosis
          console.warn('Some assets failed to cache during install:', err);
        });
    })
  );
  // Activate new service worker immediately
  self.skipWaiting();
});

// Activate event: cleanup old caches
self.addEventListener('activate', event => {
  // Clean up old caches
  event.waitUntil(
    caches.keys().then(keys => {
      return Promise.all(
        keys.filter(key => key !== CACHE_NAME)
          .map(key => caches.delete(key))
      );
    }).then(() => self.clients.claim())
  );
});

// Fetch event: simplified strategy without offline analytics
self.addEventListener('fetch', event => {
  const req = event.request;
  const url = new URL(req.url);

  // Only handle GET requests
  if (req.method !== 'GET') return;

  // Let analytics and admin API calls go to network (don't cache sensitive endpoints)
  if (url.pathname.includes('/analytics') || url.pathname.includes('/api/analytics') || url.pathname.includes('/admin')) {
    return; // allow default network handling
  }

  // Navigation requests - serve index/offline fallback for SPA-style navigation
  if (req.mode === 'navigate' || (req.headers.get('accept') || '').includes('text/html')) {
    event.respondWith(navigationHandler(req));
    return;
  }

  // For static assets, prefer cache first
  if (isStaticAsset(url)) {
    event.respondWith(cacheFirst(req));
    return;
  }

  // Fallback to network-first for others (API calls etc.)
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
    if (fresh.ok && (req.url.endsWith('/') || req.url.includes('.html'))) {
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
    // Return an offline HTML fallback if available
    const offline = await cache.match('/static/offline.html');
    if (offline) return offline;
    return new Response('Offline - Please check your connection', {
      status: 503,
      headers: { 'Content-Type': 'text/plain' }
    });
  }
}

// Handle navigation requests with network-first then fallback to cached index/offline
async function navigationHandler(req) {
  try {
    const fresh = await fetch(req);
    const cache = await caches.open(CACHE_NAME);
    // Cache successful navigation responses (HTML)
    if (fresh && fresh.ok) cache.put(req, fresh.clone());
    return fresh;
  } catch (err) {
    const cache = await caches.open(CACHE_NAME);
    // Try to serve the requested page from cache
    const cached = await cache.match(req);
    if (cached) return cached;
    // If not cached, return offline fallback page
    const offline = await cache.match('/static/offline.html');
    if (offline) return offline;
    return new Response('Offline', { status: 503, headers: { 'Content-Type': 'text/plain' } });
  }
}

// Utility: normalize urls for cache storage - make sure root and index resolve
function normalizeUrlForCache(path) {
  // Ensure absolute path strings are returned as Request-like strings
  if (path === '/') return '/';
  return path;
}

// Utility: Determine if a URL points to a static asset we want cached
function isStaticAsset(url) {
  const pathname = url.pathname;
  // Common static file extensions
  return /\.(?:js|css|png|jpg|jpeg|svg|gif|webp|woff2?|ttf|eot|json|map)$/.test(pathname) || pathname.startsWith('/static/');
}

