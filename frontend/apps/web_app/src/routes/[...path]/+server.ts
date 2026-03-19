// frontend/apps/web_app/src/routes/[...path]/+server.ts
/**
 * @file +server.ts (catch-all)
 * @description Catch-all server route that handles any URL path not matched by
 * SvelteKit's file-system routing. Returns a 302 redirect to the SPA root with
 * a #404=<path> hash fragment so the client-side Not404Screen can render.
 *
 * Architecture: Without this route the SvelteKit Vercel adapter falls through to
 * its own 404 function (the bare "404 Not Found" page). This server route
 * intercepts BEFORE that happens and redirects into the SPA gracefully.
 *
 * Flow: /iphone-review → 302 → /#404=%2Fiphone-review → SPA boots →
 *       +page.svelte onMount detects #404= hash → notFoundPathStore.set('/iphone-review')
 *       → ActiveChat shows Not404Screen.
 */

import { redirect } from '@sveltejs/kit';
import type { RequestHandler } from './$types';

export const GET: RequestHandler = ({ url }) => {
	// Preserve the original path + query string in the hash fragment.
	// encodeURIComponent encodes / as %2F which decodeURIComponent reverses on the client.
	const failedPath = url.pathname + (url.search || '');
	const hash = `#404=${encodeURIComponent(failedPath)}`;
	redirect(302, `/${hash}`);
};
