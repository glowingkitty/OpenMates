// Product-owned composer document contract shared by web and Apple adapters.
// Canonical markdown remains the durable format; this model is editor-session state.
// The initial implementation is intentionally a red-phase skeleton for contract tests.
// Parsing and serialization will be implemented only after shared fixtures fail.
// Never add encryption material, raw files, or platform editor objects here.

export interface ComposerDocumentV1 {
  version: 1;
  nodes: ComposerNodeV1[];
}

export type ComposerNodeV1 = Record<string, unknown> & {
  kind: "text" | "hardBreak" | "mention" | "embed";
  id: string;
};

export function parseCanonicalMarkdownToComposerDocument(
  _markdown: string,
): ComposerDocumentV1 {
  throw new Error("ComposerDocument parser not implemented");
}

export function serializeComposerDocumentToCanonicalMarkdown(
  _document: ComposerDocumentV1,
): string {
  throw new Error("ComposerDocument serializer not implemented");
}

export function utf16Length(value: string): number {
  return value.length;
}
