import { expect, test } from './helpers/cookie-audit';

test.describe('public news, blog, and social publications', () => {
	// contract-test: direct surface=gui.web assertions=public-publications.routes.localized-archives
	test('loads publication design tokens on direct visits in light and dark themes', async ({ page }) => {
		for (const route of ['/news', '/blog', '/social/workflow-automation-webinar']) {
			await page.goto(route, { waitUntil: 'domcontentloaded' });
			await expect(page.getByTestId('newsroom-surface')).toBeVisible();
			for (const theme of ['light', 'dark']) {
				await page.evaluate((value) => document.documentElement.dataset.theme = value, theme);
				const styles = await page.getByTestId('newsroom-surface').evaluate((surface) => {
					const style = getComputedStyle(surface);
					return {
						spacing: style.getPropertyValue('--spacing-8').trim(),
						font: style.getPropertyValue('--font-size-small').trim(),
						foreground: style.getPropertyValue('--color-font-primary').trim(),
						background: style.getPropertyValue('--color-grey-0').trim(),
						gradient: style.getPropertyValue('--gradient-primary').trim()
					};
				});
				for (const value of Object.values(styles)) expect(value).not.toBe('');
				if (route !== '/social/workflow-automation-webinar') {
					await expect(page.locator('.publication-hero')).not.toHaveCSS('background-image', 'none');
					await expect(page.locator('.publication-hero')).not.toHaveCSS('padding-left', '0px');
				}
			}
		}
	});

	// contract-test: direct surface=gui.web assertions=public-publications.routes.localized-archives,public-publications.seo.crawlable,public-publications.news.released-announcements
	test('renders localized archives and released announcement details in server HTML', async ({ request }) => {
		const news = await request.get('/news');
		expect(news.status()).toBe(200);
		const newsHtml = await news.text();
		expect(newsHtml).toContain('data-testid="newsroom-surface"');
		expect(newsHtml).toContain('v0.11');
		expect(newsHtml).toContain('rel="canonical"');
		expect(newsHtml).toContain('hreflang="de"');
		expect(newsHtml).toContain('"@type":"CollectionPage"');

		const release = await request.get('/news/introducing-openmates-v011');
		expect(release.status()).toBe(200);
		const releaseHtml = await release.text();
		expect(releaseHtml).toContain('"@type":"NewsArticle"');
		expect(releaseHtml).toContain('Code execution');

		const germanBlog = await request.get('/de/blog/privacy-as-a-product-feature');
		expect(germanBlog.status()).toBe(200);
		const blogHtml = await germanBlog.text();
		expect(blogHtml).toContain('Datenschutz sollte KI nützlicher machen');
		expect(blogHtml).toContain('"@type":"BlogPosting"');

		const sitemap = await request.get('/sitemap.xml');
		const sitemapXml = await sitemap.text();
		expect(sitemapXml).toContain('/news/introducing-openmates-v011');
		expect(sitemapXml).toContain('/de/blog/privacy-as-a-product-feature');
		expect(sitemapXml).toContain('/social/workflow-automation-webinar');
	});

	// contract-test: direct surface=gui.web assertions=public-publications.social.official-backfill,public-publications.media.read-only-delivery
	test('shows exact platform permalinks and owned media for an archived social post', async ({ page }) => {
		await page.goto('/social/workflow-automation-webinar', { waitUntil: 'domcontentloaded' });
		await expect(page.getByRole('heading', { name: /What if you did not have to constantly search/i })).toBeVisible();
		await expect(page.getByText(/constantly check for new apartments or doctor appointments/i)).toBeVisible();
		const links = page.getByRole('navigation', { name: 'Open original post' }).getByRole('link');
		await expect(links).toHaveCount(3);
		await expect(page.getByTestId('social-platform-link-bluesky')).toHaveAttribute('href', /bsky\.app\/profile\/.+\/post\//);
		await expect(page.getByTestId('social-platform-link-instagram')).toHaveAttribute('href', /instagram\.com\/reel\//);
		await expect(page.getByTestId('social-platform-link-mastodon')).toHaveAttribute('href', /mastodon\.social\/@OpenMates\//);
		await expect(page.locator('.social-detail-media video')).toHaveAttribute(
			'src',
			'https://openmates-buffer-media.nbg1.your-objectstorage.com/publications/social/46b4c44c713821cb-workflow-automation-webinar.mp4'
		);
		await expect(page.locator('.social-detail-media video')).toHaveAttribute(
			'poster',
			'/publications/social/workflow-automation-webinar.jpg'
		);
	});

	// contract-test: direct surface=gui.web assertions=public-publications.news.released-announcements
	test('redirects a legacy announcement URL to its stable news URL', async ({ request }) => {
		const response = await request.get('/announcements/introducing-openmates-v011', { maxRedirects: 0 });
		expect(response.status()).toBe(308);
		expect(response.headers().location).toBe('/news/introducing-openmates-v011');

		const retiredDemo = await request.get('/announcements/referral-feature-launch', { maxRedirects: 0 });
		expect(retiredDemo.status()).toBe(308);
		expect(retiredDemo.headers().location).toBe('/news');
	});
});
