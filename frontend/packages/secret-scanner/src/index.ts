// frontend/packages/secret-scanner/src/index.ts
/**
 * @file Public API for the @openmates/secret-scanner package.
 *
 * Provides secret detection, tokenization (redaction), and restoration
 * for both CLI terminal output and web app file processing.
 *
 * Key features:
 * - Registry-based scanning: Aho-Corasick automaton for known secret values
 *   (from .env files, process env, Settings & Memories personal data entries)
 * - Pattern-based scanning: Vendor-specific regex patterns (OpenAI, AWS, GitHub, etc.)
 *   ported from piiDetectionService.ts with proven low false-positive rates
 * - Suffix-based placeholder tokens: [OPENAI_KEY_f9d] — type + last 3 chars of value
 * - No generic high-entropy heuristic (avoids false positives on git SHAs, UUIDs, etc.)
 *
 * Architecture: docs/architecture/pii-protection.md
 * Planned: docs/planned/cli-package.md (Reversible Secret Tokenization)
 */

// Main scanner class
export { SecretScanner } from "./scanner.ts";

// Registry (for advanced usage / direct registry manipulation)
export { SecretRegistry } from "./registry.ts";

// Pattern definitions (for extending or testing)
export {
  SECRET_PATTERNS,
  getSecretSuffix,
  generatePlaceholder,
} from "./patterns.ts";

// .env file parser
export { parseEnvFile } from "./envParser.ts";

// Types
export type {
  SecretSource,
  SecretType,
  SecretRegistryEntry,
  SecretMapping,
  RedactResult,
  ScannerOptions,
  PersonalDataEntry,
} from "./types.ts";

export { SECRET_ENV_PATTERNS } from "./types.ts";
