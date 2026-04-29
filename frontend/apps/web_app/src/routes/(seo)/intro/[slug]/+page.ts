// frontend/apps/web_app/src/routes/(seo)/intro/[slug]/+page.ts
//
// Prerender configuration for intro chat SEO pages at /intro/[slug].
//
// ARCHITECTURE:
//   Intro chats are bundled statically with the frontend — no backend API call
//   needed. We prerender all known slugs at build time, producing zero-cost
//   static HTML files.
//
//   Unlike the community demo chat pages (prerender='auto' with SSR fallback),
//   these are fully static: the set of slugs is fixed in code, so prerender=true
//   is safe and eliminates any SSR cost.
//
//   See also: +page.server.ts (data loading), +page.svelte (HTML + redirect)
//   Architecture reference: docs/architecture/ (web-app, SEO page pattern)

import type { EntryGenerator } from './$types';

// Fully static — all slugs are known at build time, no SSR fallback needed
export const prerender = true;

// SSR must be true for server-side rendering (required for prerender)
export const ssr = true;

// CSR allows hydration so the onMount redirect fires in human browsers
export const csr = true;

/**
 * The intro chats bundled with the frontend.
 * These slugs must match the `slug` field on each DemoChat in:
 *   frontend/packages/ui/src/demo_chats/data/
 */
export const entries: EntryGenerator = () => {
	return [
		{ slug: 'for-everyone' },
		{ slug: 'privacy' },
		{ slug: 'safety' },
		{ slug: 'for-developers' },
		{ slug: 'who-develops-openmates' }
	];
};
