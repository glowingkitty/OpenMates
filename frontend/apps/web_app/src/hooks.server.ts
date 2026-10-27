/**
 * Server hooks — adds security response headers to all routes.
 * Matches the API's Caddy security headers for defense-in-depth.
 * See: deployment/dev_server/Caddyfile lines 28-40
 */
import type { Handle, HandleFetch } from '@sveltejs/kit';
import { assertWebNodeRuntimeSecurity } from './lib/server/webNodeRuntimeSecurity.mjs';

// SvelteKit loads this module before serving /_app/env.js. Enforce the runtime
// floor at the decoding boundary, never by crashing environment initialization.
// Same-origin fetch can also fall back to a real network request.
export const handleFetch: HandleFetch = async ({ request, fetch }) => {
	assertWebNodeRuntimeSecurity();
	return fetch(request);
};

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
	// These web routes do not support encoded request bodies. Reject before a
	// handler/library can decode one; Vercel's ingress WAF is additional protection.
	const encoding = event.request.headers.get('content-encoding')?.trim().toLowerCase();
	const response = encoding && encoding !== 'identity'
		? new Response('Unsupported content encoding', { status: 415 })
		: await resolve(event, {
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
