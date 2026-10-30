import { test, expect } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import path from 'node:path';

const ROOT = path.resolve(__dirname, '../../../..');
// contract-test-file: infrastructure
// contract-test: infrastructure
test('observes harmless kernel memory and owned container cleanup', async () => {
  const testInfo = test.info();
  test.setTimeout(180_000);
  const filename = path.join(ROOT, 'test-results/ci-client-memory-readiness.json');
  try {
    execFileSync('python3', ['-m', 'scripts.ci_client_memory_probe'], {
      cwd: ROOT, timeout: 160_000, stdio: 'pipe',
      env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1', PYTHONPATH: `${ROOT}:${path.join(ROOT, 'scripts')}` }
    });
  } finally {
    // Partial failures are evidence too; preserve the existing runner's failure.
    try { await testInfo.attach('harmless-memory-readiness', { body: readFileSync(filename), contentType: 'application/json' }); } catch { /* no receipt if admission refused before work */ }
  }
  const report = JSON.parse(readFileSync(filename, 'utf8'));
  expect(report.status).toBe('observed');
  expect(report.acceptanceEligible).toBe(false);
  expect(report.attempts.map((row: any) => row.fixture)).toEqual(['leaf', 'threads', 'child', 'node-threads']);
  for (const row of report.attempts) {
    expect(row.status).toBe('observed');
    expect(row.cleanupVerified).toBe(true);
    expect(row.collection.metric).toBe('kernel-total-container-memory-not-rss');
    expect(row.collection.memory.applicationLifetimeContainerPeakBytes).toBeGreaterThan(0);
  }
});

// contract-test: infrastructure
test('verifies contained harmless kernel admission and complete cleanup', async () => {
  test.setTimeout(420_000);
  const filename = path.join(ROOT, 'test-results/ci-client-contained-readiness.json');
  try {
    execFileSync('python3', ['-m', 'scripts.ci_client_contained_probe'], {
      cwd: ROOT, timeout: 400_000, stdio: 'pipe',
      env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1', PYTHONPATH: `${ROOT}:${path.join(ROOT, 'scripts')}` }
    });
  } finally {
    try { await test.info().attach('contained-harmless-readiness', { body: readFileSync(filename), contentType: 'application/json' }); } catch { /* pre-admission failure has no receipt */ }
  }
  const report = JSON.parse(readFileSync(filename, 'utf8'));
  expect(report.status).toBe('verified-harmless-cases');
  expect(report.acceptanceEligible).toBe(false);
  expect(report.currentMigrationAcceptance).toBe(false);
  expect(report.multiprocessTotalRss).toBe('unavailable');
  expect(report.cases.map((row: any) => row.case)).toEqual(['leaf', 'threads', 'late-worker', 'child', 'clone3', 'clone3-error', 'clone3-untraced', 'untraced', 'node-threads', 'long-lived', 'crash', 'cancel', 'deadline', 'controller-disconnect']);
  for (const row of report.cases) {
    expect(row.status).toBe('verified-harmless-case');
    expect(row.cleanupVerified).toBe(true);
    expect(row.collection.cleanupVerified).toBe(true);
  }
  expect(report.cases[0].negativeKernelGates.observationBoundary).toBe('authenticated-pid1-only-before-go-no-application-fork');
  expect(report.cases[0].negativeKernelGates.cases.map((row: any) => row.case)).toEqual(['non-socket', 'duplicate-channel', 'wrong-peer', 'wrong-namespace-type', 'non-namespace', 'extra-fd', 'named-channel']);
  for (const row of report.cases[0].negativeKernelGates.cases) {
    expect(row.status).toBe('refused-before-measured-fork');
    expect(row.returncode).toBe(125);
    expect(row.kernelGateFrames).toBe(0);
  }
});
