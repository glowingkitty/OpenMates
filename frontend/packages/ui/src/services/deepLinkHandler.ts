/**
 * Unified Deep Link Handler
 *
 * Centralizes all deep link processing to avoid collisions and ensure consistent behavior.
 * Handles all URL hash-based deep links:
 * - #chat-id={id} / #chat-id={id} - Chat deep links
 * - #settings/{path} - Settings deep links (including newsletter, email block, refunds)
 * - #signup/{step} - Signup flow deep links
 * - #embed-id={id} / #embed_id={id} - Embed deep links
 */

import { replaceState } from "$app/navigation";
import { createEntryPrefillStore } from "../stores/createEntryPrefillStore";
import { updateEntryPrefillStore } from "../stores/updateEntryPrefillStore";

export type DeepLinkType =
  | "chat"
  | "settings"
  | "signup"
  | "embed"
  | "pair"
  | "unknown";

export interface DeepLinkResult {
  type: DeepLinkType;
  processed: boolean;
  requiresAuth?: boolean;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  data?: any;
}

export interface DeepLinkHandlers {
  onChat?: (
    chatId: string,
    messageId?: string | null,
    scrollToLatestResponse?: boolean,
    embedId?: string | null,
  ) => Promise<void>;
  onSettings?: (path: string, hash: string) => void;
  onSignup?: (step: string) => void;
  onEmbed?: (embedId: string) => Promise<void>;
  /** Handler for /#pair=TOKEN deep links — opens the confirm-pair settings page */
  onPair?: (token: string) => void;
  onNoHash?: () => Promise<void>; // Handler for when no hash is present
  requiresAuthentication?: (settingsPath: string) => boolean;
  isAuthenticated?: () => boolean;
  openSettings?: () => void;
  openLogin?: () => void;
  setSettingsDeepLink?: (path: string) => void;
}

/**
 * Parse a hash string to extract deep link information
 */
export function parseDeepLink(
  hash: string,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
): { type: DeepLinkType; data: any } | null {
  if (!hash || !hash.startsWith("#")) {
    return null;
  }

  // Chat deep links: #chat-id={id} or #chat-id={id} or #chatid={id}
  // Also support / prefix (e.g. /#chatid=...)
  // Optional params: &message-id={id}  &scroll=latest-response  &embed-id={id}
  const normalizedHash = hash.startsWith("#/") ? "#" + hash.substring(2) : hash;

  // Combined chat+embed format: #chat-id={chatId}&embed-id={embedId}
  // Must be checked before the generic chat-only regex so the embed-id param is captured.
  const combinedMatch = normalizedHash.match(
    /^#chat[-_]?id=([^&]+)&embed[-_]?id=([^&]+)((?:&[^=]+=[^&]*)*)$/,
  );
  if (combinedMatch) {
    const chatId = combinedMatch[1];
    const embedId = combinedMatch[2];
    const extraParams = combinedMatch[3] || "";
    const messageIdMatch = extraParams.match(/&message[-_]?id=([^&]+)/);
    const messageId = messageIdMatch ? messageIdMatch[1] : null;
    const scrollMatch = extraParams.match(/&scroll=([^&]+)/);
    const scrollToLatestResponse = scrollMatch
      ? scrollMatch[1] === "latest-response"
      : false;
    return {
      type: "chat",
      data: {
        chatId,
        messageId,
        scrollToLatestResponse,
        embedId,
      },
    };
  }

  const chatMatch = normalizedHash.match(
    /^#chat[-_]?id=([^&]+)((?:&[^=]+=.[^&]*)*)$/,
  );
  if (chatMatch) {
    const chatId = chatMatch[1];
    const extraParams = chatMatch[2] || "";
    // Extract optional message-id param
    const messageIdMatch = extraParams.match(/&message[-_]?id=([^&]+)/);
    const messageId = messageIdMatch ? messageIdMatch[1] : null;
    // Extract optional scroll param — 'latest-response' means scroll to top of newest assistant message
    const scrollMatch = extraParams.match(/&scroll=([^&]+)/);
    const scrollToLatestResponse = scrollMatch
      ? scrollMatch[1] === "latest-response"
      : false;
    return {
      type: "chat",
      data: {
        chatId,
        messageId,
        scrollToLatestResponse,
        embedId: null,
      },
    };
  }

  // Settings deep links: #settings/{path}
  if (normalizedHash.startsWith("#settings")) {
    const settingsPath = normalizedHash.substring("#settings".length);
    return {
      type: "settings",
      data: { path: settingsPath, fullHash: normalizedHash },
    };
  }

  // Signup deep links: #signup/{step}
  if (hash.startsWith("#signup/")) {
    const step = hash.substring("#signup/".length);
    return {
      type: "signup",
      data: { step },
    };
  }

  // Embed deep links: #embed-id={id} or #embed_id={id}
  const embedMatch = hash.match(/^#embed[-_]id=(.+)$/);
  if (embedMatch) {
    const embedId = embedMatch[1].split("&")[0].split("?")[0]; // Remove query params
    return {
      type: "embed",
      data: { embedId },
    };
  }

  // Pair login deep links: #pair=TOKEN (6-char unambiguous alphabet, case-insensitive)
  // Format: /#pair=A3FX9K (cosmetic display: A3F-X9K, but URL uses no dash)
  const pairMatch = normalizedHash.match(/^#pair=([A-Za-z0-9]{6})$/i);
  if (pairMatch) {
    return {
      type: "pair",
      data: { token: pairMatch[1].toUpperCase() },
    };
  }

  return { type: "unknown", data: null };
}

/**
 * Process a deep link with the provided handlers
 */
export async function processDeepLink(
  hash: string,
  handlers: DeepLinkHandlers,
): Promise<DeepLinkResult> {
  // Handle empty/no hash case
  if (!hash || hash === "#") {
    if (handlers.onNoHash) {
      await handlers.onNoHash();
      return { type: "unknown", processed: true }; // Successfully processed "no hash" case
    }
    return { type: "unknown", processed: false };
  }

  const parsed = parseDeepLink(hash);

  if (!parsed) {
    // Still try onNoHash if hash exists but is unknown format
    if (handlers.onNoHash) {
      await handlers.onNoHash();
      return { type: "unknown", processed: true };
    }
    return { type: "unknown", processed: false };
  }

  switch (parsed.type) {
    case "chat":
      if (handlers.onChat) {
        await handlers.onChat(
          parsed.data.chatId,
          parsed.data.messageId,
          parsed.data.scrollToLatestResponse,
          parsed.data.embedId ?? null,
        );
        return { type: "chat", processed: true };
      }
      break;

    case "settings":
      if (handlers.onSettings) {
        const settingsPath = parsed.data.path;

        // Check if authentication is required
        if (handlers.requiresAuthentication && handlers.isAuthenticated) {
          const needsAuth = handlers.requiresAuthentication(settingsPath);
          if (needsAuth && !handlers.isAuthenticated()) {
            // Store for processing after login
            if (typeof window !== "undefined") {
              sessionStorage.setItem("pendingDeepLink", hash);
            }
            if (handlers.openLogin) {
              handlers.openLogin();
            }
            // Clear hash to keep URL clean
            if (typeof window !== "undefined") {
              replaceState(
                window.location.pathname + window.location.search,
                {},
              );
            }
            return { type: "settings", processed: false, requiresAuth: true };
          }
        }

        // Process settings deep link
        handlers.onSettings(settingsPath, parsed.data.fullHash);
        return { type: "settings", processed: true, requiresAuth: false };
      }
      break;

    case "signup":
      if (handlers.onSignup) {
        handlers.onSignup(parsed.data.step);
        return { type: "signup", processed: true };
      }
      break;

    case "embed":
      if (handlers.onEmbed) {
        await handlers.onEmbed(parsed.data.embedId);
        return { type: "embed", processed: true };
      }
      break;

    case "pair": {
      // Pair login deep link: navigate to Settings > Account > Security > Sessions > Confirm Device.
      // If user is not authenticated, store the pending token and open login first.
      if (handlers.onPair) {
        if (handlers.isAuthenticated && !handlers.isAuthenticated()) {
          // Store the pending deep link and open login
          if (typeof window !== "undefined") {
            sessionStorage.setItem("pendingDeepLink", hash);
          }
          if (handlers.openLogin) {
            handlers.openLogin();
          }
          // IMPORTANT: Keep #pair=TOKEN in URL for cross-browser handoff.
          // iOS in-app Safari often opens an isolated session without login state;
          // users can tap "Open in Safari" to continue in their logged-in browser.
          // If we clear the hash here, that handoff loses the token and pairing fails.
          return { type: "pair", processed: false, requiresAuth: true };
        }
        handlers.onPair(parsed.data.token);
        // Clear hash after processing
        if (typeof window !== "undefined") {
          replaceState(window.location.pathname + window.location.search, {});
        }
        return { type: "pair", processed: true };
      }
      break;
    }
  }

  return { type: parsed.type, processed: false };
}

/**
 * Process settings deep link with specific logic for different settings paths
 * Similar to the original processSettingsDeepLink function
 */

/**
 * Extract prefill JSON from a query string and store it in the appropriate prefill store.
 *
 * Handles the JSON embedded in settings/memories deep links generated by the AI.
 * Designed for maximum resilience: if any field is invalid, skip it silently.
 * If the entire JSON fails to parse, the link still works — just without prefill.
 *
 * @param queryString - Raw query string (without leading '?')
 * @param path - The normalized settings path (used to determine create vs edit)
 */
function _extractAndStorePrefill(queryString: string, path: string): void {
  try {
    // Extract prefill= value from query string
    // Use manual extraction since the JSON may contain = and & characters
    const prefillPrefix = "prefill=";
    const prefillIdx = queryString.indexOf(prefillPrefix);
    if (prefillIdx < 0) return;

    // Everything after "prefill=" is the JSON (it's always the last/only param)
    let rawJson = queryString.substring(prefillIdx + prefillPrefix.length);

    // URL-decode the value (handles %20, %28, %29, etc.)
    try {
      rawJson = decodeURIComponent(rawJson);
    } catch {
      // If decoding fails, try the raw string — it might work
    }

    // Attempt to parse the JSON
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let parsed: Record<string, any>;
    try {
      parsed = JSON.parse(rawJson);
    } catch {
      // LLM may produce slightly malformed JSON — try common fixes
      try {
        // Remove trailing comma before closing brace (common LLM mistake)
        const fixed = rawJson.replace(/,\s*}/g, "}").replace(/,\s*]/g, "]");
        parsed = JSON.parse(fixed);
      } catch {
        console.warn(
          "[DeepLink] Failed to parse prefill JSON, link will work without prefill:",
          rawJson.substring(0, 100),
        );
        return;
      }
    }

    if (
      typeof parsed !== "object" ||
      parsed === null ||
      Array.isArray(parsed)
    ) {
      console.warn("[DeepLink] Prefill JSON is not an object, ignoring");
      return;
    }

    // Validate each field: only keep string, number, boolean values
    // Skip anything else (nested objects, arrays, null, undefined)
    const validatedPrefill: Record<string, string | number | boolean> = {};
    for (const [key, value] of Object.entries(parsed)) {
      if (
        typeof value === "string" ||
        typeof value === "number" ||
        typeof value === "boolean"
      ) {
        validatedPrefill[key] = value;
      } else {
        console.warn(
          `[DeepLink] Skipping prefill field "${key}" — unsupported type: ${typeof value}`,
        );
      }
    }

    if (Object.keys(validatedPrefill).length === 0) {
      return; // No valid fields to prefill
    }

    // Determine if this is a create or edit link based on path pattern
    // Create: app_store/{appId}/settings_memories/{categoryId}/create
    // Edit: app_store/{appId}/settings_memories/{categoryId}/entry/{entryId}/edit
    const parts = path.split("/");
    const isCreate = parts.includes("create");
    const isEdit = parts.includes("edit") && parts.includes("entry");

    if (isCreate) {
      // Extract app_id and category_id from path
      // Pattern: app_store/{appId}/settings_memories/{categoryId}/create
      const appIdIdx = 1; // parts[0] = app_store, parts[1] = appId
      const categoryIdx = 3; // parts[2] = settings_memories, parts[3] = categoryId
      if (parts.length >= 5 && parts[appIdIdx] && parts[categoryIdx]) {
        createEntryPrefillStore.set({
          app_id: parts[appIdIdx],
          item_type: parts[categoryIdx],
          suggested_title:
            (validatedPrefill.name as string) ||
            (validatedPrefill.title as string) ||
            "",
          item_value: validatedPrefill,
        });
        console.warn(
          `[DeepLink] Stored create prefill for ${parts[appIdIdx]}/${parts[categoryIdx]}:`,
          Object.keys(validatedPrefill),
        );
      }
    } else if (isEdit) {
      // Extract entry_id from path
      // Pattern: app_store/{appId}/settings_memories/{categoryId}/entry/{entryId}/edit
      const entryIdIdx = parts.indexOf("entry") + 1;
      if (entryIdIdx > 0 && entryIdIdx < parts.length) {
        updateEntryPrefillStore.set({
          entryId: parts[entryIdIdx],
          prefillFields: validatedPrefill,
        });
        console.warn(
          `[DeepLink] Stored update prefill for entry ${parts[entryIdIdx]}:`,
          Object.keys(validatedPrefill),
        );
      }
    }
  } catch (error) {
    // Non-fatal: the link still works, just without prefill
    console.warn("[DeepLink] Error extracting prefill from deep link:", error);
  }
}

export function processSettingsDeepLink(
  hash: string,
  handlers: {
    openSettings: () => void;
    setSettingsDeepLink: (path: string) => void;
  },
): void {
  const settingsPath = hash.substring("#settings".length);

  handlers.openSettings();

  // Check for special deep links that need to keep hash in URL (like refund, newsletter confirm, etc.)
  const refundMatch = settingsPath.match(
    /^\/billing\/invoices\/[^/]+\/refund$/,
  );
  const newsletterConfirmMatch = settingsPath.match(
    /^\/newsletter\/confirm\/(.+)$/,
  );
  const newsletterUnsubscribeMatch = settingsPath.match(
    /^\/newsletter\/unsubscribe\/(.+)$/,
  );
  const emailBlockMatch = settingsPath.match(/^\/email\/block\/(.+)$/);
  const accountDeleteMatch = settingsPath.match(/^\/account\/delete\/[^/]+$/);

  if (
    refundMatch ||
    newsletterConfirmMatch ||
    newsletterUnsubscribeMatch ||
    emailBlockMatch ||
    accountDeleteMatch
  ) {
    // These deep links keep the hash for component processing
    // Navigate to the base settings page
    if (refundMatch) {
      handlers.setSettingsDeepLink("billing/invoices");
    } else if (
      newsletterConfirmMatch ||
      newsletterUnsubscribeMatch ||
      emailBlockMatch
    ) {
      handlers.setSettingsDeepLink("newsletter");
    } else if (accountDeleteMatch) {
      // Extract the path from the hash to include the ID
      // This ensures Settings.svelte can extract the activeAccountId
      const path = hash.startsWith("#settings/")
        ? hash.substring("#settings/".length)
        : "account/delete";
      handlers.setSettingsDeepLink(path);
    }
    // Don't clear hash - component will process it
    return;
  }

  // Regular settings paths
  if (settingsPath.startsWith("/")) {
    const pathWithParams = settingsPath.substring(1); // Remove leading slash
    // Extract prefill parameter before stripping query params (used for settings/memories deep links)
    const queryIdx = pathWithParams.indexOf("?");
    const queryString =
      queryIdx >= 0 ? pathWithParams.substring(queryIdx + 1) : "";
    let path =
      queryIdx >= 0 ? pathWithParams.substring(0, queryIdx) : pathWithParams;

    // Parse prefill JSON from query string if present
    // The AI generates links like: /#settings/.../create?prefill={"name":"Python"}
    // We extract the JSON, parse it leniently, and store in the appropriate prefill store.
    if (queryString) {
      _extractAndStorePrefill(queryString, path);
    }

    // Map common aliases - handle 'appstore' prefix (with or without subpath)
    // e.g., 'appstore' -> 'app_store', 'appstore/web' -> 'app_store/web'
    if (path === "appstore" || path.startsWith("appstore/")) {
      path = "app_store" + path.substring("appstore".length);
    }
    // Normalize hyphens to underscores for consistency (e.g., report-issue -> report_issue)
    path = path.replace(/-/g, "_");

    // Normalize app store sub-routes from plural to singular form
    // Deep links may use plural forms (e.g., 'skills', 'focuses') but routes use singular ('skill', 'focus')
    // Pattern: app_store/{appId}/skills/{skillId} -> app_store/{appId}/skill/{skillId}
    // Pattern: app_store/{appId}/focuses/{focusModeId} -> app_store/{appId}/focus/{focusModeId}
    if (path.startsWith("app_store/")) {
      path = path.replace(/\/skills\//, "/skill/");
      path = path.replace(/\/focuses\//, "/focus/");
    }

    handlers.setSettingsDeepLink(path);

    // Clear the hash after processing
    if (typeof window !== "undefined") {
      replaceState(window.location.pathname + window.location.search, {});
    }
  } else if (settingsPath === "") {
    handlers.setSettingsDeepLink("main");

    // Clear the hash after processing
    if (typeof window !== "undefined") {
      replaceState(window.location.pathname + window.location.search, {});
    }
  } else {
    console.warn(`[deepLinkHandler] Invalid settings deep link hash: ${hash}`);
    handlers.setSettingsDeepLink("main");

    // Clear the hash after processing
    if (typeof window !== "undefined") {
      replaceState(window.location.pathname + window.location.search, {});
    }
  }
}
