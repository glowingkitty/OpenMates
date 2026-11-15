// Parity vectors for the two display helpers the page still owns
// (appSettingsRequestPolicy.ts: formatDisplayName, getAppGradient). The committed
// JSON (packages/openmates-rust/src/web_settings_ts_vectors.json) is replayed by
// the Rust unit tests (web_settings_tests.rs) against web_settings.rs; category
// plans, the answered guard and the request message are decided only by the Rust
// settings unit, so they have no TypeScript twin to check here.
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { formatDisplayName, getAppGradient } from '../../appSettingsRequestPolicy';

const VECTORS = resolve(__dirname, '../../../../../../../packages/openmates-rust/src/web_settings_ts_vectors.json');
const vectors = JSON.parse(readFileSync(VECTORS, 'utf8'));

describe('settings display helper vectors', () => {
  // contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
  it('keeps display names and gradients', () => {
    for (const c of vectors.displayName) expect(formatDisplayName(c.in)).toBe(c.out);
    for (const c of vectors.gradient) expect(getAppGradient(c.in)).toBe(c.out);
  });
});
