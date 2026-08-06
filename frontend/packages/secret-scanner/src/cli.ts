/**
 * JSON stdin/stdout bridge for repository-local privacy scans.
 * It reuses canonical secret and PII patterns without returning matched values.
 * Input is a single `{ "text": string }` object.
 * Output contains status, finding count, finding types, and optionally redacted text.
 * Architecture: docs/specs/narrated-spec-demonstration-videos/spec.yml.
 */

import { SecretScanner } from "./scanner.ts";


let stdin = "";
for await (const chunk of process.stdin) {
  stdin += chunk.toString();
}
const input = JSON.parse(stdin) as {
  text?: unknown;
  knownSecrets?: Array<{ name?: unknown; value?: unknown }>;
  redact?: unknown;
};
if (typeof input.text !== "string") {
  throw new TypeError("Input field text must be a string");
}

const scanner = new SecretScanner({ enableRegistryDetection: true });
for (const item of input.knownSecrets ?? []) {
  if (typeof item.name === "string" && typeof item.value === "string") {
    scanner.addSecret(item.value, item.name, "process", "GENERIC_SECRET");
  }
}
const result = scanner.redact(input.text);
const types = [...new Set(result.mappings.map((mapping) => mapping.type))].sort();
let safeRedacted = result.redacted;
if (input.redact === true) {
  result.mappings.forEach((mapping, index) => {
    safeRedacted = safeRedacted
      .split(mapping.placeholder)
      .join(`[REDACTED_${mapping.type}_${index + 1}]`);
  });
}
process.stdout.write(JSON.stringify({
  status: types.length > 0 ? "failed" : "passed",
  count: result.mappings.length,
  types,
  ...(input.redact === true ? { redacted: safeRedacted } : {}),
}));
