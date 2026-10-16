import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { createVideoProofRuntime, defineVideoProof } = require('../helpers/video-proof');
const devices = ['web-phone', 'web-laptop'];
const proofContract = defineVideoProof({
  id: 'voice-call-event-notice', title: 'Voice call history events', surface: 'web',
  devices: devices, domain: 'app.dev.openmates.org',
  transcript: [
    { id: 'started', checkpoint: 'started', devices, text: 'The call start appears as a grey notice with the blue audio call glyph and its time.' },
    { id: 'ended', checkpoint: 'ended', devices, text: 'The call end appears with its own timestamp.' },
  ],
  assertions: [
    { id: 'start-notice', checkpoint: 'started', devices, visual: 'You started a voice call appears beside the audio call glyph and 12:31 PM.' },
    { id: 'end-notice', checkpoint: 'ended', devices, visual: 'You ended a voice call appears beside the audio call glyph and 12:33 PM.' },
  ],
  tutorial: { readingWordsPerSecond: 2.5, minimumHoldMs: 1800, maximumHoldMs: 5000 },
});
test.use({ locale: 'en-US', timezoneId: 'UTC' });

for (const width of [390, 1280]) {
  // Fixture presentation supports the lifecycle contract; encrypted persistence is covered by the authenticated flow.
  // contract-test: supporting surface=gui.web assertions=video-call.chat.call-events,video-call.privacy
  test(`renders readable audio call lifecycle notices at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 844 });
    const device = width === 390 ? 'web-phone' : 'web-laptop';
    const proof = createVideoProofRuntime(proofContract, { device, attach: testInfo.attach.bind(testInfo) });
    for (const state of [
      { action: 'started', wording: 'You started a voice call', time: '12:31 PM', datetime: '2026-10-15T12:31:00.000Z', assertion: 'start-notice' },
      { action: 'ended', wording: 'You ended a voice call', time: '12:33 PM', datetime: '2026-10-15T12:33:00.000Z', assertion: 'end-notice' },
    ]) {
      const query = new URLSearchParams({ chrome: '0', theme: 'light', width: String(width - 48),
        ...(state.action === 'ended' ? { variant: 'ended' } : {}) });
      await page.goto(`/dev/preview/VoiceCallEventNotice?${query}`);
      await waitForComponentPreview(page);
      const notice = page.getByTestId(`voice-call-${state.action}`);
      await proof.assert(state.assertion, async () => {
        await expect(notice).toBeVisible();
        await expect(notice).toHaveText(`${state.wording} – ${state.time}`);
        await expect(notice.locator('time')).toHaveAttribute('datetime', state.datetime);
        await expect(notice.locator('time')).toHaveText(state.time);
        const icon = notice.locator('.call-icon');
        await expect(icon).toBeVisible();
        await expect(icon).toHaveAttribute('aria-hidden', 'true');
        const masks = await icon.evaluate((element) => {
          // Canonical icon CSS and this component resolve the same asset through
          // Vite; production bundling may inline it rather than preserve its name.
          const probe = document.createElement('span');
          probe.className = 'clickable-icon icon_call';
          element.appendChild(probe);
          const result = { actual: getComputedStyle(element).maskImage,
            canonical: getComputedStyle(probe).maskImage };
          probe.remove();
          return result;
        });
        expect(masks.canonical).not.toBe('none');
        expect(masks.canonical).not.toBe('');
        expect(masks.actual).toBe(masks.canonical);
        expect(await icon.evaluate((element) => {
          const token = getComputedStyle(element).getPropertyValue('--color-primary-start').trim();
          const probe = document.createElement('span');
          probe.style.backgroundColor = token;
          element.appendChild(probe);
          const matches = Boolean(token) && getComputedStyle(element).backgroundColor === getComputedStyle(probe).backgroundColor;
          probe.remove();
          return matches;
        })).toBe(true);
        expect(await notice.evaluate((element) => {
          const token = getComputedStyle(element).getPropertyValue('--color-grey-60').trim();
          const probe = document.createElement('span');
          probe.style.color = token;
          element.appendChild(probe);
          const matches = Boolean(token) && getComputedStyle(element).color === getComputedStyle(probe).color;
          probe.remove();
          return matches;
        })).toBe(true);
        await expect(notice).not.toContainText('call-preview-1234');
        await expect(notice).not.toContainText('schema_version');
        await expect(notice).not.toContainText('active_elapsed_seconds');
        await expect(notice.locator('audio, video, button, svg')).toHaveCount(0);
        await expect(notice).toBeInViewport({ ratio: 1 });
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      });
      await proof.checkpoint(state.action);
    }
    await proof.attach();
  });
}
