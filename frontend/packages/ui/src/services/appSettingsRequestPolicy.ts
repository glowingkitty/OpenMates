/**
 * Pure decisions of the app settings/memories permission request handler
 * (chatSyncServiceHandlersAppSettings.ts), extracted unchanged so the flag-off
 * build keeps this TypeScript behaviour and the flag-on build asks the shared
 * Rust `settings` unit instead (web_settings.rs). The TS-generated vectors in
 * packages/openmates-rust/src/web_settings_ts_vectors.json pin both sides.
 *
 * No imports: the module must stay dependency-free so the vector generator can
 * load it directly.
 */

export interface RequestCategory {
  key: string;
  appId: string;
  itemType: string;
  displayName: string;
  entryCount: number;
  iconGradient: string;
  selected: boolean;
}

/** "preferred_technologies" -> "Preferred technologies" */
export function formatDisplayName(itemType: string): string {
  return itemType
    .split("_")
    .map((word, index) =>
      index === 0 ? word.charAt(0).toUpperCase() + word.slice(1) : word,
    )
    .join(" ");
}

const DEFAULT_GRADIENT = "linear-gradient(135deg, #4A90D9 9.04%, #7B68EE 90.06%)";

/** CSS gradient for an app ID from theme variables. */
export function getAppGradient(appId: string): string {
  const gradientMap: Record<string, string> = {
    code: "linear-gradient(135deg, #4A90D9 9.04%, #7B68EE 90.06%)",
    travel: "linear-gradient(135deg, #059DB3 9.04%, #13DAF5 90.06%)",
    finance: "linear-gradient(135deg, #119106 9.04%, #15780D 90.06%)",
    health: "linear-gradient(135deg, #FD50A0 9.04%, #F42C2D 90.06%)",
    news: "linear-gradient(135deg, #F53F5B 9.04%, #DD0B2B 90.06%)",
    weather: "linear-gradient(135deg, #005BA5 9.04%, #00A7C9 90.06%)",
    jobs: "linear-gradient(135deg, #049363 9.04%, #00C382 90.06%)",
    legal: "linear-gradient(135deg, #239CFF 9.04%, #005BA5 90.06%)",
    files: "linear-gradient(135deg, #1E3A8A 9.04%, #29BEFB 90.06%)",
    ai: "linear-gradient(135deg, #CB7D5D 9.04%, #CB685D 90.06%)",
    tv: "linear-gradient(135deg, #8B5CF6 9.04%, #6D28D9 90.06%)",
    videos: "linear-gradient(135deg, #EF4444 9.04%, #DC2626 90.06%)",
    maps: "linear-gradient(135deg, #10B981 9.04%, #059669 90.06%)",
    study: "linear-gradient(135deg, #F59E0B 9.04%, #D97706 90.06%)",
    plants: "linear-gradient(135deg, #22C55E 9.04%, #16A34A 90.06%)",
  };
  // Own keys only: ids such as "constructor" must not resolve to Object.prototype members.
  return Object.prototype.hasOwnProperty.call(gradientMap, appId) ? gradientMap[appId] : DEFAULT_GRADIENT;
}

/**
 * Categories (and their valid keys) of a server request: malformed keys and
 * keys without stored entries are skipped. `entryCounts` maps key -> count.
 */
export function planRequestCategories(
  requestedKeys: string[],
  entryCounts: ReadonlyMap<string, number>,
): { categories: RequestCategory[]; validKeys: string[] } {
  const categories: RequestCategory[] = [];
  const validKeys: string[] = [];
  for (const key of requestedKeys) {
    const dashIndex = key.indexOf("-");
    if (dashIndex === -1) continue;
    const appId = key.substring(0, dashIndex);
    const itemType = key.substring(dashIndex + 1);
    if (!appId || !itemType) continue;
    const entryCount = entryCounts.get(key) || 0;
    if (entryCount === 0) continue;
    validKeys.push(key);
    categories.push({
      key,
      appId,
      itemType,
      displayName: formatDisplayName(itemType),
      entryCount,
      iconGradient: getAppGradient(appId),
      selected: true,
    });
  }
  return { categories, validKeys };
}

/** True when a system message already answers the request of `userMessageId`. */
export function isRequestAnswered(systemContents: string[], userMessageId: string): boolean {
  return systemContents.some((content) => {
    if (!content) return false;
    try {
      const parsed = JSON.parse(content);
      return (
        parsed.type === "app_settings_memories_response" &&
        parsed.user_message_id === userMessageId
      );
    } catch {
      return false;
    }
  });
}
