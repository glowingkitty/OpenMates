#!/usr/bin/env node
// frontend/packages/ui/scripts/generate-training-policies.js
//
// Build step that mirrors shared/docs/provider_training_policies.yml into a
// typed TypeScript module consumed by buildLegalContent.ts to render the
// per-provider model training disclosure table in the public privacy policy.
//
// Source of truth: /shared/docs/provider_training_policies.yml
// Usage: `npm run generate-training-policies` (wired into `prepare` + `build`).

import { readFileSync, writeFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";
import yaml from "yaml";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const REGISTRY_PATH = resolve(
  __dirname,
  "../../../../shared/docs/provider_training_policies.yml",
);
const OUTPUT_PATH = resolve(
  __dirname,
  "../src/legal/trainingPolicies.generated.ts",
);

function main() {
  const raw = readFileSync(REGISTRY_PATH, "utf-8");
  const data = yaml.parse(raw);

  if (!data || !data.providers) {
    console.error(
      `[generate-training-policies] Registry at ${REGISTRY_PATH} is missing a 'providers' map.`,
    );
    process.exit(1);
  }

  const entries = Object.entries(data.providers).map(([key, p]) => ({
    id: key,
    status: p.status,
    provider_group: p.provider_group,
    policy_url: p.policy_url,
    terms_url: p.terms_url || null,
    source_document: p.source_document,
    quote: (p.quote || "").trim(),
    mechanism: (p.mechanism || "").trim(),
    notes: p.notes ? p.notes.trim() : null,
    opted_out_date: p.opted_out_date || null,
    last_verified: p.last_verified,
  }));

  // Validate required fields
  for (const e of entries) {
    if (!e.id || !e.status || !e.last_verified) {
      console.error(
        `[generate-training-policies] Malformed entry (missing id/status/last_verified): ${JSON.stringify(e)}`,
      );
      process.exit(1);
    }
  }

  const lines = [
    "// frontend/packages/ui/src/legal/trainingPolicies.generated.ts",
    "//",
    "// AUTO-GENERATED from /shared/docs/provider_training_policies.yml by",
    "// frontend/packages/ui/scripts/generate-training-policies.js",
    "// DO NOT EDIT BY HAND — run `npm run generate-training-policies` instead.",
    "",
    "export interface ProviderTrainingPolicy {",
    "  readonly id: string;",
    '  readonly status: "no_training" | "no_training_opt_out" | "limited_use";',
    '  readonly provider_group: "ai_models" | "image_generation";',
    "  readonly policy_url: string;",
    "  readonly terms_url: string | null;",
    "  readonly source_document: string;",
    "  readonly quote: string;",
    "  readonly mechanism: string;",
    "  readonly notes: string | null;",
    "  readonly opted_out_date: string | null;",
    "  readonly last_verified: string;",
    "}",
    "",
    `export const TRAINING_POLICIES_VERSION: number = ${Number(data.version ?? 1)};`,
    `export const TRAINING_POLICIES_LAST_AUDIT: string = ${JSON.stringify(data.last_full_audit)};`,
    "",
    "export const PROVIDER_TRAINING_POLICIES: readonly ProviderTrainingPolicy[] = [",
    ...entries.map((e) => `  ${JSON.stringify(e)},`),
    "] as const;",
    "",
  ];

  writeFileSync(OUTPUT_PATH, lines.join("\n"), "utf-8");
  console.log(
    `[generate-training-policies] Wrote ${entries.length} provider(s) to ${OUTPUT_PATH}`,
  );
}

main();
