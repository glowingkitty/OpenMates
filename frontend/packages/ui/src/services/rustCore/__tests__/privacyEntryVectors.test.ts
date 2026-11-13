// contract-test-file: tooling
// spec: specifications/surfaces/sdk#sdk.client.thin-platform-boundary
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { planPrivacyEntry } from '../../privacyEntryPolicy';

const VECTORS = resolve(__dirname, '../../../../../../../packages/openmates-rust/src/web_settings_privacy_ts_vectors.json');
const vectors = JSON.parse(readFileSync(VECTORS, 'utf8'));
const json = (value: unknown) => JSON.parse(JSON.stringify(value));

describe('privacy entry policy vectors', () => {
  it('keeps the hydration defaults per item type', () => {
    for (const c of vectors.cases) expect(json(planPrivacyEntry(c.type, c.data, vectors.defaults))).toEqual(c.out);
  });

  it('throws on null data for known item types', () => {
    for (const type of vectors.nullDataThrows) expect(() => planPrivacyEntry(type, null, vectors.defaults)).toThrow();
  });
});
