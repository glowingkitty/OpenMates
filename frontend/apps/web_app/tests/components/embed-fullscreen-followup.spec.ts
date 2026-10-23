import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentMotion, waitForComponentPreview } from '../helpers/component-preview';
// playwright-account: not_required reason=isolated_component_preview

for (const width of [390, 1280]) {
  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction,apps.results.shared-fullscreen
  test(`fullscreen Send hands text and an image reference to its source chat at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    let interpretations = 0;
    await page.route('**/v1/apps/workspace/interpret', route => {
      interpretations++;
      return route.fulfill({ status: 500, json: { detail: 'Chat followups must bypass interpretation' } });
    });
    await page.goto(`/dev/preview/embeds/ResultEmbedFollowupFixture?chrome=0&theme=light&width=${width}`);
    await waitForComponentPreview(page);
    await waitForComponentMotion(page.getByTestId('embed-fullscreen-overlay'));
    const input = page.getByTestId('apps-request-textarea');
    await input.fill('Make the sky brighter');
    const send = page.getByTestId('apps-request-submit');
    await expect(send).toHaveText('Send');
    await send.focus();
    await expect(send).toBeFocused();
    await send.click();
    await expect(page.getByTestId('followup-destination')).toHaveText('e2e-fullscreen-followup-source');
    const document = page.getByTestId('followup-document');
    await expect(document).toContainText('Make the sky brighter');
    await expect(document).toContainText('"embed_id": "11111111-1111-4111-8111-11111111f011"');
    await expect(document).toContainText('"reference_only": true');
    await expect(document).not.toContainText('Result context');
    expect(interpretations).toBe(0);
  });
}

test.use({
  launchOptions: { args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'] },
  permissions: ['microphone'],
});

async function prepareVoiceFollowup(page: import('@playwright/test').Page) {
  // The bare preview denies device access by default. Allow only this fixture's
  // fake microphone while preserving the rest of its permissions policy.
  await page.route(/\/dev\/preview\/embeds\/ResultEmbedFollowupFixture(?:\?|$)/, async route => {
    const response = await route.fetch();
    const headers = response.headers();
    await route.fulfill({ response, headers: { ...headers,
      'permissions-policy': headers['permissions-policy'].replace('microphone=()', 'microphone=(self)'),
    } });
  });
  await page.addInitScript(() => sessionStorage.setItem('ws_token', 'component-recording-token'));
  let releaseCorrection = () => { throw new Error('Recording has not finished'); };
  let correctionPending = false;
  await page.routeWebSocket(/\/v1\/apps\/audio\/realtime-transcription(?:\?|$)/, socket => {
    socket.send(JSON.stringify({ type: 'session.ready', sample_rate: 16000 }));
    let sentTranscript = false;
    socket.onMessage(message => {
      const event = JSON.parse(String(message));
      if (event.type === 'input_audio.append' && !sentTranscript) {
        sentTranscript = true;
        socket.send(JSON.stringify({ type: 'transcription.text.delta', text: 'make the sky brighter' }));
      }
      if (event.type !== 'input_audio.end') return;
      correctionPending = true;
      socket.send(JSON.stringify({ type: 'transcription.done', transcript: 'make the sky brighter', model: 'test-realtime' }));
      socket.send(JSON.stringify({ type: 'correction.started', model: 'test-correction' }));
      releaseCorrection = () => socket.send(JSON.stringify({ type: 'correction.done', transcript: 'Make the sky brighter.' }));
    });
  });
  return { pending: () => correctionPending, release: () => releaseCorrection() };
}

for (const [width, theme] of [[390, 'light'], [1280, 'dark']] as const) {
  // contract-test: supporting surface=gui.web assertions=message-input.actions.visibility,message-input.audio.editable-transcript,apps.results.shared-fullscreen
  test(`fullscreen recording Send submits corrected speech once at ${width}px in ${theme}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const correction = await prepareVoiceFollowup(page);
    await page.goto(`/dev/preview/embeds/ResultEmbedFollowupFixture?chrome=0&theme=${theme}&width=${width}`);
    await waitForComponentPreview(page);
    const fullscreen = page.getByTestId('embed-fullscreen-overlay');
    await waitForComponentMotion(fullscreen);
    await fullscreen.getByTestId('apps-request-textarea').fill('Keep the mountain.');
    await fullscreen.getByTestId('apps-request-mic').click();
    const overlay = fullscreen.getByTestId('record-overlay');
    await expect(overlay).toContainText('make the sky brighter');
    const send = overlay.getByTestId('record-send-button');
    await expect(send).toBeVisible();
    await expect(send).toBeEnabled();
    await expect(send).toHaveAccessibleName('Send');
    await expect(send.locator('svg')).toBeVisible();
    await expect(send).toHaveCSS('width', '40px');
    await expect(send).toHaveCSS('height', '40px');
    await expect(send).toHaveCSS('border-radius', '50%');
    const bounds = (await overlay.boundingBox())!;
    for (const id of ['record-cancel-button', 'record-finish-button', 'record-send-button']) {
      const control = overlay.getByTestId(id);
      await expect(control).toBeVisible();
      const box = (await control.boundingBox())!;
      expect(box.x).toBeGreaterThanOrEqual(bounds.x);
      expect(box.x + box.width).toBeLessThanOrEqual(bounds.x + bounds.width);
    }
    await send.hover();
    await send.focus();
    await expect(send).toBeFocused();
    await send.press('Enter');
    await expect.poll(correction.pending).toBe(true);
    await expect(fullscreen).toBeVisible();
    await expect(fullscreen.getByTestId('apps-request-textarea')).toBeDisabled();
    await expect(page.getByTestId('followup-destination')).toHaveCount(0);
    correction.release();
    await expect(page.getByTestId('followup-destination')).toHaveText('e2e-fullscreen-followup-source');
    const document = page.getByTestId('followup-document');
    await expect(document).toContainText('Keep the mountain.');
    await expect(document).toContainText('Make the sky brighter.');
    await expect(document).toContainText('"reference_only": true');
    await expect(document).toContainText('11111111-1111-4111-8111-11111111f011');
  });
}

for (const action of ['finish', 'cancel'] as const) {
  // contract-test: supporting surface=gui.web assertions=message-input.recording.lifecycle,message-input.audio.editable-transcript,apps.results.shared-fullscreen
  test(`fullscreen recording ${action} preserves the draft without sending`, async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 900 });
    const correction = await prepareVoiceFollowup(page);
    await page.goto('/dev/preview/embeds/ResultEmbedFollowupFixture?chrome=0&theme=light&width=390');
    await waitForComponentPreview(page);
    const fullscreen = page.getByTestId('embed-fullscreen-overlay');
    await waitForComponentMotion(fullscreen);
    const input = fullscreen.getByTestId('apps-request-textarea');
    await input.fill('Keep the mountain.');
    await fullscreen.getByTestId('apps-request-mic').click();
    const overlay = fullscreen.getByTestId('record-overlay');
    await expect(overlay).toContainText('make the sky brighter');
    await expect(overlay.getByTestId('record-send-button')).toBeVisible();
    await overlay.getByTestId(`record-${action}-button`).click();
    if (action === 'finish') {
      await expect.poll(correction.pending).toBe(true);
      correction.release();
    }
    await expect(overlay).toHaveCount(0);
    await expect(input).toBeEnabled();
    await expect(input).toHaveValue(action === 'finish' ? 'Keep the mountain.\nMake the sky brighter.' : 'Keep the mountain.');
    await expect(fullscreen).toBeVisible();
    await expect(page.getByTestId('followup-destination')).toHaveCount(0);
  });
}
