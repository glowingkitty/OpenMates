/**
 * Shared parsing for embed: link references and fragments.
 *
 * Keeps TipTap message parsing and HTML hydration consistent for links like
 * embed:file.py#L10-L20, embed:doc#text=quote, and embed:sheet#range=A1:C4.
 * The returned cleanRef is the only value used for embed_ref lookup.
 * Fragment data is forwarded to fullscreen components for visual focus.
 */

export type EmbedLinkFocus = {
  cleanRef: string;
  lineStart: number | null;
  lineEnd: number | null;
  highlightQuoteText: string | null;
  sheetRange: string | null;
};

function decodeFragmentValue(value: string): string {
  try {
    return decodeURIComponent(value.replace(/\+/g, " "));
  } catch {
    return value;
  }
}

export function parseEmbedLinkTarget(raw: string): EmbedLinkFocus {
  const hashIndex = raw.indexOf("#");
  const cleanRef = hashIndex === -1 ? raw : raw.slice(0, hashIndex);
  const fragment = hashIndex === -1 ? "" : raw.slice(hashIndex + 1);

  const lineMatch = fragment.match(/^L(\d+)(?:-L?(\d+))?$/);
  if (lineMatch) {
    const start = parseInt(lineMatch[1], 10);
    const end = lineMatch[2] ? parseInt(lineMatch[2], 10) : start;
    return {
      cleanRef,
      lineStart: Math.min(start, end),
      lineEnd: Math.max(start, end),
      highlightQuoteText: null,
      sheetRange: null,
    };
  }

  const params = new URLSearchParams(fragment);
  const text = params.get("text") || params.get("quote");
  const range = params.get("range") || params.get("cell");

  return {
    cleanRef,
    lineStart: null,
    lineEnd: null,
    highlightQuoteText: text ? decodeFragmentValue(text) : null,
    sheetRange: range ? decodeFragmentValue(range).toUpperCase() : null,
  };
}

export function generateDirectEmbedRef(
  embedType: string,
  embedId: string,
  metadata: { filename?: string | null; title?: string | null; subject?: string | null } = {},
): string {
  const candidate = metadata.filename || metadata.title || metadata.subject || embedType;
  const fallback = embedType.replace(/_/g, "-") || "embed";
  const base = String(candidate || fallback)
    .trim()
    .toLowerCase()
    .replace(/\s+/g, "-")
    .replace(/[^a-z0-9._-]+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^[-._]+|[-._]+$/g, "")
    .slice(0, 48)
    .replace(/[-._]+$/g, "") || fallback;
  const suffix = embedId.slice(0, 6);
  return suffix && !base.endsWith(`-${suffix}`) ? `${base}-${suffix}` : base;
}
