/**
 * Focused proof for the fixture-driven newsroom design review surface.
 * It intentionally verifies only the representative responsive structure and
 * core preview interactions before the user approves the visual direction.
 */
import { expect, test } from '../helpers/cookie-audit';

// playwright-account: not_required reason=isolated_component_preview
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { createVideoProofRuntime, defineVideoProof } = require('../helpers/video-proof');

const phone = Number(process.env.PLAYWRIGHT_VIDEO_WIDTH) === 390;
const device = phone ? 'web-phone' : 'web-laptop';
const width = phone ? '390' : '1180';

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

function preview(variant?: string) {
  return `/dev/preview/newsroom/NewsroomSurface?${new URLSearchParams({
    chrome: '0',
    theme: 'light',
    width,
    ...(variant ? { variant } : {}),
  })}`;
}

// contract-test: tooling
test('presents the UI-first newsroom layouts for approval', async ({ page }, testInfo) => {
  test.setTimeout(60_000);
  const proof = createVideoProofRuntime(proofContract, { device, attach: testInfo.attach.bind(testInfo) });

  await page.goto(preview(), { waitUntil: 'networkidle' });
  const root = page.getByTestId('newsroom-surface');
  await expect(root).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Introducing: Workflow Automation' })).toBeVisible();
  if (phone) {
    await expect(page.getByRole('complementary', { name: 'Newsroom archive' })).toBeHidden();
    await page.getByTestId('sidebar-toggle').click();
    await expect(page.getByRole('complementary', { name: 'Newsroom archive' })).toBeVisible();
    await page.getByRole('button', { name: 'Close Newsroom navigation' }).click();
  } else {
    await expect(page.getByRole('complementary', { name: 'Newsroom archive' })).toBeVisible();
  }
  const featuredCard = page.getByTestId('newsroom-card-health-app-redesigned');
  const standardCard = page.getByTestId('newsroom-card-new-code-skills');
  await expect(featuredCard).toBeVisible();
  await expect(standardCard).toBeVisible();
  expect((await featuredCard.boundingBox())?.height).toBeGreaterThan(200);
  expect((await standardCard.boundingBox())?.height).toBeGreaterThan(300);
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
    await page.goto(preview(variant), { waitUntil: 'networkidle' });
    await expect(page.getByTestId('newsroom-surface')).toHaveAttribute('data-view', variant === 'Blog' ? 'blog' : 'blog-post');
  }

  await page.goto(preview('Release'), { waitUntil: 'networkidle' });
  await expect(page.getByText('Workflow Automation helps people').first()).toBeVisible();
  const slideshow = page.getByTestId('newsroom-slideshow');
  await slideshow.getByRole('button', { name: 'Next media' }).click();
  await expect(slideshow).toContainText('2 / 3');
  await proof.assert('newsroom-article', async () => {
    expect(await page.getByTestId('newsroom-surface').evaluate((element) => element.scrollWidth <= element.clientWidth + 1)).toBe(true);
  });
  await proof.checkpoint('article');
  await page.waitForTimeout(proofContract.tutorial.minimumHoldMs);

  await page.goto(preview('Social post'), { waitUntil: 'networkidle' });
  await expect(page.getByTestId('newsroom-surface')).toHaveAttribute('data-view', 'social-post');
  await expect(page.getByRole('button', { name: /View original post/ })).toBeVisible();
  await proof.assert('newsroom-social', async () => {
    expect(await page.getByTestId('newsroom-surface').evaluate((element) => element.scrollWidth <= element.clientWidth + 1)).toBe(true);
  });
  await proof.checkpoint('social');
  await page.waitForTimeout(proofContract.tutorial.minimumHoldMs);
  await proof.attach();
});
