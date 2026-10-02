/** Numeric PII patterns must not consume pieces of opaque coding identifiers. */
export function codingIdentifierRanges(text: string): Array<{ start: number; end: number }> {
  const ranges: Array<{ start: number; end: number }> = [];
  const identifiers = /\b[\da-f]{8}-[\da-f]{4}-[\da-f]{4}-[\da-f]{4}-[\da-f]{12}\b|\b[\da-f]{40,64}\b|\[[A-Z][A-Z\d_]*\]/gi;
  for (const match of text.matchAll(identifiers)) {
    ranges.push({ start: match.index!, end: match.index! + match[0].length });
  }
  return ranges;
}
