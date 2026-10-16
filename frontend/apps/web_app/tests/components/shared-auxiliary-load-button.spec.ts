import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
const PREVIEW = '/dev/preview/SharedAuxiliaryLoadButton?theme=light&background=%23dbeafe&width=390&chrome=0';

// contract-test: direct surface=gui.web assertions=storage.cold.discoverable-bounded
test('shared auxiliary continuation is visible, focusable, and invokes one request', async ({ page }) => {
  await page.goto(PREVIEW);
  await waitForComponentPreview(page);
  const button = page.getByTestId('shared-auxiliary-load-more');
  await expect(button).toBeVisible();
  await expect(button).toBeEnabled();
  await expect(button).toContainText(/show more/i);
  const bounds = await button.boundingBox();
  expect(bounds?.width).toBeGreaterThan(70);
  expect(bounds?.height).toBeGreaterThan(20);
  await button.focus();
  await expect(button).toBeFocused();
  await button.click();
  await expect.poll(() => page.evaluate(() => document.body.dataset.sharedAuxiliaryClicked)).toBe('true');
});

// contract-test: direct surface=gui.web assertions=storage.cold.discoverable-bounded
test('shared auxiliary continuation shows loading and retry states', async ({ page }) => {
  await page.goto(`${PREVIEW}&variant=loading`);
  await waitForComponentPreview(page);
  const button = page.getByTestId('shared-auxiliary-load-more');
  await expect(button).toBeDisabled();
  await expect(button).toHaveAttribute('aria-busy', 'true');
  await page.goto(`${PREVIEW}&variant=failed`);
  await waitForComponentPreview(page);
  await expect(page.getByTestId('shared-auxiliary-load-more')).toContainText(/try again/i);
});
