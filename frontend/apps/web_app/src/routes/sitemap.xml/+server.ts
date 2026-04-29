// frontend/apps/web_app/src/routes/sitemap.xml/+server.ts
//
// Dynamic XML sitemap served at /sitemap.xml.
//
// ARCHITECTURE:
//   Generates a valid XML sitemap including:
//     - The homepage (/)
//     - The example chat listing index page (/example/)
//     - Each individual example chat SEO page (/example/{slug})
//     - Intro chat SEO pages (/intro/{slug})
//     - Documentation pages (/docs/{slug})
//
//   Example chats are hardcoded in the frontend — no backend API calls needed.
//
//   Cache: public, s-maxage=3600 so the CDN caches for 1 hour.
//   The robots.txt at /robots.txt already points to this sitemap.

import type { RequestHandler } from './$types';
import { getAllExampleChatData, getAllActiveNewsletterChats, newsletterKindFromChatId, LEGAL_CHATS } from '@repo/ui';
import docsData from '$lib/generated/docs-data.json';
import type { DocFolder, DocStructure } from '$lib/types/docs';

export const prerender = false; // SSR so the sitemap always reflects the current build

// Build timestamp — set once at deploy time, honest and stable across requests.
// Unlike `new Date()` per request, this doesn't change every hit, so crawlers
// see a consistent date that only advances on actual deployments.
const BUILD_DATE = new Date().toISOString().split('T')[0];

export const GET: RequestHandler = async ({ url }) => {
	const siteOrigin = url.origin;

	// Block sitemap on dev/staging hostnames — only production should be indexed.
	const hostname = url.hostname;
	const isDevHost =
		hostname.includes('.dev.') ||
		hostname.startsWith('dev.') ||
		hostname === 'localhost' ||
		hostname === '127.0.0.1';
	if (isDevHost) {
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

	// Static pages
	const staticUrls = [
		// Homepage — highest priority page
		`  <url>
    <loc>${siteOrigin}/</loc>
    <changefreq>weekly</changefreq>
    <priority>1.0</priority>
  </url>`,
		// Example chat listing page
		`  <url>
    <loc>${siteOrigin}/example</loc>
    <changefreq>weekly</changefreq>
    <priority>0.8</priority>
  </url>`,
		// Intro chat SEO pages
		`  <url>
    <loc>${siteOrigin}/intro/for-everyone</loc>
    <lastmod>${BUILD_DATE}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.9</priority>
  </url>`,
		`  <url>
    <loc>${siteOrigin}/intro/privacy</loc>
    <lastmod>${BUILD_DATE}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.9</priority>
  </url>`,
		`  <url>
    <loc>${siteOrigin}/intro/safety</loc>
    <lastmod>${BUILD_DATE}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.9</priority>
  </url>`,
		`  <url>
    <loc>${siteOrigin}/intro/for-developers</loc>
    <lastmod>${BUILD_DATE}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.9</priority>
  </url>`,
		`  <url>
    <loc>${siteOrigin}/intro/who-develops-openmates</loc>
    <lastmod>${BUILD_DATE}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.9</priority>
  </url>`
	];

	// Legal document pages — now have SSR SEO pages at /legal/{slug}
	const legalUrls = LEGAL_CHATS.map((chat) => `  <url>
    <loc>${siteOrigin}/legal/${chat.slug}</loc>
    <changefreq>monthly</changefreq>
    <priority>0.6</priority>
  </url>`);

	// Example chat pages (hardcoded static data — no backend fetch needed)
	const exampleChats = getAllExampleChatData();
	const exampleUrls = exampleChats.map((chat) => {
		return `  <url>
    <loc>${siteOrigin}/example/${chat.slug}</loc>
    <changefreq>weekly</changefreq>
    <priority>0.7</priority>
  </url>`;
	});

	// Newsletter-derived announcements + tips pages. Each issue published via
	// publish_newsletter.py becomes one DemoChat entry here, and is_active=false
	// drops it from the sitemap (so soft-deleted tips 404 for crawlers).
	const newsletterUrls = getAllActiveNewsletterChats()
		.map((chat) => {
			const kind = newsletterKindFromChatId(chat.chat_id);
			if (!kind) return null;
			return `  <url>
    <loc>${siteOrigin}/${kind}/${chat.slug}</loc>
    <changefreq>monthly</changefreq>
    <priority>0.7</priority>
  </url>`;
		})
		.filter((u): u is string => u !== null);

	// Documentation pages from statically bundled docs-data.json
	const docsUrls: string[] = [];
	function collectDocSlugs(folder: DocFolder | DocStructure) {
		for (const file of folder.files) {
			docsUrls.push(`  <url>\n    <loc>${siteOrigin}/docs/${file.slug}</loc>\n    <changefreq>weekly</changefreq>\n    <priority>0.6</priority>\n  </url>`);
		}
		for (const sub of folder.folders) {
			collectDocSlugs(sub);
		}
	}
	collectDocSlugs(docsData.structure as DocStructure);
	docsUrls.unshift(`  <url>\n    <loc>${siteOrigin}/docs</loc>\n    <changefreq>weekly</changefreq>\n    <priority>0.8</priority>\n  </url>`);

	const xml = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${staticUrls.join('\n')}
${docsUrls.join('\n')}
${legalUrls.join('\n')}
${exampleUrls.join('\n')}
${newsletterUrls.join('\n')}
</urlset>`;

	return new Response(xml, {
		headers: {
			'Content-Type': 'application/xml; charset=utf-8',
			'Cache-Control': 'public, s-maxage=3600, stale-while-revalidate=86400'
		}
	});
};
