/**
 * Seed real encrypted chat history for startup-sync-contract.spec.ts.
 * This runs only against the isolated GitHub runner's freshly provisioned
 * account and CMS. The candidate CLI encrypts every title and message.
 */
import { createHash, randomBytes, randomUUID } from 'node:crypto';
import { pathToFileURL } from 'node:url';
import path from 'node:path';

export const CHAT_COUNT = 22;
export const RECENT_MESSAGE_COUNT = 6;
const hash = value => createHash('sha256').update(value).digest('hex');

export async function buildStartupSyncFixture(source, userId, masterKey, now = Math.floor(Date.now() / 1000)) {
  const { encryptBytesWithAesGcm, encryptWithAesGcmCombined } = await import(
    pathToFileURL(path.join(source, 'frontend/packages/openmates-cli/src/crypto.ts'))
  );
  const ownerHash = hash(userId);
  const chats = [];
  const messages = [];

  for (let index = 0; index < CHAT_COUNT; index += 1) {
    const chatId = randomUUID();
    const chatKey = randomBytes(32);
    const messageCount = index < 2 ? RECENT_MESSAGE_COUNT : 1;
    const updatedAt = now - index * 60;
    const createdAt = updatedAt - messageCount;
    const label = String(index + 1).padStart(2, '0');

    chats.push({
      id: chatId,
      hashed_user_id: ownerHash,
      encrypted_chat_key: await encryptBytesWithAesGcm(chatKey, masterKey),
      encrypted_title: await encryptWithAesGcmCombined(`Startup sync fixture ${label}`, chatKey),
      messages_v: messageCount,
      title_v: 1,
      metadata_v: 1,
      unread_count: 0,
      created_at: createdAt,
      updated_at: updatedAt,
      last_edited_overall_timestamp: updatedAt,
    });

    for (let messageIndex = 0; messageIndex < messageCount; messageIndex += 1) {
      const messageId = randomUUID();
      messages.push({
        id: messageId,
        client_message_id: messageId,
        chat_id: chatId,
        hashed_user_id: ownerHash,
        role: 'user',
        encrypted_sender_name: await encryptWithAesGcmCombined('User', chatKey),
        encrypted_content: await encryptWithAesGcmCombined(
          `Synthetic startup chat ${label}, message ${messageIndex + 1}.`, chatKey
        ),
        created_at: createdAt + messageIndex + 1,
      });
    }
  }

  return { chats, messages };
}

async function persistRows(collection, rows, token) {
  for (const row of rows) {
    const response = await fetch(`http://localhost:8055/items/${collection}`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify(row),
    });
    if (!response.ok) throw new Error(`Encrypted startup fixture write failed: ${collection} HTTP ${response.status}`);
  }
}

async function main() {
  if (process.env.RUNNER_ENVIRONMENT !== 'github-hosted' || process.env.CI_TEST_MODE !== 'e2e') {
    throw new Error('Startup sync fixture requires isolated GitHub E2E');
  }
  const token = process.env.OPENMATES_CI_FIXTURE_CMS_TOKEN;
  if (!token) throw new Error('Disposable CMS fixture token missing');
  const source = path.resolve(process.argv[2]);
  const { OpenMatesClient } = await import(pathToFileURL(path.join(source, 'frontend/packages/openmates-cli/dist/index.js')));
  const client = new OpenMatesClient({ apiUrl: 'http://localhost:8000' });
  const user = await client.whoAmI();
  if (typeof user.id !== 'string') throw new Error('Fresh fixture account identity missing');
  const session = client.getSession();
  if (!session?.masterKeyExportedB64) throw new Error('Fresh fixture account master key missing');
  const fixture = await buildStartupSyncFixture(source, user.id, Buffer.from(session.masterKeyExportedB64, 'base64'));
  await persistRows('chats', fixture.chats, token);
  await persistRows('messages', fixture.messages, token);
  await client.ensureSynced(true);
  process.stdout.write(JSON.stringify({ chats: fixture.chats.length, messages: fixture.messages.length }));
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) await main();
