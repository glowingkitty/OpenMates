/* eslint-disable @typescript-eslint/no-require-imports */
// ci-profile: fresh_account
/** Actual first-party WS/Directus recovery with runner-only synthetic sealed jobs. */
export {};
const { test, expect } = require('@playwright/test');
const { execFile } = require('node:child_process');
const { promisify } = require('node:util');
const path = require('node:path');

// contract-test: direct surface=rest_api assertions=chats.persistence.client-encrypted,chats.message.identity-idempotent,chats.sync.key-gated-recovery
test('owner reconnect recovers encrypted metadata once and preserves a newer title edit', async () => {
  test.setTimeout(180000);
  const root = path.resolve(__dirname, '../../../..');
  const result = await promisify(execFile)(process.execPath,
    ['--experimental-strip-types', path.join(root, 'scripts/ci_chat_metadata_recovery.mjs'), root],
    { cwd: root, env: process.env, timeout: 150000, maxBuffer: 128 * 1024 });
  expect(JSON.parse(result.stdout)).toEqual({ discovery_after_disconnect: true, encrypted_commit: true,
    repeated_replay_idempotent: true, owner_edit_preserved: true, sealed_payload_removed: true,
    older_client_capability_guard: true, inference_calls: 0 });
});
