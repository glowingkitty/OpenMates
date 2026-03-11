// frontend/apps/web_app/src/routes/demo/chat/[slug]/+page.ts
//
// Prerender configuration for SEO demo chat pages.
//
// ARCHITECTURE:
//   prerender = 'auto': known slugs (from entries()) are prerendered to static HTML at
//   build time — zero SSR cost, served directly from disk. Unknown slugs (added after the
//   last build) fall through to live SSR via +page.server.ts automatically.
//
//   entries(): fetches all published demo chat slugs from the backend at build time and
//   returns them as prerender targets. On Vercel, this runs during `vercel build`. On
//   adapter-node (future Hetzner migration), it runs during `node build`.

import type { EntryGenerator } from './$types';

// Use 'auto' so prerendered slugs are static files but unknown slugs still SSR gracefully
export const prerender = 'auto';

// SSR must remain enabled for the SSR fallback path (new slugs not in entries())
export const ssr = true;

// CSR allows client-side hydration so the redirect script fires in human browsers
export const csr = true;

/**
 * EntryGenerator: called at build time to produce the list of slugs to prerender.
 * Fetches all published demo chats from the backend API and extracts their slugs.
 * Any slug not in this list at build time will be served via SSR on first request.
 */
export const entries: EntryGenerator = async () => {
	// entries() only runs in Node.js at build time, so process.env is safe here.
	// We cannot use $env/dynamic/private (browser-compiled too) or
	// $env/static/private (not yet established in the project), so we fall back
	// to process.env which is available in the Vercel build environment.
	const backendUrl =
		(typeof process !== 'undefined' && process.env?.BACKEND_URL) || 'https://api.openmates.org';

	try {
		const response = await fetch(`${backendUrl}/v1/demo/chats?lang=en`);

		if (!response.ok) {
			console.warn(
				`[demo/chat entries] Failed to fetch demo chats list (${response.status}) — no pages will be prerendered`
			);
			return [];
		}

		const data = await response.json();
		const demoChatsList: Array<{ slug?: string; demo_id?: string }> = data.demo_chats || [];

		const slugEntries = demoChatsList
			.map((chat) => chat.slug || chat.demo_id)
			.filter((slug): slug is string => typeof slug === 'string' && slug.startsWith('demo-'))
			.map((slug) => ({ slug }));

		console.warn(
			`[demo/chat entries] Will prerender ${slugEntries.length} demo chat pages: ${slugEntries.map((e) => e.slug).join(', ')}`
		);

		return slugEntries;
	} catch (err) {
		console.error('[demo/chat entries] Error fetching slugs for prerendering:', err);
		// Return empty array — prerendering is optional; SSR fallback handles all slugs
		return [];
	}
};
