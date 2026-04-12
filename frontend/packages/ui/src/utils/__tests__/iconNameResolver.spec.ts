// frontend/packages/ui/src/utils/__tests__/iconNameResolver.spec.ts
//
// Unit tests for resolveIconName() — the single source of truth for mapping
// logical icon names to CSS variable names (--icon-url-{name}).
//
// Regression test for: app icons (health, events, books, code) not rendering
// in settings pages because app IDs were used instead of SVG filenames.

import { describe, it, expect } from "vitest";
import { resolveIconName, ICON_NAME_MAP } from "../iconNameResolver";
import { readdirSync } from "fs";
import { resolve, basename, dirname } from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const ICONS_DIR = resolve(__dirname, "../../../static/icons");

/** Set of SVG filenames (without extension) available in static/icons/ */
const availableSvgNames = new Set(
  readdirSync(ICONS_DIR)
    .filter((f) => f.endsWith(".svg"))
    .map((f) => basename(f, ".svg")),
);

describe("resolveIconName", () => {
  // ── App ID → SVG filename mappings (regression: these were broken) ─────

  it.each([
    ["health", "heart"],
    ["code", "coding"],
    ["books", "book"],
    ["events", "event"],
  ])(
    "resolves app ID '%s' to SVG filename '%s'",
    (appId, expectedSvg) => {
      expect(resolveIconName(appId)).toBe(expectedSvg);
    },
  );

  // ── Identity mappings: SVG filenames that match directly ───────────────

  it.each(["heart", "coding", "book", "event", "ai", "mail", "search", "web"])(
    "preserves SVG filename '%s' as-is (no mapping needed)",
    (svgName) => {
      // These should either return themselves or map to another valid SVG
      const resolved = resolveIconName(svgName);
      expect(availableSvgNames.has(resolved)).toBe(true);
    },
  );

  // ── Settings section mappings ──────────────────────────────────────────

  it.each([
    ["account", "user"],
    ["apps", "app"],
    ["developers", "coding"],
    ["privacy", "lock"],
    ["notifications", "announcement"],
    ["email", "mail"],
  ])(
    "maps settings section '%s' to SVG '%s'",
    (section, expectedSvg) => {
      expect(resolveIconName(section)).toBe(expectedSvg);
    },
  );

  // ── subsetting_icon prefix stripping ──────────────────────────────────

  it("strips 'subsetting_icon ' prefix before resolving", () => {
    expect(resolveIconName("subsetting_icon account")).toBe("user");
    expect(resolveIconName("subsetting_icon health")).toBe("heart");
  });

  // ── All ICON_NAME_MAP values must point to real SVG files ──────────────

  it("every ICON_NAME_MAP value has a corresponding SVG in static/icons/", () => {
    const missing: string[] = [];
    for (const [key, value] of Object.entries(ICON_NAME_MAP)) {
      if (!availableSvgNames.has(value)) {
        missing.push(`'${key}' → '${value}'`);
      }
    }
    expect(missing).toEqual([]);
  });
});
