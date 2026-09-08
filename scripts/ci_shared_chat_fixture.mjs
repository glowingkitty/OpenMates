/**
 * Create disposable encrypted archive data for the real shared-chat viewer.
 * All accounts, keys and rows belong to the GitHub runner's fresh database.
 * Reuses the candidate CLI's crypto implementation; never generates inference,
 * uploads private history, or intercepts application requests. Sharing itself
 * executes through the genuine first-party client before logged-out assertions.
 * See docs/architecture/isolated-github-tests.md.
 */
import { randomBytes, randomUUID, createHash } from 'node:crypto';
import { pathToFileURL } from 'node:url';
import path from 'node:path';

export const TRANSCRIPT = 'This synthetic archived voice memo describes a project review and its next steps. The team will check the implementation, review the results, and document the follow-up work.';
const hash = value => createHash('sha256').update(value).digest('hex');

export async function buildFixture(source, userId, masterKey) {
  const { encryptBytesWithAesGcm, encryptWithAesGcmCombined } = await import(pathToFileURL(path.join(source, 'frontend/packages/openmates-cli/src/crypto.ts')));
  const { encryptEmbed, createEmbedJsonReferenceBlock } = await import(pathToFileURL(path.join(source, 'frontend/packages/openmates-cli/src/embedCreator.ts')));
  const chatId = randomUUID(), messageId = randomUUID(), embedId = randomUUID();
  const chatKey = randomBytes(32), now = Math.floor(Date.now() / 1000);
  const content = {app_id:'audio', skill_id:'transcribe', type:'audio-recording', status:'finished', filename:'synthetic-archived-memo.webm', transcript:TRANSCRIPT, transcript_original:TRANSCRIPT};
  const encrypted = await encryptEmbed({embedId, type:'audio-recording', content:JSON.stringify(content), textPreview:TRANSCRIPT, status:'finished'}, masterKey, chatKey, chatId, messageId, userId);
  if (!encrypted) throw new Error('Candidate embed encryption failed');
  const {embed_keys, ...embed} = encrypted;
  return {
    chat: {id:chatId, hashed_user_id:hash(userId), encrypted_chat_key:await encryptBytesWithAesGcm(chatKey, masterKey), encrypted_title:await encryptWithAesGcmCombined('Archived transcript fixture', chatKey), messages_v:1, title_v:1, metadata_v:1, unread_count:0, created_at:now, updated_at:now, last_edited_overall_timestamp:now},
    message: {id:messageId, client_message_id:messageId, chat_id:chatId, hashed_user_id:hash(userId), role:'user', encrypted_sender_name:await encryptWithAesGcmCombined('User',chatKey), encrypted_content:await encryptWithAesGcmCombined(createEmbedJsonReferenceBlock('audio-recording',embedId),chatKey), created_at:now},
    embed: {...embed, hashed_embed_id:hash(embedId), encryption_mode:'client', is_private:false, is_shared:false},
    keys:embed_keys,
  };
}

async function main() {
  if (process.env.RUNNER_ENVIRONMENT !== 'github-hosted' || process.env.CI_TEST_MODE !== 'e2e') throw new Error('Shared archive fixture requires isolated GitHub E2E');
  const source = path.resolve(process.argv[2]);
  const {OpenMatesClient} = await import(pathToFileURL(path.join(source,'frontend/packages/openmates-cli/dist/index.js')));
  const client = new OpenMatesClient({apiUrl:'http://localhost:8000'});
  const user = await client.whoAmI();
  if (typeof user.id !== 'string') throw new Error('Fresh account identity missing');
  const fixture = await buildFixture(source,user.id,Buffer.from(client.getSession().masterKeyExportedB64,'base64'));
  const token = process.env.OPENMATES_CI_FIXTURE_CMS_TOKEN;
  if (!token) throw new Error('Disposable CMS fixture token missing');
  for (const [collection, rows] of [['chats',fixture.chat],['messages',fixture.message],['embeds',fixture.embed],['embed_keys',fixture.keys]]) {
    const response = await fetch('http://localhost:8055/items/'+collection,{method:'POST',headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},body:JSON.stringify(rows)});
    if (!response.ok) throw new Error('Encrypted archive persistence failed: '+collection+' HTTP '+response.status);
  }
  await client.ensureSynced(true);
  const url = new URL(await client.createChatShareLink(fixture.chat.id));
  url.protocol='http:'; url.hostname='localhost'; url.port='5173';
  process.stdout.write(JSON.stringify({url:url.href,fixture:'synthetic-encrypted-archive-real-sharing'}));
}
if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) await main();
