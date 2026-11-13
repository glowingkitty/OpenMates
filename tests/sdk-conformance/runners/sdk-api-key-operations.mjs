/**
 * Actual public npm API-key operations and public helpers against the shared vectors.
 * Gate capabilities: sdk.api-key-operations.v1, sdk.api-key-domains-b.v1 (fake fetch,
 * no network) and sdk.public-utilities-helpers.v1 (pure functions).
 */
// contract-test-file: tooling
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';

const camel = name => name.replace(/_([a-z])/g, (_, letter) => letter.toUpperCase());

/** Maps the language-neutral vector (snake_case kwargs) onto the npm method signature. */
const ADAPTERS = {
  'billing.usage_details': (_args, kwargs) => [{ type: kwargs.type, identifier: kwargs.identifier, yearMonth: kwargs.year_month }],
  'billing.request_refund': (args, kwargs, vector) => [...args, { confirmed: vector.confirmed ?? kwargs.confirmed ?? true }],
  'reminders.delete': (args, kwargs, vector) => [...args, { confirmed: vector.confirmed ?? kwargs.confirmed ?? true }],
  'settings.set_model_defaults': (_args, kwargs) => [kwargs],
  'learning_mode.collaborative': (args, kwargs) => [{ enabled: args[0], passcode: kwargs.passcode }],
};

function callArguments(vector) {
  const adapter = ADAPTERS[vector.operation];
  if (adapter) return adapter(vector.args, vector.kwargs, vector);
  return [...vector.args, ...(Object.keys(vector.kwargs).length ? [Object.fromEntries(Object.entries(vector.kwargs).map(([k, v]) => [camel(k), v]))] : [])];
}

export async function runOperationVectors(suite, sdkModule) {
  const results = [];
  for (const vector of suite.vectors) {
    const calls = [];
    const previous = globalThis.fetch;
    globalThis.fetch = async (input, init) => {
      const url = new URL(String(input));
      calls.push({ method: init?.method, path: url.pathname + url.search, body: init?.body === undefined ? null : JSON.parse(init.body), authorization: new Headers(init?.headers).get('authorization') });
      return new Response(JSON.stringify({ ok: true }), { status: 200, headers: { 'content-type': 'application/json' } });
    };
    try {
      const client = new sdkModule.OpenMates({ apiKey: 'sk-api-ops.synthetic-local-setup-secret', apiUrl: 'https://api.example.invalid', deviceId: 'ops-device' });
      const [namespace, method] = vector.operation.split('.');
      await client[camel(namespace)][camel(method)](...callArguments(vector));
    } finally {
      globalThis.fetch = previous;
    }
    assert.equal(calls.length, 1, vector.id);
    assert.deepEqual({ method: calls[0].method, path: calls[0].path, body: calls[0].body }, vector.expect, vector.id);
    assert.equal(calls[0].authorization, 'Bearer sk-api-ops', vector.id);
    results.push({ id: vector.id, status: 'passed' });
  }
  return results;
}

/** SDK-B memories fixture: decrypt shared ciphertexts, key hashing and wrapped chat key. */
export async function runMemoryVectors(fixture, cryptoModule, sdkCrypto) {
  const key = new Uint8Array(Buffer.from(fixture.master_key_b64, 'base64'));
  const results = [];
  for (const vector of fixture.vectors) {
    assert.equal(await cryptoModule.decryptWithAesGcmCombined(vector.ciphertext, key), vector.plaintext, vector.name);
    const rewritten = await cryptoModule.encryptWithAesGcmCombined(vector.plaintext, key);
    assert.equal(await cryptoModule.decryptWithAesGcmCombined(rewritten, key), vector.plaintext, vector.name);
    results.push({ id: vector.name, status: 'passed' });
  }
  const realNow = Date.now;
  try {
    for (const entry of fixture.hashes) {
      Date.now = () => entry.millis;
      assert.equal(cryptoModule.hashItemKey(entry.app, entry.type), entry.hash, `${entry.app}/${entry.type}`);
      results.push({ id: `hash_${entry.app}_${entry.type}`, status: 'passed' });
    }
  } finally {
    Date.now = realNow;
  }
  const unwrapped = await sdkCrypto.decryptBytesWithAesGcm(fixture.wrapped_chat_key, key);
  assert.equal(Buffer.from(unwrapped).toString('base64'), fixture.chat_key_b64);
  results.push({ id: 'wrapped_chat_key', status: 'passed' });
  return results;
}

/**
 * Language-neutral projection of npm helper results: JSON has no `undefined`, so an
 * absent optional field compares as the fixture's `null`; npm's camelCase
 * `reportTitle` is the fixture's `report_title`. Values are never rewritten.
 */
function neutral(value) {
  if (value === undefined) return null;
  if (Array.isArray(value)) return value.map(neutral);
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).map(([key, entry]) => [key.replace(/[A-Z]/g, letter => '_' + letter.toLowerCase()), neutral(entry)]));
  }
  return value;
}

/** Pure public helpers exported from the npm package root. */
export function runHelperVectors(suite, indexModule) {
  const results = [];
  for (const vector of suite.vectors) {
    const helper = indexModule[camel(vector.function)];
    assert.equal(typeof helper, 'function', vector.id);
    if (vector.expect && typeof vector.expect === 'object' && vector.expect.error === 'invalid') {
      assert.throws(() => helper(...vector.args), Error, vector.id);
    } else {
      const actual = helper(...vector.args);
      const expected = vector.expect;
      const projected = expected && typeof expected === 'object'
        ? Object.fromEntries(Object.keys({ ...neutral(actual), ...expected }).map(key => [key, neutral(actual)?.[key] ?? null]))
        : neutral(actual);
      assert.deepEqual(projected, expected, vector.id);
    }
    results.push({ id: vector.id, status: 'passed' });
  }
  return results;
}

export const fixtureDigest = bytes => createHash('sha256').update(bytes).digest('hex');
