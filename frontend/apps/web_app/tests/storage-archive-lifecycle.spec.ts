/** Account-free personal and Team archive lifecycle probe on the existing isolated storage profile. */
import { createHash, randomBytes, randomUUID } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { realpathSync } from 'node:fs';
import { createRequire } from 'node:module';
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

// contract-test: direct surface=rest_api assertions=tasks.content.client-encrypted,tasks.lifecycle.visible,cli.slugs.encrypted-stable
// eslint-disable-next-line no-empty-pattern -- The probe uses an authenticated socket and no browser.
test('generated Task create job persists an encrypted slug over authenticated WebSocket', async ({}) => {
  test.setTimeout(120_000);
  const compose = process.env.E2E_STORAGE_TEAM_COMPOSE_FILE || '';
  const source = process.env.E2E_STORAGE_TEAM_SOURCE_COMMIT || '';
  if (process.env.E2E_STORAGE_CAPACITY !== '1' || !/^[0-9a-f]{40}$/.test(source)
      || !compose || !realpathSync(compose).includes('/ci-private/')) {
    throw new Error('task_job_ws_isolated_source_profile_required');
  }
  const WebSocket = createRequire(realpathSync('../../packages/openmates-cli/package.json'))('ws');
  type Fixture = Record<string, unknown>;
  const runFixture = (mode: 'prepare' | 'verify' | 'cleanup', fixture?: Fixture): Fixture => {
    const runner = [
      'import os,sys,runpy,json',
      'if os.getenv("BUILD_COMMIT_SHA") != sys.argv[1]:',
      ' print(json.dumps({"passed":False,"stage":"source_guard"}));sys.exit(1)',
      'runpy.run_path("/app/scripts/storage_archive_integration.py", run_name="__main__")',
    ].join('\n');
    const result = spawnSync('docker', [
      'compose', '-f', compose, 'exec', '-T',
      '-e', 'OPENMATES_CI_ARCHIVE_LIFECYCLE_PROBE=1',
      '-e', `OPENMATES_CI_TASK_JOB_WS_PROBE=${mode}`,
      'api', 'python', '-c', runner, source,
    ], { input: fixture ? JSON.stringify(fixture) : '', encoding: 'utf8', timeout: 45_000, maxBuffer: 64 * 1024 });
    const raw = result.stdout?.trim().split(/\r?\n/).at(-1) || '';
    let receipt: Fixture | undefined;
    try {
      const parsed: unknown = JSON.parse(raw);
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) receipt = parsed as Fixture;
    } catch { /* Fixture output stays private. */ }
    if (result.error || result.status !== 0 || result.signal || !receipt) {
      throw new Error(`task_job_ws_fixture_${mode}_failed`);
    }
    return receipt;
  };
  const fixture = runFixture('prepare');
  const identities = Object.fromEntries(
    ['user_id', 'chat_id', 'task_id', 'job_id', 'session_hash'].map(key => [key, fixture[key]]),
  );
  let socket: InstanceType<typeof WebSocket> | undefined;
  try {
    const query = new URLSearchParams({
      sessionId: String(fixture.session_id), token: String(fixture.ws_token),
      client_capabilities: 'task_update_jobs,agentic-storage-v2',
    });
    socket = new WebSocket(`ws://localhost:8000/v1/ws?${query}`, {
      headers: { Origin: 'http://localhost:5173', 'User-Agent': String(fixture.user_agent) },
    });
    await new Promise<void>((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error('task_job_ws_connect_timeout')), 15_000);
      socket!.once('open', () => { clearTimeout(timeout); resolve(); });
      socket!.once('error', (error: Error) => { clearTimeout(timeout); reject(error); });
      socket!.once('close', () => { clearTimeout(timeout); reject(new Error('task_job_ws_auth_rejected')); });
    });
    const exchange = async (payload: Record<string, unknown>): Promise<Record<string, unknown>> => {
      const request_id = randomUUID();
      const response = new Promise<Record<string, unknown>>((resolve, reject) => {
        const timeout = setTimeout(() => {
          socket!.off('message', onMessage);
          reject(new Error('task_job_ws_receipt_timeout'));
        }, 15_000);
        const onMessage = (bytes: Buffer) => {
          let frame: Record<string, unknown>;
          try { frame = JSON.parse(bytes.toString()) as Record<string, unknown>; } catch { return; }
          if (frame.type === 'ping') {
            socket!.send(JSON.stringify({ type: 'pong', payload: {} }));
            return;
          }
          const body = frame.payload as Record<string, unknown> | undefined;
          if (body?.request_id === request_id) {
            clearTimeout(timeout);
            socket!.off('message', onMessage);
            resolve(frame);
          }
        };
        socket!.on('message', onMessage);
      });
      socket!.send(JSON.stringify({ type: 'task_update_job_persist', payload: {
        protocol_version: 1, job_id: fixture.job_id,
        lease_token: fixture.lease_token, lease_generation: 1,
        expected_task_version: 0, encrypted_task_event_message: 'fixture-cipher-event',
        encrypted_task_payload: payload, request_id,
      } }));
      return response;
    };
    const accepted = fixture.encrypted_task_payload as Record<string, unknown>;
    for (const field of ['plaintext_title', 'plaintext_description']) {
      const denied = await exchange({ ...accepted, [field]: 'synthetic private text' });
      expect(denied.type).toBe('error');
      expect((denied.payload as Record<string, unknown>).code).toBe('ValueError');
    }
    const persisted = await exchange(accepted);
    expect(persisted.type).toBe('task_update_job_persisted');
    expect((persisted.payload as Record<string, unknown>).state).toBe('TASK_PERSISTED');
    const verified = runFixture('verify', identities);
    expect(verified.task_job_ws_persisted_slug_hash).toBe(true);
    expect(verified.source_commit).toBe(source);
  } finally {
    socket?.close();
    const cleaned = runFixture('cleanup', identities);
    expect(cleaned.task_job_fixture_cleanup_verified).toBe(true);
  }
});
