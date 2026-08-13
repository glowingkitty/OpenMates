// scripts/tests/extract_shared_chat.test.mjs
// Verifies that the shared-chat extraction helper accepts zero-knowledge short
// links without sending their fragment key to the resolver endpoint.
// The fixture exercises the same PBKDF2/AES-GCM envelope as the web client.

import assert from 'node:assert/strict';
import test from 'node:test';

import { resolveShareUrl } from '../extract-shared-chat.mjs';

function base64UrlEncode(data) {
  return Buffer.from(data).toString('base64url');
}

// contract-test: infrastructure
test('resolves encrypted short share URLs locally', async () => {
  const token = 'Ab12Cd34';
  const shortKey = 'A1b2C3d4E5f6G7h8I9j0K1';
  const fullUrl = 'https://app.dev.openmates.org/share/chat/11111111-2222-3333-4444-555555555555#key=encrypted-key';
  const keyMaterial = await crypto.subtle.importKey(
    'raw',
    new TextEncoder().encode(shortKey),
    'PBKDF2',
    false,
    ['deriveKey'],
  );
  const key = await crypto.subtle.deriveKey(
    {
      name: 'PBKDF2',
      salt: new TextEncoder().encode(`omts-v1-${token}`),
      iterations: 200_000,
      hash: 'SHA-256',
    },
    keyMaterial,
    { name: 'AES-GCM', length: 256 },
    false,
    ['encrypt'],
  );
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const ciphertext = new Uint8Array(await crypto.subtle.encrypt(
    { name: 'AES-GCM', iv },
    key,
    new TextEncoder().encode(fullUrl),
  ));
  const combined = new Uint8Array(iv.length + ciphertext.length);
  combined.set(iv);
  combined.set(ciphertext, iv.length);

  let requestedUrl = '';
  const resolved = await resolveShareUrl(
    `https://app.dev.openmates.org/s/${token}#${shortKey}`,
    async (url) => {
      requestedUrl = String(url);
      return new Response(JSON.stringify({ encrypted_url: base64UrlEncode(combined) }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    },
  );

  assert.equal(resolved, fullUrl);
  assert.equal(requestedUrl, `https://api.dev.openmates.org/v1/share/short-url/${token}`);
  assert.doesNotMatch(requestedUrl, new RegExp(shortKey));
});

// contract-test: infrastructure
test('passes full share URLs through without network access', async () => {
  const fullUrl = 'https://app.dev.openmates.org/share/chat/11111111-2222-3333-4444-555555555555#key=encrypted-key';
  const resolved = await resolveShareUrl(fullUrl, async () => {
    throw new Error('full links must not use the short-link resolver');
  });
  assert.equal(resolved, fullUrl);
});

// contract-test: infrastructure
test('uses an explicit API base for custom short-link domains', async () => {
  let requestedUrl = '';
  await assert.rejects(
    resolveShareUrl(
      'https://short.example/s/Ab12Cd34#A1b2C3d4',
      async (url) => {
        requestedUrl = String(url);
        return new Response(JSON.stringify({ encrypted_url: 'invalid' }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        });
      },
      'https://api.example',
    ),
  );
  assert.equal(requestedUrl, 'https://api.example/v1/share/short-url/Ab12Cd34');
});
