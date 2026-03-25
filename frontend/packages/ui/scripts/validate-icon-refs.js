// frontend/packages/ui/scripts/validate-icon-refs.js
//
// Build-time validation: ensures every icon name referenced in SettingsItem
// and AppDetailsHeader components resolves to a valid --icon-url-{name} CSS variable.
//
// Catches mismatches like icon="mates" → --icon-url-mates (doesn't exist;
// the SVG is mate.svg → --icon-url-mate). Runs as part of the build pipeline
// after generate-icon-urls.js so the generated CSS file is already up to date.
//
// Validates two things:
//   1. ICON_NAME_MAP values in iconNameResolver.ts point to real SVG files
//   2. Icon names used in components resolve (via ICON_NAME_MAP or directly)
//      to an existing --icon-url-{name} CSS variable
//
// Architecture: docs/architecture/settings-ui.md
// Related: scripts/generate-icon-urls.js, src/utils/iconNameResolver.ts

import { readFileSync, readdirSync, existsSync } from "fs";
import { resolve, dirname, basename } from "path";
import { fileURLToPath } from "url";
import { execSync } from "child_process";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const ICONS_DIR = resolve(__dirname, "../static/icons");
const ICON_RESOLVER = resolve(__dirname, "../src/utils/iconNameResolver.ts");
const ICON_SVELTE = resolve(__dirname, "../src/components/Icon.svelte");

// Directories to scan for icon usage
const SCAN_DIRS = [
  resolve(__dirname, "../src"),
  resolve(__dirname, "../../web_app/src"),
];

/**
 * Build the set of icon names that have a valid --icon-url-{name} CSS variable.
 * Sources: SVG filenames + CSS aliases defined in Icon.svelte's :root block.
 */
function getAvailableIconNames() {
  const svgNames = new Set(
    readdirSync(ICONS_DIR)
      .filter((f) => f.endsWith(".svg"))
      .map((f) => basename(f, ".svg")),
  );

  // CSS aliases: --icon-url-bfl: var(--icon-url-blackforestlabs);
  const iconSvelteContent = readFileSync(ICON_SVELTE, "utf-8");
  const aliasRe = /--icon-url-([\w][\w-]*)\s*:\s*var\(--icon-url-/g;
  let m;
  while ((m = aliasRe.exec(iconSvelteContent)) !== null) {
    svgNames.add(m[1]);
  }

  return svgNames;
}

/**
 * Parse ICON_NAME_MAP from the shared iconNameResolver.ts.
 */
function parseIconNameMap() {
  const content = readFileSync(ICON_RESOLVER, "utf-8");

  const mapMatch = content.match(
    /export\s+const\s+ICON_NAME_MAP[^{]*\{([^}]+)\}/s,
  );
  if (!mapMatch) {
    console.error(
      "[validate-icon-refs] Could not parse ICON_NAME_MAP from iconNameResolver.ts",
    );
    process.exit(1);
  }

  const map = {};
  const entryRe = /['"]([^'"]+)['"]\s*:\s*['"]([^'"]+)['"]/g;
  let m;
  while ((m = entryRe.exec(mapMatch[1])) !== null) {
    map[m[1]] = m[2];
  }
  return map;
}

/**
 * Mirror iconNameResolver's resolveIconName() logic:
 * strip "subsetting_icon " prefix, then map through ICON_NAME_MAP.
 */
function resolveIconName(name, iconNameMap) {
  const clean = name.startsWith("subsetting_icon ")
    ? name.slice("subsetting_icon ".length)
    : name;
  return iconNameMap[clean] || clean;
}

/**
 * Find icon="..." and icon: '...' usages in .svelte files that use SettingsItem
 * or AppDetailsHeader (both resolve icons via ICON_NAME_MAP).
 */
function findSettingsIconUsages() {
  const usages = [];

  for (const dir of SCAN_DIRS) {
    if (!existsSync(dir)) continue;

    let files;
    try {
      files = execSync(
        `find ${dir} -type f -name '*.svelte' ! -path '*/node_modules/*'`,
        { encoding: "utf-8" },
      )
        .trim()
        .split("\n")
        .filter(Boolean);
    } catch {
      continue;
    }

    for (const file of files) {
      const content = readFileSync(file, "utf-8");

      // Only check files that use SettingsItem or AppDetailsHeader
      if (
        !content.includes("SettingsItem") &&
        !content.includes("settingsItem") &&
        !content.includes("AppDetailsHeader") &&
        !content.includes("settingsPage")
      ) {
        continue;
      }

      // Pattern 1: icon="value" (Svelte template prop)
      const templateRe = /\bicon\s*=\s*"([^"]+)"/g;
      let m;
      while ((m = templateRe.exec(content)) !== null) {
        const val = m[1];
        // Skip dynamic expressions and file paths
        if (val.includes("{") || val.includes("$") || val.startsWith("/"))
          continue;
        usages.push({
          file: file.replace(resolve(__dirname, "../../..") + "/", ""),
          icon: val,
          line: content.substring(0, m.index).split("\n").length,
        });
      }

      // Pattern 2: icon: 'value' (JS object dispatched to SettingsItem/AppDetailsHeader)
      const objRe = /\bicon\s*:\s*['"]([^'"]+)['"]/g;
      while ((m = objRe.exec(content)) !== null) {
        const val = m[1];
        if (val.includes("{") || val.includes("$") || val.startsWith("/"))
          continue;
        usages.push({
          file: file.replace(resolve(__dirname, "../../..") + "/", ""),
          icon: val,
          line: content.substring(0, m.index).split("\n").length,
        });
      }
    }
  }

  return usages;
}

function validate() {
  const availableNames = getAvailableIconNames();
  const iconNameMap = parseIconNameMap();
  const usages = findSettingsIconUsages();
  const errors = [];

  // 1. Validate ICON_NAME_MAP values point to real SVG names
  for (const [key, value] of Object.entries(iconNameMap)) {
    if (!availableNames.has(value)) {
      errors.push(
        `ICON_NAME_MAP['${key}'] → '${value}' has no matching SVG (no --icon-url-${value})`,
      );
    }
  }

  // 2. Validate each icon usage resolves to an available CSS variable
  const seen = new Set();
  for (const { file, icon, line } of usages) {
    const resolved = resolveIconName(icon, iconNameMap);
    const key = `${icon}→${resolved}`;
    if (seen.has(key)) continue;
    seen.add(key);

    if (!availableNames.has(resolved)) {
      const examples = usages
        .filter((u) => u.icon === icon)
        .slice(0, 2)
        .map((u) => `${u.file}:${u.line}`)
        .join(", ");
      errors.push(
        `icon="${icon}" resolves to --icon-url-${resolved} (no matching SVG). Used in: ${examples}`,
      );
    }
  }

  if (errors.length > 0) {
    console.error(
      `\n[validate-icon-refs] ❌ ${errors.length} broken icon reference(s):\n`,
    );
    for (const err of errors) {
      console.error(`  • ${err}`);
    }
    console.error(
      "\nFix: add a mapping in ICON_NAME_MAP (src/utils/iconNameResolver.ts) or add the SVG to static/icons/.\n",
    );
    process.exit(1);
  }

  console.log(
    `[validate-icon-refs] ✅ All ${seen.size} icon references resolve to valid CSS variables`,
  );
}

validate();
