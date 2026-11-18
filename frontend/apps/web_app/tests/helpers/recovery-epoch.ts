/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Open recovery protocol epoch one on the disposable isolated CI stack, as dev
 * and production run it. A fresh stack starts at epoch zero (legacy turns), so
 * marker-chat specs that prove the real send path call this in beforeAll.
 * The spec must be listed in MARKER_CHAT_EPOCH_SPECS (scripts/ci_run_tests.py).
 */
const { expect } = require('@playwright/test');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '../../../../..');

// New spec registration is candidate source, while the runner harness remains
// separately frozen. Reuse its existing guarded transition from this candidate
// so this regression always exercises recovery, even before registration lands.
export function ensureIsolatedRecoveryEpoch(specName: string): void {
  expect(process.env.GITHUB_ACTIONS).toBe('true');
  expect(process.env.RUNNER_ENVIRONMENT).toBe('github-hosted');
  const compose = path.join(root, 'test-results/ci-private/compose.json');
  const profile = JSON.parse(fs.readFileSync(compose, 'utf8'));
  expect(profile.networks.default.internal).toBe(true);
  expect(profile.services.api.environment.OPENMATES_CI_ISOLATED).toBe('1');
  expect(profile.services.api.environment.OPENMATES_CI_AI_FIXTURES).toBe('1');
  const probe = `
import asyncio,json,logging,os
logging.disable(logging.CRITICAL)
assert os.getenv('OPENMATES_CI_ISOLATED') == '1' and os.getenv('MOCK_EXTERNAL_APIS') == 'true'
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.chat_recovery_cutover import ChatRecoveryCutoverController
async def main():
    cache=CacheService(); directus=DirectusService(cache_service=cache)
    try:
        print(json.dumps(await ChatRecoveryCutoverController(cache,directus).get_state(authoritative=True)))
    finally:
        await directus.close(); await cache.close()
asyncio.run(main())
`;
  const readState = () => JSON.parse(execFileSync('docker', ['compose', '-f', compose, 'exec', '-T',
    'api', 'python', '-c', probe], { cwd: root, encoding: 'utf8', timeout: 60_000 }).trim().split('\n').at(-1));
  let state = readState();
  if (state.protocol_epoch === 0) {
    execFileSync('python3', ['-c',
      `import sys; sys.path.insert(0, 'scripts'); from ci_run_tests import activate_isolated_marker_chat_epoch; activate_isolated_marker_chat_epoch(${JSON.stringify(specName)})`],
    { cwd: root, env: { ...process.env, OPENMATES_CI_SOURCE_ROOT: root }, encoding: 'utf8', timeout: 90_000 });
    state = readState();
  }
  expect(state).toEqual({ protocol_epoch: 1, sends_paused: false, legacy_in_flight: 0 });
}
