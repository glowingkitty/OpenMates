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
const { expireIsolatedAccessWindow } = require('./helpers/isolated-session-rotation');

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
    await page.keyboard.insertText(withMockMarker('Help me plan an open source conference.', 'chat_recommendations', 'medium'));
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

async function sendRightAway(page: any, text: string, expectedTurns: number): Promise<void> {
  const editor = page.getByTestId('message-editor').filter({ visible: true }).first().locator('.ProseMirror');
  await editor.waitFor({ state: 'visible', timeout: 60000 });
  await editor.click();
  await page.keyboard.insertText(text);
  await page.getByTestId('composer-send-button').filter({ visible: true }).first().click();
  await expect(page.getByTestId('message-user')).toHaveCount(expectedTurns, { timeout: 30000 });
  await expect(page.getByTestId('message-assistant')).toHaveCount(expectedTurns, { timeout: 90000 });
  await expect(page.getByTestId('message-assistant').last().getByTestId('message-content')).not.toBeEmpty();
}

// contract-test: supporting surface=gui.web assertions=chats.send.immediate-admission,auth.session.lifecycle
test('first send after several reloads and a refresh-token rotation is accepted on the open socket', async ({ page }: { page: any }, testInfo: any) => {
  test.setTimeout(300000);
  test.skip(!TEST_EMAIL || !TEST_PASSWORD || !TEST_OTP_KEY, 'Test account credentials are required.');
  test.skip(process.env.OPENMATES_CI_ISOLATED !== '1', 'Rotating the session requires the disposable isolated CI backend.');
  const logs: string[] = [];
  page.on('console', (msg: any) => {
    const text = msg.text();
    if (/^(error|warning)$/.test(msg.type()) || /handleSend|PreparedPrivacy/.test(text)) logs.push(`${msg.type()} ${text.slice(0, 400)}`);
  });
  const refusals = () => logs.filter(line => /Freshness check refused|Reason: Session (unavailable|invalid)|^error Failed to handle message send:/.test(line));
  const logCheckpoint = createSignupLogger('RELOAD_ROTATION_SEND');
  const takeStepScreenshot = createStepScreenshotter(logCheckpoint);
  try {
    await archiveExistingScreenshots(logCheckpoint);
    await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
    await startNewChat(page, logCheckpoint);
    await sendMessage(page, withMockMarker('What is the capital of Germany?', 'chat_flow_capital', 'fast'), logCheckpoint);
    await expect(page).toHaveURL(/chat-id=[a-zA-Z0-9-]+/, { timeout: 15000 });
    await expect(page.getByTestId('message-assistant')).toHaveCount(1, { timeout: 90000 });
    await page.waitForTimeout(4000); // let the server store the reply before reloading

    for (let reload = 0; reload < 3; reload += 1) {
      await page.reload({ waitUntil: 'commit' });
      await expect(page.getByTestId('message-assistant')).toHaveCount(1, { timeout: 30000 });
    }
    await page.getByTestId('message-editor').filter({ visible: true }).first().locator('.ProseMirror')
      .waitFor({ state: 'visible', timeout: 60000 });

    // Rotate the refresh token while this page's socket stays open on the old
    // hash, exactly as another tab's reload or a near-expiry /session does.
    const cookie = async () => (await page.context().cookies()).find((value: any) => value.name === 'auth_refresh_token')?.value;
    const original = await cookie();
    if (!original) throw new Error('Authenticated refresh cookie is missing.');
    const apiUrl = process.env.OPENMATES_E2E_API_URL;
    if (!apiUrl) throw new Error('OPENMATES_E2E_API_URL is required.');
    const sessionId = await page.evaluate(() => sessionStorage.getItem('session_id'));
    expireIsolatedAccessWindow(original);
    const rotated = await page.context().request.post(`${apiUrl}/v1/auth/session`, {
      data: { session_id: sessionId }, headers: { Origin: new URL(page.url()).origin },
    });
    expect(rotated.status()).toBe(200);
    expect((await rotated.json()).success).toBe(true);
    expect(await cookie(), 'The /session call must publish a successor cookie.').not.toBe(original);

    await sendRightAway(page, withMockMarker('Help me plan an open source conference.', 'chat_recommendations', 'medium'), 2);
    expect(refusals(), 'The send-time privacy check must accept the rotated session.').toEqual([]);

    // One full session-watcher interval: the rotated socket must not be closed.
    await page.waitForTimeout(12000);
    expect(refusals(), 'The open socket must survive refresh-token rotation.').toEqual([]);

    // A further reload followed by an immediate send uses the successor cookie.
    await page.reload({ waitUntil: 'commit' });
    await expect(page.getByTestId('message-assistant')).toHaveCount(2, { timeout: 30000 });
    await sendRightAway(page, withMockMarker('What is the capital of Germany?', 'chat_flow_capital', 'fast'), 3);
    expect(refusals()).toEqual([]);
  } finally {
    await testInfo.attach('console-sync-logs', { body: logs.slice(-200).join('\n'), contentType: 'text/plain' });
    await testInfo.attach('final-state', { body: await page.screenshot().catch(() => Buffer.from('')), contentType: 'image/png' });
  }
});
