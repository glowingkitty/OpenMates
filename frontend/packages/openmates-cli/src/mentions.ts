// frontend/packages/openmates-cli/src/mentions.ts
/**
 * @file CLI mention resolver — parses @mentions in user messages and
 * resolves them to backend wire syntax.
 *
 * In the web app, the TipTap editor resolves mentions during typing via
 * MentionDropdown.svelte + mentionSearchService.ts. In the CLI, we resolve
 * mentions post-input (after the user submits the message) since there is
 * no interactive dropdown during typing.
 *
 * Resolution order for each @token:
 *   1. Model alias (@best, @fast)
 *   2. Model name (@Claude-Opus-4.6 → @ai-model:claude-opus-4-6)
 *   3. Mate name (@Sophia → @mate:software_development)
 *   4. Skill (@Code-Get-Docs → @skill:code:get_docs)
 *   5. Focus mode (@Web-Research → @focus:web:research)
 *   6. Memory category (@Code-Projects → @memory:code:projects:list)
 *   7. Memory entry (@Code-Projects-MyApp → @memory-entry:code:projects:abc123)
 *   8. File path (if valid local filesystem path → handled by caller)
 *   9. Error (suggest corrections)
 *
 * Mirrors: mentionSearchService.ts (web app)
 * Backend parser: backend/core/api/app/utils/override_parser.py
 *
 * Architecture: docs/architecture/apps/cli-package.md (CLI Commands Reference)
 */

// ── Types ──────────────────────────────────────────────────────────────

/** Mention type aligned with web app's MentionType */
export type MentionType =
  | "model"
  | "model_alias"
  | "mate"
  | "skill"
  | "focus_mode"
  | "settings_memory"
  | "settings_memory_entry"
  | "file_path"
  | "unknown";

/** A resolved mention ready for wire format injection */
export interface ResolvedMention {
  /** The original @token as typed by the user (e.g., "@Sophia") */
  original: string;
  /** What kind of mention this resolved to */
  type: MentionType;
  /** Wire syntax for the backend (e.g., "@mate:software_development") */
  wireSyntax: string;
  /** Human-readable display name for confirmation */
  displayName: string;
}

/** An unresolved mention with suggestions */
export interface UnresolvedMention {
  /** The original @token as typed by the user */
  original: string;
  /** Suggested corrections (fuzzy-matched known mentions) */
  suggestions: string[];
}

/** Result of parsing a message for mentions */
export interface MentionParseResult {
  /** The message with @tokens replaced by wire syntax */
  processedMessage: string;
  /** Successfully resolved mentions */
  resolved: ResolvedMention[];
  /** File path mentions (handled separately by the caller) */
  filePaths: string[];
  /** Mentions that could not be resolved */
  unresolved: UnresolvedMention[];
}

// ── Data types for mention resolution context ──────────────────────────

/** Minimal model info needed for mention resolution */
export interface ModelInfo {
  id: string;
  name: string;
}

/** Minimal app info from /v1/apps */
export interface AppInfo {
  id: string;
  name: string;
  skills?: Array<{ id: string; name: string }>;
  focus_modes?: Array<{ id: string; name: string }>;
  settings_and_memories?: Array<{ id: string; name: string; type?: string }>;
}

/** Minimal memory entry info */
export interface MemoryEntryInfo {
  id: string;
  app_id: string;
  item_type: string;
  title?: string;
}

/** All data needed to resolve mentions */
export interface MentionContext {
  models: ModelInfo[];
  mates: Record<string, string>; // category_id → display name
  apps: AppInfo[];
  memoryEntries: MemoryEntryInfo[];
}

// ── Model aliases (mirrors mentionSearchService.ts:308-313) ────────────

/**
 * Model alias shortcuts. When a user types @best or @fast, it resolves
 * to the corresponding model via @best-model:alias wire syntax.
 *
 * Kept in sync with: mentionSearchService.ts MODEL_ALIASES
 * Backend resolution: preprocessor.py lines 1664-1686
 */
export const MODEL_ALIASES: Record<string, string> = {
  best: "claude-opus-4-6",
  fast: "qwen3-235b-a22b-2507",
};

// ── Chat-eligible model IDs (for_app_skill === "ai.ask") ───────────────

/**
 * Models available for chat @mentions. Only models with for_app_skill="ai.ask"
 * appear in the mention dropdown in the web app.
 *
 * Kept in sync with: modelsMetadata.ts (auto-generated from backend provider YAMLs)
 *
 * Format: { id, name } — minimal subset for mention resolution.
 * NOTE: When modelsMetadata.ts changes, update this list.
 */
export const CHAT_MODELS: ModelInfo[] = [
  { id: "claude-opus-4-6", name: "Claude Opus 4.6" },
  { id: "claude-sonnet-4-6", name: "Claude Sonnet 4.6" },
  { id: "claude-haiku-4-5-20251001", name: "Claude Haiku 4.5" },
  { id: "gpt-5.4", name: "GPT-5.4" },
  { id: "gpt-oss-120b", name: "GPT-OSS-120b" },
  { id: "gemini-3-flash-preview", name: "Gemini 3 Flash" },
  { id: "gemini-3-pro-image-preview", name: "Gemini 3 Pro" },
  { id: "gemini-3.1-pro-preview", name: "Gemini 3.1 Pro" },
  { id: "deepseek-v3.2", name: "DeepSeek V3.2" },
  { id: "qwen3-235b-a22b-2507", name: "Qwen 3 256b" },
  { id: "kimi-k2.5", name: "Kimi K2.5" },
  { id: "zai-glm-4.7", name: "GLM 4.7" },
  { id: "mistral-medium-latest", name: "Mistral Medium" },
  { id: "mistral-small-2506", name: "Mistral Small 3.2" },
  { id: "mistral-small-latest", name: "Mistral Small 4" },
  { id: "devstral-2512", name: "Devstral 2" },
];

// ── Core parsing ───────────────────────────────────────────────────────

/**
 * Regex to find @mentions in message text.
 * Matches @ followed by a non-whitespace sequence. The mention ends at
 * the next whitespace or end of string.
 *
 * Handles hyphenated names like @Claude-Opus-4.6 or @Code-Get-Docs.
 * Also handles file paths like @/home/user/.env or @./config.ts.
 */
const MENTION_REGEX = /(?:^|\s)@(\/[^\s]+|\.\/[^\s]+|~\/[^\s]+|[^\s@]+)/g;

/**
 * Extract raw @mention tokens from message text.
 * Returns the captured group (without the @ prefix).
 */
export function extractMentionTokens(message: string): string[] {
  const tokens: string[] = [];
  MENTION_REGEX.lastIndex = 0;
  let match;
  while ((match = MENTION_REGEX.exec(message)) !== null) {
    tokens.push(match[1]);
  }
  return tokens;
}

/**
 * Check if a token looks like a filesystem path.
 */
function isFilePath(token: string): boolean {
  return (
    token.startsWith("/") ||
    token.startsWith("./") ||
    token.startsWith("~/") ||
    token.startsWith("../")
  );
}

/**
 * Normalize a display name for comparison.
 * "Claude Opus 4.6" → "claude-opus-4.6"
 * "Code-Get-Docs" → "code-get-docs"
 */
function normalize(name: string): string {
  return name
    .toLowerCase()
    .replace(/\s+/g, "-")
    .replace(/[^a-z0-9._-]/g, "");
}

/**
 * Simple fuzzy score: how well does `query` match `candidate`?
 * Returns 0-100. Higher = better match.
 */
function fuzzyScore(query: string, candidate: string): number {
  const q = normalize(query);
  const c = normalize(candidate);
  if (q === c) return 100;
  if (c.startsWith(q)) return 75;
  if (c.includes(q)) return 50;
  // Levenshtein-like: count matching chars in order
  let qi = 0;
  let matched = 0;
  for (let ci = 0; ci < c.length && qi < q.length; ci++) {
    if (c[ci] === q[qi]) {
      matched++;
      qi++;
    }
  }
  return Math.round((matched / Math.max(q.length, 1)) * 40);
}

// ── Resolver ───────────────────────────────────────────────────────────

/**
 * Try to resolve a single @mention token against known mention types.
 * Returns a ResolvedMention if successful, null otherwise.
 */
function resolveToken(
  token: string,
  context: MentionContext,
): ResolvedMention | null {
  const normalized = normalize(token);

  // 1. Model alias (@best, @fast)
  if (MODEL_ALIASES[normalized]) {
    return {
      original: `@${token}`,
      type: "model_alias",
      wireSyntax: `@best-model:${normalized}`,
      displayName: `@${token.charAt(0).toUpperCase() + token.slice(1).toLowerCase()}`,
    };
  }

  // 2. Model name (@Claude-Opus-4.6)
  for (const model of context.models) {
    if (normalize(model.name) === normalized || model.id === normalized) {
      return {
        original: `@${token}`,
        type: "model",
        wireSyntax: `@ai-model:${model.id}`,
        displayName: `@${model.name.replace(/\s+/g, "-")}`,
      };
    }
  }

  // 3. Mate name (@Sophia → @mate:software_development)
  for (const [categoryId, displayName] of Object.entries(context.mates)) {
    if (normalize(displayName) === normalized || normalize(categoryId) === normalized) {
      return {
        original: `@${token}`,
        type: "mate",
        wireSyntax: `@mate:${categoryId}`,
        displayName: `@${displayName}`,
      };
    }
  }

  // 4. Skill (@Code-Get-Docs → @skill:code:get_docs)
  //    Parse App-Skill format: split on first hyphen to get app prefix
  for (const app of context.apps) {
    if (!app.skills) continue;
    for (const skill of app.skills) {
      // Build the display form: "Code-Get-Docs" from app.name="Code", skill.name="Get Docs"
      const displayForm = normalize(`${app.name}-${skill.name}`);
      // Also try skill.id directly
      const directForm = normalize(`${app.id}-${skill.id}`);
      if (normalized === displayForm || normalized === directForm) {
        return {
          original: `@${token}`,
          type: "skill",
          wireSyntax: `@skill:${app.id}:${skill.id}`,
          displayName: `@${capitalize(app.name)}-${capitalize(skill.name).replace(/\s+/g, "-")}`,
        };
      }
    }
  }

  // 5. Focus mode (@Web-Research → @focus:web:research)
  for (const app of context.apps) {
    if (!app.focus_modes) continue;
    for (const fm of app.focus_modes) {
      const displayForm = normalize(`${app.name}-${fm.name}`);
      const directForm = normalize(`${app.id}-${fm.id}`);
      if (normalized === displayForm || normalized === directForm) {
        return {
          original: `@${token}`,
          type: "focus_mode",
          wireSyntax: `@focus:${app.id}:${fm.id}`,
          displayName: `@${capitalize(app.name)}-${capitalize(fm.name).replace(/\s+/g, "-")}`,
        };
      }
    }
  }

  // 6. Memory category (@Code-Projects → @memory:code:projects:list)
  for (const app of context.apps) {
    if (!app.settings_and_memories) continue;
    for (const mem of app.settings_and_memories) {
      const displayForm = normalize(`${app.name}-${mem.name}`);
      const directForm = normalize(`${app.id}-${mem.id}`);
      if (normalized === displayForm || normalized === directForm) {
        const memType = mem.type || "list";
        return {
          original: `@${token}`,
          type: "settings_memory",
          wireSyntax: `@memory:${app.id}:${mem.id}:${memType}`,
          displayName: `@${capitalize(app.name)}-${capitalize(mem.name).replace(/\s+/g, "-")}`,
        };
      }
    }
  }

  // 7. Memory entry (@Code-Projects-React → @memory-entry:code:projects:abc123)
  //    This is the trickiest: App-Category-EntryTitle
  for (const entry of context.memoryEntries) {
    const app = context.apps.find((a) => a.id === entry.app_id);
    if (!app) continue;

    const entryTitle = entry.title || entry.id;
    // Match full path: App-Category-Title
    const displayForm = normalize(`${app.name}-${entry.item_type}-${entryTitle}`);
    // Also try with just App-Title (user might omit category)
    const shortForm = normalize(`${app.name}-${entryTitle}`);

    if (normalized === displayForm || normalized === shortForm) {
      // Need to find the memory category id for the wire format
      const category = app.settings_and_memories?.find(
        (m) => m.id === entry.item_type || normalize(m.name) === normalize(entry.item_type),
      );
      const categoryId = category?.id || entry.item_type;

      return {
        original: `@${token}`,
        type: "settings_memory_entry",
        wireSyntax: `@memory-entry:${app.id}:${categoryId}:${entry.id}`,
        displayName: `@${capitalize(app.name)}-${capitalize(entry.item_type).replace(/\s+/g, "-")}-${capitalize(entryTitle).replace(/\s+/g, "-")}`,
      };
    }
  }

  return null;
}

/**
 * Collect all known mention display names for fuzzy suggestion.
 */
function getAllKnownMentions(context: MentionContext): string[] {
  const mentions: string[] = [];

  // Aliases
  for (const alias of Object.keys(MODEL_ALIASES)) {
    mentions.push(alias.charAt(0).toUpperCase() + alias.slice(1));
  }

  // Models
  for (const model of context.models) {
    mentions.push(model.name.replace(/\s+/g, "-"));
  }

  // Mates
  for (const name of Object.values(context.mates)) {
    mentions.push(name);
  }

  // Skills, focus modes, memory categories
  for (const app of context.apps) {
    if (app.skills) {
      for (const skill of app.skills) {
        mentions.push(`${capitalize(app.name)}-${capitalize(skill.name).replace(/\s+/g, "-")}`);
      }
    }
    if (app.focus_modes) {
      for (const fm of app.focus_modes) {
        mentions.push(`${capitalize(app.name)}-${capitalize(fm.name).replace(/\s+/g, "-")}`);
      }
    }
    if (app.settings_and_memories) {
      for (const mem of app.settings_and_memories) {
        mentions.push(`${capitalize(app.name)}-${capitalize(mem.name).replace(/\s+/g, "-")}`);
      }
    }
  }

  return mentions;
}

/**
 * Parse a user message, resolve all @mentions to wire syntax.
 *
 * @param message The raw user message
 * @param context All available mention data (models, mates, apps, etc.)
 * @returns Parse result with processed message, resolved mentions, and errors
 */
export function parseMentions(
  message: string,
  context: MentionContext,
): MentionParseResult {
  const tokens = extractMentionTokens(message);

  if (tokens.length === 0) {
    return {
      processedMessage: message,
      resolved: [],
      filePaths: [],
      unresolved: [],
    };
  }

  const resolved: ResolvedMention[] = [];
  const filePaths: string[] = [];
  const unresolved: UnresolvedMention[] = [];
  let processedMessage = message;

  for (const token of tokens) {
    // Check if it's a file path first
    if (isFilePath(token)) {
      filePaths.push(token);
      continue; // Leave in message as-is — caller handles file processing
    }

    // Try to resolve against known mentions
    const resolved_ = resolveToken(token, context);
    if (resolved_) {
      resolved.push(resolved_);
      // Replace the display token with wire syntax in the message
      // Use word boundary matching to avoid partial replacements
      processedMessage = processedMessage.replace(
        new RegExp(`@${escapeRegExp(token)}(?=\\s|$)`, "g"),
        resolved_.wireSyntax,
      );
    } else {
      // Unresolved — generate suggestions
      const allMentions = getAllKnownMentions(context);
      const scored = allMentions
        .map((m) => ({ name: m, score: fuzzyScore(token, m) }))
        .filter((s) => s.score >= 30)
        .sort((a, b) => b.score - a.score)
        .slice(0, 5);

      unresolved.push({
        original: `@${token}`,
        suggestions: scored.map((s) => `@${s.name}`),
      });
    }
  }

  return { processedMessage, resolved, filePaths, unresolved };
}

// ── Listing all available mentions ─────────────────────────────────────

/** A mention option for the `openmates mentions list` command */
export interface MentionOption {
  type: MentionType;
  displayName: string;
  description: string;
}

/**
 * List all available mention options.
 *
 * @param context Mention resolution context
 * @param filter Optional type filter
 * @returns Array of mention options grouped by type
 */
export function listMentionOptions(
  context: MentionContext,
  filter?: MentionType,
): MentionOption[] {
  const options: MentionOption[] = [];

  // Model aliases
  if (!filter || filter === "model_alias") {
    for (const [alias, modelId] of Object.entries(MODEL_ALIASES)) {
      const model = context.models.find((m) => m.id === modelId);
      options.push({
        type: "model_alias",
        displayName: `@${alias.charAt(0).toUpperCase() + alias.slice(1)}`,
        description: `Alias → ${model?.name || modelId}`,
      });
    }
  }

  // Models
  if (!filter || filter === "model") {
    for (const model of context.models) {
      options.push({
        type: "model",
        displayName: `@${model.name.replace(/\s+/g, "-")}`,
        description: `Model: ${model.name}`,
      });
    }
  }

  // Mates
  if (!filter || filter === "mate") {
    for (const [categoryId, name] of Object.entries(context.mates)) {
      const categoryLabel = categoryId.replace(/_/g, " ");
      options.push({
        type: "mate",
        displayName: `@${name}`,
        description: `Mate: ${capitalize(categoryLabel)}`,
      });
    }
  }

  // Skills
  if (!filter || filter === "skill") {
    for (const app of context.apps) {
      if (!app.skills) continue;
      for (const skill of app.skills) {
        // Skip the ai.ask skill (same as web app — line 396 of mentionSearchService.ts)
        if (app.id === "ai" && skill.id === "ask") continue;
        options.push({
          type: "skill",
          displayName: `@${capitalize(app.name)}-${capitalize(skill.name).replace(/\s+/g, "-")}`,
          description: `Skill: ${capitalize(app.name)} → ${capitalize(skill.name)}`,
        });
      }
    }
  }

  // Focus modes
  if (!filter || filter === "focus_mode") {
    for (const app of context.apps) {
      if (!app.focus_modes) continue;
      for (const fm of app.focus_modes) {
        options.push({
          type: "focus_mode",
          displayName: `@${capitalize(app.name)}-${capitalize(fm.name).replace(/\s+/g, "-")}`,
          description: `Focus: ${capitalize(app.name)} → ${capitalize(fm.name)}`,
        });
      }
    }
  }

  // Memory categories
  if (!filter || filter === "settings_memory") {
    for (const app of context.apps) {
      if (!app.settings_and_memories) continue;
      for (const mem of app.settings_and_memories) {
        options.push({
          type: "settings_memory",
          displayName: `@${capitalize(app.name)}-${capitalize(mem.name).replace(/\s+/g, "-")}`,
          description: `Memory: ${capitalize(app.name)} → ${capitalize(mem.name)}`,
        });
      }
    }
  }

  return options;
}

// ── Helpers ─────────────────────────────────────────────────────────────

function capitalize(s: string): string {
  return s
    .split(/[\s_]+/)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
