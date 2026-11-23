/**
 * Shared display formatting for backend mention syntax (@ai-model:..., @mate:...,
 * @project:...). Used by draft saving, draft/chat previews and temporary chat
 * titles so every surface shows the same readable names and never an id.
 */
import { get } from "svelte/store";
import { text as translations } from "../i18n/translations";
import { modelsMetadata } from "../data/modelsMetadata";
import { projectNameLookup, type ProjectNameLookup } from "./mentionProjectNames";
import { matesMetadata } from "../data/matesMetadata";
import { appSkillsStore } from "../stores/appSkillsStore";

/**
 * Convert a name to hyphenated format for mention display.
 * e.g., "Claude 4.5 Opus" -> "Claude-4.5-Opus"
 */
function toHyphenatedName(name: string): string {
  return name.replace(/\s+/g, "-");
}

/**
 * Capitalize first letter of each word for display.
 * e.g., "get-docs" -> "Get-Docs"
 */
function capitalizeWords(str: string): string {
  return str
    .split("-")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join("-");
}

export { registerMentionProjectNameLookup, knownProjectMentionName, type ProjectNameLookup } from "./mentionProjectNames";

const PROJECT_MENTION = /@project:([a-zA-Z0-9_.-]+):(?:read_write|read)\b/g;
const PROJECT_SCOPED_MENTION =
  /@project-(?:folder|file):[a-zA-Z0-9_.-]+:(?:[a-zA-Z0-9_.-]+:)?([^\s:]+):(?:read_write|read)\b/g;
const MEMORY_ENTRY_MENTION = /@memory-entry:[a-zA-Z0-9_.-]+:[a-zA-Z0-9_.-]+:[a-zA-Z0-9_.-]+/g;
const WIKIPEDIA_MENTION = /@wikipedia:[a-z]{2,10}:([^\s]+)/g;
// Anything still shaped like backend mention syntax after the known kinds.
const LEFTOVER_MENTION = /@[a-z][a-z-]*:[^\s]+/gi;
const UUID = /\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b/gi;

function humanize(slug: string): string {
  const words = slug.replace(/[_-]+/g, " ").trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : "";
}

function decodePart(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

function translated(key: string | undefined): string | null {
  if (!key) return null;
  const value = get(translations)(key);
  return value && !value.startsWith("[T:") && value !== key ? value : null;
}

/** The Focus or skill title shown in the app, or its humanized id when the app list is not loaded. */
function appItemName(kind: "focus" | "skill", appId: string, itemId: string): string {
  const app = appSkillsStore.apps?.[appId];
  const items: ReadonlyArray<{ id: string; name_translation_key?: string }> | undefined =
    kind === "focus" ? app?.focus_modes : app?.skills;
  return translated(items?.find((item) => item.id === itemId)?.name_translation_key) || humanize(itemId);
}

/** The Project ids mentioned in a text, in order of appearance. */
export function mentionedProjectIds(value: string | null | undefined): string[] {
  if (!value) return [];
  const ids = [
    ...[...value.matchAll(PROJECT_MENTION)].map((match) => match[1]),
    ...[...value.matchAll(/@project-(?:folder|file):([a-zA-Z0-9_.-]+):/g)].map((match) => match[1]),
  ];
  return [...new Set(ids)];
}

/**
 * Convert backend mention syntax to human-readable display names, and remove
 * any identifier, so previews and titles never show raw mention tokens.
 *
 * - @project:{id}:{access} -> @Project Name (generic @Project while the name is unknown)
 * - @project-folder / @project-file -> @folder or file name
 * - @focus:{app_id}:{focus_id} / @skill:{app_id}:{skill_id} -> @Focus or skill title
 * - @ai-model:{model_id} -> @Model-Name (e.g., @Claude-4.5-Opus)
 * - @best-model:{alias} -> @Alias
 * - @mate:{mate_id} -> @MateName (e.g., @Sophia)
 * - @memory:openmates:memories:{type} -> @Openmates-Memories; @memory-entry -> @Memory
 * - @wikipedia:{lang}:{title} -> @Article title
 * Leftover mention syntax and bare UUIDs are removed.
 */
export function convertMentionSyntaxToDisplayName(
  text: string,
  projectName: ProjectNameLookup | null = projectNameLookup(),
): string {
  text = text.replace(PROJECT_SCOPED_MENTION, (_match, encodedPath: string) => {
    const label = decodePart(encodedPath).split("/").filter(Boolean).pop()?.trim();
    return `@${label || "Project"}`;
  });
  text = text.replace(PROJECT_MENTION, (_match, projectId: string) => `@${projectName?.(projectId)?.trim() || "Project"}`);

  text = text.replace(/@ai-model:([^\s]+)/g, (_match, ref: string) => {
    const baseId = ref.split(":")[0];
    const model =
      modelsMetadata.find((m) => m.id === ref) ??
      modelsMetadata.find((m) => m.id === baseId);
    return `@${model ? toHyphenatedName(model.name) : capitalizeWords(baseId)}`;
  });

  text = text.replace(/@best-model:([^\s:]+)/g, (_match, alias: string) => {
    return `@${capitalizeWords(alias)}`;
  });

  text = text.replace(/@mate:([^\s]+)/g, (match, mateId) => {
    const mate = matesMetadata.find((m) => m.id === mateId);
    return mate ? `@${capitalizeWords(mate.search_names[0] || mate.id)}` : match;
  });

  text = text.replace(/@(focus|skill):([a-zA-Z0-9_.-]+):([a-zA-Z0-9_.-]+)/g,
    (_match, kind: "focus" | "skill", appId: string, itemId: string) => `@${appItemName(kind, appId, itemId)}`);

  text = text.replace(
    /@memory:([^:]+):([^:]+):([^\s]+)/g,
    (match, appId, memoryId) =>
      appId === "openmates" && memoryId === "memories"
        ? "@Openmates-Memories"
        : match,
  );
  text = text.replace(MEMORY_ENTRY_MENTION, "@Memory");
  text = text.replace(WIKIPEDIA_MENTION, (_match, encodedTitle: string) => `@${humanize(decodePart(encodedTitle))}`);

  return text.replace(LEFTOVER_MENTION, " ").replace(UUID, " ").replace(/[ \t]{2,}/g, " ");
}
