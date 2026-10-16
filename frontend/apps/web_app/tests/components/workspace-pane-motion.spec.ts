// playwright-account: not_required reason=isolated_component_preview
/* eslint-disable @typescript-eslint/no-require-imports */
export {};
const { test, expect } = require('../helpers/cookie-audit');
const { waitForComponentPreview } = require('../helpers/component-preview');

test.describe('Workspace pane motion', () => {
  // contract-test: direct surface=gui.web assertions=workflows-ui.detail.fullscreen-route-motion,workspace-shell.start.chat-visual-parity
  test('slides and fades in both directions while retaining the outgoing template', async ({ page }: { page: any }) => {
    page.on('pageerror', error => console.log('PREVIEW_PAGE_ERROR', error.stack));
    page.on('console', message => { if (message.type() === 'error') console.log('PREVIEW_CONSOLE_ERROR', message.text()); });
    page.on('requestfailed', request => console.log('PREVIEW_REQUEST_FAILED', request.url(), request.failure()?.errorText));
    page.on('response', async response => { if (response.status() >= 400) console.log('PREVIEW_BAD_RESPONSE', response.status(), response.url(), (await response.text().catch(() => '')).slice(0, 6000)); });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.addInitScript(() => {
      const animate = Element.prototype.animate;
      Element.prototype.animate = function (...args: Parameters<Element['animate']>) {
        const animation = animate.apply(this, args);
        if (this.getAttribute('data-testid') === 'workflow-management') animation.playbackRate = 0.05;
        return animation;
      };
    });
    await page.goto('/dev/preview/workflows/WorkflowHomePreviewHarness?chrome=0&variant=guest&width=390');
    await waitForComponentPreview(page);
    await page.getByTestId('workflow-landing-card').first().click();
    const pane = page.getByTestId('workflow-management');
    const title = page.getByTestId('workspace-detail-title');
    await expect(title).toBeVisible();
    const expectedTitle = await title.textContent();
    async function midpoint() {
      await expect.poll(() => pane.evaluate((node: HTMLElement) => node.getAnimations().length)).toBeGreaterThan(0);
      return pane.evaluate(async (node: HTMLElement) => {
        const animation = node.getAnimations()[0];
        animation.pause();
        animation.currentTime = Number(animation.effect!.getTiming().duration) / 2;
        await new Promise(requestAnimationFrame);
        const style = getComputedStyle(node);
        const matrix = new DOMMatrixReadOnly(style.transform);
        return { y: matrix.m42, scale: matrix.m11, opacity: Number(style.opacity) };
      });
    }
    const entrance = await midpoint();
    expect(entrance.y).toBeGreaterThan(0);
    expect(entrance.scale).toBe(1);
    expect(entrance.opacity).toBeGreaterThan(0);
    expect(entrance.opacity).toBeLessThan(1);
    await pane.evaluate((node: HTMLElement) => node.getAnimations().forEach(animation => animation.finish()));
    await page.getByTestId('workflow-detail-back').click();
    const exit = await midpoint();
    await expect(title).toHaveText(expectedTitle);
    await expect(page.getByTestId('workflow-editor')).toBeAttached();
    expect(exit.y).toBeCloseTo(entrance.y, 0);
    expect(exit.opacity).toBeCloseTo(entrance.opacity, 1);
    expect(exit.scale).toBe(1);
    await pane.evaluate((node: HTMLElement) => node.getAnimations().forEach(animation => animation.finish()));
    await expect(pane).toHaveCount(0);
    await expect(page.getByTestId('workflows-start-screen')).toBeVisible();
  });
});
