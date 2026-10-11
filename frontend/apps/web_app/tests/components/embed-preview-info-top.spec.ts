import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
// contract-test: direct surface=gui.web assertions=chats.rendering.preview-info-top
test('embed preview info stays above details across statuses and card sizes', async ({ page }) => {
  const cases = [
    { variant: '', width: 1280, status: 'finished', layout: 'desktop' },
    { variant: 'processing', width: 1280, status: 'processing', layout: 'desktop' },
    { variant: 'error', width: 1280, status: 'error', layout: 'desktop' },
    { variant: 'cancelled', width: 1280, status: 'cancelled', layout: 'desktop' },
    { variant: 'mobile', width: 390, status: 'finished', layout: 'mobile' },
    { variant: 'processing', width: 390, status: 'processing', layout: 'desktop' },
  ] as const;

  for (const { variant, width, status, layout } of cases) {
    await page.setViewportSize({ width, height: width < 600 ? 844 : 900 });
    const query = new URLSearchParams({ chrome: '0', theme: 'light', width: String(width) });
    if (variant) query.set('variant', variant);
    await page.goto(`/dev/preview/embeds/web/WebSearchEmbedPreview?${query}`);
    await waitForComponentPreview(page);

    const card = page.getByTestId('embed-preview');
    const info = card.getByTestId('embed-basic-infos-bar');
    const details = card.locator('.details-section');
    await expect(card).toHaveAttribute('data-status', status);
    await expect(card.locator(`.${layout}-layout`)).toBeVisible();
    await expect(info).toHaveCount(1);
    await expect(info).toBeVisible();
    await expect(details).toBeVisible();
    await expect(info).toContainText('Search');
    await expect(info.locator('.stop-button')).toHaveCount(status === 'processing' ? 1 : 0);
    if (status === 'processing') await expect(info.locator('.stop-button')).toBeVisible();
    if (status === 'finished' || status === 'error') {
      await expect(card).toHaveAttribute('tabindex', '0');
    }

    const bounds = await card.evaluate((element) => {
      const bar = element.querySelector('[data-testid="embed-basic-infos-bar"]')!;
      const content = element.querySelector('.details-section')!;
      const cardBox = element.getBoundingClientRect();
      const barBox = bar.getBoundingClientRect();
      const contentBox = content.getBoundingClientRect();
      return {
        firstChildIsInfo: bar.parentElement?.firstElementChild === bar,
        cardTop: cardBox.top, cardBottom: cardBox.bottom,
        cardLeft: cardBox.left, cardRight: cardBox.right,
        barTop: barBox.top, barBottom: barBox.bottom,
        barLeft: barBox.left, barRight: barBox.right,
        detailsTop: contentBox.top, detailsBottom: contentBox.bottom,
      };
    });
    expect(bounds.firstChildIsInfo).toBe(true);
    expect(bounds.barTop).toBeGreaterThanOrEqual(bounds.cardTop - 1);
    expect(bounds.barBottom).toBeLessThanOrEqual(bounds.detailsTop + 1);
    expect(bounds.detailsBottom).toBeLessThanOrEqual(bounds.cardBottom + 1);
    expect(bounds.cardLeft).toBeGreaterThanOrEqual(-1);
    expect(bounds.cardRight).toBeLessThanOrEqual(width + 1);
    expect(bounds.barLeft).toBeGreaterThanOrEqual(bounds.cardLeft - 1);
    expect(bounds.barRight).toBeLessThanOrEqual(bounds.cardRight + 1);
  }
});

// contract-test: direct surface=gui.web assertions=chats.rendering.preview-info-top
test('expanded and full-image previews keep one visible info bar above content', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto('/dev/preview/embeds/web/WebSearchEmbedPreview?chrome=0&theme=light&width=700');
  await waitForComponentPreview(page);
  await page.locator('.component-mount').evaluate((element: HTMLElement) => {
    element.style.width = '700px';
    element.style.containerName = 'embed-preview';
    element.style.containerType = 'inline-size';
  });
  const largeCard = page.getByTestId('embed-preview');
  await expect(largeCard).toHaveCSS('height', '400px');
  const largeBounds = await largeCard.evaluate((element) => {
    const card = element.getBoundingClientRect();
    const bar = element.querySelector('[data-testid="embed-basic-infos-bar"]')!.getBoundingClientRect();
    const details = element.querySelector('.details-section')!.getBoundingClientRect();
    return {
      cardTop: card.top, cardBottom: card.bottom,
      barTop: bar.top, barBottom: bar.bottom,
      detailsTop: details.top, detailsBottom: details.bottom,
    };
  });
  expect(largeBounds.barTop).toBeGreaterThanOrEqual(largeBounds.cardTop - 1);
  expect(largeBounds.barBottom).toBeLessThanOrEqual(largeBounds.detailsTop + 1);
  expect(largeBounds.detailsBottom).toBeLessThanOrEqual(largeBounds.cardBottom + 1);

  await page.goto('/dev/preview/embeds/images/ImageResultEmbedPreview?chrome=0&theme=light');
  await waitForComponentPreview(page);
  const imageCard = page.getByTestId('embed-preview');
  await expect(imageCard.getByTestId('embed-basic-infos-bar')).toHaveCount(1);
  const imageBounds = await imageCard.evaluate((element) => {
    const card = element.getBoundingClientRect();
    const bar = element.querySelector('[data-testid="embed-basic-infos-bar"]')!.getBoundingClientRect();
    const details = element.querySelector('.details-section.full-width-image')!.getBoundingClientRect();
    return { cardBottom: card.bottom, barBottom: bar.bottom, detailsTop: details.top, detailsBottom: details.bottom };
  });
  expect(imageBounds.barBottom).toBeLessThanOrEqual(imageBounds.detailsTop + 1);
  expect(imageBounds.detailsBottom).toBeLessThanOrEqual(imageBounds.cardBottom + 1);
});
