const CACHE_NAME = 'static-cache-v17';
const ASSETS_TO_CACHE = [
  '/',
  '/static/js/script.js',
  '/static/style/style.css',
  '/static/icons/icon-192x192.png',
  '/static/icons/icon-512x512.png',
  '/static/manifest.json',
  '/static/logos/tmdb_logo.svg',
  '/static/logos/trakt_logo.svg',
  '/static/logos/imdb_logo.svg',
  '/static/logos/youtube_logo.svg',
  'https://cdn.jsdelivr.net/npm/ios-pwa-splash@1.0.0/cdn.min.js'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(ASSETS_TO_CACHE);
    }).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames.map((cacheName) => {
          if (cacheName !== CACHE_NAME) {
            return caches.delete(cacheName);
          }
        })
      );
    }).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  event.respondWith(
    caches.match(event.request).then((response) => {
      return response || fetch(event.request);
    })
  );
});
