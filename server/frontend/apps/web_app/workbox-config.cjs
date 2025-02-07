module.exports = {
  globDirectory: 'static/',
  globPatterns: ['**/*.{html,js,css,json,ico,png,svg,woff,woff2}'],
  swDest: 'static/sw.js',
  runtimeCaching: [
    {
      urlPattern: ({ url }) => url.protocol.startsWith('ws'),
      handler: 'NetworkOnly',
      options: {
        cacheName: 'network-only-ws',
      },
    },
    {
      urlPattern: ({ url }) => url.pathname.startsWith('/.svelte-kit/'),
      handler: 'NetworkOnly',
      options: {
        cacheName: 'network-only-sveltekit',
      },
    },
    {
      urlPattern: ({ request }) => request.mode === 'navigate',
      handler: 'NetworkFirst',
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