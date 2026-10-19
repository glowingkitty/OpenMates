import { expect, test } from './helpers/cookie-audit';
import { api, app, site, useWebsitePreview, watchPrivateStartup, website } from './helpers/website-preview';
import publicationManifest from '../../../packages/public-site/src/publications/publicationManifest.v1.json';
import newsReleases from '../../../packages/public-site/src/generated/newsReleases.generated.json';
import publicApps from '../../../packages/public-site/src/generated/publicApps.generated.json';

useWebsitePreview();

// playwright-account: not_required reason=isolated_runner_local_public_website
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { createVideoProofRuntime, defineVideoProof } = require('./helpers/video-proof');
const headerProof = defineVideoProof({
  id: 'standalone-public-header', title: 'The public website header', surface: 'web',
  devices: ['web-phone', 'web-laptop'], domain: 'landing.dev.openmates.org',
  transcript: [{ id: 'header', text: 'The website shows the complete OpenMates logo, icon-only language selection and a rightmost Open Web App link.', checkpoint: 'header', devices: ['web-phone', 'web-laptop'] }],
  assertions: [{ id: 'landing.public-header', checkpoint: 'header', visual: 'The shared standalone header has a complete wordmark, a language icon and an app-root button, without workspace tabs.', devices: ['web-phone', 'web-laptop'] }],
  tutorial: { readingWordsPerSecond: 3, minimumHoldMs: 900, maximumHoldMs: 2500 },
});


async function assertPublicHeader(page: import('@playwright/test').Page) {
  await expect(page.getByTestId('sidebar-toggle')).toHaveCount(0);
  await expect(page.getByRole('complementary', { name: /archive/i })).toHaveCount(0);
  const header = page.getByTestId('public-site-header');
  await expect(header).toBeVisible();
  await expect(header.getByRole('link', { name: 'OpenMates home' })).toHaveAttribute('href', site('/'));
  await expect(header.locator('.wordmark')).toHaveText('OpenMates');
  await expect(header.getByTestId('landing-open-web-app')).toHaveAttribute('href', `${app}/`);
  await expect(header.getByTestId('landing-language-button')).toHaveText('');
  await expect(page.locator('.workspace-nav, [data-testid^="landing-nav-"]')).toHaveCount(0);
  await expect(page.getByTestId('header-login-signup-btn')).toHaveCount(0);
}
const blog = publicationManifest.publications.find((record) => record.kind === 'blog');
const release = newsReleases[0];
if (!blog || !release) throw new Error('Canonical public blog/news records are required for route coverage');

// contract-test: direct surface=gui.web assertions=marketing-landing.app-metadata-defaults,marketing-landing.interactive-rail,marketing-landing.capability-rail-and-prompts,marketing-landing.independent-scroll
test('standalone hero uses built app defaults and selects icons without app startup', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const noPrivateStartup = watchPrivateStartup(page);
  const metadataRequests: string[] = [];
  page.on('request', request => {
    if (['fetch', 'xhr'].includes(request.resourceType()) && /\/v1\/apps(?:\/|$)/.test(new URL(request.url()).pathname)) metadataRequests.push(request.url());
  });
  await page.goto(site('/'), { waitUntil: 'networkidle' });
  const rail = page.getByTestId('landing-app-rail');
  const icons = rail.getByTestId('landing-rail-group').nth(1).locator('.rail-icon');
  expect(await icons.evaluateAll(nodes => nodes.map(node => node.getAttribute('data-app-id')))).toEqual(publicApps.map(app => app.id));
  expect(publicApps.some(app => app.id === 'plants')).toBe(false);
  expect(publicApps.every(app => Boolean(app.exampleChatId))).toBe(true);
  const travel = publicApps.find(app => app.id === 'travel')!;
  await rail.locator('.rail-group:nth-child(2) [data-app-id="travel"]').click();
  const prompt = page.getByTestId('landing-prompt');
  await expect(prompt).toHaveText('Find train connections');
  await expect(prompt).toHaveAttribute('href', `${app}/#chat-id=${encodeURIComponent(travel.exampleChatId)}`);
  await expect(prompt).toHaveAttribute('target', '_blank');
  await expect(prompt).toHaveCSS('opacity', '1');
  await expect(rail).toHaveAttribute('data-active-app', 'travel');
  expect(metadataRequests).toEqual([]);
  noPrivateStartup();
});

for (const width of [390, 1440]) {
  // contract-test: direct surface=gui.web assertions=marketing-landing.destinations,marketing-landing.hero-app-rail,marketing-landing.interactive-rail,marketing-landing.independent-scroll
  test(`standalone example opens the app and preserves the landing tab (${width}px)`, async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('crash', () => errors.push('landing tab crashed'));
    const noPrivateStartup = watchPrivateStartup(page);
    await page.setViewportSize({ width, height: width < 760 ? 844 : 900 });
    await page.emulateMedia({ reducedMotion: 'no-preference' });
    await page.goto(site('/'), { waitUntil: 'networkidle' });
    const landingUrl = page.url();
    const rail = page.getByTestId('landing-app-rail');
    const prompt = page.getByTestId('landing-prompt');
    await rail.locator('.rail-group:nth-child(2) [data-app-id="travel"]').evaluate((button: HTMLButtonElement) => button.click());
    await expect(prompt).toHaveAttribute('data-active-app', 'travel');
    const destination = await prompt.getAttribute('href');
    const [popup] = await Promise.all([page.waitForEvent('popup'), prompt.click()]);
    await expect.poll(() => popup.url()).toBe(destination);
    await expect(popup.getByTestId('chat-history-content')).toBeVisible({ timeout: 30_000 });
    await expect(popup.getByTestId('chat-history-content')).toHaveAttribute('data-source-message-count', /^[1-9]\d*$/);
    await expect(popup.getByTestId('active-chat-history-loading')).toHaveCount(0);
    await page.bringToFront();
    await expect(page.getByTestId('landing-page')).toBeVisible();
    expect(page.url()).toBe(landingUrl);
    await expect.poll(() => prompt.getAttribute('data-active-app'), { timeout: 8_000 }).not.toBe('travel');
    const track = rail.locator('.rail-track');
    const before = await track.evaluate(element => getComputedStyle(element).transform);
    await rail.dispatchEvent('wheel', { deltaX: 90, deltaY: 0 });
    expect(await track.evaluate(element => getComputedStyle(element).transform)).not.toBe(before);
    await expect(rail).toHaveAttribute('data-active-app', (await prompt.getAttribute('data-active-app'))!);
    for (const id of ['actionable', 'privacy', 'model-choice', 'workflows', 'devices', 'open-source']) {
      const section = page.getByTestId(`landing-feature-${id}`);
      await section.scrollIntoViewIfNeeded();
      await expect(section).toHaveClass(/revealed/);
      await expect(section.getByRole('heading')).toHaveCSS('opacity', '1');
      {
        const skip = section.getByTestId(`landing-skip-${id}`);
        if (await skip.count()) await skip.click();
        await expect(section).toHaveAttribute('data-story-state', 'complete');
      }
      await expect(section.locator('.feature-example')).toHaveCSS('opacity', '1');
    }
    expect(errors, 'website errors after opening a real app example').toEqual([]);
    noPrivateStartup();
    await popup.close();
  });
}

// contract-test: direct surface=gui.web assertions=marketing-landing.app-metadata-defaults
test('the supplied-events Calendar example is removed from the web app', async ({ request }) => {
  const response = await request.get('/example/calendar-week-from-supplied-events');
  expect(response.status()).toBe(404);
});

// contract-test: direct surface=gui.web assertions=marketing-landing.independent-scroll,marketing-landing.destinations,marketing-landing.public-content
test('standalone landing and publication indexes are server-rendered without app startup', async ({ page, request }) => {
  const noPrivateStartup = watchPrivateStartup(page);
  for (const route of ['/', '/news', '/blog', '/de/news', '/de/blog']) {
    const response = await request.get(site(route));
    expect(response.status(), `${route} must be served by the website`).toBe(200);
    const html = await response.text();
    expect(html).toContain('<main');
    expect(html).toContain('rel="canonical"');
    expect(html).not.toContain('login-wrapper');
    await page.goto(site(route), { waitUntil: 'domcontentloaded' });
    await expect(page.locator('main')).toBeVisible();
    await assertPublicHeader(page);
    if (route === '/') {
      await expect(page).toHaveTitle('OpenMates — Your privacy first AI team mates');
      await expect(page.locator('meta[property="og:title"]')).toHaveAttribute('content', 'OpenMates — Your privacy first AI team mates');
      await expect(page.locator('meta[name="twitter:title"]')).toHaveAttribute('content', 'OpenMates — Your privacy first AI team mates');
      await expect(page.getByTestId('landing-page')).toBeVisible();
      await expect(page.getByTestId('landing-open-web-app')).toHaveAttribute('href', `${app}/`);
      await expect(page.locator('.workspace-nav, [data-testid^="landing-nav-"]')).toHaveCount(0);
      await expect(page.getByTestId('landing-newsletter')).toBeVisible();
      expect(await page.locator('body').evaluate((body) => getComputedStyle(body).backgroundColor)).not.toBe('rgba(0, 0, 0, 0)');
      await expect(page.locator('link[rel="stylesheet"]')).not.toHaveCount(0);
      const stylesheet = await page.locator('link[rel="stylesheet"]').first().getAttribute('href');
      expect((await request.get(new URL(stylesheet!, website).href)).status()).toBe(200);
    } else {
      await expect(page.getByTestId('newsroom-surface')).toBeVisible();
    }
  }
  noPrivateStartup();
});

// contract-test: direct surface=gui.web assertions=marketing-landing.public-content,marketing-landing.destinations
test('canonical news and blog details render in English and German', async ({ page, request }) => {
  const noPrivateStartup = watchPrivateStartup(page);
  for (const locale of ['en', 'de'] as const) {
    for (const [section, record] of [['news', release], ['blog', blog]] as const) {
      const route = `${locale === 'de' ? '/de' : ''}/${section}/${record.slug}`;
      const response = await request.get(site(route));
      expect(response.status(), route).toBe(200);
      const html = await response.text();
      expect(html).toContain('<meta name="description"');
      expect(html).toContain(`href="${site(route)}"`);
      await page.goto(site(route), { waitUntil: 'domcontentloaded' });
      await assertPublicHeader(page);
      await expect(page.getByTestId('newsroom-surface')).toContainText(record.locales[locale]?.title ?? record.locales.en.title);
      await expect(page.locator('article, [data-testid="newsroom-article"]')).not.toHaveCount(0);
    }
  }
  noPrivateStartup();
});

// contract-test: direct surface=gui.web assertions=public-publications.routes.localized-archives,public-publications.seo.crawlable
test('switches the developer blog between distinct English and German slugs', async ({ page, request }) => {
  const noPrivateStartup = watchPrivateStartup(page);
  const en = '/blog/build-with-ai-openmates-rest-api-cli-sdk';
  const de = '/de/blog/mit-ki-entwickeln-openmates-rest-api-cli-sdk';
  await page.goto(site(en));
  for (const [locale, route, alternateLocale, alternateRoute, title, imageHeading, imageUsage, nextLanguage] of [
    ['en', en, 'de', de, 'Build with AI: OpenMates REST API, CLI, and SDKs', 'A picture can be part of a decision', 'their image tokens use the same free allowance or account credits', 'Deutsch'],
    ['de', de, 'en', en, 'Mit KI entwickeln: REST-API, CLI und SDKs von OpenMates', 'Ein Bild kann Teil einer Entscheidung sein', 'Ihre Bildtokens verbrauchen dasselbe kostenlose Kontingent oder Kontoguthaben', 'English'],
    ['en', en, 'de', de, 'Build with AI: OpenMates REST API, CLI, and SDKs', 'A picture can be part of a decision', 'their image tokens use the same free allowance or account credits', null]
  ] as const) {
    await expect(page).toHaveURL(site(route));
    await assertPublicHeader(page);
    await expect(page.getByRole('heading', { level: 1, name: title })).toBeVisible();
    await expect(page.locator('link[rel="canonical"]')).toHaveAttribute('href', site(route));
    await expect(page.locator(`link[hreflang="${locale}"]`)).toHaveAttribute('href', site(route));
    await expect(page.locator(`link[hreflang="${alternateLocale}"]`)).toHaveAttribute('href', site(alternateRoute));
    await expect(page.locator('link[hreflang="x-default"]')).toHaveAttribute('href', site(en));
    const article = page.locator('.article-markdown');
    await expect(article).toContainText('OpenMatesSignupRequiredError');
    await expect(article).toContainText('detail.signup_required: true');
    await expect(article.getByRole('heading', { name: imageHeading, exact: true })).toBeVisible();
    await expect(article).toContainText(imageUsage);
    await expect(article).toContainText('randomUUID()');
    await expect(article).toContainText('uuid.uuid4()');
    await expect(article).toContainText('data_base64');
    if (nextLanguage) {
      await page.getByTestId('landing-language-button').click();
      await page.getByTestId('landing-language-panel').getByRole('button', { name: nextLanguage, exact: true }).click();
    }
  }
  const sitemap = await request.get(site('/sitemap.xml'));
  // Local preview stays unindexed; publications.test.ts verifies localized production sitemap entries.
  expect(sitemap.status()).toBe(404);
  noPrivateStartup();
});

for (const width of [390, 1440]) {
  // contract-test: direct surface=gui.web assertions=marketing-landing.destinations,marketing-landing.public-content,marketing-landing.language-theme
  test(`public article language switching preserves its route and shared header (${width}px)`, async ({ page }, testInfo) => {
    test.setTimeout(60_000);
    const noPrivateStartup = watchPrivateStartup(page);
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.setViewportSize({ width, height: width < 760 ? 844 : 900 });
    const proof = createVideoProofRuntime(headerProof, {
      device: width < 760 ? 'web-phone' : 'web-laptop',
      attach: testInfo.attach.bind(testInfo), captureFrame: () => page.screenshot(),
    });
    for (const [section, record] of [['news', release], ['blog', blog]] as const) {
      const route = `/${section}/${record.slug}`;
      await page.goto(site(route), { waitUntil: 'domcontentloaded' });
      await assertPublicHeader(page);
      await page.getByTestId('landing-language-button').click();
      await page.getByTestId('landing-language-panel').getByRole('button', { name: 'Deutsch', exact: true }).click();
      await expect(page).toHaveURL(site(`/de${route}`));
      const root = page.getByTestId('newsroom-surface');
      await expect(root).toHaveAttribute('data-locale', 'de');
      await expect(root).toContainText(record.locales.de?.title ?? record.locales.en.title);
      await assertPublicHeader(page);
      await expect(page.getByTestId('landing-open-web-app')).toHaveText('Web-App öffnen');
      expect(await page.evaluate(() => localStorage.getItem('preferredLanguage'))).toBe('de');
      await page.getByTestId('landing-language-button').click();
      await page.getByTestId('landing-language-panel').getByRole('button', { name: 'English', exact: true }).click();
      await expect(page).toHaveURL(site(route));
      await expect(root).toHaveAttribute('data-locale', 'en');
      await assertPublicHeader(page);
      expect(await page.evaluate(() => localStorage.getItem('preferredLanguage'))).toBe('en');
      await expect(page.locator('link[rel="canonical"]')).toHaveAttribute('href', site(route));
    }
    await proof.assert('landing.public-header', async () => {
      await assertPublicHeader(page);
      expect(await page.getByTestId('newsroom-surface').evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
    });
    await testInfo.attach(`public-article-header-${width}px`, { body: await page.screenshot(), contentType: 'image/png' });
    await proof.checkpoint('header');
    await proof.attach();
    expect(errors).toEqual([]);
    noPrivateStartup();
  });
}

// contract-test: direct surface=gui.web assertions=marketing-landing.destinations,marketing-landing.public-content
test('news subscriptions open the standalone public form in the publication language', async ({ page }) => {
  for (const [locale, route, label] of [
    ['en', '/news', 'Subscribe to news'],
    ['de', '/de/news', 'News abonnieren']
  ] as const) {
    await page.goto(site(route), { waitUntil: 'domcontentloaded' });
    await page.getByRole('button', { name: label }).click();
    await expect(page).toHaveURL(site('/#newsletter'));
    await expect(page.getByTestId('landing-page')).toHaveAttribute('lang', locale);
    await expect(page.getByTestId('landing-newsletter')).toBeInViewport();
    await expect(page.locator('#newsletter input[type="email"]')).toBeVisible();
  }
});

// contract-test: direct surface=gui.web assertions=marketing-landing.public-content
test('privacy, terms, and imprint are full styled public documents', async ({ page, request }) => {
  const noPrivateStartup = watchPrivateStartup(page);
  for (const slug of ['privacy', 'terms', 'imprint']) {
    let english = '';
    for (const suffix of ['', '?lang=de']) {
      const route = `/legal/${slug}${suffix}`;
      const response = await request.get(site(route));
      expect(response.status(), route).toBe(200);
      const html = await response.text();
      expect(html).toContain(`href="${site(`/legal/${slug}`)}"`);
      expect(html).toMatch(/<main class="legal-document(?:\s|")/);
      await page.goto(site(route), { waitUntil: 'domcontentloaded' });
      const article = page.locator('.legal-document article');
      const header = page.getByTestId('public-site-header');
      await expect(header).toBeVisible();
      await expect(header.getByRole('link', { name: 'OpenMates home' })).toHaveAttribute('href', site('/'));
      await expect(header.getByTestId('landing-open-web-app')).toHaveAttribute('href', `${app}/`);
      await expect(header.locator('.workspace-nav, [data-testid^="landing-nav-"]')).toHaveCount(0);
      await expect(header.locator('.wordmark')).toBeVisible();
      await expect(header.getByTestId('landing-language-button')).toHaveText('');
      await header.getByTestId('landing-language-button').click();
      const languageOptions = header.getByTestId('landing-language-panel').locator('.language-options button');
      await expect(languageOptions).toHaveCount(2);
      expect(await languageOptions.evaluateAll((options) => options.map((option) => option.getAttribute('lang')).sort())).toEqual(['de', 'en']);
      await header.getByTestId('landing-language-panel').getByRole('button', { name: suffix ? 'English' : 'Deutsch', exact: true }).click();
      await expect(page).toHaveURL(site(`/legal/${slug}${suffix ? '' : '?lang=de'}`));
      await page.goto(site(route), { waitUntil: 'domcontentloaded' });
      await expect(article.locator('h1')).toBeVisible();
      const body = await article.innerText();
      expect(body.length, `${route} must contain the complete legal document`).toBeGreaterThan(slug === 'imprint' ? 50 : 1_000);
      await expect(article.locator('h2')).not.toHaveCount(0);
      if (slug === 'imprint') {
        await expect(article).toContainText('contact@openmates.org');
        await expect(article.locator('img')).toHaveCount(4);
        for (const image of await article.locator('img').all()) {
          const source = await image.getAttribute('src');
          expect((await request.get(new URL(source!, website).href)).status()).toBe(200);
        }
      }
      if (!suffix) english = body;
      else expect(body).not.toBe(english);
      expect(await article.evaluate((element) => getComputedStyle(element).lineHeight)).not.toBe('normal');
      await expect(page.locator('[data-testid="active-chat-container"]')).toHaveCount(0);
    }
  }
  noPrivateStartup();
});

for (const { width, height } of [{ width: 390, height: 844 }, { width: 1440, height: 900 }]) {
  // contract-test: direct surface=gui.web assertions=marketing-landing.feature-layout,marketing-landing.destinations,marketing-landing.real-screenshots,marketing-landing.six-feature-viewport
  test(`standalone global styles preserve the landing viewport and media at ${width}px`, async ({ page }, testInfo) => {
    test.setTimeout(45_000);
    const proof = createVideoProofRuntime(headerProof, { device: width < 760 ? 'web-phone' : 'web-laptop', attach: testInfo.attach.bind(testInfo), captureFrame: () => page.screenshot() });
    await page.setViewportSize({ width, height });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto(site('/'), { waitUntil: 'domcontentloaded' });
    await page.evaluate(() => document.fonts.ready.then(() => true));

    const root = page.getByTestId('landing-page');
    const scroller = page.getByTestId('landing-scroll-container');
    const composer = page.getByTestId('landing-compose');
    await expect(root).toBeVisible();
    await expect(page.getByTestId('landing-hero-speed')).toHaveText('In seconds');
    await expect(page.getByTestId('landing-prompt')).toHaveCSS('opacity', '1');
    const bubble = await page.getByTestId('landing-prompt').evaluate((element) => ({
      background: getComputedStyle(element).backgroundColor,
      tail: getComputedStyle(element, '::after').maskImage
    }));
    expect(bubble.background).toMatch(/^rgb\(\d+, \d+, \d+\)$/);
    expect(bubble.tail).toContain('speechbubble.svg');

    await proof.assert('landing.public-header', async () => {
    const header = page.getByTestId('public-site-header');
    await expect(header.locator('.wordmark')).toBeVisible();
    await expect(header.getByTestId('landing-open-web-app')).toHaveText('Open Web App');
    await expect(header.getByTestId('landing-open-web-app')).toHaveAttribute('href', `${app}/`);
    await expect(header.getByTestId('landing-language-button')).toHaveText('');
    await expect(header.locator('.workspace-nav, [data-testid^="landing-nav-"]')).toHaveCount(0);

    });
    await proof.checkpoint('header');
    await proof.attach();

    await expect(page.getByTestId('landing-feature-model-choice')).toHaveCount(1);
    const heroMedia = page.getByTestId('landing-hero-media');
    await expect(heroMedia.locator('.device-frame, img.device-screen, img.device-shell')).toHaveCount(0);
    const aiVisual = page.getByTestId('landing-hero-ai-icon');
    await expect(aiVisual).toHaveAttribute('aria-hidden', 'true');
    await expect(aiVisual).toHaveCSS('animation-name', 'none');
    await expect(aiVisual.locator('.hero-ai-glyph svg')).toBeVisible();
    await expect(aiVisual.locator('.hero-ai-glyph svg path')).toHaveCount(1);
    await expect(aiVisual.locator('.hero-ai-glyph')).toHaveCSS('mask-image', 'none');
    await expect(composer).toBeVisible();
    const before = await composer.boundingBox();
    expect(before).not.toBeNull();
    expect(Math.abs((await root.boundingBox())!.height - height)).toBeLessThan(2);
    expect(before!.y + before!.height).toBeLessThanOrEqual(height);
    expect(before!.y + before!.height).toBeGreaterThan(height - 105);
    await page.screenshot({ path: testInfo.outputPath(`website-landing-${width}-hero.png`), animations: 'disabled' });

    await page.getByTestId('landing-feature-devices').scrollIntoViewIfNeeded();
    await expect.poll(() => scroller.evaluate((element) => element.scrollTop)).toBeGreaterThan(0);
    const deviceImages = page.getByTestId('landing-feature-media-devices').locator('img.device-screen:visible, img.device-shell:visible');
    await expect(deviceImages).toHaveCount(width < 760 ? 2 : 4);
    await expect.poll(() => deviceImages.evaluateAll((images) => images.every((image) => (image as HTMLImageElement).complete && (image as HTMLImageElement).naturalWidth > 0))).toBe(true);
    const after = await composer.boundingBox();
    expect(Math.abs(after!.y - before!.y), 'the composer stays fixed while features scroll').toBeLessThan(2);
    expect(Math.abs(after!.height - before!.height)).toBeLessThan(2);
    const horizontalOverflow = await page.evaluate(() => ({
      document: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      scroller: document.querySelector('[data-testid="landing-scroll-container"]')!.scrollWidth - document.querySelector('[data-testid="landing-scroll-container"]')!.clientWidth
    }));
    expect(horizontalOverflow.document).toBeLessThanOrEqual(1);
    expect(horizontalOverflow.scroller).toBeLessThanOrEqual(1);
    await page.screenshot({ path: testInfo.outputPath(`website-landing-${width}-devices.png`), animations: 'disabled' });
  });
}

// contract-test: direct surface=gui.web assertions=marketing-landing.language-theme
test('saved dark theme applies in the document head before hydration', async ({ page, request }) => {
  const html = await (await request.get(site('/'))).text();
  expect(html.indexOf("localStorage.getItem('theme_mode')")).toBeGreaterThan(0);
  expect(html.indexOf("localStorage.getItem('theme_mode')")).toBeLessThan(html.indexOf('</head>'));
  await page.addInitScript(() => {
    localStorage.setItem('theme_mode', 'dark');
    const seen: string[] = [];
    (window as Window & { __initialThemeValues?: string[] }).__initialThemeValues = seen;
    new MutationObserver(records => {
      for (const record of records) {
        if (record.oldValue) seen.push(record.oldValue);
        const mode = document.documentElement.dataset.theme;
        if (mode) seen.push(mode);
      }
    }).observe(document, { subtree: true, attributes: true, attributeFilter: ['data-theme'], attributeOldValue: true });
  });
  await page.goto(site('/'), { waitUntil: 'domcontentloaded' });
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await expect(page.locator('html')).toHaveCSS('color-scheme', 'dark');
  const themeValues = await page.evaluate(() => (window as Window & { __initialThemeValues?: string[] }).__initialThemeValues ?? []);
  expect(themeValues).toContain('dark');
  expect(themeValues).not.toContain('light');
});

// contract-test: supporting surface=gui.web assertions=newsletter.surface.standalone-confirmation
test('confirmation token waits for an explicit click and reveals Signal only after a successful response', async ({ page, request }) => {
  const token = 'ci-public-confirmation-token';
  const route = `/newsletter/confirm/${token}?lang=de`;
  const response = await request.get(site(route));
  expect(response.status()).toBe(200);
  expect(response.headers()['referrer-policy']).toBe('no-referrer');
  expect(response.headers()['cache-control']).toContain('no-store');
  const html = await response.text();
  expect(html).toContain('noindex');
  let confirmations = 0;
  await page.route(`${api}/v1/newsletter/confirm/${token}`, async (intercepted) => {
    confirmations += 1;
    await intercepted.fulfill({ status: 200, contentType: 'application/json', headers: { 'Access-Control-Allow-Origin': website }, body: JSON.stringify({ success: true }) });
  });
  await page.goto(site(route), { waitUntil: 'domcontentloaded' });
  await expect(page.getByTestId('newsletter-confirm-button')).toBeVisible();
  await expect(page.getByTestId('newsletter-signal-link')).toHaveCount(0);
  expect(confirmations, 'link previews and page load must not consume the token').toBe(0);
  await page.getByTestId('newsletter-confirm-button').click();
  await expect(page.getByTestId('newsletter-signal-link')).toBeVisible();
  expect(confirmations).toBe(1);
});
