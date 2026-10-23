import { expect, test } from '../helpers/cookie-audit';
import { focusComposer } from '../helpers/composer-focus';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
test.setTimeout(120_000);

// contract-test: direct surface=gui.web assertions=message-input.suggestions.contextual,message-input.actions.visibility
test('existing-chat search cards receive a real click without losing the draft', async ({ page }) => {
  await page.goto('/dev/preview/ChatSearchComposerFixture?chrome=0&theme=dark&width=390');
  await waitForComponentPreview(page);
  await focusComposer(page);
  const editor = page.getByTestId('message-editor').getByRole('textbox', { includeHidden: true });
  await editor.fill('OpenClaw Anonymous Berlin #9');
  const card = page.getByTestId('recent-embed-search-result').filter({ hasText: 'OpenClaw Anonymous Berlin #9' }).first();
  await expect(card).toBeVisible();
  const selectedId = await card.getAttribute('data-embed-id');
  expect(selectedId).toMatch(/^[0-9a-f-]{36}$/);
  await card.click();
  const fixture = page.getByTestId('composer-search-fixture');
  await expect(fixture).toHaveAttribute('data-selected-embed', selectedId!);
  await expect(fixture).toHaveAttribute('data-selected-owner', 'example-ai-workshops-meetups-berlin');
  await expect(editor).toHaveText('OpenClaw Anonymous Berlin #9');
});

for (const component of ['ChatSearchSuggestions', 'NewChatSuggestions']) {
  const PREVIEW = `/dev/preview/${component}?theme=light&background=%23dbeafe&width=1100&chrome=0`;

  // contract-test: supporting surface=gui.web assertions=message-input.suggestions.contextual
  test(`${component} embed cards are readable and select an exact embed`, async ({ page }, testInfo) => {
    await page.addInitScript(() => {
      (window as Window & { previewSelectedEmbedId?: string }).previewSelectedEmbedId = '';
      window.addEventListener('preview-embed-selected', (event) => {
        const { embedId, chatId } = (event as CustomEvent<{ embedId: string; chatId: string }>).detail;
        (window as Window & { previewSelectedEmbedId?: string }).previewSelectedEmbedId = embedId;
        (window as Window & { previewSelectedEmbedChatId?: string }).previewSelectedEmbedChatId = chatId;
      });
    });
    await page.goto(PREVIEW);

    const suggestions = page.getByTestId(component === 'ChatSearchSuggestions' ? 'chat-search-suggestions' : 'suggestions-wrapper');
    await expect(suggestions).toBeVisible({ timeout: 30000 });
    const embedCard = page.getByTestId('recent-embed-search-result').first();
    await expect(embedCard).toBeVisible({ timeout: 30000 });
    await expect(embedCard).toContainText(/Berlin/i);
    await expect(suggestions.locator('.chat-result-wrapper:has(.embed-result-card) .card-date')).toHaveCount(0);
    await expect(embedCard.locator('.card-icon .icon-container')).toBeVisible();
    expect(await embedCard.evaluate((element) => element.scrollWidth <= element.clientWidth + 1)).toBe(true);
    await expect(page.locator('[data-testid="recent-embed-search-result"][data-app-id="events"]').first()).toBeVisible();
    const gradients = await page.evaluate(() => {
      const reference = document.createElement('div');
      document.body.appendChild(reference);
      const expected = (appId: string) => {
        reference.style.background = `var(--color-app-${appId})`;
        return getComputedStyle(reference).backgroundImage;
      };
      const result = {
        events: getComputedStyle(document.querySelector('[data-testid="recent-embed-search-result"][data-app-id="events"]')!).backgroundImage,
        expectedCode: expected('code'),
        expectedEvents: expected('events'),
      };
      reference.remove();
      return result;
    });
    expect(gradients.expectedCode).not.toBe('none');
    expect(gradients.expectedEvents).not.toBe('none');
    expect(gradients.events).toBe(gradients.expectedEvents);
    await testInfo.attach('composer-embed-suggestions', {
      body: await page.screenshot(), contentType: 'image/png',
    });

    // Separate exact-title searches cover both app gradients independently of
    // the six-result limit as the public example catalog grows.
    await page.goto(`${PREVIEW}&variant=codeResult`);
    const codeCard = page.locator('[data-testid="recent-embed-search-result"][data-app-id="code"]').first();
    await expect(codeCard).toBeVisible({ timeout: 30000 });
    await expect(codeCard).toContainText('src/main.js');
    const codeGradient = await codeCard.evaluate(element => getComputedStyle(element).backgroundImage);
    expect(codeGradient).toBe(gradients.expectedCode);
    expect(codeGradient).not.toBe(gradients.events);

    // A narrow split panel must use compact cards even on a desktop viewport.
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto(PREVIEW.replace('width=1100', 'width=390'));
    await expect(embedCard).toBeVisible({ timeout: 30000 });
    await expect(embedCard).toHaveCSS('width', '210px');
    await expect(suggestions.locator('.chat-result-wrapper:has(.embed-result-card) .card-date')).toHaveCount(0);
    const geometry = await embedCard.evaluate(element => {
      const card = element.getBoundingClientRect();
      const wrapper = element.parentElement!.getBoundingClientRect();
      const strip = element.closest('.chat-search-wrapper, .suggestions-wrapper')!.getBoundingClientRect();
      return { cardWidth: card.width, wrapperWidth: wrapper.width, left: card.left - strip.left, right: strip.right - card.right };
    });
    expect(geometry.wrapperWidth).toBeCloseTo(geometry.cardWidth, 0);
    expect(geometry.left).toBeGreaterThanOrEqual(0);
    expect(geometry.right).toBeGreaterThanOrEqual(0);
    expect(Math.abs(geometry.left - geometry.right)).toBeLessThan(2);

    await embedCard.click();
    await expect.poll(() => page.evaluate(() =>
      (window as Window & { previewSelectedEmbedId?: string }).previewSelectedEmbedId,
    )).toMatch(/[0-9a-f-]{36}/);
    await expect.poll(() => page.evaluate(() =>
      (window as Window & { previewSelectedEmbedChatId?: string }).previewSelectedEmbedChatId,
    )).toBe('example-ai-workshops-meetups-berlin');
  });
}
