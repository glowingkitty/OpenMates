// frontend/apps/web_app/src/routes/(seo)/events/[slug]/+page.ts
//
// Prerender configuration for public event SEO pages. OpenMates event records
// are generated static data, so every known slug can be built into static HTML
// while still hydrating in browsers for the SPA embed redirect.

import type { EntryGenerator } from './$types';
import { getAllOpenMatesEvents } from '@repo/ui';

export const prerender = true;
export const ssr = true;
export const csr = true;

export const entries: EntryGenerator = () => {
	return getAllOpenMatesEvents().map((event) => ({ slug: event.slug }));
};
