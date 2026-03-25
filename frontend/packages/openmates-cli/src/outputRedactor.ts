// frontend/packages/openmates-cli/src/outputRedactor.ts
/**
 * @file CLI terminal output redactor — scans all output for secrets and
 * personal data before displaying to the user.
 *
 * Loads personal data entries (names, addresses, birthdays, custom text)
 * from the user's encrypted Settings & Memories (app_id="privacy",
 * item_type="personal_data_entry") and uses the @openmates/secret-scanner
 * to redact them from all terminal output.
 *
 * Also scans for vendor-specific API key patterns (OpenAI, AWS, GitHub, etc.)
 * using the same patterns as piiDetectionService.ts in the web app.
 *
 * The redactor is initialized once at CLI startup (when the user is logged in)
 * and applied to all text output — chat responses, embed content, error messages.
 *
 * Mirrors: piiDetectionService.ts Phase 2 (personal data detection)
 * Architecture: docs/architecture/pii-protection.md
 * Package: @openmates/secret-scanner
 */

import { SecretScanner } from "../../secret-scanner/src/scanner.ts";
import type {
  PersonalDataEntry,
  SecretMapping,
  RedactResult,
} from "../../secret-scanner/src/types.ts";
import type { DecryptedMemoryEntry } from "./client.js";

/** Privacy app ID used for personal data entries in Settings & Memories */
const PRIVACY_APP_ID = "privacy";
/** Memory type for personal data entries */
const PERSONAL_DATA_ITEM_TYPE = "personal_data_entry";

/**
 * CLI output redactor — wraps the SecretScanner with personal data
 * loading and session-scoped mapping management.
 *
 * Usage:
 * ```ts
 * const redactor = new OutputRedactor();
 * await redactor.initialize(client); // loads personal data from S&M
 * const clean = redactor.redact("Hello John, key is sk-proj-abc123");
 * // clean.redacted: "Hello [MY_NAME], key is [OPENAI_KEY_123]"
 * ```
 */
export class OutputRedactor {
  private scanner: SecretScanner;
  private initialized = false;
  /** Session-scoped mappings for restoration (accumulated across all redactions) */
  private sessionMappings: Map<string, SecretMapping> = new Map();

  constructor() {
    this.scanner = new SecretScanner({
      enablePatternDetection: true,
      enableRegistryDetection: true,
    });
  }

  /**
   * Initialize the redactor by loading personal data entries from
   * the user's encrypted Settings & Memories.
   *
   * Safe to call without a session — silently skips if not logged in.
   *
   * @param memories Pre-fetched decrypted memory entries (from client.listMemories())
   */
  initializeFromMemories(memories: DecryptedMemoryEntry[]): void {
    // Extract personal data entries (app_id="privacy", item_type="personal_data_entry")
    const personalEntries = memories.filter(
      (m) =>
        m.app_id === PRIVACY_APP_ID &&
        m.item_type === PERSONAL_DATA_ITEM_TYPE,
    );

    for (const entry of personalEntries) {
      const data = entry.data as Record<string, unknown>;
      const enabled = data.enabled as boolean;
      if (!enabled) continue;

      const textToHide = data.textToHide as string | undefined;
      const replaceWith = data.replaceWith as string | undefined;
      const type = data.type as string | undefined;

      if (!textToHide || !replaceWith) continue;

      const personalDataEntry: PersonalDataEntry = {
        id: entry.id,
        textToHide,
        replaceWith,
      };

      // For address entries, also add individual address lines
      if (type === "address") {
        const addressLines = data.addressLines as
          | Record<string, string>
          | undefined;
        if (addressLines) {
          const additionalTexts: string[] = [];
          for (const value of Object.values(addressLines)) {
            if (value && value.trim().length > 0) {
              additionalTexts.push(value);
            }
          }
          if (additionalTexts.length > 0) {
            personalDataEntry.additionalTexts = additionalTexts;
          }
        }
      }

      this.scanner.addPersonalData(personalDataEntry);
    }

    this.initialized = true;
  }

  /**
   * Redact secrets and personal data from text.
   *
   * @param text Text to scan
   * @returns Redacted text with placeholders
   */
  redact(text: string): string {
    if (!text || !this.initialized) return text;

    const result = this.scanner.redact(text);

    // Store mappings for this session (for potential restoration later)
    for (const mapping of result.mappings) {
      this.sessionMappings.set(mapping.placeholder, mapping);
    }

    return result.redacted;
  }

  /**
   * Redact and return both redacted text and mappings.
   * Used when we need to store mappings alongside message data.
   */
  redactWithMappings(text: string): RedactResult {
    if (!text || !this.initialized) {
      return { redacted: text, mappings: [] };
    }

    const result = this.scanner.redact(text);

    for (const mapping of result.mappings) {
      this.sessionMappings.set(mapping.placeholder, mapping);
    }

    return result;
  }

  /**
   * Restore placeholders back to original values.
   * Only uses mappings from this session (never from external sources).
   */
  restore(text: string): string {
    if (!text || this.sessionMappings.size === 0) return text;
    return this.scanner.restore(text, Array.from(this.sessionMappings.values()));
  }

  /** Whether the redactor has been initialized with personal data */
  get isInitialized(): boolean {
    return this.initialized;
  }

  /** Number of registered secrets + personal data entries */
  get entryCount(): number {
    return this.scanner.registrySize;
  }
}
