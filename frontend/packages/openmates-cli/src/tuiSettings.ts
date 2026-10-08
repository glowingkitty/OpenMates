/** Settings panel model and controller. No settings protocol or secrets are put in commands. */
import type { OpenMatesClient } from "./client.js";
import { SETTINGS_PAGES, settingsChildren, settingsPage, type SettingsField, type SettingsPage } from "./tuiSettingsCatalog.js";
import { eraseGrapheme, terminalText, truncateCells, wrapCells, type TuiLine } from "./tuiText.js";

export type TuiSettingsState = {
  route: string;
  owner: string;
  ownerStale: boolean;
  generation: number;
  authenticated: boolean;
  restricted: boolean;
  isAdmin: boolean;
  paymentEnabled: boolean;
  paymentChecked: boolean;
  features?: ReadonlySet<string>;
  webUrl: string;
  profile: { username: string; email: string; account: string; team: string };
  data: Record<string, unknown>;
  lastResult: Record<string, unknown>;
  drafts: Record<string, Record<string, string>>;
  dirty: Record<string, boolean>;
  dirtyFields: Record<string, Record<string, true>>;
  selection: number;
  scrollOffset: number;
  followSelection: boolean;
  editing: string | null;
  confirmation: string | null;
  confirmationChoice: "confirm" | "cancel";
  busy: boolean;
  loading: boolean;
  message: string | null;
  error: string | null;
  /** One-time API key; cleared when leaving the page or changing owner. */
  oneTimeSecret: string | null;
  secretRevealed: boolean;
};

export type TuiSettingsContext = {
  client: OpenMatesClient;
  state: TuiSettingsState;
  owner: string | (() => string);
  /** Captured account/session/team fence from the shared workspace controller. */
  isOwnerCurrent?: () => boolean;
  render: () => void;
  close?: () => void;
  openWeb?: (url: string) => void;
  webUrl?: string;
  viewportHeight?: number;
};

const currentOwner = (ctx: TuiSettingsContext) => typeof ctx.owner === "function" ? ctx.owner() : ctx.owner;
const ownerValid = (ctx: TuiSettingsContext, owner: string) => currentOwner(ctx) === owner && ctx.state.owner === owner && (ctx.isOwnerCurrent?.() ?? true);
const asObject = (value: unknown): Record<string, unknown> => value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
const safeText = (value: unknown): string => terminalText(String(value ?? "")).replace(/\s+/g, " ").trim();
const isSecret = (key: string) => /(?:secret|token|password|private.?key|encrypted|ciphertext|api_key$|^key$)/i.test(key);
export function settingsWebDestination(webUrl: string, route: string): string {
  return `${webUrl.replace(/\/$/, "")}/#settings/${route}`;
}
function settingsWebUrl(ctx: TuiSettingsContext): string {
  if (ctx.webUrl) return ctx.webUrl.replace(/\/$/, "");
  if (process.env.OPENMATES_APP_URL) return process.env.OPENMATES_APP_URL.replace(/\/$/, "");
  try {
    const url = new URL(ctx.client.apiUrl);
    if (url.hostname === "api.openmates.org") return "https://openmates.org";
    if (url.hostname === "api.dev.openmates.org") return "https://app.dev.openmates.org";
    if (["localhost", "127.0.0.1", "::1"].includes(url.hostname)) return "http://localhost:5173";
    if (url.hostname.startsWith("api.")) url.hostname = `app.${url.hostname.slice(4)}`;
    return url.origin;
  } catch { return "https://openmates.org"; }
}

export function createTuiSettingsState(owner: string, options: { authenticated?: boolean; restricted?: boolean; paymentEnabled?: boolean; webUrl?: string; features?: ReadonlySet<string> } = {}): TuiSettingsState {
  return { route: "main", owner, ownerStale: false, generation: 0, authenticated: options.authenticated ?? true,
    restricted: options.restricted ?? false, isAdmin: false, paymentEnabled: options.paymentEnabled ?? false, paymentChecked: false, features: options.features, webUrl: options.webUrl ?? "",
    profile: { username: "", email: "", account: "", team: "" }, data: {}, lastResult: {}, drafts: {}, dirty: {}, dirtyFields: {}, selection: 0,
    scrollOffset: 0, followSelection: true, editing: null, confirmation: null, confirmationChoice: "confirm", busy: false, loading: false, message: null, error: null, oneTimeSecret: null, secretRevealed: false };
}

function markDraftFieldChanged(state: TuiSettingsState, fieldId: string): void {
  state.dirty[state.route] = true;
  (state.dirtyFields[state.route] ??= {})[fieldId] = true;
}

function restrictedSession(client: OpenMatesClient): boolean {
  if (!client.hasSession() || typeof client.getSession !== "function") return false;
  try {
    const session = client.getSession();
    // Pairing always records the authorizing device, including unlimited sessions.
    return typeof session.pairedSessionExpiresAt === "number" ||
      typeof session.authorizerDeviceName === "string" && session.authorizerDeviceName.trim().length > 0;
  }
  catch { return false; }
}

/** Invalidates pending reads and responses when account or team ownership changes. */
export function syncTuiSettingsOwner(ctx: TuiSettingsContext): boolean {
  const owner = currentOwner(ctx);
  if (ctx.isOwnerCurrent?.() === false && owner === ctx.state.owner) {
    if (!ctx.state.ownerStale) {
      const fresh = createTuiSettingsState(owner, { authenticated: ctx.client.hasSession(), restricted: restrictedSession(ctx.client), paymentEnabled: false, webUrl: settingsWebUrl(ctx) });
      Object.assign(ctx.state, fresh, { ownerStale: true, generation: ctx.state.generation + 1 });
      ctx.render();
    }
    return true;
  }
  if (ctx.state.owner === owner) return false;
  const fresh = createTuiSettingsState(owner, { authenticated: ctx.client.hasSession(), restricted: restrictedSession(ctx.client),
    paymentEnabled: ctx.state.paymentEnabled, features: ctx.state.features, webUrl: settingsWebUrl(ctx) });
  Object.assign(ctx.state, fresh, { generation: ctx.state.generation + 1 });
  ctx.render();
  return true;
}

function available(page: SettingsPage, state: TuiSettingsState): boolean {
  if (page.auth && !state.authenticated) return false;
  if (page.admin && !state.isAdmin) return false;
  if (state.restricted && ["account", "teams", "settings_memories", "billing"].includes(page.route.split("/")[0])) return false;
  if (page.billing && !state.paymentEnabled) return false;
  if (page.route === "projects" && state.features?.has("projects") === false) return false;
  if (page.route === "teams" && state.features?.has("teams") === false) return false;
  return true;
}

function nearestRoute(route: string, state: TuiSettingsState): string {
  let probe = route.replace(/^\/+|\/+$/g, "") || "main";
  while (probe !== "main") {
    const page = settingsPage(probe);
    if (page && available(page, state)) return probe;
    probe = probe.includes("/") ? probe.slice(0, probe.lastIndexOf("/")) : "main";
  }
  return "main";
}

async function loadPage(ctx: TuiSettingsContext, page: SettingsPage): Promise<void> {
  if (!page.load) return;
  const state = ctx.state;
  if (state.busy) return;
  if (state.ownerStale) return;
  const owner = currentOwner(ctx), generation = ++state.generation;
  state.busy = true; state.loading = true; state.error = null; ctx.render();
  try {
    const value = await page.load(ctx.client);
    if (!ownerValid(ctx, owner) || state.generation !== generation) return;
    state.data[page.route] = value;
    if (page.defaults) {
      const defaults = page.defaults(value);
      const changed = state.dirtyFields[page.route];
      state.drafts[page.route] = state.dirty[page.route] && !changed
        ? state.drafts[page.route] ?? defaults
        : { ...defaults, ...Object.fromEntries(Object.keys(changed ?? {}).map((id) => [id, state.drafts[page.route]?.[id] ?? ""])) };
    }
    if (page.route === "account/info") {
      const info = asObject(value);
      state.profile = { username: safeText(info.username), email: safeText(info.email), account: safeText(info.id), team: safeText(info.active_team_name) };
      state.isAdmin = info.is_admin === true;
    }
  } catch (error) {
    if (ownerValid(ctx, owner) && state.generation === generation) state.error = safeText(error instanceof Error ? error.message : error);
  } finally {
    if (ownerValid(ctx, owner) && state.generation === generation) { state.busy = false; state.loading = false; ctx.render(); }
  }
}

/** The root calls this when opening Settings or navigating to /settings <web-route>. */
export async function openTuiSettingsPage(state: TuiSettingsState, route: string, ctx: TuiSettingsContext): Promise<void> {
  syncTuiSettingsOwner(ctx);
  if (state.busy || state.ownerStale || state.confirmation) return;
  state.authenticated = ctx.client.hasSession();
  state.restricted = restrictedSession(ctx.client);
  state.webUrl = settingsWebUrl(ctx);
  const next = nearestRoute(route || "main", state);
  if (next !== route && route && route !== "main") state.message = `Unavailable settings route. Opened ${settingsPage(next)?.title ?? "Settings"}.`;
  else state.message = null;
  state.route = next; state.selection = 0; state.scrollOffset = 0; state.followSelection = true; state.editing = null; state.confirmation = null; state.error = null;
  state.oneTimeSecret = null; state.secretRevealed = false;
  state.lastResult[next] = undefined;
  state.generation++;
  const page = settingsPage(next)!;
  if (page.fields && !state.drafts[next]) state.drafts[next] = Object.fromEntries(page.fields.map((field) => [field.id, field.kind === "boolean" ? "off" : field.options?.[0] ?? ""]));
  if (next === "newsletter/subscribe" && !state.dirty[next] && !state.drafts[next]?.language) state.drafts[next]!.language = "en";
  ctx.render();
  if (next === "main" && state.authenticated) {
    await Promise.all([state.profile.username ? Promise.resolve() : loadProfile(ctx), state.paymentChecked ? Promise.resolve() : loadCapabilities(ctx)]);
  }
  await loadPage(ctx, page);
}

async function loadProfile(ctx: TuiSettingsContext): Promise<void> {
  const state = ctx.state, owner = currentOwner(ctx), generation = state.generation;
  try {
    const info = asObject(await ctx.client.whoAmI());
    if (!ownerValid(ctx, owner) || state.generation !== generation) return;
    state.profile = { username: safeText(info.username), email: safeText(info.email), account: safeText(info.id), team: safeText(info.active_team_name) };
    state.isAdmin = info.is_admin === true;
    ctx.render();
  } catch { /* Navigation remains usable offline. */ }
}

async function loadCapabilities(ctx: TuiSettingsContext): Promise<void> {
  const state = ctx.state, owner = currentOwner(ctx), generation = state.generation;
  if (!state.authenticated || typeof ctx.client.settingsGet !== "function") return;
  try {
    const status = asObject(await ctx.client.settingsGet("server-status"));
    if (!ownerValid(ctx, owner) || state.generation !== generation) return;
    state.paymentEnabled = status.is_self_hosted !== true && status.payment_enabled === true;
    state.paymentChecked = true;
    ctx.render();
  } catch { /* Billing stays hidden until server capability is known. */ }
}

function validateField(field: SettingsField, value: string): string | null {
  if (field.required && !value.trim()) return `${field.label} is required.`;
  if (field.kind === "number" && (!Number.isFinite(Number(value)) || !Number.isSafeInteger(Number(value)))) return `${field.label} must be a whole number.`;
  if (field.kind === "choice" && field.options && !field.options.includes(value)) return `Choose a listed ${field.label.toLowerCase()}.`;
  if (field.kind === "boolean" && value !== "on" && value !== "off") return `${field.label} must be on or off.`;
  return field.validate?.(value) ?? null;
}

export function validateTuiSettingsDraft(page: SettingsPage, draft: Record<string, string>): string | null {
  for (const field of page.fields ?? []) {
    const error = validateField(field, draft[field.id] ?? "");
    if (error) return error;
  }
  if (page.route === "billing/auto-topup/low-balance" && draft.enabled === "on" && !draft.email) return "Email is required when auto top-up is enabled.";
  if (page.route === "billing/auto-topup/low-balance" && draft.enabled === "on" && Number(draft.amount) <= 0) return "Credit amount must be positive when auto top-up is enabled.";
  return null;
}

async function runMutation(ctx: TuiSettingsContext, actionId: string): Promise<void> {
  const state = ctx.state;
  if (state.busy) return;
  const page = settingsPage(state.route);
  if (!page || !available(page, state) || page.webOnly) return;
  if (page.requiresLoad && state.data[page.route] === undefined) { state.error = "Current settings unavailable. Reopen this page to retry."; ctx.render(); return; }
  const action = page.actions?.find((item) => item.id === actionId);
  if (actionId !== "save" && !action || action?.authenticatedOnly && !state.authenticated) return;
  const draft = state.drafts[page.route] ?? {};
  const requiredForAction: Record<string, string> = { create: "name", redeem: "code", revoke: "key_id", delete: page.route === "settings_memories/list" ? "memory_id" : "file_id", refund: "invoice_id", "create-order": "credits" };
  const fieldId = requiredForAction[actionId];
  const field = fieldId ? page.fields?.find((item) => item.id === fieldId) : undefined;
  const validation = actionId === "save" ? validateTuiSettingsDraft(page, draft)
    : field ? validateField({ ...field, required: true }, draft[field.id] ?? "") : null;
  if (validation) { state.error = validation; ctx.render(); return; }
  if (action?.confirm && state.confirmation !== actionId) { state.confirmation = actionId; state.confirmationChoice = "confirm"; state.error = null; ctx.render(); return; }
  const owner = currentOwner(ctx), generation = ++state.generation;
  state.busy = true; state.error = null; state.message = null; state.confirmation = null; ctx.render();
  try {
    const result = await (action ? action.run(ctx.client, { ...draft }) : page.save!(ctx.client, { ...draft }));
    if (actionId === "logout") {
      // Logout changes the owner. Let the TUI render fence clear all private
      // workspace state before the stale-owner guard discards this response.
      ctx.render();
      return;
    }
    if (!ownerValid(ctx, owner) || state.generation !== generation) return;
    const response = asObject(result);
    if (response.success === false) throw new Error(safeText(response.message) || "Operation was not accepted.");
    state.message = action ? `${action.label} completed.` : "Saved.";
    state.dirty[page.route] = false;
    state.dirtyFields[page.route] = {};
    if (action && result && typeof result === "object") state.lastResult[page.route] = actionId === "create" && page.route === "developers/api-keys"
      ? Object.fromEntries(Object.entries(response).filter(([key]) => !isSecret(key))) : result;
    if (actionId === "create" && page.route === "developers/api-keys") state.oneTimeSecret = typeof response.api_key === "string" ? response.api_key : null;
    if (state.oneTimeSecret) state.secretRevealed = false;
    if (page.load && actionId !== "create") {
      // Reload only after acknowledgement. Drafts remain available if this read fails.
      state.busy = false; ctx.render(); await loadPage(ctx, page); return;
    }
  } catch (error) {
    if (ownerValid(ctx, owner) && state.generation === generation) state.error = safeText(error instanceof Error ? error.message : error);
  } finally {
    if (ownerValid(ctx, owner) && state.generation === generation) { state.busy = false; ctx.render(); }
  }
}

function actionIds(state: TuiSettingsState): string[] {
  const page = settingsPage(state.route)!;
  return [...settingsChildren(state.route, state).map((child) => `route:${child.route}`),
    ...(page.fields ?? []).map((field) => `field:${field.id}`),
    ...(page.save ? ["save"] : []), ...(page.actions ?? []).filter(action=>!action.authenticatedOnly||state.authenticated).map((action) => `action:${action.id}`),
    ...(state.oneTimeSecret ? ["reveal-secret"] : []),
    ...(page.webOnly ? ["web"] : [])];
}

export async function handleTuiSettingsCommand(ctx: TuiSettingsContext, arg: string): Promise<boolean> {
  const state = ctx.state;
  if (arg === "close") { state.generation++; state.busy = false; state.loading = false; state.oneTimeSecret = null; state.secretRevealed = false; ctx.close?.(); return true; }
  if (syncTuiSettingsOwner(ctx)) return true;
  if (state.ownerStale) return true;
  if (state.busy && !(state.loading && arg.startsWith("field:"))) return true;
  if (state.confirmation) {
    if (arg === "cancel") { state.confirmation = null; ctx.render(); return true; }
    if (arg === "confirm") { await runMutation(ctx, state.confirmation); return true; }
    return true;
  }
  if (arg === "back") { await openTuiSettingsPage(state, settingsPage(state.route)?.parent ?? "main", ctx); return true; }
  if (arg === "cancel") { state.confirmation = null; state.editing = null; ctx.render(); return true; }
  if (arg === "reveal-secret") { state.secretRevealed = !state.secretRevealed; ctx.render(); return true; }
  if (arg.startsWith("route:")) { await openTuiSettingsPage(state, arg.slice(6), ctx); return true; }
  if (arg.startsWith("field:")) {
    const id = arg.slice(6), page = settingsPage(state.route)!;
    const field = page.fields?.find((item) => item.id === id);
    if (!field) return true;
    // A placeholder value cannot be safely inverted before its server value arrives.
    if (state.loading && (field.kind === "boolean" || field.kind === "choice")) return true;
    const draft = state.drafts[page.route] ??= {};
    if (field.kind === "boolean") { draft[id] = draft[id] === "on" ? "off" : "on"; markDraftFieldChanged(state, id); }
    else if (field.kind === "choice") { const choices = field.options ?? []; draft[id] = choices[(choices.indexOf(draft[id] ?? "") + 1) % choices.length] ?? ""; markDraftFieldChanged(state, id); }
    else state.editing = id;
    state.selection = Math.max(0, actionIds(state).indexOf(arg)); state.followSelection = true; state.error = null; ctx.render(); return true;
  }
  if (arg === "save") { await runMutation(ctx, "save"); return true; }
  if (arg.startsWith("action:")) { await runMutation(ctx, arg.slice(7)); return true; }
  if (arg === "web") {
    const page = settingsPage(state.route);
    if (page?.webOnly) { const url = settingsWebDestination(state.webUrl, page.webOnly); state.message = `Open in browser: ${url}`; ctx.openWeb?.(url); ctx.render(); }
    return true;
  }
  return true;
}

export async function handleTuiSettingsKey(ctx: TuiSettingsContext, chunk: string, key: { name?: string; ctrl?: boolean; shift?: boolean; meta?: boolean }): Promise<boolean> {
  const state = ctx.state;
  const name = key.name?.toLowerCase() ?? "";
  if (state.ownerStale && name === "escape") return handleTuiSettingsCommand(ctx, "close");
  if (syncTuiSettingsOwner(ctx)) return true;
  if (state.ownerStale) return true;
  if (state.busy && !state.loading) return name === "escape" ? handleTuiSettingsCommand(ctx, "close") : true;
  if (state.loading && name === "escape" && !state.editing) return handleTuiSettingsCommand(ctx, "close");
  if (state.confirmation) {
    if (name === "escape" || chunk.toLowerCase() === "n") return handleTuiSettingsCommand(ctx, "cancel");
    if (name === "tab" || name === "left" || name === "right") { state.confirmationChoice = state.confirmationChoice === "confirm" ? "cancel" : "confirm"; ctx.render(); return true; }
    if (chunk.toLowerCase() === "y") return handleTuiSettingsCommand(ctx, "confirm");
    if (name === "return" || name === "enter") return handleTuiSettingsCommand(ctx, state.confirmationChoice);
    return true;
  }
  if (key.ctrl && name === "s") {
    if (settingsPage(state.route)?.save) await handleTuiSettingsCommand(ctx, "save");
    return true;
  }
  if (key.ctrl && name === "u") {
    const selected = actionIds(state)[state.selection] ?? "";
    const id = state.editing ?? (selected.startsWith("field:") ? selected.slice(6) : "");
    const field = settingsPage(state.route)?.fields?.find((item) => item.id === id);
    if (field && (field.kind === "text" || field.kind === "number")) {
      const draft = state.drafts[state.route] ??= {};
      draft[id] = ""; markDraftFieldChanged(state, id); state.error = null; ctx.render();
    }
    return true;
  }
  if (["pageup", "pagedown", "scrollup", "scrolldown", "home", "end"].includes(name)) {
    const page = Math.max(1, ctx.viewportHeight ?? 8);
    state.scrollOffset = name === "home" ? 0 : name === "end" ? Number.MAX_SAFE_INTEGER
      : Math.max(0, state.scrollOffset + (["pageup", "scrollup"].includes(name) ? -1 : 1) * (["pageup", "pagedown"].includes(name) ? page : 3));
    state.followSelection = false; ctx.render(); return true;
  }
  if (name === "tab") {
    const actions = actionIds(state);
    state.editing = null;
    if (actions.length) state.selection = (state.selection + (key.shift ? -1 : 1) + actions.length) % actions.length;
    state.followSelection = true; ctx.render(); return true;
  }
  if (state.editing) {
    if (name === "escape" || name === "return" || name === "enter") { state.editing = null; ctx.render(); return true; }
    const draft = state.drafts[state.route] ??= {};
    if (name === "backspace") draft[state.editing] = eraseGrapheme(draft[state.editing] ?? "");
    // eslint-disable-next-line no-control-regex -- Never treat terminal control reports as field text.
    else if (chunk && !key.ctrl && !key.meta && !/[\x00-\x1f\x7f]/.test(chunk)) draft[state.editing] = (draft[state.editing] ?? "") + chunk;
    else return true;
    markDraftFieldChanged(state, state.editing); state.error = null; ctx.render(); return true;
  }
  if (name === "escape") return handleTuiSettingsCommand(ctx, state.route === "main" ? "close" : "back");
  if (name === "left" || name === "backspace") return handleTuiSettingsCommand(ctx, "back");
  const actions = actionIds(state);
  if (name === "up") { state.selection = Math.max(0, state.selection - 1); state.followSelection = true; ctx.render(); return true; }
  if (name === "down") { state.selection = Math.min(actions.length - 1, state.selection + 1); state.followSelection = true; ctx.render(); return true; }
  if (/^[1-9]$/.test(chunk) && !key.ctrl) { const action = actions[Number(chunk) - 1]; if (action) { state.followSelection = true; return handleTuiSettingsCommand(ctx, action); } }
  if (name === "return" || name === "enter" || name === "right") { const action = actions[state.selection]; if (action) return handleTuiSettingsCommand(ctx, action); }
  return true;
}

// Server responses contain internal account, crypto and billing fields. Only
// these route-specific user-facing values may enter the terminal frame.
const summaryFields: Record<string, readonly [string, string][]> = {
  "account/info": [["username", "Username"], ["email", "Email"], ["timezone", "Timezone"], ["language", "Language"]],
  "account/storage": [["used_bytes", "Used bytes"], ["total_bytes", "Total bytes"], ["file_count", "Files"]],
  "account/chats": [["chat_count", "Chats"], ["message_count", "Messages"]],
  "billing/overview": [["credits", "Credits"], ["balance", "Balance"], ["currency", "Currency"]],
  "billing/usage": [["total_credits", "Credits used"], ["total_cost", "Total cost"], ["currency", "Currency"]],
};
const listFields: Record<string, { key: string; fields: readonly [string, string][] }> = {
  "account/storage/files": { key: "files", fields: [["filename", "File"], ["id", "File ID"], ["size", "Bytes"]] },
  "billing/invoices": { key: "invoices", fields: [["id", "Invoice ID"], ["date", "Date"], ["status", "Status"], ["amount", "Amount"], ["currency", "Currency"]] },
  "billing/bank-transfer": { key: "orders", fields: [["id", "Order ID"], ["status", "Status"], ["credits", "Credits"], ["amount", "Amount"], ["currency", "Currency"]] },
  "billing/gift-cards": { key: "gift_cards", fields: [["id", "Gift card ID"], ["credits", "Credits"], ["status", "Status"]] },
  "billing/gift-cards/bank-transfer": { key: "orders", fields: [["id", "Order ID"], ["status", "Status"], ["credits", "Credits"]] },
  "developers/api-keys": { key: "api_keys", fields: [["name", "Name"], ["id", "Key ID"], ["full_access", "Full access"], ["expires_at", "Expires"]] },
  "settings_memories/list": { key: "memories", fields: [["title", "Title"], ["id", "Memory ID"]] },
};
const resultFields: Record<string, readonly [string, string][]> = {
  "billing/bank-transfer": [["order_id", "Order ID"], ["payment_reference", "Reference"], ["iban", "IBAN"], ["recipient", "Recipient"], ["amount", "Amount"], ["currency", "Currency"]],
  "billing/gift-cards/bank-transfer": [["order_id", "Order ID"], ["payment_reference", "Reference"], ["iban", "IBAN"], ["recipient", "Recipient"], ["amount", "Amount"], ["currency", "Currency"]],
  "billing/gift-cards": [["credits", "Credits redeemed"]],
};
function scalarValue(value: unknown): string | null {
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "string" || typeof value === "number") return safeText(value) || null;
  return null;
}
function allowedRows(value: unknown, fields: readonly [string, string][], width: number): string[] {
  const record = asObject(value);
  return fields.flatMap(([key, label]) => {
    const shown = scalarValue(record[key]);
    return shown === null ? [] : wrapCells(`  ${label}: ${shown}`, width);
  });
}
function settingsDataLines(page: SettingsPage, value: unknown, width: number, result = false): string[] {
  if (result) return allowedRows(value, resultFields[page.route] ?? [], width);
  if (page.save && page.defaults && page.fields) {
    const defaults = page.defaults(value);
    return allowedRows(defaults, page.fields.map(({ id, label }) => [id, label]), width);
  }
  const summary = summaryFields[page.route];
  if (summary) return allowedRows(value, summary, width);
  const list = listFields[page.route];
  if (!list) return [];
  const collection = Array.isArray(value) ? value : asObject(value)[list.key];
  if (!Array.isArray(collection)) return [];
  return [`  ${collection.length} item${collection.length === 1 ? "" : "s"}`,
    ...collection.slice(0, 20).flatMap((item, index) => {
      const detail = allowedRows(item, list.fields, width);
      return detail.length ? [`  ${index + 1}.`, ...detail] : [];
    })];
}

function line(text: string, action?: string, selected = false): TuiLine {
  return { text, ...(action ? { action: { kind: "command" as const, command: `/settings-action ${action}` } } : {}), ...(selected ? { bold: true, color: "#89c4ff" } : {}) };
}

/** Pure view of the current settings route. Root handles panel sizing and clipping. */
export function renderTuiSettings(state: TuiSettingsState, width: number): TuiLine[] {
  width = Math.max(16, width);
  const page = settingsPage(state.route) ?? settingsPage("main")!;
  const lines: TuiLine[] = [line(truncateCells(`Settings  /  ${page.title}`, width))];
  if (state.route !== "main" && !state.confirmation) lines.push(line(`[Back to ${settingsPage(page.parent ?? "main")?.title ?? "Settings"}]`, "back"));
  lines.push(line("[Close Settings]", "close"), "");
  if (state.ownerStale) return [line("Settings"), line("Account or team changed. Reopen Settings."), line("Close Settings", "close")];
  if (state.confirmation) {
    lines.push(...wrapCells(page.actions?.find((action) => action.id === state.confirmation)?.confirm ?? "Confirm operation?", width), "",
      line(state.confirmationChoice === "confirm" ? "› Confirm" : "  Confirm", "confirm", state.confirmationChoice === "confirm"),
      line(state.confirmationChoice === "cancel" ? "› Cancel" : "  Cancel", "cancel", state.confirmationChoice === "cancel"),
      "", ...wrapCells("Tab choose · Enter select · Esc cancel", width));
    return lines;
  }
  if (state.route === "main") {
    const profile = state.authenticated ? [state.profile.username || "Signed in", state.profile.team || "Personal", state.restricted ? "Paired session" : "", state.profile.email].filter(Boolean).join(" · ") : "Signed out";
    lines.push(...wrapCells(profile, width), "");
  }
  if (page.description) lines.push(...wrapCells(page.description, width), "");
  if (state.message) lines.push(...wrapCells(`✓ ${state.message}`, width), "");
  if (state.error) lines.push(...wrapCells(`Error: ${state.error}`, width), "");
  if (state.busy) lines.push("Working…", "");
  const ids = actionIds(state);
  for (const child of settingsChildren(state.route, state)) {
    const id = `route:${child.route}`, index = ids.indexOf(id);
    lines.push(line(truncateCells(`${index + 1}. ${state.selection === index ? "› " : "  "}${child.title}${child.webOnly ? "  [Web]" : ""}`, width), id, state.selection === index));
  }
  const draft = state.drafts[page.route] ?? {};
  if (page.fields?.length) {
    lines.push("", "Edit fields, then Save:");
    for (const field of page.fields) {
      const id = `field:${field.id}`, index = ids.indexOf(id), value = draft[field.id] ?? "";
      const pendingChoice = state.loading && (field.kind === "boolean" || field.kind === "choice");
      const visibleValue = pendingChoice && state.data[page.route] === undefined ? "Loading…" : value || "—";
      const suffix = pendingChoice ? "" : field.kind === "boolean" || field.kind === "choice" ? "  ↻" : state.editing === field.id ? "  [edit]" : "";
      lines.push(line(truncateCells(`${index + 1}. ${state.selection === index ? "› " : "  "}${field.label}: ${visibleValue}${suffix}`, width), pendingChoice ? undefined : id, state.selection === index));
      if (field.hint && state.editing === field.id) lines.push(...wrapCells(`   ${field.hint}`, width));
    }
  }
  if (page.save) { const index = ids.indexOf("save"); lines.push("", line(`${index + 1}. Save${state.dirty[page.route] ? " changes" : ""}`, "save", state.selection === index)); }
  for (const action of (page.actions ?? []).filter(action=>!action.authenticatedOnly||state.authenticated)) { const id = `action:${action.id}`, index = ids.indexOf(id); lines.push(line(`${index + 1}. ${action.label}`, id, state.selection === index)); }
  if (page.webOnly) {
    lines.push("", ...wrapCells(page.webReason ?? "This action requires the browser.", width));
    const index = ids.indexOf("web"); lines.push(line(`${index + 1}. Open web destination`, "web", state.selection === index), ...wrapCells(settingsWebDestination(state.webUrl, page.webOnly), width));
  }
  if (state.data[page.route] !== undefined && !page.webOnly) {
    const values = settingsDataLines(page, state.data[page.route], width);
    if (values.length) lines.push("", "Current values:", ...values);
  }
  if (state.lastResult[page.route] !== undefined) {
    const values = settingsDataLines(page, state.lastResult[page.route], width, true);
    if (values.length) lines.push("", "Operation details:", ...values);
  }
  if (state.oneTimeSecret) {
    const index = ids.indexOf("reveal-secret");
    lines.push("", line(`${index + 1}. ${state.secretRevealed ? "Hide" : "Reveal"} new API key`, "reveal-secret", state.selection === index));
    if (state.secretRevealed) lines.push("Shown once; store securely:", ...wrapCells(state.oneTimeSecret, width));
  }
  lines.push("", ...wrapCells("↑/↓ or Tab select · Enter open/edit · Ctrl+S save · Ctrl+U clear field · PgUp/PgDn scroll · Esc back/close", width));
  return lines;
}

export { SETTINGS_PAGES, settingsPage, settingsChildren };
