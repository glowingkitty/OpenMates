/** Account-free personal and Team archive lifecycle probe on the existing isolated storage profile. */
import { createHash, randomBytes } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { realpathSync } from 'node:fs';
import { expect, test } from '@playwright/test';
import { decryptWithAesGcmCombined, encryptWithAesGcmCombined } from '../../../packages/openmates-cli/src/crypto';

// contract-test: supporting surface=rest_api assertions=storage.cold.atomic-eligible-graphs,storage.rollout.verified-24-hour-buffer,storage.compression.incremental-archive,storage.cold.shared-team-authorized,storage.privacy.ciphertext-boundary

test.describe.configure({ retries: 0 });

// eslint-disable-next-line no-empty-pattern -- The probe uses no browser or account.
test('personal and Team ciphertext remains readable after source pruning', async ({}, testInfo) => {
  if (testInfo.retry !== 0) throw new Error('archive_lifecycle_single_attempt_required');
  test.setTimeout(300_000);
  const compose = process.env.E2E_STORAGE_TEAM_COMPOSE_FILE || '';
  const source = process.env.E2E_STORAGE_TEAM_SOURCE_COMMIT || '';
  if (process.env.E2E_STORAGE_CAPACITY !== '1' || !/^[0-9a-f]{40}$/.test(source)
      || !compose || !realpathSync(compose).includes('/ci-private/')) {
    throw new Error('archive_lifecycle_isolated_source_profile_required');
  }
  const key = randomBytes(32);
  const plaintexts = Array.from({ length: 20 }, (_, index) => `archive-lifecycle:${source}:${index}`);
  const ciphertexts = await Promise.all(plaintexts.map(text => encryptWithAesGcmCombined(text, key)));
  const runner = [
    'import os,sys,runpy,json',
    'if os.getenv("BUILD_COMMIT_SHA") != sys.argv[1]:',
    ' print(json.dumps({"passed":False,"stage":"source_guard","reason":"source_mismatch"}));sys.exit(1)',
    'try:',
    ' runpy.run_path("/app/scripts/storage_archive_integration.py", run_name="__main__")',
    'except Exception:',
    ' print(json.dumps({"passed":False,"stage":"probe_bootstrap","reason":"execution_failed"}));sys.exit(1)',
  ].join('\n');
  const result = spawnSync('docker', [
    'compose', '-f', compose, 'exec', '-T', '-e', 'OPENMATES_CI_ARCHIVE_LIFECYCLE_PROBE=1',
    'api', 'python', '-c', runner, source,
  ], { input: JSON.stringify(ciphertexts), encoding: 'utf8', timeout: 270_000, maxBuffer: 1024 * 1024 });
  const raw = result.stdout?.trim().split(/\r?\n/).at(-1) || '';
  let receipt: Record<string, unknown> | undefined;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) receipt = parsed as Record<string, unknown>;
  } catch { /* Failure output stays private. */ }
  if (result.error || result.status !== 0 || result.signal || !receipt || receipt.passed !== true) {
    const reason = (result.error as NodeJS.ErrnoException | undefined)?.code === 'ETIMEDOUT' ? 'process_timeout'
      : result.error ? 'docker_unavailable' : result.signal ? 'process_signal'
      : !receipt ? 'invalid_receipt' : 'probe_failed';
    await testInfo.attach('archive-lifecycle-safe-failure', {
      body: JSON.stringify({ passed: false, stage: 'docker_exec', reason }), contentType: 'application/json',
    });
    throw new Error(`archive_lifecycle_isolated_probe_failed:${reason}`);
  }
  expect(receipt.source_commit).toBe(source);
  expect(receipt.source_messages).toBe(20);
  expect(receipt.verified_pages).toBe(1);
  expect(receipt.pruned_messages).toBe(20);
  for (const flag of [
    'personal_archive_read_after_prune', 'team_archive_claim_read_prune',
    'reader_verified_before_activation', 'late_arrival_retained',
    'concurrent_prune_idempotent', 'pending_recovery_fence', 'source_mutation_fence',
  ]) expect(receipt[flag], flag).toBe(true);
  const returned = receipt.client_ciphertexts_after_prune;
  expect(Array.isArray(returned) && returned.length === 20 && returned.every(value => typeof value === 'string')).toBe(true);
  const digest = (values: string[]) => createHash('sha256').update(JSON.stringify(values)).digest('hex');
  expect(digest(returned as string[])).toBe(digest(ciphertexts));
  const decrypted = await Promise.all((returned as string[]).map(value => decryptWithAesGcmCombined(value, key)));
  expect(decrypted).toEqual(plaintexts);
  await testInfo.attach('archive-lifecycle-verified-receipt', {
    body: JSON.stringify({ source_commit: source, source_messages: 20, verified_pages: 1,
      pruned_messages: 20, personal_archive_read_after_prune: true,
      team_archive_claim_read_prune: true, client_decrypt_exact_ledger: true }),
    contentType: 'application/json',
  });
});
