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

import type { RequestHandler } from './$types';
import { getBackendUrl } from '$lib/backendUrl';

interface DemoChatListItem {
	slug?: string;
	demo_id?: string;
	updated_at?: string;
}

export const prerender = false; // Always SSR so new demo chats appear without rebuilding

export const GET: RequestHandler = async ({ fetch, url }) => {
	const siteOrigin = url.origin;

	// Block sitemap on dev/staging hostnames — we only want production to be indexed.
	// Matches the same logic used in robots.txt/+server.ts.
	const hostname = url.hostname;
	const isDevHost =
		hostname.includes('.dev.') ||
		hostname.startsWith('dev.') ||
		hostname === 'localhost' ||
		hostname === '127.0.0.1';
	if (isDevHost) {
		// Return an empty (but valid) sitemap so crawlers don't get a parse error,
		// while ensuring no URLs are submitted for indexing on dev/staging.
		return new Response(
			'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n</urlset>',
			{
				headers: {
					'Content-Type': 'application/xml; charset=utf-8',
					'Cache-Control': 'no-store'
				}
			}
		);
	}

	const backendUrl = getBackendUrl(url);

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
		// Demo chat listing/index page (no trailing slash — matches canonicalUrl in +page.server.ts)
		`  <url>
    <loc>${siteOrigin}/demo/chat</loc>
    <lastmod>${today}</lastmod>
    <changefreq>daily</changefreq>
    <priority>0.8</priority>
  </url>`,
		// Intro chat SEO pages — static, bundled with the frontend (not backend-fetched)
		// Priority 0.9: higher than community demo chats (0.7) — these are core app introduction pages
		`  <url>
    <loc>${siteOrigin}/intro/for-everyone</loc>
    <lastmod>${today}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.9</priority>
  </url>`,
		`  <url>
    <loc>${siteOrigin}/intro/for-developers</loc>
    <lastmod>${today}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.9</priority>
  </url>`,
		`  <url>
    <loc>${siteOrigin}/intro/who-develops-openmates</loc>
    <lastmod>${today}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.9</priority>
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
