import assert from "node:assert/strict";
import { test } from "node:test";
import { createInitialTuiState } from "../src/tuiRenderer.js";
import { createTuiModelSelectorShell } from "../src/tuiModelSelectorShell.js";
import type { ChatModelCatalog, ChatModelPreferences } from "../src/chatModelPreferences.js";
import type { OpenMatesClient } from "../src/client.js";

const catalog = Object.assign([
  { id: "openai/gpt-6-astra", name: "GPT 6 Astra", providerId: "openai", providerName: "OpenAI", description: "", available: true },
  { id: "qwen/qwen3-235b-a22b-2507", name: "Qwen Fast", providerId: "qwen", providerName: "Qwen", description: "", available: true },
], { authoritative: true }) as ChatModelCatalog;
function fixture() {
  const state = createInitialTuiState();
  state.signedIn = true; state.workspace = "chats"; state.screen = "chat"; state.activeChatId = "chat-one"; state.headerState = "ready";
  let session = { apiUrl: "https://example.test", hashedEmail: "alice", createdAt: "1", masterKeyExportedB64: "YWJj", activeTeamId: null };
  const client = { apiUrl: session.apiUrl, hasSession: () => !!session, getSession: () => session,
    resolveTeamContext: () => null } as unknown as OpenMatesClient;
  const writes: Array<[string, string]> = [], subscribed: string[] = [];
  const prefs = { catalog: async () => catalog,
    restore: async (_chatId: string) => ({ selection: "auto", pending: false, restored: true }),
    current: (_chatId: string) => ({ selection: "auto", pending: false, restored: false }),
    select: async (chatId: string, selection: string) => { writes.push([chatId, selection]); return { selection, pending: false, restored: true }; },
    subscribe: (chatId: string) => { subscribed.push(chatId); return () => {}; },
    validate: async () => ({ selection: "auto", pending: false, restored: true, reset: true }),
  } as unknown as ChatModelPreferences;
  let draws = 0;
  const shell = createTuiModelSelectorShell({ state, client, preferences: prefs, render: () => { draws++; } });
  const settle = async () => { await Promise.resolve(); await new Promise(resolve => setImmediate(resolve)); };
  return { state, shell, writes, subscribed, settle, draws: () => draws, signOut: () => { session = null as never; } };
}

// contract-test: supporting surface=cli assertions=ai-model-routing.chat-selection.encrypted-user-chat-scope,ai-model-routing.surface.semantic-parity
test("restored chat model follows the active chat and cannot leak into a new chat", async () => {
  const { state, shell, subscribed, settle } = fixture();
  shell.sync(); await settle();
  assert.equal(shell.selectionForSend(), "auto");
  state.activeChatId = "chat-two"; shell.sync(); await settle();
  assert.deepEqual(subscribed, ["chat-one", "chat-two"]);
  assert.equal(state.modelSelector?.chatId, "chat-two");
  assert.equal(shell.selectionForSend(), "auto");
  shell.dispose();
});

// contract-test: supporting surface=cli assertions=ai-model-routing.precedence.chat-over-tier-over-auto,ai-model-routing.surface.semantic-parity
test("editor @best chooses an available catalog model and removes only its visible token", async () => {
  const { state, shell, writes, settle } = fixture();
  shell.sync(); await settle();
  state.input = "Please review @best this draft";
  state.inputCursor = state.input.length;
  const result = await shell.consumeMention(state.input, true);
  assert.equal(result.blocked, false);
  assert.equal(result.message, "Please review this draft");
  assert.equal(state.input, result.message);
  assert.equal(state.modelSelector?.selection, "openai/gpt-6-astra");
  assert.deepEqual(writes, [["chat-one", "openai/gpt-6-astra"]]);
  assert.equal(shell.selectionForSend(), "openai/gpt-6-astra");
  shell.dispose();
});

// contract-test: supporting surface=cli assertions=ai-model-routing.unavailable.notify-reset-auto,ai-model-routing.chat-selection.encrypted-user-chat-scope
test("unavailable explicit model keeps the draft and signed-out owner clears the picker", async () => {
  const { state, shell, writes, settle, signOut } = fixture();
  shell.sync(); await settle();
  const result = await shell.consumeMention("Use @ai-model:missing:openai please", true);
  assert.equal(result.blocked, true);
  assert.equal(result.message, "Use @ai-model:missing:openai please");
  assert.deepEqual(writes, []);
  signOut(); shell.sync();
  assert.equal(state.modelSelector, null);
  shell.dispose();
});

// contract-test: supporting surface=cli assertions=ai-model-routing.chat-selection.encrypted-user-chat-scope
test("an unconfirmed chat cannot write a preference; hydration begins after metadata confirms it", async () => {
  const { state, shell, writes, settle } = fixture();
  state.headerState = "loading";
  shell.sync(); await settle();
  assert.equal(shell.selectionForSend(), null);
  await shell.open();
  assert.equal(state.modelSelector?.open, false);
  assert.equal((await shell.consumeMention("@best go", true)).blocked, true);
  assert.deepEqual(writes, []);
  state.headerState = "ready"; shell.sync(); await settle();
  assert.equal(shell.selectionForSend(), "auto");
  shell.dispose();
});
