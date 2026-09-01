// OpenMates no longer ships a web-app service worker.
//
// This file only exists so old Workbox installations that request /sw.js during
// their update check receive an unregistering worker instead of a 404. It must
// never add fetch handlers, cache app files, or implement offline behavior.
// Legacy caches are left to browser eviction because deleting large CacheStorage
// databases during activation can make every controlled tab unresponsive.

self.addEventListener('install', () => {
	self.skipWaiting();
});

self.addEventListener('activate', (event) => {
	event.waitUntil(self.registration.unregister());
});
