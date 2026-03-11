// frontend/apps/web_app/src/lib/backendUrl.ts
//
// Derives the backend API base URL from the incoming request hostname.
// Eliminates the need for a BACKEND_URL environment variable on Vercel.
//
// Mapping:
//   app.dev.openmates.org  →  https://api.dev.openmates.org
//   app.openmates.org      →  https://api.openmates.org
//   localhost / 127.0.0.1  →  https://api.dev.openmates.org  (dev fallback)
//   anything else          →  https://api.openmates.org       (safe default)
//
// For build-time prerendering (entries() in +page.ts), there is no request
// URL available. Those callers should import PRERENDER_BACKEND_URL directly.

/**
 * Derive the backend API base URL from a SvelteKit request URL object.
 * Use this in +server.ts and +page.server.ts handlers.
 */
export function getBackendUrl(url: URL): string {
	const host = url.hostname;
	if (
		host.includes('.dev.') ||
		host.startsWith('dev.') ||
		host === 'localhost' ||
		host === '127.0.0.1'
	) {
		return 'https://api.dev.openmates.org';
	}
	return 'https://api.openmates.org';
}

/**
 * Backend URL for build-time use (entries() generators, prerender).
 * Always points to production — prerendering only runs against prod data.
 */
export const PRERENDER_BACKEND_URL = 'https://api.openmates.org';
