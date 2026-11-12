/**
 * Shared display formatting for backend mention syntax (@ai-model:..., @mate:...).
 * Used by draft saving and draft/title previews so all surfaces show the same names.
 */
import { modelsMetadata } from "../data/modelsMetadata";
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

/**
 * Convert backend mention syntax to human-readable display names.
 * This ensures draft previews show "@Claude-4.5-Opus" instead of "@ai-model:claude-4-sonnet"
 *
 * Supported mention formats:
 * - @ai-model:{model_id} -> @Model-Name (e.g., @Claude-4.5-Opus)
 * - @mate:{mate_id} -> @MateName (e.g., @Sophia)
 * - @skill:{app_id}:{skill_id} -> @App-Skill-Name (e.g., @Code-Get-Docs)
 * - @focus:{app_id}:{focus_id} -> @App-Focus-Name (e.g., @Web-Research)
 * - @memory:{app_id}:{memory_id}:{type} -> @App-Memory-Name (e.g., @Code-Projects)
 */
export function convertMentionSyntaxToDisplayName(text: string): string {
  // @ai-model:{id} or @ai-model:{id}:{provider} -> @Model-Name
  text = text.replace(/@ai-model:([^\s]+)/g, (_match, ref: string) => {
    const baseId = ref.split(":")[0];
    const model =
      modelsMetadata.find((m) => m.id === ref) ??
      modelsMetadata.find((m) => m.id === baseId);
    return `@${model ? toHyphenatedName(model.name) : capitalizeWords(baseId)}`;
  });

  // @best-model:{alias} (best, fast) -> @Best / @Fast
  text = text.replace(/@best-model:([^\s:]+)/g, (_match, alias: string) => {
    return `@${capitalizeWords(alias)}`;
  });

  // Replace @mate:{id} with @MateName
  text = text.replace(/@mate:([^\s]+)/g, (match, mateId) => {
    const mate = matesMetadata.find((m) => m.id === mateId);
    if (mate) {
      // Use first search name (the actual name like "Sophia")
      const displayName = capitalizeWords(mate.search_names[0] || mate.id);
      return `@${displayName}`;
    }
    return match; // Keep original if mate not found
  });

  // Replace @skill:{app_id}:{skill_id} with @App-Skill-Name
  text = text.replace(/@skill:([^:]+):([^\s]+)/g, (match, appId, skillId) => {
    const apps = appSkillsStore.apps;
    const app = apps[appId];
    if (app) {
      const skill = app.skills.find((s) => s.id === skillId);
      if (skill) {
        const appDisplayName = capitalizeWords(appId);
        const skillDisplayName = capitalizeWords(skillId.replace(/_/g, "-"));
        return `@${appDisplayName}-${skillDisplayName}`;
      }
    }
    return match; // Keep original if not found
  });

  // Replace @focus:{app_id}:{focus_id} with @App-Focus-Name
  text = text.replace(/@focus:([^:]+):([^\s]+)/g, (match, appId, focusId) => {
    const apps = appSkillsStore.apps;
    const app = apps[appId];
    if (app) {
      const focusMode = app.focus_modes.find((f) => f.id === focusId);
      if (focusMode) {
        const appDisplayName = capitalizeWords(appId);
        const focusDisplayName = capitalizeWords(focusId.replace(/_/g, "-"));
        return `@${appDisplayName}-${focusDisplayName}`;
      }
    }
    return match; // Keep original if not found
  });

  // Replace @memory:{app_id}:{memory_id}:{type} with @App-Memory-Name
  text = text.replace(
    /@memory:([^:]+):([^:]+):([^\s]+)/g,
    (match, appId, memoryId) =>
      appId === "openmates" && memoryId === "memories"
        ? "@Openmates-Memories"
        : match,
  );

  return text;
}

