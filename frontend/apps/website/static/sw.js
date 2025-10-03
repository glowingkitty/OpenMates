/**
 * Service Worker for OpenMates Website
 * 
 * Provides offline support for documentation pages.
 * Caches docs pages and assets for offline access.
 */

const CACHE_NAME = 'openmates-docs-v1';
const DOCS_CACHE = 'openmates-docs-content-v1';

// Assets to cache on install
const STATIC_ASSETS = [
    '/',
    '/favicon.png',
    '/favicon.svg',
    '/manifest.json'
];

/**
 * Install event - cache static assets
 */
self.addEventListener('install', (event) => {
    console.log('[SW] Installing service worker...');
    
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then((cache) => {
                console.log('[SW] Caching static assets');
                return cache.addAll(STATIC_ASSETS);
            })
            .then(() => self.skipWaiting())
    );
});

/**
 * Activate event - clean up old caches
 */
self.addEventListener('activate', (event) => {
    console.log('[SW] Activating service worker...');
    
    event.waitUntil(
        caches.keys()
            .then((cacheNames) => {
                return Promise.all(
                    cacheNames
                        .filter((name) => name !== CACHE_NAME && name !== DOCS_CACHE)
                        .map((name) => caches.delete(name))
                );
            })
            .then(() => self.clients.claim())
    );
});

/**
 * Fetch event - serve from cache or network
 * Strategy: Network first for docs, cache fallback
 */
self.addEventListener('fetch', (event) => {
    const { request } = event;
    const url = new URL(request.url);
    
    // Only handle GET requests
    if (request.method !== 'GET') {
        return;
    }
    
    // Special handling for docs pages
    if (url.pathname.startsWith('/docs')) {
        event.respondWith(
            // Try network first
            fetch(request)
                .then((response) => {
                    // Clone the response
                    const responseClone = response.clone();
                    
                    // Cache the successful response
                    if (response.status === 200) {
                        caches.open(DOCS_CACHE).then((cache) => {
                            cache.put(request, responseClone);
                        });
                    }
                    
                    return response;
                })
                .catch(() => {
                    // Network failed, try cache
                    return caches.match(request)
                        .then((cachedResponse) => {
                            if (cachedResponse) {
                                console.log('[SW] Serving from cache:', url.pathname);
                                return cachedResponse;
                            }
                            
                            // No cache, return offline page
                            return new Response(
                                '<h1>Offline</h1><p>This page is not available offline.</p>',
                                {
                                    headers: { 'Content-Type': 'text/html' },
                                    status: 503,
                                    statusText: 'Service Unavailable'
                                }
                            );
                        });
                })
        );
        return;
    }
    
    // Default strategy for other requests: Cache first, network fallback
    event.respondWith(
        caches.match(request)
            .then((cachedResponse) => {
                if (cachedResponse) {
                    return cachedResponse;
                }
                
                return fetch(request)
                    .then((response) => {
                        // Don't cache non-successful responses
                        if (!response || response.status !== 200) {
                            return response;
                        }
                        
                        const responseClone = response.clone();
                        
                        caches.open(CACHE_NAME).then((cache) => {
                            cache.put(request, responseClone);
                        });
                        
                        return response;
                    });
            })
    );
});

/**
 * Message event - handle messages from clients
 */
self.addEventListener('message', (event) => {
    if (event.data && event.data.type === 'SKIP_WAITING') {
        self.skipWaiting();
    }
});

