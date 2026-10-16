/** Pure mention choices for the terminal composer. Account data is supplied by its owner. */
import { MODEL_ALIASES, type MentionContext } from "./mentions.js";
import type { TuiModelEntry } from "./tuiModelSelector.js";
import { terminalText } from "./tuiText.js";

export type TuiMentionType = "wikipedia_source" | "wikipedia" | "model_alias" | "model" | "mate" |
  "skill" | "focus_mode" | "settings_memory" | "settings_memory_entry" |
  "project" | "project_folder" | "project_file" | "team_ai";

export interface TuiMentionSuggestion {
  id: string;
  type: TuiMentionType;
  label: string;
  description: string;
  wireSyntax: string;
  /** Canonical provider/model route for the composer model selector. */
  modelId?: string;
  /** Additional search names. Kept on the catalog item to make search deterministic. */
  searchTerms?: string[];
}

export interface TuiMentionRange { start: number; end: number; query: string }

/** Decrypted, owner-scoped Project data prepared by the composer shell. */
export interface TuiMentionProject {
  id: string;
  name: string;
  description?: string;
  accessMode?: "read" | "read_write";
  files?: Array<{ path: string; name?: string; sourceId?: string }>;
  folders?: Array<{ path: string; name?: string; sourceId?: string }>;
}

/** Web composer rule: @ starts at the beginning of text or after whitespace. */
export function extractTuiMention(input: string, cursor: number): TuiMentionRange | null {
  if (!Number.isInteger(cursor) || cursor < 0 || cursor > input.length) return null;
  const before = input.slice(0, cursor);
  const start = before.lastIndexOf("@");
  if (start < 0 || (start > 0 && !/[ \n\t]/.test(before[start - 1]))) return null;
  const query = before.slice(start + 1);
  if (/\s/.test(query) || query.includes("@")) return null;
  return { start, end: cursor, query };
}

function safe(value: unknown): string {
  return typeof value === "string" ? terminalText(value).replace(/\s+/g, " ").trim() : "";
}
function label(value: string): string { return `@${safe(value).replace(/\s+/g, "-")}`; }
function displayId(value: string): string {
  return value.split(/[-_\s]+/).filter(Boolean).map(part => part[0].toUpperCase() + part.slice(1)).join("-");
}
function plainModelId(model: TuiModelEntry): string {
  const prefix = `${model.providerId}/`;
  return model.id.startsWith(prefix) ? model.id.slice(prefix.length) : model.id;
}

export function buildTuiMentionCatalog(
  context: MentionContext, models: TuiModelEntry[], projects: TuiMentionProject[], team: boolean,
): TuiMentionSuggestion[] {
  const choices: TuiMentionSuggestion[] = [{
    id: "wikipedia-source", type: "wikipedia_source", label: "@Wiki", description: "Wikipedia",
    wireSyntax: "@wiki:", searchTerms: ["wiki", "wikipedia", "encyclopedia"],
  }];
  if (team) choices.push({ id: "team-ai", type: "team_ai", label: "@openmates", description: "Ask OpenMates AI",
    wireSyntax: "@openmates", searchTerms: ["openmates", "ai", "assistant"] });

  const availableModels = models.filter(model => model.available);
  for (const [alias, modelName] of Object.entries(MODEL_ALIASES)) {
    const model = availableModels.find(candidate => plainModelId(candidate) === modelName);
    if (!model) continue;
    choices.push({ id: `alias:${alias}`, type: "model_alias", label: label(displayId(alias)),
      description: model.name, wireSyntax: `@best-model:${alias}`, modelId: model.id,
      searchTerms: [alias, model.name, model.providerName] });
  }
  for (const model of availableModels) {
    const id = plainModelId(model);
    choices.push({ id: `model:${model.id}`, type: "model", label: label(model.name),
      description: model.providerName, wireSyntax: `@ai-model:${id}:${model.providerId}`, modelId: model.id,
      searchTerms: [id, model.name, model.providerName, model.providerBrandName ?? "", model.description ?? ""] });
  }
  for (const [id, name] of Object.entries(context.mates)) {
    if (!safe(name)) continue;
    choices.push({ id: `mate:${id}`, type: "mate", label: label(name), description: "Mate",
      wireSyntax: `@mate:${id}`, searchTerms: [id, name] });
  }
  for (const app of context.apps) {
    const appName = safe(app.name) || displayId(app.id);
    for (const skill of app.skills ?? []) {
      if (app.id === "ai" && skill.id === "ask") continue;
      choices.push({ id: `skill:${app.id}:${skill.id}`, type: "skill", label: label(`${appName}-${safe(skill.name) || displayId(skill.id)}`),
        description: `Skill · ${appName}`, wireSyntax: `@skill:${app.id}:${skill.id}`,
        searchTerms: [app.id, appName, skill.id, skill.name] });
    }
    for (const focus of app.focus_modes ?? []) {
      choices.push({ id: `focus:${app.id}:${focus.id}`, type: "focus_mode", label: label(`${appName}-${safe(focus.name) || displayId(focus.id)}`),
        description: `Focus mode · ${appName}`, wireSyntax: `@focus:${app.id}:${focus.id}`,
        searchTerms: [app.id, appName, focus.id, focus.name] });
    }
    for (const memory of app.settings_and_memories ?? []) {
      const entries = context.memoryEntries.filter(entry => entry.app_id === app.id && entry.item_type === memory.id);
      if (!entries.length) continue;
      const memoryName = safe(memory.name) || displayId(memory.id);
      choices.push({ id: `memory:${app.id}:${memory.id}`, type: "settings_memory", label: label(`${appName}-${memoryName}`),
        description: `Memory · ${entries.length} entries`, wireSyntax: `@memory:${app.id}:${memory.id}:${memory.type || "list"}`,
        searchTerms: [app.id, appName, memory.id, memoryName] });
      for (const entry of entries) {
        const title = safe(entry.title) || entry.id;
        choices.push({ id: `memory-entry:${app.id}:${memory.id}:${entry.id}`, type: "settings_memory_entry",
          label: label(`${appName}-${memoryName}-${title}`), description: `Memory entry · ${memoryName}`,
          wireSyntax: `@memory-entry:${app.id}:${memory.id}:${entry.id}`,
          searchTerms: [title, memoryName, appName] });
      }
    }
  }
  for (const project of projects) {
    const id = safe(project.id);
    const name = safe(project.name);
    if (!id || !name) continue;
    const mode = project.accessMode === "read_write" ? "read_write" : "read";
    choices.push({ id: `project:${id}`, type: "project", label: label(name), description: "Project context",
      wireSyntax: `@project:${id}:${mode}`, searchTerms: [name, id, safe(project.description)] });
    for (const [kind, children] of [["project_folder", project.folders ?? []], ["project_file", project.files ?? []]] as const) {
      for (const child of children) {
        const path = safe(child.path);
        if (!path) continue;
        const source = safe(child.sourceId);
        const segment = source ? `:${source}` : "";
        const wireType = kind === "project_folder" ? "project-folder" : "project-file";
        choices.push({ id: `${kind}:${id}:${source}:${path}`, type: kind,
          label: label(`${name}-${safe(child.name) || path.split("/").filter(Boolean).at(-1) || path}`),
          description: path, wireSyntax: `@${wireType}:${id}${segment}:${encodeURIComponent(path)}:${mode}`,
          searchTerms: [name, id, source, path, safe(child.name)] });
      }
    }
  }
  return choices;
}

function score(query: string, choice: TuiMentionSuggestion): number {
  const terms = [choice.label.slice(1), choice.description, ...(choice.searchTerms ?? [])]
    .flatMap(term => { const lower = safe(term).toLowerCase(); return [lower, ...lower.split(/[\s\-_]+/).filter(part => part.length > 1)]; });
  let value = 0;
  for (const term of new Set(terms)) {
    if (term === query) value += 100;
    else if (term.startsWith(query)) value += 50;
    else if (term.includes(query)) value += 25;
  }
  if (value && (choice.type === "settings_memory" || choice.type === "settings_memory_entry")) value += 30;
  if (value && choice.type === "project") value += 40;
  return value;
}

/** Empty @ mirrors the web's source/alias/top-model defaults; matching Projects lead query results. */
export function searchTuiMentionCatalog(catalog: TuiMentionSuggestion[], query: string): TuiMentionSuggestion[] {
  const trimmed = query.trim().toLowerCase();
  if (!trimmed) {
    const defaults = [
      ...catalog.filter(item => item.type === "wikipedia_source"),
      ...catalog.filter(item => item.type === "team_ai"),
      ...catalog.filter(item => item.type === "model_alias"),
    ];
    return [...defaults, ...catalog.filter(item => item.type === "model").slice(0, Math.max(0, 4 - catalog.filter(item => item.type === "model_alias").length))];
  }
  return catalog.map((item, index) => ({ item, index, score: score(trimmed, item) }))
    .filter(row => row.score > 0)
    .sort((a, b) => Number(b.item.type.startsWith("project")) - Number(a.item.type.startsWith("project")) ||
      b.score - a.score || a.index - b.index)
    .slice(0, 8).map(row => row.item);
}
