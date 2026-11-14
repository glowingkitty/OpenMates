/* eslint-disable @typescript-eslint/no-require-imports */
export {};
import type { Page } from '@playwright/test';

// The specifications and checks commands exist only in the native Rust CLI (client core),
// so this spec drives it. Set before the CLI helpers load: they read it at require time.
process.env.OPENMATES_CLI_IMPL = 'native';

const { test, expect } = require('./helpers/cookie-audit');
const { getTestAccount, getE2EDebugUrl } = require('./signup-flow-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { naturalProjectName } = require('./helpers/project-names');
const { closeSettingsPanel } = require('./helpers/settings-readiness');
const { createWorkflowCliHome, removeWorkflowCliHome, loginWorkflowCliViaPair, runWorkflowCliJson,
  workflowApiUrl } = require('./helpers/workflow-cli-e2e-helpers');
const { email, password, otpKey } = getTestAccount();

test.describe('Web Project Checks', () => {
  test.setTimeout(240_000);
  test.beforeAll(() => {
    // A cold release build of the native CLI takes far longer than one test.
    test.setTimeout(2_700_000);
    require('./helpers/rust-cli-terminal').buildRustCli();
  });
  // contract-test: supporting surface=gui.web assertions=checks.project.encrypted-embed,checks.human.waiting-for-confirmation
  test('a Project shows its Check waiting for confirmation and the human source is confirmed in the fullscreen', async ({ page }: { page: Page }) => {
    skipWithoutCredentials(test, email, password, otpKey);
    const apiUrl = workflowApiUrl();
    const cliHome = createWorkflowCliHome('project-checks-web');
    let projectId = '';
    try {
      await loginWorkflowCliViaPair(page, apiUrl, cliHome, 'WEB_PROJECT_CHECKS');
      await closeSettingsPanel(page, test.info());
      const created = await runWorkflowCliJson(apiUrl, cliHome, ['projects', 'create', naturalProjectName('Recipe collection'),
        '--write-policy', 'apply_and_show', '--personal'], 'create disposable Project');
      projectId = created.project.project_id;
      const made = await runWorkflowCliJson(apiUrl, cliHome, ['checks', 'create', '--project', projectId, '--personal',
        '--title', 'Pancake recipe works', '--source', 'unit:required:tests/pancakes',
        '--source', 'human_confirmation:required:Taste the pancakes and confirm they are fluffy'], 'create Check');
      const checkId = made.check.check_id;
      const started = await runWorkflowCliJson(apiUrl, cliHome, ['checks', 'run', checkId, '--project', projectId, '--personal'], 'start run');
      const runId = started.run.run_id;
      await runWorkflowCliJson(apiUrl, cliHome, ['checks', 'result', runId, 's1', '--check', checkId, '--status', 'passed',
        '--project', projectId, '--personal'], 'report passed unit result');

      await page.goto(getE2EDebugUrl(`/#project-id=${encodeURIComponent(projectId)}`), { waitUntil: 'domcontentloaded' });
      await expect(page.getByTestId('project-checks-section')).toBeVisible({ timeout: 60_000 });
      const card = page.getByTestId(`project-check-${checkId}`);
      await expect(card).toContainText('Pancake recipe works', { timeout: 30_000 });
      await expect(card).toContainText('Waiting for confirmation');
      await expect(page.getByTestId('project-checks-error')).toHaveCount(0);

      // The whole card opens the fullscreen; click near its top, away from the Run button.
      await page.locator(`[data-embed-id="project-check-${checkId}"]`).click({ position: { x: 150, y: 30 } });
      await expect(page.getByTestId('check-human-confirm')).toBeVisible({ timeout: 30_000 });
      await expect(page.getByText('Taste the pancakes and confirm they are fluffy').first()).toBeVisible();
      const confirmed = page.waitForResponse((response) => response.request().method() === 'POST'
        && response.url().includes(`/runs/${runId}/sources/s2/confirm`) && response.ok());
      await page.getByTestId('check-human-confirm').click();
      expect((await confirmed).request().postDataJSON().decision).toBe('confirmed');
      await expect(page.getByText('Passed').first()).toBeVisible({ timeout: 30_000 });
      await expect(page.getByTestId('project-checks-action-error')).toHaveCount(0);
    } finally {
      try {
        if (projectId) await runWorkflowCliJson(apiUrl, cliHome,
          ['projects', 'delete', projectId, '--confirm', projectId, '--personal'], 'delete disposable Project');
      } finally { removeWorkflowCliHome(cliHome); }
    }
  });
});
