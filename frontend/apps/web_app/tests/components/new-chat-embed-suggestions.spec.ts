import { expect, test } from '../helpers/cookie-audit';

// playwright-account: not_required reason=isolated_component_preview
const PREVIEW = '/dev/preview/NewChatSuggestions?theme=light&background=%23dbeafe&width=1100&chrome=0';

// contract-test: supporting surface=gui.web assertions=message-input.suggestions.contextual
test('new-chat composer shows and selects an event from public examples', async ({ page }, testInfo) => {
  await page.addInitScript(() => {
    (window as Window & { previewSelectedEmbedId?: string }).previewSelectedEmbedId = '';
    window.addEventListener('preview-embed-selected', (event) => {
      (window as Window & { previewSelectedEmbedId?: string }).previewSelectedEmbedId = (event as CustomEvent<string>).detail;
    });
  });
  await page.goto(PREVIEW);

  const suggestions = page.getByTestId('suggestions-wrapper');
  await expect(suggestions).toBeVisible({ timeout: 30_000 });
  const embedCard = page.getByTestId('recent-embed-search-result').first();
  await expect(embedCard).toBeVisible({ timeout: 30_000 });
  await expect(embedCard).toContainText(/Berlin/i);
  await expect(embedCard.locator('.card-icon .icon-container')).toBeVisible();
  expect(await embedCard.evaluate((element) => element.scrollWidth <= element.clientWidth + 1)).toBe(true);
  await expect(page.locator('[data-testid="recent-embed-search-result"][data-app-id="code"]')).toBeVisible();
  await expect(page.locator('[data-testid="recent-embed-search-result"][data-app-id="events"]').first()).toBeVisible();
  const gradients = await page.evaluate(() => {
    const reference = document.createElement('div');
    document.body.appendChild(reference);
    const expected = (appId: string) => {
      reference.style.background = `var(--color-app-${appId})`;
      return getComputedStyle(reference).backgroundImage;
    };
    const result = {
      code: getComputedStyle(document.querySelector('[data-testid="recent-embed-search-result"][data-app-id="code"]')!).backgroundImage,
      events: getComputedStyle(document.querySelector('[data-testid="recent-embed-search-result"][data-app-id="events"]')!).backgroundImage,
      expectedCode: expected('code'),
      expectedEvents: expected('events'),
    };
    reference.remove();
    return result;
  });
  expect(gradients.expectedCode).not.toBe('none');
  expect(gradients.expectedEvents).not.toBe('none');
  expect(gradients.code).toBe(gradients.expectedCode);
  expect(gradients.events).toBe(gradients.expectedEvents);
  expect(gradients.code).not.toBe(gradients.events);
  await testInfo.attach('new-chat-embed-suggestions', {
    body: await page.screenshot(), contentType: 'image/png',
  });

  await embedCard.click();
  await expect.poll(() => page.evaluate(() =>
    (window as Window & { previewSelectedEmbedId?: string }).previewSelectedEmbedId,
  )).toMatch(/[0-9a-f-]{36}/);
});
