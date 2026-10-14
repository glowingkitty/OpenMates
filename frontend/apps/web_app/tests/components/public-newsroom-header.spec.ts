import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { createVideoProofRuntime, defineVideoProof } = require('../helpers/video-proof');
const proofContract = defineVideoProof({
  id: 'shared-public-newsroom-header', title: 'The shared website header on news and blog', surface: 'web',
  devices: ['web-phone', 'web-laptop'], domain: 'landing.dev.openmates.org',
  transcript: [
    { id: 'index', text: 'News keeps the complete website logo, language selection and Open Web App button. Its archive remains searchable.', checkpoint: 'index', devices: ['web-phone', 'web-laptop'] },
    { id: 'article', text: 'Blog articles use the same header, with readable content and independent scrolling.', checkpoint: 'article', devices: ['web-phone', 'web-laptop'] },
  ],
  assertions: [
    { id: 'landing.public-newsroom-header', checkpoint: 'index', visual: 'The full wordmark and app-root CTA fit on the viewport; language options remain usable above an open archive.', devices: ['web-phone', 'web-laptop'] },
    { id: 'landing.public-article-header', checkpoint: 'article', visual: 'Articles keep the same public header and archive navigation without duplicate branding, overlap or horizontal overflow.', devices: ['web-phone', 'web-laptop'] },
  ],
  tutorial: { readingWordsPerSecond: 3, minimumHoldMs: 900, maximumHoldMs: 2500 },
});

function preview(width: number, variant?: string) {
  return `/dev/preview/newsroom/PublicNewsroomPreview?${new URLSearchParams({
    chrome: '0', theme: 'light', background: '#dbeafe', width: String(width),
    ...(variant ? { variant } : {}),
  })}`;
}

for (const { width, height } of [
  { width: 320, height: 640 }, { width: 390, height: 844 },
  { width: 768, height: 1024 }, { width: 1512, height: 1000 },
]) {
  // contract-test: direct surface=gui.web assertions=marketing-landing.destinations,marketing-landing.public-content,marketing-landing.language-theme,public-publications.controls.consistent-navigation
  test(`shared public newsroom header and article navigation fit ${width}px`, async ({ page }, testInfo) => {
    test.setTimeout(75_000);
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.setViewportSize({ width, height });
    await page.goto(preview(width), { waitUntil: 'domcontentloaded' });
    await waitForComponentPreview(page);
    const proof = createVideoProofRuntime(proofContract, {
      device: width < 760 ? 'web-phone' : 'web-laptop', attach: testInfo.attach.bind(testInfo),
      captureFrame: () => page.screenshot(),
    });
    const header = page.getByTestId('public-site-header');
    const root = page.getByTestId('newsroom-surface');
    const language = header.getByTestId('landing-language-button');
    const archive = page.getByRole('complementary', { name: 'Newsroom archive' });
    await expect(header.getByRole('link', { name: 'OpenMates home' })).toHaveAttribute('href', 'https://landing.dev.openmates.org/');
    await expect(header.locator('.wordmark')).toHaveText('OpenMates');
    await expect(header.locator('.wordmark')).toHaveCSS('font-size', '20px');
    await expect(header.getByTestId('landing-open-web-app')).toHaveAttribute('href', 'https://app.dev.openmates.org/');
    await expect(header.getByTestId('landing-open-web-app')).toHaveText('Open Web App');
    await expect(language).toHaveText('');
    await expect(page.getByTestId('header-login-signup-btn')).toHaveCount(0);
    await expect(page.locator('.workspace-nav, [data-testid^="landing-nav-"]')).toHaveCount(0);
    const newsLink = header.getByRole('link', { name: 'News', exact: true });
    const blogLink = header.getByRole('link', { name: 'Blog', exact: true });
    await expect(newsLink).toHaveAttribute('href', 'https://landing.dev.openmates.org/news');
    await expect(newsLink).toHaveAttribute('aria-current', 'page');
    await expect(newsLink).toHaveCSS('opacity', '1');
    await expect(blogLink).toHaveCSS('opacity', '0.5');
    await expect(header.locator('.github-link svg')).toBeVisible();
    await expect(language.locator('svg')).toBeVisible();
    await expect(root.locator('.publication-header .logo-link')).toBeHidden();
    await expect(root.locator('.section-actions svg')).toHaveCount(3);
    await expect(root.locator('.center-actions svg')).toHaveCount(2);
    await expect(root.getByRole('button', { name: 'Subscribe to news', exact: true }).locator('svg')).toHaveAttribute('data-icon', 'mail');
    const toggleSize = await page.getByTestId('sidebar-toggle').evaluate(el => ({ width: el.offsetWidth, height: el.offsetHeight }));
    expect(toggleSize.width).toBe(41);
    expect(toggleSize.height).toBe(41);
    for (const icon of await root.locator('.section-actions svg, .center-actions svg').all()) {
      await expect(icon).toBeVisible();
      expect(await icon.evaluate(node => node.getBoundingClientRect().width)).toBeGreaterThan(0);
    }
    await expect(archive).toBeHidden();
    await page.getByTestId('sidebar-toggle').click();
    await expect(archive).toBeVisible();
    await page.getByTestId('sidebar-search').click();
    const archiveSearch = page.getByTestId('sidebar-search-input');
    await expect(archiveSearch).toBeFocused();
    await archiveSearch.fill('Health');
    await expect(archive.getByText('The Health app, redesigned')).toBeVisible();
    await expect(archive.getByText('New skills for the Code app')).toHaveCount(0);
    await language.click();
    const panel = page.getByTestId('landing-language-panel');
    await expect(panel).toBeVisible();
    const panelBox = (await panel.boundingBox())!;
    expect(panelBox.x).toBeGreaterThanOrEqual(0);
    expect(panelBox.x + panelBox.width).toBeLessThanOrEqual(width);
    await panel.getByRole('button', { name: 'Deutsch', exact: true }).click();
    await expect(root).toHaveAttribute('data-locale', 'de');
    await expect(header.getByTestId('landing-open-web-app')).toHaveText('Web-App öffnen');
    await expect(language).toBeFocused();
    await language.click();
    await panel.getByRole('button', { name: 'English', exact: true }).click();
    await expect(root).toHaveAttribute('data-locale', 'en');
    await language.click();
    await page.keyboard.press('Escape');
    await expect(panel).toHaveCount(0);
    await expect(language).toBeFocused();
    await archive.getByRole('button', { name: 'Close Newsroom navigation', exact: true }).click();
    await expect(archive).toBeHidden();
    await language.hover();
    await expect(language).toHaveCSS('scale', '1');
    await proof.assert('landing.public-newsroom-header', async () => {
      const boxes = await header.locator('.wordmark, .language-button, .header-link').evaluateAll(nodes => nodes.map(node => node.getBoundingClientRect().toJSON()));
      for (const box of boxes) {
        expect(box.x).toBeGreaterThanOrEqual(0);
        expect(box.right).toBeLessThanOrEqual(width);
        expect(box.top).toBeGreaterThanOrEqual(0);
        expect(box.bottom).toBeLessThanOrEqual(width <= 600 ? 110 : 70);
      }
      expect(boxes[0].right).toBeLessThanOrEqual(boxes[1].left);
      expect(boxes[1].right).toBeLessThanOrEqual(boxes[2].left);
      await header.getByTestId('landing-open-web-app').hover();
      const hoverBoxes = await header.locator('.language-button, .header-link').evaluateAll(nodes => nodes.map(node => node.getBoundingClientRect().toJSON()));
      expect(hoverBoxes[0].right).toBeLessThanOrEqual(hoverBoxes[1].left);
      expect(hoverBoxes[1].right).toBeLessThanOrEqual(width);
      expect(await root.evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
    });
    await testInfo.attach(`public-news-${width}px`, { body: await page.screenshot(), contentType: 'image/png' });
    await proof.checkpoint('index');

    await page.goto(preview(width, 'Blog post'), { waitUntil: 'domcontentloaded' });
    await waitForComponentPreview(page);
    await expect(root).toHaveAttribute('data-view', 'blog-post');
    await expect(root.locator('.article-body')).toBeVisible();
    await expect(root.locator('.publication-header .logo-link')).toHaveAttribute('href', 'https://landing.dev.openmates.org/blog');
    await expect(blogLink).toHaveAttribute('aria-current', 'page');
    await expect(blogLink).toHaveCSS('opacity', '1');
    await expect(newsLink).toHaveCSS('opacity', '0.5');
    const close = page.getByTestId('publication-detail-close');
    await expect(close.locator('svg')).toBeVisible();
    const closeSize = await close.evaluate(el => {
      const style = getComputedStyle(el);
      return { width: el.offsetWidth, height: el.offsetHeight, padding: Number.parseFloat(style.paddingLeft) };
    });
    expect(closeSize.width).toBe(25 + 2 * closeSize.padding);
    expect(closeSize.height).toBe(closeSize.width);
    await expect(close).toHaveCSS('scale', '1');
    await expect(close).toHaveCSS('color', 'rgb(255, 255, 255)');
    await header.getByTestId('landing-open-web-app').hover();
    await header.getByTestId('landing-open-web-app').focus();
    await expect(header.getByTestId('landing-open-web-app')).toHaveCSS('outline-style', 'solid');
    await proof.assert('landing.public-article-header', async () => {
      const before = (await header.boundingBox())!;
      const content = root.locator('.publication-scroll');
      const closeBefore = (await close.boundingBox())!;
      await content.evaluate(el => { el.scrollTop = 700; });
      await expect(close).not.toHaveCSS('color', 'rgb(255, 255, 255)');
      const closeAfter = (await close.boundingBox())!;
      expect(closeAfter.y).toBe(closeBefore.y);
      expect(closeAfter.x).toBe(closeBefore.x);
      expect(await content.evaluate(el => el.scrollTop)).toBeGreaterThan(0);
      const after = (await header.boundingBox())!;
      expect(after.y).toBe(before.y);
      expect(after.y + after.height).toBeLessThanOrEqual((await root.locator('.publication-hero').boundingBox())!.y + 700);
      expect(await root.evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
      await content.evaluate(el => { el.scrollTop = 0; });
    });
    expect(errors).toEqual([]);
    await testInfo.attach(`public-blog-article-${width}px`, { body: await page.screenshot(), contentType: 'image/png' });
    await proof.checkpoint('article');
    await close.click();
    await expect(root).toHaveAttribute('data-view', 'blog');
    for (const platform of ['instagram', 'mastodon', 'linkedin']) {
      const link = page.getByTestId(`publication-follow-${platform}`);
      await expect(link).toHaveAttribute('href', /^https:\/\//);
      await link.scrollIntoViewIfNeeded();
      await expect(link.locator('svg')).toBeVisible();
      await expect(link).toHaveAttribute('target', '_blank');
      await expect(link).toHaveAttribute('rel', 'noopener noreferrer');
    }
    await page.goto(preview(width, 'Social post'), { waitUntil: 'domcontentloaded' });
    await waitForComponentPreview(page);
    await expect(root).toHaveAttribute('data-view', 'social-post');
    await expect(close.locator('svg')).toBeVisible();
    const socialCloseBefore = (await close.boundingBox())!;
    await root.locator('.publication-scroll').evaluate(el => { el.scrollTop = 200; });
    expect((await close.boundingBox())!.y).toBe(socialCloseBefore.y);
    await close.click();
    await expect(root).toHaveAttribute('data-view', 'news');
    // Keep the surface and close button mounted through social -> article.
    // At scrollTop=0, scrollTo(0) emits no event to repair a stale overlay state.
    await page.getByTestId('newsroom-card-workflow-social').click();
    await expect(root).toHaveAttribute('data-view', 'social-post');
    await root.locator('.publication-scroll').evaluate(el => { el.scrollTop = 0; });
    await expect(close).not.toHaveCSS('color', 'rgb(255, 255, 255)');
    await page.getByTestId('sidebar-toggle').click();
    await archive.getByRole('button').filter({ hasText: 'The Health app, redesigned' }).click();
    await expect(root).toHaveAttribute('data-view', 'release');
    await expect(root.getByRole('button', { name: 'Subscribe to news', exact: true }).locator('svg')).toHaveAttribute('data-icon', 'mail');
    await expect(root.locator('.publication-scroll')).toHaveJSProperty('scrollTop', 0);
    await expect(close).toHaveCSS('color', 'rgb(255, 255, 255)');
    await expect(close).toHaveCSS('background-color', 'rgba(255, 255, 255, 0.2)');
    expect(errors).toEqual([]);
    await proof.attach();
  });
}
