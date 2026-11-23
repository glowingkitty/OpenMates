// proof-video: not_required reason=non_visual_setup
/** Real call, real canonical events: the quiet local call sounds are counted at
 * the WebAudio oscillator, since they are not visible. Only the microphone is
 * a silent fixture stream. */
import type { Page } from '@playwright/test';
/* eslint-disable @typescript-eslint/no-require-imports -- Existing shared helpers use CommonJS. */
const { expect, test } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');

const LOOP_LOW = 261.63;
const LOOP_HIGH = 329.63;
const CHIME_LOW = 493.88;
const CHIME_HIGH = 739.99;

type Counts = Record<string, number>;

async function installAudioObservers(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const counts: Counts = {};
    Object.assign(window, { __toneCounts: counts });
    const create = AudioContext.prototype.createOscillator;
    AudioContext.prototype.createOscillator = function (this: AudioContext) {
      const oscillator = create.call(this);
      const setValueAtTime = oscillator.frequency.setValueAtTime.bind(oscillator.frequency);
      oscillator.frequency.setValueAtTime = (value: number, at: number) => {
        const key = value.toFixed(2);
        counts[key] = (counts[key] ?? 0) + 1;
        return setValueAtTime(value, at);
      };
      return oscillator;
    };
    // A silent microphone: a real MediaStream without any oscillator of ours.
    navigator.mediaDevices.getUserMedia = async () => {
      const context = new AudioContext();
      return context.createMediaStreamDestination().stream;
    };
  });
}

const tones = (page: Page): Promise<Counts> =>
  page.evaluate(() => ({ ...(window as unknown as { __toneCounts: Counts }).__toneCounts }));
const total = (counts: Counts, ...keys: number[]): number =>
  keys.reduce((sum, key) => sum + (counts[key.toFixed(2)] ?? 0), 0);

async function callChatId(page: Page): Promise<string> {
  let id = '';
  await expect.poll(async () => {
    id = page.url().match(/chat-id=([a-zA-Z0-9-]+)/)?.[1]
      ?? (await page.locator('[data-current-chat-id]').first().getAttribute('data-current-chat-id').catch(() => null)) ?? '';
    return id;
  }, { timeout: 15_000 }).not.toBe('');
  return id;
}

function dispatch(page: Page, name: string, detail: Record<string, unknown>): Promise<void> {
  return page.evaluate(([eventName, payload]) => {
    const hook = (window as unknown as { __openmatesE2EChatSyncEvents: { dispatch: (name: string, detail: unknown) => void } }).__openmatesE2EChatSyncEvents;
    hook.dispatch(eventName as string, payload);
  }, [name, detail] as const);
}

test.describe('voice call ambient sounds', () => {
  // contract-test: direct surface=gui.web assertions=video-call.sounds.ambient-skill-loop,video-call.sounds.ambient-focus-chime,video-call.sounds.local-only
  test('plays a skill loop and a focus chime during a live call and nothing while muted', async ({ page }) => {
    test.setTimeout(120_000);
    await installAudioObservers(page);
    await loginToTestAccount(page, () => {}, async () => {}, { waitForEditor: false });
    // The consent notice has its own case in voice-call.spec.ts; save the
    // acknowledgement through the product API so this call starts with one tap.
    const acknowledged = await page.evaluate(async (apiUrl: string) => {
      const response = await fetch(`${apiUrl}/v1/settings/voice-processing-ack`, {
        method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ version: 3 }),
      });
      return response.ok && (await response.json()).acknowledged === true;
    }, process.env.PLAYWRIGHT_TEST_API_URL!);
    expect(acknowledged, 'save the voice processing acknowledgement').toBe(true);
    await page.locator('[data-testid="voice-call-start"]:visible').click();
    await expect(page.getByTestId('voice-call-status-text')).toHaveText('Listening · You can speak now', { timeout: 15_000 });
    const chatId = await callChatId(page);
    const skill = (status: string) => ({ chat_id: chatId, embed_id: 'ambient-skill-1', type: 'app-skill-use', status, isProcessing: status === 'processing' });

    // Skill runs: the loop notes start and repeat.
    await dispatch(page, 'embedUpdated', skill('processing'));
    await expect.poll(async () => total(await tones(page), LOOP_LOW, LOOP_HIGH), { timeout: 5_000 }).toBeGreaterThanOrEqual(2);
    await expect.poll(async () => total(await tones(page), LOOP_LOW), { timeout: 6_000 }).toBeGreaterThanOrEqual(2);

    // The finish refresh carries no type; the loop stops anyway.
    await dispatch(page, 'embedUpdated', { chat_id: chatId, embed_id: 'ambient-skill-1', status: 'finished' });
    await page.waitForTimeout(300);
    const stopped = total(await tones(page), LOOP_LOW, LOOP_HIGH);
    await page.waitForTimeout(3_000);
    expect(total(await tones(page), LOOP_LOW, LOOP_HIGH)).toBe(stopped);

    // A focus mode of this chat starts: exactly one chime (two notes).
    const beforeChime = total(await tones(page), CHIME_LOW, CHIME_HIGH);
    await dispatch(page, 'focusModeActivated', { chat_id: chatId, focus_id: 'ambient-focus' });
    await expect.poll(async () => total(await tones(page), CHIME_LOW, CHIME_HIGH) - beforeChime).toBe(2);
    await page.waitForTimeout(1_000);
    expect(total(await tones(page), CHIME_LOW, CHIME_HIGH) - beforeChime).toBe(2);

    // Another chat's events stay silent.
    const beforeOther = await tones(page);
    await dispatch(page, 'embedUpdated', { ...skill('processing'), chat_id: 'another-chat' });
    await dispatch(page, 'focusModeActivated', { chat_id: 'another-chat' });
    await page.waitForTimeout(500);
    expect(await tones(page)).toEqual(beforeOther);

    // Muted: neither the loop nor the chime plays.
    await page.getByTestId('voice-call-mute').click();
    const beforeMuted = await tones(page);
    await dispatch(page, 'embedUpdated', skill('processing'));
    await dispatch(page, 'focusModeActivated', { chat_id: chatId, focus_id: 'ambient-focus' });
    await page.waitForTimeout(3_000);
    expect(await tones(page)).toEqual(beforeMuted);
    await dispatch(page, 'embedUpdated', { chat_id: chatId, embed_id: 'ambient-skill-1', status: 'finished' });
  });
});
