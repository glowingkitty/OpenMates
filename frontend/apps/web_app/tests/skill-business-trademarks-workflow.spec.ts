/* eslint-disable @typescript-eslint/no-require-imports */
/** Real keyless trademark searches and typed downstream values in Workflows. */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { runCli, deriveApiUrl } = require('./helpers/cli-test-helpers');
const { createWorkflowCliHome, removeWorkflowCliHome, writeWorkflowYaml } = require('./helpers/workflow-cli-e2e-helpers');
const fs = require('node:fs');
const { spawnSync } = require('node:child_process');

const apiUrl = process.env.PLAYWRIGHT_TEST_API_URL || deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
const cliOptions = { useApiKey: false, record: false, env: { OPENMATES_API_KEY: undefined } };

async function cli(args: string[], label: string, timeoutMs = 90_000): Promise<any> {
  const result = await runCli(apiUrl, [...args, '--json'], timeoutMs, cliOptions);
  expect(result.code, `${label}: ${(result.stderr || result.stdout).slice(-1500)}`).toBe(0);
  return JSON.parse(result.stdout);
}

function assertEvidence(output: any): void {
  expect(output.app_id).toBe('business');
  expect(output.skill_id).toBe('search_trademarks');
  expect(output.raw.success).toBe(true);
  expect(output.matches.length).toBeGreaterThan(0);
  expect(output.matches.length).toBeLessThanOrEqual(2);
  expect(output.result_count).toBe(output.matches.length);
  expect(output.regions).toEqual(['US', 'EU']);
  expect(output.nice_classes).toEqual([25]);
  expect(output.status_filter).toBe('active');
  expect(output.match).toBe('exact');
  expect(output.partial).toBe(true);
  expect(output.matches).toEqual(output.raw.matches);
  expect(output.coverage).toEqual(output.raw.coverage);
  expect(output.coverage.map((row: any) => row.status)).toEqual(['searched', 'unsupported']);
  expect(output.coverage[0].checked_at).toEqual(expect.any(String));
  expect(output.coverage[0].returned_count).toBe(output.matches.length);
  expect(output.coverage[1].source_url).toMatch(/^https:\/\//);
  expect(output.limitation).toContain('legal availability');
  for (const record of output.matches) {
    expect(record.mark.toUpperCase()).toBe('ADIDAS');
    expect(record.nice_classes).toContain(25);
    expect(record.source_url).toMatch(/^https:\/\/tsdr\.uspto\.gov\/#caseNumber=\d+/);
    expect(record).not.toHaveProperty('ownerAddress');
  }
}

test.describe('Business / Search trademarks in Workflows', () => {
  test.setTimeout(300_000);

  // contract-test: direct surface=cli assertions=trademarks.request,trademarks.coverage,trademarks.evidence,trademarks.parity
  test('step-tests and runs real searches with partial coverage, zero matches and typed downstream checks', async ({ request }: any, testInfo: any) => {
    for (const args of [
      ['apt-get', 'install', '-y', 'xvfb', 'zutty', 'xdotool', 'ffmpeg', 'fonts-dejavu', 'libgl1-mesa-dri', 'x11-xserver-utils'],
      ['update-alternatives', '--set', 'x-terminal-emulator', '/usr/bin/zutty']
    ]) {
      const setup = spawnSync('sudo', args, { encoding: 'utf8', timeout: 150_000 });
      expect(setup.status, `Runner CLI recording setup: ${setup.stderr?.slice(-1500)}`).toBe(0);
    }
    const folder = createWorkflowCliHome('trademark-workflow');
    let workflowId: string | undefined;
    try {
      expect((await request.get(apiUrl + '/health')).ok()).toBe(true);
      const capabilities = await cli(['workflows', 'capabilities'], 'Capability discovery');
      const trademark = capabilities.find((item: any) => item.id === 'business.search_trademarks');
      expect(trademark?.enabled).toBe(true);
      expect(trademark.metadata.workflow).toMatchObject({
        available: true, execution_mode: 'sync', effect: 'read', unattended: true,
        approval: 'never', test_allowed: true
      });
      expect(trademark.metadata.output_schema.properties.matches.type).toBe('array');
      expect(trademark.metadata.output_schema.properties.coverage.type).toBe('array');
      const yaml = writeWorkflowYaml(folder, 'trademarks.yml', `
title: Trademark workflow fixture ${Date.now()}
start_when:
  manual: {}
steps:
  - id: marks
    use_app_skill: business.search_trademarks
    input:
      queries: [ADIDAS]
      regions: [US, EU]
      nice_classes: [25]
      match: exact
      max_results: 2
  - id: count
    check:
      left: $nodes.marks.output.result_count
      op: gt
      right: 0
  - id: partial
    check:
      left: $nodes.marks.output.partial
      op: eq
      right: true
  - id: zero
    use_app_skill: business.search_trademarks
    input:
      queries: [OpenMatesWorkflowNoMark${Date.now()}QZX]
      regions: [US]
      match: exact
      max_results: 1
  - id: empty
    check:
      left: $nodes.zero.output.result_count
      op: eq
      right: 0
  - id: report
    send_chat_message:
      title: Trademark workflow fixture
      message: "Records: {{steps.marks.result_count}}. Coverage: {{steps.marks.coverage}}. {{steps.marks.limitation}}"
`);
      const created = await cli(['workflows', 'create', '--file', yaml], 'Workflow creation');
      workflowId = created.workflow.id;
      expect(created.workflow.enabled).toBe(false);
      expect(created.validation.enable_ready).toBe(true);
      const stepTest = await cli(['workflows', 'step-test', workflowId!, 'marks', '--yes'], 'Step test');
      expect(stepTest.status).toBe('completed');
      expect(stepTest.trigger_type).toBe('step_test');
      assertEvidence(stepTest.node_runs.find((node: any) => node.node_id === 'marks').output_summary);
      const accepted = await cli(['workflows', 'run', workflowId!, '--idempotency-key', `${workflowId}-trademarks`], 'Workflow run');
      let completed: any;
      await expect(async () => {
        completed = await cli(['workflows', 'run-show', workflowId!, accepted.id], 'Workflow status', 30_000);
        expect(['completed', 'failed', 'cancelled']).toContain(completed.status);
      }).toPass({ timeout: 120_000, intervals: [1_000, 2_000, 5_000] });
      expect(completed.status).toBe('completed');
      assertEvidence(completed.node_runs.find((node: any) => node.node_id === 'marks').output_summary);
      for (const id of ['count', 'partial', 'empty']) {
        expect(completed.node_runs.find((node: any) => node.node_id === id).output_summary.matched).toBe(true);
      }
      const zero = completed.node_runs.find((node: any) => node.node_id === 'zero').output_summary;
      expect(zero.raw.success).toBe(true);
      expect(zero.matches).toEqual([]);
      expect(zero.result_count).toBe(0);
      expect(zero.partial).toBe(false);
      expect(zero.coverage[0].status).toBe('searched');
      const report = completed.node_runs.find((node: any) => node.node_id === 'report');
      expect(report.status).toBe('completed');
      expect(report.output_summary.delivery_id).toEqual(expect.any(String));
      const recorded = await runCli(apiUrl, ['workflows', 'run-show', workflowId!, accepted.id, '--json'], 60_000, {
        useApiKey: false, record: true, env: { OPENMATES_API_KEY: undefined,
          OPENMATES_CLI_RECORD_E2E: '1', OPENMATES_E2E_SPEC: 'skill-business-trademarks-workflow.spec.ts',
          LIBGL_ALWAYS_SOFTWARE: 'true', GALLIUM_DRIVER: 'llvmpipe' }
      });
      expect(recorded.recording, 'Real CLI workflow recording required').toBeTruthy();
      expect(fs.existsSync(recorded.recording.videoPath)).toBe(true);
      await testInfo.attach('trademark-workflow-cli', { path: recorded.recording.videoPath, contentType: 'video/mp4' });
      await testInfo.attach('trademark-workflow-cli-manifest', { path: recorded.recording.manifestPath, contentType: 'application/json' });
      expect(recorded.code, recorded.stderr.slice(-1500)).toBe(0);
      expect(JSON.parse(recorded.stdout).status).toBe('completed');
    } finally {
      if (workflowId) {
        const cleanup = await runCli(apiUrl, ['workflows', 'delete', workflowId, '--yes', '--json'], 30_000, cliOptions);
        expect(cleanup.code, 'Disposable workflow cleanup').toBe(0);
      }
      removeWorkflowCliHome(folder);
    }
  });
});
