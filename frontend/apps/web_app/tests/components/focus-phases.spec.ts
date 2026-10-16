import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
// playwright-account: not_required reason=isolated_component_preview

test.describe('Phased focus details and chat history', () => {
  // contract-test: direct surface=gui.web assertions=focus-modes.phases
  test('details show instructions and requirements at laptop and phone widths', async ({ page }) => {
    for (const width of [1280, 390]) {
      await page.setViewportSize({ width, height: 850 });
      await page.goto('/dev/preview/settings/FocusModePhases?chrome=0');
      await waitForComponentPreview(page);
      await expect(page.getByTestId('focus-mode-phase')).toHaveCount(2);
      await expect(page.getByTestId('focus-phase-instructions').first()).toContainText('skip remaining questions');
      await expect(page.getByTestId('focus-phase-requirement').last()).toContainText('explicitly asks to skip');
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.screenshot({ path: test.info().outputPath(`focus-phases-${width}.png`) });
    }
  });
  // contract-test: direct surface=gui.web assertions=focus-modes.phases,focus-modes.history-side-effects,focus-modes.history-events
  test('actual system message shows a phase link, survives reload, and has no active-phase controls', async ({ page }) => {
    await page.goto('/dev/preview/ChatMessage?chrome=0&variant=focusPhase');
    await waitForComponentPreview(page);
    const link = page.getByTestId('focus-phase-details-link');
    await expect(link).toHaveText('Explore career directions');
    await expect(link).toHaveAttribute('data-focus-detail-path', 'apps/jobs/focus/career_insights');
    await expect(page.getByTestId('focus-progress-bar')).toHaveCount(0);
    await expect(page.getByTestId('focus-phase-requirement')).toHaveCount(0);
    await page.reload();
    await expect(link).toBeVisible();
    await link.click();
    // Preview still has access to the real settings store; opening the link changes only navigation.
    await expect(page.getByTestId('focus-phase-notice')).toContainText('Explore career directions');
    await page.screenshot({ path: test.info().outputPath('focus-phase-history.png') });
  });
  // contract-test: direct surface=gui.web assertions=focus-modes.phases,focus-modes.history-events
  test('rewind history clearly identifies returning to a previous phase', async ({ page }) => {
    await page.goto('/dev/preview/ChatMessage?chrome=0&variant=focusPhaseReturn');
    await waitForComponentPreview(page);
    await expect(page.getByTestId('focus-phase-notice')).toContainText('Returned to focus phase:');
    await expect(page.getByTestId('focus-phase-details-link')).toHaveText('Understand your situation');
  });
});
