/** Manual real-provider guest dictation proof; never run in isolated CI. */
import fs from 'node:fs';
import path from 'node:path';
import { expect, test } from './helpers/cookie-audit';

const fixture = fs.existsSync('/workspace/backend/tests/fixtures/realtime_transcription_speech.wav')
  ? '/workspace/backend/tests/fixtures/realtime_transcription_speech.wav'
  : path.resolve(__dirname, '../../../../backend/tests/fixtures/realtime_transcription_speech.wav');

test.use({
  launchOptions: { args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream',
    `--use-file-for-fake-audio-capture=${fixture}`] },
  permissions: ['microphone'],
});

// contract-test: direct surface=gui.web assertions=message-input.audio.guest-admission,message-input.audio.editable-transcript
test('real guest microphone audio becomes editable text and consumes the existing allowance without uploading audio', async ({ page, context }) => {
  test.setTimeout(120_000);
  await context.clearCookies();
  const events: string[] = [];
  const sockets: string[] = [];
  const uploads: string[] = [];
  let statusEndpoint = '';
  page.on('websocket', socket => {
    if (!socket.url().includes('/v1/apps/audio/realtime-transcription')) return;
    sockets.push(socket.url());
    socket.on('framereceived', ({ payload }) => {
      try { events.push(JSON.parse(String(payload)).type); } catch { /* Non-JSON frames are irrelevant. */ }
    });
  });
  page.on('request', request => {
    if (request.url().includes('/v1/anonymous/free-usage/status')) statusEndpoint = request.url();
    if (request.method() === 'POST' && /\/v1\/(?:upload\/file|apps\/audio\/skills\/transcribe)/.test(request.url())) uploads.push(request.url());
  });
  await page.goto('/');
  const field = page.getByTestId('message-field').filter({ visible: true });
  await expect(field).toHaveCount(1);
  const editor = field.getByTestId('message-editor').locator('[contenteditable="true"]');
  await editor.fill('Please verify: ');
  await editor.press('ControlOrMeta+End');
  await expect.poll(() => statusEndpoint).toContain('/v1/anonymous/free-usage/status');
  const before = await page.evaluate(async url => {
    const response = await fetch(url, { cache: 'no-store', credentials: 'omit' });
    if (!response.ok) throw new Error(`Guest status failed: ${response.status}`);
    return response.json();
  }, statusEndpoint);
  expect(before.can_send_text).toBe(true);
  const identityBefore = await page.evaluate(() => localStorage.getItem('openmates_anonymous_id'));
  expect(identityBefore).toBeTruthy();
  await field.getByTestId('record-audio-button').dispatchEvent('mousedown', { button: 0 });
  const overlay = page.getByTestId('record-overlay');
  await expect(overlay).toBeVisible();
  await expect(overlay.getByTestId('recording-live-transcript')).toContainText(/transcription.*working/i, { timeout: 60_000 });
  await overlay.getByTestId('record-finish-button').click();
  await expect(overlay).toHaveCount(0, { timeout: 45_000 });
  await expect(editor).toContainText('Please verify:');
  await expect(editor).toContainText(/transcription.*working.*correctly/i);
  await expect(editor).toBeFocused();
  await page.keyboard.type(' Ready to review.');
  await expect(editor).toContainText('Ready to review.');
  expect(sockets).toHaveLength(1);
  const socketUrl = new URL(sockets[0]);
  expect(socketUrl.searchParams.get('anonymous_id')).toBe(identityBefore);
  expect(socketUrl.searchParams.has('token')).toBe(false);
  expect(events).toContain('transcription.done');
  expect(events).toContain('correction.done');
  expect(events).not.toContain('session.error');
  expect(uploads).toEqual([]);
  expect(await page.evaluate(() => localStorage.getItem('openmates_anonymous_id'))).toBe(identityBefore);
  const after = await page.evaluate(async url => (await fetch(url, { cache: 'no-store', credentials: 'omit' })).json(), statusEndpoint);
  expect(after.daily_remaining_percent).toBeGreaterThanOrEqual(0);
  expect(after.daily_remaining_percent).toBeLessThanOrEqual(before.daily_remaining_percent);
  await test.info().attach('guest-allowance', { body: JSON.stringify({ before: before.daily_remaining_percent,
    after: after.daily_remaining_percent }), contentType: 'application/json' });
  await expect(page.getByTestId('user-message-content')).toHaveCount(0);
  await test.info().attach('real-guest-editable-transcript', { body: await field.screenshot(), contentType: 'image/png' });
});
