/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
// proof-video: not_required reason=visual_smoke_not_needed (the audio proof video of each call and attached screenshots cover each checkpoint)
/**
 * Guest voice calls: a signed-out visitor starts a call, accepts the privacy notice,
 * speaks, sees the question and the reply in the guest chat and hears the answer.
 * Isolated CI runs the self-hosted edition (guest routes are refused), so the server
 * status, the guest call socket, the anonymous chat stream and the speech endpoint are
 * mocked the way anonymous-free-chat.spec.ts mocks them. The page code is the real one.
 */
import fs from 'node:fs';
import path from 'node:path';
import type { Page, TestInfo } from '@playwright/test';

const { expect, test: auditedTest } = require('./helpers/cookie-audit');
const { withProofAudio, proofAudioLaunchArgs } = require('./helpers/proof-audio');
const { getE2EDebugUrl } = require('./signup-flow-helpers');

const test = withProofAudio(auditedTest);
test.use({ launchOptions: { args: proofAudioLaunchArgs() } });

const QUESTION = 'What is the capital of France?';
const ANSWER = 'Paris is the capital of France.';
const SPEECH_AUDIO = fs.readFileSync(path.resolve(__dirname, '../static/store-examples/community-garden-volunteer-chime.mp3'));

const usage = () => ({
  active: true, can_send_text: true, reason: null,
  reset_at: new Date(Date.now() + 60 * 60 * 1000).toISOString(),
  cta: 'Create an account to keep using OpenMates.'
});

async function mockGuestBackend(page: any, mode: 'answer' | 'limit') {
  const seen = { socketUrls: [] as string[], speechRequests: [] as any[], speechCookies: [] as (string | undefined)[], streamRequests: [] as any[], frames: [] as any[] };
  await page.route('**/v1/settings/server-status', (route: any) => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({
      is_self_hosted: false, payment_enabled: true, server_edition: 'development', domain: 'app.dev.openmates.org',
      ai_models_configured: true, anonymous_free_usage: usage()
    })
  }));
  await page.route('**/v1/anonymous/free-usage/status**', (route: any) => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify(usage())
  }));
  await page.route('**/v1/anonymous/speech', async (route: any) => {
    seen.speechRequests.push(route.request().postDataJSON());
    seen.speechCookies.push(await route.request().headerValue('cookie') ?? undefined);
    await route.fulfill({ status: 200, contentType: 'audio/mpeg', body: SPEECH_AUDIO });
  });
  await page.exposeFunction('recordGuestStreamRequest', (body: any) => { seen.streamRequests.push(body); return seen.streamRequests.length; });
  await page.addInitScript(() => {
    const originalFetch = window.fetch.bind(window);
    window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
      if (url.includes('/v1/anonymous/chat/stream')) {
        const body = JSON.parse(String(init?.body ?? '{}'));
        const n = await (window as any).recordGuestStreamRequest(body);
        return new Response(JSON.stringify({
          status: 'completed', messageId: `guest-call-assistant-${n}`, assistant: 'Paris is the capital of France.',
          category: 'general_knowledge', modelName: 'test-model'
        }), { status: 200, headers: { 'content-type': 'application/json' } });
      }
      return originalFetch(input, init);
    };
    // Record what the page really plays: the assistant's speech goes through an Audio element.
    (window as any).__playedAudio = [];
    const play = HTMLMediaElement.prototype.play;
    HTMLMediaElement.prototype.play = function (this: HTMLMediaElement) {
      const result = play.call(this);
      Promise.resolve(result).then(() => (window as any).__playedAudio.push({ src: this.currentSrc || this.src }), () => {});
      return result;
    };
  });
  await page.routeWebSocket('**/v1/voice-call/guest**', (ws: any) => {
    seen.socketUrls.push(ws.url());
    let replied = false;
    ws.onMessage((raw: string) => {
      let frame: any;
      try { frame = JSON.parse(String(raw)); } catch { return; }
      if (frame.type !== 'mic_audio') seen.frames.push(frame.type);
      if (frame.type === 'start') ws.send(JSON.stringify({ type: 'ready' }));
      if (frame.type === 'mic_audio' && !replied) {
        replied = true;
        if (mode === 'limit') {
          ws.send(JSON.stringify({ type: 'error', code: 'anonymous_usage_limit', signup_required: true }));
          return;
        }
        ws.send(JSON.stringify({ type: 'transcript', turn_id: 't1', text: 'What is the capital', final: false }));
        setTimeout(() => ws.send(JSON.stringify({ type: 'transcript', turn_id: 't1', text: QUESTION, final: true })), 400);
      }
    });
  });
  return seen;
}

async function startGuestCall(page: any) {
  await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
  const start = page.locator('[data-testid="voice-call-start"]:visible');
  await expect(start).toBeVisible({ timeout: 30_000 });
  await start.click();
  // No acknowledgement yet: the privacy notice comes first, and no socket opens before Continue.
  const notice = page.getByTestId('notification').filter({ hasText: 'Continue' });
  await expect(notice).toBeVisible({ timeout: 10_000 });
  await notice.getByTestId('notification-action').click();
}

async function expectNoCredentials(page: any, seen: any) {
  expect(seen.socketUrls.length, 'the guest call socket opened').toBeGreaterThan(0);
  for (const url of seen.socketUrls) expect(new URL(url).searchParams.get('anonymous_id'), 'socket carries the anonymous id').toBeTruthy();
  const cookies = await page.context().cookies();
  expect(cookies.filter((cookie: any) => /auth|refresh|session/i.test(cookie.name)), 'no auth cookie exists for a guest').toEqual([]);
  for (const header of seen.speechCookies) expect(header ?? '', 'no auth cookie on the speech request').not.toMatch(/auth|refresh/i);
}

test.describe('guest voice call', () => {
  const viewports = [
    { name: 'desktop', size: { width: 1280, height: 720 } },
    { name: 'phone', size: { width: 390, height: 844 } }
  ];
  for (const viewport of viewports) {
    // contract-test: direct surface=gui.web assertions=video-call.guest-calls
    test(`signed-out visitor asks by voice and hears the answer (${viewport.name})`, async ({ page }: any, testInfo: any) => {
      test.setTimeout(120_000);
      await page.setViewportSize(viewport.size);
      const seen = await mockGuestBackend(page, 'answer');
      await startGuestCall(page);
      await expect(page.getByTestId('voice-call-bar')).toBeVisible({ timeout: 20_000 });
      await expect(page.getByTestId('voice-call-status-text')).toHaveText('Listening · You can speak now', { timeout: 20_000 });
      await testInfo.attach(`${viewport.name}-listening`, { body: await page.screenshot(), contentType: 'image/png' });
      await expect(page.getByTestId('message-user').filter({ hasText: QUESTION })).toBeVisible({ timeout: 20_000 });
      await expect(page.getByTestId('message-assistant').filter({ hasText: ANSWER })).toBeVisible({ timeout: 20_000 });
      await expect.poll(() => seen.speechRequests.length, { timeout: 20_000 }).toBeGreaterThan(0);
      expect(seen.speechRequests[0].text).toContain('Paris is the capital of France');
      expect(seen.speechRequests[0].anonymous_id).toBeTruthy();
      expect(seen.streamRequests.length, 'the spoken question went through the anonymous chat stream').toBe(1);
      await expect.poll(() => page.evaluate(() => (window as any).__playedAudio.length), { timeout: 20_000 }).toBeGreaterThan(0);
      await testInfo.attach(`${viewport.name}-answered`, { body: await page.screenshot(), contentType: 'image/png' });
      await expectNoCredentials(page, seen);
      await page.getByTestId('voice-call-hangup').click();
      await expect(page.getByTestId('voice-call-bar')).toHaveCount(0);
      expect(seen.frames).toContain('hangup');
    });
  }

  for (const knownDevice of [false, true]) {
    // contract-test: direct surface=gui.web assertions=message-input.signed-out-action-access,video-call.guest-calls
    test(`blocked call opens ${knownDevice ? 'login' : 'signup'} before starting on a ${knownDevice ? 'known' : 'new'} device`, async ({ page }: { page: Page }, testInfo: TestInfo) => {
      const seen = await mockGuestBackend(page, 'answer');
      let exhausted = knownDevice;
      await page.route('**/v1/anonymous/free-usage/status**', route => route.fulfill({
        json: exhausted
          ? { ...usage(), active: false, can_send_text: false, reason: 'per_identity_exhausted' }
          : usage(),
      }));
      await page.addInitScript((known: boolean) => {
        if (known) localStorage.setItem('openmates:last-auth-method', 'email');
        const starts: string[] = [];
        Object.assign(window, { callStarts: starts });
        navigator.mediaDevices.getUserMedia = async () => {
          starts.push('microphone');
          throw new Error('A blocked call requested the microphone');
        };
        new MutationObserver(() => {
          if (document.querySelector('[data-testid="voice-call-bar"]')) starts.push('call bar');
        }).observe(document, { subtree: true, childList: true });
      }, knownDevice);
      await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
      const field = page.getByTestId('message-field');
      await expect(field).toHaveAttribute('data-editor-ready', 'true', { timeout: 30_000 });
      const editor = field.getByTestId('message-editor').locator('[contenteditable="true"]');
      await editor.fill('A local draft');
      if (knownDevice) {
        await expect(page.getByTestId('guest-access-reason')).toHaveText("You've logged in on this device before. Log in to keep chatting.");
        await expect(page.getByTestId('composer-account-cta')).toHaveText(/^log\s?in$/i);
      } else {
        await expect(field.getByTestId('composer-send-button')).toBeEnabled();
        // A different visitor can use up the shared allowance while this tab is open.
        exhausted = true;
      }
      // The welcome header hides while the composer is focused.
      await editor.blur();
      await page.locator('[data-testid="voice-call-start"]:visible').click();
      await expect(page.getByTestId(knownDevice ? 'login-modal' : 'signup-modal')).toBeVisible();
      await expect(page.getByTestId('notification').filter({ hasText: 'Continue' })).toHaveCount(0);
      expect(await page.evaluate(() => (window as typeof window & { callStarts: string[] }).callStarts)).toEqual([]);
      expect(seen.socketUrls).toEqual([]);
      await testInfo.attach('account-flow-without-call', { body: await page.screenshot(), contentType: 'image/png' });
    });
  }

  // contract-test: direct surface=gui.web assertions=video-call.guest-calls
  test('an allowance exhausted during a call ends it and offers sign-up', async ({ page }: any, testInfo: any) => {
    test.setTimeout(120_000);
    await page.setViewportSize({ width: 1280, height: 720 });
    const seen = await mockGuestBackend(page, 'limit');
    await startGuestCall(page);
    await expect(page.getByTestId('voice-call-bar')).toBeVisible({ timeout: 20_000 });
    const signup = page.getByTestId('notification').filter({ hasText: 'free usage limit' });
    await expect(signup).toBeVisible({ timeout: 20_000 });
    await expect(signup.getByTestId('notification-action')).toHaveText('Sign up');
    await expect(page.getByTestId('voice-call-bar')).toHaveCount(0, { timeout: 10_000 });
    await testInfo.attach('limit-signup-notice', { body: await page.screenshot(), contentType: 'image/png' });
    await expectNoCredentials(page, seen);
    expect(seen.speechRequests.length, 'no speech is requested after the limit').toBe(0);
  });
});
