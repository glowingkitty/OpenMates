/**
 * Utility functions for chat categories and gradient colors
 */

import * as LucideIcons from "@lucide/svelte";

export const IMPORTED_ASSISTANT_PROVIDERS: Record<
  string,
  { displayName: string; iconName: string }
> = {
  openmates: { displayName: "OpenMates", iconName: "openmates" },
  chatgpt: { displayName: "ChatGPT", iconName: "openai" },
  claude: { displayName: "Claude", iconName: "claude" },
  gemini: { displayName: "Gemini", iconName: "google" },
  opencode: { displayName: "OpenCode", iconName: "coding" },
  other: { displayName: "AI assistant", iconName: "ai" },
};

export function getImportedAssistantProvider(
  category: string | undefined,
): { displayName: string; iconName: string } | null {
  return category ? IMPORTED_ASSISTANT_PROVIDERS[category] ?? null : null;
}

/**
 * Category gradient colors configuration
 */
export { CATEGORY_GRADIENTS, CATEGORY_FALLBACK_ICONS } from "../../../chatCategoryTheme";
import { CATEGORY_GRADIENTS, CATEGORY_FALLBACK_ICONS } from "../../../chatCategoryTheme";

/**
 * Get gradient colors for a category
 */
export function getCategoryGradientColors(
  category: string,
): { start: string; end: string } | null {
  return CATEGORY_GRADIENTS[category] || null;
}

/**
 * Get fallback icon for a category
 */
export function getFallbackIconForCategory(category: string): string {
  return CATEGORY_FALLBACK_ICONS[category] || "help-circle";
}

/**
 * Check if a string is a valid Lucide icon name
 */
export function isValidLucideIcon(iconName: string): boolean {
  if (!iconName) return false;

  // Convert kebab-case to PascalCase (e.g., 'help-circle' -> 'HelpCircle')
  const pascalCaseName = iconName
    .split("-")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join("");

  return pascalCaseName in LucideIcons;
}

/**
 * Get a valid icon name with robust fallback system
 */
export function getValidIconName(
  providedIconNames: string | string[],
  category: string,
): string {
  const iconNames = Array.isArray(providedIconNames)
    ? providedIconNames
    : [providedIconNames];

  // Try each provided icon name in order
  for (const iconName of iconNames) {
    if (isValidLucideIcon(iconName)) {
      return iconName;
    }
  }

  // If no valid icons provided, use category-specific fallback
  const categoryFallback = getFallbackIconForCategory(category);
  if (isValidLucideIcon(categoryFallback)) {
    return categoryFallback;
  }

  // Final safety net
  return "help-circle";
}

/**
 * Get the Lucide icon component by name
 * Returns a Svelte component type
 */
export function getLucideIcon(iconName: string): typeof LucideIcons.HelpCircle {
  if (!iconName) return LucideIcons.HelpCircle;

  // Convert kebab-case to PascalCase (e.g., 'help-circle' -> 'HelpCircle')
  const pascalCaseName = iconName
    .split("-")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join("");

  // Dynamic access to LucideIcons (property names are determined at runtime)
  // Type assertion needed because property access is dynamic
  const icon = (
    LucideIcons as unknown as Record<string, typeof LucideIcons.HelpCircle>
  )[pascalCaseName];
  return icon || LucideIcons.HelpCircle;
}
