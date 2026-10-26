import assert from 'node:assert/strict';
import { test } from 'node:test';
import { assertWebNodeRuntimeSecurity } from '../src/lib/server/webNodeRuntimeSecurity.mjs';

const patched = { BROTLI_DECODER_ERROR_FORMAT_BLOCK_SWITCH: -17 };

// contract-test: supporting surface=gui.web assertions=pii.surface.semantic-parity
test('accepts the patched Node floor and later Node 24 releases', () => {
  for (const nodeVersion of ['24.22.1', 'v24.22.1', '24.22.2', '24.23.0']) {
    assert.doesNotThrow(() => assertWebNodeRuntimeSecurity({ nodeVersion, brotliConstants: patched }));
  }
});

// contract-test: supporting surface=gui.web assertions=pii.surface.semantic-parity
test('rejects pre-patch Node 24 and unsupported Node majors even if a constant is supplied', () => {
  for (const nodeVersion of ['24.22.0', '24.21.9', '20.20.0', '22.23.4', '25.0.0']) {
    assert.throws(() => assertWebNodeRuntimeSecurity({ nodeVersion, brotliConstants: patched }), /Node\.js 24\.22\.1/);
  }
});

// contract-test: supporting surface=gui.web assertions=pii.surface.semantic-parity
test('rejects a claimed patched Node version with a missing or wrong backport signature', () => {
  for (const brotliConstants of [{}, { BROTLI_DECODER_ERROR_FORMAT_BLOCK_SWITCH: -16 }]) {
    assert.throws(() => assertWebNodeRuntimeSecurity({ nodeVersion: '24.22.1', brotliConstants }), /Brotli security patch/);
  }
});
