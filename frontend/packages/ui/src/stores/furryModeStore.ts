// frontend/packages/ui/src/stores/furryModeStore.ts
//
// Account-synced UI preference for Furry Mode.
// The local store mirrors the server value for instant CSS avatar swapping;
// backend prompt construction reads the synced value from the user profile.

import { browser } from "$app/environment";
import { writable } from "svelte/store";

const STORAGE_KEY = "openmates_furry_mode_enabled";
const ROOT_ATTRIBUTE = "data-furry-mode";

function readInitialValue(): boolean {
  if (!browser) return false;
  return localStorage.getItem(STORAGE_KEY) === "true";
}

function applyRootAttribute(enabled: boolean) {
  if (!browser) return;
  document.documentElement.setAttribute(ROOT_ATTRIBUTE, enabled ? "true" : "false");
}

export const furryModeEnabled = writable<boolean>(readInitialValue());

if (browser) {
  applyRootAttribute(readInitialValue());
  furryModeEnabled.subscribe((enabled) => {
    localStorage.setItem(STORAGE_KEY, enabled ? "true" : "false");
    applyRootAttribute(enabled);
  });
}

export function initializeFurryMode() {
  applyRootAttribute(readInitialValue());
}

export function setFurryModeEnabled(enabled: boolean) {
  furryModeEnabled.set(enabled);
}

export function applySyncedFurryMode(enabled: boolean | null | undefined) {
  setFurryModeEnabled(enabled === true);
}
