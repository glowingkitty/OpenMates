// frontend/packages/ui/src/stores/__tests__/theme.test.ts
// Regression coverage for persisted light/dark theme precedence.
// Verifies migration from the legacy manual preference keys and ensures
// authenticated server restore cannot overwrite a local manual choice.
// Architecture: frontend/packages/ui/src/stores/theme.ts

import { beforeEach, describe, expect, it, vi } from "vitest";
import { get } from "svelte/store";

vi.mock("$app/environment", () => ({ browser: true }));

import {
  applyServerDarkMode,
  initializeTheme,
  theme,
  themeMode,
} from "../theme";

const storage = new Map<string, string>();
const localStorageMock = {
  getItem: vi.fn((key: string) => storage.get(key) ?? null),
  setItem: vi.fn((key: string, value: string) => storage.set(key, value)),
  removeItem: vi.fn((key: string) => storage.delete(key)),
};
const mediaQueryMock = {
  matches: true,
  addEventListener: vi.fn(),
  removeEventListener: vi.fn(),
};

describe("theme persistence", () => {
  beforeEach(() => {
    storage.clear();
    vi.clearAllMocks();
    Object.defineProperty(globalThis, "localStorage", {
      configurable: true,
      value: localStorageMock,
    });
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      value: localStorageMock,
    });
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      value: vi.fn(() => mediaQueryMock),
    });
    theme.set("light");
    themeMode.set("auto");
  });

  it("keeps following the OS theme during authenticated session restore", () => {
    initializeTheme();
    applyServerDarkMode(false);

    expect(get(theme)).toBe("dark");
    expect(get(themeMode)).toBe("auto");
    expect(storage.get("theme_mode")).toBeUndefined();
  });

  it("migrates a legacy manual dark preference during initialization", () => {
    storage.set("theme_preference", "manual");
    storage.set("theme", "dark");

    initializeTheme();

    expect(get(theme)).toBe("dark");
    expect(get(themeMode)).toBe("dark");
    expect(storage.get("theme_mode")).toBe("dark");
  });

  it("keeps a legacy local manual preference during server restore", () => {
    storage.set("theme_preference", "manual");
    storage.set("theme", "dark");

    applyServerDarkMode(false);

    expect(get(theme)).toBe("dark");
    expect(get(themeMode)).toBe("dark");
    expect(storage.get("theme_mode")).toBe("dark");
  });

  it("prefers the current theme_mode key over legacy values", () => {
    storage.set("theme_mode", "light");
    storage.set("theme_preference", "manual");
    storage.set("theme", "dark");

    initializeTheme();

    expect(get(theme)).toBe("light");
    expect(get(themeMode)).toBe("light");
  });
});
