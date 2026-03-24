// frontend/apps/web_app/src/sw.ts
//
// Custom Workbox service worker entry for Vite PWA injectManifest.
// Keeps runtime caching behavior and handles Web Push notifications.
// Architecture context: docs/architecture/notifications.md
// Build note: injectManifest reads this file via `injectManifest.swSrc`.
// Test reference: `pnpm run build` in frontend/apps/web_app.

/// <reference lib="webworker" />

import { clientsClaim } from 'workbox-core';
import { cleanupOutdatedCaches, precacheAndRoute } from 'workbox-precaching';
import { NavigationRoute, registerRoute } from 'workbox-routing';
import { ExpirationPlugin } from 'workbox-expiration';
import { NetworkFirst } from 'workbox-strategies';

declare let self: ServiceWorkerGlobalScope;

precacheAndRoute(self.__WB_MANIFEST);
cleanupOutdatedCaches();
clientsClaim();

// Listen for SKIP_WAITING message from performCleanUpdate() in cacheManager.ts.
// When the app detects a new version (via SvelteKit version polling) and the user
// clicks "Refresh now", performCleanUpdate() posts this message to activate the
// waiting service worker immediately — ensuring the new JS bundle is loaded.
// Without this handler, the waiting SW would only activate after ALL tabs close,
// which can leave devices running stale code for hours/days (causing encryption
// key sync failures on multi-device setups).
self.addEventListener('message', (event: ExtendableMessageEvent) => {
	if (event.data && event.data.type === 'SKIP_WAITING') {
		self.skipWaiting();
	}
});

registerRoute(
	({ url }) => /^https:\/\/api\.(dev\.)?openmates\.org\/.*/i.test(url.href),
	new NetworkFirst({
		cacheName: 'api-cache',
		networkTimeoutSeconds: 10,
		plugins: [new ExpirationPlugin({ maxEntries: 50, maxAgeSeconds: 60 * 60 })]
	})
);

registerRoute(
	new NavigationRoute(
		new NetworkFirst({
			cacheName: 'navigation-cache',
			networkTimeoutSeconds: 5,
			plugins: [
				new ExpirationPlugin({
					maxEntries: 10,
					maxAgeSeconds: 24 * 60 * 60
				})
			]
		})
	)
);

self.addEventListener('push', (event: PushEvent) => {
	if (!event.data) return;

	let payload: {
		title?: string;
		body?: string;
		url?: string;
		tag?: string;
		icon?: string;
		badge?: string;
	};

	try {
		payload = event.data.json();
	} catch {
		payload = { title: 'OpenMates', body: event.data.text() };
	}

	const title = payload.title ?? 'OpenMates';
	const options: NotificationOptions = {
		body: payload.body ?? '',
		icon: payload.icon ?? '/icons/icon-192x192.png',
		badge: payload.badge ?? '/icons/badge-72x72.png',
		tag: payload.tag ?? 'openmates-push',
		data: { url: payload.url ?? '/' },
		requireInteraction: false
	};

	event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', (event: NotificationEvent) => {
	event.notification.close();

	const targetUrl: string = (event.notification.data as { url?: string })?.url ?? '/';

	event.waitUntil(
		self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
			for (const client of clientList) {
				if ('focus' in client) {
					const windowClient = client as WindowClient;
					if (windowClient.url === targetUrl || windowClient.url.startsWith(self.location.origin)) {
						return windowClient.focus().then((focused) => {
							if (focused.url !== targetUrl) {
								return focused.navigate(targetUrl);
							}
							return focused;
						});
					}
				}
			}

			return self.clients.openWindow(targetUrl);
		})
	);
});
