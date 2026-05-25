// frontend/packages/ui/src/stores/uiFont.ts
//
// Manages the app-wide interface font preference.
//
// The generated token CSS owns the default `--font-primary` value.
// This store applies a user override at the document root so the preference
// affects the whole web UI without modifying generated token files.

import { browser } from "$app/environment";
import { writable } from "svelte/store";

export type UiFont = "lexend" | "system" | "serif" | "mono";

export const DEFAULT_UI_FONT: UiFont = "lexend";
export const UI_FONT_STORAGE_KEY = "ui_font";

export const UI_FONT_OPTIONS: Array<{
  value: UiFont;
  labelKey: string;
  descriptionKey: string;
  cssStack: string;
}> = [
  {
    value: "lexend",
    labelKey: "settings.interface.font.lexend",
    descriptionKey: "settings.interface.font.lexend.description",
    cssStack: '"Lexend Deca Variable", "Lexend Deca", system-ui, sans-serif',
  },
  {
    value: "system",
    labelKey: "settings.interface.font.system",
    descriptionKey: "settings.interface.font.system.description",
    cssStack: 'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
  },
  {
    value: "serif",
    labelKey: "settings.interface.font.serif",
    descriptionKey: "settings.interface.font.serif.description",
    cssStack: 'Georgia, "Times New Roman", Times, serif',
  },
  {
    value: "mono",
    labelKey: "settings.interface.font.mono",
    descriptionKey: "settings.interface.font.mono.description",
    cssStack: '"SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace',
  },
];

export const uiFont = writable<UiFont>(DEFAULT_UI_FONT);

export function isUiFont(value: unknown): value is UiFont {
  return typeof value === "string" && UI_FONT_OPTIONS.some((option) => option.value === value);
}

function applyUiFont(font: UiFont): void {
  if (!browser) return;

  const option = UI_FONT_OPTIONS.find((candidate) => candidate.value === font) ?? UI_FONT_OPTIONS[0];
  document.documentElement.style.setProperty("--font-primary", option.cssStack);
  document.documentElement.style.setProperty("--button-font-family", option.cssStack);
  document.documentElement.dataset.uiFont = option.value;
}

export function initializeUiFont(): void {
  if (!browser) return;

  const storedFont = localStorage.getItem(UI_FONT_STORAGE_KEY);
  const font = isUiFont(storedFont) ? storedFont : DEFAULT_UI_FONT;
  uiFont.set(font);
  applyUiFont(font);
}

export function applyServerUiFont(font: string | null | undefined): void {
  if (!browser || !isUiFont(font)) return;

  const localFont = localStorage.getItem(UI_FONT_STORAGE_KEY);
  if (isUiFont(localFont)) return;

  uiFont.set(font);
  localStorage.setItem(UI_FONT_STORAGE_KEY, font);
  applyUiFont(font);
}

export async function setUiFont(font: UiFont, syncToServer = false): Promise<void> {
  if (!browser) return;

  uiFont.set(font);
  localStorage.setItem(UI_FONT_STORAGE_KEY, font);
  applyUiFont(font);

  if (!syncToServer) return;

  try {
    const { getApiEndpoint } = await import("../config/api");
    const endpoint = getApiEndpoint("settings.user.ui_font");
    if (!endpoint) return;

    const response = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ ui_font: font }),
    });

    if (!response.ok) {
      console.warn(`[uiFont] Failed to sync UI font to server: ${response.status}`);
    }
  } catch (error) {
    console.warn("[uiFont] Error syncing UI font to server:", error);
  }
}
