/**
 * Real dev REST/WebSocket proof for memory-consent persistence convergence.
 * Uses the existing paired owner session and an explicitly supplied fictional
 * source chat. Forks only its first user message; never starts AI inference.
 * Request ciphertext is written twice with the shared client message identity.
 * No memory content, credentials, keys or response ciphertext are printed.
 * The isolated fork remains available for inspection after the test.
 */
import { it } from "node:test";
import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { OpenMatesClient } from "../src/client.js";
import { encryptWithAesGcmCombined, decryptWithAesGcmCombined } from "../src/crypto.js";
import { buildMemoryRequestMessage } from "../../ui/src/utils/appMemoryRequests.js";

const DEV_API = "https://api.dev.openmates.org";
const sourceChat = process.env.OPENMATES_MEMORY_CONSENT_SOURCE_CHAT;
const POLL_INTERVAL_MS = 1000;
const MAX_PERSISTENCE_POLLS = 20;

// contract-test: direct surface=rest_api assertions=app-memories.conversation.request-convergence,app-memories.privacy.client-encrypted
it("persists one encrypted consent request across concurrent clients and retry on dev", { skip: !sourceChat, timeout: 90000 }, async () => {
  const client = OpenMatesClient.load({ apiUrl: DEV_API });
  const source = await client.getChatMessagesWindow(sourceChat!);
  const firstUser = source.messages.find(message => message.role === "user");
  assert.ok(firstUser, "The authorized fictional source must have a user message");
  const fork = await client.forkChat({ chatId: sourceChat!, fromMessageId: firstUser.id, title: "Memory consent protocol verification" });
  console.log(JSON.stringify({ verification_chat_id: fork.chat_id }));
  const { chatKey } = await client.resolveChatKeyForContext(fork.chat_id);
  const history = await client.getChatMessagesWindow(fork.chat_id);
  const userMessageId = history.messages.find(message => message.role === "user")!.clientMessageId;
  const requestId = randomUUID();
  const message = buildMemoryRequestMessage({ userMessageId, requestId, requestedKeys: ["mail-writing_styles"], entryCounts: new Map([["mail-writing_styles", 1]]), createdAt: Math.floor(Date.now() / 1000) });
  const first = await client.openLocalConnectorWebSocket();
  const peer = OpenMatesClient.load({ apiUrl: DEV_API });
  const second = await peer.openLocalConnectorWebSocket();
  try {
    const send = async (ws: typeof first) => {
      const confirmation = ws.waitForMessage("system_message_confirmed", payload => (payload as { message_id?: string }).message_id === requestId, 20000);
      await ws.sendAsync("chat_system_message_added", { chat_id: fork.chat_id, message: {
        message_id: message.message_id, role: message.role, created_at: message.created_at,
        encrypted_content: await encryptWithAesGcmCombined(message.content, chatKey),
      } });
      await confirmation;
    };
    await Promise.all([send(first), send(second)]);
    await send(first);
    let rows: Record<string, unknown>[] = [];
    for (let attempt = 0; attempt < MAX_PERSISTENCE_POLLS; attempt++) {
      const result = await client.settingsGet(`/v1/chats/${fork.chat_id}/messages/window?direction=latest&limit=30`) as { messages: Array<string | Record<string, unknown>> };
      rows = result.messages.map(row => typeof row === "string" ? JSON.parse(row) : row).filter(row => row.client_message_id === requestId);
      if (rows.length) break;
      await new Promise(resolve => setTimeout(resolve, POLL_INTERVAL_MS));
    }
    assert.equal(rows.length, 1, "One durable request row after concurrent writes and retry");
    assert.equal(rows[0].content, undefined, "REST returns ciphertext, not plaintext request content");
    const request = JSON.parse(await decryptWithAesGcmCombined(String(rows[0].encrypted_content), chatKey));
    assert.equal(request.categories[0].entryCount, 1);
    assert.equal(request.action, undefined, "Persistence does not grant consent");
    console.log(JSON.stringify({ chat_id: fork.chat_id, request_id: requestId, persisted_rows: rows.length, entry_count: 1, inference_started: false }));
  } finally {
    first.close(); second.close();
  }
});
