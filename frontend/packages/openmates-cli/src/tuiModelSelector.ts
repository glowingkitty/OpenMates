/** Terminal composer model picker. Catalog and preference storage are supplied by the client adapter. */
import { terminalText, truncateCells, wrapCells, type TuiLine } from "./tuiText.js";

export type TuiModelCapability = "low" | "medium" | "high" | "max";
export type TuiModelEntry = {
  /** Canonical provider/model selection identity. */
  id: string;
  name: string;
  providerId: string;
  providerName: string;
  providerBrandName?: string;
  providerOrder?: number;
  capability?: TuiModelCapability;
  releaseDate?: string;
  description?: string;
  /** False when disabled by the user or without a healthy permitted route. */
  available: boolean;
};
/** Cached offline catalogs are provisional and cannot prove a model was removed. */
export type TuiModelCatalog = TuiModelEntry[] & { authoritative?: boolean };

export type TuiModelSelectorState = {
  owner: string;
  chatId: string | null;
  generation: number;
  open: boolean;
  ready: boolean;
  busy: boolean;
  selection: string;
  models: TuiModelEntry[];
  catalogAuthoritative: boolean | null;
  page: "providers" | "more" | "models" | "details";
  providerId: string | null;
  detailId: string | null;
  selectedIndex: number;
  error: string | null;
};

export type TuiModelSelectorContext = {
  state: TuiModelSelectorState;
  owner: string | (() => string);
  chatId: string | null | (() => string | null);
  isOwnerCurrent?: () => boolean;
  loadCatalog: () => Promise<TuiModelCatalog>;
  restoreSelection: () => Promise<string>;
  persistSelection: (selection: string) => Promise<string>;
  render: () => void;
  close?: () => void;
};

const currentOwner = (ctx: TuiModelSelectorContext) => typeof ctx.owner === "function" ? ctx.owner() : ctx.owner;
const currentChatId = (ctx: TuiModelSelectorContext) => typeof ctx.chatId === "function" ? ctx.chatId() : ctx.chatId;
const current = (ctx: TuiModelSelectorContext, owner: string, chatId: string | null, generation: number) =>
  ctx.state.owner === owner && ctx.state.chatId === chatId && currentOwner(ctx) === owner && currentChatId(ctx) === chatId
  && ctx.state.generation === generation && (ctx.isOwnerCurrent?.() ?? true);
const clean = (value: string) => terminalText(value).replace(/\s+/g, " ").trim();
const modelValue = (model: TuiModelEntry) => model.id;
const rank: Record<TuiModelCapability, number> = { low: 0, medium: 1, high: 2, max: 3 };

export function createTuiModelSelectorState(owner: string, chatId: string | null = null): TuiModelSelectorState {
  return { owner, chatId, generation: 0, open: false, ready: false, busy: false, selection: "auto", models: [], catalogAuthoritative: null,
    page: "providers", providerId: null, detailId: null, selectedIndex: 0, error: null };
}

/** Forget account-scoped model names and preferences before a different owner can render. */
export function syncTuiModelSelectorOwner(ctx: TuiModelSelectorContext): boolean {
  const owner = currentOwner(ctx), chatId = currentChatId(ctx);
  if (ctx.state.owner === owner && ctx.state.chatId === chatId && (ctx.isOwnerCurrent?.() ?? true)) return false;
  Object.assign(ctx.state, createTuiModelSelectorState(owner, chatId), { generation: ctx.state.generation + 1 });
  ctx.render();
  return true;
}

function usableModels(state: TuiModelSelectorState): TuiModelEntry[] {
  return state.models.filter((model) => model.available && model.id.startsWith(`${model.providerId}/`));
}

function providers(state: TuiModelSelectorState): Array<{ id: string; name: string }> {
  const byId = new Map<string, { id: string; name: string; order: number; index: number }>();
  for (const model of usableModels(state)) if (!byId.has(model.providerId)) byId.set(model.providerId,
    { id: model.providerId, name: model.providerBrandName || model.providerName,
      order: model.providerOrder ?? Number.MAX_SAFE_INTEGER, index: byId.size });
  return [...byId.values()].sort((a, b) => a.order - b.order || a.index - b.index).map(({ id, name }) => ({ id, name }));
}

function providerModels(state: TuiModelSelectorState): TuiModelEntry[] {
  return usableModels(state).filter((model) => model.providerId === state.providerId)
    .sort((a, b) => (b.releaseDate ?? "").localeCompare(a.releaseDate ?? "") || (rank[b.capability ?? "low"] - rank[a.capability ?? "low"]) || a.name.localeCompare(b.name));
}

function selectedModel(state: TuiModelSelectorState): TuiModelEntry | undefined {
  return usableModels(state).find((model) => modelValue(model) === state.selection);
}

export function tuiModelTriggerLabel(state: TuiModelSelectorState, width = 24): string {
  if (!state.ready) return width < 12 ? "AI…" : "Model: Loading…";
  const model = selectedModel(state);
  if (width < 12) return model ? "AI*" : "AI";
  return truncateCells(`Model: ${model?.name ?? "Auto"} ▾`, width);
}

/** Null means send must wait for preference restoration or catalog validation. */
export function tuiModelSelectionForSend(state: TuiModelSelectorState): string | null {
  if (!state.ready || state.busy) return null;
  return state.selection === "auto" || selectedModel(state) ? state.selection : null;
}

/** Restore both catalog and encrypted per-chat selection before exposing a model label. */
export async function restoreTuiModelSelection(ctx: TuiModelSelectorContext): Promise<void> {
  syncTuiModelSelectorOwner(ctx);
  const state = ctx.state, owner = currentOwner(ctx), chatId = currentChatId(ctx), generation = ++state.generation;
  state.ready = false; state.busy = true; state.error = null; ctx.render();
  try {
    const [catalogResult, selectionResult] = await Promise.allSettled([ctx.loadCatalog(), ctx.restoreSelection()]);
    if (!current(ctx, owner, chatId, generation)) return;
    if (catalogResult.status === "fulfilled") {
      state.models = catalogResult.value.filter((model) => model.id.startsWith(`${model.providerId}/`) && model.name && model.providerName);
      state.catalogAuthoritative = catalogResult.value.authoritative !== false;
    }
    if (selectionResult.status === "rejected") {
      state.error = "Model selection could not be restored. Retry or choose Auto.";
      return;
    }
    const selection = selectionResult.value;
    state.selection = selection;
    if (catalogResult.status === "rejected") {
      if (selection === "auto") {
        state.ready = true;
        state.error = "Model list could not refresh. Auto remains available.";
      } else if (selectedModel(state)) {
        state.ready = true;
        state.error = "Model list could not refresh. Showing cached model availability.";
      } else state.error = "Model availability could not be checked. Retry or choose Auto.";
      return;
    }
    const available = state.models.some((model) => model.available && modelValue(model) === selection);
    if (catalogResult.value.authoritative === false) {
      if (selection === "auto" || available) {
        state.ready = true;
        state.error = "Showing cached model availability. Refresh when online.";
      } else state.error = "Cached model list cannot verify this selection. Retry or choose Auto.";
      return;
    }
    if (selection !== "auto" && !available) {
      state.selection = "auto";
      state.error = "The selected model is unavailable. Reset to Auto.";
      await ctx.persistSelection("auto");
      if (!current(ctx, owner, chatId, generation)) return;
    }
    state.ready = true;
  } catch (error) {
    if (current(ctx, owner, chatId, generation)) state.error = clean(error instanceof Error ? error.message : String(error));
  } finally {
    if (current(ctx, owner, chatId, generation)) { state.busy = false; ctx.render(); }
  }
}

export async function openTuiModelSelector(ctx: TuiModelSelectorContext): Promise<void> {
  syncTuiModelSelectorOwner(ctx);
  const state = ctx.state;
  state.open = true; state.page = "providers"; state.providerId = null; state.detailId = null; state.selectedIndex = 0;
  ctx.render();
  if (!state.ready && !state.busy) await restoreTuiModelSelection(ctx);
  if (state.open && state.ready) {
    const model = selectedModel(state);
    if (model) { state.page = "models"; state.providerId = model.providerId; state.selectedIndex = 0; ctx.render(); }
  }
}

export function closeTuiModelSelector(ctx: TuiModelSelectorContext): void {
  ctx.state.open = false; ctx.state.page = "providers"; ctx.state.providerId = null; ctx.state.detailId = null;
  ctx.close?.(); ctx.render();
}

type PickerAction = { id: string; label: string; detail?: string };
function actions(state: TuiModelSelectorState): PickerAction[] {
  if (!state.ready) return [{ id: "retry", label: "Retry model selection" }, { id: "select:auto", label: "Use Auto instead" }];
  if (state.page === "details") {
    const model = usableModels(state).find((item) => modelValue(item) === state.detailId);
    return [{ id: "back", label: "Back to models" }, ...(model ? [{ id: `select:${modelValue(model)}`, label: state.selection === modelValue(model) ? "Use Auto instead" : `Use ${model.name}` }] : [])];
  }
  if (state.page === "models") return [{ id: "back", label: "Back to providers" },
    ...providerModels(state).flatMap((model): PickerAction[] => [
      { id: `select:${modelValue(model)}`, label: `${state.selection === modelValue(model) ? "●" : "○"} ${model.name}${model.capability ? `  [${model.capability}]` : ""}` },
      { id: `details:${modelValue(model)}`, label: `  About ${model.name}` },
    ])];
  const list = providers(state), shown = state.page === "more" ? list.slice(4) : list.slice(0, 4);
  return [...(state.page === "more" ? [{ id: "back", label: "Back to providers" }] : [{ id: "select:auto", label: `${state.selection === "auto" ? "●" : "○"} Auto select` }]),
    ...shown.map((provider) => ({ id: `provider:${provider.id}`, label: provider.name })),
    ...(state.page === "providers" && list.length > 4 ? [{ id: "more", label: `Show ${list.length - 4} more providers` }] : []),
    ...(state.page === "providers" && state.error ? [{ id: "retry", label: "Retry model list" }] : [])];
}

export async function handleTuiModelSelectorAction(ctx: TuiModelSelectorContext, action: string): Promise<boolean> {
  const state = ctx.state;
  if (action === "close") { closeTuiModelSelector(ctx); return true; }
  if (syncTuiModelSelectorOwner(ctx)) return true;
  if (!state.open || state.busy) return true;
  if (action === "retry") { await restoreTuiModelSelection(ctx); return true; }
  if (!state.ready && action !== "select:auto") return true;
  if (action === "back") {
    if (state.page === "details") state.page = "models";
    else if (state.page === "models" || state.page === "more") { state.page = "providers"; state.providerId = null; }
    else { closeTuiModelSelector(ctx); return true; }
    state.selectedIndex = 0; ctx.render(); return true;
  }
  if (action === "more" && state.page === "providers") { state.page = "more"; state.selectedIndex = 0; ctx.render(); return true; }
  if (action.startsWith("provider:")) {
    const id = action.slice(9);
    if (providers(state).some((provider) => provider.id === id)) { state.providerId = id; state.page = "models"; state.selectedIndex = 0; ctx.render(); }
    return true;
  }
  if (action.startsWith("details:")) {
    const id = action.slice(8);
    if (usableModels(state).some((model) => modelValue(model) === id && model.providerId === state.providerId)) {
      state.detailId = id; state.page = "details"; state.selectedIndex = 0; ctx.render();
    }
    return true;
  }
  if (action.startsWith("select:")) {
    const requested = action.slice(7);
    if (requested !== "auto" && !usableModels(state).some((model) => modelValue(model) === requested)) return true;
    const selection = requested === state.selection && requested !== "auto" ? "auto" : requested;
    const owner = currentOwner(ctx), chatId = currentChatId(ctx), generation = ++state.generation;
    state.busy = true; state.error = null; ctx.render();
    try {
      const persisted = await ctx.persistSelection(selection);
      if (!current(ctx, owner, chatId, generation)) return true;
      state.selection = persisted;
      if (persisted === "auto") state.ready = true;
      closeTuiModelSelector(ctx);
    } catch (error) {
      if (current(ctx, owner, chatId, generation)) state.error = clean(error instanceof Error ? error.message : String(error));
    } finally {
      if (current(ctx, owner, chatId, generation)) { state.busy = false; ctx.render(); }
    }
    return true;
  }
  return true;
}

export async function handleTuiModelSelectorKey(ctx: TuiModelSelectorContext, chunk: string, key: { name?: string; shift?: boolean; ctrl?: boolean; meta?: boolean }): Promise<boolean> {
  const state = ctx.state;
  if (!state.open) return false;
  const name = key.name?.toLowerCase() ?? "";
  if (name === "escape" && (state.busy || !state.ready)) { closeTuiModelSelector(ctx); return true; }
  if (name === "escape") return handleTuiModelSelectorAction(ctx, state.page === "providers" ? "close" : "back");
  if (syncTuiModelSelectorOwner(ctx) || state.busy) return true;
  const items = actions(state);
  if (name === "up" || name === "down" || name === "tab") {
    const step = name === "up" || name === "tab" && key.shift ? -1 : 1;
    state.selectedIndex = Math.max(0, Math.min(items.length - 1, state.selectedIndex + step)); ctx.render(); return true;
  }
  if (name === "return" || name === "enter" || name === "right") return handleTuiModelSelectorAction(ctx, items[state.selectedIndex]?.id ?? "");
  if (name === "left" || name === "backspace") return handleTuiModelSelectorAction(ctx, "back");
  if (!key.ctrl && !key.meta && /^[1-9]$/.test(chunk)) return handleTuiModelSelectorAction(ctx, items[Number(chunk) - 1]?.id ?? "");
  return true;
}

function line(label: string, action?: string, selected = false): TuiLine {
  return { text: label, ...(action ? { action: { kind: "command" as const, command: `/model-action ${action}` } } : {}),
    ...(selected ? { bold: true, color: "#89c4ff" } : {}) };
}

export function renderTuiModelSelector(state: TuiModelSelectorState, width: number): TuiLine[] {
  width = Math.max(16, width);
  const title = state.page === "models" ? providers(state).find((provider) => provider.id === state.providerId)?.name ?? "Models"
    : state.page === "details" ? "Model details" : state.page === "more" ? "More providers" : "Choose AI model";
  const lines: TuiLine[] = [line(truncateCells(title, width)), line("[Close model picker]", "close"), ""];
  if (state.error) lines.push(...wrapCells(`Error: ${state.error}`, width), "");
  if (!state.ready || state.busy) lines.push("Loading…", "");
  if (!state.ready && state.busy) return lines;
  if (state.page === "details") {
    const model = usableModels(state).find((item) => modelValue(item) === state.detailId);
    if (model) lines.push(...wrapCells(`${clean(model.name)} · ${clean(model.providerBrandName || model.providerName)}${model.capability ? ` · ${model.capability} capability` : ""}`, width),
      ...(model.description ? wrapCells(clean(model.description), width) : []), "");
  }
  const items = actions(state);
  if (!items.length) lines.push("No available models. Auto remains available.");
  for (const [index, item] of items.entries()) {
    const text = truncateCells(`${index + 1}. ${state.selectedIndex === index ? "› " : "  "}${clean(item.label)}`, width);
    lines.push(line(text, state.busy ? undefined : item.id, state.selectedIndex === index));
  }
  lines.push("", ...wrapCells("↑↓ or Tab choose · Enter select · Esc back/close", width));
  return lines;
}
