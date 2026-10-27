import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
// contract-test: supporting surface=gui.web assertions=events-search.surface-parity,chats.sync.key-gated-recovery,chats.rendering.inline-entity-interaction
test('a saved reply hydrates its event card after delayed data, including after reload', async ({ page }) => {
  await page.setViewportSize({ width: 1100, height: 900 });
  await page.goto('/dev/preview/ReadOnlyMessage?chrome=0&width=520&theme=dark&variant=deferredEventReply');
  for (const reload of [false, true]) {
    if (reload) await page.reload({ waitUntil: 'domcontentloaded' });
    await waitForComponentPreview(page);
    const card = page.getByTestId('embed-preview');
    await expect(card).toBeVisible();
    await expect(card).toHaveAttribute('data-status', 'processing');
    await page.evaluate(() => document.dispatchEvent(new Event('preview:hydrate-reply-event')));
    await expect(card).toContainText('Community AI Hack');
    await expect(card.getByTestId('event-preview-attribution')).toContainText('Community Builders');
    await expect(card.getByTestId('event-preview-attribution')).toContainText('9:00 AM');
    await expect(card.getByTestId('event-preview-rsvps')).toContainText('42 RSVPs');
    await expect(card.locator('img')).toBeVisible();
    await expect.poll(() => card.locator('img').evaluate((image: HTMLImageElement) => image.naturalWidth)).toBeGreaterThan(0);
    await expect(card).toHaveAttribute('data-status', 'finished');
    const expand = card.getByTestId('result-preview-expand');
    await expand.hover();
    await expand.focus();
    await expect(expand).toBeFocused();
    await page.evaluate(() => document.addEventListener('embedfullscreen', (event) => {
      document.documentElement.dataset.expandedEvent = (event as CustomEvent).detail.embedId;
    }, { once: true }));
    await expand.press('Enter');
    await expect(page.locator('html')).toHaveAttribute('data-expanded-event', 'preview-deferred-reply-event');
  }
});
