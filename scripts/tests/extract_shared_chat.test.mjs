// scripts/tests/extract_shared_chat.test.mjs
// Verifies that the shared-chat extraction helper accepts zero-knowledge short
// links without sending their fragment key to the resolver endpoint.
// The fixture exercises the same PBKDF2/AES-GCM envelope as the web client.

import assert from 'node:assert/strict';
import test from 'node:test';

import { decryptSharedChatPayload, fetchSharedPayload, resolveShareUrl } from '../extract-shared-chat.mjs';

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

function mockShare(manifest, routeHandler = () => undefined) {
  const requested = [];
  return {
    requested,
    fetch: async input => {
      const url = new URL(input);
      assert.equal(url.hash, '', 'the share fragment stays local');
      requested.push(url);
      let payload;
      if (url.pathname.endsWith('/manifest')) payload = {
        embeds: [], embed_keys: [], sub_chats: [], compression_checkpoints: [],
        embed_window: { has_more_before: false },
        embed_key_window: { has_more_after: false }, sub_chat_window: { has_more_before: false },
        compression_checkpoint_window: { has_more_before: false }, ...manifest,
      };
      else if (url.pathname.endsWith('/messages')) payload = { messages: [], has_more: false };
      else payload = routeHandler(url);
      if (payload === undefined) throw new Error(`Unexpected shared request: ${url.pathname}`);
      if (payload instanceof Response) return payload;
      return Response.json(Array.isArray(payload.embeds)
        ? { embed_keys: [], embed_keys_has_more_after: false, ...payload } : payload);
    },
  };
}

// contract-test: infrastructure
test('extracts every embed and wrapper beyond the first shared manifest window', async () => {
  const latest = Array.from({ length: 30 }, (_, index) => ({ embed_id: `recent-${index}` }));
  const mock = mockShare({ embeds: latest, embed_keys: [{ id: 'key-a' }],
    embed_window: { has_more_before: true, start_cursor: { created_at: 10, id: 'row-30' } },
    embed_key_window: { has_more_after: true, end_cursor: 'key-a' } }, url => {
    if (url.pathname.endsWith('/embeds/keys/window')) {
      assert.deepEqual(url.searchParams.get('embed_ids').split(','), latest.map(row => row.embed_id));
      assert.equal(url.searchParams.get('after_key_id'), 'key-a');
      return { embed_keys: [{ id: 'key-b' }], has_more_after: false };
    }
    assert.equal(url.pathname, '/v1/share/chat/shared/embeds/window');
    assert.equal(url.searchParams.get('before_created_at'), '10');
    assert.equal(url.searchParams.get('before_id'), 'row-30');
    return { embeds: [{ embed_id: 'old-parent' }, { embed_id: 'old-child' }, { embed_id: 'old-code' }],
      embed_keys: [{ id: 'key-c' }], has_more_before: false };
  });
  const result = await fetchSharedPayload('https://api.example', 'shared', mock.fetch);
  assert.equal(result.embeds.length, 33);
  assert.deepEqual(result.embed_keys.map(row => row.id), ['key-a', 'key-b', 'key-c']);
});

// contract-test: infrastructure
test('reads an oversized encrypted embed and key before advancing their independent cursors', async () => {
  const mock = mockShare({ embeds: [], embed_keys: [], embed_window: { has_more_before: true,
    oversized_embed_id: 'large-embed', oversized_embed_cursor: { created_at: 7, id: 'row-large' } } }, url => {
    if (url.pathname.endsWith('/embeds/large-embed')) return {
      embed: { embed_id: 'large-embed' }, embed_keys: [], embed_keys_has_more_after: true,
      oversized_embed_key_id: 'large-key',
    };
    if (url.pathname.endsWith('/embeds/keys/window')) {
      assert.equal(url.searchParams.get('embed_ids'), 'large-embed');
      if (url.searchParams.get('key_id')) return { embed_keys: [{ id: 'large-key' }], has_more_after: false };
      assert.equal(url.searchParams.get('after_key_id'), 'large-key');
      return { embed_keys: [{ id: 'following-key' }], has_more_after: false };
    }
    assert.equal(url.searchParams.get('before_id'), 'row-large');
    return { embeds: [], embed_keys: [], has_more_before: false };
  });
  const result = await fetchSharedPayload('https://api.example', 'shared', mock.fetch);
  assert.deepEqual(result.embeds.map(row => row.embed_id), ['large-embed']);
  assert.deepEqual(result.embed_keys.map(row => row.id), ['large-key', 'following-key']);
});

// contract-test: infrastructure
test('retains older sub-chats and compression checkpoints from bounded continuation pages', async () => {
  const mock = mockShare({ sub_chats: [{ id: 'child-new', created_at: 9 }],
    sub_chat_window: { has_more_before: true, start_cursor: { timestamp: 9, id: 'child-new' } },
    compression_checkpoints: [{ id: 'checkpoint-new', created_at: 8 }],
    compression_checkpoint_window: { has_more_before: true, start_cursor: { created_at: 8, id: 'checkpoint-new' } } }, url => {
    if (url.pathname.endsWith('/auxiliary/sub_chats')) {
      assert.equal(url.searchParams.get('before_timestamp'), '9');
      return { items: [{ id: 'child-old', created_at: 1 }], has_more_before: false };
    }
    assert.equal(url.pathname, '/v1/share/chat/shared/compression-checkpoints');
    assert.equal(url.searchParams.get('before_timestamp'), '8');
    return { checkpoints: [{ id: 'checkpoint-old', created_at: 2 }], has_more_before: false };
  });
  const result = await fetchSharedPayload('https://api.example', 'shared', mock.fetch);
  assert.deepEqual(result.sub_chats.map(row => row.id), ['child-old', 'child-new']);
  assert.deepEqual(result.compression_checkpoints.map(row => row.id), ['checkpoint-old', 'checkpoint-new']);
});

// contract-test: infrastructure
test('fails extraction on a continuation outage rather than falling back to a truncated legacy payload', async () => {
  const mock = mockShare({ embed_window: { has_more_before: true, start_cursor: { created_at: 1, id: 'row' } } },
    () => new Response('', { status: 503 }));
  await assert.rejects(fetchSharedPayload('https://api.example', 'shared', mock.fetch), /503/);
  assert.ok(mock.requested.every(url => url.pathname !== '/v1/share/chat/shared'));
});

// contract-test: infrastructure
test('rejects stalled shared embed and message cursors', async () => {
  const window = { has_more_before: true, start_cursor: { created_at: 1, id: 'row' } };
  const mock = mockShare({ embed_window: window }, () => ({ embeds: [], ...window }));
  await assert.rejects(fetchSharedPayload('https://api.example', 'shared', mock.fetch), /cursor did not advance/);
  const messages = mockShare({});
  await assert.rejects(fetchSharedPayload('https://api.example', 'shared', async url => {
    if (new URL(url).pathname.endsWith('/messages')) return Response.json({ messages: [], has_more: true });
    return messages.fetch(url);
  }), /message window cannot advance/);
});

// contract-test: infrastructure
test('rejects mismatched selected identities and changed ciphertext rows', async () => {
  const mock = mockShare({ embed_window: { has_more_before: true, oversized_embed_id: 'expected' } },
    () => ({ embed: { embed_id: 'different' } }));
  await assert.rejects(fetchSharedPayload('https://api.example', 'shared', mock.fetch), /identity mismatch/);
  const changed = mockShare({ embeds: [{ embed_id: 'same', encrypted_content: 'first' }],
    embed_window: { has_more_before: true, start_cursor: { created_at: 1, id: 'row' } } },
    () => ({ embeds: [{ embed_id: 'same', encrypted_content: 'different' }], has_more_before: false }));
  await assert.rejects(fetchSharedPayload('https://api.example', 'shared', changed.fetch), /identity changed/);
});

// contract-test: infrastructure
test('requires complete window metadata instead of assuming a truncated manifest is complete', async () => {
  for (const field of ['embed_window', 'embed_key_window', 'sub_chat_window', 'compression_checkpoint_window']) {
    const mock = mockShare({ [field]: null });
    await assert.rejects(fetchSharedPayload('https://api.example', 'shared', mock.fetch), /window metadata is missing/);
  }
});

// contract-test: infrastructure
test('rejects successful responses with missing ciphertext arrays instead of publishing an empty graph', async () => {
  for (const field of ['embeds', 'embed_keys', 'sub_chats', 'compression_checkpoints']) {
    const mock = mockShare({ [field]: undefined });
    await assert.rejects(fetchSharedPayload('https://api.example', 'shared', mock.fetch), /rows are missing/);
  }
  const mock = mockShare({ embed_window: { has_more_before: true, start_cursor: { created_at: 1, id: 'row' } } },
    () => Response.json({ has_more_before: false, embed_keys: [], embed_keys_has_more_after: false }));
  await assert.rejects(fetchSharedPayload('https://api.example', 'shared', mock.fetch), /Shared embed rows are missing/);
  await assert.rejects(fetchSharedPayload('https://api.example', 'shared', async url => {
    if (new URL(url).pathname.endsWith('/messages')) return Response.json({ has_more: false });
    return mock.fetch(url);
  }), /Shared message rows are missing/);
});

// contract-test: infrastructure
test('rejects unauthenticated ciphertext instead of emitting empty message content', async () => {
  const keyBytes = crypto.getRandomValues(new Uint8Array(32));
  const wrongKey = crypto.getRandomValues(new Uint8Array(32));
  const key = await crypto.subtle.importKey('raw', keyBytes, 'AES-GCM', false, ['encrypt']);
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const encrypted = new Uint8Array(await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, key,
    new TextEncoder().encode('Real shared message')));
  const ciphertext = Buffer.concat([iv, encrypted]).toString('base64');
  const payload = { messages: [{ id: 'message', encrypted_content: ciphertext }], embeds: [], embed_keys: [] };
  const decrypted = await decryptSharedChatPayload('shared', payload, keyBytes);
  assert.equal(decrypted.messages[0].content, 'Real shared message');
  await assert.rejects(decryptSharedChatPayload('shared', payload, wrongKey), /could not be authenticated/);
});
