/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
export {};

const { expect, test } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');
const { createProjectPlanForTest } = require('./helpers/create-project-plan');

test.describe('Plans in Tasks and Projects', () => {
  // contract-test: direct surface=gui.web assertions=plans.lifecycle.visible,plans.content.client-encrypted,plans.ui.edit-approve-resume
  test('creates an encrypted Project Plan and opens it from the Tasks board', async ({ page }) => {
    test.setTimeout(180000);
    test.skip(!getTestAccount().email, 'Test account credentials required.');
    await skipIfFeaturesDisabled(test, page, ['platform:projects', 'platform:tasks', 'platform:plans']);
    await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
    await loginToTestAccount(page);

    const projectName = `Plan flow project ${Date.now()}`;
    let planPayload = '';
    page.on('request', (request) => {
      if (request.method() === 'POST' && request.url().endsWith('/v1/user-plans')) planPayload = request.postData() ?? '';
    });
    const { planId } = await createProjectPlanForTest(page, projectName);
    expect(planPayload).not.toContain(projectName);
    await expect(page.getByTestId('plan-title-input')).toBeVisible();

    await page.goto(getE2EDebugUrl('/tasks'), { waitUntil: 'domcontentloaded' });
    await expect(page.getByTestId('tasks-page')).toBeVisible({ timeout: 30000 });
    const card = page.locator(`[data-testid="task-board-plan-card"][data-plan-id="${planId}"]`);
    await expect(card).toBeVisible({ timeout: 30000 });
    await card.getByTestId('task-board-plan-open').click();
    await expect(page).toHaveURL(new RegExp(`/#plan-id=${planId}(?:&|$)`));
    await expect(page.getByTestId('plan-detail-page')).toBeVisible();
    await expect(page.getByTestId('plans-nav-link')).toHaveCount(0);
    await expect(page.getByTestId('tasks-nav-link')).toHaveAttribute('aria-current', 'page');
  });
});
