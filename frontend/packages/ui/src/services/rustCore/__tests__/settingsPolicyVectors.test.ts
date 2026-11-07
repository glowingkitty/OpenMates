// TS-generated parity vectors for the shared Rust settings request policy.
// The committed JSON (packages/openmates-rust/src/web_settings_ts_vectors.json)
// holds inputs plus the outcomes of the TypeScript policy
// (appSettingsRequestPolicy.ts) and appMemoryRequests.ts. This test fails if the
// TypeScript behaviour drifts from the vectors; the Rust unit tests
// (web_settings_tests.rs) replay the same file against web_settings.rs.
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  formatDisplayName, getAppGradient, isRequestAnswered, planRequestCategories,
} from '../../appSettingsRequestPolicy';
import { buildMemoryRequestMessage } from '../../../utils/appMemoryRequests';

const VECTORS = resolve(__dirname, '../../../../../../../packages/openmates-rust/src/web_settings_ts_vectors.json');
const vectors = JSON.parse(readFileSync(VECTORS, 'utf8'));
const json = (value: unknown) => JSON.parse(JSON.stringify(value));

describe('settings request policy vectors', () => {
  // contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
  it('keeps display names, gradients and category plans', () => {
    for (const c of vectors.displayName) expect(formatDisplayName(c.in)).toBe(c.out);
    for (const c of vectors.gradient) expect(getAppGradient(c.in)).toBe(c.out);
    for (const c of vectors.plans) expect(json(planRequestCategories(c.keys, new Map(Object.entries(c.counts))))).toEqual(c.out);
  });

  // contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
  it('keeps the answered guard', () => {
    for (const c of vectors.answered) expect(isRequestAnswered(c.contents, c.id)).toBe(c.out);
  });

  // contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
  it('keeps the persisted request message', () => {
    for (const c of vectors.requests) {
      let outcome: unknown;
      try {
        outcome = { kind: 'ok', message: json(buildMemoryRequestMessage({
          userMessageId: c.u, requestId: c.r, requestedKeys: c.keys, createdAt: c.at,
          entryCounts: new Map(Object.entries(c.counts)), responseTransport: c.voice ? 'voice' : undefined,
        })) };
      } catch (error) {
        outcome = { kind: 'error', message: (error as Error).message };
      }
      expect(outcome).toEqual(c.out);
    }
  });
});
