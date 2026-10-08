import assert from "node:assert/strict";
import { test } from "node:test";
import { cells, lineText, stripAnsi } from "../src/tuiText.js";
import { createInitialTuiState } from "../src/tuiRenderer.js";
import { renderWorkspaceFrame } from "../src/tuiLayout.js";
import {
  createTuiModelSelectorState, handleTuiModelSelectorAction, handleTuiModelSelectorKey, openTuiModelSelector,
  renderTuiModelSelector, restoreTuiModelSelection, syncTuiModelSelectorOwner, tuiModelSelectionForSend,
  tuiModelTriggerLabel, type TuiModelCatalog, type TuiModelEntry, type TuiModelSelectorContext,
} from "../src/tuiModelSelector.js";

const models: TuiModelEntry[] = [
  { id: "openai/astra", name: "GPT Astra", providerId: "openai", providerName: "OpenAI", providerBrandName: "ChatGPT", capability: "max", releaseDate: "2026-10-01", available: true, description: "Deep reasoning" },
  { id: "openai/sol", name: "GPT Sol", providerId: "openai", providerName: "OpenAI", providerBrandName: "ChatGPT", capability: "high", releaseDate: "2026-09-01", available: true },
  { id: "openai/hidden", name: "Hidden", providerId: "openai", providerName: "OpenAI", capability: "low", available: false },
  { id: "anthropic/claude", name: "Claude", providerId: "anthropic", providerName: "Anthropic", capability: "high", available: true },
  { id: "google/gemini", name: "Gemini", providerId: "google", providerName: "Google", capability: "high", available: true },
  { id: "mistral/mistral", name: "Mistral", providerId: "mistral", providerName: "Mistral", capability: "medium", available: true },
  { id: "alibaba/qwen", name: "Qwen", providerId: "alibaba", providerName: "Alibaba", capability: "medium", available: true },
];
function setup(overrides: Partial<TuiModelSelectorContext> = {}) {
  const state = createTuiModelSelectorState("alice", "chat-1");
  const writes: string[] = [];
  let draws = 0, closes = 0;
  const ctx: TuiModelSelectorContext = {
    state, owner: "alice", chatId: "chat-1", loadCatalog: async () => models,
    restoreSelection: async () => "auto", persistSelection: async (selection) => { writes.push(selection); return selection; },
    render: () => { draws++; }, close: () => { closes++; }, ...overrides,
  };
  return { state, ctx, writes, draws: () => draws, closes: () => closes };
}
const shown = (state: ReturnType<typeof createTuiModelSelectorState>) => renderTuiModelSelector(state, 48).map(lineText).join("\n");

// contract-test: supporting surface=cli assertions=ai-model-routing.composer.responsive-actions
test("open picker stays within every terminal row at narrow widths", async () => {
  const { state: picker, ctx } = setup();
  await openTuiModelSelector(ctx);
  const state = createInitialTuiState();
  state.signedIn = true; state.focus = "composer"; state.modelSelector = picker;
  for (const width of [6, 10, 16, 24]) {
    const rows = stripAnsi(renderWorkspaceFrame(state, width, 16, [])).split("\n");
    assert.ok(rows.every(row => cells(row) === width), `picker must fit width ${width}`);
  }
});

// contract-test: supporting surface=cli assertions=ai-model-routing.composer.responsive-actions,ai-model-routing.surface.semantic-parity
test("provider-first picker shows Auto, available providers, capability, details and compact trigger", async () => {
  const { state, ctx } = setup();
  await openTuiModelSelector(ctx);
  assert.match(shown(state), /Auto select/);
  assert.match(shown(state), /ChatGPT/);
  assert.match(shown(state), /Show 1 more providers/);
  assert.doesNotMatch(shown(state), /Hidden/);
  await handleTuiModelSelectorAction(ctx, "provider:openai");
  assert.ok(shown(state).indexOf("GPT Astra") < shown(state).indexOf("GPT Sol"));
  assert.match(shown(state), /GPT Astra.*\[max\]/);
  await handleTuiModelSelectorAction(ctx, "details:openai/astra");
  assert.match(shown(state), /Deep reasoning/);
  await handleTuiModelSelectorAction(ctx, "back");
  await handleTuiModelSelectorAction(ctx, "back");
  await handleTuiModelSelectorAction(ctx, "more");
  assert.match(shown(state), /Alibaba/);
  await handleTuiModelSelectorAction(ctx, "provider:alibaba");
  assert.match(shown(state), /Qwen/);
  assert.equal(tuiModelTriggerLabel(state, 8), "AI");
});

// contract-test: supporting surface=cli assertions=ai-model-routing.chat-selection.encrypted-user-chat-scope,ai-model-routing.precedence.chat-over-tier-over-auto
test("exact choice persists through the adapter, and selecting it again returns to Auto", async () => {
  const { state, ctx, writes, closes } = setup();
  await openTuiModelSelector(ctx);
  await handleTuiModelSelectorAction(ctx, "provider:openai");
  await handleTuiModelSelectorAction(ctx, "select:openai/astra");
  assert.deepEqual(writes, ["openai/astra"]);
  assert.equal(state.selection, "openai/astra");
  assert.equal(tuiModelSelectionForSend(state), "openai/astra");
  assert.match(tuiModelTriggerLabel(state), /GPT Astra/);
  assert.equal(closes(), 1);
  await openTuiModelSelector(ctx);
  assert.equal(state.page, "models", "exact selection opens its provider as on the web");
  await handleTuiModelSelectorAction(ctx, "back");
  assert.equal(state.page, "providers");
  await handleTuiModelSelectorKey(ctx, "", { name: "return" });
  assert.deepEqual(writes, ["openai/astra", "auto"]);
  assert.equal(state.selection, "auto");
});

// contract-test: supporting surface=cli assertions=ai-model-routing.unavailable.notify-reset-auto,ai-model-routing.chat-selection.encrypted-user-chat-scope
test("unavailable restored model visibly resets and persists Auto before sending", async () => {
  const { state, ctx, writes } = setup({ restoreSelection: async () => "openai/hidden" });
  assert.equal(tuiModelSelectionForSend(state), null);
  await restoreTuiModelSelection(ctx);
  assert.equal(state.selection, "auto");
  assert.deepEqual(writes, ["auto"]);
  assert.equal(tuiModelSelectionForSend(state), "auto");
  assert.match(shown(state), /selected model is unavailable/);
});

// contract-test: supporting surface=cli assertions=ai-model-routing.chat-selection.encrypted-user-chat-scope,ai-model-routing.unavailable.notify-reset-auto
test("uncached restore failure blocks send until Retry or explicit Auto", async () => {
  const { state, ctx, writes } = setup({ restoreSelection: async () => { throw new Error("offline"); } });
  await openTuiModelSelector(ctx);
  assert.equal(state.ready, false);
  assert.equal(tuiModelSelectionForSend(state), null);
  assert.match(shown(state), /Retry model selection/);
  assert.match(shown(state), /Use Auto instead/);
  assert.deepEqual(writes, [], "unknown exact preference must not be silently overwritten");
  await handleTuiModelSelectorAction(ctx, "select:auto");
  assert.deepEqual(writes, ["auto"]);
  assert.equal(state.selection, "auto");
  assert.equal(tuiModelSelectionForSend(state), "auto", "explicit Auto releases the send gate after failed restore");
});

// contract-test: supporting surface=cli assertions=ai-model-routing.chat-selection.encrypted-user-chat-scope,ai-model-routing.unavailable.notify-reset-auto
test("catalog failure does not reset a saved exact model without availability evidence", async () => {
  const { state, ctx, writes } = setup({ loadCatalog: async () => { throw new Error("offline"); }, restoreSelection: async () => "openai/astra" });
  await restoreTuiModelSelection(ctx);
  assert.equal(state.selection, "openai/astra");
  assert.equal(state.ready, false);
  assert.equal(tuiModelSelectionForSend(state), null);
  assert.deepEqual(writes, []);
  assert.match(shown(state), /Model availability could not be checked/);
  const auto = setup({ loadCatalog: async () => { throw new Error("offline"); } });
  await restoreTuiModelSelection(auto.ctx);
  assert.equal(tuiModelSelectionForSend(auto.state), "auto");
  assert.match(shown(auto.state), /Model list could not refresh/);
});

// contract-test: supporting surface=cli assertions=ai-model-routing.unavailable.notify-reset-auto,ai-model-routing.chat-selection.encrypted-user-chat-scope
test("provisional offline catalog cannot prove a saved exact model is unavailable", async () => {
  const cached = models.filter((model) => model.id !== "openai/astra") as TuiModelCatalog;
  cached.authoritative = false;
  const { state, ctx, writes } = setup({ loadCatalog: async () => cached, restoreSelection: async () => "openai/astra" });
  await restoreTuiModelSelection(ctx);
  assert.equal(state.selection, "openai/astra");
  assert.equal(state.ready, false);
  assert.equal(tuiModelSelectionForSend(state), null);
  assert.deepEqual(writes, []);
  assert.match(shown(state), /Cached model list cannot verify/);
});

// contract-test: supporting surface=cli assertions=ai-model-routing.chat-selection.encrypted-user-chat-scope,terminal-pointer.lifecycle-selection-safe
test("pending catalog response cannot cross owner or chat context, and picker consumes typing", async () => {
  let finish!: (entries: TuiModelEntry[]) => void;
  const { state, ctx } = setup({ loadCatalog: () => new Promise((resolve) => { finish = resolve; }) });
  const opening = openTuiModelSelector(ctx);
  assert.equal(state.ready, false);
  assert.equal(tuiModelSelectionForSend(state), null);
  ctx.owner = "bob"; ctx.chatId = "chat-2";
  syncTuiModelSelectorOwner(ctx);
  finish(models);
  await opening;
  assert.equal(state.owner, "bob");
  assert.equal(state.models.length, 0);
  assert.equal(state.selection, "auto");
  const next = setup();
  await openTuiModelSelector(next.ctx);
  assert.equal(await handleTuiModelSelectorKey(next.ctx, "hello", { name: "paste" }), true);
  assert.equal(next.state.selection, "auto");
  await handleTuiModelSelectorKey(next.ctx, "", { name: "escape" });
  assert.equal(next.state.open, false);
  assert.equal(next.closes(), 1);
});

// contract-test: supporting surface=cli assertions=ai-model-routing.chat-selection.encrypted-user-chat-scope
test("failed selection keeps the previous model and lets the user retry", async () => {
  const { state, ctx } = setup({ persistSelection: async () => { throw new Error("offline"); } });
  await openTuiModelSelector(ctx);
  await handleTuiModelSelectorAction(ctx, "provider:openai");
  await handleTuiModelSelectorAction(ctx, "select:openai/astra");
  assert.equal(state.selection, "auto");
  assert.equal(state.open, true);
  assert.match(shown(state), /Error: offline/);
});
