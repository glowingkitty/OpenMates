// frontend/packages/ui/src/demo_chats/resolveI18nServer.ts
//
// Server-only module for resolving example chat i18n keys to English text.
// Imports the full English locale JSON — only import this from +page.server.ts
// files (SSR), never from client-side code (it would bloat the bundle by ~400KB).

import enLocale from "../i18n/locales/en.json";

/**
 * Resolve an i18n key to English text for server-side SEO rendering.
 * Traverses the nested locale JSON using dot-separated key paths.
 *
 * @param key - i18n key (e.g. "example_chats.gigantic_airplanes.title")
 * @returns English text, or the key itself if not found
 */
export function resolveExampleChatI18nKey(key: string): string {
  if (!key.startsWith("example_chats.")) return key;
  return resolveI18nKey(key);
}

/** Resolve any i18n key (demo_chats.*, example_chats.*, etc.) to English text. */
export function resolveI18nKey(key: string): string {
  const parts = key.split(".");
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let current: any = enLocale;
  for (const part of parts) {
    if (current == null || typeof current !== "object") return key;
    current = current[part];
  }

  if (current && typeof current === "object" && "text" in current) {
    return current.text;
  }
  if (typeof current === "string") return current;
  return key;
}
