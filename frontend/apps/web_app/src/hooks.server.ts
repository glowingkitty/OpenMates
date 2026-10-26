/**
 * Server hooks — adds security response headers to all routes.
 * Matches the API's Caddy security headers for defense-in-depth.
 * See: deployment/dev_server/Caddyfile lines 28-40
 */
import type { Handle } from '@sveltejs/kit';
// The optional Redact model runs in a browser worker, never in this server.
// Enforce its Node/Brotli floor during model preparation and native evaluation;
// a hosted runtime patch lag must not take down SvelteKit's /_app/env.js.

const SEO_ROUTE_PREFIXES = ['/example', '/intro', '/legal', '/events', '/announcements', '/tips'];

function isSeoRoute(pathname: string): boolean {
	return SEO_ROUTE_PREFIXES.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`))
		|| /^\/(?:de\/)?(?:news|blog|social)(?:\/|$)/.test(pathname);
}

function stripDefaultSeoTags(html: string): string {
	return html.replace(
		/\n?\t*<!-- openmates-default-seo:start -->[\s\S]*?<!-- openmates-default-seo:end -->/,
		''
	);
}

export const handle: Handle = async ({ event, resolve }) => {
	const response = await resolve(event, {
		transformPageChunk: ({ html }) => (isSeoRoute(event.url.pathname) ? stripDefaultSeoTags(html) : html)
	});
	response.headers.set('X-Frame-Options', 'DENY');
	response.headers.set('X-Content-Type-Options', 'nosniff');
	response.headers.set('Referrer-Policy', 'strict-origin-when-cross-origin');
	response.headers.set(
		'Permissions-Policy',
		'geolocation=(), microphone=(), camera=(), interest-cohort=()'
	);
	response.headers.set(
		'Content-Security-Policy',
		"object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
	);
	return response;
};
