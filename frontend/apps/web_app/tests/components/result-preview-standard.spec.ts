/**
 * Geometry and interaction contracts for the common embed preview shell.
 * Uses existing default fixtures and the real named assistant container.
 * Screenshots document requested Home, Health, Event and memory states;
 * assertions establish dimensions and behavior without claiming visual approval.
 */
import { expect, test } from '../helpers/cookie-audit';
import type { Locator, Page, TestInfo } from '@playwright/test';
import { waitForComponentPreview } from '../helpers/component-preview';
// playwright-account: not_required reason=isolated_component_preview
/* eslint-disable @typescript-eslint/no-require-imports -- Shared proof helpers use CommonJS. */
const { createVideoProofRuntime, defineVideoProof } = require('../helpers/video-proof');

const proofContract = defineVideoProof({
  id: 'result-preview-memory-control', title: 'Icon-only memory control changes saved state',
  surface: 'web', domain: 'app.dev.openmates.org', devices: ['web-laptop'],
  transcript: [
    { id: 'unsaved', checkpoint: 'unsaved', devices: ['web-laptop'], text: 'The unsaved memory action shows a heart and retains its accessible Add memory label.' },
    { id: 'saved', checkpoint: 'saved', devices: ['web-laptop'], text: 'Activating the heart changes its pressed state and pink saved appearance without adding visible text.' },
  ],
  assertions: [
    { id: 'chats.rendering.inline-entity-interaction', checkpoint: 'unsaved', devices: ['web-laptop'], visual: 'The memory button is a white circle containing the existing heart icon.' },
    { id: 'chats.rendering.assistant-document-convergence', checkpoint: 'saved', devices: ['web-laptop'], visual: 'The same button is pink after activation and exposes the Forget accessible label.' },
  ],
  tutorial: { readingWordsPerSecond: 3, minimumHoldMs: 1200, maximumHoldMs: 4000 },
});

const families = {
  discovery: ['web/WebsiteEmbedPreview', 'news/NewsEmbedPreview', 'events/EventEmbedPreview', 'home/HomeListingEmbedPreview', 'health/HealthAppointmentEmbedPreview', 'weather/WeatherDayEmbedPreview'],
  catalogue: ['code/CodeRepoEmbedPreview', 'models3d/Model3DResultEmbedPreview', 'jobs/JobsResultEmbedPreview', 'shopping/ShoppingResultEmbedPreview', 'nutrition/NutritionRecipeEmbedPreview', 'fitness/FitnessResultEmbedPreview', 'hosting/HostingDomainEmbedPreview', 'electronics/ElectronicsComponentEmbedPreview', 'design/DesignIconResultEmbedPreview'],
  mediaAndEditors: ['images/ImageEmbedPreview', 'images/ImageResultEmbedPreview', 'images/ImageGenerateEmbedPreview', 'videos/VideoEmbedPreview', 'videos/VideoGenerateEmbedPreview', 'travel/TravelConnectionEmbedPreview', 'travel/TravelStayEmbedPreview', 'code/CodeEmbedPreview', 'docs/DocsEmbedPreview', 'sheets/SheetEmbedPreview'],
} as const;
type Theme = 'light' | 'dark';
type Mode = 'compact' | 'mobile' | 'chat';
const requestedCaptures = new Set(['home/HomeListingEmbedPreview', 'health/HealthAppointmentEmbedPreview', 'events/EventEmbedPreview']);

async function isolateExternalMedia(page: Page) {
  const response = await page.request.get('/images/examples/group1.jpg');
  expect(response.ok()).toBeTruthy();
  const body = await response.body();
  await page.route('**/api/v1/image?*', route => route.fulfill({ contentType: 'image/jpeg', body }));
  await page.route('**/api/v1/metadata?*', route => route.fulfill({ json: {} }));
  await page.route('**/api/v1/youtube?*', route => route.fulfill({ json: {} }));
  await page.route('**/v1/apps/design/icons/iconify/**', route => route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M3 10 12 2l9 8v12H3z"/></svg>' }));
}

async function openPreview(page: Page, path: string, theme: Theme, mode: Mode) {
  await page.mouse.move(1100, 850);
  const params = new URLSearchParams({ chrome: '0', theme, width: mode === 'chat' ? '1000' : '390' });
  if (mode === 'chat') params.set('context', 'chat');
  if (mode === 'mobile') params.set('props', JSON.stringify({ isMobile: true }));
  await page.goto(`/dev/preview/embeds/${path}?${params}`);
  await waitForComponentPreview(page);
  return page.getByTestId('embed-preview');
}

async function assertShell(page: Page, card: Locator, mode: Mode, path: string) {
  await expect(card).toBeVisible();
  await expect(card).toHaveCSS('border-top-left-radius', '30px');
  await expect(card).toHaveCSS('border-top-right-radius', '30px');
  await expect(card).toHaveCSS('border-bottom-left-radius', '30px');
  await expect(card).toHaveCSS('border-bottom-right-radius', '30px');
  const box = (await card.boundingBox())!;
  const wrapper = (await page.getByTestId('component-preview-viewport').boundingBox())!;
  expect(box.x, `${path}: card starts inside its wrapper`).toBeGreaterThanOrEqual(wrapper.x - 1);
  expect(box.x + box.width, `${path}: card ends inside its wrapper`).toBeLessThanOrEqual(wrapper.x + wrapper.width + 1);
  expect(box.width, `${path}: standard width`).toBeCloseTo(mode === 'chat' ? wrapper.width : mode === 'mobile' ? 150 : 300, 0);
  expect(box.height, `${path}: standard height`).toBeCloseTo(mode === 'chat' ? 400 : mode === 'mobile' ? 290 : 200, 0);
  if (mode === 'chat') {
    await expect(card).toHaveAttribute('role', 'group');
    await card.hover({ position: { x: box.width - 12, y: box.height - 12 } });
    await expect(card, `${path}: assistant cards retain their position on hover`).toHaveCSS('transform', 'none');
  }
}

async function assertSharedCard(card: Locator, mode: Mode, path: string) {
  const shared = card.getByTestId('result-card-content');
  if (await shared.count() === 0) return;
  const title = shared.locator('h3');
  await expect(title, `${path}: title is limited to two lines`).toHaveCSS('-webkit-line-clamp', '2');
  const primaryText = await title.evaluate(element => {
    const probe = document.createElement('span');
    probe.style.color = 'var(--color-font-primary)';
    element.appendChild(probe);
    const color = getComputedStyle(probe).color;
    probe.remove();
    return color;
  });
  await expect(title, `${path}: title uses primary text contrast`).toHaveCSS('color', primaryText);
  if (mode === 'compact') {
    const copy = shared.locator('.card-copy');
    await expect(copy).toHaveCSS('padding-left', '48px');
    await expect(copy).toHaveCSS('padding-right', '48px');
    const titleBounds = (await title.boundingBox())!;
    const bounds = (await shared.boundingBox())!;
    expect(titleBounds.x - bounds.x, `${path}: title clears the carousel side controls`).toBeGreaterThanOrEqual(47);
    expect(bounds.x + bounds.width - titleBounds.x - titleBounds.width).toBeGreaterThanOrEqual(47);
  }
  const media = shared.getByTestId('result-card-media');
  if (await media.count() === 0 || !(await media.isVisible())) return;
  if (mode === 'compact') {
    const mediaBounds = (await media.boundingBox())!;
    const copyBounds = (await shared.locator('.card-copy').boundingBox())!;
    const cardBounds = (await shared.boundingBox())!;
    expect(copyBounds.y, `${path}: image does not sit behind the card's text`).toBeGreaterThanOrEqual(mediaBounds.y + mediaBounds.height - 1);
    expect(copyBounds.y + copyBounds.height, `${path}: text is inside the card`).toBeLessThanOrEqual(cardBounds.y + cardBounds.height + 1);
  }
  for (const image of await media.locator(':scope > img').all()) {
    await expect(image, `${path}: preserve the complete media aspect`).toHaveCSS('object-fit', 'contain');
    await expect.poll(() => image.evaluate((element: HTMLImageElement) => element.complete && element.naturalWidth > 0)).toBe(true);
  }
  if (mode === 'chat') {
    const frame = (await shared.boundingBox())!;
    const mediaBox = (await media.boundingBox())!;
    expect(mediaBox.x - frame.x, `${path}: text occupies one third`).toBeCloseTo(frame.width / 3, 0);
    expect(mediaBox.width, `${path}: media occupies two thirds`).toBeCloseTo(frame.width * 2 / 3, 0);
  }
}

for (const theme of ['light', 'dark'] as const) {
  for (const [group, components] of Object.entries(families)) {
    // contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence,chats.rendering.inline-entity-interaction
    test(`${group} previews preserve standard shells, media and assistant hover in ${theme}`, async ({ page }, testInfo) => {
      test.setTimeout(240_000);
      await page.setViewportSize({ width: 1120, height: 900 });
      await isolateExternalMedia(page);
      for (const path of components) {
        for (const mode of ['compact', 'mobile', 'chat'] as const) {
          await test.step(`${path}: ${mode}`, async () => {
            const card = await openPreview(page, path, theme, mode);
            await assertShell(page, card, mode, path);
            await assertSharedCard(card, mode, path);
            if (requestedCaptures.has(path) && mode !== 'mobile') {
              await page.mouse.move(1100, 850);
              await capture(page, testInfo, `${path.split('/')[0]}-${mode}-${theme}-standard`);
            }
          });
        }
      }
    });
  }

  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
  test(`grid card retains hover feedback while assistant card remains still in ${theme}`, async ({ page }) => {
    await page.setViewportSize({ width: 1120, height: 900 });
    await page.emulateMedia({ reducedMotion: 'no-preference' });
    await isolateExternalMedia(page);
    const card = await openPreview(page, 'web/WebsiteEmbedPreview', theme, 'compact');
    await expect(card).toHaveAttribute('role', 'button');
    await card.hover({ position: { x: 285, y: 185 } });
    await expect(card).toHaveClass(/hovering/);
    await expect.poll(() => card.evaluate(element => getComputedStyle(element).transform)).not.toBe('none');
    await openPreview(page, 'web/WebsiteEmbedPreview', theme, 'chat');
    await card.hover({ position: { x: 950, y: 350 } });
    await expect(card).toHaveCSS('transform', 'none');
  });

  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction,chats.rendering.assistant-document-convergence
  test(`memory heart toggles accessible unsaved and saved states without visible text in ${theme}`, async ({ page }, testInfo) => {
    const proof = createVideoProofRuntime(proofContract, { device: 'web-laptop', attach: testInfo.attach.bind(testInfo) });
    await page.goto(`/dev/preview/embeds/MemoryCtaFixture?chrome=0&width=390&theme=${theme}`);
    await waitForComponentPreview(page);
    const heart = page.getByTestId('memory-cta-toggle');
    await proof.assert('chats.rendering.inline-entity-interaction', async () => {
      await expect(heart).toHaveAccessibleName('Add memory');
      await expect(heart).toHaveAttribute('aria-pressed', 'false');
      await expect(heart).toHaveText('');
      await expect(heart).toHaveCSS('background-color', 'rgb(255, 255, 255)');
      const icon = heart.locator('[style*="--icon-name: heart"]');
      await expect(icon).toBeVisible();
      const heartMask = await icon.evaluate(element => {
        const probe = document.createElement('span');
        probe.style.maskImage = 'var(--icon-url-heart)';
        element.appendChild(probe);
        const masks = {
          actual: getComputedStyle(element).maskImage,
          expected: getComputedStyle(probe).maskImage,
        };
        probe.remove();
        return masks;
      });
      expect(heartMask.expected).not.toBe('none');
      expect(heartMask.actual).not.toBe('none');
      expect(heartMask.actual).toBe(heartMask.expected);
    });
    await capture(page, testInfo, `memory-heart-unsaved-white-${theme}`);
    await proof.checkpoint('unsaved');
    await heart.focus();
    await heart.press('Enter');
    await expect(heart).toHaveAttribute('aria-pressed', 'true');
    await expect(heart).toHaveAccessibleName('Forget');
    await expect(heart).toHaveText('');
    const expectedPink = await heart.evaluate(element => {
      const probe = document.createElement('span');
      probe.style.backgroundColor = 'var(--color-app-health-start)';
      element.appendChild(probe);
      const color = getComputedStyle(probe).backgroundColor;
      probe.remove();
      return color;
    });
    await proof.assert('chats.rendering.assistant-document-convergence', async () => {
      await expect(heart).toHaveCSS('background-color', expectedPink);
      await expect(heart).toHaveAttribute('aria-pressed', 'true');
      await expect(heart).toHaveAccessibleName('Forget');
    });
    await capture(page, testInfo, `memory-heart-saved-pink-${theme}`);
    await proof.checkpoint('saved');
    await heart.press('Space');
    await expect(heart).toHaveAttribute('aria-pressed', 'false');
    await expect(heart).toHaveAccessibleName('Add memory');
    await proof.attach();
  });
}

async function capture(page: Page, testInfo: TestInfo, name: string) {
  await testInfo.attach(name, { body: await page.getByTestId('component-preview-canvas').screenshot({ animations: 'disabled' }), contentType: 'image/png' });
}
