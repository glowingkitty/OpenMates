import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview

const preview = '/dev/preview/settings/SettingsTeams?theme=light&background=%23dbeafe&width=390&chrome=0';

// contract-test: direct surface=gui.web assertions=billing.storage.weekly-quote,billing.storage.team-policy-gate
// contract-test: supporting surface=gui.web assertions=settings-ui.composition.canonical-and-accessible,settings-ui.localization.visible-content-resolves
test('team storage preview states separate price quote from enabled billing', async ({ page }) => {
  await page.goto(`${preview}&variant=owner`);
  const canvas = await waitForComponentPreview(page);
  await expect(canvas.getByTestId('team-storage-summary')).toContainText('3 credits / week');
  await expect(canvas.getByTestId('team-storage-policy')).toContainText('Sundays at 03:00 UTC');
  await expect(canvas.getByTestId('team-storage-preview')).toContainText('not yet enabled');
  await expect(canvas.getByTestId('team-storage-active-notice')).toHaveCount(0);
  const layout = await canvas.locator('.settings-page-container').evaluate(element => ({ client: element.clientWidth, scroll: element.scrollWidth }));
  expect(layout.scroll).toBeLessThanOrEqual(layout.client + 1);
});

// contract-test: direct surface=gui.web assertions=billing.storage.team-policy-gate
test('team storage quote is available to admins and hidden from viewers', async ({ page }) => {
  await page.goto(`${preview}&variant=admin`);
  let canvas = await waitForComponentPreview(page);
  await expect(canvas.getByTestId('team-storage-summary')).toBeVisible();
  await page.goto(`${preview}&variant=viewer`);
  canvas = await waitForComponentPreview(page);
  await expect(canvas.getByTestId('team-storage-summary')).toHaveCount(0);
  await expect(canvas.getByTestId('team-storage-policy')).toHaveCount(0);
});

// contract-test: direct surface=gui.web assertions=billing.storage.team-warning-expiry
// contract-test: supporting surface=gui.web assertions=settings-ui.composition.canonical-and-accessible
test('team storage notice previews delivered warnings and paginates affected units', async ({ page }) => {
  const second = { unit_id: 'b'.repeat(64), kind: 'artifact_history', resource_id: 'artifact-2',
    oldest_at: 1_700_000_100, bytes: 268_435_456, fingerprint: 'preview-2' };
  await page.route('**/v1/teams/preview-team/storage/notice?**', route => route.fulfill({ json: {
    episode_id: 'episode-1', warning_count: 3, deadline_at: 1_791_936_000, manual_review: false,
    unit_selection_hash: 'preview', units: [second], has_more: false, next_after_unit_id: null,
  } }));
  await page.goto(`${preview}&variant=notice`);
  const canvas = await waitForComponentPreview(page);
  await expect(canvas.getByTestId('team-storage-active-notice')).toContainText('four delivered weekly warning rounds');
  await expect(canvas.getByTestId('team-storage-affected-unit')).toHaveCount(1);
  const more = canvas.getByTestId('team-storage-load-more');
  await more.focus();
  await expect(more).toBeFocused();
  await more.press('Enter');
  await expect(canvas.getByTestId('team-storage-affected-unit')).toHaveCount(2);
  await expect(more).toHaveCount(0);
});

// contract-test: direct surface=gui.web assertions=billing.storage.team-warning-expiry,billing.storage.team-policy-gate
test('a delayed old team notice cannot block or replace the selected team notice', async ({ page }) => {
  const storageFor = (team: string) => ({ storage: {
    total_bytes: 1_610_612_736, legacy_upload_bytes: 0, logical_s3_bytes: 1_610_612_736,
    categories: { cold_chat_graphs: 1_610_612_736 }, measurement_at: 1_791_072_000,
    metering_source_version: 'logical-s3-v1', metering_policy_version: 'team-storage-1gb-3credits-week-v1',
    free_bytes: 1_073_741_824, credits_per_started_excess_gib_per_week: 3, billable_gib: 1,
    weekly_cost_credits: 3, billing_status: 'unpaid',
    billing: { status: 'unpaid', warning_count: team === 'first' ? 4 : 2, deadline_at: 1_791_936_000,
      expiry_due: false, expiry_enabled: false, affected_units: [], has_more_affected_units: false },
  } });
  await page.route('**/v1/teams/first-team/storage', route => route.fulfill({ json: storageFor('first') }));
  await page.route('**/v1/teams/second-team/storage', route => route.fulfill({ json: storageFor('second') }));
  let releaseFirst!: () => void;
  let firstStarted!: () => void;
  let firstCompleted!: () => void;
  const firstGate = new Promise<void>(resolve => { releaseFirst = resolve; });
  const firstRequest = new Promise<void>(resolve => { firstStarted = resolve; });
  const firstDone = new Promise<void>(resolve => { firstCompleted = resolve; });
  await page.route('**/v1/teams/first-team/storage/notice?**', async route => {
    firstStarted();
    await firstGate;
    await route.fulfill({ json: { episode_id: 'old-episode', warning_count: 4, deadline_at: 1_791_936_000,
      manual_review: false, unit_selection_hash: 'old', units: [], has_more: false, next_after_unit_id: null } });
    firstCompleted();
  });
  await page.route('**/v1/teams/second-team/storage/notice?**', route => route.fulfill({ json: {
    episode_id: 'new-episode', warning_count: 2, deadline_at: 1_791_936_000,
    manual_review: false, unit_selection_hash: 'new', units: [], has_more: false, next_after_unit_id: null,
  } }));
  await page.goto('/dev/preview/settings/SettingsTeamsRaceHarness?theme=light&background=%23dbeafe&width=390&chrome=0');
  const canvas = await waitForComponentPreview(page);
  await firstRequest;
  await canvas.getByTestId('team-preview-switch').click();
  await expect(canvas.getByTestId('teams-settings-detail')).toContainText('Second team');
  await expect(canvas.getByTestId('teams-settings-detail')).toContainText('2 / 4');
  releaseFirst();
  await firstDone;
  await expect(canvas.getByTestId('teams-settings-detail')).toContainText('2 / 4');
});
