/** Connects the terminal model picker to the encrypted, owner-scoped chat preference service. */
import { createHash } from "node:crypto";
import type { OpenMatesClient } from "./client.js";
import type { ChatModelPreferences, ChatModelPreferenceState } from "./chatModelPreferences.js";
import { captureTuiWorkspaceOwner } from "./tuiCachedWorkspaces.js";
import type { TuiState } from "./tuiRenderer.js";
import {
  createTuiModelSelectorState, handleTuiModelSelectorAction, handleTuiModelSelectorKey, openTuiModelSelector,
  restoreTuiModelSelection, tuiModelSelectionForSend, type TuiModelSelectorContext,
} from "./tuiModelSelector.js";
import type { TerminalKey } from "./tuiTerminal.js";
import { MODEL_ALIASES } from "./mentions.js";

export function isTuiAiComposer(state: TuiState): boolean {
  return state.workspace === "chats" && ["start", "chats", "chat", "example"].includes(state.screen);
}
const chatIdForView = (state: TuiState) => state.screen === "chat" ? state.activeChatId : null;

function ownerId(client: OpenMatesClient): string | null {
  if (!client.hasSession()) return null;
  try {
    const session = client.getSession();
    return createHash("sha256").update(JSON.stringify([session.apiUrl, session.hashedEmail, session.createdAt,
      session.masterKeyExportedB64, client.resolveTeamContext()])).digest("hex");
  } catch { return null; }
}

export function createTuiModelSelectorShell(args: {
  state: TuiState; client: OpenMatesClient; preferences: ChatModelPreferences; render: () => void;
}) {
  const { state, client, preferences, render } = args;
  let unsubscribe: (() => void) | null = null;
  let ownerFence: (() => boolean) | null = null;
  let waitingForChat = false;
  const clearSubscription = () => { unsubscribe?.(); unsubscribe = null; };
  const context = (): TuiModelSelectorContext | null => {
    if (!state.modelSelector || !ownerFence) return null;
    return {
      state: state.modelSelector,
      owner: () => ownerId(client) ?? "signed-out",
      chatId: () => chatIdForView(state),
      isOwnerCurrent: ownerFence,
      loadCatalog: () => preferences.catalog(),
      restoreSelection: async () => {
        const chatId = chatIdForView(state);
        if (!chatId) return state.modelSelector?.selection ?? "auto";
        const restored = await preferences.restore(chatId);
        if (!restored.restored) throw new Error("Could not restore this chat's model selection.");
        return restored.selection;
      },
      persistSelection: async (selection) => {
        const chatId = chatIdForView(state);
        if (!chatId) return selection;
        return (await preferences.select(chatId, selection)).selection;
      },
      render,
    };
  };
  const updateFromSync = (chatId: string, preference: ChatModelPreferenceState) => {
    const picker = state.modelSelector;
    if (!picker || picker.chatId !== chatId || !ownerFence?.() || !preference.restored) return;
    if (picker.selection === preference.selection) return;
    picker.selection = preference.selection;
    if (picker.catalogAuthoritative && preference.selection !== "auto" &&
      !picker.models.some((model) => model.id === preference.selection && model.available)) {
      picker.ready = false;
      picker.error = "Selected model availability changed. Retry or choose Auto.";
      void preferences.validate(chatId, Object.assign(picker.models.map(model=>({...model,description:model.description??""})), { authoritative: true }))
        .then((validated) => {
          if (state.modelSelector !== picker || picker.chatId !== chatId || !ownerFence?.()) return;
          picker.selection = validated.selection;
          picker.ready = true;
          picker.error = validated.reset ? "The selected model is unavailable. Reset to Auto." : null;
          render();
        }).catch(() => { if (state.modelSelector === picker && ownerFence?.()) render(); });
    }
    render();
  };
  const subscribe = (chatId: string | null) => {
    clearSubscription();
    if (chatId) unsubscribe = preferences.subscribe(chatId, (preference) => updateFromSync(chatId, preference));
  };
  const restoreAndReconcile = async (ctx: TuiModelSelectorContext) => {
    await restoreTuiModelSelection(ctx);
    const chatId = ctx.state.chatId;
    if (chatId && state.modelSelector === ctx.state && ownerFence?.()) {
      const latest = preferences.current(chatId);
      if (latest.restored) updateFromSync(chatId, latest);
    }
  };

  /** Called before each scheduled render; starts one fenced restore per view. */
  const sync = () => {
    const owner = ownerId(client);
    if (!owner || !isTuiAiComposer(state)) {
      clearSubscription(); ownerFence = null; state.modelSelector = null; return;
    }
    const chatId = chatIdForView(state);
    if (state.modelSelector?.owner === owner && state.modelSelector.chatId === chatId && ownerFence?.()) {
      if (!waitingForChat || state.headerState !== "ready") return;
      waitingForChat = false;
      const ctx = context();
      if (ctx) queueMicrotask(() => { if (state.modelSelector === ctx.state && ownerFence?.()) void restoreAndReconcile(ctx); });
      return;
    }
    clearSubscription();
    state.modelSelector = createTuiModelSelectorState(owner, chatId);
    ownerFence = captureTuiWorkspaceOwner(client);
    subscribe(chatId);
    const picker = state.modelSelector;
    waitingForChat = !!chatId && state.headerState !== "ready";
    if (waitingForChat) return;
    queueMicrotask(() => {
      if (state.modelSelector !== picker || !ownerFence?.()) return;
      const ctx = context();
      if (ctx) void restoreAndReconcile(ctx);
    });
  };

  const open = async () => {
    sync();
    if (!isTuiAiComposer(state) || !client.hasSession()) {
      state.status = "Sign in to choose an exact AI model."; render(); return;
    }
    if (waitingForChat) { state.status = "Wait until this chat has opened before choosing a model."; render(); return; }
    const ctx = context();
    if (ctx) await openTuiModelSelector(ctx);
  };
  const action = async (arg: string) => {
    const ctx = context();
    if (ctx) await handleTuiModelSelectorAction(ctx, arg);
  };
  const key = async (chunk: string, pressed: TerminalKey): Promise<boolean> => {
    const ctx = context();
    return ctx ? handleTuiModelSelectorKey(ctx, chunk, pressed) : false;
  };
  const selectionForSend = (): string | null => {
    if (!client.hasSession()) return "auto";
    if (typeof client.getSession !== "function") return "auto";
    sync();
    if (waitingForChat) return null;
    return state.modelSelector ? tuiModelSelectionForSend(state.modelSelector) : null;
  };
  /** Resolve editor model mentions against the live catalog and keep routing tokens out of the visible draft. */
  const consumeMention = async (message: string, complete = false): Promise<{ message: string; blocked: boolean }> => {
    if (!client.hasSession() || !isTuiAiComposer(state)) return { message, blocked: false };
    const match = /(^|\s)@([^\s@]+)(?=\s|$)/g;
    for (const found of message.matchAll(match)) {
      const token = found[2], lower = token.toLowerCase();
      const end = (found.index ?? 0) + found[0].length;
      if (!complete && end === message.length) continue;
      const picker = state.modelSelector;
      const isAlias = Object.hasOwn(MODEL_ALIASES, lower);
      const isWire = lower.startsWith("ai-model:") || lower.startsWith("best-model:");
      const normalized = lower.replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
      const knownName = picker?.models.some((item) => item.name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") === normalized);
      if (!isAlias && !isWire && !knownName) continue;
      if (waitingForChat) { state.status = "Wait until this chat has opened before choosing a model."; render(); return { message, blocked: true }; }
      if (!picker?.ready || picker.busy) {
        state.status = "Model selection is loading. Your draft is kept."; render();
        return { message, blocked: true };
      }
      const targetId = isAlias ? MODEL_ALIASES[lower] : lower.startsWith("best-model:")
        ? MODEL_ALIASES[lower.slice(11)] : null;
      const wire = lower.startsWith("ai-model:") ? lower.slice(9).split(":") : null;
      const selected = picker.models.find((item) => item.available && (targetId ? item.id.endsWith(`/${targetId}`)
        : wire ? item.providerId === wire[1] && item.id === `${wire[1]}/${wire[0]}`
          : item.name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") === normalized));
      if (!selected) {
        state.status = `Model ${token} is unavailable. Choose an available model or Auto.`; render();
        return { message, blocked: true };
      }
      const ctx = context();
      if (!ctx) return { message, blocked: true };
      const owner = picker.owner, chatId = picker.chatId, generation = picker.generation;
      picker.busy = true; render();
      try {
        const saved = await ctx.persistSelection(selected.id);
        if (state.modelSelector !== picker || !ownerFence?.() || picker.owner !== owner || picker.chatId !== chatId || picker.generation !== generation)
          return { message, blocked: true };
        picker.selection = saved; picker.ready = true;
        const start = (found.index ?? 0) + found[1].length;
        let removedStart = start, removedEnd = start + token.length + 1;
        let before = message.slice(0, removedStart), after = message.slice(removedEnd);
        if (/\s$/.test(before) && /^\s/.test(after) || !before && /^\s/.test(after)) { after = after.slice(1); removedEnd++; }
        else if (!after && /\s$/.test(before)) { before = before.slice(0, -1); removedStart--; }
        const cleaned = before + after;
        if (state.input === message) {
          const cursor = state.inputCursor ?? message.length;
          state.input = cleaned;
          state.inputCursor = cursor <= removedStart ? cursor : cursor >= removedEnd
            ? cursor - (removedEnd - removedStart) : removedStart;
          state.drafts[state.activeChatId ?? "new"] = cleaned;
        }
        state.status = null; render();
        return { message: cleaned, blocked: false };
      } catch (error) {
        state.status = error instanceof Error ? error.message : String(error); render();
        return { message, blocked: true };
      } finally { if (state.modelSelector === picker) { picker.busy = false; render(); } }
    }
    return { message, blocked: false };
  };
  /** Preserve a new-chat choice through its optimistic UUID without writing a draft-only preference. */
  const adoptNewChat = (chatId: string) => {
    const picker = state.modelSelector;
    if (!picker || picker.chatId !== null || !ownerFence?.()) return;
    picker.chatId = chatId; picker.generation++;
    subscribe(chatId);
  };
  const persistCreatedChat = async (chatId: string, selection: string) => {
    if (selection === "auto" || !ownerFence?.()) return;
    const picker = state.modelSelector;
    if (!picker || picker.chatId !== chatId) return;
    try {
      const saved = await preferences.select(chatId, selection);
      if (state.modelSelector === picker && ownerFence?.()) { picker.selection = saved.selection; render(); }
    } catch (error) {
      if (state.modelSelector === picker && ownerFence?.()) {
        picker.error = error instanceof Error ? error.message : String(error);
        state.status = "Model preference could not sync. Your chat remains available.";
        render();
      }
    }
  };
  return { sync, open, action, key, selectionForSend, consumeMention, adoptNewChat, persistCreatedChat,
    close: () => { const ctx = context(); if (ctx?.state.open) handleTuiModelSelectorAction(ctx, "close"); },
    dispose: clearSubscription };
}

export type TuiModelSelectorShell = ReturnType<typeof createTuiModelSelectorShell>;
