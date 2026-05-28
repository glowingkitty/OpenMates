// frontend/apps/web_app/scripts/audit-example-seo.js
//
// Build-time SEO audit for prerendered example chat pages.
// Runs after `vite build` so it validates the actual raw HTML that crawlers see,
// not just source data. The checks intentionally stay regex-based to avoid
// adding another parser dependency to the web app build.
//
// Fails on unresolved i18n keys, duplicate SEO tags, missing JSON-LD, missing
// canonicals, or thin example transcript content.

import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { join, relative } from 'node:path';
import { pathToFileURL } from 'node:url';

const PAGES_DIR = '.svelte-kit/output/prerendered/pages';
const SITEMAP_SERVER_ENTRY = '.svelte-kit/output/server/entries/endpoints/sitemap.xml/_server.ts.js';
const MIN_TRANSCRIPT_WORDS = 120;

function walkHtmlFiles(dir) {
	const files = [];
	for (const entry of readdirSync(dir, { withFileTypes: true })) {
		const fullPath = join(dir, entry.name);
		if (entry.isDirectory()) {
			files.push(...walkHtmlFiles(fullPath));
		} else if (entry.isFile() && entry.name.endsWith('.html')) {
			files.push(fullPath);
		}
	}
	return files;
}

function countMatches(html, pattern) {
	return [...html.matchAll(pattern)].length;
}

function textContent(html) {
	return html
		.replace(/<script[\s\S]*?<\/script>/gi, ' ')
		.replace(/<style[\s\S]*?<\/style>/gi, ' ')
		.replace(/<[^>]+>/g, ' ')
		.replace(/&[^;]+;/g, ' ')
		.replace(/\s+/g, ' ')
		.trim();
}

function assertCount(errors, label, html, pattern, expected) {
	const count = countMatches(html, pattern);
	if (count !== expected) {
		errors.push(`${label}: expected ${expected}, found ${count}`);
	}
}

function auditExamplePage(filePath) {
	const html = readFileSync(filePath, 'utf8');
	const relPath = relative(process.cwd(), filePath);
	const errors = [];

	if (html.includes('example_chats.')) {
		errors.push('contains unresolved example_chats.* i18n keys');
	}

	assertCount(errors, 'title', html, /<title[\s>]/gi, 1);
	assertCount(errors, 'meta description', html, /<meta\s+name="description"/gi, 1);
	assertCount(errors, 'canonical', html, /<link\s+rel="canonical"/gi, 1);
	assertCount(errors, 'robots', html, /<meta\s+name="robots"/gi, 1);
	assertCount(errors, 'og:title', html, /<meta\s+property="og:title"/gi, 1);
	assertCount(errors, 'og:description', html, /<meta\s+property="og:description"/gi, 1);
	assertCount(errors, 'og:image', html, /<meta\s+property="og:image"/gi, 1);
	assertCount(errors, 'twitter:title', html, /<meta\s+name="twitter:title"/gi, 1);
	assertCount(errors, 'twitter:description', html, /<meta\s+name="twitter:description"/gi, 1);
	assertCount(errors, 'twitter:image', html, /<meta\s+name="twitter:image"/gi, 1);
	assertCount(errors, 'JSON-LD', html, /<script\s+type="application\/ld\+json"/gi, 1);

	if (!/<main[\s>]/i.test(html) || !/<article[\s>]/i.test(html)) {
		errors.push('missing crawlable main/article content');
	}
	if (!html.includes('OpenMates:')) {
		errors.push('missing readable OpenMates transcript speaker label');
	}
	if (!html.includes('User:')) {
		errors.push('missing readable user transcript speaker label');
	}

	const wordCount = textContent(html).split(/\s+/).filter(Boolean).length;
	if (wordCount < MIN_TRANSCRIPT_WORDS) {
		errors.push(`too-thin content: ${wordCount} words, expected at least ${MIN_TRANSCRIPT_WORDS}`);
	}

	const jsonLdMatch = html.match(/<script\s+type="application\/ld\+json">([\s\S]*?)<\/script>/i);
	if (jsonLdMatch) {
		try {
			const jsonLd = JSON.parse(jsonLdMatch[1]);
			if (jsonLd['@type'] !== 'Article') {
				errors.push(`JSON-LD @type is ${jsonLd['@type']}, expected Article`);
			}
			if (!jsonLd.headline || !jsonLd.description || !jsonLd.mainEntityOfPage?.['@id']) {
				errors.push('JSON-LD is missing headline, description, or mainEntityOfPage @id');
			}
			if (!jsonLd.dateModified) {
				errors.push('JSON-LD is missing dateModified');
			}
		} catch (error) {
			errors.push(`JSON-LD is not valid JSON: ${error.message}`);
		}
	}

	return errors.map((error) => `${relPath}: ${error}`);
}

async function auditSitemap(exampleFiles) {
	if (!existsSync(SITEMAP_SERVER_ENTRY)) {
		return [`Compiled sitemap endpoint missing: ${SITEMAP_SERVER_ENTRY}`];
	}

	const { GET } = await import(pathToFileURL(join(process.cwd(), SITEMAP_SERVER_ENTRY)).href);
	const response = await GET({ url: new URL('https://openmates.org/sitemap.xml') });
	const sitemapXml = await response.text();
	const errors = [];

	for (const filePath of exampleFiles) {
		const slug = relative(join(PAGES_DIR, 'example'), filePath).replace(/\.html$/, '');
		const entryPattern = new RegExp(
			`<loc>https://openmates\\.org/example/${slug}</loc>\\s*<lastmod>\\d{4}-\\d{2}-\\d{2}</lastmod>`
		);
		if (!entryPattern.test(sitemapXml)) {
			errors.push(`/example/${slug} missing from sitemap with lastmod`);
		}
	}

	return errors;
}

if (!existsSync(PAGES_DIR)) {
	throw new Error(`Prerender output missing: ${PAGES_DIR}`);
}

const exampleFiles = walkHtmlFiles(PAGES_DIR).filter((filePath) => {
	const relPath = relative(PAGES_DIR, filePath).replace(/\\/g, '/');
	return relPath.startsWith('example/') && relPath !== 'example/index.html';
});

if (exampleFiles.length === 0) {
	throw new Error('No prerendered /example/{slug} pages found to audit.');
}

const errors = exampleFiles.flatMap(auditExamplePage);
errors.push(...(await auditSitemap(exampleFiles)));

if (errors.length > 0) {
	console.error('Example chat SEO audit failed:');
	for (const error of errors) {
		console.error(`- ${error}`);
	}
	process.exit(1);
}

console.log(`Example chat SEO audit passed for ${exampleFiles.length} pages.`);
// Importing the compiled SvelteKit sitemap endpoint also imports app-level
// modules that register timers/WebSocket handlers. End explicitly so the audit
// remains a deterministic build gate instead of hanging on open handles.
process.exit(0);
