// frontend/apps/web_app/src/routes/sitemap.xml/+server.ts
//
// Dynamic XML sitemap served at /sitemap.xml.
//
// ARCHITECTURE:
//   Fetches all published demo chat slugs from the backend at request time and
//   generates a valid XML sitemap. Includes:
//     - The demo chat listing index page (/demo/chat/)
//     - Each individual demo chat SEO page (/demo/chat/{slug})
//     - Static pages: home, docs pages (if any)
//
//   Cache: public, s-maxage=3600 so the CDN caches for 1 hour and regenerates
//   automatically in the background. Crawlers that re-request the sitemap every
//   few days will always get an up-to-date copy without hitting the origin.
//
//   The robots.txt at /robots.txt already points to this sitemap.

import { env } from '$env/dynamic/private';
import type { RequestHandler } from './$types';

interface DemoChatListItem {
	slug?: string;
	demo_id?: string;
	updated_at?: string;
}

export const prerender = false; // Always SSR so new demo chats appear without rebuilding

export const GET: RequestHandler = async ({ fetch, url }) => {
	const siteOrigin = url.origin;
	const backendUrl = env.BACKEND_URL || 'https://app.dev.openmates.org';

	// Fetch all published demo chats to include in sitemap
	let demoChats: DemoChatListItem[] = [];
	try {
		const response = await fetch(`${backendUrl}/v1/demo/chats?lang=en`);
		if (response.ok) {
			const data = await response.json();
			demoChats = (data.demo_chats || []) as DemoChatListItem[];
		} else {
			console.error(`[sitemap.xml] Backend returned ${response.status} for demo chats list`);
		}
	} catch (err) {
		console.error('[sitemap.xml] Failed to fetch demo chats list:', err);
		// Serve sitemap with only static pages — better than failing completely
	}

	// Filter to only valid slug-based chats (slug starts with 'demo-')
	const validChats = demoChats.filter((chat) => {
		const slug = chat.slug || chat.demo_id || '';
		return slug.startsWith('demo-');
	});

	// Today's date as W3C datetime (YYYY-MM-DD) — used as lastmod for static pages
	const today = new Date().toISOString().split('T')[0];

	// Build XML entries
	const staticUrls = [
		// Demo chat listing/index page
		`  <url>
    <loc>${siteOrigin}/demo/chat/</loc>
    <lastmod>${today}</lastmod>
    <changefreq>daily</changefreq>
    <priority>0.8</priority>
  </url>`
	];

	const demoUrls = validChats.map((chat) => {
		const slug = chat.slug || chat.demo_id || '';
		// Use the chat's updated_at if available, otherwise fall back to today
		const lastmod = chat.updated_at ? chat.updated_at.split('T')[0] : today;
		return `  <url>
    <loc>${siteOrigin}/demo/chat/${slug}</loc>
    <lastmod>${lastmod}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>0.7</priority>
  </url>`;
	});

	const xml = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${staticUrls.join('\n')}
${demoUrls.join('\n')}
</urlset>`;

	return new Response(xml, {
		headers: {
			'Content-Type': 'application/xml; charset=utf-8',
			'Cache-Control': 'public, s-maxage=3600, stale-while-revalidate=86400'
		}
	});
};
