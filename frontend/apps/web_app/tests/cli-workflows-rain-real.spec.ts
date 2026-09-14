/* eslint-disable @typescript-eslint/no-require-imports */
/** Modern CLI workflow lifecycle, real Berlin forecast and encrypted chat delivery.
 * Runs only through isolated CI, using its disposable account and credential-free weather provider.
 */
export {};
const { test, expect } = require('./helpers/cookie-audit');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { getTestAccount } = require('./signup-flow-helpers');
const {
 createWorkflowCliHome, deleteWorkflowQuietly, loginWorkflowCliViaPair,
 removeWorkflowCliHome, runWorkflowCli, runWorkflowCliJson, uniqueWorkflowName,
 waitForWorkflowRunStatus, waitForChatTitle, workflowApiUrl, writeWorkflowYaml
} = require('./helpers/workflow-cli-e2e-helpers');
const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

test.describe('CLI Workflows rain YAML lifecycle', () => {
 test.setTimeout(360_000);
 // contract-test: direct surface=cli assertions=workflows-ui.identity.automatic-category-icon,workflows.surface.semantic-parity,cli.output.actionable-readable,cli.surface.semantic-parity,workflows.activation.reachable-side-effect,workflows.chat-delivery.client-encrypted
 test('saves a draft, runs while disabled, delivers encrypted results and deletes run history', async ({ page }: { page: any }) => {
  skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
  const apiUrl = workflowApiUrl();
  const homeDir = createWorkflowCliHome('workflow-rain');
  let workflowId: string | undefined;
  try {
   await loginWorkflowCliViaPair(page, apiUrl, homeDir, 'CLI_WORKFLOW_RAIN');
   const capabilities = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'capabilities'], 'capabilities');
   expect(capabilities.filter((c: any) => c.enabled).map((c: any) => c.id)).toEqual(expect.arrayContaining(['schedule_trigger', 'app_skill_action', 'check', 'send_chat_message', 'weather.forecast']));
   const title = uniqueWorkflowName('Berlin rain workflow');
   const chatTitle = uniqueWorkflowName('Berlin weather results');
   const source = (input: string) => `
title: ${title}
start_when:
  schedule:
    type: daily
    time: "09:00"
    timezone: Europe/Berlin
steps:
  - id: forecast
    use_app_skill: weather.forecast
    input: ${input}
  - id: rain_check
    check:
      left: $nodes.forecast.output.rain_expected
      op: eq
      right: true
  - id: report
    send_chat_message:
      title: ${chatTitle}
      message: Berlin weather update
      blocks:
        - id: weather
          source: $nodes.forecast.output.rain_summary
`;
   const incomplete = writeWorkflowYaml(homeDir, 'incomplete.yml', source('{}'));
   const created = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'create', '--file', incomplete], 'create incomplete draft');
   workflowId = created.workflow.id;
   expect(created.workflow.enabled).toBe(false);
   expect(created.validation.enable_ready).toBe(false);
   const rejected = await runWorkflowCli(apiUrl, homeDir, ['workflows', 'run', workflowId, '--idempotency-key', `${workflowId}-incomplete`, '--json']);
   expect(rejected.code).not.toBe(0);
   expect(`${rejected.stdout}\n${rejected.stderr}`).toMatch(/location|required|input/i);

   const complete = writeWorkflowYaml(homeDir, 'complete.yml', source('{location: Berlin, days: 1, timezone: Europe/Berlin}'));
   const updated = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'update', workflowId, '--file', complete], 'save complete');
   expect(updated.validation.enable_ready).toBe(true);
   expect(updated.workflow.enabled).toBe(false);
   expect(updated.workflow.icon).toBe('cloud-rain');
   const key = `${workflowId}-manual`;
   const accepted = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'run', workflowId, '--idempotency-key', key], 'manual run while disabled');
   const completed = await waitForWorkflowRunStatus(apiUrl, homeDir, workflowId, accepted.id, ['completed'], 'Berlin weather run');
   expect(completed.node_runs.find((n: any) => n.node_id === 'forecast')?.status).toBe('completed');
   expect(typeof completed.node_runs.find((n: any) => n.node_id === 'rain_check')?.output_summary.matched).toBe('boolean');
   expect(completed.node_runs.find((n: any) => n.node_id === 'report')?.output_summary.delivery_id).toBeTruthy();
   await waitForChatTitle(apiUrl, homeDir, chatTitle, 120_000);
   const retry = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'run', workflowId, '--idempotency-key', key], 'idempotent run retry');
   expect(retry.id).toBe(accepted.id);
   const enabled = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'enable', workflowId], 'enable schedule');
   expect(enabled.enabled).toBe(true);
   await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'disable', workflowId], 'disable schedule');
   const deleted = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'run-delete', workflowId, accepted.id, '--yes'], 'delete run');
   expect(deleted.status).toBe('deleted');
   const runs = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'runs', workflowId], 'remaining runs');
   expect(runs.some((r: any) => r.id === accepted.id)).toBe(false);
   await waitForChatTitle(apiUrl, homeDir, chatTitle, 30_000);
  } finally {
   await deleteWorkflowQuietly(apiUrl, homeDir, workflowId);
   removeWorkflowCliHome(homeDir);
  }
 });
});
