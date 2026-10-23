import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
import type { Locator } from '@playwright/test';
// playwright-account: not_required reason=isolated_component_preview

for (const status of ['processing', 'finished']) for (const width of [390, 1100]) {
  // contract-test: supporting surface=gui.web assertions=chats.layout.responsive-history
  test(`news skill-call row has no result carousel arrows at ${width}px (${status})`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    const variant = status === 'processing' ? 'skillCallsProcessing' : 'skillCallsFinished';
    await page.goto(`/dev/preview/embeds/GroupedResultPreviewHarness?chrome=0&context=chat&theme=dark&width=${width}&variant=${variant}`);
    await waitForComponentPreview(page);
    const fixture = page.getByTestId('grouped-result-fixture');
    await expect(fixture).toHaveAttribute('data-ready', 'true');
    const group = fixture.getByTestId('app-skill-embed-group');
    const cards = group.getByTestId('embed-preview');
    await expect(cards).toHaveCount(3);
    await expect(group.getByTestId('grouped-preview-navigation')).toHaveCount(0);
    await expect(group.getByRole('button', { name: /^(Previous|Next)$/ })).toHaveCount(0);
    for (const card of await cards.all()) {
      await expect(card).toHaveAttribute('data-status', status);
      await expect(card).toHaveCSS('width', '300px');
      await expect(card).toHaveCSS('height', '200px');
      await expect(card).toHaveCSS('border-radius', '30px');
      await expect(card).toContainText('via Brave Search');
      await expect(card.getByTestId('embed-basic-infos-bar')).toBeVisible();
      await expect(card.getByTestId('embed-result-identity')).toHaveCount(0);
      await expect(card.locator('.result-corner')).toHaveCount(0);
    }
    await expect(cards.first()).toContainText('artificial intelligence latest developments');
    await expect(cards.first().getByRole('button', { name: 'Stop', exact: true })).toHaveCount(status === 'processing' ? 1 : 0);
    const scroller = group.getByTestId('app-skill-embed-group-scroll');
    await expect.poll(() => scroller.evaluate(element => element.scrollWidth - element.clientWidth)).toBeGreaterThan(0);
    const segments = group.getByTestId('embed-group-scroll-indicator').getByRole('button');
    await expect(segments).toHaveCount(3);
    await segments.last().click();
    await expect(cards.last()).toBeInViewport({ ratio: 1 });
    const lastScroll = await scroller.evaluate(element => element.scrollLeft);
    expect(lastScroll).toBeGreaterThan(0);
    await segments.first().click();
    await expect.poll(() => scroller.evaluate(element => element.scrollLeft)).toBeLessThan(lastScroll);
    await expect(cards.first()).toBeInViewport({ ratio: 1 });
    await testInfo.attach(`news-skills-${status}-${width}`, { body: await fixture.screenshot(), contentType: 'image/png' });
  });
}

async function assertCardGeometry(card: Locator, previous: Locator, next: Locator) {
  await expect(card).toHaveAttribute('role', 'group');
  const bounds = (await card.boundingBox())!;
  await expect(previous).toBeVisible();
  await expect(next).toBeVisible();
  for (const [control, side] of [[previous, 'left'], [next, 'right']] as const) {
    const button = (await control.boundingBox())!;
    expect(button.width).toBeLessThanOrEqual(44);
    expect(button.height).toBeLessThanOrEqual(44);
    expect(bounds.y + bounds.height - button.y - button.height).toBeCloseTo(10, 0);
    expect(side === 'left' ? button.x - bounds.x : bounds.x + bounds.width - button.x - button.width).toBeCloseTo(10, 0);
  }
  const copy = await card.locator('.card-copy').evaluate(element => {
    const style = getComputedStyle(element);
    const title = element.querySelector('h3')!;
    const titleStyle = getComputedStyle(title);
    const rect = title.getBoundingClientRect();
    const cardRect = element.closest('[data-testid="embed-preview"]')!.getBoundingClientRect();
    return { left: Number.parseFloat(style.paddingLeft), right: Number.parseFloat(style.paddingRight),
      titleLeft: rect.left - cardRect.left, titleRight: cardRect.right - rect.right,
      titleHeight: rect.height, lineHeight: Number.parseFloat(titleStyle.lineHeight),
      clamp: titleStyle.webkitLineClamp, horizontalOverflow: title.scrollWidth > title.clientWidth + 1 };
  });
  expect(copy.left).toBeGreaterThanOrEqual(48);
  expect(copy.right).toBeGreaterThanOrEqual(48);
  expect(copy.titleLeft).toBeGreaterThanOrEqual(48);
  expect(copy.titleRight).toBeGreaterThanOrEqual(48);
  expect(copy.clamp).toBe('2');
  expect(copy.titleHeight).toBeLessThanOrEqual(copy.lineHeight * 2 + 1);
  expect(copy.horizontalOverflow).toBe(false);
  await expect(card.getByTestId('result-preview-more')).toBeVisible();
  await expect(card.getByTestId('result-preview-expand')).toBeVisible();
}

async function assertEventAttribution(card: Locator) {
  const title = (await card.getByTestId('result-card-title').textContent()) || '';
  const index = title.startsWith('First') ? 0 : title.startsWith('Second') ? 1 : 2;
  await expect(card.getByTestId('event-preview-attribution')).toContainText(`by Berlin Event Community ${index + 1}`);
  await expect(card.getByTestId('event-preview-attribution')).toContainText('7:00 PM');
  await expect(card.getByTestId('event-preview-rsvps')).toContainText(`${80 + index} RSVPs`);
  await expect(card.getByTestId('event-preview-attribution')).toHaveCSS('font-size', '16px');
  const isLarge = (await card.boundingBox())!.width > 400;
  if (isLarge) await expect(card.getByTestId('event-preview-rsvps')).toBeVisible();
  else await expect(card.getByTestId('event-preview-rsvps')).toBeHidden();
  for (const row of [card.getByTestId('event-preview-attribution'), ...(isLarge ? [card.getByTestId('event-preview-rsvps')] : [])]) {
    await expect(row).toBeVisible();
    await expect(row).toBeInViewport({ ratio: 1 });
    const clipping = await row.evaluate(element => {
      const bounds = element.getBoundingClientRect();
      const card = element.closest('[data-testid="embed-preview"]')!;
      const cardBounds = card.getBoundingClientRect();
      const clippedBy: string[] = [];
      for (let parent = element.parentElement; parent; parent = parent.parentElement) {
        const style = getComputedStyle(parent);
        const clip = parent.getBoundingClientRect();
        if (/(hidden|clip|auto|scroll)/.test(style.overflowX) && (bounds.left < clip.left - 1 || bounds.right > clip.right + 1)) clippedBy.push(`${parent.className}:horizontal`);
        if (/(hidden|clip|auto|scroll)/.test(style.overflowY) && (bounds.top < clip.top - 1 || bounds.bottom > clip.bottom + 1)) clippedBy.push(`${parent.className}:vertical`);
        if (parent === card) break;
      }
      return { clippedBy, topGap: bounds.top - cardBounds.top, bottomGap: cardBounds.bottom - bounds.bottom,
        leftGap: bounds.left - cardBounds.left, rightGap: cardBounds.right - bounds.right };
    });
    expect(clipping.clippedBy).toEqual([]);
    expect(clipping.topGap).toBeGreaterThanOrEqual(0);
    expect(clipping.bottomGap).toBeGreaterThanOrEqual(0);
    expect(clipping.leftGap).toBeGreaterThanOrEqual(48);
    expect(clipping.rightGap).toBeGreaterThanOrEqual(48);
  }
}

for (const app of ['home', 'events']) for (const theme of ['light', 'dark']) for (const width of [390, 1100]) {
  // contract-test: supporting surface=gui.web assertions=chats.layout.responsive-history
  test(`${app} real compact and large grouped navigation at ${width}px in ${theme}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1100 });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto(`/dev/preview/embeds/GroupedResultPreviewHarness?chrome=0&context=chat&theme=${theme}&width=${width}${app === 'events' ? '&variant=events' : ''}`);
    await waitForComponentPreview(page);
    const fixture = page.getByTestId('grouped-result-fixture');
    await expect(fixture).toHaveAttribute('data-ready', 'true');
    await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
    const compact = page.getByTestId('compact-group');
    const scroller = compact.locator('.group-scroll-container');
    const items = compact.locator('.embed-group-item');
    await expect(items).toHaveCount(3);
    const card = items.first().getByTestId('embed-preview');
    await expect(card).toHaveCSS('width', '300px');
    await expect(card).toHaveCSS('height', '200px');
    await expect(card).toHaveCSS('border-radius', '30px');
    await assertCardGeometry(card, items.first().getByTestId('grouped-preview-previous'), items.first().getByTestId('grouped-preview-next'));
    const firstTitle = await card.getByTestId('result-card-title').textContent();
    if (app === 'events') await assertEventAttribution(card);
    await items.first().getByTestId('grouped-preview-next').click();
    await expect.poll(() => scroller.evaluate(element => element.scrollLeft)).toBeGreaterThan(0);
    await items.nth(1).getByTestId('grouped-preview-previous').click();
    await expect.poll(() => scroller.evaluate(element => element.scrollLeft)).toBeLessThan(2);
    await expect(page.getByTestId('embed-fullscreen-overlay')).toHaveCount(0);

    const large = page.getByTestId('large-group');
    await large.scrollIntoViewIfNeeded();
    const shell = large.getByTestId('embed-preview-large');
    const largeCard = shell.getByTestId('embed-preview');
    await expect(largeCard).toHaveCSS('height', width > 600 ? '400px' : '200px');
    await assertCardGeometry(largeCard, large.getByRole('button', { name: 'Previous', exact: true }), large.getByRole('button', { name: 'Next', exact: true }));
    await large.getByRole('button', { name: 'Next', exact: true }).click();
    await expect(large.getByRole('tab', { name: 'Go to slide 2 of 3' })).toHaveAttribute('aria-selected', 'true');
    const active = large.locator('.embed-preview-large-overlay:not(.embed-preview-large-overlay--hidden)');
    await expect(active.getByTestId('result-card-title')).not.toHaveText(firstTitle!);
    if (app === 'events') await assertEventAttribution(active.getByTestId('embed-preview'));
    await large.getByRole('button', { name: 'Previous', exact: true }).click();
    await expect(large.getByRole('tab', { name: 'Go to slide 1 of 3' })).toHaveAttribute('aria-selected', 'true');
    await expect(largeCard.getByTestId('result-card-title')).toHaveText(firstTitle!);
    if (app === 'events') await assertEventAttribution(largeCard);

    const ungrouped = page.getByTestId('ungrouped-result').getByTestId('embed-preview');
    await expect(ungrouped.locator('.card-copy')).toHaveCSS('padding-left', '48px');
    await expect(ungrouped.locator('.card-copy')).toHaveCSS('padding-right', '48px');
    await expect(ungrouped.getByTestId('grouped-preview-navigation')).toHaveCount(0);
    // Capture the complete multi-surface fixture. Its three stacked examples
    // can exceed the preview route's fixed-height, overflow-hidden viewport.
    const fixtureHeight = Math.ceil((await fixture.boundingBox())!.height);
    await page.setViewportSize({ width, height: Math.max(1100, fixtureHeight + 128) });
    await fixture.scrollIntoViewIfNeeded();
    if (app === 'events') await assertEventAttribution(ungrouped);
    if (app === 'events') {
      await assertEventAttribution(card);
      await assertEventAttribution(largeCard);
    }
    await testInfo.attach(`${app}-grouped-${theme}-${width}`, { body: await fixture.screenshot(), contentType: 'image/png' });
  });
}
