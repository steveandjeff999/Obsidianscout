// Service Worker for ObsidianScout - Simplified version without offline analytics

// Increment the CACHE_VERSION to force clients to update caches when you change assets
const CACHE_VERSION = 3;
const CACHE_NAME = `scout-app-cache-v${CACHE_VERSION}`;

// Core site shell files to pre-cache. Add any top-level routes or critical files here.
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
  '/static/js/pit_scouting_offline.js',
  '/static/offline.html'
];

// Common image fallbacks to pre-cache so we can serve a reliable placeholder
// when individual icon requests fail. Add any frequently used icons here.
STATIC_ASSETS.push('/static/img/avatars/default.png');
STATIC_ASSETS.push('/static/img/obsidian.png');
STATIC_ASSETS.push('/static/assets/obsidian.png');

// Install event: pre-cache site shell
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(async cache => {
      const toCache = STATIC_ASSETS.map(normalizeUrlForCache);
      // Try addAll first for speed, but fall back to individual caching so
      // one failure doesn't prevent other assets from being cached.
      try {
        await cache.addAll(toCache);
      } catch (err) {
        console.warn('cache.addAll failed, attempting individual asset caching', err);
        await Promise.all(toCache.map(async url => {
          try {
            await cache.add(url);
          } catch (e) {
            // Log and continue - individual assets may 404 during build-time
            console.warn('Failed to cache asset during install:', url, e);
          }
        }));
      }
    })
  );
  // Activate new service worker immediately
  self.skipWaiting();
});

// Activate event: cleanup old caches and take control
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys => {
      return Promise.all(
        keys.filter(key => key !== CACHE_NAME)
          .map(key => caches.delete(key))
      );
    }).then(() => self.clients.claim())
  );
});

// Fetch handler: caching strategies
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
    // For images we often see cache-miss differences caused by query strings
    // (cache-busting). Ignore search when matching image requests to improve
    // hit-rate for icons and avatars.
    const reqUrl = new URL(req.url);
    const isImage = /\.(?:png|jpg|jpeg|svg|gif|webp)$/.test(reqUrl.pathname);
    const cached = isImage ? await cache.match(req, { ignoreSearch: true }) : await cache.match(req);
    if (cached) {
      return cached;
    }
    const fresh = await fetch(req);
    cache.put(req, fresh.clone());
    return fresh;
  } catch (error) {
    console.warn('Cache-first failed:', error);
    // If the request was for an image, attempt to return a sensible fallback
    // (pre-cached default avatar) so the UI doesn't show broken icons.
    try {
      const reqUrl = new URL(req.url);
      if (/\.(?:png|jpg|jpeg|svg|gif|webp)$/.test(reqUrl.pathname) || req.destination === 'image') {
        const cache = await caches.open(CACHE_NAME);
        const fallback = await cache.match('/static/img/avatars/default.png');
        if (fallback) return fallback;
        // As a last resort return a tiny transparent SVG so the layout stays intact.
        return new Response('<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"></svg>', {
          headers: { 'Content-Type': 'image/svg+xml' }
        });
      }
    } catch (e) {
      console.warn('Error while trying to serve image fallback:', e);
    }
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
  if (path === '/') return '/';
  return path;
}

// Utility: Determine if a URL points to a static asset we want cached
function isStaticAsset(url) {
  const pathname = url.pathname;
  return /\.(?:js|css|png|jpg|jpeg|svg|gif|webp|woff2?|ttf|eot|json|map)$/.test(pathname) || pathname.startsWith('/static/');
}
