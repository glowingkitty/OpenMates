// frontend/packages/secret-scanner/src/registry.ts
/**
 * @file Secret registry — in-memory store of known secret values.
 *
 * Builds a registry from environment files, process env vars, and
 * user-defined personal data entries. Each secret value is mapped to
 * a placeholder token for redaction and later restoration.
 *
 * The registry also pre-computes common encoded variants (base64,
 * URL-encoded) so the same secret is caught regardless of encoding.
 *
 * Uses Aho-Corasick automaton for O(text_length) multi-pattern matching
 * against all known secret values simultaneously.
 *
 * Architecture: docs/architecture/pii-protection.md
 * Planned: docs/architecture/apps/cli-package.md (Reversible Secret Tokenization)
 */

import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const AhoCorasick = require("ahocorasick") as new (keywords: string[]) => { search: (text: string) => Array<[number, string[]]> };
import type {
  SecretRegistryEntry,
  SecretSource,
  SecretType,
  PersonalDataEntry,
  SecretMapping,
} from "./types.ts";
import { SECRET_ENV_PATTERNS } from "./types.ts";
import { getSecretSuffix } from "./patterns.ts";

/**
 * Minimum secret value length for registry inclusion.
 * Values shorter than this are excluded to avoid false positives
 * on common short strings like "true", "false", "3306", etc.
 */
const MIN_SECRET_LENGTH = 8;

/**
 * In-memory registry of known secret values and their tokens.
 *
 * Maps plaintext values (and their encoded variants) to registry entries.
 * The Aho-Corasick automaton is rebuilt whenever the registry changes.
 */
export class SecretRegistry {
  /** Map from plaintext value → registry entry */
  private entries: Map<string, SecretRegistryEntry> = new Map();

  /** Map from encoded variant → original plaintext value */
  private variantToOriginal: Map<string, string> = new Map();

  /** Aho-Corasick automaton for multi-pattern matching (rebuilt on changes) */
  private automaton: { search: (text: string) => Array<[number, string[]]> } | null = null;

  /** Suffix length for placeholder tokens */
  private suffixLength: number;

  /** Minimum value length for inclusion */
  private minLength: number;

  /** Track placeholder suffixes to detect collisions */
  private usedPlaceholders: Map<string, string> = new Map();

  constructor(suffixLength = 3, minLength = MIN_SECRET_LENGTH) {
    this.suffixLength = suffixLength;
    this.minLength = minLength;
  }

  /**
   * Add a secret value to the registry.
   * Generates a placeholder token and pre-computes encoded variants.
   *
   * @param value The plaintext secret value
   * @param name Variable/key name (e.g., "OPENAI_API_KEY")
   * @param source Where the secret was found
   * @param type Detection type
   * @returns The generated placeholder token, or null if value is too short
   */
  add(
    value: string,
    name: string,
    source: SecretSource,
    type: SecretType,
  ): string | null {
    if (!value || value.length < this.minLength) return null;

    // Skip if already registered
    if (this.entries.has(value)) {
      return this.entries.get(value)!.token;
    }

    // Generate placeholder prefix from the variable name
    const prefix = this.getPlaceholderPrefix(name, type);
    let token = `[${prefix}_${getSecretSuffix(value, this.suffixLength)}]`;

    // Handle suffix collisions — if two different secrets produce the same
    // placeholder, extend the suffix for disambiguation
    const existing = this.usedPlaceholders.get(token);
    if (existing && existing !== value) {
      // Try progressively longer suffixes
      for (let len = this.suffixLength + 1; len <= 8; len++) {
        const candidate = `[${prefix}_${getSecretSuffix(value, len)}]`;
        const candidateExisting = this.usedPlaceholders.get(candidate);
        if (!candidateExisting || candidateExisting === value) {
          token = candidate;
          break;
        }
      }
    }

    const entry: SecretRegistryEntry = {
      value,
      token,
      source,
      name,
      type,
      length: value.length,
    };

    this.entries.set(value, entry);
    this.usedPlaceholders.set(token, value);

    // Pre-compute encoded variants
    this.addVariants(value);

    // Invalidate automaton (rebuilt lazily on next scan)
    this.automaton = null;

    return token;
  }

  /**
   * Add a personal data entry to the registry.
   * Personal data entries use their own placeholder format.
   */
  addPersonalData(entry: PersonalDataEntry): void {
    const textsToAdd: string[] = [];

    if (entry.textToHide && entry.textToHide.trim().length > 0) {
      textsToAdd.push(entry.textToHide);
    }
    if (entry.additionalTexts) {
      for (const text of entry.additionalTexts) {
        if (text && text.trim().length > 0) {
          textsToAdd.push(text);
        }
      }
    }

    for (const text of textsToAdd) {
      // Personal data uses its own placeholder from the entry
      const placeholder = entry.replaceWith.startsWith("[")
        ? entry.replaceWith
        : `[${entry.replaceWith}]`;

      const regEntry: SecretRegistryEntry = {
        value: text,
        token: placeholder,
        source: "settings",
        name: entry.id,
        type: "PERSONAL_DATA",
        length: text.length,
      };

      // Personal data entries may be shorter than MIN_SECRET_LENGTH
      // (e.g., a 4-letter first name) — allow them regardless of length
      this.entries.set(text, regEntry);
      this.usedPlaceholders.set(placeholder, text);

      // Also register lowercase variant for case-insensitive matching
      const lower = text.toLowerCase();
      if (lower !== text) {
        this.variantToOriginal.set(lower, text);
      }
    }

    // Invalidate automaton
    this.automaton = null;
  }

  /**
   * Populate registry from environment variables.
   * Filters process.env for variable names matching SECRET_ENV_PATTERNS.
   */
  addFromProcessEnv(env: Record<string, string | undefined> = process.env): void {
    for (const [key, value] of Object.entries(env)) {
      if (!value || value.length < this.minLength) continue;

      const isSecret = SECRET_ENV_PATTERNS.some((pattern) =>
        pattern.test(key),
      );
      if (isSecret) {
        this.add(value, key, "process", "ENV_VAR");
      }
    }
  }

  /**
   * Populate registry from parsed .env file content.
   * Expects an object of { KEY: VALUE } pairs.
   */
  addFromEnvFile(
    vars: Record<string, string>,
    source: SecretSource = "env",
  ): void {
    for (const [name, value] of Object.entries(vars)) {
      if (!value || value.length < this.minLength) continue;
      this.add(value, name, source, "ENV_VAR");
    }
  }

  /**
   * Find all known secrets in the given text using Aho-Corasick.
   *
   * @param text Text to scan
   * @returns Array of secret mappings for all matches found
   */
  findAll(text: string): SecretMapping[] {
    if (this.entries.size === 0) return [];

    // Build automaton lazily
    if (!this.automaton) {
      this.buildAutomaton();
    }

    const results = this.automaton!.search(text);
    const mappings: SecretMapping[] = [];
    const coveredRanges: Array<{ start: number; end: number }> = [];

    // Aho-Corasick returns [endIndex, [matchedStrings...]]
    // Sort by match length descending to prefer longer matches
    const sortedResults: Array<{
      endIndex: number;
      match: string;
    }> = [];

    for (const result of results) {
      const endIdx = result[0] as number;
      const matches = result[1] as string[];
      for (const match of matches) {
        sortedResults.push({ endIndex: endIdx, match });
      }
    }

    // Sort by match length descending (longer matches first to avoid partial overlaps)
    sortedResults.sort((a, b) => b.match.length - a.match.length);

    for (const { endIndex, match } of sortedResults) {
      const startIndex = endIndex - match.length + 1;

      // Check for overlap with already-matched ranges
      const overlaps = coveredRanges.some(
        (range) =>
          (startIndex >= range.start && startIndex < range.end) ||
          (endIndex >= range.start && endIndex < range.end) ||
          (startIndex <= range.start && endIndex >= range.end),
      );
      if (overlaps) continue;

      // Resolve variants back to original value
      const originalValue = this.variantToOriginal.get(match) ?? match;
      const entry = this.entries.get(originalValue);

      if (entry) {
        mappings.push({
          placeholder: entry.token,
          original: match, // Use the actual matched text (may be an encoded variant)
          type: entry.type,
          source: entry.source,
        });
        coveredRanges.push({ start: startIndex, end: endIndex + 1 });
      }
    }

    return mappings;
  }

  /**
   * Look up a registry entry by its plaintext value.
   */
  get(value: string): SecretRegistryEntry | undefined {
    return this.entries.get(value);
  }

  /**
   * Look up a registry entry by its placeholder token.
   */
  getByToken(token: string): SecretRegistryEntry | undefined {
    const value = this.usedPlaceholders.get(token);
    if (!value) return undefined;
    return this.entries.get(value);
  }

  /** Number of registered secrets (excluding variants) */
  get size(): number {
    return this.entries.size;
  }

  /** Clear all entries and invalidate the automaton */
  clear(): void {
    this.entries.clear();
    this.variantToOriginal.clear();
    this.usedPlaceholders.clear();
    this.automaton = null;
  }

  // ── Private helpers ──────────────────────────────────────────────────

  /**
   * Pre-compute encoded variants of a secret value.
   * Each variant maps back to the original value for restoration.
   */
  private addVariants(value: string): void {
    // Base64 encoded
    try {
      const b64 = Buffer.from(value).toString("base64");
      if (b64 !== value && b64.length >= this.minLength) {
        this.variantToOriginal.set(b64, value);
      }
    } catch {
      // Skip if encoding fails
    }

    // URL-encoded
    try {
      const urlEncoded = encodeURIComponent(value);
      if (urlEncoded !== value) {
        this.variantToOriginal.set(urlEncoded, value);
      }
    } catch {
      // Skip if encoding fails
    }

    // JSON-escaped (for values with special chars)
    const jsonEscaped = JSON.stringify(value).slice(1, -1); // Remove wrapping quotes
    if (jsonEscaped !== value) {
      this.variantToOriginal.set(jsonEscaped, value);
    }
  }

  /**
   * Build the Aho-Corasick automaton from all registered values and variants.
   */
  private buildAutomaton(): void {
    const patterns: string[] = [];

    // Add all original values
    for (const value of this.entries.keys()) {
      patterns.push(value);
    }

    // Add all encoded variants
    for (const variant of this.variantToOriginal.keys()) {
      patterns.push(variant);
    }

    // Personal data: add lowercase variants for case-insensitive matching
    for (const entry of this.entries.values()) {
      if (entry.type === "PERSONAL_DATA") {
        const lower = entry.value.toLowerCase();
        if (lower !== entry.value && !this.variantToOriginal.has(lower)) {
          this.variantToOriginal.set(lower, entry.value);
          patterns.push(lower);
        }
      }
    }

    this.automaton = new AhoCorasick(patterns);
  }

  /**
   * Generate a placeholder prefix from the variable name and type.
   * For known types, uses the standard prefix. For generic env vars,
   * derives a clean prefix from the variable name.
   */
  private getPlaceholderPrefix(name: string, type: SecretType): string {
    // Known types have standard prefixes
    const typeToPrefix: Partial<Record<SecretType, string>> = {
      AWS_ACCESS_KEY: "AWS_KEY",
      AWS_SECRET_KEY: "AWS_SECRET",
      OPENAI_KEY: "OPENAI_KEY",
      ANTHROPIC_KEY: "ANTHROPIC_KEY",
      GITHUB_PAT: "GITHUB_TOKEN",
      STRIPE_KEY: "STRIPE_KEY",
      GOOGLE_API_KEY: "GOOGLE_KEY",
      SLACK_TOKEN: "SLACK_TOKEN",
      TWILIO_KEY: "TWILIO_KEY",
      SENDGRID_KEY: "SENDGRID_KEY",
      AZURE_KEY: "AZURE_KEY",
      HUGGINGFACE_KEY: "HF_TOKEN",
      DATABRICKS_TOKEN: "DATABRICKS_TOKEN",
      FIREBASE_KEY: "FIREBASE_KEY",
      GENERIC_SECRET: "SECRET",
      PRIVATE_KEY: "PRIVATE_KEY",
      JWT: "JWT_TOKEN",
    };

    if (typeToPrefix[type]) return typeToPrefix[type]!;

    // For ENV_VAR type, derive from the variable name
    // e.g., "OPENAI_API_KEY" → "OPENAI_API_KEY", "database_url" → "DATABASE_URL"
    return name.toUpperCase().replace(/[^A-Z0-9_]/g, "_");
  }
}
