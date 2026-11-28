/**
 * Focused component spec for the start-screen row (TASK-1321).
 * Assertions: daily-inspiration.start-row-rhythm, daily-inspiration.start-row-cards,
 * daily-inspiration.start-row-actions, daily-inspiration.start-row-suggestions,
 * continue-carousel.upcoming-entry, daily-inspiration.start-row-active-first. Synthetic data from StartScreenRowPreviewHarness.preview.ts.
 */
import type { Page, TestInfo } from '@playwright/test';
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview

const PREVIEW = '/dev/preview/welcome/StartScreenRowPreviewHarness?chrome=0&theme=light';
/** Cards sit in animated slot wrappers (startRowMotion); the browse actions are the last direct item. */
const ROW_ITEMS = ':scope > [data-testid], :scope > .harness-slot > [data-testid]';

async function openPreview(page: Page, width: number, height: number, variant?: string): Promise<void> {
  await page.setViewportSize({ width, height });
  await page.goto(`${PREVIEW}${variant ? `&variant=${variant}` : ''}`, { waitUntil: 'domcontentloaded' });
  await waitForComponentPreview(page);
  await expect(page.getByTestId('start-row-harness')).toBeVisible();
}

async function rowKinds(page: Page): Promise<string[]> {
  return page.getByTestId('recent-chats-scroll-container').locator(ROW_ITEMS).evaluateAll((nodes: Element[]) =>
    nodes.map((node: Element) => {
      const id = node.getAttribute('data-testid');
      if (id === 'start-row-actions') return 'actions';
      return id === 'start-row-inspiration-card' ? 'inspiration' : 'chat';
    }),
  );
}

async function expectFirstCardCentred(page: Page): Promise<void> {
  const row = page.getByTestId('recent-chats-scroll-container');
  const [rowBox, cardBox] = await Promise.all([row.boundingBox(), row.locator(ROW_ITEMS).first().boundingBox()]);
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

    // A daily inspiration is the normal chat card (gradient, icon, same size) with a small
    // label, never a video or article image as the background (Marco, 21 Nov).
    const inspiration = page.getByTestId('start-row-inspiration-card').first();
    await expect(inspiration.locator('img')).toHaveCount(0);
    await expect(inspiration.getByTestId('start-card-icon')).toBeVisible();
    const inspirationBox = await inspiration.boundingBox();
    expect(inspirationBox?.width).toBe(box?.width);
    expect(inspirationBox?.height).toBe(box?.height);
    const [chatBackground, inspirationBackground] = await Promise.all([
      firstCard.evaluate((node) => getComputedStyle(node).backgroundImage),
      inspiration.evaluate((node) => getComputedStyle(node).backgroundImage),
    ]);
    expect(chatBackground).toContain('gradient');
    expect(inspirationBackground).toContain('gradient');
    for (const card of [firstCard, inspiration]) {
      const radius = await card.evaluate((node) => getComputedStyle(node).borderTopLeftRadius);
      await expect(card.getByTestId('start-card-glows')).toHaveCSS('clip-path', `inset(0px round ${radius})`);
    }
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
    const cards = page.getByTestId('recent-chats-scroll-container').locator(ROW_ITEMS);
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

  // contract-test: direct surface=gui.web assertions=daily-inspiration.start-row-cards
  test('a draft card shows up to three lines of the draft text', async ({ page }, testInfo) => {
    await openPreview(page, 390, 844, 'draftCard');
    const card = page.getByTestId('start-row-draft-card');
    await expect(card).toBeVisible();
    const text = card.getByTestId('resume-large-title');
    await expect(text).toContainText('surprise birthday dinner');
    const metrics = await text.evaluate((node: Element) => {
      const style = getComputedStyle(node);
      const element = node as HTMLElement;
      return { clamp: style.webkitLineClamp, lines: Math.round(element.clientHeight / parseFloat(style.lineHeight)), cut: element.scrollHeight > element.clientHeight + 1 };
    });
    // Marco, 22 Nov: two lines wasted the card; the long draft fills three lines, then the ellipsis.
    expect(metrics).toEqual({ clamp: '3', lines: 3, cut: true });
    await testInfo.attach('phone-390-draft-card-3-lines', { body: await card.screenshot(), contentType: 'image/png' });
    // Same card with the old two-line limit, for the before/after comparison.
    await text.evaluate((node: Element) => { (node as HTMLElement).style.setProperty('-webkit-line-clamp', '2'); (node as HTMLElement).style.setProperty('line-clamp', '2'); });
    await testInfo.attach('phone-390-draft-card-2-lines-before', { body: await card.screenshot(), contentType: 'image/png' });
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
        await expect(row.locator(ROW_ITEMS).last()).toHaveAttribute('data-testid', 'start-row-actions');
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

  // contract-test: direct surface=gui.web assertions=daily-inspiration.start-row-active-first
  test('running chats come first with an Active label; a chat that becomes active fades in at the front', async ({ page }, testInfo) => {
    test.setTimeout(90_000);
    for (const viewport of [{ name: 'desktop', width: 1280, height: 800 }, { name: 'phone', width: 390, height: 844 }]) {
      await openPreview(page, viewport.width, viewport.height, 'activeChats');
      const row = page.getByTestId('recent-chats-scroll-container');
      expect(await rowKinds(page)).toEqual(['chat', 'chat', 'inspiration', 'chat', 'chat', 'chat', 'inspiration', 'chat', 'actions']);
      const items = row.locator(ROW_ITEMS);
      for (const index of [0, 1]) {
        await expect(items.nth(index)).toHaveAttribute('data-testid', 'start-row-active-card');
        await expect(items.nth(index).getByTestId('start-row-active-pill')).toHaveText('Active');
      }
      await expect(row.getByTestId('start-row-active-card')).toHaveCount(2);
      await expectFirstCardCentred(page);
      await attach(page, testInfo, `active-first-${viewport.name}`);

      // A chat starts running: it fades in from below at the front and the others slide right.
      const secondBefore = await items.nth(0).boundingBox();
      await page.waitForTimeout(400); // motion is enabled once the row has settled
      await page.getByTestId('start-row-harness-activate').click();
      await page.waitForTimeout(90);
      const midway = await items.nth(0).evaluate((node) => {
        const slot = node.parentElement as HTMLElement;
        return { opacity: Number(getComputedStyle(slot).opacity), transform: getComputedStyle(slot).transform };
      });
      expect(midway.opacity, 'the new active card is still fading in').toBeLessThan(1);
      expect(midway.transform, 'the new active card rises from below').not.toBe('none');
      await attach(page, testInfo, `active-fading-in-${viewport.name}`);
      await page.waitForTimeout(450);
      await expect(row.getByTestId('start-row-active-card')).toHaveCount(3);
      await expect(items.nth(0)).toHaveAttribute('data-testid', 'start-row-active-card');
      const formerFirst = await items.nth(1).boundingBox();
      expect(formerFirst!.x, 'the former first card slid one slot to the right').toBeGreaterThan(secondBefore!.x + 100);
      await row.evaluate((node) => node.scrollTo({ left: 0 }));
      await attach(page, testInfo, `active-after-${viewport.name}`);
    }

    // Reduced motion: the change is immediate.
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await openPreview(page, 1280, 800, 'activeChats');
    await page.waitForTimeout(400);
    await page.getByTestId('start-row-harness-activate').click();
    const slotOpacity = await page.getByTestId('recent-chats-scroll-container').locator(ROW_ITEMS).nth(0).evaluate((node) => Number(getComputedStyle(node.parentElement as HTMLElement).opacity));
    expect(slotOpacity).toBe(1);
    await expect(page.getByTestId('start-row-active-pill').first()).toBeVisible();
  });
});
