/**
 * Embed references are machine-generated identifiers, never personal data.
 *
 * Personal-data detection must not rewrite any part of them: a random UUID
 * segment inside a ref (e.g. `...-0123-4567-91b3--2e1a33`) can look like a
 * phone number, and a redacted ref can never resolve to its embed again.
 * Shared by the web composer detector, the model-span merge and the CLI
 * message redaction; the Rust port is `web_composer/embed_refs.rs`.
 *
 * Protected spans:
 * - the `(embed:<ref>)` target of a markdown embed link such as
 *   `[!](embed:<ref>)` (display text in the brackets is still scanned);
 * - inside a fenced ```json embed reference block (an object carrying
 *   `embed_id` or `embed_ids`, the grammar of
 *   `placeholderRewriteService.getProtectedRanges`), the `embed_id` /
 *   `embed_ids` members themselves. Other members such as a user note stay
 *   scanned (`ai-model-routing.preprocessing.prepared-privacy`).
 */
const EMBED_LINK_TARGET = /\(embed:[^\s)]+\)/g;
const JSON_FENCE_OPEN = "```json\n";
const JSON_BLOCK = /```json\n([\s\S]*?)\n```/g;
const EMBED_ID_MEMBER = /"embed_id"\s*:\s*"(?:\\.|[^"\\])*"|"embed_ids"\s*:\s*\[(?:\s*"(?:\\.|[^"\\])*"\s*,?)*\s*\]/g;

function isEmbedReferenceJson(body: string): boolean {
  let parsed: unknown;
  try {
    parsed = JSON.parse(body.trim());
  } catch {
    // Not JSON: an ordinary code block, scanned like any other text.
    return false;
  }
  return typeof parsed === "object" && parsed !== null && ("embed_id" in parsed || "embed_ids" in parsed);
}

/** UTF-16 ranges of every embed reference in `text`, in ascending start order. */
export function embedReferenceRanges(text: string): Array<{ start: number; end: number }> {
  if (!text.includes("embed")) return [];
  const ranges: Array<{ start: number; end: number }> = [];
  for (const match of Array.from(text.matchAll(EMBED_LINK_TARGET))) {
    ranges.push({ start: match.index!, end: match.index! + match[0].length });
  }
  for (const match of Array.from(text.matchAll(JSON_BLOCK))) {
    if (!isEmbedReferenceJson(match[1]!)) continue;
    const bodyStart = match.index! + JSON_FENCE_OPEN.length;
    for (const member of Array.from(match[1]!.matchAll(EMBED_ID_MEMBER))) {
      ranges.push({ start: bodyStart + member.index!, end: bodyStart + member.index! + member[0].length });
    }
  }
  return ranges.sort((a, b) => a.start - b.start);
}

/** True when `[start, end)` touches any of `ranges`. */
export function overlapsAnyRange(start: number, end: number, ranges: ReadonlyArray<{ start: number; end: number }>): boolean {
  return ranges.some((range) => start < range.end && end > range.start);
}
