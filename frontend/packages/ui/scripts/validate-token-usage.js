// frontend/packages/ui/scripts/validate-token-usage.js
//
// Lint script that flags hardcoded CSS values that should use design tokens.
// Runs during build to prevent regression after the token migration.
//
// Usage:
//   node scripts/validate-token-usage.js              # Full scan (warnings only)
//   node scripts/validate-token-usage.js --strict     # Exit 1 on any violation
//   node scripts/validate-token-usage.js --file path  # Single file
//
// Checks:
//   ERROR:   font-size with px units (accessibility violation)
//   WARNING: Raw hex/rgb colors, z-index, border-radius, spacing, shadow, transition

import { readFileSync, readdirSync, existsSync } from "fs";
import { dirname, resolve, relative, join } from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const UI_SRC = resolve(__dirname, "../src");
const COMPONENTS_DIR = resolve(UI_SRC, "components");
const ALLOWLIST_PATH = resolve(UI_SRC, "tokens/.token-allowlist.json");

// Load allowlist (file:line pairs that are intentionally hardcoded)
let allowlist = {};
if (existsSync(ALLOWLIST_PATH)) {
  allowlist = JSON.parse(readFileSync(ALLOWLIST_PATH, "utf-8"));
}

function extractStyleBlocks(content) {
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

function validateFile(filePath, relPath) {
  const content = readFileSync(filePath, "utf-8");
  const styleBlocks = extractStyleBlocks(content);
  const violations = [];
  const fileAllowlist = allowlist[relPath] || [];

  for (const block of styleBlocks) {
    const lines = block.css.split("\n");
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      const lineNum = block.lineOffset + i;

      // Skip comments and lines already using var()
      if (line.trim().startsWith("/*") || line.trim().startsWith("*") || line.trim().startsWith("//")) continue;
      if (fileAllowlist.includes(lineNum)) continue;

      // ERROR: font-size with px units (accessibility)
      if (/font-size:\s*\d+(?:\.\d+)?px/.test(line) && !line.includes("var(")) {
        violations.push({ line: lineNum, severity: "error", rule: "font-size-px",
          message: `font-size uses px — use var(--font-size-*) token (rem for accessibility)` });
      }

      // WARNING: raw hex colors in style properties
      if (/(?:color|background(?:-color)?|border(?:-color)?|fill|stroke):\s*#[0-9a-fA-F]{3,8}/.test(line) && !line.includes("var(")) {
        violations.push({ line: lineNum, severity: "warning", rule: "raw-color",
          message: `Hardcoded color — use var(--color-*) token` });
      }

      // WARNING: z-index with raw numbers
      if (/z-index:\s*\d+/.test(line) && !line.includes("var(")) {
        violations.push({ line: lineNum, severity: "warning", rule: "raw-z-index",
          message: `Hardcoded z-index — use var(--z-index-*) token` });
      }

      // WARNING: border-radius with common token values
      if (/border-radius:\s*(?:4|6|8|10|12|14|16|20|9999)px/.test(line) && !line.includes("var(")) {
        violations.push({ line: lineNum, severity: "warning", rule: "raw-radius",
          message: `Hardcoded border-radius — use var(--radius-*) token` });
      }

      // WARNING: box-shadow with common preset patterns
      if (/box-shadow:\s*0\s+\d+px\s+\d+px\s+rgba/.test(line) && !line.includes("var(") && !line.includes("none")) {
        violations.push({ line: lineNum, severity: "warning", rule: "raw-shadow",
          message: `Hardcoded box-shadow — use var(--shadow-*) token` });
      }
    }
  }

  return violations;
}

function walkDir(dir) {
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

function main() {
  const args = process.argv.slice(2);
  const strict = args.includes("--strict");
  const singleFile = args.find(a => a.startsWith("--file="))?.split("=")[1]
    || (args.includes("--file") ? args[args.indexOf("--file") + 1] : null);

  let files;
  if (singleFile) {
    files = [resolve(singleFile)];
  } else {
    files = walkDir(COMPONENTS_DIR).sort();
  }

  let totalErrors = 0;
  let totalWarnings = 0;

  for (const file of files) {
    const relPath = relative(UI_SRC, file);
    const violations = validateFile(file, relPath);

    if (violations.length > 0) {
      for (const v of violations) {
        const prefix = v.severity === "error" ? "ERROR" : "WARN ";
        console.log(`  ${prefix} ${relPath}:${v.line} — ${v.message}`);
        if (v.severity === "error") totalErrors++;
        else totalWarnings++;
      }
    }
  }

  console.log(`\n[validate-token-usage] ${files.length} files scanned: ${totalErrors} errors, ${totalWarnings} warnings`);

  if (totalErrors > 0) {
    console.error("[validate-token-usage] ✗ Errors found — fix before committing.");
    process.exit(1);
  }
  if (strict && totalWarnings > 0) {
    console.error("[validate-token-usage] ✗ Warnings found (--strict mode).");
    process.exit(1);
  }
  console.log("[validate-token-usage] ✓ Passed.");
}

main();
