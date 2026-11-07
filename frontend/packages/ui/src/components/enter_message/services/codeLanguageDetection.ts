/**
 * Pure code-language detection for pasted and attached text (VS Code clipboard
 * data and content heuristics). Import-free so the Rust twin
 * (web_composer/code_language.rs) can be checked against it with generated vectors.
 */

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
