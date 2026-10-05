/*
 * Apps workspace model for the interactive terminal.
 * Uses the web Apps catalog and skill form contract, with client-side encryption
 * for saved Personal results. No file, provider, or account secret is sent to the
 * Apps result index in plaintext. Skill execution requires explicit confirmation.
 * Team and guest execution are disabled until their web authorization contracts
 * can be carried through the CLI client.
 */

import { randomBytes, randomUUID } from "node:crypto";
import type { OpenMatesClient } from "./client.js";
import { decryptBytesWithAesGcm, decryptWithAesGcmCombined, encryptBytesWithAesGcm, encryptWithAesGcmCombined } from "./crypto.js";
import { formatEmbedPreviewLines } from "./embedRenderers.js";
import { formValue, type TuiForm } from "./tuiForms.js";
import { cells, padCells, terminalText, truncateCells, wrapCells, type TuiLine } from "./tuiText.js";
import { centeredCarouselText, renderCardCarousel } from "./tuiCarousel.js";
import { APP_GRADIENTS, PRIMARY_GRADIENT } from "../../appGradientTheme.js";
import {
  getSkillPath, prepareSkillInput, resolveSkillSchema, schemaForPath, setSkillPath,
  skillLeafPaths, validateSkillInput, type SkillSchema,
} from "../../ui/src/components/apps/appsSkillFormUtils.js";

const APP_ID = /^[a-z][a-z0-9_]{0,63}$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const RESULT_PAGE_SIZE = 20;
const MAX_RESULT_LINES = 120;
const HOME_APP_ORDER = ["web", "news", "health", "travel", "weather", "audio"];
const pendingConfirmations = new WeakMap<TuiForm, Promise<TuiAppsSavedResult>>();

export type TuiAppSkill = { id: string; name: string; description: string; providers: string[] };
export type TuiApp = {
  id: string; name: string; description: string; category: string;
  skills: TuiAppSkill[];
  focusModes: Array<{ id: string; name: string; description: string }>;
  settingsMemories: Array<{ id: string; name: string; description: string; body?: string }>;
};
export type TuiAppsTab = "skills" | "focus_modes" | "settings_memories" | "embeds" | "workflows";
export type TuiAppsSkillTab = "overview" | "embeds" | "workflows";
export type TuiAppsSkillDetails = {
  appId: string; skillId: string; name: string; description: string;
  schema: SkillSchema; defaults: Record<string, unknown>; primaryFields: string[];
  pricing: Record<string, unknown> | null; providers: string[];
  executionAvailable: boolean; unavailableReason: string | null;
};
export type TuiAppsResultItem = { embedId: string; appId: string; skillId: string; createdAt: number; status: string };
export type TuiAppsResultsPage = { items: TuiAppsResultItem[]; hasMore: boolean; offset: number };
export type TuiAppsWorkflowPage = { items: Array<{ id: string; title: string }>; hasMore: boolean; offset: number };
export type TuiAppsSavedResult = {
  embedId: string; appId: string; skillId: string; status: string;
  content: Record<string, unknown>; children: Array<{ embedId: string; type: string; content: Record<string, unknown> }>;
  retentionError?: string;
};
export type TuiAppsPreparedRun = { appId: string; skillId: string; input: Record<string, unknown>; summary: string };

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}
function string(value: unknown, fallback = ""): string { return typeof value === "string" ? value : fallback; }
function rows(value: unknown): Record<string, unknown>[] { return Array.isArray(value) ? value.map(record) : []; }
function oneLine(value: string): string { return terminalText(value).replace(/\s+/g, " ").trim(); }
function textLines(value: string, width: number): string[] { return wrapCells(value, Math.max(1, width)); }

function parseApp(value: Record<string, unknown>, idHint = ""): TuiApp | null {
  const id = string(value.id, idHint);
  if (!APP_ID.test(id)) return null;
  return {
    id, name: string(value.name, id), description: string(value.description), category: string(value.category),
    skills: rows(value.skills).flatMap((skill): TuiAppSkill[] => {
      const skillId = string(skill.id);
      if (!APP_ID.test(skillId)) return [];
      return [{ id: skillId, name: string(skill.name, skillId), description: string(skill.description),
        providers: rows(skill.providers).map((provider) => string(provider.name, string(provider.provider))).filter(Boolean) }];
    }),
    focusModes: rows(value.focus_modes).map((entry) => ({ id: string(entry.id), name: string(entry.name), description: string(entry.description) })),
    settingsMemories: [
      ...rows(value.settings_and_memories).map((entry) => ({ id: string(entry.id), name: string(entry.name), description: string(entry.description) })),
      ...rows(value.memories).map((entry) => ({ id: string(entry.id), name: string(entry.title),
        description: `App-provided · Read-only · Loads automatically when relevant. ${string(entry.description)}`, body: string(entry.body) })),
    ],
  };
}

/** Read the same public catalog consumed by the web Apps workspace. */
export async function loadTuiApps(client: Pick<OpenMatesClient, "getAppsWorkspaceCatalog">): Promise<TuiApp[]> {
  const data = record(await client.getAppsWorkspaceCatalog());
  const source = data.apps;
  const apps = Array.isArray(source) ? source.map((value) => parseApp(record(value)))
    : Object.entries(record(source)).map(([id, value]) => parseApp(record(value), id));
  return apps.filter((app): app is TuiApp => app !== null).sort((a, b) => {
    const left = HOME_APP_ORDER.indexOf(a.id), right = HOME_APP_ORDER.indexOf(b.id);
    if (left >= 0 || right >= 0) return (left < 0 ? Infinity : left) - (right < 0 ? Infinity : right);
    return a.name.localeCompare(b.name);
  });
}

export function visibleTuiApps(apps: TuiApp[], query = ""): TuiApp[] {
  const words = query.toLocaleLowerCase().trim().split(/\s+/).filter(Boolean);
  return apps.filter((app) => words.every((word) => `${app.name} ${app.description} ${app.category} ${app.skills.map((skill) => skill.name).join(" ")}`.toLocaleLowerCase().includes(word)));
}

/** Keep the featured home, full catalog, filtering and Enter targets in agreement. */
export function homeTuiApps(apps: TuiApp[], query = "", showAll = false): TuiApp[] {
  const visible = visibleTuiApps(apps, query);
  return showAll || query ? visible : visible.slice(0, HOME_APP_ORDER.length);
}

export function renderTuiAppsHome(apps: TuiApp[], options: { width: number; selectedId?: string; selectedIndex?: number; query?: string }): TuiLine[] {
  const width = Math.max(1, options.width);
  const visible = visibleTuiApps(apps, options.query);
  if (!visible.length) return [centeredCarouselText(options.query ? "No matching apps." : "No apps available.", width)];
  const selected = Math.max(0, Math.min(visible.length - 1, options.selectedIndex ?? visible.findIndex((app) => app.id === options.selectedId)));
  return [...renderCardCarousel(visible.map((app) => ({ title: app.name, description: app.description,
    footer: `${app.skills.length} skills${app.category ? ` · ${app.category.replaceAll("_", " ")}` : ""}`,
    background: (APP_GRADIENTS[app.id] ?? PRIMARY_GRADIENT).start,
  })), width, selected, options.selectedId !== undefined), "",
  centeredCarouselText(`${selected > 0 ? "‹" : " "}  App ${selected + 1} of ${visible.length}  ${selected < visible.length - 1 ? "›" : " "}`, width),
  centeredCarouselText("←/→ choose app  ·  Enter open  ·  Tab focus", width)];
}

function cardLines(title: string, description: string, footer: string, width: number): string[] {
  if (width < 4) return [truncateCells(title, width)];
  const cardWidth = Math.min(width, 64);
  const inner = cardWidth - 4;
  return [
    `╭${"─".repeat(cardWidth - 2)}╮`,
    `│ ${padCells(title, inner)} │`,
    `│ ${padCells(oneLine(description), inner)} │`,
    `│ ${padCells(footer, inner)} │`,
    `╰${"─".repeat(cardWidth - 2)}╯`,
  ];
}

function identityCard(rows: string[], width: number, label: string): string[] {
  width = Math.max(1, width);
  if (width < 6) return rows.flatMap((row) => textLines(row, width));
  const inner = width - 4;
  const heading = truncateCells(`─ ${label} `, width - 2);
  return [
    `╭${heading}${"─".repeat(Math.max(0, width - 2 - cells(heading)))}╮`,
    ...rows.flatMap((row) => textLines(row, inner).map((line) => `│ ${padCells(line, inner)} │`)),
    `╰${"─".repeat(width - 2)}╯`,
  ];
}

function outlinedTabs<T extends string>(tabs: readonly T[], labels: Record<T, string>, selected: T, width: number): string[] {
  width = Math.max(1, width);
  if (width < tabs.length * 8 + 1) return ["", truncateCells(tabs.map((tab, index) => `${index + 1} ${tab === selected ? `[${labels[tab]}]` : labels[tab]}`).join(" | "), width), ""];
  const available = width - tabs.length - 1;
  const base = Math.floor(available / tabs.length);
  const widths = tabs.map((_, index) => base + (index < available % tabs.length ? 1 : 0));
  const edges = widths.map((size) => "─".repeat(size));
  const row = tabs.map((tab, index) => {
    const label = `${index + 1} ${tab === selected ? `[${labels[tab]}]` : labels[tab]}`;
    const size = widths[index]!;
    return padCells(label, size);
  });
  return ["", `╭${edges.join("┬")}╮`, `│${row.join("│")}│`, `╰${edges.join("┴")}╯`, ""];
}

export function renderTuiAppIdentity(app: TuiApp, width: number): string[] {
  return identityCard([`APP  /  ${app.id.toUpperCase()}`, app.name, app.description,
    `${app.skills.length} skills · ${app.focusModes.length} focus modes`], width, "APP WORKSPACE");
}

export function renderTuiAppTabs(tab: TuiAppsTab, width: number): string[] {
  const tabs: TuiAppsTab[] = ["skills", "focus_modes", "settings_memories", "embeds", "workflows"];
  const labels: Record<TuiAppsTab, string> = { skills: "Skills", focus_modes: "Focus modes", settings_memories: "Memories", embeds: "Embeds", workflows: "Workflows" };
  return outlinedTabs(tabs, labels, tab, width);
}

export function renderTuiApp(app: TuiApp, options: { width: number; tab: TuiAppsTab; selectedId?: string }): string[] {
  const width = Math.max(1, options.width);
  const lines = [...renderTuiAppIdentity(app, width), ...renderTuiAppTabs(options.tab, width)];
  if (options.tab === "skills") {
    lines.push("Which app skill do you want to use?", "");
    if (!app.skills.length) lines.push("No skills available.");
    for (const skill of app.skills) {
      lines.push(...cardLines(`${skill.id === options.selectedId ? "›" : " "} ${skill.name}`, skill.description,
        skill.providers.length ? `via ${skill.providers.join(", ")}` : `${app.id}/${skill.id}`, width), "");
    }
  } else if (options.tab === "focus_modes" || options.tab === "settings_memories") {
    const items = options.tab === "focus_modes" ? app.focusModes : app.settingsMemories;
    if (!items.length) lines.push("Nothing in this section.");
    for (const item of items) {
      lines.push(truncateCells(`${item.id === options.selectedId ? ">" : " "} ${item.name}`, width));
      if (item.description) lines.push(...textLines(`  ${oneLine(item.description)}`, width));
      if ('body' in item && item.body && item.id === options.selectedId) lines.push(...textLines(item.body, width));
    }
    lines.push("", "Manage private Memories in the web app.");
  } else if (options.tab === "embeds") lines.push("Saved results load from the encrypted Apps history. Use Enter to inspect a result.");
  else lines.push("Saved workflows for this app load from Workflows. Open a workflow there to inspect it.");
  return lines;
}

export async function loadTuiAppsSkill(client: Pick<OpenMatesClient, "getAppsWorkspaceSkillDetails">, appId: string, skillId: string): Promise<TuiAppsSkillDetails> {
  const source = record(await client.getAppsWorkspaceSkillDetails(appId, skillId));
  if (source.app_id !== appId || source.skill_id !== skillId) throw new Error("App skill details did not match the selected skill.");
  const schema = record(source.input_schema) as SkillSchema;
  return {
    appId, skillId, name: string(source.name, skillId), description: string(source.description), schema,
    defaults: record(source.defaults), primaryFields: Array.isArray(source.primary_fields) ? source.primary_fields.filter((value): value is string => typeof value === "string") : [],
    pricing: source.pricing ? record(source.pricing) : null,
    providers: rows(source.providers).map((provider) => string(provider.name)).filter(Boolean),
    executionAvailable: source.execution_available === true, unavailableReason: typeof source.unavailable_reason === "string" ? source.unavailable_reason : null,
  };
}

export function renderTuiAppsSkill(skill: TuiAppsSkillDetails, options: { width: number; tab: TuiAppsSkillTab }): string[] {
  const width = Math.max(1, options.width);
  const lines = [...renderTuiAppsSkillIdentity(skill, width), ...renderTuiAppsSkillTabs(options.tab, width)];
  if (options.tab === "overview") {
    lines.push("Use this skill manually. Your mates can also use it in chats.", "");
    for (const path of skillLeafPaths(skill.schema)) {
      const field = schemaForPath(skill.schema, path);
      const value = getSkillPath(skill.defaults, path);
      lines.push(truncateCells(`${path}${isRequired(skill.schema, path) ? " *" : ""} · ${field?.type ?? "value"}${value !== undefined ? ` · ${typeof value === "string" ? value : JSON.stringify(value)}` : ""}`, width));
    }
    lines.push("", skill.executionAvailable ? "Enter opens the input form. Running may spend credits." : `Unavailable: ${skill.unavailableReason ?? "This skill cannot run here."}`);
    const fixed = skill.pricing?.fixed;
    if (typeof fixed === "number") lines.push(`${fixed} credits per request`);
  } else if (options.tab === "embeds") lines.push("Saved results are listed in the app's Embeds tab.");
  else lines.push("Open related workflows from the app's Workflows tab.");
  return lines;
}

export function renderTuiAppsSkillIdentity(skill: TuiAppsSkillDetails, width: number): string[] {
  return identityCard([`SKILL  /  ${skill.appId.toUpperCase()}`, skill.name, skill.description,
    ...(skill.providers.length ? [`via ${skill.providers.join(", ")}`] : []),
    skill.executionAvailable ? "Use skill · review input and confirm credits before running" : "Skill unavailable"], width, "APP SKILL");
}

export function renderTuiAppsSkillTabs(tab: TuiAppsSkillTab, width: number): string[] {
  const tabs: TuiAppsSkillTab[] = ["overview", "embeds", "workflows"];
  const labels: Record<TuiAppsSkillTab, string> = { overview: "Overview", embeds: "Embeds", workflows: "Workflows" };
  return outlinedTabs(tabs, labels, tab, width);
}

function isRequired(schema: SkillSchema, path: string): boolean {
  const parts = path.replaceAll("[]", "").split(".");
  let current = schema;
  for (const part of parts) {
    const resolved = resolveSkillSchema(current, schema);
    if (!resolved.required?.includes(part)) return false;
    current = resolved.properties?.[part] as SkillSchema ?? {};
    if (current.type === "array") current = current.items as SkillSchema ?? {};
  }
  return true;
}

function displayValue(value: unknown): string { return value === undefined || value === null ? "" : typeof value === "string" ? value : JSON.stringify(value); }

export function buildTuiAppsSkillForm(skill: TuiAppsSkillDetails): TuiForm {
  const paths = skillLeafPaths(skill.schema);
  return {
    kind: "app-skill-input", title: `Use ${skill.name}`, contextId: `${skill.appId}/${skill.skillId}`, fieldIndex: 0,
    fields: paths.map((path) => ({ name: path, label: `${path}${isRequired(skill.schema, path) ? " *" : ""}`, value: displayValue(getSkillPath(skill.defaults, path)),
      multiline: /(?:query|prompt|message|body|text|code)$/i.test(path) })),
  };
}

function parseField(raw: string, schema: SkillSchema | null): unknown {
  const field = schema ?? {};
  const type = field.type;
  if (!raw.trim()) return undefined;
  if (type === "number" || type === "integer") {
    const parsed = Number(raw);
    if (!Number.isFinite(parsed) || type === "integer" && !Number.isInteger(parsed)) throw new Error("Enter a valid number.");
    return parsed;
  }
  if (type === "boolean") {
    if (raw !== "true" && raw !== "false") throw new Error("Use true or false.");
    return raw === "true";
  }
  if (type === "object" || type === "array") return JSON.parse(raw);
  return raw;
}

export function prepareTuiAppsSkillRun(skill: TuiAppsSkillDetails, form: TuiForm, timezone = Intl.DateTimeFormat().resolvedOptions().timeZone): TuiAppsPreparedRun {
  if (form.kind !== "app-skill-input" || form.contextId !== `${skill.appId}/${skill.skillId}`) throw new Error("App skill form context changed.");
  if (!skill.executionAvailable) throw new Error(skill.unavailableReason ?? "This skill is unavailable.");
  let input = structuredClone(skill.defaults);
  for (const field of form.fields) {
    const previous = getSkillPath(input, field.name);
    if (!field.value.trim() && previous === undefined) continue;
    let value: unknown;
    try { value = parseField(field.value, schemaForPath(skill.schema, field.name)); }
    catch (error) { throw new Error(`${field.label}: ${error instanceof Error ? error.message : "Invalid value"}`); }
    input = setSkillPath(input, field.name, value);
  }
  input = prepareSkillInput(skill.schema, input, timezone);
  const issues = validateSkillInput(skill.schema, input);
  if (issues.length) throw new Error(`Check ${issues.map((issue) => `${issue.path}: ${issue.code}`).join(", ")}`);
  const cost = typeof skill.pricing?.fixed === "number" ? `${skill.pricing.fixed} credits per request` : "Credits may be charged";
  return { appId: skill.appId, skillId: skill.skillId, input, summary: `${skill.name} · ${cost}` };
}

export function buildTuiAppsRunConfirmation(run: TuiAppsPreparedRun): TuiForm {
  return { kind: "app-skill-confirm", title: `Run ${run.appId}/${run.skillId}? ${run.summary}`, contextId: `${run.appId}/${run.skillId}`, fieldIndex: 0,
    fields: [{ name: "confirm", label: "Type RUN to execute and accept any credit charge", value: "" }] };
}

function responseResults(response: unknown): unknown[] {
  const source = record(response).data ?? response;
  if (Array.isArray(source)) return source.flatMap((item) => {
    const nested = responseResults(item);
    return nested.length ? nested : [item];
  });
  const data = record(source);
  const results = data.results;
  if (!Array.isArray(results)) return typeof data.embed_id === "string" && UUID.test(data.embed_id) ? [data] : [];
  return results.flatMap((item) => Array.isArray(record(item).results) ? record(item).results as unknown[] : [item]);
}

function linkedResultIds(response: unknown, results: unknown[]): string[] {
  const data = record(record(response).data ?? response);
  const resultIds = new Set(results.map((item) => string(record(item).embed_id)).filter((id) => UUID.test(id)));
  const candidates = data.child_embed_ids ?? data.embed_ids;
  return Array.isArray(candidates)
    ? [...new Set(candidates.filter((id): id is string => typeof id === "string" && UUID.test(id) && !resultIds.has(id)))] : [];
}

function resultContent(appId: string, skillId: string, input: Record<string, unknown>, response: unknown, status: string, embedIds: string[] = []): Record<string, unknown> {
  const data = record(record(response).data ?? response);
  const results = responseResults(response);
  return { ...data, app_id: appId, skill_id: skillId, input, results, status, result_count: results.length, embed_ids: embedIds };
}

async function saveEncryptedResult(client: OpenMatesClient, ownerId: string, rootId: string, key: Uint8Array, encryptedKey: string, run: TuiAppsPreparedRun, response: unknown, status: string): Promise<void> {
  const results = status === "finished" ? responseResults(response) : [];
  if (results.length > 500) throw new Error("Apps result exceeds the supported graph size.");
  const linkedIds = linkedResultIds(response, results);
  const children = await Promise.all(results.flatMap((result): Array<Promise<Record<string, unknown>>> => {
    const value = record(result);
    const type = string(value.type, string(value.embed_type));
    if (!type && typeof value.embed_id !== "string") return [];
    const id = typeof value.embed_id === "string" && UUID.test(value.embed_id) ? value.embed_id : randomUUID();
    return [(async () => ({
      embed_id: id, encrypted_type: await encryptWithAesGcmCombined(type || "app_skill_use", key),
      encrypted_content: await encryptWithAesGcmCombined(JSON.stringify({ app_id: run.appId, skill_id: run.skillId, ...value, result }), key),
      status: "finished", parent_embed_id: rootId,
    }))()];
  }));
  const childIds = children.map((child) => string(child.embed_id));
  const allIds = [...childIds, ...linkedIds];
  const content = resultContent(run.appId, run.skillId, run.input, response, status, allIds);
  await client.saveAppsWorkspaceResult({
    app_id: run.appId, skill_id: run.skillId, root_embed_id: rootId, expected_user_id: ownerId,
    encrypted_embed_key: encryptedKey, linked_embed_ids: linkedIds,
    embeds: [{ embed_id: rootId, encrypted_type: await encryptWithAesGcmCombined("app_skill_use", key),
      encrypted_content: await encryptWithAesGcmCombined(JSON.stringify(content), key), status, embed_ids: allIds }, ...children],
  });
}

/** Only this confirmed path dispatches a potentially billable skill. */
export function executeTuiAppsSkill(client: OpenMatesClient, run: TuiAppsPreparedRun, confirmation: TuiForm): Promise<TuiAppsSavedResult> {
  if (confirmation.kind !== "app-skill-confirm" || confirmation.contextId !== `${run.appId}/${run.skillId}` || formValue(confirmation, "confirm") !== "RUN") {
    return Promise.reject(new Error("Type RUN to confirm skill execution and possible credit charge."));
  }
  const pending = pendingConfirmations.get(confirmation);
  if (pending) return pending;
  const operation = executeConfirmedTuiAppsSkill(client, run);
  pendingConfirmations.set(confirmation, operation);
  void operation.then(() => pendingConfirmations.delete(confirmation), () => pendingConfirmations.delete(confirmation));
  return operation;
}

async function executeConfirmedTuiAppsSkill(client: OpenMatesClient, run: TuiAppsPreparedRun): Promise<TuiAppsSavedResult> {
  if (!client.hasSession()) throw new Error("Sign in to run Apps skills in the terminal.");
  if (client.getActiveTeamId()) throw new Error("Switch to Personal to run Apps skills in the terminal.");
  const owner = record(await client.whoAmI());
  const ownerId = string(owner.id, string(owner.user_id));
  if (!ownerId) throw new Error("Account identity unavailable; skill was not run.");
  const rootId = randomUUID();
  const key = randomBytes(32);
  const encryptedKey = await encryptBytesWithAesGcm(key, client.getMasterKeyBytes());
  await saveEncryptedResult(client, ownerId, rootId, key, encryptedKey, run, { status: "processing" }, "processing");
  const beforeDispatch = record(await client.whoAmI());
  if (string(beforeDispatch.id, string(beforeDispatch.user_id)) !== ownerId || client.getActiveTeamId()) {
    throw new Error(`Account context changed; skill was not run. The pending result is ${rootId}.`);
  }
  let response: unknown;
  try {
    response = await client.runSkill({ app: run.appId, skill: run.skillId, inputData: run.input });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    // A timed-out async task may still complete; leave its accepted root in processing.
    if (!/Task \S+ did not complete within/.test(message)) {
      const current = record(await client.whoAmI());
      if (string(current.id, string(current.user_id)) === ownerId && !client.getActiveTeamId()) {
        await saveEncryptedResult(client, ownerId, rootId, key, encryptedKey, run, { error: message }, "error");
      }
    }
    throw new Error(`${message} Saved Apps result: ${rootId}`);
  }
  const current = record(await client.whoAmI());
  if (string(current.id, string(current.user_id)) !== ownerId || client.getActiveTeamId()) throw new Error(`Account context changed; accepted result ${rootId} can be reopened from Apps history.`);
  try {
    await saveEncryptedResult(client, ownerId, rootId, key, encryptedKey, run, response, "finished");
  } catch {
    const afterFailure = record(await client.whoAmI());
    if (string(afterFailure.id, string(afterFailure.user_id)) !== ownerId || client.getActiveTeamId()) {
      throw new Error(`Account context changed; accepted result ${rootId} can be reopened from Apps history.`);
    }
    return { embedId: rootId, appId: run.appId, skillId: run.skillId, status: "unsaved",
      content: resultContent(run.appId, run.skillId, run.input, response, "unsaved"), children: [],
      retentionError: "The skill completed, but its result could not be saved. Copy the response before leaving this screen." };
  }
  return loadTuiAppsResult(client, rootId);
}

export async function loadTuiAppsResults(client: Pick<OpenMatesClient, "listAppsWorkspaceResults" | "getActiveTeamId">, appId: string, offset = 0): Promise<TuiAppsResultsPage> {
  if (!APP_ID.test(appId)) throw new Error("Invalid app ID.");
  if (client.getActiveTeamId()) throw new Error("Switch to Personal to browse Apps results in the terminal.");
  const page = record(await client.listAppsWorkspaceResults(appId, offset, RESULT_PAGE_SIZE));
  return { items: rows(page.items).map((item) => ({ embedId: string(item.embed_id), appId: string(item.app_id), skillId: string(item.skill_id),
    createdAt: typeof item.created_at === "number" ? item.created_at : 0, status: string(item.status) })), hasMore: page.has_more === true, offset: typeof page.offset === "number" ? page.offset : offset };
}

export async function loadTuiAppsWorkflows(client: Pick<OpenMatesClient, "listAppsWorkspaceWorkflows" | "getActiveTeamId">, appId: string, offset = 0): Promise<TuiAppsWorkflowPage> {
  if (!APP_ID.test(appId)) throw new Error("Invalid app ID.");
  if (client.getActiveTeamId()) throw new Error("Switch to Personal to browse Apps workflows in the terminal.");
  const page = record(await client.listAppsWorkspaceWorkflows(appId, offset, RESULT_PAGE_SIZE));
  return { items: rows(page.workflows).map((item) => ({ id: string(item.id), title: string(item.title, string(item.id)) })).filter((item) => item.id),
    hasMore: page.has_more === true, offset: typeof page.offset === "number" ? page.offset : offset };
}

export function renderTuiAppsWorkflows(page: TuiAppsWorkflowPage, options: { width: number; selectedId?: string }): string[] {
  const width = Math.max(1, options.width);
  const lines = ["Related workflows", ""];
  if (!page.items.length) lines.push("No workflows for this app.");
  for (const workflow of page.items) lines.push(truncateCells(`${workflow.id === options.selectedId ? ">" : " "} ${workflow.title} · ${workflow.id.slice(0, 8)}`, width));
  if (page.offset > 0 || page.hasMore) lines.push("", `Page ${Math.floor(page.offset / RESULT_PAGE_SIZE) + 1} · previous/next available`);
  return lines;
}

async function decryptedRow(row: Record<string, unknown>, key: Uint8Array): Promise<{ embedId: string; type: string; content: Record<string, unknown> }> {
  const type = await decryptWithAesGcmCombined(string(row.encrypted_type), key);
  const content = await decryptWithAesGcmCombined(string(row.encrypted_content), key);
  if (type === null || content === null) throw new Error("Apps result could not be decrypted.");
  return { embedId: string(row.embed_id), type, content: record(JSON.parse(content)) };
}

export async function loadTuiAppsResult(client: Pick<OpenMatesClient, "getAppsWorkspaceResult" | "getMasterKeyBytes" | "getActiveTeamId">, embedId: string): Promise<TuiAppsSavedResult> {
  if (client.getActiveTeamId()) throw new Error("Switch to Personal to inspect Apps results in the terminal.");
  const detail = record(await client.getAppsWorkspaceResult(embedId));
  const root = record(detail.root), wrapper = record(detail.key);
  if (!wrapper.encrypted_embed_key || wrapper.key_type !== "master") throw new Error("This result needs its original chat or Team key. Open it in the web app.");
  const key = await decryptBytesWithAesGcm(string(wrapper.encrypted_embed_key), client.getMasterKeyBytes());
  if (!key) throw new Error("Apps result key could not be decrypted.");
  const decrypted = await decryptedRow(root, key);
  if (decrypted.embedId !== embedId) throw new Error("Apps result ID mismatch.");
  const children = await Promise.all(rows(detail.children).map((row) => decryptedRow(row, key)));
  return { embedId, appId: string(root.app_id), skillId: string(root.skill_id), status: string(root.status), content: decrypted.content, children };
}

export function renderTuiAppsResults(page: TuiAppsResultsPage, options: { width: number; selectedId?: string }): string[] {
  const width = Math.max(1, options.width);
  const lines = ["Saved results", ""];
  if (!page.items.length) lines.push("No saved results for this app.");
  for (const item of page.items) lines.push(truncateCells(`${item.embedId === options.selectedId ? ">" : " "} ${item.skillId} · ${item.status} · ${item.embedId.slice(0, 8)}`, width));
  if (page.offset > 0 || page.hasMore) lines.push("", `Page ${Math.floor(page.offset / RESULT_PAGE_SIZE) + 1} · previous/next available`);
  return lines;
}

export function renderTuiAppsResult(result: TuiAppsSavedResult, width: number): string[] {
  width = Math.max(1, width);
  const lines = [`${result.appId} / ${result.skillId}`, `Result ${result.embedId} · ${result.status}`, ""];
  if (result.retentionError) lines.push(result.retentionError, "");
  lines.push(...embedPreview(result.embedId, "app_skill_use", result.content, result.appId, result.skillId,
    `/app-result ${result.embedId}`, width));
  if (result.children.length) {
    lines.push("", `Embeds (${result.children.length})`);
    for (const child of result.children) {
      lines.push("", ...embedPreview(child.embedId, child.type, child.content, null, null, `/embed ${child.embedId}`, width));
      const details = Object.fromEntries(Object.entries(child.content).filter(([key]) => !CHILD_BOOKKEEPING_FIELDS.has(key)));
      if (Object.keys(details).length) lines.push(...readableFields(details, width).slice(0, result.retentionError ? undefined : 4));
    }
  }
  const input = record(result.content.input);
  if (Object.keys(input).length) lines.push("", "Request", ...readableFields(input, width));
  const response = Object.fromEntries(Object.entries(result.content).filter(([key]) => !RESULT_BOOKKEEPING_FIELDS.has(key)));
  if (Object.keys(response).length) lines.push("", "Response", ...readableFields(response, width));
  else if (!result.children.length) lines.push("", result.status === "processing" ? "Waiting for the skill result." : "No result content was returned.");
  const wrapped = lines.flatMap((line) => textLines(line, width));
  if (result.retentionError || wrapped.length <= MAX_RESULT_LINES) return wrapped;
  return [...wrapped.slice(0, MAX_RESULT_LINES - 1), "… more content is available in the web app"];
}

const RESULT_BOOKKEEPING_FIELDS = new Set(["app_id", "skill_id", "input", "status", "result_count", "embed_ids", "child_embed_ids", "task_id", "task_ids"]);
const CHILD_BOOKKEEPING_FIELDS = new Set(["app_id", "skill_id", "embed_id", "embed_type", "type"]);

function embedPreview(embedId: string, type: string, content: Record<string, unknown>, appId: string | null, skillId: string | null, action: string, width: number): string[] {
  const display = appId ? content : Object.fromEntries(Object.entries(content).filter(([key]) => key !== "app_id" && key !== "skill_id"));
  const preview = formatEmbedPreviewLines({ id: embedId, embedId, type, textPreview: null, content: display,
    appId, skillId, createdAt: null }, 3);
  return preview.map((line) => line.startsWith("└─") ? `└─ ${action}` : line).flatMap((line) => textLines(line, width));
}

function readableFields(value: Record<string, unknown>, width: number): string[] {
  const lines: string[] = [];
  function visit(label: string, item: unknown, indent: string): void {
    if (Array.isArray(item)) {
      lines.push(`${indent}${label} (${item.length})`);
      item.forEach((entry, index) => visit(`${index + 1}.`, entry, `${indent}  `));
    } else if (item && typeof item === "object") {
      lines.push(`${indent}${label}`);
      for (const [key, entry] of Object.entries(item)) visit(readableLabel(key), entry, `${indent}  `);
    } else {
      const text = item === null ? "None" : typeof item === "boolean" ? item ? "Yes" : "No" : String(item);
      const [first = "", ...rest] = text.split("\n");
      lines.push(`${indent}${label} ${first}`);
      lines.push(...rest.map((line) => `${indent}  ${line}`));
    }
  }
  for (const [key, item] of Object.entries(value)) visit(`${readableLabel(key)}:`, item, "");
  return lines.flatMap((line) => textLines(line, width));
}

function readableLabel(key: string): string {
  const label = key.replace(/[_-]+/g, " ").replace(/([a-z])([A-Z])/g, "$1 $2");
  return label ? label[0]!.toUpperCase() + label.slice(1) : "Value";
}
