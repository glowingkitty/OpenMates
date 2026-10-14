/**
 * extract-shared-chat.mjs
 *
 * Extracts and decrypts a shared chat from its share URL.
 * Uses the same crypto flow as the browser client:
 * 1. Derive key from chat ID (PBKDF2-SHA256)
 * 2. Decrypt the key blob from URL fragment (AES-256-GCM)
 * 3. Fetch encrypted share manifest and message windows from API
 * 4. Decrypt messages, embeds, and compression checkpoint summaries
 *
 * Accepts full `/share/chat/...#key=...` links and zero-knowledge `/s/{token}#...`
 * short links. Short-link secrets remain local and are never sent to the server.
 *
 * Usage: node scripts/extract-shared-chat.mjs <share-url-or-short-url> [--api-base <url>]
 */

const { subtle } = globalThis.crypto;
import { fileURLToPath } from 'node:url';

export function apiBaseFor(url) {
  const host = url.host;
  return host.startsWith('app.dev.')
    ? `https://api.dev.${host.replace('app.dev.', '')}`
    : host.startsWith('app.')
      ? `https://api.${host.replace('app.', '')}`
      : `${url.protocol}//${host}`;
}

export async function resolveShareUrl(inputUrl, fetchImpl = fetch, apiBaseOverride = '') {
  const shortUrl = new URL(inputUrl);
  const tokenMatch = shortUrl.pathname.match(/^\/s\/([A-Za-z0-9]{6,12})\/?$/);
  if (!tokenMatch) return inputUrl;

  const token = tokenMatch[1];
  const shortKey = shortUrl.hash.slice(1);
  if (!/^[A-Za-z0-9]{4,22}$/.test(shortKey)) {
    throw new Error('Short share URL is missing a valid fragment key');
  }

  const apiBase = apiBaseOverride || process.env.OPENMATES_API_BASE || apiBaseFor(shortUrl);
  const response = await fetchImpl(`${apiBase.replace(/\/$/, '')}/v1/share/short-url/${encodeURIComponent(token)}`);
  if (!response.ok) throw new Error(`Short URL resolution failed: ${response.status}`);
  const payload = await response.json();
  if (typeof payload.encrypted_url !== 'string') {
    throw new Error('Short URL response did not contain encrypted_url');
  }

  const keyMaterial = await subtle.importKey(
    'raw',
    new TextEncoder().encode(shortKey),
    'PBKDF2',
    false,
    ['deriveKey'],
  );
  const key = await subtle.deriveKey(
    {
      name: 'PBKDF2',
      salt: new TextEncoder().encode(`omts-v1-${token}`),
      iterations: 200_000,
      hash: 'SHA-256',
    },
    keyMaterial,
    { name: 'AES-GCM', length: 256 },
    false,
    ['decrypt'],
  );
  const decrypted = await decryptAESGCM(base64UrlDecode(payload.encrypted_url), key);
  return new TextDecoder().decode(decrypted);
}

const SHARED_MESSAGE_PAGE_LIMIT = 100;

// --- Crypto helpers ---

function base64UrlDecode(str) {
  // URL-safe base64 → standard base64
  let b64 = str.replace(/-/g, '+').replace(/_/g, '/');
  while (b64.length % 4 !== 0) b64 += '=';
  return Buffer.from(b64, 'base64');
}

function base64Decode(str) {
  return Buffer.from(str, 'base64');
}

async function deriveKeyFromId(id, salt) {
  const encoder = new TextEncoder();
  const keyMaterial = await subtle.importKey(
    'raw',
    encoder.encode(id),
    'PBKDF2',
    false,
    ['deriveKey']
  );
  return subtle.deriveKey(
    {
      name: 'PBKDF2',
      salt: encoder.encode(salt),
      iterations: 100000,
      hash: 'SHA-256',
    },
    keyMaterial,
    { name: 'AES-GCM', length: 256 },
    false,
    ['decrypt']
  );
}

async function decryptAESGCM(combined, key) {
  const iv = combined.slice(0, 12);
  const ciphertext = combined.slice(12);
  const decrypted = await subtle.decrypt(
    { name: 'AES-GCM', iv },
    key,
    ciphertext
  );
  return new Uint8Array(decrypted);
}

async function decryptContent(encryptedBase64, keyBytes) {
  if (!encryptedBase64) return null;

  const raw = base64Decode(encryptedBase64);

  let iv, ciphertext;

  // Check for Format A: [0x4F 0x4D] [4-byte fingerprint] [12-byte IV] [ciphertext]
  if (raw.length > 18 && raw[0] === 0x4F && raw[1] === 0x4D) {
    // Format A (with magic bytes + fingerprint)
    iv = raw.slice(6, 18);
    ciphertext = raw.slice(18);
  } else {
    // Legacy format: [12-byte IV] [ciphertext]
    iv = raw.slice(0, 12);
    ciphertext = raw.slice(12);
  }

  const cryptoKey = await subtle.importKey(
    'raw',
    keyBytes,
    { name: 'AES-GCM' },
    false,
    ['decrypt']
  );

  try {
    const decrypted = await subtle.decrypt(
      { name: 'AES-GCM', iv },
      cryptoKey,
      ciphertext
    );
    return new TextDecoder().decode(decrypted);
  } catch (e) {
    throw new Error('Shared ciphertext could not be authenticated', { cause: e });
  }
}

async function unwrapEmbedKey(wrappedKeyBase64, chatKeyBytes) {
  const combined = base64Decode(wrappedKeyBase64);
  const iv = combined.slice(0, 12);
  const ciphertext = combined.slice(12);

  const chatCryptoKey = await subtle.importKey(
    'raw',
    chatKeyBytes,
    { name: 'AES-GCM' },
    false,
    ['decrypt']
  );

  const decrypted = await subtle.decrypt(
    { name: 'AES-GCM', iv },
    chatCryptoKey,
    ciphertext
  );
  return new Uint8Array(decrypted);
}

function normalizeJsonRows(rows) {
  return (rows || []).map((row) => (typeof row === 'string' ? JSON.parse(row) : row));
}

const MAX_SHARED_WINDOW_PAGES = 200;
const MAX_SHARED_WINDOW_ROWS = 20_000;

function requireJsonRows(rows, label) {
  if (!Array.isArray(rows)) throw new Error(`${label} rows are missing`);
  return normalizeJsonRows(rows);
}

async function fetchJson(url, label, fetchImpl = fetch) {
  const res = await fetchImpl(url);
  if (!res.ok) {
    throw new Error(`${label} failed: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

async function fetchSharedMessages(apiBase, targetChatId, fetchImpl) {
  const pages = [];
  let beforeTimestamp = null;
  let beforeMessageId = null;
  let hasMore = true;

  const seenCursors = new Set();
  for (let pageCount = 0; hasMore; pageCount += 1) {
    if (pageCount >= MAX_SHARED_WINDOW_PAGES) throw new Error('Shared message window exceeded page limit');
    const params = new URLSearchParams({ limit: String(SHARED_MESSAGE_PAGE_LIMIT) });
    if (beforeTimestamp !== null) params.set('before_timestamp', String(beforeTimestamp));
    if (beforeMessageId) params.set('before_message_id', beforeMessageId);
    const payload = await fetchJson(
      `${apiBase}/v1/share/chat/${encodeURIComponent(targetChatId)}/messages?${params.toString()}`,
      `Shared messages fetch for ${targetChatId}`,
      fetchImpl,
    );
    const rows = requireJsonRows(payload.messages, 'Shared message');
    if (typeof payload.has_more !== 'boolean') throw new Error('Shared message window metadata is missing');
    if (rows.length === 0 && payload.has_more === true) throw new Error('Shared message window cannot advance');
    pages.unshift(rows);
    hasMore = payload.has_more === true;
    beforeTimestamp = payload.next_before_timestamp ?? null;
    beforeMessageId = payload.next_before_message_id ?? null;
    if (hasMore) {
      const cursor = JSON.stringify([beforeTimestamp, beforeMessageId]);
      if (!Number.isSafeInteger(beforeTimestamp) || beforeTimestamp < 0 || !beforeMessageId || seenCursors.has(cursor)) {
        throw new Error('Shared message cursor did not advance');
      }
      seenCursors.add(cursor);
    }
    if (pages.reduce((count, page) => count + page.length, 0) > MAX_SHARED_WINDOW_ROWS) {
      throw new Error('Shared message window exceeded row limit');
    }
  }

  return pages.flat();
}

function addRows(target, rawRows, idField, label) {
  for (const row of requireJsonRows(rawRows, label)) {
    const id = row?.[idField];
    if (typeof id !== 'string' || !id) throw new Error(`${label} row is missing its identity`);
    const existing = target.get(id);
    if (existing && JSON.stringify(existing) !== JSON.stringify(row)) throw new Error(`${label} identity changed during extraction`);
    target.set(id, row);
    if (target.size > MAX_SHARED_WINDOW_ROWS) throw new Error(`${label} exceeded row limit`);
  }
}

function checkedCursor(cursor, timestampField, seen, label) {
  const timestamp = cursor?.[timestampField];
  const id = cursor?.id;
  const identity = JSON.stringify([timestamp, id]);
  if (!Number.isSafeInteger(timestamp) || timestamp < 0 || typeof id !== 'string' || !id || seen.has(identity)) {
    throw new Error(`${label} cursor did not advance`);
  }
  seen.add(identity);
  return cursor;
}

function requireWindow(window, flag, label) {
  if (!window || typeof window[flag] !== 'boolean') throw new Error(`${label} window metadata is missing`);
  return window;
}

async function completeEmbedKeys(base, embedIds, initialKeys, initialWindow, keys, fetchImpl) {
  addRows(keys, initialKeys, 'id', 'Shared embed key');
  let window = requireWindow(initialWindow, 'has_more_after', 'Shared embed key');
  const seen = new Set();
  for (let count = 0; window?.has_more_after; count += 1) {
    if (count >= MAX_SHARED_WINDOW_PAGES) throw new Error('Shared embed key window exceeded page limit');
    const selectedId = window.oversized_key_id;
    const cursor = selectedId || window.end_cursor;
    const position = `${selectedId ? 'selected' : 'after'}:${cursor}`;
    if (typeof cursor !== 'string' || !cursor || seen.has(position)) throw new Error('Shared embed key cursor did not advance');
    seen.add(position);
    const query = new URLSearchParams({ embed_ids: embedIds.join(',') });
    query.set(selectedId ? 'key_id' : 'after_key_id', cursor);
    const page = await fetchJson(`${base}/embeds/keys/window?${query}`, 'Shared embed key continuation', fetchImpl);
    const rows = requireJsonRows(page.embed_keys, 'Shared embed key');
    if (selectedId && (rows.length !== 1 || rows[0]?.id !== selectedId)) {
      throw new Error('Shared selected embed key identity mismatch');
    }
    addRows(keys, rows, 'id', 'Shared embed key');
    // An exact oversized-key read completes only that record, not the remainder.
    window = selectedId ? { has_more_after: true, end_cursor: selectedId }
      : requireWindow(page, 'has_more_after', 'Shared embed key');
  }
}

function embedKeyWindow(page) {
  return { has_more_after: page.embed_keys_has_more_after, end_cursor: page.embed_keys_end_cursor,
    oversized_key_id: page.oversized_embed_key_id };
}

async function completeSharedEmbeds(base, manifest, fetchImpl) {
  const embeds = new Map();
  const keys = new Map();
  let rows = requireJsonRows(manifest.embeds, 'Shared embed');
  addRows(embeds, rows, 'embed_id', 'Shared embed');
  await completeEmbedKeys(base, rows.map(row => row.embed_id), manifest.embed_keys,
    manifest.embed_key_window, keys, fetchImpl);
  let window = requireWindow(manifest.embed_window, 'has_more_before', 'Shared embed');
  const cursors = new Set();
  for (let count = 0; window?.has_more_before; count += 1) {
    if (count >= MAX_SHARED_WINDOW_PAGES) throw new Error('Shared embed window exceeded page limit');
    let cursor;
    if (window.oversized_embed_id) {
      const id = window.oversized_embed_id;
      const selected = await fetchJson(`${base}/embeds/${encodeURIComponent(id)}`, 'Shared selected embed', fetchImpl);
      if (selected.embed?.embed_id !== id) throw new Error('Shared selected embed identity mismatch');
      addRows(embeds, [selected.embed], 'embed_id', 'Shared embed');
      await completeEmbedKeys(base, [id], selected.embed_keys, embedKeyWindow(selected), keys, fetchImpl);
      cursor = window.oversized_embed_cursor || { created_at: selected.embed.created_at, id: selected.embed.id };
    } else cursor = window.start_cursor;
    checkedCursor(cursor, 'created_at', cursors, 'Shared embed');
    const query = new URLSearchParams({ before_created_at: String(cursor.created_at), before_id: cursor.id });
    const page = await fetchJson(`${base}/embeds/window?${query}`, 'Shared embed continuation', fetchImpl);
    rows = requireJsonRows(page.embeds, 'Shared embed');
    addRows(embeds, rows, 'embed_id', 'Shared embed');
    await completeEmbedKeys(base, rows.map(row => row.embed_id), page.embed_keys, embedKeyWindow(page), keys, fetchImpl);
    window = requireWindow(page, 'has_more_before', 'Shared embed');
  }
  return { embeds: [...embeds.values()], embed_keys: [...keys.values()] };
}

async function completeSharedAuxiliary(base, initialRows, initialWindow, kind, fetchImpl) {
  const rows = new Map();
  const checkpoints = kind === 'compression-checkpoints';
  const field = checkpoints ? 'checkpoints' : 'items';
  const timestampField = checkpoints ? 'created_at' : 'timestamp';
  const path = checkpoints ? `${base}/compression-checkpoints` : `${base}/auxiliary/${kind}`;
  addRows(rows, initialRows, 'id', `Shared ${kind}`);
  let window = requireWindow(initialWindow, 'has_more_before', `Shared ${kind}`);
  const cursors = new Set();
  for (let count = 0; window?.has_more_before; count += 1) {
    if (count >= MAX_SHARED_WINDOW_PAGES) throw new Error(`Shared ${kind} window exceeded page limit`);
    const oversizedId = checkpoints ? window.oversized_checkpoint_id : window.oversized_id;
    let cursor;
    if (oversizedId) {
      const selected = await fetchJson(`${path}/${encodeURIComponent(oversizedId)}`, `Shared selected ${kind}`, fetchImpl);
      const item = selected[checkpoints ? 'checkpoint' : 'item'];
      if (item?.id !== oversizedId) throw new Error(`Shared selected ${kind} identity mismatch`);
      addRows(rows, [item], 'id', `Shared ${kind}`);
      cursor = { [timestampField]: item.created_at, id: item.id };
    } else cursor = window.start_cursor;
    checkedCursor(cursor, timestampField, cursors, `Shared ${kind}`);
    const query = new URLSearchParams({ before_timestamp: String(cursor[timestampField]), before_id: cursor.id });
    const page = await fetchJson(`${path}?${query}`, `Shared ${kind} continuation`, fetchImpl);
    addRows(rows, page[field], 'id', `Shared ${kind}`);
    window = requireWindow(page, 'has_more_before', `Shared ${kind}`);
  }
  return [...rows.values()].sort((a, b) => a.created_at - b.created_at || String(a.id).localeCompare(String(b.id)));
}

// Extract complete ciphertext windows. A partial/error page must never become a
// publishable example; no legacy fallback can silently hide an omitted graph.
export async function fetchSharedPayload(apiBase, targetChatId, fetchImpl = fetch) {
  const base = `${apiBase.replace(/\/$/, '')}/v1/share/chat/${encodeURIComponent(targetChatId)}`;
  const manifest = await fetchJson(`${base}/manifest`, 'Shared manifest fetch', fetchImpl);
  const messages = await fetchSharedMessages(apiBase.replace(/\/$/, ''), targetChatId, fetchImpl);
  const graph = await completeSharedEmbeds(base, manifest, fetchImpl);
  const subChats = await completeSharedAuxiliary(base, manifest.sub_chats, manifest.sub_chat_window, 'sub_chats', fetchImpl);
  const checkpoints = await completeSharedAuxiliary(base, manifest.compression_checkpoints,
    manifest.compression_checkpoint_window, 'compression-checkpoints', fetchImpl);
  return { ...manifest, messages, ...graph, sub_chats: subChats, compression_checkpoints: checkpoints };
}

async function decryptMessages(rawMessages, chatKeyBytes) {
  const messages = [];
  for (const msg of rawMessages) {
    const content = await decryptContent(msg.encrypted_content, chatKeyBytes);
    const senderName = await decryptContent(msg.encrypted_sender_name, chatKeyBytes);
    const msgCategory = await decryptContent(msg.encrypted_category, chatKeyBytes);
    const modelName = await decryptContent(msg.encrypted_model_name, chatKeyBytes);

    // Preserve explicitly shared mappings so published examples retain reveal/hide.
    const piiMappings = msg.encrypted_pii_mappings
      ? JSON.parse(await decryptContent(msg.encrypted_pii_mappings, chatKeyBytes))
      : undefined;

    messages.push({
      message_id: msg.client_message_id || msg.message_id || msg.id,
      role: msg.role,
      content,
      pii_mappings: piiMappings,
      sender_name: senderName,
      category: msgCategory,
      model_name: modelName,
      created_at: msg.created_at,
      user_message_id: msg.user_message_id,
    });
  }
  return messages;
}

async function decryptEmbeds(rawEmbeds, rawEmbedKeys, chatKeyBytes) {
  // embed_keys use hashed_embed_id — build a hash→key map, then resolve to embed_id
  const { createHash } = await import('crypto');
  function sha256(input) {
    return createHash('sha256').update(input).digest('hex');
  }

  const hashedKeyMap = {};
  for (const ek of rawEmbedKeys) {
    if (ek.hashed_embed_id && ek.encrypted_embed_key) {
      try {
        const embedKey = await unwrapEmbedKey(ek.encrypted_embed_key, chatKeyBytes);
        hashedKeyMap[ek.hashed_embed_id] = embedKey;
      } catch (e) {
        console.error(`   Failed to unwrap key for hashed embed ${ek.hashed_embed_id.slice(0,8)}...: ${e.message}`);
      }
    }
  }

  const embedKeyMap = {};
  for (const embed of rawEmbeds) {
    const hashed = sha256(embed.embed_id);
    if (hashedKeyMap[hashed]) {
      embedKeyMap[embed.embed_id] = hashedKeyMap[hashed];
    }
  }
  console.log(`   Resolved ${Object.keys(embedKeyMap).length} direct embed keys out of ${rawEmbeds.length} embeds`);

  // Child embeds use the same key as their parent — propagate parent keys to children
  const parentChildMap = new Map();
  for (const embed of rawEmbeds) {
    if (embed.parent_embed_id) {
      parentChildMap.set(embed.embed_id, embed.parent_embed_id);
    }
    if (Array.isArray(embed.embed_ids)) {
      for (const childId of embed.embed_ids) {
        parentChildMap.set(childId, embed.embed_id);
      }
    }
  }
  for (let pass = 0; pass < parentChildMap.size; pass += 1) {
    let changed = false;
    for (const [childId, parentId] of parentChildMap) {
      if (!embedKeyMap[childId] && embedKeyMap[parentId]) {
        embedKeyMap[childId] = embedKeyMap[parentId];
        changed = true;
      }
    }
    if (!changed) break;
  }
  console.log(`   After parent propagation: ${Object.keys(embedKeyMap).length} embed keys`);

  const embeds = [];
  for (const embed of rawEmbeds) {
    const embedKey = embedKeyMap[embed.embed_id];
    let content = null;
    let type = null;

    if (embedKey) {
      content = await decryptContent(embed.encrypted_content, embedKey);
      type = embed.encrypted_type
        ? await decryptContent(embed.encrypted_type, embedKey)
        : embed.embed_type;
    } else if (embed.encrypted_content || embed.encrypted_type) {
      throw new Error(`No shared key for encrypted embed ${embed.embed_id}`);
    }

    embeds.push({
      embed_id: embed.embed_id,
      type,
      content,
      status: embed.status,
      parent_embed_id: embed.parent_embed_id,
      embed_ids: embed.embed_ids,
    });
  }
  return embeds;
}

async function decryptCompressionCheckpoints(rawCheckpoints, chatKeyBytes, targetChatId) {
  const checkpoints = [];
  for (const rawCheckpoint of rawCheckpoints || []) {
    const checkpoint = typeof rawCheckpoint === 'string' ? JSON.parse(rawCheckpoint) : rawCheckpoint;
    if (!checkpoint || !checkpoint.id) continue;
    checkpoints.push({
      id: checkpoint.id,
      chat_id: targetChatId,
      summary: await decryptContent(checkpoint.encrypted_summary, chatKeyBytes) || '',
      compressed_up_to_timestamp: Number(checkpoint.compressed_up_to_timestamp || 0),
      compressed_message_count: Number(checkpoint.compressed_message_count || 0),
      summary_token_estimate: checkpoint.summary_token_estimate ?? undefined,
      key_version: checkpoint.key_version ?? null,
      created_at: Number(checkpoint.created_at || 0),
      updated_at: Number(checkpoint.updated_at || checkpoint.created_at || 0),
    });
  }
  return checkpoints;
}

export async function decryptSharedChatPayload(targetChatId, data, chatKeyBytes, options = {}) {
  const title = await decryptContent(data.encrypted_title, chatKeyBytes);
  const summary = await decryptContent(data.encrypted_chat_summary, chatKeyBytes);
  const icon = await decryptContent(data.encrypted_icon, chatKeyBytes);
  const category = await decryptContent(data.encrypted_category, chatKeyBytes);
  const followUps = await decryptContent(data.encrypted_follow_up_request_suggestions, chatKeyBytes);

  const rawMessages = normalizeJsonRows(data.messages || []);
  console.log(`\n${options.label || 'Chat'}: decrypting ${rawMessages.length} messages for ${targetChatId}...`);
  const messages = await decryptMessages(rawMessages, chatKeyBytes);

  const rawEmbeds = (data.embeds || []).map(e =>
    typeof e === 'string' ? JSON.parse(e) : e
  );
  const rawEmbedKeys = (data.embed_keys || []).map(ek =>
    typeof ek === 'string' ? JSON.parse(ek) : ek
  );
  console.log(`${options.label || 'Chat'}: decrypting ${rawEmbeds.length} embeds for ${targetChatId}...`);
  const embeds = await decryptEmbeds(rawEmbeds, rawEmbedKeys, chatKeyBytes);

  const rawCompressionCheckpoints = normalizeJsonRows(data.compression_checkpoints || []);
  console.log(`${options.label || 'Chat'}: decrypting ${rawCompressionCheckpoints.length} compression checkpoints for ${targetChatId}...`);
  const compressionCheckpoints = await decryptCompressionCheckpoints(rawCompressionCheckpoints, chatKeyBytes, targetChatId);

  return {
    chat_id: targetChatId,
    title,
    summary,
    icon,
    category,
    follow_up_suggestions: followUps ? JSON.parse(followUps) : null,
    messages,
    embeds,
    compression_checkpoints: compressionCheckpoints,
  };
}

// --- Main flow ---

async function main(inputUrl) {
  if (!inputUrl) {
    console.error('Usage: node scripts/extract-shared-chat.mjs <share-url-or-short-url> [--api-base <url>]');
    process.exit(1);
  }

  const apiBaseFlagIndex = process.argv.indexOf('--api-base');
  const apiBaseOverride = apiBaseFlagIndex >= 0 ? process.argv[apiBaseFlagIndex + 1] : '';
  if (apiBaseFlagIndex >= 0 && !apiBaseOverride) {
    throw new Error('--api-base requires a URL');
  }
  const shareUrl = await resolveShareUrl(inputUrl, fetch, apiBaseOverride);
  const url = new URL(shareUrl);
  const pathParts = url.pathname.split('/');
  const chatId = pathParts[pathParts.length - 1];
  const params = new URLSearchParams(url.hash.slice(1));
  const encryptedBlob = params.get('key');
  if (!chatId || !encryptedBlob) {
    throw new Error('Could not parse chat ID or key from URL');
  }
  const apiBase = apiBaseOverride || process.env.OPENMATES_API_BASE || apiBaseFor(url);

  console.log(`Chat ID: ${chatId}`);
  console.log(`API Base: ${apiBase}`);

  // Step 1: Derive key from chat ID
  console.log('\n1. Deriving key from chat ID...');
  const chatIdKey = await deriveKeyFromId(chatId, 'openmates-share-v1');

  // Step 2: Decrypt the blob
  console.log('2. Decrypting key blob...');
  const blobBytes = base64UrlDecode(encryptedBlob);
  const decryptedBlobBytes = await decryptAESGCM(blobBytes, chatIdKey);
  const blobString = new TextDecoder().decode(decryptedBlobBytes);

  const blobParams = new URLSearchParams(blobString);
  const chatKeyBase64 = blobParams.get('chat_encryption_key');
  const generatedAt = parseInt(blobParams.get('generated_at') || '0');
  const durationSeconds = parseInt(blobParams.get('duration_seconds') || '0');
  const pwd = blobParams.get('pwd');

  console.log(`   Generated at: ${new Date(generatedAt * 1000).toISOString()}`);
  console.log(`   Duration: ${durationSeconds}s (${durationSeconds === 0 ? 'no expiry' : 'expires'})`);
  console.log(`   Password protected: ${pwd === '1' ? 'yes' : 'no'}`);

  if (pwd === '1') {
    console.error('Password-protected shares not supported in this script');
    process.exit(1);
  }

  // Decode the chat key
  const chatKeyBytes = base64Decode(chatKeyBase64);
  console.log(`   Chat key: ${chatKeyBytes.length} bytes`);

  // Step 3: Fetch and decrypt root chat data
  console.log('\n3. Fetching encrypted chat data...');
  const data = await fetchSharedPayload(apiBase, chatId);
  const output = await decryptSharedChatPayload(chatId, data, chatKeyBytes, { label: 'Root chat' });

  console.log(`   Title: ${output.title}`);
  console.log(`   Summary: ${output.summary}`);
  console.log(`   Icon: ${output.icon}`);
  console.log(`   Category: ${output.category}`);

  // Step 4: Fetch and decrypt child sub-chats. Sub-chats use the parent chat key.
  const rawSubChats = Array.isArray(data.sub_chats) ? data.sub_chats : [];
  console.log(`\n4. Fetching ${rawSubChats.length} sub-chat(s)...`);
  output.sub_chats = [];
  for (const subChat of rawSubChats) {
    const subChatId = subChat.id || subChat.chat_id;
    if (!subChatId) throw new Error('Shared sub-chat is missing its identity');
    const subChatPayload = await fetchSharedPayload(apiBase, subChatId);
    const decryptedSubChat = await decryptSharedChatPayload(subChatId, subChatPayload, chatKeyBytes, {
      label: 'Sub-chat',
    });
    decryptedSubChat.parent_id = chatId;
    decryptedSubChat.is_sub_chat = true;
    decryptedSubChat.budget_limit = subChat.budget_limit ?? null;
    decryptedSubChat.budget_spent = subChat.budget_spent ?? 0;
    output.sub_chats.push(decryptedSubChat);
  }

  console.log('\n' + '='.repeat(80));
  console.log('DECRYPTED CHAT DATA');
  console.log('='.repeat(80));
  console.log(JSON.stringify(output, null, 2));
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  main(process.argv[2]).catch(err => {
    console.error('Fatal error:', err);
    process.exit(1);
  });
}
