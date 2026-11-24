/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
// proof-video: not_required reason=visual_smoke_not_needed (dev-host check; the audio proof video of the call is attached)
/**
 * Real guest voice call on a deployed host, no mocks (not part of isolated CI).
 * Runs only when VOICE_GUEST_REAL_BASE_URL names the host. A fresh browser context
 * without cookies presses Start, accepts the privacy notice, the fake microphone plays
 * the same generated question as the signed-in check. The test verifies the heard text, an
 * assistant reply, a 200 from /v1/anonymous/speech and audio playback, then hangs up.
 * VOICE_CHECK_RECEIPT (a file path) receives a JSON receipt on success and failure.
 */
import fs from 'node:fs';
import path from 'node:path';
import type { Page, TestInfo } from '@playwright/test';

const { expect, test: playwrightTest } = require('@playwright/test');
const { withProofAudio, proofAudioLaunchArgs } = require('./helpers/proof-audio');

const BASE_URL = process.env.VOICE_GUEST_REAL_BASE_URL || '';
const RECEIPT = process.env.VOICE_CHECK_RECEIPT || '';
const SPEECH_DIR = process.env.VOICE_CALL_REAL_SPEECH_DIR;
const SCENARIO = process.env.VOICE_CALL_REAL_SCENARIO || 'capital';
const voiceWav = SPEECH_DIR ? path.join(SPEECH_DIR, `${SCENARIO}.wav`) : null;
const test = withProofAudio(playwrightTest);
test.use({
  baseURL: BASE_URL || undefined,
  viewport: { width: 1280, height: 720 },
  permissions: ['microphone'],
  launchOptions: { args: proofAudioLaunchArgs({ voiceWav }) },
});

interface Receipt { status: 'passed' | 'failed'; heard_text: string; reply_text: string; speech_status: number | null; error: string }

function writeReceipt(receipt: Receipt): void {
  if (!RECEIPT) return;
  fs.mkdirSync(path.dirname(path.resolve(RECEIPT)), { recursive: true });
  fs.writeFileSync(RECEIPT, JSON.stringify({ ...receipt, base_url: BASE_URL, finished_at: new Date().toISOString() }, null, 2));
}

test.describe('guest voice call on a real host', () => {
  test.skip(!BASE_URL, 'set VOICE_GUEST_REAL_BASE_URL to run the real guest voice call check');

  // contract-test: direct surface=gui.web assertions=video-call.guest-calls
  test('a signed-out visitor speaks and hears the answer', async ({ page }: { page: Page }, testInfo: TestInfo) => {
    const testStartedAt = Date.now();
    test.setTimeout(180_000);
    const receipt: Receipt = { status: 'failed', heard_text: '', reply_text: '', speech_status: null, error: '' };
    try {
      expect(voiceWav && fs.existsSync(voiceWav), 'generated microphone question').toBe(true);
      expect(await page.context().cookies(), 'fresh context has no cookies').toEqual([]);
      await page.addInitScript(() => {
        const proof = Object.assign(window, { __guestVoiceAudioFinished: 0 });
        const play = HTMLMediaElement.prototype.play;
        HTMLMediaElement.prototype.play = function (this: HTMLMediaElement) {
          const result = play.call(this);
          if (this instanceof HTMLAudioElement && this.src.startsWith('blob:')) {
            this.addEventListener('ended', () => { proof.__guestVoiceAudioFinished += 1; }, { once: true });
          }
          return result;
        };
      });
      page.on('response', response => {
        if (new URL(response.url()).pathname === '/v1/anonymous/speech') receipt.speech_status = response.status();
      });
      await page.goto('/', { waitUntil: 'domcontentloaded' });
      const start = page.locator('[data-testid="voice-call-start"]:visible');
      await expect(start).toBeVisible({ timeout: 30_000 });
      // Bound the recurring smoke call even if speech stalls.
      testInfo.setTimeout(Date.now() - testStartedAt + 45_000);
      await start.click();
      const notice = page.getByTestId('notification').filter({ hasText: 'Continue' });
      await expect(notice).toBeVisible({ timeout: 10_000 });
      await notice.getByTestId('notification-action').click();
      await expect(page.getByTestId('voice-call-bar')).toBeVisible({ timeout: 30_000 });
      const user = page.getByTestId('message-user').first();
      await expect(user).toBeVisible({ timeout: 90_000 });
      receipt.heard_text = ((await user.innerText()) || '').trim();
      expect(receipt.heard_text, 'the spoken question was transcribed').toMatch(/capital of France/i);
      const assistant = page.getByTestId('message-assistant').first();
      await expect(assistant).toContainText(/Paris/i, { timeout: 120_000 });
      receipt.reply_text = ((await assistant.innerText()) || '').trim();
      await expect.poll(() => receipt.speech_status, { timeout: 30_000 }).toBe(200);
      await expect.poll(() => page.evaluate(() =>
        (window as unknown as { __guestVoiceAudioFinished: number }).__guestVoiceAudioFinished), { timeout: 30_000 }).toBeGreaterThan(0);
      await testInfo.attach('guest-call-answered', { body: await page.screenshot(), contentType: 'image/png' });
      await page.getByTestId('voice-call-hangup').click();
      await expect(page.getByTestId('voice-call-bar')).toHaveCount(0, { timeout: 10_000 });
      receipt.status = 'passed';
    } catch (error) {
      receipt.error = error instanceof Error ? error.message.slice(0, 1000) : String(error);
      throw error;
    } finally {
      writeReceipt(receipt);
    }
  });
});
