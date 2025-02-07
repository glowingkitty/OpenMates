module.exports = {
  globDirectory: 'static/',
  globPatterns: ['**/*.{html,js,css,json,ico,png,svg,woff,woff2}'],
  swDest: 'static/sw.js',
  runtimeCaching: [
    {
      urlPattern: ({ request }) => request.mode === 'navigate', // Cache HTML pages
      handler: 'NetworkFirst', // Try network first, fallback to cache
      options: {
        cacheName: 'html-cache',
      },
    },
    {
      urlPattern: ({ request }) => request.destination === 'script' || request.destination === 'style',
      handler: 'StaleWhileRevalidate',
      options: {
        cacheName: 'static-resources',
      },
    },
    {
      urlPattern: ({ request }) => request.destination === 'image',
      handler: 'CacheFirst',
      options: {
        cacheName: 'image-cache',
        expiration: {
          maxEntries: 50,
          maxAgeSeconds: 30 * 24 * 60 * 60,
        },
      },
    },
    {
      urlPattern: ({ request }) => request.destination === 'font',
      handler: 'CacheFirst',
      options: {
        cacheName: 'font-cache',
        expiration: {
          maxEntries: 20,
          maxAgeSeconds: 60 * 60 * 24 * 365,
        },
      },
    },
  ],
};