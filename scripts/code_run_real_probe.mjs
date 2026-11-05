#!/usr/bin/env node
// contract-test-file: infrastructure
// Read-only installed-SDK probe. Credentials stay in the explicitly isolated CLI state.
import { pathToFileURL } from 'node:url';
import { resolve } from 'node:path';
import { readFileSync } from 'node:fs';

const input = JSON.parse(readFileSync(0, 'utf8'));
if (input.api_url !== 'https://api.dev.openmates.org'
    || !process.env.OPENMATES_STATE_DIR?.startsWith('/tmp/')
    || !input.sdk_module || !input.chat_id) throw new Error('InvalidProbeInput');
const { OpenMatesClient } = await import(pathToFileURL(resolve(input.sdk_module)).href);
const client = OpenMatesClient.load({ apiUrl: input.api_url });
if (!client.hasSession() || client.getSession().apiUrl !== input.api_url) throw new Error('IsolatedDevSessionRequired');
const loaded = await client.getChatMessages(input.chat_id, { personal: true });
const ids = new Set(), executions = new Set(input.execution_ids || []);
function discover(value) {
  if (Array.isArray(value)) { for (const item of value) discover(item); return; }
  if (value && typeof value === 'object') {
    for (const [key, item] of Object.entries(value)) {
      if (['embed_id', 'embedId', 'target_embed_id'].includes(key) && typeof item === 'string') ids.add(item);
      if (['embedIds', 'created_embed_ids'].includes(key) && Array.isArray(item)) item.forEach(id => ids.add(id));
      if (['execution_id', 'task_id'].includes(key) && typeof item === 'string') executions.add(item);
      discover(item);
    }
  } else if (typeof value === 'string') {
    // Message fences may use any JSON whitespace. Match only the explicit
    // embed identifier field, with a bounded UUID value, rather than treating
    // every message/chat UUID as an embed read request.
    for (const match of value.matchAll(/"(?:embed_id|target_embed_id)"\s*:\s*"([0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12})"/gi)) ids.add(match[1]);
    for (const match of value.matchAll(/\b[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\b/gi)) {
      // IDs in the saved assistant response are discovery hints only. Status is
      // authenticated below and must point back to a created code embed.
      executions.add(match[0]);
      if (value.includes(`embed:${match[0]}`)) ids.add(match[0]);
    }
  }
}
discover(loaded.messages);
const embeds = [], errors = [];
const seenIds = new Set();
while (seenIds.size < 40) {
  const id = [...ids].find(candidate => !seenIds.has(candidate));
  if (!id) break;
  seenIds.add(id);
  try {
    const embed = await client.getEmbed(id, { chatId: loaded.chat.id, personal: true });
    embeds.push(embed); discover(embed.content);
  } catch { errors.push({ stage: 'embed_read', id }); }
}
const codeIds = new Set(embeds.filter(e => e.content && typeof e.content.code === 'string').map(e => e.embedId));
const statuses = [];
for (const id of [...executions].slice(0, 50)) {
  if (!/^[0-9a-f-]{36}$/i.test(id)) continue;
  try {
    const status = await client.getCodeRunStatus(`/v1/code/run/${id}`);
    if (codeIds.has(status.target_embed_id)) statuses.push(status);
  } catch { /* Non-execution UUIDs are normal discovery candidates. */ }
}
const blocked = /(?:key|nonce|token|cookie|password|s3_base_url|s3_key|download_url|native_render_payload)/i;
function safe(value) {
  if (Array.isArray(value)) return value.map(safe);
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value)
    .filter(([key]) => !blocked.test(key)).map(([key, item]) => [key, safe(item)]));
  return value;
}
process.stdout.write(JSON.stringify(safe({ chat: loaded.chat, messages: loaded.messages, embeds, executions: statuses, errors })) + '\n');
