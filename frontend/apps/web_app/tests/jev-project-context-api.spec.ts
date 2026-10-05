/* eslint-disable @typescript-eslint/no-require-imports */
export {};
import type { Page } from '@playwright/test';
const { test, expect } = require('./helpers/cookie-audit');
const { getTestAccount } = require('./signup-flow-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { createWorkflowCliHome, removeWorkflowCliHome, loginWorkflowCliViaPair,
  runWorkflowCliJson, workflowApiUrl } = require('./helpers/workflow-cli-e2e-helpers');
const { randomUUID } = require('node:crypto');

test.describe('Jev Project context HTTP boundaries', () => {
  test.setTimeout(180_000);
  // contract-test: direct surface=rest_api assertions=chats.context.memory-only-summary,rules.ownership.encrypted-custom
  test('public requests cannot access memory-only context or background private jobs', async ({ page }: { page: Page }) => {
    const base = workflowApiUrl();
    for (const endpoint of ['completion', 'read', 'write', 'active', 'context/seal', 'context/open']) {
      const response = await page.request.post(`${base}/internal/recent-work/${endpoint}`, {
        data: { text: 'synthetic-private-context-sentinel' },
      });
      expect([401, 403, 404]).toContain(response.status());
      expect(await response.text()).not.toContain('synthetic-private-context-sentinel');
    }
    const privateJob = await page.request.get(`${base}/v1/projects/${randomUUID()}/authoring/jobs/${randomUUID()}`);
    expect([401, 403, 404]).toContain(privateJob.status());
  });

  // contract-test: direct surface=rest_api assertions=projects.focus.inferred-consent,focus-modes.project-authoring-click,focus-modes.project-recommendation-catalog
  test('owned Project metadata does not authorize private loading or an authoring job', async ({ page }: { page: Page }) => {
    const { email, password, otpKey } = getTestAccount();
    skipWithoutCredentials(test, email, password, otpKey);
    const base = workflowApiUrl();
    const cliHome = createWorkflowCliHome('jev-project-context-boundaries');
    let projectId = '';
    try {
      await loginWorkflowCliViaPair(page, base, cliHome, 'JEV_PROJECT_CONTEXT_BOUNDARIES');
      const result = await runWorkflowCliJson(base, cliHome, ['projects', 'create', `Jev boundary ${Date.now()}`,
        '--write-policy', 'always_ask', '--personal'], 'create disposable context Project');
      projectId = result.project.project_id;
      const prefix = `${base}/v1/projects/${projectId}`;
      const chatId = randomUUID();
      const context = await page.request.post(`${prefix}/context/select`, {
        data: { chat_id: chatId, text: 'synthetic-private-context-sentinel', candidates: [] },
      });
      expect([403, 404]).toContain(context.status());
      expect(await context.text()).not.toContain('synthetic-private-context-sentinel');
      const recommendation = await page.request.post(`${prefix}/authoring/recommend`, {
        data: { chat_id: chatId, message_id: randomUUID(), catalog: [],
          history: [{ role: 'user', content: 'synthetic-private-context-sentinel' }] },
      });
      expect([403, 404, 409]).toContain(recommendation.status());
      expect(await recommendation.text()).not.toContain('synthetic-private-context-sentinel');
      const unrequested = await page.request.post(`${prefix}/authoring/jobs`, {
        data: { recommendation_id: randomUUID(), expected_revision: null,
          history: [{ role: 'user', content: 'synthetic-private-context-sentinel' }] },
      });
      expect([403, 404, 409]).toContain(unrequested.status());
      expect(await unrequested.text()).not.toContain('synthetic-private-context-sentinel');
      const missing = await page.request.get(`${prefix}/authoring/jobs/${randomUUID()}`);
      expect([403, 404]).toContain(missing.status());
      const settings = await runWorkflowCliJson(base, cliHome, ['projects', 'settings', projectId, '--personal'],
        'verify rejected context requests preserve Project policy');
      expect(settings.settings.write_mode).toBe('always_ask');
    } finally {
      try {
        if (projectId) await runWorkflowCliJson(base, cliHome,
          ['projects', 'delete', projectId, '--confirm', projectId, '--personal'], 'delete disposable context Project');
      } finally { removeWorkflowCliHome(cliHome); }
    }
  });
});
