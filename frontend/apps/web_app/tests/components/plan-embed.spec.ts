import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview

const card = '/dev/preview/embeds/plans/PlanEmbedPreview?chrome=0';
const fullscreen = '/dev/preview/embeds/plans/PlanEmbedFullscreen?chrome=0';

// The card body must be the rendered Plan, fully inside the standard embed card
// (a stray markup fragment once rendered as text and pushed the content out).
async function expectCardContentInside(page: import('@playwright/test').Page) {
  const shell = page.getByTestId('embed-preview');
  const article = page.getByTestId('plan-embed-preview');
  await expect(article).not.toContainText(/onclick|data-approval-state|\$\$props/);
  const box = (await shell.boundingBox())!;
  const optional = ['plan-embed-approval', 'plan-embed-waiting', 'plan-embed-assumptions'];
  for (const id of ['plan-embed-title', 'plan-embed-status', 'plan-embed-approval', 'plan-embed-progress', 'plan-embed-checks', ...optional]) {
    if (optional.includes(id) && (await page.getByTestId(id).count()) === 0) continue;
    const el = (await page.getByTestId(id).boundingBox())!;
    expect(el.y, `${id} starts inside the card`).toBeGreaterThanOrEqual(box.y - 1);
    expect(el.y + el.height, `${id} fits inside the card`).toBeLessThanOrEqual(box.y + box.height + 1);
    expect(el.x + el.width, `${id} fits inside the card`).toBeLessThanOrEqual(box.x + box.width + 1);
  }
}

// contract-test: supporting surface=gui.web assertions=plans.embed.preview-fullscreen
test('Plan embed card shows status, approval, progress, checks and open assumptions', async ({ page }) => {
  await page.goto(`${card}&variant=inProgress`);
  await waitForComponentPreview(page);
  await expect(page.getByTestId('plan-embed-preview')).toHaveAttribute('data-plan-status', 'executing');
  await expect(page.getByTestId('plan-embed-preview')).toHaveAttribute('data-approval-state', 'approved');
  await expect(page.getByTestId('plan-embed-approval')).toBeVisible();
  await expect(page.getByTestId('plan-embed-title')).toHaveText('Prepare the OpenMates launch plan');
  await expect(page.getByTestId('plan-embed-waiting')).toBeVisible();
  await expect(page.getByTestId('plan-embed-progress')).toBeVisible();
  await expect(page.getByTestId('plan-embed-checks')).toBeVisible();
  const shell = page.getByTestId('embed-preview');
  await expect(shell).toHaveCount(1);
  await expect(shell.getByTestId('plan-embed-preview')).toHaveCount(1);
  await expectCardContentInside(page);
  await test.info().attach('plan-embed-in-progress', { body: await shell.screenshot(), contentType: 'image/png' });
  await expect(page.getByTestId('plan-embed-assumptions')).toHaveCount(0);

  await page.goto(`${card}&variant=draft`);
  await waitForComponentPreview(page);
  // A draft Plan says "Draft" once: the approval chip would only repeat the status chip.
  await expect(page.getByTestId('plan-embed-preview')).toHaveAttribute('data-approval-state', 'draft');
  await expect(page.getByTestId('plan-embed-status')).toHaveAttribute('data-status', 'draft');
  await expect(page.getByTestId('plan-embed-approval')).toHaveCount(0);
  await expect(page.getByTestId('plan-embed-preview').getByText('Draft', { exact: true })).toHaveCount(1);
  await expect(page.getByTestId('plan-embed-assumptions')).toBeVisible();
  await expectCardContentInside(page);
  await test.info().attach('plan-embed-draft', { body: await shell.screenshot(), contentType: 'image/png' });

  await page.goto(`${card}&variant=blocked`);
  await waitForComponentPreview(page);
  await expect(page.getByTestId('plan-embed-approval')).toHaveAttribute('data-status', 'changed');
  await expect(page.getByTestId('plan-embed-status')).toHaveAttribute('data-status', 'blocked');
  await expectCardContentInside(page);
  await test.info().attach('plan-embed-blocked', { body: await shell.screenshot(), contentType: 'image/png' });
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
  await expect(page.getByTestId('plan-assumption-open-chat')).toHaveText('Checking chat');
  await expect(page.getByTestId('plan-task-open-chat')).toHaveCount(1);
  await expect(page.getByTestId('plan-task-open-chat')).toHaveText('Working chat');
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
