// Theme store — manages light/dark mode state and persistence.
//
// Three-mode system:
//   'auto'  — follow OS prefers-color-scheme (no manual override; default)
//   'light' — always light (manual override, persisted to localStorage + server)
//   'dark'  — always dark  (manual override, persisted to localStorage + server)
//
// Persistence layers:
//   - localStorage 'theme_mode'   : 'auto' | 'light' | 'dark'
//   - localStorage 'theme'        : 'light' | 'dark'  (actual resolved value)
//   - Backend /v1/settings/user/darkmode : boolean (only when authenticated)
//
// Unauthenticated users: modes work via localStorage only.
// Authenticated users: manual Light/Dark choices are also synced to the backend.
//   'Auto' is a client-only concept — the backend boolean tracks the last explicit choice.

import { writable } from "svelte/store";
import { browser } from "$app/environment";

// ─── Stores ───────────────────────────────────────────────────────────────────

/** Resolved theme: the actual data-theme value applied to <html>. */
export const theme = writable<"light" | "dark">("light");

/** The user's chosen mode: auto / light / dark. */
export const themeMode = writable<"auto" | "light" | "dark">("auto");

// ─── Helpers ──────────────────────────────────────────────────────────────────

/** Returns the OS-preferred theme ('light' or 'dark'). */
function getSystemThemePreference(): "light" | "dark" {
  if (browser) {
    return window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light";
  }
  return "light";
}

// OS-change listener reference so we can remove it when switching to manual mode.
let systemThemeListener: ((e: MediaQueryListEvent) => void) | null = null;

function attachSystemListener() {
  if (!browser) return;
  // Remove any existing listener first to avoid duplicates.
  detachSystemListener();
  systemThemeListener = (e: MediaQueryListEvent) => {
    // Only apply the OS change if the user is in auto mode.
    const { localStorage } = window;
    if (
      localStorage.getItem("theme_mode") !== "manual" &&
      localStorage.getItem("theme_mode") !== "light" &&
      localStorage.getItem("theme_mode") !== "dark"
    ) {
      theme.set(e.matches ? "dark" : "light");
    }
  };
  window
    .matchMedia("(prefers-color-scheme: dark)")
    .addEventListener("change", systemThemeListener);
}

function detachSystemListener() {
  if (!browser || !systemThemeListener) return;
  window
    .matchMedia("(prefers-color-scheme: dark)")
    .removeEventListener("change", systemThemeListener);
  systemThemeListener = null;
}

// ─── Public API ───────────────────────────────────────────────────────────────

/**
 * Call once on app mount (e.g. in +layout.svelte onMount).
 * Reads persisted preference from localStorage and initialises both stores.
 * Falls back to OS preference when no manual mode is stored.
 */
export function initializeTheme() {
  if (!browser) return;

  const storedMode = localStorage.getItem("theme_mode") as
    | "auto"
    | "light"
    | "dark"
    | null;

  if (storedMode === "light" || storedMode === "dark") {
    // Manual mode — apply directly.
    themeMode.set(storedMode);
    theme.set(storedMode);
    // No OS listener needed while in manual mode.
  } else {
    // Auto mode (default).
    themeMode.set("auto");
    theme.set(getSystemThemePreference());
    attachSystemListener();
  }
}

/**
 * Apply a server-side darkmode value on login / session restore.
 * Only takes effect when the user has NOT set a manual mode locally.
 * This ensures a local manual preference always wins over the server value.
 *
 * @param darkmode  The boolean value from the server (true = dark, false = light).
 */
export function applyServerDarkMode(darkmode: boolean) {
  if (!browser) return;
  const storedMode = localStorage.getItem("theme_mode");
  // If the user already has a manual local preference, do not override it.
  if (storedMode === "light" || storedMode === "dark") {
    console.debug(
      "[theme] applyServerDarkMode: local manual override present, skipping server value",
    );
    return;
  }
  // In auto mode: respect the server value by switching to the matching
  // explicit mode so the user's cross-device preference is honoured.
  const serverMode = darkmode ? "dark" : "light";
  themeMode.set(serverMode);
  theme.set(serverMode);
  // Persist to localStorage so subsequent page loads remember the choice.
  localStorage.setItem("theme_mode", serverMode);
  // Detach the OS listener since we now have a server-driven preference.
  detachSystemListener();
  console.debug(
    `[theme] applyServerDarkMode: applied server mode '${serverMode}'`,
  );
}

/**
 * Set the theme mode explicitly (called from UI settings).
 * Persists to localStorage and optionally syncs to the backend when authenticated.
 *
 * @param mode  'auto' | 'light' | 'dark'
 * @param syncToServer  When true, sends a PATCH to the darkmode API endpoint.
 */
export async function setThemeMode(
  mode: "auto" | "light" | "dark",
  syncToServer = false,
) {
  if (!browser) return;

  themeMode.set(mode);

  if (mode === "auto") {
    // Remove stored manual mode; switch back to OS preference.
    localStorage.removeItem("theme_mode");
    const systemTheme = getSystemThemePreference();
    theme.set(systemTheme);
    localStorage.setItem("theme", systemTheme);
    attachSystemListener();
  } else {
    // Manual mode — persist and detach OS listener.
    localStorage.setItem("theme_mode", mode);
    localStorage.setItem("theme", mode);
    theme.set(mode);
    detachSystemListener();

    // Sync explicit choice to server if authenticated.
    if (syncToServer) {
      try {
        const { getApiEndpoint } = await import("../config/api");
        const endpoint = getApiEndpoint("settings.user.darkmode");
        if (endpoint) {
          const resp = await fetch(endpoint, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            credentials: "include",
            body: JSON.stringify({ darkmode: mode === "dark" }),
          });
          if (resp.ok) {
            console.debug(
              `[theme] Dark mode preference '${mode}' synced to server.`,
            );
          } else {
            console.warn(
              `[theme] Failed to sync dark mode to server: ${resp.status}`,
            );
          }
        }
      } catch (err) {
        console.warn("[theme] Error syncing dark mode to server:", err);
      }
    }
  }
}

/**
 * Legacy toggle helper — kept for any existing callers.
 * Toggles between light and dark (manual mode). Does NOT sync to server.
 * Prefer setThemeMode() for new code.
 */
export function toggleTheme() {
  if (!browser) return;
  // Read current resolved theme and flip it.
  const current = localStorage.getItem("theme") ?? getSystemThemePreference();
  const next = current === "light" ? "dark" : "light";
  setThemeMode(next as "light" | "dark", false);
}
