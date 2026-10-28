// playwright-account: not_required reason=isolated_component_preview
import { expect, test } from '../helpers/cookie-audit';
import type { Page } from '@playwright/test';
import { waitForComponentPreview } from '../helpers/component-preview';
import { allowFixtureMicrophone } from '../helpers/recording-permission';

const RAW = 'please schedule the project review';
const CORRECTED = 'Please schedule the project review.';
const GUEST_ID = 'guest-dictation-component';

test.use({
  launchOptions: { args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'] },
  permissions: ['microphone'], hasTouch: true,
});

async function openGuest(page: Page, width: number, denial?: 'initial' | 'streaming') {
  let exhausted = false;
  let releaseCorrection: (() => void) | undefined;
  const connections: string[] = [];
  const frames: Array<{ type: string }> = [];
  const uploads: string[] = [];
  const availability = () => ({ active: !exhausted, can_send_text: !exhausted,
    reason: exhausted ? 'per_identity_exhausted' : null, daily_remaining_percent: exhausted ? 0 : 80 });
  await allowFixtureMicrophone(page, /\/dev\/preview\/enter_message\/MessageInputNotificationPreview(?:\?|$)/);
  await page.setViewportSize({ width: width < 400 ? 390 : 1280, height: 900 });
  await page.addInitScript(id => localStorage.setItem('openmates_anonymous_id', id), GUEST_ID);
  await page.route('**/v1/settings/server-status', route => route.fulfill({ json: {
    is_self_hosted: false, server_edition: 'development', ai_models_configured: true,
    anonymous_free_usage: availability(),
  } }));
  await page.route('**/v1/anonymous/free-usage/status**', route => route.fulfill({ json: availability() }));
  page.on('request', request => {
    if (request.method() === 'POST' && /\/v1\/(?:upload\/file|apps\/audio\/skills\/transcribe)/.test(request.url())) uploads.push(request.url());
  });
  await page.routeWebSocket(/\/v1\/apps\/audio\/realtime-transcription(?:\?|$)/, socket => {
    connections.push(socket.url());
    const deny = () => {
      exhausted = true;
      socket.send(JSON.stringify({ type: 'session.error', code: 'per_identity_exhausted', signup_required: true,
        message: 'Free usage limit reached' }));
    };
    if (denial === 'initial') { deny(); return; }
    socket.send(JSON.stringify({ type: 'session.ready', sample_rate: 16000 }));
    let transcriptSent = false;
    socket.onMessage(raw => {
      const frame = JSON.parse(String(raw));
      frames.push(frame);
      if (frame.type === 'input_audio.append' && !transcriptSent) {
        transcriptSent = true;
        if (denial === 'streaming') { deny(); return; }
        socket.send(JSON.stringify({ type: 'transcription.text.delta', text: RAW }));
      }
      if (frame.type === 'input_audio.end') {
        socket.send(JSON.stringify({ type: 'transcription.done', transcript: RAW, model: 'fixture-transcription' }));
        socket.send(JSON.stringify({ type: 'correction.started', model: 'fixture-correction' }));
        releaseCorrection = () => socket.send(JSON.stringify({ type: 'correction.done', transcript: CORRECTED }));
      }
    });
  });
  await page.goto(`/dev/preview/enter_message/MessageInputNotificationPreview?chrome=0&theme=light&background=%23dbeafe&width=${width}`);
  await waitForComponentPreview(page);
  const field = page.getByTestId('message-field');
  await expect(field).toHaveAttribute('data-editor-ready', 'true');
  const editor = field.getByTestId('message-editor').locator('.ProseMirror');
  await editor.fill('Existing notes. ');
  await editor.press('ControlOrMeta+End');
  await expect(field.getByTestId('record-audio-button')).toBeVisible();
  return { field, editor, connections, frames, uploads, release: async () => {
    await expect.poll(() => !!releaseCorrection).toBe(true);
    releaseCorrection!();
  } };
}

for (const entry of ['mouse', 'touch', 'keyboard'] as const) {
  // contract-test: direct surface=gui.web assertions=message-input.audio.guest-admission,message-input.audio.editable-transcript
  test(`guest ${entry} dictation becomes editable unsent text without an audio upload`, async ({ page }) => {
    const state = await openGuest(page, entry === 'touch' ? 390 : 680);
    const microphone = state.field.getByTestId('record-audio-button');
    if (entry === 'keyboard') {
      await page.evaluate(() => window.dispatchEvent(new CustomEvent('recordingShortcut', { detail: { action: 'start' } })));
    } else if (entry === 'touch') await microphone.tap();
    else await microphone.dispatchEvent('mousedown', { button: 0 });
    const overlay = page.getByTestId('record-overlay');
    await expect(overlay).toBeVisible();
    await expect.poll(() => state.frames.some(frame => frame.type === 'input_audio.append')).toBe(true);
    await expect(overlay.getByTestId('record-finish-button')).toBeVisible();
    await overlay.getByTestId('record-finish-button').click();
    await state.release();
    await expect(overlay).toHaveCount(0);
    await expect(state.editor).toContainText('Existing notes.');
    await expect(state.editor).toContainText(CORRECTED);
    await expect(state.editor).toBeFocused();
    await page.keyboard.type(' Edited before sending.');
    await expect(state.editor).toContainText('Edited before sending.');
    expect(state.connections).toHaveLength(1);
    const url = new URL(state.connections[0]);
    expect(url.searchParams.get('anonymous_id')).toBe(GUEST_ID);
    expect(url.searchParams.has('token')).toBe(false);
    expect(state.frames.some(frame => frame.type === 'session.metadata')).toBe(false);
    expect(state.uploads).toEqual([]);
    await expect(page.getByTestId('recording-preview')).toHaveCount(0);
    await expect(page.getByTestId('user-message-content')).toHaveCount(0);
    await test.info().attach('guest-editable-transcript', { body: await state.field.screenshot(), contentType: 'image/png' });
  });
}

for (const denial of ['initial', 'streaming'] as const) {
  // contract-test: direct surface=gui.web assertions=message-input.audio.guest-admission
  test(`guest ${denial} allowance denial closes recording, preserves notes and offers signup`, async ({ page }) => {
    const state = await openGuest(page, 680, denial);
    await state.field.getByTestId('record-audio-button').dispatchEvent('mousedown', { button: 0 });
    const notice = page.getByTestId('notification').filter({ hasText: "You've reached the free usage limit." });
    await expect(notice).toBeVisible();
    await expect(notice.getByTestId('notification-action')).toHaveText('Sign up');
    await expect(page.getByTestId('record-overlay')).toHaveCount(0);
    await expect(state.editor).toHaveText('Existing notes.');
    await expect(page.locator('[data-action="sign-up-to-send"]')).toBeVisible();
    expect(state.connections).toHaveLength(1);
    expect(state.uploads).toEqual([]);
  });
}
