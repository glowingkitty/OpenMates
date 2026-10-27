import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
// playwright-account: not_required reason=isolated_component_preview

test.describe('Localized focus instructions', () => {
  // contract-test: direct surface=gui.web assertions=settings-ui.localization.visible-content-resolves,focus-modes.controls
  test('authored instructions use the selected language and expand without placeholders', async ({ page }) => {
    for (const [language, width, phrase] of [['en', 1280, 'Act as a professional Social Media Strategist'], ['de', 390, 'Agiere als professioneller Social-Media-Stratege']] as const) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto(`/dev/preview/settings/FocusModeDetails?chrome=0&theme=light&background=%23dbeafe&width=${width}&lang=${language}`);
      await waitForComponentPreview(page);
      const toggle = page.getByTestId('focus-instructions-toggle');
      await expect(toggle).toBeVisible();
      await toggle.focus();
      await expect(toggle).toBeFocused();
      await toggle.press('Enter');
      const instructions = page.getByTestId('focus-instructions-text');
      await expect(instructions).toContainText(phrase);
      await expect(page.locator('body')).not.toContainText('[T:');
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.screenshot({ path: test.info().outputPath(`focus-instructions-${language}-${width}.png`) });
      await toggle.click();
      await expect(instructions).toHaveCount(0);
    }
  });

  // contract-test: direct surface=gui.web assertions=settings-ui.localization.visible-content-resolves,focus-modes.controls
  test('empty and stale-reference modes show the translated empty state without inventing instructions', async ({ page }) => {
    for (const variant of ['empty', 'staleReferences']) {
      await page.goto(`/dev/preview/settings/FocusModeDetails?chrome=0&theme=light&background=%23dbeafe&width=390&variant=${variant}`);
      await waitForComponentPreview(page);
      await expect(page.getByTestId('focus-no-instructions')).toBeVisible();
      await expect(page.getByTestId('focus-instructions-toggle')).toHaveCount(0);
      await expect(page.getByTestId('focus-instructions-text')).toHaveCount(0);
      await expect(page.locator('body')).not.toContainText('[T:');
      await page.screenshot({ path: test.info().outputPath(`focus-instructions-${variant}.png`) });
    }
  });
});
