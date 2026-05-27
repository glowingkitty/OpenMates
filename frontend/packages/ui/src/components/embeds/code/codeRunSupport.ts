// frontend/packages/ui/src/components/embeds/code/codeRunSupport.ts
//
// Shared Code Run capability checks for code embeds.
// Keeps the fullscreen CTA decision testable and aligned with the backend
// execution allowlist in backend/core/api/app/routes/code_execution.py.
// Atopile is intentionally excluded until it has a dedicated check/build flow.

const RUNNABLE_LANGUAGES = new Set([
  "python", "py",
  "javascript", "js", "node",
  "typescript", "ts",
  "bash", "sh", "shell",
  "c",
  "cpp", "c++", "cplusplus",
  "rust", "rs",
  "go", "golang",
]);

const RUNNABLE_EXTENSIONS = new Set([
  ".py",
  ".js",
  ".mjs",
  ".cjs",
  ".ts",
  ".sh",
  ".c",
  ".cc",
  ".cpp",
  ".cxx",
  ".rs",
  ".go",
]);

export function isCodeRunSupported(language: string, filename?: string): boolean {
  const normalizedLanguage = language.trim().toLowerCase();
  if (RUNNABLE_LANGUAGES.has(normalizedLanguage)) return true;
  if (!filename) return false;

  const extensionIndex = filename.lastIndexOf(".");
  if (extensionIndex < 0) return false;
  return RUNNABLE_EXTENSIONS.has(filename.slice(extensionIndex).toLowerCase());
}
