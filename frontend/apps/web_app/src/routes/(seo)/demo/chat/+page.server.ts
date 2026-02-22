// frontend/apps/web_app/src/routes/(seo)/demo/chat/+page.server.ts
//
// Server-side data loader for the demo chat listing/index page at /demo/chat/.
//
// ARCHITECTURE:
//   Fetches all published demo chats from the backend and groups them by category.
//   This page is SEO-optimized — crawlers index the full listing so individual
//   demo chat pages are discoverable from internal links.
//
//   Categories supported:
//     for_everyone    — General-purpose demos
//     for_developers  — Technical / dev-focused demos
//     news            — News and current events demos
//     learn           — Educational demos
//     features        — Feature showcase demos
//     example_chats   — Curated example conversations
//
// CACHE: public, s-maxage=3600 (1h CDN) + stale-while-revalidate=86400 (24h background refresh)

import { env } from '$env/dynamic/private';
import type { PageServerLoad } from './$types';

/** A demo chat entry as returned by GET /v1/demo/chats. */
interface DemoChatListItem {
	demo_id: string;
	slug: string;
	title: string;
	summary?: string;
	category?: string;
	icon?: string;
	demo_chat_category?: string;
	content_hash?: string;
	updated_at?: string;
	created_at?: string;
}

/** A demo chat grouped by category for display in the listing page. */
export interface DemoChatGroup {
	category: string;
	/** Human-readable label for this category (English only — SEO pages are English). */
	label: string;
	chats: DemoChatListItem[];
}

// Display order and labels for each category
const CATEGORY_CONFIG: Record<string, { label: string; order: number }> = {
	for_everyone: { label: 'For Everyone', order: 1 },
	learn: { label: 'Learn', order: 2 },
	features: { label: 'Features', order: 3 },
	example_chats: { label: 'Example Chats', order: 4 },
	for_developers: { label: 'For Developers', order: 5 },
	news: { label: 'News', order: 6 }
};

// Note: prerender / ssr / csr page options must be exported from +page.ts, not here.
// They are silently ignored in +page.server.ts. See (seo)/demo/chat/+page.ts.

export const load: PageServerLoad = async ({ fetch, setHeaders, url }) => {
	const backendUrl = env.BACKEND_URL || 'https://app.dev.openmates.org';

	let allChats: DemoChatListItem[] = [];

	try {
		const response = await fetch(`${backendUrl}/v1/demo/chats?lang=en`);

		if (response.ok) {
			const data = await response.json();
			allChats = (data.demo_chats || []) as DemoChatListItem[];
		} else {
			console.error(`[demo/chat] Backend returned ${response.status} for demo chats list`);
		}
	} catch (err) {
		console.error('[demo/chat] Failed to fetch demo chats list:', err);
		// Return empty list rather than 500 — the page renders with no chats
	}

	// Set cache headers for SSR fallback responses
	setHeaders({
		'Cache-Control': 'public, s-maxage=3600, stale-while-revalidate=86400'
	});

	// Group chats by category and sort groups by display order
	const groupMap = new Map<string, DemoChatListItem[]>();
	for (const chat of allChats) {
		const cat = chat.demo_chat_category || 'for_everyone';
		if (!groupMap.has(cat)) {
			groupMap.set(cat, []);
		}
		groupMap.get(cat)!.push(chat);
	}

	const groups: DemoChatGroup[] = Array.from(groupMap.entries())
		.map(([category, chats]) => ({
			category,
			label: CATEGORY_CONFIG[category]?.label ?? category,
			chats
		}))
		.sort((a, b) => {
			const orderA = CATEGORY_CONFIG[a.category]?.order ?? 99;
			const orderB = CATEGORY_CONFIG[b.category]?.order ?? 99;
			return orderA - orderB;
		});

	const canonicalUrl = `${url.origin}/demo/chat`;

	return {
		groups,
		totalCount: allChats.length,
		canonicalUrl
	};
};
