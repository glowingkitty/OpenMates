/**
 * npm keyManagement / models facades (shared Rust core via the packaged WASM) against
 * the shared vectors. Gate capabilities sdk.key-management.primitives.v1 and
 * sdk.models.layout.v1. Pure library calls; every vector runs, unknown ops fail.
 */
// contract-test-file: tooling
import assert from 'node:assert/strict';

const hex = bytes => Buffer.from(bytes).toString('hex');
const fromHex = value => new Uint8Array(Buffer.from(value, 'hex'));

function refused(call, code) {
  assert.throws(call, error => error?.name === 'SessionClientError' && error.code === code);
}

function keyCase(keys, vector) {
  const key = vector.key_hex === undefined ? undefined : fromHex(vector.key_hex);
  switch (vector.op) {
    case 'encode_key': assert.equal(keys.encodeKey(key), vector.expect); break;
    case 'decode_key':
      if (vector.expect_error) refused(() => keys.decodeKey(vector.value), 'crypto');
      else assert.equal(hex(keys.decodeKey(vector.value)), vector.expect_hex);
      break;
    case 'key_fingerprint': assert.equal(hex(keys.keyFingerprint(key)), vector.expect_hex); break;
    case 'hash_email': assert.equal(keys.hashEmail(vector.email), vector.expect); break;
    case 'hash_key': assert.equal(keys.hashKey(vector.password, new Uint8Array(Buffer.from(vector.salt_b64, 'base64'))), vector.expect); break;
    case 'decrypt_combined':
      if (vector.expect_error) refused(() => keys.decryptCombined(vector.ciphertext, key), 'crypto');
      else assert.equal(keys.decryptCombined(vector.ciphertext, key), vector.expect);
      break;
    case 'encrypt_combined': {
      const sealed = keys.encryptCombined(vector.plaintext, key);
      const raw = Buffer.from(sealed, 'base64');
      assert.equal(raw.subarray(0, 2).toString(), 'OM');
      assert.equal(hex(raw.subarray(2, 6)), hex(keys.keyFingerprint(key)));
      assert.equal(keys.decryptCombined(sealed, key), vector.plaintext);
      break;
    }
    case 'random_key': {
      const first = keys.randomKey(), second = keys.randomKey();
      assert.ok(first instanceof Uint8Array && first.length === 32 && second.length === 32);
      assert.notEqual(hex(first), hex(second));
      break;
    }
    default: throw new Error('Unsupported key-management vector op');
  }
}

function modelCase(models, vector) {
  if (vector.kind === 'workspaces') { assert.deepEqual(models.workspaces(), vector.expect); return; }
  const parse = { chat: models.parseChat, message: models.parseMessage, item: models.parseItem }[vector.kind];
  assert.equal(typeof parse, 'function', vector.id);
  if (vector.expect_error) refused(() => parse(vector.input), 'invalid_argument');
  else assert.deepEqual(parse(vector.input), vector.expect, vector.id);
}

export function runLocalPrimitiveVectors(capability, suite, keyModule, modelModule) {
  const results = [];
  for (const vector of suite.vectors) {
    if (capability === 'sdk.key-management.primitives.v1') keyCase(keyModule.keyManagement, vector);
    else if (capability === 'sdk.models.layout.v1') modelCase(modelModule.models, vector);
    else throw new Error('Unsupported conformance capability');
    results.push({ id: vector.id, status: 'passed' });
  }
  return results;
}
