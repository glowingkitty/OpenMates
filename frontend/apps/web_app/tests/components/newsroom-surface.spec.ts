/**
 * Focused proof for the fixture-driven newsroom design review surface.
 * It intentionally verifies only the representative responsive structure and
 * core preview interactions before the user approves the visual direction.
 */
import { expect, test } from '../helpers/cookie-audit';

// playwright-account: not_required reason=isolated_component_preview
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { createVideoProofRuntime, defineVideoProof } = require('../helpers/video-proof');


const proofContract = defineVideoProof({
  id: 'newsroom-surface-design-review',
  title: 'Review the OpenMates newsroom',
  surface: 'web',
  devices: ['web-phone', 'web-laptop'],
  domain: 'app.dev.openmates.org',
  transcript: [
    { id: 'index', text: 'News uses a featured release, chronological navigation, searchable cards, and newsroom sections.', checkpoint: 'index', devices: ['web-phone', 'web-laptop'] },
    { id: 'article', text: 'Release and blog detail pages keep the same newsroom frame, with readable article content and grouped media.', checkpoint: 'article', devices: ['web-phone', 'web-laptop'] },
    { id: 'social', text: 'Archived OpenMates social posts remain readable without loading a social platform embed.', checkpoint: 'social', devices: ['web-phone', 'web-laptop'] },
  ],
  assertions: [
    { id: 'newsroom-index', checkpoint: 'index', visual: 'The news index has the featured release, recent-publication navigation, search, and cards without horizontal overflow.', devices: ['web-phone', 'web-laptop'] },
    { id: 'newsroom-article', checkpoint: 'article', visual: 'Detail content and the grouped-media slideshow remain readable at the active viewport.', devices: ['web-phone', 'web-laptop'] },
    { id: 'newsroom-social', checkpoint: 'social', visual: 'The social archive shows owned media, readable post text, and an original-post action.', devices: ['web-phone', 'web-laptop'] },
  ],
  tutorial: { readingWordsPerSecond: 3, minimumHoldMs: 900, maximumHoldMs: 2200 },
});

function preview(width: string, variant?: string) {
  return `/dev/preview/newsroom/NewsroomSurface?${new URLSearchParams({
    chrome: '0',
    theme: 'light',
    width,
    ...(variant ? { variant } : {}),
  })}`;
}

for (const phone of [false, true]) {
  const device = phone ? 'web-phone' : 'web-laptop';
  const width = phone ? '390' : '1512';
  // contract-test: tooling
  test(`presents the UI-first newsroom layouts for approval (${device})`, async ({ page }, testInfo) => {
    test.setTimeout(90_000);
    await page.setViewportSize({ width: Number(width), height: phone ? 844 : 1000 });
    const proof = createVideoProofRuntime(proofContract, { device, attach: testInfo.attach.bind(testInfo) });

    await page.goto(preview(width), { waitUntil: 'networkidle' });
    const root = page.getByTestId('newsroom-surface');
    await expect(root).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Introducing: Workflow Automation' })).toBeVisible();
    if (phone) {
      await expect(page.getByRole('complementary', { name: 'Newsroom archive' })).toBeHidden();
      await page.getByTestId('sidebar-toggle').click();
      await expect(page.getByRole('complementary', { name: 'Newsroom archive' })).toBeVisible();
      await expect(page.getByTestId('sidebar-toggle')).toHaveAttribute('aria-expanded', 'true');
      await page.getByTestId('sidebar-toggle').click();
      await expect(page.getByRole('complementary', { name: 'Newsroom archive' })).toBeHidden();
    } else {
      await expect(page.getByRole('complementary', { name: 'Newsroom archive' })).toBeVisible();
      await page.getByTestId('sidebar-toggle').click();
      await expect(page.getByRole('complementary', { name: 'Newsroom archive' })).toBeHidden();
      await page.getByTestId('sidebar-toggle').click();
      await expect(page.getByRole('complementary', { name: 'Newsroom archive' })).toBeVisible();
    }
    const featuredCard = page.getByTestId('newsroom-card-health-app-redesigned');
    const standardCard = page.getByTestId('newsroom-card-new-code-skills');
    await expect(featuredCard).toBeVisible();
    await expect(standardCard).toBeVisible();
    expect((await featuredCard.boundingBox())?.height).toBeGreaterThan(200);
    expect((await standardCard.boundingBox())?.height).toBeGreaterThan(300);
    const geometry = await root.evaluate((element) => {
      const rect = (selector: string) => element.querySelector(selector)!.getBoundingClientRect();
      const header = rect('.main-panel > header');
      const cta = rect('[data-testid="header-login-signup-btn"]');
      const hero = rect('.publication-hero');
      const section = rect('.content-section');
      const card = rect('.publication-card');
      const panel = rect('.main-panel');
      return { headerTop: header.top, headerHeight: header.height, ctaInset: panel.right - cta.right,
        sectionGap: section.top - hero.bottom, cardInset: card.left - panel.left,
        heroTop: hero.top, headerBottom: header.bottom };
    });
    expect(geometry.headerTop).toBe(0);
    expect(geometry.headerHeight).toBeLessThanOrEqual(72);
    expect(geometry.ctaInset).toBeGreaterThanOrEqual(16);
    expect(geometry.ctaInset).toBeLessThanOrEqual(24);
    expect(geometry.sectionGap).toBeGreaterThanOrEqual(40);
    expect(geometry.cardInset).toBeGreaterThanOrEqual(24);
    expect(geometry.heroTop).toBeGreaterThanOrEqual(geometry.headerBottom);
    await testInfo.attach(`news-${device}`, { body: await page.screenshot(), contentType: 'image/png' });
    if (phone) {
      await root.locator('.publication-scroll').evaluate((element) => { element.scrollTop = 300; });
      expect((await root.locator('.main-panel > header').boundingBox())!.y).toBe(0);
      await testInfo.attach('news-phone-scrolled', { body: await page.screenshot(), contentType: 'image/png' });
    }
    await page.getByTestId('newsroom-search-toggle').click();
    const search = page.getByTestId('newsroom-search-input');
    await search.fill('Health');
    await expect(featuredCard).toBeVisible();
    await expect(page.getByTestId('newsroom-card-new-code-skills')).toHaveCount(0);
    await proof.assert('newsroom-index', async () => {
      expect(await root.evaluate((element) => element.scrollWidth <= element.clientWidth + 1)).toBe(true);
    });
    await proof.checkpoint('index');
    await page.waitForTimeout(proofContract.tutorial.minimumHoldMs);

    for (const variant of ['Blog', 'Blog post']) {
      await page.goto(preview(width, variant), { waitUntil: 'networkidle' });
      await expect(page.getByTestId('newsroom-surface')).toHaveAttribute('data-view', variant === 'Blog' ? 'blog' : 'blog-post');
      await testInfo.attach(`${variant}-${device}`, { body: await page.screenshot(), contentType: 'image/png' });
    }

    await page.goto(preview(width, 'Release'), { waitUntil: 'networkidle' });
    await expect(page.getByText('Workflow Automation helps people').first()).toBeVisible();
    await testInfo.attach(`release-${device}`, { body: await page.screenshot(), contentType: 'image/png' });
    const slideshow = page.getByTestId('newsroom-slideshow');
    await slideshow.getByRole('button', { name: 'Next media' }).click();
    await expect(slideshow).toContainText('2 / 3');
    await proof.assert('newsroom-article', async () => {
      expect(await page.getByTestId('newsroom-surface').evaluate((element) => element.scrollWidth <= element.clientWidth + 1)).toBe(true);
    });
    await proof.checkpoint('article');
    await page.waitForTimeout(proofContract.tutorial.minimumHoldMs);

    await page.goto(preview(width, 'Social post'), { waitUntil: 'networkidle' });
    await expect(page.getByTestId('newsroom-surface')).toHaveAttribute('data-view', 'social-post');
    await expect(page.getByText('View original post')).toHaveCount(0);
    const platformLinks = page.getByRole('navigation', { name: 'Open original post' }).getByRole('link');
    await expect(platformLinks).toHaveCount(3);
    const expectedPlatforms = [
      ['bluesky', /bsky\.app\/profile\/.+\/post\//],
      ['instagram', /instagram\.com\/(?:openmates_official\/p|reel)\//],
      ['mastodon', /mastodon\.social\/@OpenMates\//],
    ] as const;
    for (const [platform, href] of expectedPlatforms) {
      const link = page.getByTestId(`social-platform-link-${platform}`);
      await expect(link).toHaveAttribute('href', href);
      await expect(link).toHaveAttribute('target', '_blank');
      await expect(link).toHaveAttribute('rel', 'noopener noreferrer');
    }
    await proof.assert('newsroom-social', async () => {
      expect(await page.getByTestId('newsroom-surface').evaluate((element) => element.scrollWidth <= element.clientWidth + 1)).toBe(true);
    });
    const media = await root.locator('.social-detail-media').boundingBox();
    expect(media!.height / media!.width).toBeCloseTo(1.6, 1);
    const copy = await root.locator('.social-detail-copy').boundingBox();
    if (phone) expect(copy!.y).toBeGreaterThanOrEqual(media!.y + media!.height + 20);
    else expect(copy!.x).toBeGreaterThanOrEqual(media!.x + media!.width + 30);
    const more = await root.locator('.more-posts').boundingBox();
    expect(more!.y).toBeGreaterThanOrEqual(media!.y + media!.height + 40);
    const textSize = await page.locator('#social-post-title').evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
    expect(textSize).toBe(16);
    await root.locator('.publication-scroll').evaluate((element) => { element.scrollTop = 0; });
    await testInfo.attach(`social-${device}`, { body: await page.screenshot(), contentType: 'image/png' });
    await proof.checkpoint('social');
    await page.waitForTimeout(proofContract.tutorial.minimumHoldMs);
    await proof.attach();
  });

}
