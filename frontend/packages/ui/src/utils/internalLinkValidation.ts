// frontend/packages/ui/src/utils/internalLinkValidation.ts
//
// Validates internal markdown links before they are rendered as clickable UI.
// LLM output can hallucinate hash routes such as nonexistent settings pages;
// those degrade to a safe #message prefill link instead of dead navigation.
// Keep this lightweight and free of Svelte component imports so markdown parsing
// can use it without pulling the settings view tree into chat rendering.

import { modelsMetadata } from "../data/modelsMetadata";
import { matesMetadata } from "../data/matesMetadata";
import { providersMetadata } from "../data/providersMetadata";
import { appSkillsStore } from "../stores/appSkillsStore";

const STATIC_SETTINGS_ROUTES = new Set([
  "main",
  "pricing",
  "ai",
  "apps",
  "apps/all",
  "settings_memories",
  "privacy",
  "privacy/hide-personal-data",
  "privacy/hide-personal-data/add-name",
  "privacy/hide-personal-data/add-address",
  "privacy/hide-personal-data/add-birthday",
  "privacy/hide-personal-data/add-custom",
  "privacy/auto-deletion/chats",
  "privacy/auto-deletion/files",
  "privacy/share-debug-logs",
  "mates",
  "billing",
  "billing/buy-credits",
  "billing/buy-credits/payment",
  "billing/buy-credits/confirmation",
  "billing/redeem-giftcard",
  "billing/auto-topup",
  "billing/auto-topup/low-balance",
  "billing/auto-topup/monthly",
  "billing/invoices",
  "billing/referral-code",
  "billing/gift-cards",
  "billing/gift-cards/redeem",
  "billing/gift-cards/redeemed",
  "billing/gift-cards/buy",
  "billing/gift-cards/buy/payment",
  "billing/gift-cards/buy/confirmation",
  "notifications",
  "notifications/chat",
  "notifications/backup",
  "shared",
  "shared/share",
  "shared/tip",
  "fork",
  "interface",
  "interface/language",
  "interface/dark_mode",
  "interface/font",
  "account",
  "account/timezone",
  "account/username",
  "account/email",
  "account/security",
  "account/security/passkeys",
  "account/security/password",
  "account/security/2fa",
  "account/security/recovery-key",
  "account/security/sessions",
  "account/security/sessions/pair-initiate",
  "account/security/sessions/confirm-pair",
  "account/export",
  "account/import",
  "account/chats",
  "account/storage",
  "account/storage/images",
  "account/storage/videos",
  "account/storage/audio",
  "account/storage/pdf",
  "account/storage/code",
  "account/storage/docs",
  "account/storage/sheets",
  "account/storage/archives",
  "account/storage/other",
  "account/profile-picture",
  "account/delete",
  "developers",
  "developers/api-keys",
  "developers/devices",
  "developers/webhooks",
  "newsletter",
  "support",
  "support/one-time",
  "support/monthly",
  "report_issue",
  "report_issue/confirmation",
  "incognito/info",
  "server",
  "server/software-update",
  "server/stats",
  "server/gift-cards",
  "server/tests",
  "logs",
]);

const VALID_ALL_APPS_FILTERS = new Set([
  "all",
  "memories",
  "settings_memories",
  "focus_modes",
  "skills",
]);

const MEMORY_SEGMENT = "memories";
const INTERNAL_MEMORY_SEGMENT = "settings_memories";

type SettingsMemoryCategory = {
  id: string;
  schema?: {
    properties?: Record<string, unknown>;
  };
  schema_definition?: {
    properties?: Record<string, unknown>;
  };
};

type SettingsAppMetadata = {
  settings_and_memories?: SettingsMemoryCategory[];
};

function stripHashPrefix(href: string): string | null {
  if (!href) return null;

  const hashIndex = href.indexOf("#settings");
  if (hashIndex < 0) return null;

  return href.slice(hashIndex + "#settings".length);
}

export function isInternalHashLink(href: string): boolean {
  if (!href) return false;
  const normalizedHref = href.startsWith("/#") ? href.substring(1) : href;
  return (
    normalizedHref.startsWith("#chat-id=") ||
    normalizedHref.startsWith("#message=") ||
    normalizedHref.startsWith("#settings") ||
    normalizedHref.includes("#chat-id=") ||
    normalizedHref.includes("#message=") ||
    normalizedHref.includes("#settings/")
  );
}

export function normalizeSettingsDeepLinkPath(href: string): string | null {
  const settingsPath = stripHashPrefix(href);
  if (settingsPath === null) return null;
  if (settingsPath === "") return "main";
  if (!settingsPath.startsWith("/")) return null;

  const pathWithParams = settingsPath.substring(1);
  const queryIdx = pathWithParams.indexOf("?");
  let path = queryIdx >= 0 ? pathWithParams.substring(0, queryIdx) : pathWithParams;

  if (path === "app_store" || path.startsWith("app_store/")) {
    path = "apps" + path.substring("app_store".length);
  } else if (path === "appstore" || path.startsWith("appstore/")) {
    path = "apps" + path.substring("appstore".length);
  }

  if (path === MEMORY_SEGMENT || path.startsWith(`${MEMORY_SEGMENT}/`)) {
    path = INTERNAL_MEMORY_SEGMENT + path.substring(MEMORY_SEGMENT.length);
  }

  const aiDetailMatch = path.match(/^(ai\/(?:model|provider))\/(.*)/);
  if (aiDetailMatch) {
    path = aiDetailMatch[1].replace(/-/g, "_") + "/" + aiDetailMatch[2];
  } else {
    path = path.replace(/-/g, "_");
  }

  const allAppsFilterMatch = path.match(/^apps\/all\/(.+)$/);
  if (allAppsFilterMatch) {
    const filter = allAppsFilterMatch[1] === MEMORY_SEGMENT
      ? INTERNAL_MEMORY_SEGMENT
      : allAppsFilterMatch[1];
    path = VALID_ALL_APPS_FILTERS.has(filter)
      ? "apps/all"
      : path;
  }

  if (path.startsWith("apps/")) {
    path = path.replace(/\/skills\//, "/skill/");
    path = path.replace(/\/focuses\//, "/focus/");
    path = path.replace(/\/memories\//, "/settings_memories/");
  }

  if (path === "billing/referral_code") {
    path = "billing/referral-code";
  }

  return path;
}

export function isRenderableInternalHref(href: string): boolean {
  if (!isInternalHashLink(href)) return true;
  if (href.includes("#chat-id=")) return true;
  if (href.includes("#message=")) return true;

  const settingsPath = normalizeSettingsDeepLinkPath(href);
  if (settingsPath === null) return false;

  return isExistingSettingsPath(settingsPath) && hasValidPrefillFields(href, settingsPath);
}

export function buildMessagePrefillHref(text: string): string {
  return `#message=${encodeURIComponent(text.trim())}`;
}

export function getRenderableInternalHref(href: string, fallbackText = ""): string | null {
  if (!isInternalHashLink(href)) return href;
  if (href.includes("#chat-id=")) return href.startsWith("/#") ? href.substring(1) : href;
  if (href.includes("#message=")) return href.startsWith("/#") ? href.substring(1) : href;

  const settingsPath = normalizeSettingsDeepLinkPath(href);
  if (settingsPath === null || !isExistingSettingsPath(settingsPath) || !hasValidPrefillFields(href, settingsPath)) {
    return fallbackText.trim() ? buildMessagePrefillHref(fallbackText) : null;
  }

  return buildCanonicalSettingsHref(href, settingsPath);
}

export function isExistingSettingsPath(path: string): boolean {
  if (STATIC_SETTINGS_ROUTES.has(path)) return true;

  if (/^billing\/invoices\/[^/]+\/refund$/.test(path)) return true;
  if (/^newsletter\/(confirm|unsubscribe)\/[^/]+$/.test(path)) return true;
  if (/^email\/block\/.+$/.test(path)) return true;
  if (/^account\/delete\/[^/]+$/.test(path)) return true;
  if (/^privacy\/hide-personal-data\/edit-(name|address|birthday|custom)\/[^/]+$/.test(path)) return true;
  if (/^apps\/reminder\/entry\/[^/]+(\/edit)?$/.test(path)) return true;

  const aiModelMatch = path.match(/^ai\/model\/([^/]+)$/);
  if (aiModelMatch) return modelsMetadata.some((model) => model.id === aiModelMatch[1]);

  const aiProviderMatch = path.match(/^ai\/provider\/([^/]+)$/);
  if (aiProviderMatch) return Boolean(providersMetadata[aiProviderMatch[1]]);

  const mateMatch = path.match(/^mates\/([^/]+)$/);
  if (mateMatch) return matesMetadata.some((mate) => mate.id === mateMatch[1]);

  const appStoreMatch = path.match(/^apps\/([^/]+)(?:\/(.*))?$/);
  if (!appStoreMatch) return false;

  const [, appId, rest = ""] = appStoreMatch;
  const app = appSkillsStore.getState().apps[appId];
  if (!app) return false;
  if (!rest) return true;
  if (appId === "reminder" && rest === "create") return true;

  const parts = rest.split("/");
  if (parts[0] === "skill" && parts[1]) {
    const skill = app.skills?.find((candidate) => candidate.id === parts[1]);
    if (!skill) return false;
    if (parts.length === 2) return true;
    if (parts.length === 4 && parts[2] === "model") {
      return modelsMetadata.some((model) => model.id === parts[3]);
    }
    if (parts.length === 4 && parts[2] === "provider") {
      return Boolean(providersMetadata[parts[3]]);
    }
    return false;
  }

  if (parts[0] === "focus" && parts.length === 2) {
    return Boolean(app.focus_modes?.some((focusMode) => focusMode.id === parts[1]));
  }

  if (parts[0] === "settings_memories" && parts[1]) {
    const category = app.settings_and_memories?.find(
      (candidate) => candidate.id === parts[1],
    );
    if (!category) return false;
    if (parts.length === 2) return true;
    if (parts.length === 3 && parts[2] === "create") return true;
    if (parts.length === 4 && parts[2] === "entry") return true;
    if (parts.length === 5 && parts[2] === "entry" && parts[4] === "edit") return true;
  }

  return false;
}

function buildCanonicalSettingsHref(href: string, path: string): string {
  const hashIndex = href.indexOf("#settings");
  const rawAfterSettings = hashIndex >= 0 ? href.slice(hashIndex + "#settings".length) : "";
  const queryIdx = rawAfterSettings.indexOf("?");
  const queryString = queryIdx >= 0 ? rawAfterSettings.substring(queryIdx + 1) : "";
  const userPath = buildPublicSettingsPath(rawAfterSettings, path);
  const encodedPrefill = extractEncodedPrefill(queryString);
  return encodedPrefill
    ? `#settings/${userPath}?prefill=${encodedPrefill}`
    : `#settings/${userPath}`;
}

function buildPublicSettingsPath(rawAfterSettings: string, path: string): string {
  const rawPath = rawAfterSettings.split("?", 1)[0].replace(/^\/+/, "").replace(/-/g, "_");
  const allAppsFilterMatch = rawPath.match(/^apps\/all\/(.+)$/);
  if (path === "apps/all" && allAppsFilterMatch) {
    const filter = allAppsFilterMatch[1] === INTERNAL_MEMORY_SEGMENT
      ? MEMORY_SEGMENT
      : allAppsFilterMatch[1];
    return `apps/all/${filter}`;
  }

  return path.replace(/(^|\/)settings_memories(?=\/|$)/g, `$1${MEMORY_SEGMENT}`);
}

function hasValidPrefillFields(href: string, path: string): boolean {
  const prefill = parsePrefill(href);
  if (prefill === null) return !hasPrefillParameter(href);

  const route = parseSettingsMemoryRoute(path);
  if (!route) return false;

  const category = route.app.settings_and_memories?.find(
    (candidate) => candidate.id === route.categoryId,
  );
  const schemaProperties = category?.schema?.properties ?? category?.schema_definition?.properties;
  if (!schemaProperties || typeof schemaProperties !== "object") return true;

  return Object.keys(prefill).every((key) => Object.prototype.hasOwnProperty.call(schemaProperties, key));
}

function hasPrefillParameter(href: string): boolean {
  const hashIndex = href.indexOf("#settings");
  if (hashIndex < 0) return false;
  const queryIdx = href.indexOf("?", hashIndex);
  if (queryIdx < 0) return false;
  return href.substring(queryIdx + 1).includes("prefill=");
}

function parseSettingsMemoryRoute(path: string): { app: SettingsAppMetadata; categoryId: string } | null {
  const match = path.match(/^apps\/([^/]+)\/settings_memories\/([^/]+)\/(?:create|entry\/[^/]+\/edit)$/);
  if (!match) return null;
  const app = appSkillsStore.getState().apps[match[1]];
  if (!app) return null;
  return { app, categoryId: match[2] };
}

function parsePrefill(href: string): Record<string, unknown> | null {
  const hashIndex = href.indexOf("#settings");
  if (hashIndex < 0) return null;
  const queryIdx = href.indexOf("?", hashIndex);
  if (queryIdx < 0) return null;
  const encoded = extractEncodedPrefill(href.substring(queryIdx + 1));
  if (!encoded) return null;
  try {
    const parsed = JSON.parse(decodeURIComponent(encoded));
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

function extractEncodedPrefill(queryString: string): string | null {
  const prefillPrefix = "prefill=";
  const prefillIdx = queryString.indexOf(prefillPrefix);
  if (prefillIdx < 0) return null;
  const raw = queryString.substring(prefillIdx + prefillPrefix.length).split("&", 1)[0];
  if (!raw) return null;
  try {
    const decoded = decodeURIComponent(raw).replace(/[“”]/g, '"').replace(/[‘’]/g, "'");
    const parsed = JSON.parse(decoded);
    return encodeURIComponent(JSON.stringify(parsed));
  } catch {
    return null;
  }
}
