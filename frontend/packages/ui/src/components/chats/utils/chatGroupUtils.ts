import { get } from "svelte/store";
import { locale as svelteLocaleStore } from "svelte-i18n";

/**
 * Provides a localized title for a given group key.
 *
 * @param groupKey The key identifying the chat group (e.g., "today", "month_2025_5").
 * @param t The svelte-i18n translation function (`$_`).
 * @returns A localized string for the group title.
 */
export function getLocalizedGroupTitle(
  groupKey: string,
  t: (key: string, options?: Record<string, unknown>) => string,
): string {
  if (groupKey === "incognito") return t("activity.incognito");
  if (groupKey === "intro") return t("activity.intro");
  if (groupKey === "examples") return t("activity.examples");
  if (groupKey === "announcements") return t("activity.announcements");
  if (groupKey === "tips_and_tricks") return t("activity.tips_and_tricks");
  if (groupKey === "legal") return t("activity.legal");
  if (groupKey === "shared_by_others") return t("activity.shared_by_others");
  if (groupKey === "today") return t("activity.today");
  if (groupKey === "yesterday") return t("activity.yesterday");
  if (groupKey === "previous_7_days") return t("activity.previous_7_days");
  if (groupKey === "previous_30_days") return t("activity.previous_30_days");

  if (groupKey.startsWith("month_")) {
    const parts = groupKey.split("_");
    if (parts.length === 3) {
      const year = parseInt(parts[1], 10);
      const month = parseInt(parts[2], 10);
      if (!isNaN(year) && !isNaN(month)) {
        const date = new Date(year, month - 1);
        // Use current locale from svelte-i18n store for formatting
        const currentLocale = get(svelteLocaleStore);
        return date.toLocaleString(currentLocale || undefined, {
          month: "long",
          year: "numeric",
        });
      }
    }
  }
  // Fallback for unknown group keys or malformed month keys
  return groupKey;
}
