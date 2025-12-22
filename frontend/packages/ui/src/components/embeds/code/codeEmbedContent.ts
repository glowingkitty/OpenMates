export type ParsedCodeEmbedContent = {
  code: string;
  language?: string;
  filename?: string;
};

type ParseHints = {
  language?: string;
  filename?: string;
};

const PLAIN_LANGS = new Set(['text', 'plaintext']);

function isBlank(value: string | undefined | null): boolean {
  return !value || value.trim().length === 0;
}

function normalizeNewlines(value: string): string {
  return value.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
}

// Accepts `lang:path` on the very first line.
// Example: `python:test_calculator.py`
function parseLangPathHeader(firstLine: string): { language: string; filename: string } | null {
  const match = firstLine.match(/^([a-zA-Z0-9_+.#-]{1,32}):(.{1,512})$/);
  if (!match) return null;

  const language = match[1].trim().toLowerCase();
  const filename = match[2].trim();

  if (language.length === 0 || filename.length === 0) return null;
  if (filename.includes('\n')) return null;
  // Avoid false positives on normal code like `a:b` by requiring the "path" to look like a file/path.
  if (!/[./\\]/.test(filename)) return null;

  return { language, filename };
}

export function parseCodeEmbedContent(rawCodeContent: string, hints: ParseHints = {}): ParsedCodeEmbedContent {
  const normalized = normalizeNewlines(rawCodeContent || '');

  const firstNewlineIndex = normalized.indexOf('\n');
  const firstLine = (firstNewlineIndex === -1 ? normalized : normalized.slice(0, firstNewlineIndex)).trimEnd();

  const header = parseLangPathHeader(firstLine);
  const strippedCode = header
    ? (firstNewlineIndex === -1 ? '' : normalized.slice(firstNewlineIndex + 1))
    : normalized;

  const resolvedLanguage =
    !isBlank(hints.language) && !PLAIN_LANGS.has((hints.language || '').toLowerCase())
      ? hints.language
      : header?.language;

  const resolvedFilename = !isBlank(hints.filename) ? hints.filename : header?.filename;

  return {
    code: strippedCode,
    language: resolvedLanguage,
    filename: resolvedFilename
  };
}

export function countCodeLines(code: string): number {
  if (!code) return 0;
  const normalized = normalizeNewlines(code);
  const trimmedOneTrailingNewline = normalized.endsWith('\n') ? normalized.slice(0, -1) : normalized;
  if (!trimmedOneTrailingNewline) return 0;
  return trimmedOneTrailingNewline.split('\n').length;
}

export function formatLanguageName(language: string | undefined): string {
  const lang = (language || '').trim().toLowerCase();
  if (!lang || PLAIN_LANGS.has(lang)) return '';

  const map: Record<string, string> = {
    js: 'JavaScript',
    javascript: 'JavaScript',
    ts: 'TypeScript',
    typescript: 'TypeScript',
    py: 'Python',
    python: 'Python',
    cpp: 'C++',
    c: 'C',
    cs: 'C#',
    csharp: 'C#',
    java: 'Java',
    rust: 'Rust',
    go: 'Go',
    ruby: 'Ruby',
    php: 'PHP',
    swift: 'Swift',
    kotlin: 'Kotlin',
    yaml: 'YAML',
    yml: 'YAML',
    json: 'JSON',
    sql: 'SQL',
    bash: 'Bash',
    shell: 'Shell',
    dockerfile: 'Dockerfile',
    markdown: 'Markdown',
    md: 'Markdown',
    xml: 'XML',
    html: 'HTML',
    css: 'CSS'
  };

  if (map[lang]) return map[lang];
  return lang.charAt(0).toUpperCase() + lang.slice(1);
}
