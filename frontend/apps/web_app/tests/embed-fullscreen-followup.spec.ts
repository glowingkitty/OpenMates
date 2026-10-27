/* eslint-disable @typescript-eslint/no-require-imports */
export {};
const { expect, test } = require('./helpers/cookie-audit');
const { loginToTestAccount, startNewChat, sendMessage, waitForChatReady } = require('./helpers/chat-test-helpers');
const { getE2EDebugUrl, withMockMarker } = require('./signup-flow-helpers');

// contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction,apps.results.shared-fullscreen
test('fullscreen correction sends the text and a rendered image into the existing chat', async ({ page }: { page: any }) => {
  test.setTimeout(180_000);
  expect(process.env.E2E_USE_MOCKS, 'This regression requires committed inference fixtures').toBeTruthy();
  expect(process.env.E2E_RECORD_FIXTURES).toBeFalsy();
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
  await loginToTestAccount(page, () => {}, async () => {}, { waitForEditor: true });
  await startNewChat(page);
  await sendMessage(page, withMockMarker('Capital of Germany?', 'chat_flow_capital', 'instant'));
  await expect(page.getByTestId('message-assistant').last()).toContainText('Berlin', { timeout: 60_000 });
  await waitForChatReady(page);
  const seeded = await page.evaluate(async () => {
    const seed = (window as Window & {
      __openmatesE2ESeedFollowupImage?: () => Promise<{ chatId: string; embedId: string }>;
    }).__openmatesE2ESeedFollowupImage;
    if (!seed) throw new Error('Followup image fixture hook unavailable');
    return seed();
  });
  const before = await page.getByTestId('message-user').count();
  let interpretations = 0;
  await page.route('**/v1/apps/workspace/interpret', (route: any) => {
    interpretations++;
    return route.fulfill({ status: 500, json: { detail: 'Chat followups must bypass interpretation' } });
  });
  // Enter through the real fullscreen listener with an already-resolved image.
  // Only the image bytes/metadata are fixtures; navigation and chat sending stay real.
  await page.evaluate(({ chatId, embedId }: { chatId: string; embedId: string }) => {
    document.dispatchEvent(new CustomEvent('embedfullscreen', { detail: {
      embedId, embedType: 'app-skill-use', sourceChatId: chatId, hasChatContext: true,
    }, bubbles: true }));
  }, seeded);
  const fullscreen = page.getByTestId('embed-fullscreen-overlay');
  await expect(fullscreen).toBeVisible({ timeout: 20_000 });
  const correction = 'Make the sky brighter and keep the mountain';
  await fullscreen.getByTestId('apps-request-textarea').fill(withMockMarker(correction, 'chat_flow_capital', 'instant'));
  const send = fullscreen.getByTestId('apps-request-submit');
  await expect(send).toHaveText('Send');
  await send.click();
  await expect(page.getByTestId('message-user')).toHaveCount(before + 1, { timeout: 30_000 });
  const delivered = page.getByTestId('message-user').last();
  await expect(delivered).toContainText(correction);
  await expect(delivered.getByTestId('embed-preview').first()).toBeVisible({ timeout: 30_000 });
  await expect(delivered.locator('img').first()).toBeVisible();
  await expect(delivered).not.toContainText('Result context');
  await expect(delivered).not.toContainText('"embed_id"');
  await expect(page.getByTestId('active-chat-container')).toHaveAttribute('data-current-chat-id', seeded.chatId);
  expect(new URL(page.url()).hash).toContain(`chat-id=${seeded.chatId}`);
  expect(interpretations).toBe(0);
  await expect(page.getByTestId('message-assistant')).toHaveCount(2, { timeout: 60_000 });
  await expect(page.getByTestId('message-assistant').last()).toContainText('Berlin', { timeout: 60_000 });
});
