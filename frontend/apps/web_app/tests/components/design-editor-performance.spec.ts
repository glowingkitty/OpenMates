// playwright-account: not_required reason=isolated_component_preview
// contract-test-file: tooling
import { test, expect, type BrowserContext } from '@playwright/test';
import { createIsolatedBrowserContext, declareTestState } from '../helpers/chat-test-helpers';
import { waitForComponentPreview } from '../helpers/component-preview';

const path = '/dev/preview/embeds/design/editor/DesignEditorFullscreen';

const testState = declareTestState({
  auth: 'guest component preview',
  browserStorage: 'fresh',
  account: 'none',
  chat: 'none',
  notifications: 'none',
  securityReminders: 'none'
});

const performanceProfiles = [
  { name: 'desktop-ci', viewport: { width: 1280, height: 860 }, deviceScaleFactor: 1, cpuRate: 1 },
  { name: 'phone-proxy-ci', viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, cpuRate: 4 }
];

for (const profile of performanceProfiles) {
  test(`measures cold paint, drag frame pacing and memory on ${profile.name}`, async ({ browser }, info) => {
    test.setTimeout(240_000);
    const results = [];
    for (const layers of [50, 100, 250, 500, 1000]) {
      for (let repeat = 0; repeat < 3; repeat++) {
        const context: BrowserContext = await createIsolatedBrowserContext(browser, testState, {
          baseURL: String(info.project.use.baseURL), viewport: profile.viewport,
          deviceScaleFactor: profile.deviceScaleFactor, reducedMotion: 'reduce',
          isMobile: profile.cpuRate > 1, hasTouch: profile.cpuRate > 1
        });
        try {
          const page = await context.newPage();
          const cdp = await context.newCDPSession(page);
          await cdp.send('Emulation.setCPUThrottlingRate', { rate: profile.cpuRate });
          const query = new URLSearchParams({
            theme: 'light', width: String(profile.viewport.width), chrome: '0', variant: `stress-${layers}`
          });
          await page.goto(`${path}?${query}`);
          await waitForComponentPreview(page);
          const board = page.getByTestId('design-canvas');
          await expect(board).toHaveAttribute('data-painted-page', 'stress');
          const coldMs = await page.evaluate(() => performance.getEntriesByName('design-page-painted')[0].startTime);
          const bounds = (await board.boundingBox())!;
          const scale = Number(await board.getAttribute('data-scale'));
          const start = {
            x: bounds.x + (bounds.width - 812 * scale) / 2 + 190 * scale,
            y: bounds.y + (bounds.height - 46 - 570 * scale) / 2 + 47 * scale
          };
          await page.mouse.move(start.x, start.y);
          await page.mouse.down();
          await expect(page.getByTestId('design-workspace')).toHaveAttribute('data-selection', 'headline');
          const timing = await board.evaluate(async (node: HTMLCanvasElement, start) => {
            const context = node.getContext('2d')!;
            const clear = context.clearRect;
            const draws: number[] = [];
            // The editor clears once per draw. Count actual draws, since browser
            // animation callbacks can continue while a renderer skips a frame.
            context.clearRect = function (...args) {
              draws.push(performance.now());
              clear.apply(this, args);
            };
            try {
              await new Promise<void>((resolve) => {
                let first = 0;
                function frame(now: number) {
                  if (!first) first = now;
                  if (now - first >= 1_000) {
                    resolve();
                    return;
                  }
                  // Schedule input after the current paint so it cannot cancel
                  // a draw that is already queued for this frame.
                  setTimeout(() => {
                    const offset = Math.sin((now - first) / 150) * 30;
                    node.dispatchEvent(new PointerEvent('pointermove', {
                      bubbles: true, composed: true, pointerId: 1, pointerType: 'mouse', buttons: 1,
                      clientX: start.x + offset, clientY: start.y
                    }));
                  }, 0);
                  requestAnimationFrame(frame);
                }
                requestAnimationFrame(frame);
              });
            } finally {
              context.clearRect = clear;
            }
            const deltas = draws.slice(1).map((time, index) => time - draws[index]).sort((a, b) => a - b);
            return { draws: draws.length, fps: 1000 * deltas.length / (draws.at(-1)! - draws[0]),
              p95Ms: deltas[Math.ceil(deltas.length * .95) - 1] };
          }, start);
          expect(timing.draws).toBeGreaterThan(2);
          await page.mouse.up();
          await cdp.send('HeapProfiler.collectGarbage');
          const heap = await cdp.send('Runtime.getHeapUsage');
          const canvasBytes = await board.evaluate((node: HTMLCanvasElement) => node.width * node.height * 4);
          const sample = { profile: profile.name, layers, coldMs, ...timing,
            jsHeapMiB: heap.usedSize / 2 ** 20, rgbaBufferMiB: canvasBytes / 2 ** 20 };
          results.push(sample);
          console.log('Design performance sample', JSON.stringify(sample));
        } finally {
          await context.close();
        }
      }
    }
    await info.attach(`design-performance-${profile.name}.json`, {
      body: JSON.stringify(results, null, 2), contentType: 'application/json'
    });
    console.log('Design performance samples', JSON.stringify(results));
  });
}
