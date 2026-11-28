import type { SheetFormatting } from "./sheetFormattingTypes";

const PREFIX = "<!-- openmates-sheet-format-v1: ";
const SUFFIX = " -->";

/** Read the optional final formatting line, leaving legacy table text unchanged. */
export function splitSheetFormatting(text: string): { table: string; formatting?: SheetFormatting } {
  const end = text.trimEnd();
  const newline = end.lastIndexOf("\n");
  const footer = end.slice(newline + 1);
  if (newline === -1 || !footer.startsWith(PREFIX) || !footer.endsWith(SUFFIX)) {
    return { table: text };
  }
  const table = end.slice(0, newline);
  try {
    const formatting: unknown = JSON.parse(footer.slice(PREFIX.length, -SUFFIX.length));
    if (formatting && typeof formatting === "object" && !Array.isArray(formatting)) {
      return { table, formatting: formatting as SheetFormatting };
    }
  } catch (error) {
    if (!(error instanceof SyntaxError)) throw error;
  }
  return { table };
}

/** Only sheets with formatting receive a footer in their existing versioned text. */
export function withSheetFormatting(table: string, formatting?: SheetFormatting): string {
  if (!formatting || !Object.keys(formatting).length) return table;
  const encoded = JSON.stringify(formatting).replaceAll("<", "\\u003c").replaceAll(">", "\\u003e");
  return `${table.trimEnd()}\n${PREFIX}${encoded}${SUFFIX}`;
}
