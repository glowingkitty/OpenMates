import { test, expect } from './helpers/cookie-audit';
import { openChatAfterContextSync } from './helpers/chat-hydration';
import { createTimelineFixture, persistTimelineFixture, type TimelineFixture } from './helpers/chat-timeline-fixture';
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { createWorkflowCliHome, loginWorkflowCliViaPair, removeWorkflowCliHome, workflowApiUrl } = require('./helpers/workflow-cli-e2e-helpers');

// contract-test: direct surface=gui.web assertions=chat-message-timeline.full-history-loading,chat-message-timeline.compression-history,chat-message-timeline.access-and-lifecycle,chat-message-timeline.preview-and-activate,chat-message-timeline.bookmarks,chat-message-timeline.accessible-layout
test('cold ten-thousand-exchange history persists private bookmarks and loads the exact compressed section with retry', async ({ page, playwright }, info) => {
  test.setTimeout(480_000);
  const home = createWorkflowCliHome('message-timeline');
  const apiUrl = workflowApiUrl();
  let fixture: TimelineFixture | undefined;
  const catalogueKeys = new Set<string>();
  const catalogueDiagnostics: unknown[] = [];
  const catalogueWarnings: string[] = [];
  const sectionRequests: URL[] = [];
  const outgoingTypes: string[] = [];
  const bookmarkWrites: Record<string, unknown>[] = [];
  page.on('websocket', socket => socket.on('framesent', event => {
    try { outgoingTypes.push(JSON.parse(String(event.payload)).type); } catch { /* Non-JSON transport frame. */ }
  }));
  page.on('response', async response => {
    if (!new URL(response.url()).pathname.endsWith('/timeline')) return;
    const payload = await response.json().catch(() => ({}));
    catalogueDiagnostics.push({ status: response.status(), count: payload.entries?.length,
      hasMore: payload.has_more, before: payload.before, chatId: payload.chat_id,
      detail: payload.detail, sampleTypes: payload.entries?.[0] && Object.fromEntries(
        Object.entries(payload.entries[0]).map(([key, value]) => [key, typeof value])) });
    for (const row of payload.entries ?? []) for (const key of Object.keys(row)) catalogueKeys.add(key);
  });
  page.on('requestfailed', request => {
    if (new URL(request.url()).pathname.endsWith('/timeline')) catalogueDiagnostics.push({ failed: request.failure()?.errorText });
  });
  page.on('console', message => {
    if (message.text().startsWith('[ChatHistory] Timeline catalogue unavailable')) catalogueWarnings.push(message.text());
  });
  page.on('request', request => {
    if (request.url().includes('/messages/window?')) sectionRequests.push(new URL(request.url()));
    if (new URL(request.url()).pathname.endsWith('/settings/encrypted-account') && request.method() === 'POST') {
      bookmarkWrites.push(request.postDataJSON());
    }
  });
  try {
    await page.setViewportSize({ width: 1280, height: 900 });
    await loginWorkflowCliViaPair(page, apiUrl, home, 'CHAT_TIMELINE');
    fixture = createTimelineFixture(apiUrl, home);
    persistTimelineFixture(fixture, 'seed');
    const before = persistTimelineFixture(fixture, 'snapshot');
    await page.goto('/');
    await openChatAfterContextSync(page, fixture.chatId, info);
    const rail = page.getByTestId('timeline-rail');
    await expect(rail).toHaveAttribute('data-count', '10000', { timeout: 90_000 });
    const laneLeft = await page.getByTestId('chat-history-content').evaluate(node => node.getBoundingClientRect().left + parseFloat(getComputedStyle(node).paddingLeft));
    expect((await rail.boundingBox())!.x + (await rail.boundingBox())!.width).toBeCloseTo(laneLeft - 8, 0);
    expect((await rail.boundingBox())!.height).toBe(240);
    await expect(rail.locator('button')).toHaveCount(0);
    const firstId = String(fixture.messages[0].client_message_id);
    const first = page.locator(`[data-testid="message-user"][data-message-id="${firstId}"]`);
    await expect(first).toHaveCount(0);
    expect(await page.locator('.message-wrapper').count()).toBeLessThan(180);
    expect([...catalogueKeys].sort()).toEqual(['created_at', 'message_id', 'role', 'user_message_id']);

    const anonymous = await playwright.request.newContext();
    try {
      const denied = await anonymous.get(`${apiUrl}/v1/chats/${fixture.chatId}/timeline`);
      expect([401, 403]).toContain(denied.status());
      expect(await denied.text()).not.toContain(firstId);
    } finally { await anonymous.dispose(); }

    await rail.focus();
    await rail.press('Home');
    await expect(page.getByTestId('timeline-user-preview')).toContainText('Question 0:');
    await expect(page.getByTestId('timeline-response-preview')).toContainText('Response 0:');
    await expect(page.getByTestId('timeline-before-compression')).toBeVisible();
    await expect(first).toHaveCount(0); // Preview alone preserves the recent transcript.
    await page.screenshot({ path: info.outputPath('timeline-cold-preview.png') });
    let bookmark = page.getByTestId('timeline-preview').getByTestId('message-bookmark-button');
    await bookmark.click();
    await expect(bookmark).toHaveAttribute('aria-pressed', 'true');
    expect(bookmarkWrites).toHaveLength(1);
    expect(Object.keys(bookmarkWrites[0])).toEqual(['encrypted_settings']);
    expect(typeof bookmarkWrites[0].encrypted_settings).toBe('string');
    expect(JSON.stringify(bookmarkWrites[0])).not.toContain(firstId);
    expect(JSON.stringify(bookmarkWrites[0])).not.toContain('message_bookmarks');
    await expect(first).toHaveCount(0);
    await expect(rail.locator(`.timeline-mark.bookmarked[data-message-id="${firstId}"]`)).toHaveCount(1);
    await page.screenshot({ path: info.outputPath('timeline-bookmarked-unloaded.png') });

    // A fresh application instance restores the account's encrypted settings.
    await page.reload();
    await openChatAfterContextSync(page, fixture.chatId, info);
    await expect(rail).toHaveAttribute('data-count', '10000', { timeout: 90_000 });
    await rail.focus();
    await rail.press('Home');
    await expect(page.getByTestId('timeline-user-preview')).toContainText('Question 0:');
    bookmark = page.getByTestId('timeline-preview').getByTestId('message-bookmark-button');
    await expect(bookmark).toHaveAttribute('aria-pressed', 'true');
    await expect(first).toHaveCount(0);
    await expect(rail.locator(`.timeline-mark.bookmarked[data-message-id="${firstId}"]`)).toHaveCount(1);
    const failBookmark = async (route: import('@playwright/test').Route) => route.abort('internetdisconnected');
    await page.route('**/settings/encrypted-account', failBookmark);
    await bookmark.click();
    await expect(bookmark).toHaveAttribute('data-save-failed', 'true');
    await expect(bookmark).toHaveAttribute('aria-pressed', 'true');
    await page.unroute('**/settings/encrypted-account', failBookmark);
    await bookmark.click();
    await expect(bookmark).toHaveAttribute('aria-pressed', 'false');
    await expect(rail.locator('.timeline-mark.bookmarked')).toHaveCount(0);
    await expect(first).toHaveCount(0);
    // Put keyboard focus back on the rail without changing its selected identity.
    await rail.focus();
    await rail.press('Enter');
    await expect(first).toBeVisible();
    await expect(first).toHaveAttribute('data-forgotten', 'true');
    await expect(first).toContainText('Question 0:');
    expect(sectionRequests.some(url => url.searchParams.get('anchor_message_id') === firstId
      && url.searchParams.get('respect_compression_boundary') === 'false')).toBe(true);
    expect(await page.locator('.message-wrapper').count()).toBeLessThan(180);
    await page.screenshot({ path: info.outputPath('timeline-cold-section.png') });

    // The real successful reads are untouched. Fail the next uncached section once.
    let failed = false;
    const failOneSection = async (route: import('@playwright/test').Route) => {
      const url = new URL(route.request().url());
      if (!failed && url.searchParams.get('direction') === 'around'
          && url.searchParams.get('anchor_message_id') !== firstId) {
        failed = true;
        await route.abort('internetdisconnected');
      } else await route.continue();
    };
    await page.route('**/messages/window?**', failOneSection);
    await rail.focus();
    await rail.press('Home');
    await rail.press('PageDown');
    await rail.press('PageDown');
    await rail.press('Enter');
    await expect(page.getByTestId('timeline-preview')).toContainText('This section couldn’t be loaded.');
    expect(failed).toBe(true);
    await expect(first).toBeVisible();
    await page.unroute('**/messages/window?**', failOneSection);
    await page.getByTestId('timeline-retry').click();
    const retryId = sectionRequests[sectionRequests.length - 1].searchParams.get('anchor_message_id')!;
    await expect(page.locator(`[data-testid="message-user"][data-message-id="${retryId}"]`)).toBeVisible();
    await expect(page.getByTestId('timeline-preview')).toHaveCount(0);
    const target = page.locator(`.message-wrapper[data-message-id="${retryId}"]`);
    await expect.poll(() => target.evaluate(node => node.getBoundingClientRect().top - node.closest('.chat-history-container')!.getBoundingClientRect().top)).toBeCloseTo(70, 0);
    await expect(page.locator('.message-wrapper.user').getByTestId('message-bookmark-button')).toHaveCount(0);
    await page.getByRole('button', { name: 'Scroll to bottom', exact: true }).click();
    const latestId = String(fixture.messages[fixture.messages.length - 1].client_message_id);
    await expect(page.locator(`[data-message-id="${latestId}"]`)).toBeVisible();
    await expect(rail).toHaveAttribute('aria-valuenow', '10000');
    expect(persistTimelineFixture(fixture, 'snapshot')).toEqual(before);
    expect(outgoingTypes.filter(type => /^(send_chat_message|new_chat_message|chat_message_added|message_send|compress_chat|store_chat_compression_checkpoint)$/.test(type))).toEqual([]);
    await page.screenshot({ path: info.outputPath('timeline-back-latest.png') });
  } finally {
    await info.attach('timeline-catalogue-diagnostics', { contentType: 'application/json',
      body: JSON.stringify({ pages: catalogueDiagnostics, warnings: catalogueWarnings }) });
    if (fixture) persistTimelineFixture(fixture, 'cleanup');
    removeWorkflowCliHome(home);
  }
});
