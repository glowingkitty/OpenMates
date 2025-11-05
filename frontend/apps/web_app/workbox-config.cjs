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
        // Safari-specific: Aggressive cache expiration for HTML
        // NetworkFirst with short timeout ensures we always check for new HTML first
        // This prevents Safari from serving stale HTML files
        expiration: {
          maxEntries: 10, // Reduced from 30 to minimize stale HTML caching (Safari-specific fix)
          maxAgeSeconds: 60 * 60, // Reduced to 1 hour (Safari-specific fix)
        },
        // Network timeout ensures we check network first, then fall back to cache
        networkTimeoutSeconds: 3, // Quick timeout to check network first
      },
    },
    {
      urlPattern: ({ request }) => request.destination === 'script' || request.destination === 'style',
      handler: 'StaleWhileRevalidate',
      options: {
        cacheName: 'static-resources',
        // Safari-specific: Use StaleWhileRevalidate to ensure we check for updates
        // This strategy serves from cache immediately but checks for updates in background
        // This ensures Safari gets updated JS/CSS files while maintaining fast load times
        expiration: {
          maxEntries: 100, // Limit JS/CSS files in cache
          maxAgeSeconds: 30 * 24 * 60 * 60, // 30 days - assets are versioned by build hashes
        },
      },
    },
    {
      urlPattern: ({ request }) => request.destination === 'image',
      handler: 'CacheFirst',
      options: {
        cacheName: 'image-cache',
        expiration: {
          maxEntries: 30, // Reduced from 50 to prevent quota issues
          maxAgeSeconds: 7 * 24 * 60 * 60, // Reduced from 30 days to 7 days
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