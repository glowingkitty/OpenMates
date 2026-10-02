/** Shared, pure parser for inline embed references in assistant messages. */
export type MessageSegment =
  | { type: "text"; value: string; rawLength: number }
  | { type: "embed"; value: string; meta?: Record<string, unknown>; rawLength: number };

export function parseMessageSegments(content: string, options: {preserveCodeFences?: boolean} = {}): MessageSegment[] {
  const segments: MessageSegment[] = [];
  const pattern = /```(?:json_embed|json)\n([\s\S]*?)\n```/g;
  let last = 0;
  for (const match of content.matchAll(pattern)) {
    const index = match.index;
    if (index > last) {
      const value = content.slice(last, index);
      segments.push({type: "text", value, rawLength: value.length});
    }
    let reference = false;
    try {
      const parsed: unknown = JSON.parse(match[1].trim());
      if (parsed && typeof parsed === "object" && "embed_id" in parsed && typeof parsed.embed_id === "string" && parsed.embed_id) {
        segments.push({type: "embed", value: parsed.embed_id, meta: parsed as Record<string, unknown>, rawLength: match[0].length});
        reference = true;
      }
    } catch { /* Ordinary or malformed code stays visible when requested. */ }
    if (!reference && options.preserveCodeFences) segments.push({type: "text", value: match[0], rawLength: match[0].length});
    last = index + match[0].length;
  }
  if (last < content.length) {
    const value = content.slice(last);
    segments.push({type: "text", value, rawLength: value.length});
  }
  return segments;
}
