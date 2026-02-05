/**
 * Code Embed Service
 *
 * Creates proper embed entries for code blocks pasted by users.
 * Follows the same pattern as urlMetadataService.ts for consistency.
 *
 * Flow:
 * 1. User pastes multi-line text
 * 2. This service creates an embed with unique embed_id
 * 3. Embed is stored in EmbedStore (encrypted)
 * 4. Returns embed reference for insertion into message
 * 5. When message is sent, embed is loaded from EmbedStore and sent to server
 */

import { embedStore } from "../../../services/embedStore";
import { generateUUID } from "../../../message_parsing/utils";
import { createEmbedReferenceBlock } from "./urlMetadataService";
import { encode as toonEncode } from "@toon-format/toon";

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
}

/**
 * Creates a proper embed from pasted code/text content.
 * This function:
 * 1. Generates a unique embed_id
 * 2. Encodes content as TOON for storage efficiency
 * 3. Stores the embed in EmbedStore (encrypted)
 * 4. Returns the embed reference for insertion into message content
 *
 * @param content The code/text content to embed
 * @param language The language/format identifier (e.g., 'markdown', 'python', 'text')
 * @param filename Optional filename for the code
 * @returns CodeEmbedCreationResult with embed_id and markdown reference
 */
export async function createCodeEmbed(
  content: string,
  language: string = "text",
  filename?: string,
): Promise<CodeEmbedCreationResult> {
  // Generate unique embed_id
  const embed_id = generateUUID();

  // Count lines for metadata
  const lineCount = content.split("\n").length;

  console.debug("[codeEmbedService] Creating code embed:", {
    embed_id,
    language,
    lineCount,
    contentLength: content.length,
    filename: filename || "none",
  });

  // Prepare embed content for storage
  // This structure matches what chatSyncServiceSenders.ts creates for code blocks
  const embedContent = {
    type: "code",
    language: language,
    code: content,
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

  // Store in EmbedStore (will be encrypted with master key)
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

  // Create the embed reference JSON block
  // Note: For code embeds we don't include a URL fallback since there's no URL
  const embedReference = createEmbedReferenceBlock("code", embed_id);

  return {
    embed_id,
    type: "code",
    embedReference,
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
  if (/^\s*[{\[]/.test(firstLine)) {
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
