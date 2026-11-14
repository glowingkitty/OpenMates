import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
// proof-video: not_required reason=visual_smoke_not_needed

const PREVIEW = '/dev/preview/embeds/checks/CheckEmbedPreview?chrome=0&theme=light';
const FULLSCREEN = '/dev/preview/embeds/checks/CheckEmbedFullscreen?chrome=0&theme=light';
test.use({ viewport: { width: 1000, height: 800 }, trace: 'retain-on-failure' });

async function open(page: import('@playwright/test').Page, base: string, variant = '') {
  await page.goto(`${base}${variant ? `&variant=${variant}` : ''}&width=420`);
  await waitForComponentPreview(page);
}

// contract-test: supporting surface=gui.web assertions=checks.sources.mixed-types
test('preview shows mixed per-type chips and a passed status in text', async ({ page }, testInfo) => {
  await open(page, PREVIEW);
  const card = page.getByTestId('check-preview');
  await expect(card.getByTestId('check-preview-status')).toContainText('Passed');
  await expect(card.getByTestId('check-preview-chip-e2e')).toContainText('E2E 2/2');
  await expect(card.getByTestId('check-preview-chip-unit')).toContainText('Unit 1/1');
  await expect(card.getByTestId('check-preview-chip-ai')).toContainText('AI ✓');
  await testInfo.attach('check-preview-passed-mixed', { body: await card.screenshot(), contentType: 'image/png' });
});

// contract-test: supporting surface=gui.web assertions=checks.human.waiting-for-confirmation
test('preview shows Waiting for confirmation for a pending human source, not failed', async ({ page }, testInfo) => {
  await open(page, PREVIEW, 'waitingForConfirmation');
  const card = page.getByTestId('check-preview');
  await expect(card.getByTestId('check-preview-status')).toContainText('Waiting for confirmation');
  await expect(card).not.toContainText('Failed');
  await expect(card.getByTestId('check-preview-chip-human')).toContainText('pending');
  // The card has no nested actions (runs start in the fullscreen) and its last-run line fits inside the 200px card.
  await expect(card.getByTestId('check-preview-run')).toHaveCount(0);
  const shell = await page.locator('.unified-embed-preview').first().boundingBox();
  const meta = await card.getByTestId('check-preview-last-run').boundingBox();
  expect(shell && meta).toBeTruthy();
  expect(meta!.y + meta!.height).toBeLessThanOrEqual(shell!.y + shell!.height - 8);
  await testInfo.attach('check-preview-waiting', { body: await card.screenshot(), contentType: 'image/png' });
});

// contract-test: supporting surface=gui.web assertions=checks.runs.revision-bound
test('preview marks a stale Check with text', async ({ page }) => {
  await open(page, PREVIEW, 'stale');
  await expect(page.getByTestId('check-preview-stale')).toContainText('Stale');
});

// contract-test: supporting surface=gui.web assertions=checks.aggregation.required-sources-gate
test('fullscreen groups sources by type and keeps a failing supporting source from turning the Check red', async ({ page }, testInfo) => {
  await open(page, FULLSCREEN);
  const body = page.getByTestId('check-fullscreen-body');
  for (const group of ['e2e', 'unit', 'ai', 'human']) await expect(body.getByTestId(`check-group-${group}`)).toBeVisible();
  await expect(body.getByTestId('check-group-e2e').getByTestId('check-source-role').first()).toContainText('Required');
  await expect(body.getByTestId('check-ai-score')).toContainText('0.86');
  await expect(body.getByTestId('check-ai-question')).toBeVisible();
  await expect(body.getByTestId('check-rule-notice')).toBeVisible();
  await expect(body.getByTestId('check-status')).toContainText('Passed');
  await testInfo.attach('check-fullscreen-passed-mixed', { body: await page.screenshot(), contentType: 'image/png' });
});

// contract-test: supporting surface=gui.web assertions=checks.human.waiting-for-confirmation
test('fullscreen confirm button is offered only while pending and reports the decision', async ({ page }) => {
  await open(page, FULLSCREEN, 'waitingForConfirmation');
  const logs: string[] = [];
  page.on('console', (m) => logs.push(m.text()));
  await expect(page.getByTestId('check-source-human-1')).toContainText('Waiting for confirmation');
  await page.getByTestId('check-human-confirm').click();
  await expect.poll(() => logs.some((l) => l.includes('confirm') && l.includes('human-1') && l.includes('confirmed'))).toBe(true);
  await open(page, FULLSCREEN);
  await expect(page.getByTestId('check-human-confirm')).toHaveCount(0);
});

// contract-test: supporting surface=gui.web assertions=checks.human.waiting-for-confirmation
test('fullscreen shows a stored human instruction once and no empty run detail', async ({ page }, testInfo) => {
  await open(page, FULLSCREEN, 'storedHumanSource');
  const human = page.getByTestId('check-source-s2');
  await expect(human).toContainText('Waiting for confirmation');
  await expect(human.getByText('Taste the pancakes and confirm they are fluffy')).toHaveCount(1);
  await expect(human.getByTestId('check-human-confirm')).toBeVisible();
  const run = page.getByTestId('check-run-run-1');
  await expect(run).toContainText('Revision 1 · ');
  await expect(run).not.toContainText('· ·');
  await testInfo.attach('check-fullscreen-stored-human-source', { body: await page.getByTestId('check-fullscreen-body').screenshot(), contentType: 'image/png' });
});

// contract-test: supporting surface=gui.web assertions=checks.runs.revision-bound
test('fullscreen run history lists the newest run first and marks stale runs', async ({ page }) => {
  await open(page, FULLSCREEN);
  const runs = page.getByTestId('check-history').locator('[data-testid^="check-run-run-"]');
  await expect(runs.first()).toHaveAttribute('data-testid', 'check-run-run-3');
  await expect(page.getByTestId('check-run-run-2')).toHaveAttribute('data-stale', 'true');
});
