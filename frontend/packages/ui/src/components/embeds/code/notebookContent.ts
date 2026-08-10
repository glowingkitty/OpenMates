// frontend/packages/ui/src/components/embeds/code/notebookContent.ts
//
// Shared parsing helpers for Jupyter notebook embeds. These functions normalize
// nbformat JSON into display-safe cell records without executing or mutating the
// notebook source.

export interface NotebookCell {
  cell_type: string;
  source?: string | string[];
  metadata?: Record<string, unknown>;
  execution_count?: number | null;
  outputs?: unknown[];
}

export interface NotebookDocument {
  nbformat?: number;
  nbformat_minor?: number;
  metadata?: Record<string, unknown>;
  cells: NotebookCell[];
}

export interface NormalizedNotebook {
  notebook: NotebookDocument | null;
  filename: string;
  language: string;
  isPython: boolean;
  cellCount: number;
  codeCellCount: number;
  markdownCellCount: number;
  rawCellCount: number;
  sourceVersion?: string | null;
}

export function sourceToText(source: unknown): string {
  if (typeof source === 'string') return source;
  if (Array.isArray(source) && source.every((part) => typeof part === 'string')) {
    return source.join('');
  }
  return '';
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function parseContentString(value: unknown): Record<string, unknown> | null {
  if (typeof value !== 'string' || !value.trim()) return null;
  try {
    const parsed = JSON.parse(value) as unknown;
    return asRecord(parsed);
  } catch {
    return null;
  }
}

function notebookFromContent(content: Record<string, unknown>): NotebookDocument | null {
  const nested = asRecord(content.notebook)
    ?? asRecord(content.content)
    ?? parseContentString(content.content)
    ?? (Array.isArray(content.cells) ? content : null);
  if (!nested || !Array.isArray(nested.cells)) return null;
  return {
    nbformat: typeof nested.nbformat === 'number' ? nested.nbformat : undefined,
    nbformat_minor: typeof nested.nbformat_minor === 'number' ? nested.nbformat_minor : undefined,
    metadata: asRecord(nested.metadata) ?? {},
    cells: nested.cells.filter((cell): cell is NotebookCell => !!asRecord(cell)).map((cell) => cell as NotebookCell),
  };
}

function notebookLanguage(metadata: Record<string, unknown> | undefined): string {
  const kernelspec = asRecord(metadata?.kernelspec);
  const languageInfo = asRecord(metadata?.language_info);
  for (const value of [kernelspec?.language, languageInfo?.name, kernelspec?.name]) {
    if (typeof value === 'string' && value.trim()) {
      const normalized = value.trim().toLowerCase();
      if (normalized === 'python3' || normalized === 'py') return 'python';
      return normalized;
    }
  }
  return 'unknown';
}

function fallbackFilename(value: unknown): string {
  if (typeof value !== 'string' || !value.trim()) return 'notebook.ipynb';
  const filename = value.replace(/\\/g, '/').split('/').filter(Boolean).pop() || 'notebook.ipynb';
  return filename.endsWith('.ipynb') ? filename : `${filename}.ipynb`;
}

export function normalizeNotebookContent(content: unknown): NormalizedNotebook {
  const record = asRecord(content) ?? {};
  const notebook = notebookFromContent(record);
  const cells = notebook?.cells ?? [];
  const language = typeof record.language === 'string' && record.language.trim()
    ? record.language.trim().toLowerCase()
    : notebookLanguage(notebook?.metadata);
  return {
    notebook,
    filename: fallbackFilename(record.filename),
    language,
    isPython: language === 'python',
    cellCount: typeof record.cell_count === 'number' ? record.cell_count : cells.length,
    codeCellCount: cells.filter((cell) => cell.cell_type === 'code' && sourceToText(cell.source).trim()).length,
    markdownCellCount: cells.filter((cell) => cell.cell_type === 'markdown').length,
    rawCellCount: cells.filter((cell) => cell.cell_type === 'raw').length,
    sourceVersion: typeof record.source_version === 'string' ? record.source_version : null,
  };
}

export function notebookTitle(notebook: NormalizedNotebook): string {
  const firstMarkdown = notebook.notebook?.cells.find((cell) => cell.cell_type === 'markdown');
  const heading = sourceToText(firstMarkdown?.source)
    .split('\n')
    .map((line) => line.trim())
    .find((line) => line.startsWith('#'))
    ?.replace(/^#+\s*/, '')
    .trim();
  return heading || notebook.filename;
}

export function renderNotebookText(content: Record<string, unknown>): string {
  const notebook = normalizeNotebookContent(content);
  const lines = [`**${notebook.filename}**`, `${notebook.cellCount} cells, Notebook`];
  const cells = notebook.notebook?.cells ?? [];
  for (let index = 0; index < cells.length; index += 1) {
    const cell = cells[index];
    const text = sourceToText(cell.source).trim();
    if (!text) continue;
    lines.push('', `Cell ${index + 1} (${cell.cell_type})`, text);
  }
  return lines.join('\n');
}
