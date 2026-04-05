// frontend/packages/ui/scripts/audit-tokens.js
//
// Audit script that scans all .svelte files for hardcoded CSS values that
// should use design tokens. Produces token-audit.json — the migration manifest
// consumed by migrate-tokens.js and parallel agent workflows.
//
// Usage:
//   node scripts/audit-tokens.js                    # Full audit
//   node scripts/audit-tokens.js --file path.svelte # Single file
//   node scripts/audit-tokens.js --summary          # Summary only
//
// Output: src/tokens/token-audit.json

import { readFileSync, writeFileSync, readdirSync, statSync } from "fs";
import { dirname, resolve, relative, join } from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const UI_SRC = resolve(__dirname, "../src");
const COMPONENTS_DIR = resolve(UI_SRC, "components");
const OUTPUT_FILE = resolve(UI_SRC, "tokens/token-audit.json");

// ── Token Scales (must match the YAML sources) ────────────────────────────

const SPACING_SCALE = {
  0: 0, 1: 2, 2: 4, 3: 6, 4: 8, 5: 10,
  6: 12, 8: 16, 10: 20, 12: 24, 16: 32,
  20: 40, 24: 48, 32: 64
};
const SPACING_REVERSE = Object.fromEntries(
  Object.entries(SPACING_SCALE).map(([k, v]) => [v, `var(--spacing-${k})`])
);

const RADII_SCALE = {
  1: 4, 2: 6, 3: 8, 4: 10, 5: 12, 6: 14, 7: 16, 8: 20, full: 9999
};
const RADII_REVERSE = Object.fromEntries(
  Object.entries(RADII_SCALE).map(([k, v]) => [v, `var(--radius-${k})`])
);

const FONT_SIZE_MAP = {
  "60px": { token: "var(--font-size-h1)", rem: 3.75 },
  "36px": { token: "var(--font-size-h1-mobile)", rem: 2.25 },
  "30px": { token: "var(--font-size-h2)", rem: 1.875 },
  "24px": { token: "var(--font-size-h2-mobile)", rem: 1.5 },
  "20px": { token: "var(--font-size-h3)", rem: 1.25 },
  "18px": { token: "var(--font-size-h3-mobile)", rem: 1.125 },
  "16px": { token: "var(--font-size-p)", rem: 1 },
  "15px": { token: null, rem: 0.9375 },  // no exact token — flag as manual
  "14px": { token: "var(--font-size-small)", rem: 0.875 },
  "13px": { token: "var(--font-size-xs)", rem: 0.8125 },
  "12px": { token: "var(--font-size-xxs)", rem: 0.75 },
  "11px": { token: "var(--font-size-tiny)", rem: 0.6875 },
  "10px": { token: null, rem: 0.625 },  // no exact token
};

const SHADOW_PRESETS = {
  "0 2px 4px rgba(0, 0, 0, 0.1)": "var(--shadow-xs)",
  "0 2px 8px rgba(0, 0, 0, 0.05)": "var(--shadow-sm)",
  "0 4px 12px rgba(0, 0, 0, 0.15)": "var(--shadow-md)",
  "0 4px 16px rgba(0, 0, 0, 0.15)": "var(--shadow-lg)",
  "0 4px 16px rgba(0, 0, 0, 0.25)": "var(--shadow-xl)",
};

const DURATION_MAP = {
  "0.15s": "var(--duration-fast)",
  "0.2s": "var(--duration-normal)",
  "0.3s": "var(--duration-slow)",
};

const EASING_MAP = {
  "ease": "var(--easing-default)",
  "ease-in-out": "var(--easing-in-out)",
};

const ZINDEX_MAP = {
  0: "var(--z-index-base)",
  1: "var(--z-index-raised)",
  2: "var(--z-index-raised)",
  3: "var(--z-index-raised)",
  10: "var(--z-index-dropdown)",
  20: "var(--z-index-dropdown)",
  100: "var(--z-index-dropdown)",
  200: "var(--z-index-sticky)",
  300: "var(--z-index-overlay)",
  400: "var(--z-index-modal)",
  500: "var(--z-index-popover)",
  1000: "var(--z-index-modal)",
  1001: "var(--z-index-modal)",
  1005: "var(--z-index-popover)",
  1006: "var(--z-index-popover)",
  10000: "var(--z-index-tooltip)",
  99999: "var(--z-index-popover)",
  100000: "var(--z-index-skip-link)",
};

const ICON_SIZE_MAP = {
  16: "var(--icon-size-xs)",
  20: "var(--icon-size-sm)",
  24: "var(--icon-size-md)",
  32: "var(--icon-size-lg)",
  40: "var(--icon-size-xl)",
  48: "var(--icon-size-xxl)",
};

// ── Color normalization ────────────────────────────────────────────────────

/** Normalize hex to 6-digit lowercase. */
function normalizeHex(hex) {
  hex = hex.replace("#", "").toLowerCase();
  if (hex.length === 3) hex = hex[0] + hex[0] + hex[1] + hex[1] + hex[2] + hex[2];
  return "#" + hex;
}

// Map of normalized hex values to token names (light theme)
const COLOR_HEX_MAP = {
  "#ffffff": "var(--color-grey-0)",
  "#f9f9f9": "var(--color-grey-10)",
  "#f3f3f3": "var(--color-grey-20)",
  "#e8e8e8": "var(--color-grey-25)",
  "#e3e3e3": "var(--color-grey-30)",
  "#c4c4c4": "var(--color-grey-40)",
  "#a6a6a6": "var(--color-grey-50)",
  "#888888": "var(--color-grey-60)",
  "#666666": "var(--color-grey-70)",
  "#444444": "var(--color-grey-80)",
  "#222222": "var(--color-grey-90)",
  "#000000": "var(--color-grey-100)",
  "#e6eaff": "var(--color-grey-blue)",
  "#a9a9a9": "var(--color-font-secondary)",
  "#6b6b6b": "var(--color-font-tertiary)",
  "#9e9e9e": "var(--color-font-field-placeholder)",
  "#503ba0": "var(--color-bold-text)",
  "#e74c3c": "var(--color-error)",
  "#e67e22": "var(--color-warning)",
  "#ff553b": "var(--color-button-primary)",
  "#ff6b54": "var(--color-button-primary-hover)",
  "#ff4422": "var(--color-button-primary-pressed)",
  "#808080": "var(--color-button-secondary)",
  "#606060": "var(--color-button-secondary-pressed)",
};

// ── Style block extraction ─────────────────────────────────────────────────

function extractStyleBlocks(content) {
  /** Extract all <style> block contents with their line offsets. */
  const blocks = [];
  const regex = /<style[^>]*>([\s\S]*?)<\/style>/g;
  let match;
  while ((match = regex.exec(content)) !== null) {
    const beforeStyle = content.slice(0, match.index);
    const lineOffset = beforeStyle.split("\n").length;
    blocks.push({ css: match[1], lineOffset });
  }
  return blocks;
}

// ── Replacement detection ──────────────────────────────────────────────────

function findReplacements(css, lineOffset) {
  const replacements = [];
  const lines = css.split("\n");

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const lineNum = lineOffset + i;

    // Skip lines that are comments or already use var()
    if (line.trim().startsWith("/*") || line.trim().startsWith("*") || line.trim().startsWith("//")) continue;

    // Skip lines inside multi-line var() expressions
    if (/var\(--/.test(line) && !/:\s*[^v]/.test(line)) continue;

    // ── Font sizes ──
    const fontSizeMatch = line.match(/font-size:\s*(\d+(?:\.\d+)?px)/);
    if (fontSizeMatch && !line.includes("var(")) {
      const px = fontSizeMatch[1];
      const mapping = FONT_SIZE_MAP[px];
      if (mapping && mapping.token) {
        replacements.push({
          line: lineNum,
          property: "font-size",
          original: px,
          replacement: mapping.token,
          category: "font-size",
          confidence: "exact",
          proof: `${px} = ${mapping.rem}rem × 16px base`
        });
      } else if (mapping) {
        replacements.push({
          line: lineNum,
          property: "font-size",
          original: px,
          replacement: null,
          category: "font-size",
          confidence: "manual",
          note: `No exact token for ${px} (${mapping.rem}rem)`
        });
      }
    }

    // ── Border radius ──
    const radiusMatch = line.match(/border-radius:\s*(\d+)px/);
    if (radiusMatch && !line.includes("var(")) {
      const px = parseInt(radiusMatch[1]);
      if (RADII_REVERSE[px]) {
        replacements.push({
          line: lineNum,
          property: "border-radius",
          original: `${px}px`,
          replacement: RADII_REVERSE[px],
          category: "border-radius",
          confidence: "exact"
        });
      }
    }

    // ── Spacing (gap, padding, margin) ──
    const spacingProps = ["gap", "padding", "margin", "padding-top", "padding-right",
      "padding-bottom", "padding-left", "margin-top", "margin-right",
      "margin-bottom", "margin-left", "row-gap", "column-gap"];
    for (const prop of spacingProps) {
      const spacingRegex = new RegExp(`${prop}:\\s*([^;]+);`);
      const spacingMatch = line.match(spacingRegex);
      if (spacingMatch && !line.includes("var(") && !line.includes("calc(") && !line.includes("auto")) {
        const value = spacingMatch[1].trim();
        // Handle single value
        const singlePxMatch = value.match(/^(\d+)px$/);
        if (singlePxMatch) {
          const px = parseInt(singlePxMatch[1]);
          if (SPACING_REVERSE[px] !== undefined) {
            replacements.push({
              line: lineNum,
              property: prop,
              original: `${px}px`,
              replacement: SPACING_REVERSE[px],
              category: "spacing",
              confidence: "exact"
            });
          }
        }
        // Handle shorthand (e.g., "8px 12px")
        else if (value.includes("px") && !value.includes("var(")) {
          const parts = value.split(/\s+/);
          const allMappable = parts.every(p => {
            const m = p.match(/^(\d+)px$/);
            return m && SPACING_REVERSE[parseInt(m[1])] !== undefined;
          });
          if (allMappable && parts.length > 1) {
            const mapped = parts.map(p => {
              const n = parseInt(p);
              return SPACING_REVERSE[n];
            }).join(" ");
            replacements.push({
              line: lineNum,
              property: prop,
              original: value,
              replacement: mapped,
              category: "spacing",
              confidence: "exact"
            });
          }
        }
      }
    }

    // ── Colors (hex) ──
    const colorProps = ["color", "background-color", "background", "border-color",
      "border", "fill", "stroke", "outline-color", "text-decoration-color"];
    for (const prop of colorProps) {
      const colorRegex = new RegExp(`(?:^|;|\\s)${prop}:\\s*([^;]+);`);
      const colorMatch = line.match(colorRegex);
      if (colorMatch && !line.includes("var(") && !line.includes("gradient")) {
        const value = colorMatch[1].trim();
        const hexMatch = value.match(/#[0-9a-fA-F]{3,8}/);
        if (hexMatch) {
          const normalized = normalizeHex(hexMatch[0]);
          if (COLOR_HEX_MAP[normalized]) {
            replacements.push({
              line: lineNum,
              property: prop,
              original: hexMatch[0],
              replacement: COLOR_HEX_MAP[normalized],
              category: "color",
              confidence: "exact"
            });
          }
        }
      }
    }

    // ── Z-index ──
    const zIndexMatch = line.match(/z-index:\s*(\d+)/);
    if (zIndexMatch && !line.includes("var(")) {
      const value = parseInt(zIndexMatch[1]);
      if (ZINDEX_MAP[value] !== undefined) {
        const isIdentity = value === 0 || value === 1;
        replacements.push({
          line: lineNum,
          property: "z-index",
          original: String(value),
          replacement: ZINDEX_MAP[value],
          category: "z-index",
          confidence: isIdentity ? "exact" : "manual",
          note: isIdentity ? undefined : `z-index ${value} → ${ZINDEX_MAP[value]} (value changes — requires stacking review)`
        });
      }
    }

    // ── Box shadows ──
    const shadowMatch = line.match(/box-shadow:\s*([^;]+);/);
    if (shadowMatch && !line.includes("var(") && shadowMatch[1].trim() !== "none") {
      const normalized = shadowMatch[1].trim().replace(/\s+/g, " ").replace(/,\s*/g, ", ");
      // Try exact match against presets
      for (const [preset, token] of Object.entries(SHADOW_PRESETS)) {
        if (normalized === preset) {
          replacements.push({
            line: lineNum,
            property: "box-shadow",
            original: normalized,
            replacement: token,
            category: "shadow",
            confidence: "exact"
          });
          break;
        }
      }
    }

    // ── Transitions ──
    const transitionMatch = line.match(/transition:\s*([^;]+);/);
    if (transitionMatch && !line.includes("var(")) {
      const value = transitionMatch[1].trim();
      // Parse individual transitions (comma-separated)
      const transitions = value.split(",").map(t => t.trim());
      let allMappable = true;
      const mapped = transitions.map(t => {
        const parts = t.split(/\s+/);
        // Expected: property duration [easing]
        if (parts.length >= 2) {
          const property = parts[0];
          const duration = parts[1];
          const easing = parts[2] || null;
          let newDuration = DURATION_MAP[duration];
          let newEasing = easing ? EASING_MAP[easing] : null;
          if (newDuration) {
            return [property, newDuration, newEasing].filter(Boolean).join(" ");
          }
        }
        allMappable = false;
        return t;
      });
      if (allMappable) {
        replacements.push({
          line: lineNum,
          property: "transition",
          original: value,
          replacement: mapped.join(", "),
          category: "transition",
          confidence: "exact"
        });
      }
    }
  }

  return replacements;
}

// ── File scanning ──────────────────────────────────────────────────────────

function walkDir(dir) {
  /** Recursively list all .svelte files. */
  const results = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const fullPath = join(dir, entry.name);
    if (entry.isDirectory()) {
      results.push(...walkDir(fullPath));
    } else if (entry.name.endsWith(".svelte")) {
      results.push(fullPath);
    }
  }
  return results;
}

function auditFile(filePath) {
  const content = readFileSync(filePath, "utf-8");
  const styleBlocks = extractStyleBlocks(content);
  const allReplacements = [];

  for (const block of styleBlocks) {
    allReplacements.push(...findReplacements(block.css, block.lineOffset));
  }

  return allReplacements;
}

// ── Main ───────────────────────────────────────────────────────────────────

function main() {
  const args = process.argv.slice(2);
  const singleFile = args.find(a => a.startsWith("--file="))?.split("=")[1]
    || (args.includes("--file") ? args[args.indexOf("--file") + 1] : null);
  const summaryOnly = args.includes("--summary");

  let files;
  if (singleFile) {
    files = [resolve(singleFile)];
  } else {
    // Scan both UI components and web app sources
    const webAppSrc = resolve(__dirname, "../../apps/web_app/src");
    files = [...walkDir(COMPONENTS_DIR)];
    try { files.push(...walkDir(webAppSrc)); } catch { /* web_app may not exist */ }
    files.sort();
  }

  const audit = {
    generated: new Date().toISOString(),
    summary: {
      total_files: files.length,
      files_with_hardcoded: 0,
      total_replacements: 0,
      by_category: {},
      by_confidence: { exact: 0, approximate: 0, manual: 0 }
    },
    files: {}
  };

  for (const file of files) {
    const replacements = auditFile(file);
    if (replacements.length > 0) {
      const relPath = relative(UI_SRC, file);
      audit.files[relPath] = { replacements };
      audit.summary.files_with_hardcoded++;
      audit.summary.total_replacements += replacements.length;

      for (const r of replacements) {
        audit.summary.by_category[r.category] = (audit.summary.by_category[r.category] || 0) + 1;
        audit.summary.by_confidence[r.confidence] = (audit.summary.by_confidence[r.confidence] || 0) + 1;
      }
    }
  }

  // Print summary
  console.log(`\n[audit-tokens] Scanned ${audit.summary.total_files} files`);
  console.log(`[audit-tokens] ${audit.summary.files_with_hardcoded} files with hardcoded values`);
  console.log(`[audit-tokens] ${audit.summary.total_replacements} total replacements found`);
  console.log("\nBy category:");
  for (const [cat, count] of Object.entries(audit.summary.by_category).sort((a, b) => b[1] - a[1])) {
    console.log(`  ${cat}: ${count}`);
  }
  console.log("\nBy confidence:");
  for (const [conf, count] of Object.entries(audit.summary.by_confidence)) {
    if (count > 0) console.log(`  ${conf}: ${count}`);
  }

  if (!summaryOnly) {
    writeFileSync(OUTPUT_FILE, JSON.stringify(audit, null, 2) + "\n", "utf-8");
    console.log(`\n[audit-tokens] Written to ${OUTPUT_FILE}`);
  }
}

main();
