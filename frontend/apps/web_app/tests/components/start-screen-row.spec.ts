/**
 * Focused component spec for the start-screen row (TASK-1321).
 * Assertions: daily-inspiration.start-row-rhythm, daily-inspiration.start-row-cards,
 * daily-inspiration.start-row-actions, daily-inspiration.start-row-suggestions,
 * continue-carousel.upcoming-entry. Synthetic data from StartScreenRowPreviewHarness.preview.ts.
 */
import type { Page, TestInfo } from '@playwright/test';
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview

const PREVIEW = '/dev/preview/welcome/StartScreenRowPreviewHarness?chrome=0&theme=light';

async function openPreview(page: Page, width: number, height: number, variant?: string): Promise<void> {
  await page.setViewportSize({ width, height });
  await page.goto(`${PREVIEW}${variant ? `&variant=${variant}` : ''}`, { waitUntil: 'domcontentloaded' });
  await waitForComponentPreview(page);
  await expect(page.getByTestId('start-row-harness')).toBeVisible();
}

async function rowKinds(page: Page): Promise<string[]> {
  return page.getByTestId('recent-chats-scroll-container').locator(':scope > [data-testid]').evaluateAll((nodes: Element[]) =>
    nodes.map((node: Element) => {
      const id = node.getAttribute('data-testid');
      if (id === 'start-row-actions') return 'actions';
      return id === 'start-row-inspiration-card' ? 'inspiration' : 'chat';
    }),
  );
}

async function expectFirstCardCentred(page: Page): Promise<void> {
  const row = page.getByTestId('recent-chats-scroll-container');
  const [rowBox, cardBox] = await Promise.all([row.boundingBox(), row.locator(':scope > [data-testid]').first().boundingBox()]);
  expect(Math.abs(cardBox!.x + cardBox!.width / 2 - (rowBox!.x + rowBox!.width / 2))).toBeLessThanOrEqual(2);
}

async function attach(page: Page, testInfo: TestInfo, name: string): Promise<void> {
  await testInfo.attach(name, { body: await page.getByTestId('start-row-harness').screenshot(), contentType: 'image/png' });
}

test.describe('start-screen row', () => {
  // contract-test: direct surface=gui.web assertions=daily-inspiration.start-row-rhythm,daily-inspiration.start-row-cards
  test('interleaves inspirations after two and then every third own chat, large cards only', async ({ page }, testInfo) => {
    test.setTimeout(60_000);
    await openPreview(page, 1280, 800);

    expect(await rowKinds(page)).toEqual(['chat', 'chat', 'inspiration', 'chat', 'chat', 'chat', 'inspiration', 'chat', 'actions']);
    await expect(page.locator('[data-testid="resume-chat-card"]')).toHaveCount(0);

    const labels = page.getByTestId('start-row-inspiration-label');
    await expect(labels).toHaveCount(2);
    for (const label of await labels.all()) await expect(label).toHaveText('Daily inspiration');

    const firstCard = page.getByTestId('resume-chat-large-card').first();
    const box = await firstCard.boundingBox();
    expect(box?.width).toBe(300);
    expect(box?.height).toBe(200);
    await expect(firstCard.getByTestId('resume-card-pin')).toBeVisible();
    await expectFirstCardCentred(page);

    const inspiration = page.getByTestId('start-row-inspiration-card').first();
    await expect(inspiration.getByTestId('start-card-media')).toBeVisible();
    await attach(page, testInfo, 'desktop-1280');

    await inspiration.hover();
    await attach(page, testInfo, 'desktop-1280-inspiration-hover');
    await inspiration.click();
    await expect(page.getByTestId('start-row-harness')).toHaveAttribute('data-last-activated', 'insp-octopus');
  });

  // contract-test: direct surface=gui.web assertions=continue-carousel.upcoming-entry
  test('shows the upcoming event as one compact entry below the row', async ({ page }, testInfo) => {
    test.setTimeout(60_000);
    await openPreview(page, 820, 1180);
    const entry = page.getByTestId('start-screen-upcoming-entry');
    await expect(entry).toBeVisible();
    await expect(entry.getByTestId('start-screen-upcoming-title')).toHaveText('Dentist appointment');
    await expect(entry.getByTestId('start-screen-upcoming-time')).toHaveText('Today, 15:30');
    const rowBox = await page.getByTestId('recent-chats-scroll-container').boundingBox();
    const entryBox = await entry.boundingBox();
    expect(entryBox!.y).toBeGreaterThan(rowBox!.y + rowBox!.height - 1);
    expect(entryBox!.height).toBeLessThan(56);
    await attach(page, testInfo, 'tablet-820');
    await entry.click();
    await expect(page.getByTestId('start-row-harness')).toHaveAttribute('data-last-activated', 'upcoming');
  });

  // contract-test: direct surface=gui.web assertions=daily-inspiration.start-row-rhythm,daily-inspiration.start-row-cards
  test('phone keeps the next card peeking and a new user sees only inspirations', async ({ page }, testInfo) => {
    test.setTimeout(60_000);
    await openPreview(page, 390, 844);
    await expectFirstCardCentred(page);
    const cards = page.getByTestId('recent-chats-scroll-container').locator(':scope > [data-testid]');
    const second = await cards.nth(1).boundingBox();
    expect(second!.x).toBeLessThan(390);
    expect(second!.x).toBeGreaterThan(200);
    await expect(page.getByTestId('start-screen-upcoming-title')).toHaveJSProperty('scrollWidth', await page.getByTestId('start-screen-upcoming-title').evaluate((node) => node.clientWidth));
    await attach(page, testInfo, 'phone-390');

    await openPreview(page, 390, 844, 'newUser');
    expect(await rowKinds(page)).toEqual(['inspiration', 'inspiration', 'inspiration', 'actions']);
    await expectFirstCardCentred(page);
    await attach(page, testInfo, 'phone-390-new-user');
  });

  // contract-test: direct surface=gui.web assertions=daily-inspiration.start-row-rhythm,daily-inspiration.start-row-cards
  test('full row shows at most ten cards, inspirations included, then the actions', async ({ page }, testInfo) => {
    test.setTimeout(60_000);
    await openPreview(page, 1440, 900, 'fullRow');
    expect(await rowKinds(page)).toEqual([
      'chat', 'chat', 'inspiration', 'chat', 'chat', 'chat', 'inspiration', 'chat', 'chat', 'chat', 'actions',
    ]);
    await attach(page, testInfo, 'desktop-1440-full-row');
    await openPreview(page, 1280, 800, 'plainInspirations');
    await expect(page.getByTestId('start-row-inspiration-card').first().getByTestId('start-card-icon')).toBeVisible();
    await attach(page, testInfo, 'desktop-1280-inspiration-without-image');
  });

  // contract-test: direct surface=gui.web assertions=daily-inspiration.start-row-actions,daily-inspiration.start-row-suggestions
  for (const viewport of [
    { name: 'phone-390', width: 390, height: 844 },
    { name: 'tablet-820', width: 820, height: 1180 },
    { name: 'desktop-1280', width: 1280, height: 800 },
  ]) {
    test(`browse actions end the row and suggestions sit below it at ${viewport.name}`, async ({ page }, testInfo) => {
      test.setTimeout(60_000);
      for (const mode of ['signed-in', 'guest'] as const) {
        await openPreview(page, viewport.width, viewport.height, mode === 'guest' ? 'guest' : undefined);
        const row = page.getByTestId('recent-chats-scroll-container');
        const actions = row.getByTestId('start-row-actions');
        await expect(row.locator(':scope > [data-testid]').last()).toHaveAttribute('data-testid', 'start-row-actions');
        const expectedIds = mode === 'guest'
          ? ['guest-interest-select-interests', 'guest-show-all-examples']
          : ['chat-show-all', 'chat-search'];
        expect(await actions.locator('button').evaluateAll((nodes) => nodes.map((node) => node.getAttribute('data-testid')))).toEqual(expectedIds);
        const actionsBox = await actions.boundingBox();
        expect(actionsBox!.height).toBe(200);
        // Every action label is shown in full, never cut off with an ellipsis.
        const clipped = await actions.locator('.start-row-action-label').evaluateAll((nodes: Element[]) =>
          nodes.filter((node) => node.scrollWidth > node.clientWidth + 1 || node.scrollHeight > node.clientHeight + 1).map((node) => node.textContent)
        );
        expect(clipped).toEqual([]);
        // Nothing about browsing sits below the row any more.
        await expect(page.locator('[data-testid="chat-browse-controls"], [data-testid="guest-example-link-row"]')).toHaveCount(0);

        const suggestions = page.getByTestId('start-screen-suggestions');
        await expect(suggestions).toBeVisible();
        const items = suggestions.getByTestId('follow-up-suggestion-item');
        await expect(items).toHaveCount(3);
        const rowBox = await row.boundingBox();
        const suggestionsBox = await suggestions.boundingBox();
        expect(suggestionsBox!.y).toBeGreaterThan(rowBox!.y + rowBox!.height - 1);
        expect(suggestionsBox!.x).toBeGreaterThanOrEqual(0);
        expect(suggestionsBox!.x + suggestionsBox!.width).toBeLessThanOrEqual(viewport.width + 1);
        // Each suggestion stays on one line (issue CCFK8); long text is cut with an ellipsis.
        const wrapped = await suggestions.getByTestId('follow-up-suggestion-text').evaluateAll((nodes: Element[]) =>
          nodes
            .filter((node) => {
              const style = getComputedStyle(node);
              return style.whiteSpace !== 'nowrap' || node.getBoundingClientRect().height >= parseFloat(style.lineHeight) * 1.5;
            })
            .map((node) => node.textContent)
        );
        expect(wrapped).toEqual([]);

        await actions.scrollIntoViewIfNeeded();
        await attach(page, testInfo, `${viewport.name}-${mode}-row-end`);
        await row.evaluate((node) => node.scrollTo({ left: 0 }));
        await attach(page, testInfo, `${viewport.name}-${mode}`);

        await actions.getByTestId(expectedIds[0]).click();
        await expect(page.getByTestId('start-row-harness')).toHaveAttribute('data-last-activated', mode === 'guest' ? 'interests' : 'show-all');
        const firstSuggestion = (await items.first().innerText()).trim();
        await items.first().click();
        await expect(page.getByTestId('start-row-harness')).toHaveAttribute('data-last-activated', `suggestion:${firstSuggestion}`);
      }
    });
  }
});
