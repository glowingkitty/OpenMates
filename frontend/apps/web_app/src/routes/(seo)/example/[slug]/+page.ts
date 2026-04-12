// frontend/apps/web_app/src/routes/(seo)/example/[slug]/+page.ts
//
// Prerender configuration for individual example chat SEO pages.
// All example chats are known at build time — prerender them all as static HTML.

import type { EntryGenerator } from './$types';
import { getAllExampleChatData } from '@repo/ui';

export const prerender = 'auto';
export const ssr = true;
export const csr = true;

/**
 * EntryGenerator: produces the list of slugs to prerender at build time.
 * Since example chats are hardcoded, all slugs are known statically.
 */
export const entries: EntryGenerator = () => {
	return getAllExampleChatData().map(chat => ({ slug: chat.slug }));
};
