import { expect, test } from './helpers/cookie-audit';
import { app, site, useWebsitePreview, watchPrivateStartup } from './helpers/website-preview';

// playwright-account: not_required reason=isolated_runner_local_public_website
useWebsitePreview();

// contract-test: direct surface=gui.web assertions=marketing-landing.destinations,public-example-chats.seo.crawlable
test('legacy website example links redirect to the configured app with their path and query', async ({ page, request }) => {
  for (const route of [
    '/example',
    '/example/',
    '/example/rust-vector-database-repos?lang=de&source=readme',
    '/example/removed-example?source=old-link'
  ]) {
    for (const method of ['GET', 'HEAD']) {
      const response = await request.fetch(site(route), { method, maxRedirects: 0 });
      expect(response.status(), `${method} ${route}`).toBe(302);
      expect(response.headers().location).toBe(`${app}${route}`);
    }
  }

  await page.goto(site('/example/rust-vector-database-repos?source=readme'), { waitUntil: 'domcontentloaded' });
  await expect.poll(() => new URL(page.url()).origin).toBe(app);
  await expect(page.getByTestId('chat-history-content')).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId('chat-history-content')).toHaveAttribute('data-source-message-count', /^[1-9]\d*$/);
});

// contract-test: direct surface=gui.web assertions=marketing-landing.independent-scroll,marketing-landing.destinations,marketing-landing.public-content
test('broken website page links recover to the landing page without changing endpoint 404s', async ({ page, request }) => {
  const noPrivateStartup = watchPrivateStartup(page);
  await page.emulateMedia({ reducedMotion: 'reduce' });
  for (const route of [
    '/missing-page?source=broken-link',
    '/nested/missing-page',
    '/examples-not-a-chat',
    '/legal/missing-document',
    '/blog/missing-article',
    '/de/news/missing-article'
  ]) {
    const response = await request.get(site(route), { maxRedirects: 0 });
    expect(response.status(), route).toBe(302);
    expect(response.headers().location, route).toBe('/');
    await page.goto(site(route), { waitUntil: 'domcontentloaded' });
    await expect(page).toHaveURL(site('/'));
    await expect(page.getByTestId('landing-page')).toBeVisible();
    await expect(page).toHaveTitle('OpenMates — Your privacy first AI team mates');
  }
  const head = await request.head(site('/nested/missing-page'), { maxRedirects: 0 });
  expect(head.status()).toBe(302);
  expect(head.headers().location).toBe('/');
  const sitemap = await request.get(site('/sitemap.xml'), { maxRedirects: 0, headers: { Accept: 'text/html' } });
  expect(sitemap.status()).toBe(404);
  expect(sitemap.headers().location).toBeUndefined();
  noPrivateStartup();
});

// contract-test: direct surface=gui.web assertions=marketing-landing.public-content,marketing-landing.destinations,settings-ui.localization.visible-content-resolves
test('existing public pages and endpoints keep their routes', async ({ page, request }) => {
  const noPrivateStartup = watchPrivateStartup(page);
  for (const route of ['/', '/news', '/blog', '/de/news', '/legal/privacy', '/robots.txt']) {
    const response = await request.get(site(route), { maxRedirects: 0 });
    expect(response.status(), route).toBe(200);
    expect(response.headers().location, route).toBeUndefined();
  }
  for (const [language, privacyTitle, termsTitle, metadataHeading] of [
    ['en', 'Privacy Policy', 'Terms and Conditions', 'YouTube (video metadata)'],
    ['de', 'Datenschutzerklärung', 'Allgemeine Geschäftsbedingungen', 'YouTube (Video-Metadaten)']
  ] as const) {
    for (const [document, title] of [['privacy', privacyTitle], ['terms', termsTitle]] as const) {
      const route = `/legal/${document}?lang=${language}`;
      const response = await request.get(site(route), { maxRedirects: 0 });
      expect(response.status(), route).toBe(200);
      expect(response.headers().location, route).toBeUndefined();
      const navigation = await page.goto(site(route), { waitUntil: 'domcontentloaded' });
      expect(navigation?.status(), route).toBe(200);
      await expect(page).toHaveURL(site(route));
      const article = page.getByRole('article');
      await expect(article).toBeVisible();
      await expect(article.getByRole('heading', { level: 1, name: title, exact: true })).toBeVisible();
      await expect(article).not.toContainText('[T:');
      if (document === 'privacy') {
        await expect(article.getByRole('heading', { name: metadataHeading, exact: true })).toBeVisible();
        await expect(article).toContainText('YouTube Data API');
      }
    }
  }
  noPrivateStartup();
});

