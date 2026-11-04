/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Regression: a follow-up sent right after a reload (Stay logged in) must send and
 * get a reply. Mirrors the web-rust-core-bench TS arm: send, wait for the reply,
 * reload the open chat, then type and click Send as soon as the composer is usable.
 */
export {};
const { test, expect } = require('./helpers/cookie-audit');
const { createSignupLogger, createStepScreenshotter, archiveExistingScreenshots,
  getTestAccount, withMockMarker } = require('./signup-flow-helpers');
const { loginToTestAccount, startNewChat, sendMessage } = require('./helpers/chat-test-helpers');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

// contract-test: supporting surface=gui.web assertions=chats.send.immediate-admission
test('follow-up sent right after a reload is not stuck as a queued edit and gets a reply', async ({ page }: { page: any }, testInfo: any) => {
  test.setTimeout(240000);
  test.skip(!TEST_EMAIL || !TEST_PASSWORD || !TEST_OTP_KEY, 'Test account credentials are required.');
  const logs: string[] = [];
  page.on('console', (msg: any) => {
    const text = msg.text();
    if (/^(error|warning)$/.test(msg.type()) || /handleSend/.test(text)) logs.push(`${msg.type()} ${text.slice(0, 400)}`);
  });
  const logCheckpoint = createSignupLogger('RELOAD_FOLLOWUP_SEND');
  const takeStepScreenshot = createStepScreenshotter(logCheckpoint);
  try {
    await archiveExistingScreenshots(logCheckpoint);
    await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
    await startNewChat(page, logCheckpoint);
    await sendMessage(page, withMockMarker('What is the capital of Germany?', 'chat_flow_capital', 'fast'), logCheckpoint);
    await expect(page).toHaveURL(/chat-id=[a-zA-Z0-9-]+/, { timeout: 15000 });
    await expect(page.getByTestId('message-assistant')).toHaveCount(1, { timeout: 90000 });
    await expect(page.getByTestId('message-assistant').first().getByTestId('message-content')).not.toBeEmpty();
    await page.waitForTimeout(4000); // let the server store the reply before reloading

    await page.reload({ waitUntil: 'commit' });
    await expect(page.getByTestId('message-assistant')).toHaveCount(1, { timeout: 30000 });
    await expect(page.getByTestId('message-user')).toHaveCount(1);

    const editor = page.getByTestId('message-editor').filter({ visible: true }).first().locator('.ProseMirror');
    await editor.waitFor({ state: 'visible', timeout: 60000 });
    await editor.click();
    await page.keyboard.insertText(withMockMarker('Give me one quick tip for studying.', 'chat_flow_quick_tip', 'medium'));
    await expect(page.getByTestId('queued-edit-banner')).toHaveCount(0);
    await page.getByTestId('composer-send-button').filter({ visible: true }).first().click();
    await expect(page.getByTestId('message-user')).toHaveCount(2, { timeout: 30000 });
    await expect(page.getByTestId('queued-edit-cancel')).toHaveCount(0);
    await expect(page.getByTestId('message-assistant')).toHaveCount(2, { timeout: 90000 });
    await expect(page.getByTestId('message-assistant').last().getByTestId('message-content')).not.toBeEmpty();
  } finally {
    await testInfo.attach('console-sync-logs', { body: logs.slice(-200).join('\n'), contentType: 'text/plain' });
    await testInfo.attach('final-state', { body: await page.screenshot().catch(() => Buffer.from('')), contentType: 'image/png' });
  }
});
