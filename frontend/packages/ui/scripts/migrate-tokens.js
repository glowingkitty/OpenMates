// frontend/packages/ui/scripts/migrate-tokens.js
//
// Migration script that replaces hardcoded CSS values with design token
// references in a single .svelte file. Uses the audit manifest produced
// by audit-tokens.js.
//
// Usage:
//   node scripts/migrate-tokens.js <relative-path-from-src>
//   node scripts/migrate-tokens.js components/Notification.svelte
//   node scripts/migrate-tokens.js --dry-run components/Notification.svelte
//
// The script reads token-audit.json, finds replacements for the given file,
// and performs them in reverse line order (to preserve line offsets).

import { readFileSync, writeFileSync, existsSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const UI_SRC = resolve(__dirname, "../src");
const AUDIT_FILE = resolve(UI_SRC, "tokens/token-audit.json");

function main() {
  const args = process.argv.slice(2);
  const dryRun = args.includes("--dry-run");
  const exactOnly = args.includes("--exact-only");
  const includeManual = args.includes("--include-manual");
  const filePaths = args.filter(a => !a.startsWith("--"));

  if (filePaths.length === 0) {
    console.error("Usage: node scripts/migrate-tokens.js [--dry-run] [--exact-only] <file-path> [<file-path> ...]");
    console.error("  File paths are relative to src/ (e.g., components/Notification.svelte)");
    process.exit(1);
  }

  if (!existsSync(AUDIT_FILE)) {
    console.error("[migrate-tokens] token-audit.json not found. Run audit-tokens.js first.");
    process.exit(1);
  }

  const audit = JSON.parse(readFileSync(AUDIT_FILE, "utf-8"));
  let totalChanged = 0;
  let totalSkipped = 0;

  for (const filePath of filePaths) {
    const fileData = audit.files[filePath];
    if (!fileData) {
      console.log(`[migrate-tokens] No replacements found for ${filePath} — skipping.`);
      continue;
    }

    let replacements = fileData.replacements;
    if (exactOnly) {
      replacements = replacements.filter(r => r.confidence === "exact");
    } else if (!includeManual) {
      // Skip manual confidence by default (only exact + approximate)
      replacements = replacements.filter(r => r.confidence !== "manual");
    }
    // With --include-manual, all replacements are applied (including z-index)

    if (replacements.length === 0) {
      console.log(`[migrate-tokens] No applicable replacements for ${filePath} — skipping.`);
      continue;
    }

    const absPath = resolve(UI_SRC, filePath);
    if (!existsSync(absPath)) {
      console.error(`[migrate-tokens] File not found: ${absPath}`);
      continue;
    }

    const content = readFileSync(absPath, "utf-8");
    const lines = content.split("\n");

    // Sort replacements by line number descending (so edits don't shift offsets)
    const sorted = [...replacements].sort((a, b) => b.line - a.line);

    let changed = 0;
    let skipped = 0;

    for (const r of sorted) {
      const lineIdx = r.line - 1; // 0-based
      if (lineIdx < 0 || lineIdx >= lines.length) {
        console.warn(`  [skip] Line ${r.line} out of range in ${filePath}`);
        skipped++;
        continue;
      }

      const line = lines[lineIdx];

      // Verify the original value is still present
      if (!line.includes(r.original)) {
        console.warn(`  [skip] L${r.line}: "${r.original}" not found in line`);
        skipped++;
        continue;
      }

      // Skip if already tokenized
      if (line.includes("var(--") && line.includes(r.property)) {
        skipped++;
        continue;
      }

      // Perform replacement
      const newLine = line.replace(r.original, r.replacement);
      lines[lineIdx] = newLine;
      changed++;

      if (dryRun) {
        console.log(`  L${r.line} ${r.property}: ${r.original} → ${r.replacement}`);
      }
    }

    if (!dryRun && changed > 0) {
      writeFileSync(absPath, lines.join("\n"), "utf-8");
    }

    const status = dryRun ? "[dry-run]" : "[migrated]";
    console.log(`${status} ${filePath}: ${changed} replaced, ${skipped} skipped`);
    totalChanged += changed;
    totalSkipped += skipped;
  }

  console.log(`\n[migrate-tokens] Total: ${totalChanged} replaced, ${totalSkipped} skipped`);
  if (dryRun) {
    console.log("[migrate-tokens] Dry run — no files were modified.");
  }
}

main();
