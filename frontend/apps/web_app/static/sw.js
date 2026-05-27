// OpenMates no longer ships a web-app service worker.
//
// This file only exists so old Workbox installations that request /sw.js during
// their update check receive an unregistering worker instead of a 404. It must
// never add fetch handlers, cache app files, or implement offline behavior.

self.addEventListener('install', () => {
	self.skipWaiting();
});

self.addEventListener('activate', (event) => {
	event.waitUntil(
		self.registration
			.unregister()
			.then(() => self.clients.matchAll({ type: 'window', includeUncontrolled: true }))
			.then((clients) => Promise.all(clients.map((client) => client.navigate(client.url))))
			.then(() => self.caches.keys())
			.then((cacheNames) => Promise.all(cacheNames.map((cacheName) => self.caches.delete(cacheName))))
	);
});
