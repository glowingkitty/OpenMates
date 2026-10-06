/**
 * Authenticated route proof using the existing OpenMates test account.
 * Only the call WebSocket is replaced; ordinary login remains real.
 * Tiny synthetic MP4s verify ephemeral clip playback and URL revocation.
 * No paid Gemini or video generation request is made by this spec.
 */
import type { Page } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { expect, test } from './helpers/cookie-audit';
const requireFromHere = createRequire(import.meta.url);
const { loginToTestAccount } = requireFromHere('./helpers/chat-test-helpers');
const { getTestAccount } = requireFromHere('./signup-flow-helpers');
const firstClip = readFileSync(new URL('./fixtures/video-call-clip-a.mp4', import.meta.url)).toString('base64');
const secondClip = readFileSync(new URL('./fixtures/video-call-clip-b.mp4', import.meta.url)).toString('base64');

test.use({
  launchOptions: { args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'] },
  permissions: ['microphone'],
});

async function mockCallTransport(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const NativeWebSocket = window.WebSocket;
    const originalRevoke = URL.revokeObjectURL.bind(URL);
    const revokedUrls: string[] = [];
    URL.revokeObjectURL = (url) => { revokedUrls.push(url); originalRevoke(url); };
    const transport = { sent: [] as Record<string, unknown>[], socket: null as EventTarget | null, emit(message: Record<string, unknown>) {
      this.socket?.dispatchEvent(new MessageEvent('message', { data: JSON.stringify(message) }));
    }, revokedUrls };
    Object.assign(window, { __callTransport: transport });
    class CallSocket extends EventTarget {
      readyState: number = WebSocket.CONNECTING;
      onmessage: ((event: MessageEvent<string>) => void) | null = null;
      onerror: (() => void) | null = null;
      onclose: (() => void) | null = null;
      constructor() {
        super();
        transport.socket = this;
        this.addEventListener('message', (event) => this.onmessage?.(event as MessageEvent<string>));
        queueMicrotask(() => {
          this.readyState = WebSocket.OPEN;
          transport.emit({ type: 'ready', max_duration_seconds: 120, input_sample_rate: 16000, output_sample_rate: 24000, audio_credits_per_minute: 27.6, video_credits_per_minute: 1080 });
          transport.emit({ type: 'transcript', role: 'model', text: 'Welcome to the call.', final: true });
          transport.emit({ type: 'usage', elapsed_seconds: 4, credits_accrued: 1.84, credits_charged: 2, audio_credits: 1.84, video_credits: 0, gemini_input_tokens: 20, gemini_output_tokens: 8, gemini_context_tokens: 20, h3_generated_seconds: 0, audio_credits_per_minute: 27.6, video_credits_per_minute: 1080 });
        });
      }
      send(data: string) { transport.sent.push(JSON.parse(data) as Record<string, unknown>); }
      close() { this.readyState = WebSocket.CLOSED; this.onclose?.(); }
    }
    window.WebSocket = new Proxy(NativeWebSocket, {
      construct(Target, args) {
        if (String(args[0]).includes('/v1/experiment/videocall')) return new CallSocket() as unknown as WebSocket;
        return Reflect.construct(Target, args);
      },
    });
  });
}

test.describe('Authenticated video call experiment route', () => {
  // contract-test: direct surface=gui.web assertions=video-call.experiment.live-voice,video-call.experiment.privacy
  test('requires the existing OpenMates login', async ({ page }) => {
    await page.goto('/experiment/videocall');
    await expect(page.getByTestId('call-auth-required')).toBeVisible();
    await expect(page.getByTestId('call-start')).toHaveCount(0);
  });

  // contract-test: direct surface=gui.web assertions=video-call.experiment.live-voice,video-call.experiment.generated-visuals,video-call.experiment.user-stop,video-call.experiment.billing,video-call.experiment.responsive,video-call.experiment.no-recording,video-call.experiment.privacy
  test('runs an authenticated call with mocked media transport and independent visual stop', async ({ page }) => {
    test.setTimeout(240_000);
    test.skip(!getTestAccount().email, 'Test account credentials required.');
    await mockCallTransport(page);
    await loginToTestAccount(page, () => {}, async () => {});
    await page.goto('/experiment/videocall');
    await expect(page.getByTestId('video-call-panel')).toBeVisible();
    await page.getByTestId('call-start').click();
    await expect(page.getByTestId('call-hangup')).toBeVisible();
    await expect(page.getByTestId('call-transcript')).toContainText('Welcome to the call.');
    await expect(page.getByTestId('call-active-rate')).toContainText('28 credits/min');
    await page.evaluate(() => (window as typeof window & { __callTransport: { emit: (message: Record<string, unknown>) => void } }).__callTransport.emit({ type: 'video.queued' }));
    await expect(page.getByTestId('video-call-stage')).toContainText('Creating a visual');
    await expect(page.getByTestId('call-active-rate')).toContainText('1,108 credits/min');
    await page.evaluate((data) => (window as typeof window & { __callTransport: { emit: (message: Record<string, unknown>) => void } }).__callTransport.emit({ type: 'video.ready', clip_id: '1', duration_seconds: 1.5, data }), firstClip);
    await expect(page.getByTestId('call-video')).toBeVisible();
    await page.evaluate((data) => (window as typeof window & { __callTransport: { emit: (message: Record<string, unknown>) => void } }).__callTransport.emit({ type: 'video.ready', clip_id: '2', duration_seconds: 1.5, data }), secondClip);
    await expect.poll(() => page.getByTestId('call-video').getAttribute('src'), { timeout: 10_000 }).not.toBeNull();
    await page.getByTestId('call-stop-video').click();
    await expect(page.getByTestId('call-active-rate')).toContainText('28 credits/min');
    await expect(page.getByTestId('call-hangup')).toBeVisible();
    await expect.poll(() => page.evaluate(() => (window as typeof window & { __callTransport: { sent: Record<string, unknown>[] } }).__callTransport.sent.some((event) => event.type === 'stop_visuals'))).toBe(true);
    await expect.poll(() => page.evaluate(() => (window as typeof window & { __callTransport: { revokedUrls: string[] } }).__callTransport.revokedUrls.length)).toBeGreaterThanOrEqual(2);
    await page.getByTestId('call-hangup').click();
    await expect(page.getByText('Call ended. Your audio and visuals were released.')).toBeVisible();
    await expect(page.getByTestId('video-call-panel')).not.toContainText('Replay');
    await expect(page.getByTestId('video-call-panel')).not.toContainText('Download');
  });
});
