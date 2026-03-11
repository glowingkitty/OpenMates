// frontend/apps/web_app/src/sw.ts
/**
 * Custom Service Worker — injectManifest strategy
 *
 * Purpose: Provides Workbox precaching + runtime caching (same as the old
 * generateSW config) PLUS native Web Push notification support so the backend
 * can deliver push messages to this browser even while the app is closed.
 *
 * Architecture context: docs/architecture/notifications.md
 * The `push` event fires when the backend sends a Web Push message via pywebpush.
 * On click the SW focuses an existing window or opens a new one at the target URL.
 *
 * Tests: Notification delivery is verified manually via the admin debug tools.
 *
 * IMPORTANT: This file is compiled by Vite/Workbox as part of the
 * `injectManifest` build step. Do NOT use regular ESM imports that are only
 * available in the browser — use the `workbox-*` virtual imports instead.
 */

/// <reference lib="webworker" />

import { clientsClaim } from 'workbox-core';
import {
	precacheAndRoute,
	cleanupOutdatedCaches,
	createHandlerBoundToURL
} from 'workbox-precaching';
import { NavigationRoute, registerRoute } from 'workbox-routing';
import { NetworkFirst } from 'workbox-strategies';
import { ExpirationPlugin } from 'workbox-expiration';

declare let self: ServiceWorkerGlobalScope;

// ──────────────────────────────────────────────────────────────────────────────
// Workbox precaching (injected at build time by @vite-pwa/sveltekit)
// ──────────────────────────────────────────────────────────────────────────────

// self.__WB_MANIFEST is replaced by the build tool with the precache manifest.
// Keeping all asset types from the old generateSW config.
precacheAndRoute(self.__WB_MANIFEST);
cleanupOutdatedCaches();

// Keep skipWaiting=false so the old SW keeps serving until the user navigates
// again (prevents mid-session disruption). The frontend will call
// registration.update() on soft navigation to pick up new versions quickly.
clientsClaim();

// ──────────────────────────────────────────────────────────────────────────────
// Runtime caching (mirrors old generateSW `runtimeCaching` config)
// ──────────────────────────────────────────────────────────────────────────────

// API responses — NetworkFirst, short TTL, small cache.
registerRoute(
	({ url }) => /^https:\/\/api\.(dev\.)?openmates\.org\/.*/i.test(url.href),
	new NetworkFirst({
		cacheName: 'api-cache',
		networkTimeoutSeconds: 10,
		plugins: [new ExpirationPlugin({ maxEntries: 50, maxAgeSeconds: 60 * 60 })]
	})
);

// Navigation (HTML) — NetworkFirst so the user always gets the latest shell.
// Offline fallback is provided by the precached index.html entry.
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

// ──────────────────────────────────────────────────────────────────────────────
// Web Push — receive notifications while the app is closed/backgrounded
// ──────────────────────────────────────────────────────────────────────────────

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
		// Fallback for plain-text payloads
		payload = { title: 'OpenMates', body: event.data.text() };
	}

	const title = payload.title ?? 'OpenMates';
	const options: NotificationOptions = {
		body: payload.body ?? '',
		icon: payload.icon ?? '/icons/icon-192x192.png',
		badge: payload.badge ?? '/icons/badge-72x72.png',
		tag: payload.tag ?? 'openmates-push',
		data: { url: payload.url ?? '/' },
		// Keep the notification visible until the user interacts with it
		requireInteraction: false
	};

	event.waitUntil(self.registration.showNotification(title, options));
});

// ──────────────────────────────────────────────────────────────────────────────
// Notification click — focus existing window or open new one
// ──────────────────────────────────────────────────────────────────────────────

self.addEventListener('notificationclick', (event: NotificationEvent) => {
	event.notification.close();

	const targetUrl: string = (event.notification.data as { url?: string })?.url ?? '/';

	event.waitUntil(
		self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
			// If there's already an open window, focus it and navigate if needed.
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
			// No existing window — open a new one.
			return self.clients.openWindow(targetUrl);
		})
	);
});
