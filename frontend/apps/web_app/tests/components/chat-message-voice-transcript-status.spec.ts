// playwright-account: not_required reason=isolated_component_preview
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// contract-test: direct surface=gui.web assertions=video-call.chat.transcripts,video-call.chat.typed-input
test('spoken call transcripts have no send or processing footer while typed input keeps Sending', async ({ page }, testInfo) => {
  test.setTimeout(60_000);
  await page.setViewportSize({ width: 390, height: 844 });
  for (const [variant, body, sending] of [
    ['voiceUserSending', 'Spoken words', false],
    ['voiceAssistantStreaming', 'Spoken response', false],
    ['voiceAssistantSending', 'Saved response', false],
    ['typedCallSending', 'Typed while calling', true],
    ['typedAcceptedSending', 'Accepted typed call input', false],
    ['sending', 'This message is being sent…', true],
  ] as const) {
    const params = new URLSearchParams({ chrome: '0', theme: 'light', background: '#dbeafe', width: '390', variant });
    await page.goto(`/dev/preview/ChatMessage?${params}`);
    const canvas = await waitForComponentPreview(page);
    const message = canvas.locator('.chat-message');
    await expect(message).toContainText(body);
    const footer = message.locator('.message-status');
    if (sending) await expect(footer).toHaveText('Sending...');
    else await expect(footer).toHaveCount(0);
    await expect(message.getByTestId('assistant-response-status')).toHaveCount(0);
    if (variant === 'voiceUserSending' || variant === 'typedCallSending') {
      await page.screenshot({ path: testInfo.outputPath(`${variant}-390.png`) });
    }
  }
});
