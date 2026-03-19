// frontend/packages/secret-scanner/src/scanner.ts
/**
 * @file Main secret scanner — combines registry-based (Aho-Corasick) and
 * pattern-based (regex) detection into a single redact/restore API.
 *
 * The scanner operates in two phases:
 * 1. Registry scan: Known secret values (from .env files, process env,
 *    personal data entries) matched via Aho-Corasick automaton in O(text_length).
 * 2. Pattern scan: Vendor-specific API key patterns (OpenAI, AWS, GitHub, etc.)
 *    matched via sequential regex — same proven approach as piiDetectionService.ts.
 *
 * No generic high-entropy heuristic is applied — only vendor-specific patterns
 * with proven low false-positive rates.
 *
 * Architecture: docs/architecture/pii-protection.md
 * Planned: docs/planned/cli-package.md (Reversible Secret Tokenization)
 */

import { SecretRegistry } from "./registry.ts";
import { SECRET_PATTERNS, generatePlaceholder } from "./patterns.ts";
import type {
  SecretMapping,
  RedactResult,
  ScannerOptions,
  PersonalDataEntry,
} from "./types.ts";

/**
 * Secret scanner that provides redact/restore functionality.
 *
 * Usage:
 * ```ts
 * const scanner = new SecretScanner();
 * scanner.addFromEnvFile({ OPENAI_API_KEY: "sk-proj-abc123" });
 * scanner.addPersonalData({ id: "1", textToHide: "John", replaceWith: "[MY_NAME]" });
 *
 * const { redacted, mappings } = scanner.redact("My key is sk-proj-abc123, signed John");
 * // redacted: "My key is [OPENAI_KEY_123], signed [MY_NAME]"
 *
 * const restored = scanner.restore(redacted, mappings);
 * // restored: "My key is sk-proj-abc123, signed John"
 * ```
 */
export class SecretScanner {
  private registry: SecretRegistry;
  private options: Required<ScannerOptions>;

  constructor(options: ScannerOptions = {}) {
    this.options = {
      minSecretLength: options.minSecretLength ?? 8,
      suffixLength: options.suffixLength ?? 3,
      enablePatternDetection: options.enablePatternDetection ?? true,
      enableRegistryDetection: options.enableRegistryDetection ?? true,
      personalDataEntries: options.personalDataEntries ?? [],
    };

    this.registry = new SecretRegistry(
      this.options.suffixLength,
      this.options.minSecretLength,
    );

    // Register initial personal data entries
    for (const entry of this.options.personalDataEntries) {
      this.registry.addPersonalData(entry);
    }
  }

  // ── Registry population ──────────────────────────────────────────────

  /**
   * Add secrets from parsed .env file content.
   */
  addFromEnvFile(vars: Record<string, string>): void {
    this.registry.addFromEnvFile(vars);
  }

  /**
   * Add secrets from process environment variables.
   */
  addFromProcessEnv(env?: Record<string, string | undefined>): void {
    this.registry.addFromProcessEnv(env);
  }

  /**
   * Add a personal data entry for substring detection.
   */
  addPersonalData(entry: PersonalDataEntry): void {
    this.registry.addPersonalData(entry);
  }

  /**
   * Add multiple personal data entries.
   */
  addPersonalDataEntries(entries: PersonalDataEntry[]): void {
    for (const entry of entries) {
      this.registry.addPersonalData(entry);
    }
  }

  /**
   * Add a single secret value to the registry.
   */
  addSecret(
    value: string,
    name: string,
    source: "env" | "aws" | "ssh" | "gcloud" | "process" | "settings" | "custom" = "custom",
    type: "ENV_VAR" | "GENERIC_SECRET" = "ENV_VAR",
  ): string | null {
    return this.registry.add(value, name, source, type);
  }

  // ── Redaction ────────────────────────────────────────────────────────

  /**
   * Redact all secrets in the given text.
   *
   * Runs both registry-based (Aho-Corasick) and pattern-based (regex) scans.
   * Registry matches take priority over pattern matches when they overlap.
   *
   * @param text Text to scan and redact
   * @returns Object with redacted text and mappings for restoration
   */
  redact(text: string): RedactResult {
    if (!text) return { redacted: text, mappings: [] };

    const allMappings: SecretMapping[] = [];
    const coveredRanges: Array<{ start: number; end: number }> = [];

    // Phase 1: Registry-based scan (Aho-Corasick)
    if (this.options.enableRegistryDetection && this.registry.size > 0) {
      const registryMappings = this.registry.findAll(text);
      for (const mapping of registryMappings) {
        // Find all occurrences of this match in the text and record ranges
        let searchFrom = 0;
        const searchText = text.toLowerCase();
        const matchLower = mapping.original.toLowerCase();

        while (searchFrom < searchText.length) {
          const idx = searchText.indexOf(matchLower, searchFrom);
          if (idx === -1) break;
          coveredRanges.push({ start: idx, end: idx + mapping.original.length });
          searchFrom = idx + mapping.original.length;
        }
        allMappings.push(mapping);
      }
    }

    // Phase 2: Pattern-based scan (regex)
    if (this.options.enablePatternDetection) {
      for (const pattern of SECRET_PATTERNS) {
        pattern.regex.lastIndex = 0;
        let match;

        while ((match = pattern.regex.exec(text)) !== null) {
          const matchText = match[0];
          const startIndex = match.index;
          const endIndex = startIndex + matchText.length;

          // Skip if overlapping with a registry match (registry takes priority)
          const overlaps = coveredRanges.some(
            (range) =>
              (startIndex >= range.start && startIndex < range.end) ||
              (endIndex > range.start && endIndex <= range.end) ||
              (startIndex <= range.start && endIndex >= range.end),
          );
          if (overlaps) continue;

          // Run validation if defined
          if (pattern.validate && !pattern.validate(matchText)) continue;

          // Check if this exact value is already in the registry
          // (avoid duplicate detection)
          const existing = this.registry.get(matchText);
          if (existing) continue;

          const placeholder = generatePlaceholder(
            pattern.placeholderPrefix,
            matchText,
            this.options.suffixLength,
          );

          allMappings.push({
            placeholder,
            original: matchText,
            type: pattern.type,
            source: "env", // Pattern-detected secrets don't have a known source
          });

          coveredRanges.push({ start: startIndex, end: endIndex });
        }
      }
    }

    // Apply replacements (sort by original length descending to replace longest first)
    let redacted = text;
    const sortedMappings = [...allMappings].sort(
      (a, b) => b.original.length - a.original.length,
    );

    for (const mapping of sortedMappings) {
      // Case-insensitive replacement for personal data
      if (mapping.type === "PERSONAL_DATA") {
        const regex = new RegExp(
          escapeRegExp(mapping.original),
          "gi",
        );
        redacted = redacted.replace(regex, mapping.placeholder);
      } else {
        // Exact replacement for secrets (case-sensitive)
        redacted = redacted.split(mapping.original).join(mapping.placeholder);
      }
    }

    return { redacted, mappings: allMappings };
  }

  // ── Restoration ──────────────────────────────────────────────────────

  /**
   * Restore placeholder tokens back to their original secret values.
   *
   * SECURITY NOTE: Only restore mappings that were created by this scanner
   * session's own redact() calls. Never restore tokens from external/untrusted
   * sources — an attacker could embed fake tokens to extract secrets.
   *
   * @param text Text containing placeholder tokens
   * @param mappings Mappings from a previous redact() call
   * @returns Text with placeholders replaced by original values
   */
  restore(text: string, mappings: SecretMapping[]): string {
    if (!text || !mappings || mappings.length === 0) return text;

    let result = text;
    for (const mapping of mappings) {
      result = result.split(mapping.placeholder).join(mapping.original);
    }
    return result;
  }

  // ── Utility ──────────────────────────────────────────────────────────

  /** Number of secrets in the registry */
  get registrySize(): number {
    return this.registry.size;
  }

  /** Clear all registered secrets */
  clear(): void {
    this.registry.clear();
  }
}

/**
 * Escape special regex characters in a string.
 */
function escapeRegExp(string: string): string {
  return string.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
