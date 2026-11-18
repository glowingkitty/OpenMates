// contract-test: supporting surface=gui.web assertions=contracts.revision.exact-approval,contracts.ui.human-readable-default
/**
 * Specification embed: preview card status, revisions panel and exact-revision approval.
 * Uses synthetic /dev/preview fixtures; does not prove backend storage.
 * Contract: feature.specifications.
 */
import { test, expect } from '../helpers/cookie-audit';

// playwright-account: not_required reason=isolated_component_preview
// proof-video: not_required reason=visual_smoke_not_needed


test.describe('Specification embed preview', () => {
  // contract-test: supporting surface=gui.web assertions=contracts.ui.human-readable-default
  test('draft card shows status, revision and proof summary', async ({ page }) => {
    await page.goto(`/dev/preview/embeds/specifications/SpecificationEmbedPreview?chrome=0&theme=light`);
    await expect(page.getByTestId('specification-status')).toHaveAttribute('data-status', 'draft');
    await expect(page.getByTestId('specification-revision')).toContainText('3');
    await expect(page.getByTestId('specification-proof-summary')).toContainText('1');
  });

  // contract-test: supporting surface=gui.web assertions=contracts.revision.exact-approval
  test('approved variant and changes-since-approval variant show their badges', async ({ page }) => {
    await page.goto(`/dev/preview/embeds/specifications/SpecificationEmbedPreview?chrome=0&theme=light&variant=approved`);
    await expect(page.getByTestId('specification-status')).toHaveAttribute('data-status', 'approved');
    await page.goto(`/dev/preview/embeds/specifications/SpecificationEmbedPreview?chrome=0&theme=light&variant=changes-since-approval`);
    await expect(page.getByTestId('specification-status')).toHaveAttribute('data-status', 'changes');
  });
});

test.describe('Specification fullscreen revisions and approval', () => {
  // contract-test: supporting surface=gui.web assertions=contracts.revision.exact-approval
  test('lists revisions with current marker and confirms approval of the exact revision', async ({ page }) => {
    await page.goto(`/dev/preview/embeds/specifications/SpecificationEmbedFullscreen?chrome=0&theme=light`);
    await expect(page.getByTestId('specification-revisions').locator('li')).toHaveCount(3);
    await expect(page.getByTestId('specification-revision-rev-3').locator('[data-marker="current"]')).toBeVisible();
    await expect(page.getByTestId('specification-revision-rev-2').locator('[data-marker="approved"]')).toBeVisible();

    const approved = page.evaluate(() => new Promise(resolve =>
      window.addEventListener('specification-preview-approve', e => resolve((e as CustomEvent).detail), { once: true })));
    await page.getByTestId('specification-approve').click();
    await expect(page.getByTestId('specification-approve-confirm')).toBeVisible();
    await page.getByTestId('specification-approve-confirm-button').click();
    expect(await approved).toEqual({ revisionId: 'rev-3', contentHash: 'sha256:c3' });
  });

  // contract-test: supporting surface=gui.web assertions=contracts.revision.exact-approval
  test('approve is disabled on an older read-only revision', async ({ page }) => {
    await page.goto(`/dev/preview/embeds/specifications/SpecificationEmbedFullscreen?chrome=0&theme=light&variant=older-revision-read-only`);
    await expect(page.getByTestId('specification-read-only')).toBeVisible();
    await expect(page.getByTestId('specification-approve')).toBeDisabled();
  });

  // contract-test: supporting surface=gui.web assertions=contracts.revision.exact-approval
  test('approve is disabled when the shown revision is already approved', async ({ page }) => {
    await page.goto(`/dev/preview/embeds/specifications/SpecificationEmbedFullscreen?chrome=0&theme=light&variant=approved`);
    await expect(page.getByTestId('specification-status-strip')).toHaveAttribute('data-approval-state', 'approved');
    await expect(page.getByTestId('specification-approve')).toBeDisabled();
  });
});
