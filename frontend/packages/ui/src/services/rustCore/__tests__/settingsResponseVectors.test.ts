// contract-test-file: tooling
// spec: specifications/surfaces/sdk#sdk.client.thin-platform-boundary
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  confirmOutcome, planSelectedKeys, responseCategories, responseContent, selectEntryIds,
} from '../../appSettingsResponsePolicy';

const VECTORS = resolve(__dirname, '../../../../../../../packages/openmates-rust/src/web_settings_response_ts_vectors.json');
const vectors = JSON.parse(readFileSync(VECTORS, 'utf8'));
const json = (value: unknown) => JSON.parse(JSON.stringify(value));

describe('settings response policy vectors', () => {
  it('keeps key routing and entry selection', () => {
    for (const c of vectors.keys) expect(json(planSelectedKeys(c.in))).toEqual(c.out);
    for (const c of vectors.select) expect(selectEntryIds(c.ids, c.sel)).toEqual(c.out);
  });

  it('keeps response categories, outcomes and content', () => {
    for (const c of [...vectors.categories, vectors.categoriesEmpty]) expect(json(responseCategories(c.cats, c.released))).toEqual(c.out);
    for (const c of vectors.outcomes) expect(confirmOutcome(c.n, c.voice, c.hasId)).toEqual(c.out);
    for (const c of vectors.content) expect(responseContent(c.u, c.action, c.categories ?? undefined)).toBe(c.out);
  });
});
