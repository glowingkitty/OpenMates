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
	// During prerendering, SvelteKit uses a synthetic hostname — use the same
	// PRERENDER_BACKEND_URL that entries() generators use for consistency.
	if (host === 'sveltekit-prerender') {
		return PRERENDER_BACKEND_URL;
	}
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
 * Resolve the canonical site origin used by SEO routes.
 * During prerender builds SvelteKit provides a synthetic origin
 * (http://sveltekit-prerender) which must never leak into canonical/og URLs.
 */
export function getSiteOrigin(url: URL): string {
	if (url.hostname === 'sveltekit-prerender') {
		return 'https://openmates.org';
	}
	return url.origin;
}

/**
 * Backend URL for build-time use (entries() generators, prerender).
 * Reads BACKEND_URL from the environment so dev and prod Vercel builds
 * each prerender against their own backend. Falls back to prod if unset.
 */
export const PRERENDER_BACKEND_URL = process.env.BACKEND_URL ?? 'https://api.openmates.org';
