// proof-video: not_required reason=non_visual_setup
import { execFileSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { expect, test } from '@playwright/test';

const root = path.resolve(__dirname, '../../../..');
const composeFile = path.join(root, 'test-results/ci-private/compose.json');

test.describe('Workflow authoring transaction on disposable Directus', () => {
  test.setTimeout(180_000);

  // contract-test: supporting surface=rest_api assertions=workflows.authoring.atomic-update
  test('commits two targets once and rolls back stale and guarded undo batches', () => {
    test.skip(process.env.GITHUB_ACTIONS !== 'true' || process.env.RUNNER_ENVIRONMENT !== 'github-hosted'
      || process.env.CI_TEST_MODE !== 'e2e',
      'Requires the runner-local isolated product stack');
    expect(existsSync(composeFile)).toBe(true);
    const output = execFileSync('docker', [
      'compose', '-f', composeFile, 'exec', '-T', '-e', 'CI=true',
      '-e', 'OPENMATES_CI_ISOLATED=1', 'api', 'python',
      '/app/backend/scripts/probe_workflow_authoring_transaction.py',
    ], { cwd: root, encoding: 'utf8', timeout: 150_000 });
    expect(output.trim()).toBe('real-db workflow authoring transaction passed');
  });
});
