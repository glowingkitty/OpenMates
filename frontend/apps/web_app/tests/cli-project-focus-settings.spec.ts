/* eslint-disable @typescript-eslint/no-require-imports */
export {};
import type { Page } from '@playwright/test';

const { test, expect } = require('./helpers/cookie-audit');
const { getTestAccount } = require('./signup-flow-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { createWorkflowCliHome, removeWorkflowCliHome, loginWorkflowCliViaPair,
  runWorkflowCliJson, workflowApiUrl } = require('./helpers/workflow-cli-e2e-helpers');
const { email, password, otpKey } = getTestAccount();

test.describe('CLI Project focus preference', () => {
  test.setTimeout(180_000);
  // contract-test: direct surface=cli assertions=projects.focus.auto-selection-setting,projects.surface.semantic-parity
  test('persists focus activation policies and legacy off/on without changing encrypted instructions', async ({ page }: { page: Page }) => {
    skipWithoutCredentials(test, email, password, otpKey);
    const apiUrl = workflowApiUrl();
    const cliHome = createWorkflowCliHome('project-focus-settings');
    let projectId = '';
    try {
      await loginWorkflowCliViaPair(page, apiUrl, cliHome, 'CLI_PROJECT_FOCUS_SETTINGS');
      const created = await runWorkflowCliJson(apiUrl, cliHome, ['projects', 'create', `Focus preference ${Date.now()}`,
        '--write-policy', 'apply_and_show', '--personal'], 'create disposable Project');
      projectId = created.project.project_id;
      const settings = async (...flags: string[]) => runWorkflowCliJson(apiUrl, cliHome,
        ['projects', 'settings', projectId, '--personal', ...flags], 'Project focus preference');
      const initial = (await settings()).settings;
      expect(initial.auto_selection).toBe(true);
      expect(initial.focus_activation_policy).toBe('delayed');
      const disabled = (await settings('--auto-selection', 'off')).settings;
      expect(disabled.auto_selection).toBe(false);
      expect(disabled.encrypted_settings).toBe(initial.encrypted_settings);
      expect((await settings()).settings.auto_selection).toBe(false);
      expect((await settings('--auto-selection', 'on')).settings.auto_selection).toBe(true);
      expect((await settings('--focus-activation', 'immediate')).settings.focus_activation_policy).toBe('immediate');
      expect((await settings('--focus-activation', 'approval')).settings.focus_activation_policy).toBe('approval');
      const restored = (await settings('--focus-activation', 'delayed')).settings;
      expect(restored.focus_activation_policy).toBe('delayed');
      expect(restored.encrypted_settings).toBe(initial.encrypted_settings);
    } finally {
      try {
        if (projectId) await runWorkflowCliJson(apiUrl, cliHome,
          ['projects', 'delete', projectId, '--confirm', projectId, '--personal'], 'delete disposable Project');
      } finally { removeWorkflowCliHome(cliHome); }
    }
  });
});
