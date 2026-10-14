// contract-test-file: infrastructure
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { PreparedPrivacyCache, PREPARED_PRIVACY_IDLE_MS } from '../src/preparedPrivacy.js';
import { compileCliPrivacy, prepareCliMessagePrivacy } from '../src/privacyScan.js';
import type { DecryptedMemoryEntry } from '../src/client.js';

const memories = [{ id: 'private-value', app_id: 'privacy', item_type: 'personal_data_entry', data:
  { enabled: true, textToHide: 'Harriet Finch', replaceWith: 'PERSON', addressLines: { street: '14 Sample Road' } } },
  { id: 'categories', app_id: 'privacy', item_type: 'pii_detection_settings', data: { categories: { email_addresses: false } } }] as DecryptedMemoryEntry[];

// contract-test: supporting surface=cli assertions=ai-model-routing.preprocessing.prepared-privacy
 test('prepared privacy retains compiled real entries with sliding expiry and exact scope/preferences binding', () => {
  let now = 1;
  const cache = new PreparedPrivacyCache(() => now);
  cache.set('account-api-session-device-team-key', 'prefs-a', 'generation-a', memories);
  const first = cache.get('account-api-session-device-team-key', 'prefs-a');
  assert.ok(first);
  assert.deepEqual(first.privacy.matchPersonal('HARRIET FINCH at 14 Sample Road').map(range => [range.start, range.end]), [[0, 13], [17, 31]]);
  now += PREPARED_PRIVACY_IDLE_MS - 1;
  assert.equal(cache.get(first.ownerKey, first.preferencesKey), first, 'valid activity extends retention');
  now += PREPARED_PRIVACY_IDLE_MS;
  assert.equal(cache.get(first.ownerKey, first.preferencesKey), null);
  cache.set(first.ownerKey, first.preferencesKey, 'generation-b', memories);
  assert.equal(cache.get(first.ownerKey, 'prefs-b'), null);
  cache.set(first.ownerKey, first.preferencesKey, 'generation-b', memories);
  assert.equal(cache.get('different-team-or-key', first.preferencesKey), null);
  cache.set(first.ownerKey, first.preferencesKey, null, memories);
  assert.equal(cache.get(first.ownerKey, first.preferencesKey), null, 'missing authoritative generation cannot certify reuse');
  cache.set(first.ownerKey, first.preferencesKey, 'generation-c', memories); cache.clear();
  assert.equal(cache.get(first.ownerKey, first.preferencesKey), null);
 });

// contract-test: supporting surface=cli assertions=ai-model-routing.preprocessing.prepared-privacy
 test('compiled personal values preserve configured detector policy and reversible encrypted mapping input', async () => {
  const compiled = compileCliPrivacy(memories);
  const prepared = await prepareCliMessagePrivacy('Harriet Finch lives at 14 Sample Road; contact public@example.org', memories, [], { kind: 'message' }, undefined, compiled);
  assert.equal(prepared.message.includes('Harriet Finch'), false);
  assert.equal(prepared.message.includes('14 Sample Road'), false);
  assert.equal(prepared.message.includes('public@example.org'), true, 'disabled email category stays disabled');
  assert.deepEqual(prepared.mappings.map(mapping => mapping.original), ['Harriet Finch', '14 Sample Road']);
 });
