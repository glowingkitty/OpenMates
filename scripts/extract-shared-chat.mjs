/**
 * extract-shared-chat.mjs
 *
 * Extracts and decrypts a shared chat from its share URL.
 * Uses the same crypto flow as the browser client:
 * 1. Derive key from chat ID (PBKDF2-SHA256)
 * 2. Decrypt the key blob from URL fragment (AES-256-GCM)
 * 3. Fetch encrypted chat data from API
 * 4. Decrypt messages and embeds
 *
 * Usage: node scripts/extract-shared-chat.mjs <share-url>
 */

const { subtle } = globalThis.crypto;

const SHARE_URL = process.argv[2];
if (!SHARE_URL) {
  console.error('Usage: node scripts/extract-shared-chat.mjs <share-url>');
  process.exit(1);
}

// Parse URL
const url = new URL(SHARE_URL);
const pathParts = url.pathname.split('/');
const chatId = pathParts[pathParts.length - 1];
const fragment = url.hash.slice(1); // Remove #
const params = new URLSearchParams(fragment);
const encryptedBlob = params.get('key');

if (!chatId || !encryptedBlob) {
  console.error('Could not parse chat ID or key from URL');
  process.exit(1);
}

// The frontend app proxies to the API - derive API URL from app URL
const host = url.host;
const API_BASE = host.startsWith('app.dev.')
  ? `https://api.dev.${host.replace('app.dev.', '')}`
  : host.startsWith('app.')
    ? `https://api.${host.replace('app.', '')}`
    : `${url.protocol}//${host}`;

console.log(`Chat ID: ${chatId}`);
console.log(`API Base: ${API_BASE}`);

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
    console.error(`Decryption failed for content (length ${raw.length}):`, e.message);
    return null;
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

// --- Main flow ---

async function main() {
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

  // Step 3: Fetch encrypted data from API
  console.log('\n3. Fetching encrypted chat data...');
  const res = await fetch(`${API_BASE}/v1/share/chat/${chatId}`);
  if (!res.ok) {
    console.error(`API error: ${res.status} ${res.statusText}`);
    process.exit(1);
  }
  const data = await res.json();

  // Step 4: Decrypt chat metadata
  console.log('\n4. Decrypting chat metadata...');
  const title = await decryptContent(data.encrypted_title, chatKeyBytes);
  const summary = await decryptContent(data.encrypted_chat_summary, chatKeyBytes);
  const icon = await decryptContent(data.encrypted_icon, chatKeyBytes);
  const category = await decryptContent(data.encrypted_category, chatKeyBytes);
  const followUps = await decryptContent(data.encrypted_follow_up_request_suggestions, chatKeyBytes);

  console.log(`   Title: ${title}`);
  console.log(`   Summary: ${summary}`);
  console.log(`   Icon: ${icon}`);
  console.log(`   Category: ${category}`);

  // Step 5: Decrypt messages
  // Messages may be returned as JSON strings (not objects) from the API
  const rawMessages = (data.messages || []).map(m =>
    typeof m === 'string' ? JSON.parse(m) : m
  );
  console.log(`\n5. Decrypting ${rawMessages.length} messages...`);
  const messages = [];
  for (const msg of rawMessages) {
    const content = await decryptContent(msg.encrypted_content, chatKeyBytes);
    const senderName = await decryptContent(msg.encrypted_sender_name, chatKeyBytes);
    const msgCategory = await decryptContent(msg.encrypted_category, chatKeyBytes);
    const modelName = await decryptContent(msg.encrypted_model_name, chatKeyBytes);

    messages.push({
      message_id: msg.client_message_id || msg.message_id || msg.id,
      role: msg.role,
      content,
      sender_name: senderName,
      category: msgCategory,
      model_name: modelName,
      created_at: msg.created_at,
      user_message_id: msg.user_message_id,
    });
  }

  // Step 6: Decrypt embeds
  // Parse embeds (may be JSON strings)
  const rawEmbeds = (data.embeds || []).map(e =>
    typeof e === 'string' ? JSON.parse(e) : e
  );
  console.log(`\n6. Decrypting ${rawEmbeds.length} embeds...`);

  // Build embed key map from embed_keys (may be JSON strings)
  const rawEmbedKeys = (data.embed_keys || []).map(ek =>
    typeof ek === 'string' ? JSON.parse(ek) : ek
  );
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

  // Map embed_id → key by hashing each embed's ID
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
    // Also derive from parent's embed_ids list
    if (Array.isArray(embed.embed_ids)) {
      for (const childId of embed.embed_ids) {
        parentChildMap.set(childId, embed.embed_id);
      }
    }
  }

  // Propagate parent keys to children
  for (const [childId, parentId] of parentChildMap) {
    if (!embedKeyMap[childId] && embedKeyMap[parentId]) {
      embedKeyMap[childId] = embedKeyMap[parentId];
    }
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
    } else {
      console.error(`   No key for embed ${embed.embed_id} (parent: ${embed.parent_embed_id || 'none'})`);
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

  // Output complete chat data
  const output = {
    chat_id: chatId,
    title,
    summary,
    icon,
    category,
    follow_up_suggestions: followUps ? JSON.parse(followUps) : null,
    messages,
    embeds,
  };

  console.log('\n' + '='.repeat(80));
  console.log('DECRYPTED CHAT DATA');
  console.log('='.repeat(80));
  console.log(JSON.stringify(output, null, 2));
}

main().catch(err => {
  console.error('Fatal error:', err);
  process.exit(1);
});
