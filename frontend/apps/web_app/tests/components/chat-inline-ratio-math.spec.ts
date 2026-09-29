// playwright-account: not_required reason=isolated_component_preview
import { expect, test } from '../helpers/cookie-audit';

// contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence
test('assistant chat message renders ratio formulas without swallowing prose', async ({ page }) => {
  await page.goto('/dev/preview/ChatMessage?variant=inlineRatioMath&theme=dark&width=900&chrome=0', {
    waitUntil: 'networkidle',
  });

  await expect(page.getByTestId('component-preview-canvas')).toHaveAttribute(
    'data-preview-ready',
    'true',
    { timeout: 30_000 },
  );

  const message = page.locator('.chat-message-body');
  await expect(message).toBeVisible();
  const formulas = message.locator('[data-type="inline-math"]');
  await expect(formulas).toHaveCount(4);
  await expect(formulas.first()).toHaveAttribute('data-latex', '1:1{,}618');
  await expect(formulas.nth(1)).toHaveAttribute('data-latex', '1:1{,}414');
  await expect(formulas.nth(2)).toHaveAttribute('data-latex', '\\sqrt{2}');
  await expect(formulas.nth(3)).toHaveAttribute('data-latex', '1:1{,}5');
  await expect(message).toContainText('Je nach Kontext werden oft Seitenverhältnisse');
  await expect(message.locator('.katex-error')).toHaveCount(0);
  await expect(formulas.first().locator('.katex-html')).toContainText('1:1,618');
});
