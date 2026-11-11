/** Selected-media proof uses real upload, encrypted storage and browser sharing. */
import type { Locator, Page } from '@playwright/test';
import { expect, test } from '@playwright/test';

export async function allowIsolatedAuthoredMedia(page: Page, baseUrl: string, apiUrl: string) {
  const allowed = new Set([new URL(baseUrl).origin, new URL(apiUrl).origin,
    'http://storage.ci.test:9000']);
  await page.route('**/*', route => {
    const url = new URL(route.request().url());
    return !['http:', 'https:'].includes(url.protocol) || allowed.has(url.origin)
      ? route.continue() : route.abort('blockedbyclient');
  });
  // No metadata/icon proxy should turn this provider-free fixture into egress.
  for (const pattern of ['**/api/v1/image?*', '**/api/v1/metadata?*',
    '**/v1/apps/design/icons/iconify/**']) {
    await page.route(pattern, route => route.fulfill({ status: 404, body: '' }));
  }
}

export async function expectSelectedRecipeImage(surface: Locator) {
  const image = surface.getByTestId('nutrition-recipe-image');
  await expect(image).toBeVisible({ timeout: 60_000 });
  await expect(image).toHaveAttribute('src', /^blob:/);
  await expect.poll(() => image.evaluate(node => {
    const image = node as HTMLImageElement;
    return image.complete && image.naturalWidth > 0 && image.naturalHeight > 0;
  }), { timeout: 60_000 }).toBe(true);
  await expect(surface.getByTestId('authored-result-context')).toContainText('Disposable CI image fixture');
  expect(await surface.innerText()).not.toMatch(/"(?:aes_key|aes_nonce|authored_media|source_json)"\s*:/);
}

export async function openSelectedRecipe(page: Page, childId: string, assistantMessageId: string) {
  const chat = page.getByTestId('active-chat-container');
  const assistant = chat.locator(`[data-testid="message-assistant"][data-message-id="${assistantMessageId}"]`);
  await test.step('Reveal the authored assistant message so its lazy editor initializes', async () => {
    await expect(chat.getByTestId('chat-history-container')).toHaveAttribute('data-scroll-state', 'ready', { timeout: 60_000 });
    await expect(assistant, 'the actual authoring response is present in the synced chat').toBeAttached({ timeout: 60_000 });
    // ReadOnlyMessage creates its editor only when the parent message enters
    // the chat viewport. The child card cannot be queried before that happens.
    await assistant.scrollIntoViewIfNeeded({ timeout: 15_000 });
  });
  const card = assistant.locator(`[data-testid="embed-preview"][data-embed-id="${childId}"]`);
  await test.step('Wait for the selected recipe card to attach and finish rendering', async () => {
    // A missing child previously consumed the remaining 900-second test budget
    // inside scrolling. Separate absence/hydration from activation failures.
    await expect(card, 'selected recipe card is present in the synced chat').toBeAttached({ timeout: 60_000 });
    await expect(card).toHaveAttribute('data-status', 'finished', { timeout: 60_000 });
    await expect(card).toHaveAttribute('aria-disabled', 'false', { timeout: 60_000 });
  });
  await test.step('Scroll to and activate the selected recipe card', async () => {
    await card.scrollIntoViewIfNeeded({ timeout: 15_000 });
    await expect(card).toBeVisible({ timeout: 15_000 });
    await card.focus({ timeout: 15_000 });
    await card.press('Enter', { timeout: 15_000 });
  });
  const overlay = page.getByTestId('embed-fullscreen-overlay').last();
  await expect(overlay.getByTestId('embed-header-title')).toHaveText('Supplied lentil recipe');
  await expectSelectedRecipeImage(overlay);
  return overlay;
}

export async function explicitlyShareSelectedChild(page: Page, overlay: Locator, childId: string) {
  await page.context().grantPermissions(['clipboard-read', 'clipboard-write'], { origin: new URL(page.url()).origin });
  await overlay.getByTestId('embed-share-button').click();
  await expect(page.getByTestId('share-embed-preview')).toBeVisible();
  const saved = page.waitForResponse(response => response.url().includes('/v1/share/embed/metadata')
    && response.request().method() === 'POST' && response.request().postDataJSON()?.embed_id === childId,
  { timeout: 60_000 });
  await page.getByTestId('share-generate-link').click();
  await expect(page.getByTestId('share-copy-link')).toBeVisible({ timeout: 60_000 });
  expect((await saved).ok(), 'explicit child-share metadata must be durable').toBe(true);
  await page.getByTestId('share-copy-link').click();
  await expect(page.getByTestId('share-copy-link')).toHaveClass(/copied/);
  const url = await page.evaluate(() => navigator.clipboard.readText());
  const parsed = new URL(url);
  expect(parsed.origin).toBe(new URL(page.url()).origin);
  expect(parsed.pathname === `/share/embed/${childId}` || /^\/s\/[A-Za-z0-9]+$/.test(parsed.pathname)).toBe(true);
  expect(parsed.hash.length > 1, 'share key remains in fragment').toBe(true);
  return url;
}

export async function deleteSelectedUploadMessage(page: Page, apiUrl: string, chatId: string,
  messageId: string, uploadId: string) {
  expect((await page.request.get(`${apiUrl}/v1/embeds/chats/${chatId}/embeds/${uploadId}`)).status(),
    'source upload must exist canonically before deletion').toBe(200);
  const message = page.locator(`[data-message-id="${messageId}"]`).getByTestId('user-message-content');
  // The upload preview inside the message has its own menu, so open the message
  // menu from its text. The menu closes itself on any scroll or layout move while
  // the upload preview settles, so reopen it until Delete can be used.
  const text = message.locator('p').filter({ hasText: /\S/ }).first();
  const menu = page.getByTestId('message-context-menu');
  const remove = menu.getByRole('button', { name: 'Delete', exact: true });
  await expect(async () => {
    if (!(await menu.isVisible())) await text.click({ button: 'right' });
    await expect(remove).toBeEnabled({ timeout: 2000 });
    await remove.click({ timeout: 2000 });
  }).toPass({ timeout: 45_000 });
  await menu.getByRole('button', { name: 'Confirm', exact: true }).click();
  await expect(message).toHaveCount(0);
  // The UI acknowledgement precedes Celery persistence. Wait for the canonical
  // authorized read to lose the source, rather than certifying optimistic UI.
  await expect.poll(async () => (await page.request.get(
    `${apiUrl}/v1/embeds/chats/${chatId}/embeds/${uploadId}`)).status(),
  { timeout: 90_000, intervals: [500, 1000, 2000] }).toBe(404);
}
