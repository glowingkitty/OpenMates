// playwright-account: not_required reason=public_guest_navigation
/* eslint-disable @typescript-eslint/no-require-imports */
export {};
const { test, expect } = require('./helpers/cookie-audit');
const { getE2EDebugUrl } = require('./signup-flow-helpers');

test.describe('Guest workspace navigation', () => {
  // contract-test: direct surface=gui.web assertions=workflows-ui.detail.fullscreen-route-motion,landing-onboarding.uses-real-chat-shell,workspace-shell.start.chat-visual-parity
  for (const width of [1440, 390]) {
    test(`retains guest panels through reverse motion and exposes settings and signup at ${width}px`, async ({ page }: { page: any }) => {
      test.setTimeout(120000);
      await page.setViewportSize({ width, height: 900 });
      await page.addInitScript(() => {
        const animate = Element.prototype.animate;
        Element.prototype.animate = function (...args: Parameters<Element['animate']>) {
          const animation = animate.apply(this, args);
          if (this.matches('[data-testid="workflow-management"], .chat-wrapper')) animation.playbackRate = 0.05;
          return animation;
        };
      });
      async function settings() {
        const button = page.getByTestId('profile-container');
        await expect(button).toBeVisible();
        await button.click();
        await expect(page.getByTestId('settings-menu')).toHaveClass(/overlay/);
        await page.getByTestId('icon-button-close').click();
        await expect(page.getByTestId('settings-menu')).not.toHaveClass(/overlay/);
      }
      async function sample(pane: any) {
        await expect.poll(() => pane.evaluate((node: HTMLElement) => node.getAnimations().length)).toBeGreaterThan(0);
        return pane.evaluate(async (node: HTMLElement) => {
          const animation = node.getAnimations()[0];
          animation.pause();
          animation.currentTime = Number(animation.effect!.getTiming().duration) / 2;
          await new Promise(requestAnimationFrame);
          const style = getComputedStyle(node);
          const transform = new DOMMatrixReadOnly(style.transform);
          return { y: transform.m42, scale: transform.m11, opacity: Number(style.opacity) };
        });
      }
      async function finish(pane: any) {
        await pane.evaluate((node: HTMLElement) => node.getAnimations().forEach(animation => animation.finish()));
      }
      async function gutters(panel: any) {
        await expect(panel).toBeVisible();
        return panel.evaluate((node: HTMLElement) => {
          const rect = node.getBoundingClientRect();
          return { left: rect.left, bottom: window.innerHeight - rect.bottom };
        });
      }
      await page.goto(getE2EDebugUrl('/workflows'), { waitUntil: 'networkidle' });
      await expect(page.getByText('Explore the workflow automations:', { exact: true })).toBeVisible();
      const workflowGutters = await gutters(page.getByTestId('workflows-page'));
      await settings();
      await page.getByTestId('workflow-landing-card').first().click();
      const workflow = page.getByTestId('workflow-management');
      const title = page.getByTestId('workspace-detail-title');
      const expectedTitle = await title.textContent();
      const incoming = await sample(workflow);
      expect(incoming.y).toBeGreaterThan(0);
      expect(incoming.scale).toBe(1);
      expect(incoming.opacity).toBeGreaterThan(0);
      expect(incoming.opacity).toBeLessThan(1);
      await finish(workflow);
      await page.getByTestId('workflow-detail-back').click();
      const outgoing = await sample(workflow);
      await expect(title).toHaveText(expectedTitle);
      await expect(page.getByTestId('workflow-editor')).toBeAttached();
      expect(outgoing.y).toBeCloseTo(incoming.y, 0);
      expect(outgoing.opacity).toBeCloseTo(incoming.opacity, 1);
      await finish(workflow);
      await expect(workflow).toHaveCount(0);
      await page.getByTestId('workflow-guest-signup').click();
      await expect(page.getByTestId('signup-modal')).toBeVisible();

      await page.goto(getE2EDebugUrl('/'), { waitUntil: 'networkidle' });
      const skip = page.getByTestId('guest-interest-skip');
      if (await skip.isVisible()) await skip.click();
      await expect(page.getByTestId('guest-interest-prompt')).toHaveText('Explore some example chats:');
      const chatGutters = await gutters(page.getByTestId('active-chat-container'));
      expect(chatGutters.left).toBeCloseTo(workflowGutters.left, 0);
      expect(chatGutters.bottom).toBeCloseTo(workflowGutters.bottom, 0);
      await settings();
      const guestCards = page.locator('[data-testid="resume-chat-large-card"], [data-testid="resume-chat-card"]');
      const guestChatIds = await guestCards.evaluateAll((cards: HTMLElement[]) => cards.map(card => card.dataset.chatId).filter(Boolean));
      await guestCards.first().click();
      const chatPane = page.locator('.chat-wrapper').filter({ has: page.getByTestId('chat-close-button') });
      const chatIncoming = await sample(chatPane);
      expect(chatIncoming.y).toBeGreaterThan(0);
      expect(chatIncoming.scale).toBe(1);
      await finish(chatPane);
      await expect(page.getByTestId('active-chat-container')).not.toHaveAttribute('data-current-chat-id', '');
      const chatId = await page.getByTestId('active-chat-container').getAttribute('data-current-chat-id');
      await page.getByTestId('chat-close-button').click();
      const chatOutgoing = await sample(chatPane);
      await expect(page.getByTestId('active-chat-container')).toHaveAttribute('data-current-chat-id', chatId);
      expect(chatOutgoing.y).toBeCloseTo(chatIncoming.y, 0);
      expect(chatOutgoing.opacity).toBeCloseTo(chatIncoming.opacity, 1);
      await finish(chatPane);
      await expect(page.getByTestId('chat-close-button')).toHaveCount(0);
      if (width === 1440) {
        // Freeze A's outgoing animation, then select B through the real URL navigation boundary.
        // Completing the stale A close must preserve B and give B its own entrance.
        const replacementId = guestChatIds.find((id: string) => id !== chatId);
        expect(replacementId, 'guest examples provide a distinct replacement chat').toBeTruthy();
        await page.evaluate((id: string) => { window.location.hash = `chat-id=${id}`; }, chatId);
        const reopenedPane = page.locator('.chat-wrapper').filter({ has: page.getByTestId('chat-close-button') });
        await sample(reopenedPane);
        await finish(reopenedPane);
        await page.getByTestId('chat-close-button').click();
        await sample(reopenedPane);
        await page.evaluate((id: string) => { window.location.hash = `chat-id=${id}`; }, replacementId);
        await expect(page.getByTestId('active-chat-container')).toHaveAttribute('data-current-chat-id', replacementId);
        await finish(reopenedPane);
        await expect(reopenedPane).toHaveAttribute('data-navigation-closing', 'false');
        const replacementEntrance = await sample(reopenedPane);
        expect(replacementEntrance.y).toBeGreaterThan(0);
        await expect(page.getByTestId('active-chat-container')).toHaveAttribute('data-current-chat-id', replacementId);
        await finish(reopenedPane);
        await expect(page.getByTestId('chat-close-button')).toBeVisible();
      }

      await page.goto(getE2EDebugUrl('/apps'), { waitUntil: 'networkidle' });
      const appsGutters = await gutters(page.getByTestId('apps-workspace-home'));
      expect(appsGutters.left).toBeCloseTo(chatGutters.left, 0);
      expect(appsGutters.bottom).toBeCloseTo(chatGutters.bottom, 0);
    });
  }
});
