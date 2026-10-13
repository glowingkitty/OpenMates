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
  // contract-test: direct surface=gui.web assertions=marketing-landing.destinations,marketing-landing.public-content,marketing-landing.language-theme
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
    await expect(root.locator('.publication-header .logo-link')).toHaveText('Newsroom');
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
    await page.getByTestId('sidebar-toggle').click();
    await expect(archive).toBeHidden();
    await proof.assert('landing.public-newsroom-header', async () => {
      const boxes = await header.locator('.wordmark, .language-button, .header-link').evaluateAll(nodes => nodes.map(node => node.getBoundingClientRect().toJSON()));
      for (const box of boxes) {
        expect(box.x).toBeGreaterThanOrEqual(0);
        expect(box.right).toBeLessThanOrEqual(width);
        expect(box.top).toBeGreaterThanOrEqual(0);
        expect(box.bottom).toBeLessThanOrEqual(70);
      }
      expect(boxes[0].right).toBeLessThanOrEqual(boxes[1].left);
      expect(boxes[1].right).toBeLessThanOrEqual(boxes[2].left);
      expect(await root.evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
    });
    await testInfo.attach(`public-news-${width}px`, { body: await page.screenshot(), contentType: 'image/png' });
    await proof.checkpoint('index');

    await page.goto(preview(width, 'Blog post'), { waitUntil: 'domcontentloaded' });
    await waitForComponentPreview(page);
    await expect(root).toHaveAttribute('data-view', 'blog-post');
    await expect(root.locator('.article-body')).toBeVisible();
    await expect(root.locator('.publication-header .logo-link')).toHaveAttribute('href', 'https://landing.dev.openmates.org/blog');
    await expect(root.locator('.publication-header .logo-link')).toHaveText('Blog');
    await header.getByTestId('landing-open-web-app').hover();
    await header.getByTestId('landing-open-web-app').focus();
    await expect(header.getByTestId('landing-open-web-app')).toHaveCSS('outline-style', 'solid');
    await proof.assert('landing.public-article-header', async () => {
      const before = (await header.boundingBox())!;
      const content = root.locator('.publication-scroll');
      await content.evaluate(el => { el.scrollTop = 350; });
      expect(await content.evaluate(el => el.scrollTop)).toBeGreaterThan(0);
      const after = (await header.boundingBox())!;
      expect(after.y).toBe(before.y);
      expect(after.y + after.height).toBeLessThanOrEqual((await root.locator('.publication-header').boundingBox())!.y);
      expect(await root.evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
      await content.evaluate(el => { el.scrollTop = 0; });
    });
    expect(errors).toEqual([]);
    await testInfo.attach(`public-blog-article-${width}px`, { body: await page.screenshot(), contentType: 'image/png' });
    await proof.checkpoint('article');
    await proof.attach();
  });
}
