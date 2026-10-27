import { describe, expect, it } from 'vitest';
import { loadPublicationPage, getPublicationSitemapEntries } from '../../../../../packages/public-site/src/publications/publications';
import { isOfficialOpenMatesPublicationHost } from './publicationHosting';

describe('official publication hosting', () => {
	// contract-test: direct surface=gui.web assertions=public-publications.routes.localized-archives
	it('serves publications on OpenMates cloud and local development hosts', () => {
		expect(isOfficialOpenMatesPublicationHost('openmates.org')).toBe(true);
		expect(isOfficialOpenMatesPublicationHost('app.openmates.org')).toBe(true);
		expect(isOfficialOpenMatesPublicationHost('app.dev.openmates.org')).toBe(true);
		expect(isOfficialOpenMatesPublicationHost('localhost')).toBe(true);
	});

	// contract-test: direct surface=gui.web assertions=public-publications.routes.localized-archives
	it('keeps publications disabled on self-hosted domains', () => {
		expect(isOfficialOpenMatesPublicationHost('openmates.example')).toBe(false);
		expect(isOfficialOpenMatesPublicationHost('openmates-selfhost.vercel.app')).toBe(false);
		expect(isOfficialOpenMatesPublicationHost('localhost', 'self_hosted')).toBe(false);
		expect(isOfficialOpenMatesPublicationHost('openmates.org', 'self_hosted')).toBe(false);
	});
});


describe('localized publication slugs', () => {
	// contract-test: direct surface=gui.web assertions=public-publications.routes.localized-archives,public-publications.seo.crawlable
	it('maps canonical and alternate URLs by stable publication ID in both directions', () => {
		const en = '/blog/build-with-ai-openmates-rest-api-cli-sdk';
		const de = '/de/blog/mit-ki-entwickeln-openmates-rest-api-cli-sdk';
		for (const [locale, path, alternatePath] of [['en', en, de], ['de', de, en]] as const) {
			const data = loadPublicationPage({ locale, section: 'blog', slug: path.split('/').at(-1)!, url: new URL(`https://openmates.org${path}`) });
			expect(data.canonicalUrl).toBe(`https://openmates.org${path}`);
			expect(data.alternateUrl).toBe(`https://openmates.org${alternatePath}`);
			expect(data.linksById['blog-build-with-ai-openmates-rest-api-cli-sdk']).toBe(path);
			expect(getPublicationSitemapEntries()).toContainEqual(expect.objectContaining({ locale, path, alternatePath }));
		}
	});

	// contract-test: direct surface=gui.web assertions=public-publications.routes.localized-archives
	it('preserves legacy routes and English content when no German translation exists', () => {
		const entries = getPublicationSitemapEntries();
		expect(entries).toContainEqual(expect.objectContaining({ path: '/de/blog/better-guardrails-for-agentic-coding', alternatePath: '/blog/better-guardrails-for-agentic-coding' }));
		expect(entries).toContainEqual(expect.objectContaining({ path: '/de/social/workflow-automation-webinar', alternatePath: '/social/workflow-automation-webinar' }));
		const fallback = loadPublicationPage({ locale: 'de', section: 'social', slug: 'workflow-automation-webinar', url: new URL('https://openmates.org/de/social/workflow-automation-webinar') });
		expect(fallback.pageTitle).toMatch(/What if you did not have to constantly search/i);
	});
});
