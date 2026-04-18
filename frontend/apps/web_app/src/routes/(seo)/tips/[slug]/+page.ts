// frontend/apps/web_app/src/routes/(seo)/tips/[slug]/+page.ts
//
// Prerender configuration for individual tip newsletter pages.
// All tip chats are known at build time (registered in
// newsletterChatStore.ts via publish_newsletter.py) — prerender each as
// static HTML so crawlers and link-preview bots get a fully-rendered page.

import type { EntryGenerator } from './$types';
import { getAllActiveNewsletterChats, newsletterKindFromChatId } from '@repo/ui';

export const prerender = true;
export const ssr = true;
export const csr = true;

export const entries: EntryGenerator = () => {
	return getAllActiveNewsletterChats()
		.filter((chat) => newsletterKindFromChatId(chat.chat_id) === 'tips')
		.map((chat) => ({ slug: chat.slug }));
};
