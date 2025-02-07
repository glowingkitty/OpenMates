module.exports = {
  globDirectory: 'static/',
  globPatterns: ['**/*.{html,js,css,json,ico,png,svg}'],
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
  ],
};