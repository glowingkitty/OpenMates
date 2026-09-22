import { expect, test } from './helpers/cookie-audit';

test.describe('public news, blog, and social publications', () => {
	// contract-test: direct surface=gui.web assertions=public-publications.seo.crawlable
	test('sends one article preview with a reachable image to crawlers', async ({ request }) => {
		for (const path of [
			'/news/introducing-openmates-v011',
			'/blog/better-guardrails-for-agentic-coding',
			'/social/workflow-automation-webinar'
		]) {
			const response = await request.get(path);
			expect(response.status()).toBe(200);
			const html = await response.text();
			for (const property of ['og:title', 'og:description', 'og:image', 'og:url']) {
				expect(html.match(new RegExp(`<meta property="${property}"`, 'g'))).toHaveLength(1);
			}
			expect(html.match(/<meta name="description"/g)).toHaveLength(1);
			expect(html.split('</head>')[0]).not.toContain('Your AI team for getting things done');
			const imageUrl = html.match(/<meta property="og:image" content="([^"]+)"/)?.[1];
			expect(imageUrl).toMatch(/^https?:\/\//);
			const image = await request.get(imageUrl!);
			expect(image.status()).toBe(200);
			expect(image.headers()['content-type']).toMatch(/^image\//);
		}
	});

	// contract-test: direct surface=gui.web assertions=public-publications.content.media-groups,public-publications.seo.crawlable
	test('renders the illustrated blog without cropping or overflowing on mobile', async ({ page }) => {
		await page.setViewportSize({ width: 390, height: 844 });
		await page.goto('/blog/better-guardrails-for-agentic-coding');
		await expect(page.getByRole('heading', { level: 1, name: 'Don’t fly blind: Better guardrails for agentic coding' })).toBeVisible();
		const article = page.locator('.article-markdown');
		const images = article.locator('img');
		await expect(images).toHaveCount(15);
		await expect(article.getByRole('link', { name: 'Projects are now a conversation with Claude' })).toHaveAttribute('href', 'https://www.youtube.com/watch?v=5qt_aGyAsKk');
		await expect(article.getByRole('link', { name: 'Projects are now a conversation with Claude' })).toHaveAttribute('target', '_blank');
		await expect(article.getByRole('link', { name: 'Projects are now a conversation with Claude' })).toHaveAttribute('rel', 'noopener noreferrer');
		await expect(images.first()).toHaveAttribute('src', /^\/publications\/blog\//);
		await expect(images.first().locator('..')).toHaveAttribute('href', /^https:\/\/openmates-buffer-media\.nbg1\.your-objectstorage\.com\/publications\/blog\//);
		await expect(images.first().locator('..')).toHaveAttribute('target', '_blank');
		await expect(images.first().locator('..')).toHaveAttribute('rel', 'noopener noreferrer');
		await expect(page.locator('.publication-hero .play-button')).toHaveCount(0);
		await expect(page.getByTestId('newsroom-slideshow')).toHaveCount(0);
		const authorLink = page.getByRole('link', { name: "Open Marco's LinkedIn profile" });
		await expect(authorLink).toHaveAttribute('href', 'https://www.linkedin.com/in/marco0/');
		await expect(authorLink).toHaveAttribute('target', '_blank');
		await expect(authorLink.locator('img')).toHaveAttribute('src', '/publications/authors/marco.jpg');
		await expect(page.getByRole('heading', { name: 'Latest news' })).toBeVisible();
		await expect(page.locator('.publication-header .logo-link')).toHaveAttribute('href', '/blog');
		await expect.poll(() => images.first().evaluate((image: HTMLImageElement) => image.complete && image.naturalWidth > 0)).toBe(true);
		const size = await images.first().evaluate((image) => image.getBoundingClientRect().toJSON());
		expect(size.width / size.height).toBeCloseTo(16 / 9, 1);
		expect(size.right).toBeLessThanOrEqual(390);
		await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
	});

	// contract-test: direct surface=gui.web assertions=public-publications.routes.localized-archives,public-publications.seo.crawlable
	test('renders the translated German blog at its localized canonical route', async ({ page }) => {
		await page.goto('/de/blog/better-guardrails-for-agentic-coding');
		await expect(page.getByRole('heading', { level: 1, name: 'Nicht im Blindflug: Bessere Leitplanken für agentisches Programmieren' })).toBeVisible();
		await expect(page.getByText('Marco', { exact: true })).toBeVisible();
		await expect(page.getByText('Gründer von OpenMates.', { exact: true })).toBeVisible();
		await expect(page.getByRole('heading', { name: 'Neueste Meldungen' })).toBeVisible();
		await expect(page.locator('.publication-header .logo-link')).toHaveAttribute('href', '/de/blog');
	});


	// contract-test: direct surface=gui.web assertions=public-publications.routes.localized-archives
	test('loads publication design tokens on direct visits in light and dark themes', async ({ page }) => {
		for (const route of ['/news', '/blog', '/social/workflow-automation-webinar']) {
			await page.goto(route, { waitUntil: 'domcontentloaded' });
			await expect(page.getByTestId('newsroom-surface')).toBeVisible();
			await expect(page.getByTestId('sidebar-toggle')).not.toHaveCSS('mask-image', 'none');
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
			await expect(page.locator('.publication-header .logo-link')).toHaveAttribute('href', route === '/blog' ? '/blog' : '/news');
		}
	});

	// contract-test: direct surface=gui.web assertions=public-publications.routes.localized-archives
	test('keeps the archive closed initially and searches every publication section', async ({ page }) => {
		await page.goto('/news', { waitUntil: 'domcontentloaded' });
		await expect(page.getByRole('complementary', { name: 'Newsroom archive' })).toBeHidden();
		await page.getByTestId('sidebar-toggle').click();
		await page.getByTestId('sidebar-search').click();
		const sidebarSearch = page.getByTestId('sidebar-search-input');
		await expect(sidebarSearch).toBeFocused();
		await sidebarSearch.fill('v0.11');
		await expect(page.getByRole('complementary', { name: 'Newsroom archive' }).getByText(/v0.11/)).toBeVisible();
		await page.getByTestId('sidebar-toggle').click();
		await page.getByTestId('newsroom-search-toggle').click();
		const search = page.getByTestId('newsroom-search-input');
		await expect(search).toBeFocused();
		await search.fill('privacy');
		await expect(page.getByRole('heading', { name: 'Social media' })).toBeVisible();
		await expect(page.getByRole('heading', { name: 'Press coverage' })).toBeVisible();
		await expect(page.getByRole('heading', { name: 'Latest blog posts' })).toBeVisible();
		await expect(page.getByTestId('newsroom-card-news-introducing-openmates-v011')).toHaveCount(0);
	});

	// contract-test: direct surface=gui.web assertions=public-publications.routes.localized-archives,public-publications.seo.crawlable,public-publications.news.released-announcements
	test('renders localized archives and released announcement details in server HTML', async ({ request }) => {
		const news = await request.get('/news');
		expect(news.status()).toBe(200);
		const newsHtml = await news.text();
		expect(newsHtml).toContain('data-testid="newsroom-surface"');
		expect(newsHtml).toContain('v0.11');
		expect(newsHtml).toContain('/publications/openmates-ui-fallback.png');
		expect(newsHtml).not.toContain('Show all');
		expect(newsHtml).toContain('rel="canonical"');
		expect(newsHtml).toContain('hreflang="de"');
		expect(newsHtml).toContain('"@type":"CollectionPage"');

		const release = await request.get('/news/introducing-openmates-v011');
		expect(release.status()).toBe(200);
		const releaseHtml = await release.text();
		expect(releaseHtml).toContain('"@type":"NewsArticle"');
		expect(releaseHtml).toContain('Code execution');

		for (const blogPostPath of [
			'/blog/privacy-as-a-product-feature',
			'/de/blog/privacy-as-a-product-feature'
		]) {
			const blogPost = await request.get(blogPostPath);
			expect(blogPost.status()).toBe(404);
		}

		const sitemap = await request.get('/sitemap.xml');
		const sitemapXml = await sitemap.text();
		expect(sitemapXml).toContain('/news/introducing-openmates-v011');
		expect(sitemapXml).not.toContain('/blog/privacy-as-a-product-feature');
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
