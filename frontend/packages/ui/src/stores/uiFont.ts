// frontend/packages/ui/src/stores/uiFont.ts
//
// Manages the app-wide interface font preference.
//
// The generated token CSS owns the default `--font-primary` value.
// This store applies a user override at the document root so the preference
// affects the whole web UI without modifying generated token files.

import { browser } from "$app/environment";
import { writable } from "svelte/store";

export type UiFont =
  | "lexend"
  | "figtree"
  | "rubik"
  | "inter"
  | "public_sans"
  | "atkinson"
  | "ibm_plex_sans"
  | "source_serif"
  | "jetbrains_mono"
  | "ibm_plex_mono"
  | "system"
  | "serif"
  | "mono";

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
    value: "figtree",
    labelKey: "settings.interface.font.figtree",
    descriptionKey: "settings.interface.font.figtree.description",
    cssStack: '"Figtree Variable", Figtree, system-ui, sans-serif',
  },
  {
    value: "rubik",
    labelKey: "settings.interface.font.rubik",
    descriptionKey: "settings.interface.font.rubik.description",
    cssStack: '"Rubik Variable", Rubik, system-ui, sans-serif',
  },
  {
    value: "inter",
    labelKey: "settings.interface.font.inter",
    descriptionKey: "settings.interface.font.inter.description",
    cssStack: '"Inter Variable", Inter, system-ui, sans-serif',
  },
  {
    value: "public_sans",
    labelKey: "settings.interface.font.public_sans",
    descriptionKey: "settings.interface.font.public_sans.description",
    cssStack: '"Public Sans Variable", "Public Sans", system-ui, sans-serif',
  },
  {
    value: "atkinson",
    labelKey: "settings.interface.font.atkinson",
    descriptionKey: "settings.interface.font.atkinson.description",
    cssStack: '"Atkinson Hyperlegible", system-ui, sans-serif',
  },
  {
    value: "ibm_plex_sans",
    labelKey: "settings.interface.font.ibm_plex_sans",
    descriptionKey: "settings.interface.font.ibm_plex_sans.description",
    cssStack: '"IBM Plex Sans", system-ui, sans-serif',
  },
  {
    value: "source_serif",
    labelKey: "settings.interface.font.source_serif",
    descriptionKey: "settings.interface.font.source_serif.description",
    cssStack: '"Source Serif 4 Variable", "Source Serif 4", Georgia, serif',
  },
  {
    value: "jetbrains_mono",
    labelKey: "settings.interface.font.jetbrains_mono",
    descriptionKey: "settings.interface.font.jetbrains_mono.description",
    cssStack: '"JetBrains Mono Variable", "JetBrains Mono", monospace',
  },
  {
    value: "ibm_plex_mono",
    labelKey: "settings.interface.font.ibm_plex_mono",
    descriptionKey: "settings.interface.font.ibm_plex_mono.description",
    cssStack: '"IBM Plex Mono", monospace',
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

const loadedFontCss = new Set<UiFont>();

export function isUiFont(value: unknown): value is UiFont {
  return typeof value === "string" && UI_FONT_OPTIONS.some((option) => option.value === value);
}

function applyUiFont(font: UiFont): void {
  if (!browser) return;

  void loadUiFontCss(font);
  const option = UI_FONT_OPTIONS.find((candidate) => candidate.value === font) ?? UI_FONT_OPTIONS[0];
  document.documentElement.style.setProperty("--font-primary", option.cssStack);
  document.documentElement.style.setProperty("--button-font-family", option.cssStack);
  document.documentElement.dataset.uiFont = option.value;
}

async function loadUiFontCss(font: UiFont): Promise<void> {
  if (loadedFontCss.has(font)) return;
  loadedFontCss.add(font);

  try {
    switch (font) {
      case "lexend":
        await import("@fontsource-variable/lexend-deca");
        break;
      case "figtree":
        await import("@fontsource-variable/figtree");
        break;
      case "rubik":
        await import("@fontsource-variable/rubik");
        break;
      case "inter":
        await import("@fontsource-variable/inter");
        break;
      case "public_sans":
        await import("@fontsource-variable/public-sans");
        break;
      case "atkinson":
        await import("@fontsource/atkinson-hyperlegible");
        break;
      case "ibm_plex_sans":
        await import("@fontsource/ibm-plex-sans");
        break;
      case "source_serif":
        await import("@fontsource-variable/source-serif-4");
        break;
      case "jetbrains_mono":
        await import("@fontsource-variable/jetbrains-mono");
        break;
      case "ibm_plex_mono":
        await import("@fontsource/ibm-plex-mono");
        break;
    }
  } catch (error) {
    console.warn(`[uiFont] Failed to load font CSS for ${font}:`, error);
  }
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
    const { apiEndpoints, getApiEndpoint } = await import("../config/api");
    const endpoint = getApiEndpoint(apiEndpoints.settings.user.ui_font);
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
