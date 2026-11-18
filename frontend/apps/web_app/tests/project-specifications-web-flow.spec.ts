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
  workflowApiUrl, writeWorkflowYaml } = require('./helpers/workflow-cli-e2e-helpers');
const { email, password, otpKey } = getTestAccount();

const documentYaml = (outcome: string) => `title: Recipe planning
summary: Save recipes and plan meals for the week
category: Product
outcome: ${outcome}
scope:
  included: [Saving recipes]
  excluded: [Grocery delivery]
requirements:
  - id: R1
    statement: A user can save a recipe.
    example: Saving "Pancakes" lists it under recipes.
`;

test.describe('Web Project Specifications', () => {
  test.setTimeout(240_000);
  test.beforeAll(() => {
    // A cold release build of the native CLI takes far longer than one test.
    test.setTimeout(2_700_000);
    require('./helpers/rust-cli-terminal').buildRustCli();
  });
  // contract-test: supporting surface=gui.web assertions=contracts.revision.exact-approval,contracts.ui.human-readable-default
  test('a Project shows its Specification, opens the readable document with revisions and approves the shown revision', async ({ page }: { page: Page }) => {
    skipWithoutCredentials(test, email, password, otpKey);
    const apiUrl = workflowApiUrl();
    const cliHome = createWorkflowCliHome('project-specifications-web');
    let projectId = '';
    try {
      await loginWorkflowCliViaPair(page, apiUrl, cliHome, 'WEB_PROJECT_SPECIFICATIONS');
      await closeSettingsPanel(page, test.info());
      const created = await runWorkflowCliJson(apiUrl, cliHome, ['projects', 'create', naturalProjectName('Recipe collection'),
        '--write-policy', 'apply_and_show', '--personal'], 'create disposable Project');
      projectId = created.project.project_id;
      const first = writeWorkflowYaml(cliHome, 'spec-1.yml', documentYaml('People keep their recipes in one place.'));
      const made = await runWorkflowCliJson(apiUrl, cliHome, ['specifications', 'create', '--project', projectId, '--file', first, '--personal'], 'create Specification');
      const specificationId = made.specification.specification_id;
      const firstRevisionId = made.revision.revision_id;
      const second = writeWorkflowYaml(cliHome, 'spec-2.yml', documentYaml('People keep and reuse their recipes in one place.'));
      const revised = await runWorkflowCliJson(apiUrl, cliHome, ['specifications', 'revise', specificationId, '--project', projectId,
        '--revision', firstRevisionId, '--file', second, '--personal'], 'revise Specification');
      const headRevisionId = revised.revision.revision_id;

      await page.goto(getE2EDebugUrl(`/#project-id=${encodeURIComponent(projectId)}`), { waitUntil: 'domcontentloaded' });
      const section = page.getByTestId('project-specifications-section');
      await expect(section).toBeVisible({ timeout: 60_000 });
      const card = page.getByTestId(`project-specification-${specificationId}`);
      await expect(card).toContainText('Recipe planning', { timeout: 30_000 });
      await expect(page.getByTestId('project-specifications-error')).toHaveCount(0);

      await card.getByTestId('specification-embed-card').click();
      await expect(page.getByTestId('specification-revisions')).toBeVisible({ timeout: 30_000 });
      await expect(page.getByText('People keep and reuse their recipes in one place.').first()).toBeVisible();
      await expect(page.getByTestId('spec-requirement').first()).toContainText('A user can save a recipe.');
      await expect(page.getByTestId(`specification-revision-${firstRevisionId}`)).toBeVisible();
      await expect(page.getByTestId(`specification-revision-${headRevisionId}`)).toBeVisible();

      await page.getByTestId(`specification-revision-${firstRevisionId}`).click();
      await expect(page.getByText('People keep their recipes in one place.').first()).toBeVisible({ timeout: 30_000 });
      await expect(page.getByTestId('specification-read-only')).toBeVisible();

      await page.getByTestId(`specification-revision-${headRevisionId}`).click();
      await expect(page.getByText('People keep and reuse their recipes in one place.').first()).toBeVisible({ timeout: 30_000 });
      const approved = page.waitForResponse((response) => response.request().method() === 'POST'
        && response.url().includes(`/specifications/${specificationId}/approve`) && response.ok());
      await page.getByTestId('specification-approve').click();
      await page.getByTestId('specification-approve-confirm-button').click();
      const approveBody = (await approved).request().postDataJSON();
      expect(approveBody.revision_id).toBe(headRevisionId);
      await expect(page.getByTestId('specification-status-strip')).toContainText('Approved', { timeout: 30_000 });
      await expect(page.getByTestId('project-specifications-action-error')).toHaveCount(0);
    } finally {
      try {
        if (projectId) await runWorkflowCliJson(apiUrl, cliHome,
          ['projects', 'delete', projectId, '--confirm', projectId, '--personal'], 'delete disposable Project');
      } finally { removeWorkflowCliHome(cliHome); }
    }
  });
});
