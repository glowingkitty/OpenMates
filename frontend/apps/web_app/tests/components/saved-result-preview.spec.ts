/**
 * Saved preview behavior through real cards, memory state and forget action.
 * The isolated fixture supplies synthetic entries and no account/backend.
 * Assertions distinguish assistant actions from decorative grid markers,
 * verify shared state propagation, and retain memory after storage failure.
 */
import { expect, test } from '../helpers/cookie-audit';
import type { Locator, Page } from '@playwright/test';
import { waitForComponentPreview } from '../helpers/component-preview';
// playwright-account: not_required reason=isolated_component_preview
/* eslint-disable @typescript-eslint/no-require-imports -- Shared proof helpers use CommonJS. */
const { createVideoProofRuntime, defineVideoProof } = require('../helpers/video-proof');
const proofContract = defineVideoProof({
  id: 'saved-result-preview', title: 'Saved assistant preview forgets memory and restores More',
  surface: 'web', domain: 'app.dev.openmates.org', devices: ['web-laptop'],
  transcript: [
    { id: 'saved', checkpoint: 'saved', devices: ['web-laptop'], text: 'The saved assistant result shows a pink heart beside Expand.' },
    { id: 'forgotten', checkpoint: 'forgotten', devices: ['web-laptop'], text: 'Forgetting the memory restores More in both previews and shows the existing confirmation.' },
  ],
  assertions: [{ id: 'chats.rendering.inline-entity-interaction', checkpoint: 'forgotten', devices: ['web-laptop'], visual: 'Both result previews show More after the matching memory is forgotten, while the unrelated saved entry remains.' }],
  tutorial: { readingWordsPerSecond: 3, minimumHoldMs: 1200, maximumHoldMs: 4000 },
});

async function open(page: Page, theme: string, props: Record<string, unknown> = {}) {
  await page.setViewportSize({ width: 1100, height: 900 });
  const params = new URLSearchParams({ chrome: '0', width: '700', theme, props: JSON.stringify(props) });
  await page.goto(`/dev/preview/embeds/SavedResultPreviewFixture?${params}`);
  await waitForComponentPreview(page);
  await expect(page.getByTestId('saved-result-fixture')).toHaveAttribute('data-ready', 'true');
  await expect(page.getByTestId('saved-result-fixture')).toHaveAttribute('data-unrelated-present', 'true');
}

async function expectedColor(element: Locator, token: string) {
  return element.evaluate((node, variable) => {
    const probe = document.createElement('span');
    probe.style.background = `var(${variable})`;
    node.appendChild(probe);
    const color = getComputedStyle(probe).backgroundColor;
    probe.remove();
    return color;
  }, token);
}

async function assertHeartPaint(heart: Locator) {
  await expect(heart).toHaveCSS('width', '36px');
  await expect(heart).toHaveCSS('height', '36px');
  await expect(heart).toHaveCSS('border-radius', '50%');
  await expect(heart).toHaveCSS('background-color', await expectedColor(heart, '--color-app-health-start'));
  const icon = heart.locator('.clickable-icon');
  await expect(icon).toHaveCSS('background-color', 'rgb(255, 255, 255)');
  const masks = await icon.evaluate(node => {
    const probe = document.createElement('span');
    probe.style.maskImage = 'var(--icon-url-heart)';
    node.appendChild(probe);
    const result = { actual: getComputedStyle(node).maskImage, expected: getComputedStyle(probe).maskImage };
    probe.remove();
    return result;
  });
  expect(masks.expected).not.toBe('none');
  expect(masks.actual).toBe(masks.expected);
}

for (const theme of ['light', 'dark']) {
  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
  test(`saved assistant cards reuse exact memory state and the existing forget notification in ${theme}`, async ({ page }, testInfo) => {
    test.setTimeout(120_000);
    const proof = createVideoProofRuntime(proofContract, { device: 'web-laptop', attach: testInfo.attach.bind(testInfo) });
    for (const family of ['home', 'health', 'events', 'code']) {
      await open(page, theme, { family, collidingKeys: true });
      const fixture = page.getByTestId('saved-result-fixture');
      const first = page.getByTestId('saved-result-copy-0');
      const heart = first.getByTestId('result-preview-forget');
      await expect(page.getByTestId('result-preview-forget')).toHaveCount(2);
      await expect(page.getByTestId('result-preview-more')).toHaveCount(0);
      await expect(page.getByTestId('saved-embed-badge')).toHaveCount(0);
      await expect(heart).toHaveAccessibleName('Forget');
      await expect(heart).toHaveAttribute('aria-pressed', 'true');
      await assertHeartPaint(heart);
      expect(await heart.evaluate(node => node.nextElementSibling?.getAttribute('data-testid'))).toBe('result-preview-expand');
      await heart.hover();
      await expect(heart).toHaveCSS('scale', '1.02');
      if (family === 'home') {
        await testInfo.attach(`saved-result-heart-${theme}`, { body: await page.getByTestId('component-preview-canvas').screenshot({ animations: 'disabled' }), contentType: 'image/png' });
        await proof.checkpoint('saved');
      }
      await heart.focus();
      await heart.press('Enter');
      await expect(page.getByTestId('result-preview-forget')).toHaveCount(0);
      await expect(page.getByTestId('result-preview-more')).toHaveCount(2);
      await expect(first.getByTestId('result-preview-more')).toBeFocused();
      await expect(fixture).toHaveAttribute('data-deletions', '["saved-preview-fixture-memory"]');
      await expect(fixture).toHaveAttribute('data-unrelated-present', 'true');
      await expect(fixture).toHaveAttribute('data-expanded', '0');
      await expect(page.getByTestId('saved-result-notifications').locator('[data-notification-type="success"]')).toHaveText('Forgot "Saved preview result".');
      await first.getByTestId('result-preview-more').click();
      await expect(fixture).toHaveAttribute('data-menus', '1');
      await expect(fixture).toHaveAttribute('data-expanded', '0');
      if (family === 'home') {
        await proof.assert('chats.rendering.inline-entity-interaction', async () => {
          await expect(page.getByTestId('result-preview-more')).toHaveCount(2);
          await expect(fixture).toHaveAttribute('data-unrelated-present', 'true');
        });
        await proof.checkpoint('forgotten');
      }
    }
    await proof.attach();
  });

  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
  test(`failed unsave retains both saved hearts and reports failure without success in ${theme}`, async ({ page }) => {
    await open(page, theme, { failDelete: true });
    const failureLog = page.waitForEvent('console', { predicate: message => message.type() === 'error'
      && message.text().startsWith('[SavedEmbedPreviewAction] Failed to forget saved memory:') });
    await page.getByTestId('result-preview-forget').first().click();
    expect((await failureLog).text()).toContain('Failed to delete saved memory from browser storage.');
    await expect(page.getByTestId('saved-result-fixture')).toHaveAttribute('data-deletions', '["saved-preview-fixture-memory"]');
    await expect(page.getByTestId('saved-result-notifications').locator('[data-notification-type="error"]')).toHaveText('Failed to update saved memory.');
    await expect(page.getByTestId('saved-result-notifications').locator('[data-notification-type="success"]')).toHaveCount(0);
    await expect(page.getByTestId('result-preview-forget')).toHaveCount(2);
    await expect(page.getByTestId('result-preview-forget').first()).toBeEnabled();
    await expect(page.getByTestId('result-preview-more')).toHaveCount(0);
    await expect(page.getByTestId('saved-result-fixture')).toHaveAttribute('data-unrelated-present', 'true');
  });

  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
  test(`saved grid cards show only a decorative pink heart and open through the card in ${theme}`, async ({ page }, testInfo) => {
    for (const family of ['home', 'events', 'code']) {
      await open(page, theme, { mode: 'grid', family });
      const card = page.getByTestId('saved-result-copy-0').getByTestId('embed-preview');
      const marker = card.getByTestId('result-preview-saved-marker');
      await expect(card).toHaveAttribute('role', 'button');
      await expect(marker).toBeVisible();
      await expect(marker).toHaveAttribute('aria-hidden', 'true');
      await expect(marker).toHaveCSS('pointer-events', 'none');
      await expect(marker).toHaveCSS('background-color', 'rgba(0, 0, 0, 0)');
      await expect(marker).toHaveCSS('border-radius', '0px');
      expect(await marker.evaluate(node => (node as HTMLElement).tabIndex)).toBe(-1);
      await expect(marker.locator('span')).toHaveCSS('background-color', await expectedColor(marker, '--color-app-health-start'));
      await expect(card.locator('button, a')).toHaveCount(0);
      await expect(card.getByTestId('result-preview-more')).toHaveCount(0);
      await expect(card.getByTestId('result-preview-expand')).toHaveCount(0);
      await expect(card.getByTestId('saved-embed-badge')).toHaveCount(0);
      if (family === 'code') {
        const title = card.locator('.result-identity-title > span').first();
        await expect(title).toHaveCSS('text-overflow', 'ellipsis');
        expect((await title.boundingBox())!.x + (await title.boundingBox())!.width).toBeLessThanOrEqual((await marker.boundingBox())!.x - 2);
      }
      await page.mouse.move(1050, 850);
      await testInfo.attach(`${family}-saved-grid-marker-${theme}`, { body: await page.getByTestId('component-preview-canvas').screenshot({ animations: 'disabled' }), contentType: 'image/png' });
      const bounds = (await marker.boundingBox())!;
      await page.mouse.click(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2);
      await expect(page.getByTestId('saved-result-fixture')).toHaveAttribute('data-expanded', '1');
      await expect(page.getByTestId('saved-result-fixture')).toHaveAttribute('data-deletions', '[]');
    }
  });
}

// contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
test('busy saved action keeps keyboard focus and ignores More until the existing deletion finishes', async ({ page }) => {
  await open(page, 'light', { deferSync: true, collidingKeys: true });
  const first = page.getByTestId('saved-result-copy-0');
  await first.getByTestId('result-preview-forget').focus();
  await page.keyboard.press('Enter');
  const more = first.getByTestId('result-preview-more');
  await expect(more).toHaveAttribute('aria-disabled', 'true');
  await expect(more).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page.getByTestId('saved-result-fixture')).toHaveAttribute('data-menus', '0');
  await expect(page.getByTestId('saved-result-fixture')).toHaveAttribute('data-deletions', '["saved-preview-fixture-memory"]');
  await expect(page.getByTestId('saved-result-notifications').locator('[data-notification-type="success"]')).toHaveCount(0);
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('saved-preview-release-delete')));
  await expect(more).not.toHaveAttribute('aria-disabled', 'true');
  await expect(more).toBeFocused();
  await more.click();
  await expect(page.getByTestId('saved-result-fixture')).toHaveAttribute('data-menus', '1');
  await expect(page.getByTestId('saved-result-fixture')).toHaveAttribute('data-unrelated-present', 'true');
});

// contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
test('an unrelated saved memory never marks an unsaved assistant result', async ({ page }) => {
  await open(page, 'light', { saved: false });
  await expect(page.getByTestId('result-preview-more')).toHaveCount(2);
  await expect(page.getByTestId('result-preview-forget')).toHaveCount(0);
  await expect(page.getByTestId('result-preview-saved-marker')).toHaveCount(0);
  await expect(page.getByTestId('saved-embed-badge')).toHaveCount(0);
});
