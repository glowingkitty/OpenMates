// proof-video: not_required reason=visual_smoke_not_needed
/** Opening a call from a new chat: the call strip appears once and stays.
 * Real call socket, STT fixture and encrypted chat binding in isolated CI. Every
 * animation frame from the tap until the bound chat is listening is sampled, so
 * a remount, a gap or a replayed entrance fails instead of only looking wrong.
 */
/* eslint-disable @typescript-eslint/no-require-imports -- Existing shared helpers use CommonJS. */
const { expect, test: auditedTest } = require('./helpers/cookie-audit');
const { withProofAudio, proofAudioLaunchArgs } = require('./helpers/proof-audio');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');

const test = withProofAudio(auditedTest);
test.use({ launchOptions: { args: proofAudioLaunchArgs() }, reducedMotion: 'no-preference' });

interface BarSample {
  t: number;
  count: number;
  id: number;
  top: number;
  opacity: number;
  slot: string;
  faded: string[];
}

test.describe('voice call opening', () => {
  // contract-test: direct surface=gui.web assertions=video-call.chat.call-strip-opening
  test('opens the call bar from a new chat exactly once and keeps it visible until listening', async ({ page }, testInfo) => {
    test.setTimeout(120_000);
    await page.addInitScript(() => {
      const samples: BarSample[] = [];
      const entrances: string[] = [];
      const ids = new WeakMap<Element, number>();
      let nextId = 0;
      let armed = false;
      Object.assign(window, { __callBarSamples: samples, __callBarEntrances: entrances, __armCallBarSampling: () => { armed = true; } });
      document.addEventListener('animationstart', event => {
        if (armed && event.target instanceof Element && event.target.matches('.voice-call-inline-region')) {
          entrances.push(event.animationName);
        }
      });
      const sample = () => {
        if (armed && samples.length < 6000) {
          const bars = [...document.querySelectorAll('[data-testid="voice-call-bar"]')]
            .filter(bar => { const box = bar.getBoundingClientRect(); return box.width > 0 && box.height > 0; });
          const bar = bars[0];
          if (bar && !ids.has(bar)) ids.set(bar, ++nextId);
          let opacity = 1;
          const faded: string[] = [];
          for (let node: Element | null = bar ?? null; node; node = node.parentElement) {
            const value = Number(getComputedStyle(node).opacity);
            opacity *= value;
            if (value < 0.99) faded.push(`${node.className || node.tagName}: ${value.toFixed(2)}`);
          }
          samples.push({
            t: Math.round(performance.now()), count: bars.length, id: bar ? ids.get(bar)! : 0,
            top: bar ? Math.round(bar.getBoundingClientRect().top) : -1, opacity: bar ? Math.round(opacity * 100) / 100 : 0,
            slot: !bar ? 'none' : bar.closest('.voice-call-inline-region') ? 'inline' : 'history', faded,
          });
        }
        requestAnimationFrame(sample);
      };
      requestAnimationFrame(sample);
    });
    await loginToTestAccount(page, () => {}, async () => {}, { waitForEditor: false });
    // The consent notice has its own case in voice-call.spec.ts.
    const acknowledged = await page.evaluate(async (apiUrl: string) => {
      const response = await fetch(`${apiUrl}/v1/settings/voice-processing-ack`, {
        method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ version: 3 }),
      });
      return response.ok && (await response.json()).acknowledged === true;
    }, process.env.PLAYWRIGHT_TEST_API_URL!);
    expect(acknowledged, 'save the voice processing acknowledgement').toBe(true);

    const start = page.locator('[data-testid="voice-call-start"]:visible');
    await expect(start).toBeVisible();
    // The hover tooltip names only the action.
    await start.hover();
    const tooltip = page.getByRole('tooltip');
    await expect(tooltip).toHaveText('Start voice call');
    await expect(start).not.toHaveAttribute('title', /.+/);
    await testInfo.attach('start-voice-call-tooltip', { body: await page.screenshot(), contentType: 'image/png' });
    await page.mouse.move(0, 0);

    await page.evaluate(() => (window as unknown as { __armCallBarSampling: () => void }).__armCallBarSampling());
    await start.click();
    await expect(page.getByTestId('voice-call-status-text')).toHaveText('Listening · You can speak now', { timeout: 20_000 });
    await expect(page).toHaveURL(/chat-id=/);
    // playwright-determinism: allow - this observation window measures visibility across the full chat binding and header reveal.
    await page.waitForTimeout(3_000);
    await testInfo.attach('call-bar-open', { body: await page.screenshot(), contentType: 'image/png' });
    const { samples, entrances } = await page.evaluate(() => {
      const recording = window as unknown as { __callBarSamples: BarSample[]; __callBarEntrances: string[] };
      return { samples: recording.__callBarSamples, entrances: recording.__callBarEntrances };
    });
    await testInfo.attach('call-bar-opening-timeline', { body: JSON.stringify(samples), contentType: 'application/json' });
    expect(entrances, 'one slide-in for the call strip').toEqual([expect.stringContaining('voice-call-enter')]);

    const first = samples.findIndex(sample => sample.count > 0);
    expect(first, 'the call bar appears after the tap').toBeGreaterThanOrEqual(0);
    const after = samples.slice(first);
    expect(after.filter(sample => sample.count === 0).length, 'the call bar never disappears while it opens').toBe(0);
    // Name each element change (time, slot, position) so a failure shows which mount replaced the bar.
    const changes = after.filter((sample, index) => index > 0 && sample.id !== after[index - 1].id)
      .map(sample => `${sample.t - after[0].t}ms -> #${sample.id} ${sample.slot} top=${sample.top}`);
    expect(new Set(after.map(sample => sample.id)).size, `one call bar element: no remount restarts its entrance (${after[0].slot} first; ${changes.join(', ')})`).toBe(1);
    expect(Math.max(...after.map(sample => sample.count)), 'never two call bars at once').toBe(1);
    const shown = after.findIndex(sample => sample.opacity >= 0.99);
    expect(shown, 'the call bar becomes fully visible').toBeGreaterThanOrEqual(0);
    const faded = after.slice(shown).filter(sample => sample.opacity < 0.99);
    const ancestors = [...new Set(faded.flatMap(sample => sample.faded))];
    expect(faded.length, `the call bar does not fade out and in again (${ancestors.join(', ')})`).toBe(0);

    await page.getByTestId('voice-call-hangup').click();
    await expect(page.getByTestId('voice-call-bar')).toHaveCount(0);
  });
});
