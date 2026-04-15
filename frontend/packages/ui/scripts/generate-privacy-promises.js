#!/usr/bin/env node
// frontend/packages/ui/scripts/generate-privacy-promises.js
//
// Build step that mirrors shared/docs/privacy_promises.yml into a typed
// TypeScript module consumed by frontend/packages/ui/src/legal/buildLegalContent.ts.
//
// We generate a small browser-safe module instead of parsing YAML at runtime —
// the registry is a build-time artifact, so the browser never ships a YAML
// parser. Each emitted entry includes only what the legal content builder
// needs (id, i18n key, severity, surfaced_in_policy flag).
//
// Source of truth: /shared/docs/privacy_promises.yml
// Architecture doc: /home/superdev/.claude/plans/fuzzy-sauteeing-pancake.md (Phase 2)
// Meta-test: backend/tests/test_privacy_promises.py validates registry shape.
//
// Usage: `npm run generate-privacy-promises` (wired into `prepare` + `build`).

import { readFileSync, writeFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";
import yaml from "yaml";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// Repo-relative paths
const REGISTRY_PATH = resolve(
  __dirname,
  "../../../../shared/docs/privacy_promises.yml",
);
const OUTPUT_PATH = resolve(
  __dirname,
  "../src/legal/privacyPromises.generated.ts",
);

function main() {
  const raw = readFileSync(REGISTRY_PATH, "utf-8");
  const data = yaml.parse(raw);

  if (!data || !Array.isArray(data.promises)) {
    console.error(
      `[generate-privacy-promises] Registry at ${REGISTRY_PATH} is missing a 'promises' array.`,
    );
    process.exit(1);
  }

  const entries = data.promises.map((p) => ({
    id: p.id,
    i18n_key: p.i18n_key,
    category: p.category,
    severity: p.severity,
    verification: p.verification,
    surfaced_in_policy: Boolean(p.surfaced_in_policy),
    gdpr_articles: Array.isArray(p.gdpr_articles) ? p.gdpr_articles : [],
  }));

  // Validate: every entry has required fields
  for (const e of entries) {
    if (!e.id || !e.i18n_key) {
      console.error(
        `[generate-privacy-promises] Malformed entry (missing id/i18n_key): ${JSON.stringify(
          e,
        )}`,
      );
      process.exit(1);
    }
  }

  const lines = [
    "// frontend/packages/ui/src/legal/privacyPromises.generated.ts",
    "// ",
    "// AUTO-GENERATED from /shared/docs/privacy_promises.yml by",
    "// frontend/packages/ui/scripts/generate-privacy-promises.js",
    "// DO NOT EDIT BY HAND — run `npm run generate-privacy-promises` instead.",
    "",
    "export interface PrivacyPromise {",
    "  readonly id: string;",
    "  readonly i18n_key: string;",
    "  readonly category: string;",
    "  readonly severity: string;",
    "  readonly verification: string;",
    "  readonly surfaced_in_policy: boolean;",
    "  readonly gdpr_articles: readonly string[];",
    "}",
    "",
    `export const PRIVACY_PROMISES_VERSION: number = ${Number(
      data.version ?? 1,
    )};`,
    "",
    "export const PRIVACY_PROMISES: readonly PrivacyPromise[] = [",
    ...entries.map(
      (e) =>
        `  ${JSON.stringify(e)},`,
    ),
    "] as const;",
    "",
    "export const SURFACED_PRIVACY_PROMISES: readonly PrivacyPromise[] =",
    "  PRIVACY_PROMISES.filter((p) => p.surfaced_in_policy);",
    "",
  ];

  writeFileSync(OUTPUT_PATH, lines.join("\n"), "utf-8");
  console.log(
    `[generate-privacy-promises] Wrote ${entries.length} promise(s) to ${OUTPUT_PATH}`,
  );
}

main();
