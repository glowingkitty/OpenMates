import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview

const card = '/dev/preview/embeds/plans/PlanEmbedPreview?chrome=0';
const fullscreen = '/dev/preview/embeds/plans/PlanEmbedFullscreen?chrome=0';

// contract-test: supporting surface=gui.web assertions=plans.embed.preview-fullscreen
test('Plan embed card shows status, approval, progress, checks and open assumptions', async ({ page }) => {
  await page.goto(`${card}&variant=inProgress`);
  await waitForComponentPreview(page);
  await expect(page.getByTestId('plan-embed-preview')).toHaveAttribute('data-plan-status', 'executing');
  await expect(page.getByTestId('plan-embed-preview')).toHaveAttribute('data-approval-state', 'approved');
  await expect(page.getByTestId('plan-embed-title')).toHaveText('Prepare the OpenMates launch plan');
  await expect(page.getByTestId('plan-embed-waiting')).toBeVisible();
  await expect(page.getByTestId('plan-embed-assumptions')).toHaveCount(0);

  await page.goto(`${card}&variant=draft`);
  await waitForComponentPreview(page);
  await expect(page.getByTestId('plan-embed-approval')).toHaveAttribute('data-status', 'draft');
  await expect(page.getByTestId('plan-embed-assumptions')).toBeVisible();

  await page.goto(`${card}&variant=blocked`);
  await waitForComponentPreview(page);
  await expect(page.getByTestId('plan-embed-approval')).toHaveAttribute('data-status', 'changed');
  await expect(page.getByTestId('plan-embed-status')).toHaveAttribute('data-status', 'blocked');
});

// contract-test: supporting surface=gui.web assertions=plans.embed.preview-fullscreen,plans.approval.revision-bound
test('Plan fullscreen lists goal, assumptions, criteria, tasks, checks and binds approval to the revision', async ({ page }) => {
  await page.goto(`${fullscreen}&variant=draft`);
  await waitForComponentPreview(page);
  await expect(page.getByTestId('plan-goal-text')).toBeVisible();
  await expect(page.getByTestId('plan-assumption-row')).toHaveCount(2);
  await expect(page.getByTestId('plan-assumption-open-chat')).toHaveCount(1);
  await expect(page.getByTestId('plan-criterion-row')).toHaveCount(1);
  await expect(page.getByTestId('plan-task-row')).toHaveCount(3);
  await expect(page.getByTestId('plan-check-row')).toHaveCount(1);
  await expect(page.getByTestId('plan-approval-bar')).toHaveAttribute('data-revision-id', 'rev-1');
  await expect(page.getByTestId('plan-approve-button')).toBeEnabled();

  await page.goto(`${fullscreen}&variant=approved`);
  await waitForComponentPreview(page);
  await expect(page.getByTestId('plan-approval-bar')).toHaveAttribute('data-approval-state', 'approved');
  await expect(page.getByTestId('plan-approve-button')).toBeDisabled();

  await page.goto(`${fullscreen}&variant=inProgress`);
  await waitForComponentPreview(page);
  await expect(page.locator('[data-testid="plan-check-row"][data-status="waiting_for_confirmation"]')).toHaveCount(1);
  await expect(page.locator('[data-testid="plan-check-row"][data-status="stale"]')).toHaveCount(1);
  await expect(page.locator('[data-testid="plan-check-row"][data-required="false"]')).toHaveCount(0);

  await page.goto(`${fullscreen}&variant=blocked`);
  await waitForComponentPreview(page);
  await expect(page.getByTestId('plan-approval-bar')).toHaveAttribute('data-approval-state', 'changed');
  await expect(page.getByTestId('plan-approval-bar')).toHaveAttribute('data-revision-id', 'rev-3');
  await expect(page.getByTestId('plan-approve-button')).toBeEnabled();
});
