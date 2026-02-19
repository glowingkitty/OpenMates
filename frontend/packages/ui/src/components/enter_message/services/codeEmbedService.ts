/**
 * Code Embed Service
 *
 * Creates proper embed entries for code blocks pasted by users or dropped as files.
 * Follows the same pattern as urlMetadataService.ts for consistency.
 *
 * PII Protection Architecture:
 * - Before TOON-encoding, PII is detected in the code content using piiDetectionService
 * - The code stored in the TOON payload uses placeholders (e.g. [EMAIL_1], [AWS_KEY_1])
 * - PII mappings ({placeholder, original, type}[]) are stored separately in EmbedStore
 *   under key `embed_pii:{embed_id}`, encrypted with the master key
 * - This separation ensures that:
 *   1. The LLM/server only ever sees redacted code
 *   2. Share links (which use the embed key, not the master key) never expose PII mappings
 *   3. Only the owner can restore originals — recipients of shared embeds see placeholders
 *
 * Flow:
 * 1. User pastes or drops a code file
 * 2. PII is detected in the code content
 * 3. Placeholders replace originals in the code
 * 4. Embed TOON content is created with the redacted code
 * 5. PII mappings are stored separately under master-key encryption
 * 6. Embed is stored in EmbedStore; returns embed reference for insertion into message
 * 7. When message is sent, embed (with placeholders) is sent to server
 * 8. The embedPIIStore merges embed-level mappings for display toggling
 */

import { embedStore } from "../../../services/embedStore";
import { generateUUID } from "../../../message_parsing/utils";
import { createEmbedReferenceBlock } from "./urlMetadataService";
import { encode as toonEncode } from "@toon-format/toon";
import {
  detectPII,
  replacePIIWithPlaceholders,
  createPIIMappingsForStorage,
  type PIIMappingForStorage,
  type PIIDetectionOptions,
  type PersonalDataForDetection,
} from "./piiDetectionService";
import {
  personalDataStore,
  type PIIDetectionSettings,
} from "../../../stores/personalDataStore";
import { get } from "svelte/store";
import type { EmbedType } from "../../../message_parsing/types";

/**
 * Result of creating a code embed
 */
export interface CodeEmbedCreationResult {
  /** Unique identifier for the embed */
  embed_id: string;
  /** Embed type (always 'code' for this service) */
  type: "code";
  /** Markdown embed reference block to insert into message content */
  embedReference: string;
  /** Number of PII items that were redacted (0 if none) */
  piiRedactedCount: number;
}

/**
 * Build PII detection options from the user's current privacy settings.
 * Respects the master toggle and per-category toggles in personalDataStore.
 * User-defined personal data entries (names, addresses, etc.) are included.
 *
 * Returns null if PII detection is disabled by the user.
 */
function buildCodePIIDetectionOptions(): PIIDetectionOptions | null {
  try {
    const piiSettings: PIIDetectionSettings = get(personalDataStore.settings);

    // Respect the master toggle — if disabled, skip all detection
    if (!piiSettings.masterEnabled) {
      return null;
    }

    // Build set of disabled categories from user's per-category toggles
    const disabledCategories = new Set<string>();
    for (const [category, enabled] of Object.entries(piiSettings.categories)) {
      if (!enabled) disabledCategories.add(category);
    }

    // Get user-defined personal data entries (names, addresses, etc.)
    // NOTE: User-specific entries are kept client-side only (zero-knowledge architecture).
    // TODO: In a future iteration, consider server-side user-specific PII detection
    //       for document processing (pdf, docx, xlsx). Requires careful privacy architecture
    //       to avoid leaking user's personal data definitions to the server.
    const enabledPersonalEntries = get(personalDataStore.enabledEntries);
    const personalDataEntries: PersonalDataForDetection[] =
      enabledPersonalEntries.map((entry) => {
        const result: PersonalDataForDetection = {
          id: entry.id,
          textToHide: entry.textToHide,
          replaceWith: entry.replaceWith,
        };
        // For address entries, include individual lines as additional search texts
        if (entry.type === "address" && entry.addressLines) {
          const additionalTexts: string[] = [];
          if (entry.addressLines.street)
            additionalTexts.push(entry.addressLines.street);
          if (entry.addressLines.city)
            additionalTexts.push(entry.addressLines.city);
          result.additionalTexts = additionalTexts;
        }
        return result;
      });

    return {
      disabledCategories,
      personalDataEntries,
      // No excludedIds for embed PII — the user cannot click-to-exclude in the embed flow
      // (unlike MessageInput where highlights are interactive)
    };
  } catch (error) {
    // If reading settings fails, skip detection rather than crashing
    console.warn(
      "[codeEmbedService] Could not read PII settings, skipping detection:",
      error,
    );
    return null;
  }
}

/**
 * Store PII mappings for an embed separately from the embed content.
 *
 * Why separate storage:
 * - The embed TOON content (stored in Directus, shared via share link) only contains
 *   the redacted code — never the PII mappings.
 * - PII mappings are stored under the master key (not the embed key), so sharing
 *   the embed key (for share links) never exposes the originals.
 * - Only the embed owner, who has the master key, can restore originals for display.
 *
 * @param embedId - The embed's unique ID
 * @param piiMappings - Array of {placeholder, original, type} mappings
 */
async function storeEmbedPIIMappings(
  embedId: string,
  piiMappings: PIIMappingForStorage[],
): Promise<void> {
  if (piiMappings.length === 0) return;

  const piiKey = `embed_pii:${embedId}`;
  const piiData = {
    embed_id: embedId,
    pii_mappings: piiMappings,
    created_at: Date.now(),
  };

  try {
    // Store using master-key encryption (same as all other embedStore.put() entries)
    await embedStore.put(piiKey, piiData, "code-code" as EmbedType);
    console.info(
      "[codeEmbedService] Stored PII mappings for embed:",
      embedId,
      `(${piiMappings.length} mappings)`,
    );
  } catch (error) {
    // Log but don't block — the redacted embed still works, just no owner-side restoration
    console.error(
      "[codeEmbedService] Failed to store PII mappings for embed:",
      embedId,
      error,
    );
  }
}

/**
 * Load PII mappings for an embed from separate storage.
 * Returns an empty array if no mappings exist (embed has no PII, or mappings lost).
 *
 * @param embedId - The embed's unique ID
 */
export async function loadEmbedPIIMappings(
  embedId: string,
): Promise<PIIMappingForStorage[]> {
  const piiKey = `embed_pii:${embedId}`;
  try {
    const piiData = await embedStore.get(piiKey);
    if (
      piiData &&
      piiData.pii_mappings &&
      Array.isArray(piiData.pii_mappings)
    ) {
      return piiData.pii_mappings as PIIMappingForStorage[];
    }
  } catch (error) {
    console.debug(
      "[codeEmbedService] No PII mappings found for embed:",
      embedId,
      error,
    );
  }
  return [];
}

/**
 * Creates a proper embed from pasted or file-loaded code/text content.
 *
 * PII-aware flow:
 * 1. Run PII detection on the code content (respects user's privacy settings)
 * 2. Replace PII with placeholders in the code
 * 3. Create TOON embed content with the redacted code
 * 4. Store PII mappings separately (master-key encrypted, not in TOON)
 * 5. Store the embed in EmbedStore
 * 6. Return the embed reference for insertion into message content
 *
 * @param content The code/text content to embed
 * @param language The language/format identifier (e.g., 'markdown', 'python', 'text')
 * @param filename Optional filename for the code
 * @returns CodeEmbedCreationResult with embed_id, markdown reference, and PII count
 */
export async function createCodeEmbed(
  content: string,
  language: string = "text",
  filename?: string,
): Promise<CodeEmbedCreationResult> {
  // Generate unique embed_id
  const embed_id = generateUUID();

  console.debug("[codeEmbedService] Creating code embed:", {
    embed_id,
    language,
    lineCount: content.split("\n").length,
    contentLength: content.length,
    filename: filename || "none",
  });

  // ── PII Detection & Redaction ────────────────────────────────────────────
  // Detect sensitive data in the code content and replace with placeholders.
  // This ensures the LLM/server only ever sees redacted code.
  let codeContent = content;
  let piiMappingsForStorage: PIIMappingForStorage[] = [];

  const detectionOptions = buildCodePIIDetectionOptions();
  if (detectionOptions && content.length >= 6) {
    try {
      const piiMatches = detectPII(content, detectionOptions);

      if (piiMatches.length > 0) {
        console.debug(
          "[codeEmbedService] Detected PII in code embed, redacting:",
          piiMatches.map((m) => ({
            type: m.type,
            placeholder: m.placeholder,
            // Don't log the actual match value for security
            matchLength: m.match.length,
          })),
        );

        // Replace PII originals with placeholders in the code
        codeContent = replacePIIWithPlaceholders(content, piiMatches);

        // Create storage mappings ({placeholder, original, type}) for owner-side restoration
        piiMappingsForStorage = createPIIMappingsForStorage(piiMatches);

        console.info(
          `[codeEmbedService] Redacted ${piiMatches.length} PII item(s) in code embed ${embed_id}`,
        );
      }
    } catch (error) {
      console.error(
        "[codeEmbedService] PII detection failed for code embed:",
        error,
      );
      // Continue with unredacted content — log the failure but don't block the embed
    }
  }

  // ── Build TOON Content ───────────────────────────────────────────────────
  // The TOON content contains the REDACTED code (with placeholders).
  // pii_mappings are stored SEPARATELY — never embedded in the TOON.
  // This ensures that sharing the embed key (via a share link) does NOT expose
  // PII originals; only the owner's master key can decrypt the pii_mappings.
  const lineCount = codeContent.split("\n").length;
  const embedContent = {
    type: "code",
    language: language,
    code: codeContent, // Redacted code — placeholders where PII was
    filename: filename || null,
    status: "finished",
    line_count: lineCount,
  };

  // Encode as TOON for storage efficiency (30-60% savings vs JSON)
  let toonContent: string;
  if (toonEncode) {
    try {
      toonContent = toonEncode(embedContent);
      console.debug("[codeEmbedService] Encoded embed as TOON:", {
        embed_id,
        jsonSize: JSON.stringify(embedContent).length,
        toonSize: toonContent.length,
        savings: `${Math.round((1 - toonContent.length / JSON.stringify(embedContent).length) * 100)}%`,
      });
    } catch (error) {
      // Fallback to JSON if TOON encoding fails
      console.warn(
        "[codeEmbedService] TOON encoding failed, using JSON fallback:",
        error,
      );
      toonContent = JSON.stringify(embedContent);
    }
  } else {
    // TOON not available, use JSON
    toonContent = JSON.stringify(embedContent);
  }

  // Create text preview (first line or language indicator)
  const textPreview = filename
    ? `${filename}${language ? ` (${language})` : ""}`
    : language
      ? `${lineCount} lines, ${language}`
      : `${lineCount} lines`;

  // Create embed data structure matching what the embed system expects
  const now = Date.now();
  const embedData = {
    embed_id,
    type: "code-code", // Frontend embed type for code
    status: "finished",
    content: toonContent,
    text_preview: textPreview,
    createdAt: now,
    updatedAt: now,
  };

  // ── Store Embed in EmbedStore ────────────────────────────────────────────
  // The embed content (with redacted code) is stored encrypted with the master key.
  try {
    await embedStore.put(`embed:${embed_id}`, embedData, "code-code");
    console.info(
      "[codeEmbedService] Stored code embed in EmbedStore:",
      embed_id,
    );
  } catch (error) {
    console.error(
      "[codeEmbedService] Failed to store embed in EmbedStore:",
      error,
    );
    // Continue anyway - embed can still be sent with message
  }

  // ── Store PII Mappings Separately ───────────────────────────────────────
  // PII mappings are stored under a separate key (`embed_pii:{embed_id}`) using
  // master-key encryption. This ensures:
  // - Share links (which provide the embed key) cannot decrypt PII mappings
  // - Only the owner (who has the master key) can restore originals
  if (piiMappingsForStorage.length > 0) {
    await storeEmbedPIIMappings(embed_id, piiMappingsForStorage);
  }

  // Create the embed reference JSON block
  // Note: For code embeds we don't include a URL fallback since there's no URL
  const embedReference = createEmbedReferenceBlock("code", embed_id);

  return {
    embed_id,
    type: "code",
    embedReference,
    piiRedactedCount: piiMappingsForStorage.length,
  };
}

/**
 * Options for creating a code embed from pasted text
 */
export interface PastedTextOptions {
  /** The pasted text content */
  text: string;
  /**
   * VS Code editor data from clipboard (JSON string from 'vscode-editor-data' MIME type)
   * Contains language/mode information when code is copied from VS Code
   */
  vsCodeEditorData?: string | null;
  /**
   * Explicit language override. If provided, takes precedence over vsCodeEditorData.
   */
  language?: string;
}

/**
 * Detects the programming language from VS Code clipboard data.
 * VS Code stores language info in the 'vscode-editor-data' MIME type as JSON with a 'mode' field.
 *
 * @param vsCodeEditorData The raw string from clipboardData.getData('vscode-editor-data')
 * @returns The detected language mode, or null if not available
 */
export function detectLanguageFromVSCode(
  vsCodeEditorData: string | null | undefined,
): string | null {
  if (!vsCodeEditorData) {
    return null;
  }

  try {
    const data = JSON.parse(vsCodeEditorData);
    const mode = data?.mode;

    if (mode && typeof mode === "string") {
      console.debug("[codeEmbedService] Detected VS Code language:", mode);
      return mode;
    }
  } catch (error) {
    console.warn(
      "[codeEmbedService] Failed to parse vscode-editor-data:",
      error,
    );
  }

  return null;
}

/**
 * Heuristic-based language detection from code content.
 * Analyzes the text for common patterns like shebangs, imports, and syntax.
 *
 * @param text The code/text content to analyze
 * @returns The detected language, or null if no confident match
 */
export function detectLanguageFromContent(text: string): string | null {
  const firstLine = text.split("\n")[0].trim();
  const content = text.slice(0, 2000); // Analyze first 2000 chars for performance

  // 1. Shebang detection (highest confidence)
  if (firstLine.startsWith("#!")) {
    const shebang = firstLine.toLowerCase();
    if (shebang.includes("python")) return "python";
    if (shebang.includes("node")) return "javascript";
    if (shebang.includes("bash") || shebang.includes("/sh")) return "bash";
    if (shebang.includes("zsh")) return "zsh";
    if (shebang.includes("ruby")) return "ruby";
    if (shebang.includes("perl")) return "perl";
    if (shebang.includes("php")) return "php";
  }

  // 2. XML/HTML declaration
  if (firstLine.startsWith("<?xml")) return "xml";
  if (firstLine.startsWith("<!DOCTYPE html") || firstLine.startsWith("<html"))
    return "html";

  // 3. Language-specific imports/declarations (check multiple lines)
  // Python
  if (/^(from\s+\S+\s+import|import\s+\S+)/.test(firstLine)) return "python";
  if (/^def\s+\w+\s*\(/.test(firstLine)) return "python";
  if (/^class\s+\w+.*:/.test(firstLine)) return "python";

  // JavaScript/TypeScript
  if (/^import\s+.*\s+from\s+['"]/.test(firstLine)) return "typescript";
  if (/^const\s+\w+\s*=\s*require\s*\(/.test(firstLine)) return "javascript";
  if (
    /^export\s+(default\s+)?(function|class|const|let|var|interface|type)/.test(
      firstLine,
    )
  )
    return "typescript";

  // Go
  if (/^package\s+\w+/.test(firstLine)) return "go";

  // Rust
  if (/^(use\s+\w+|fn\s+\w+|pub\s+fn|impl\s+)/.test(firstLine)) return "rust";
  if (content.includes("fn main()") && content.includes("println!"))
    return "rust";

  // Java/Kotlin
  if (/^package\s+[\w.]+;/.test(firstLine)) return "java";
  if (/^public\s+class\s+\w+/.test(content)) return "java";

  // C/C++
  if (/^#include\s*[<"]/.test(firstLine)) return "cpp";
  if (/^int\s+main\s*\(/.test(content)) return "c";

  // Ruby
  if (/^require\s+['"]/.test(firstLine)) return "ruby";
  if (/^class\s+\w+\s*(<\s*\w+)?$/.test(firstLine)) return "ruby";

  // PHP
  if (firstLine.startsWith("<?php")) return "php";

  // SQL
  if (/^(SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER|DROP)\s+/i.test(firstLine))
    return "sql";

  // YAML (common in configs)
  if (/^\w+:\s*$/.test(firstLine) && content.includes("\n  ")) return "yaml";

  // JSON (starts with { or [)
  if (/^\s*[{[]/.test(firstLine)) {
    try {
      JSON.parse(text);
      return "json";
    } catch {
      // Not valid JSON, might be JS object
    }
  }

  // Shell commands (common patterns)
  if (
    /^(sudo\s+|apt\s+|npm\s+|yarn\s+|pip\s+|docker\s+|git\s+|curl\s+|wget\s+)/.test(
      firstLine,
    )
  )
    return "bash";
  if (/^\$\s+\w+/.test(firstLine)) return "bash"; // $ command prompt

  // CSS
  if (/^[.#@][\w-]+\s*\{/.test(firstLine)) return "css";
  if (/^:\s*root\s*\{/.test(firstLine)) return "css";

  // Markdown (headers, lists)
  if (/^#{1,6}\s+/.test(firstLine)) return "markdown";
  if (
    /^[-*+]\s+/.test(firstLine) &&
    content.split("\n").filter((l) => /^[-*+]\s+/.test(l)).length > 2
  )
    return "markdown";

  // No confident match
  return null;
}

/**
 * Creates a code embed specifically for multi-line pasted text.
 * Automatically detects language using multiple strategies.
 *
 * Language detection priority:
 * 1. Explicit language parameter (if provided)
 * 2. VS Code editor data (if code was copied from VS Code)
 * 3. Content-based heuristics (shebangs, imports, syntax patterns)
 * 4. Default to 'text' for unrecognized content
 *
 * @param options Pasted text options including content and optional language detection
 * @returns CodeEmbedCreationResult with embed_id and markdown reference
 */
export async function createCodeEmbedFromPastedText(
  options: PastedTextOptions | string,
): Promise<CodeEmbedCreationResult> {
  // Support legacy string-only signature for backward compatibility
  if (typeof options === "string") {
    const heuristicLanguage = detectLanguageFromContent(options);
    return createCodeEmbed(options, heuristicLanguage || "text");
  }

  const { text, vsCodeEditorData, language: explicitLanguage } = options;

  // Determine language with priority: explicit > VS Code > heuristics > default
  let language: string;
  let detectionSource: string;

  if (explicitLanguage) {
    language = explicitLanguage;
    detectionSource = "explicit";
  } else {
    // Try VS Code clipboard data first
    const vsCodeLanguage = detectLanguageFromVSCode(vsCodeEditorData);
    if (vsCodeLanguage) {
      language = vsCodeLanguage;
      detectionSource = "vscode";
    } else {
      // Fall back to content-based heuristics
      const heuristicLanguage = detectLanguageFromContent(text);
      if (heuristicLanguage) {
        language = heuristicLanguage;
        detectionSource = "heuristic";
      } else {
        // Default to plain text for unrecognized content
        language = "text";
        detectionSource = "default";
      }
    }
  }

  console.debug(
    `[codeEmbedService] Language detection: ${language} (source: ${detectionSource})`,
  );

  return createCodeEmbed(text, language);
}
