/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Regression (issue WRPEB): pasting a long CV with bullet and numbered lists
 * threw "RangeError: Unknown node type: listItem" in the composer, the send
 * hung for minutes and Cancel stayed stuck. The pasted text must stay in the
 * composer as plain markdown lines and send normally with a reply.
 */
export {};
const { test, expect } = require('./helpers/cookie-audit');
const { createSignupLogger, createStepScreenshotter, archiveExistingScreenshots,
  getTestAccount, withMockMarker } = require('./signup-flow-helpers');
const { loginToTestAccount, startNewChat } = require('./helpers/chat-test-helpers');
const { createVideoProofRuntime, defineVideoProof } = require('./helpers/video-proof');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

const CV = [
  'Please review my CV for a product designer role.',
  '',
  'Curriculum vitae: Example Person, Example City',
  '',
  'Experience',
  ...Array.from({ length: 24 }, (_, i) => `- Led design project ${i + 1} for an example client, shipped on time`),
  '',
  'How I work',
  ...Array.from({ length: 10 }, (_, i) => `${i + 1}. Step ${i + 1} of my research process`),
  '',
  'Thanks for reading.',
].join('\n');

const proofContract = defineVideoProof({
  id: 'chat-paste-long-list-send',
  title: 'Paste a long CV with lists into the composer and send it',
  surface: 'web',
  devices: ['web-laptop'],
  domain: 'app.dev.openmates.org',
  transcript: [
    { id: 'pasted', text: 'The pasted CV with its bullet and numbered lists stays in the message field.', checkpoint: 'cv-pasted', devices: ['web-laptop'] },
    { id: 'sent', text: 'The message sends right away and the assistant replies; the message field is empty again.', checkpoint: 'cv-sent', devices: ['web-laptop'] },
  ],
  assertions: [
    { id: 'chats.paste.lists-stay-text', checkpoint: 'cv-pasted', visual: 'The composer shows the pasted list lines with their "- " and "1. " markers.', devices: ['web-laptop'] },
    { id: 'chats.paste.lists-send', checkpoint: 'cv-sent', visual: 'The sent CV appears as a user message followed by an assistant reply, with no stuck cancel control.', devices: ['web-laptop'] },
  ],
  tutorial: { readingWordsPerSecond: 3, minimumHoldMs: 900, maximumHoldMs: 2500 },
});

// contract-test: supporting surface=gui.web assertions=chats.send.immediate-admission
test('a pasted long CV with bullet and numbered lists stays text and sends with a reply', async ({ page }: { page: any }, testInfo: any) => {
  test.setTimeout(240000);
  test.skip(!TEST_EMAIL || !TEST_PASSWORD || !TEST_OTP_KEY, 'Test account credentials are required.');
  const warnings: string[] = [];
  page.on('console', (msg: any) => {
    const text = msg.text();
    if (/Unknown node type|Invalid content|RangeError/.test(text)) warnings.push(`${msg.type()} ${text.slice(0, 400)}`);
  });
  const proof = createVideoProofRuntime(proofContract, { device: 'web-laptop', attach: testInfo.attach.bind(testInfo), captureFrame: () => page.screenshot() });
  const logCheckpoint = createSignupLogger('PASTE_LONG_LIST_SEND');
  const takeStepScreenshot = createStepScreenshotter(logCheckpoint);
  try {
    await page.setViewportSize({ width: 1440, height: 900 });
    await archiveExistingScreenshots(logCheckpoint);
    await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
    await startNewChat(page, logCheckpoint);

    const composer = page.getByTestId('message-editor').filter({ visible: true }).first();
    const editor = composer.locator('.ProseMirror');
    await editor.waitFor({ state: 'visible', timeout: 60000 });
    await editor.click();
    const text = CV;
    await page.evaluate((pasted: string) => {
      const target = document.querySelector('[data-testid="message-editor"] [contenteditable="true"]');
      if (!target) throw new Error('message-editor not found');
      const clipboardData = new DataTransfer();
      clipboardData.setData('text/plain', pasted);
      target.dispatchEvent(new ClipboardEvent('paste', { clipboardData, bubbles: true, cancelable: true }));
    }, text);

    await proof.assert('chats.paste.lists-stay-text', async () => {
      await expect(composer).toContainText('Please review my CV', { timeout: 10000 });
      await expect(composer).toContainText('- Led design project 24');
      await expect(composer).toContainText('10. Step 10 of my research process');
    });
    await testInfo.attach('cv-pasted', { body: await composer.screenshot(), contentType: 'image/png' });
    await proof.checkpoint('cv-pasted');

    // The replay marker is typed after the paste: a long paste can become a
    // document card, and the mock server reads only the typed message text.
    await editor.click();
    await page.keyboard.press('Control+End');
    await page.keyboard.insertText(withMockMarker(' What do you think?', 'chat_flow_capital', 'fast'));
    await page.getByTestId('composer-send-button').filter({ visible: true }).first().click();
    await proof.assert('chats.paste.lists-send', async () => {
      await expect(page.getByTestId('message-user')).toHaveCount(1, { timeout: 30000 });
      await expect(page.getByTestId('message-user').first()).toContainText('Please review my CV');
      await expect(page.getByTestId('message-assistant')).toHaveCount(1, { timeout: 90000 });
      await expect(page.getByTestId('message-assistant').first().getByTestId('message-content')).not.toBeEmpty();
      await expect(page.getByTestId('message-assistant').first()).not.toContainText('encountered an error');
      await expect(page.getByTestId('queued-edit-cancel')).toHaveCount(0);
      await expect(editor).toHaveText('');
    });
    await proof.checkpoint('cv-sent');
    expect(warnings, 'The composer must accept the pasted lists without schema errors.').toEqual([]);
    await proof.attach();
  } finally {
    await testInfo.attach('schema-warnings', { body: warnings.join('\n') || 'none', contentType: 'text/plain' });
    await testInfo.attach('final-state', { body: await page.screenshot().catch(() => Buffer.from('')), contentType: 'image/png' });
  }
});
