// frontend/packages/ui/src/components/embeds/code/testResultFixtures.ts
//
// Shared decoded-content fixtures for the test result embed component previews.
// Evidence URLs point at static dev fixtures served by the web app.

const FIXTURE_BASE = '/dev-fixtures/test-result';

export const fixtureEvidenceUrl = async (assetId: string): Promise<string | null> => {
  if (assetId.startsWith('asset-video')) return `${FIXTURE_BASE}/run.webm`;
  if (assetId.startsWith('asset-frame')) return `${FIXTURE_BASE}/frame.png`;
  return null;
};

const browserSteps = (failedLast: boolean) => [
  { name: 'Open sign-in page', start_ms: 0, end_ms: 2000, status: 'passed', is_preview: false },
  { name: 'Enter credentials', start_ms: 2000, end_ms: 4000, status: 'passed', is_preview: false },
  { name: 'Submit form', start_ms: 4000, end_ms: 6000, status: 'passed', is_preview: true },
  {
    name: 'Dashboard is visible', start_ms: 6000, end_ms: 8000,
    status: failedLast ? 'failed' : 'passed', is_preview: false,
    ...(failedLast ? { error: 'Expected element [data-testid=dashboard] to be visible' } : {}),
  },
];

const browserEvidence = [
  { kind: 'video', path: 'artifacts/run.webm', mime_type: 'video/webm', size_bytes: 122700, asset_id: 'asset-video-1' },
  { kind: 'preview_frame', path: 'artifacts/frame.png', mime_type: 'image/png', size_bytes: 2452, asset_id: 'asset-frame-1', at_step: 2 },
];

const base = {
  exit_code: 0,
  skipped: 0,
  revisions: [{ path: 'src/login.ts', revision: 'rev-1' }],
  tested_embed_ids: ['embed-code-1'],
  is_current: true,
};

export const browserPassed = {
  ...base, kind: 'browser', target: 'e2e/login.spec.ts', run_status: 'passed', duration_ms: 8000,
  passed: 4, failed: 0, preview_step_index: 2, steps: browserSteps(false), evidence: browserEvidence, tests: [],
};

export const browserFailed = {
  ...base, kind: 'browser', target: 'e2e/login.spec.ts', run_status: 'failed', exit_code: 1, duration_ms: 8000,
  passed: 3, failed: 1, preview_step_index: 3, steps: browserSteps(true), evidence: browserEvidence, tests: [],
  error: '1 step failed',
};

export const browserNoFrame = { ...browserPassed, evidence: [] };

export const cliResult = {
  ...base, kind: 'cli', target: 'cargo test -p openmates-sdk', run_status: 'failed', exit_code: 101, duration_ms: 4200,
  passed: 1, failed: 1, evidence: [], tests: [],
  steps: [
    { name: 'Build', start_ms: 0, end_ms: 1500, status: 'passed', is_preview: false, command: 'cargo build -p openmates-sdk', output: 'Compiling openmates-sdk v0.1.0\n    Finished dev [unoptimized] target(s) in 1.4s' },
    { name: 'Test', start_ms: 1500, end_ms: 4200, status: 'failed', is_preview: false, command: 'cargo test -p openmates-sdk', output: 'running 2 tests\ntest parse_ok ... ok\ntest parse_bad ... FAILED', error: 'assertion failed: left == right' },
  ],
};

export const unitResult = {
  ...base, kind: 'unit', target: 'tests/test_parser.py', run_status: 'failed', exit_code: 1, duration_ms: 950,
  passed: 2, failed: 1, skipped: 1, steps: [], evidence: [],
  tests: [
    { name: 'test_parse_simple', status: 'passed', duration_ms: 12 },
    { name: 'test_parse_nested', status: 'passed', duration_ms: 20 },
    { name: 'test_parse_invalid', status: 'failed', duration_ms: 31, error: 'AssertionError: expected ParseError, got None' },
    { name: 'test_parse_slow', status: 'skipped' },
  ],
};

export const staleResult = {
  ...browserPassed, is_current: false, stale_reason: 'src/login.ts changed after this run',
};
