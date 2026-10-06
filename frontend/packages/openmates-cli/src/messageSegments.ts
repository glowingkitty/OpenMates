/** Shared, pure parser for inline embed references in assistant messages. */
export type MessageSegment =
  | { type: "text"; value: string; rawLength: number }
  | { type: "embed"; value: string; meta?: Record<string, unknown>; rawLength: number };

export function parseMessageSegments(content: string, options: {preserveCodeFences?: boolean} = {}): MessageSegment[] {
  const segments: MessageSegment[] = [];
  const rows = content.match(/[^\n]*(?:\n|$)/g)?.filter(Boolean) ?? [];
  const offsets: number[] = [];
  let position = 0;
  for (const row of rows) {offsets.push(position);position += row.length;}
  let last = 0;
  for (let rowIndex = 0; rowIndex < rows.length; rowIndex++) {
    const fence = /^ {0,3}(`{3,}|~{3,})([^`~]*)$/.exec(rows[rowIndex].replace(/\r?\n$/, ''));
    if (!fence) continue;
    const close = new RegExp(`^ {0,3}${fence[1][0]}{${fence[1].length},}[ \\t]*$`);
    let end = rowIndex + 1;
    while (end < rows.length && !close.test(rows[end].replace(/\r?\n$/, ''))) end++;
    if (end === rows.length) break;
    const language = fence[2].trim();
    const index = offsets[rowIndex], finish = offsets[end] + rows[end].replace(/\r?\n$/, '').length;
    const body = rows.slice(rowIndex + 1,end).join('');
    rowIndex = end; // Never scan examples inside an enclosing code fence as references.
    if (language !== 'json_embed' && language !== 'json') continue;
    const raw = content.slice(index,finish);
    if (index > last) {
      const value = content.slice(last, index);
      segments.push({type: "text", value, rawLength: value.length});
    }
    let reference = false;
    try {
      const parsed: unknown = JSON.parse(body.trim());
      if (parsed && typeof parsed === "object" && "embed_id" in parsed && typeof parsed.embed_id === "string" && parsed.embed_id) {
        segments.push({type: "embed", value: parsed.embed_id, meta: parsed as Record<string, unknown>, rawLength: raw.length});
        reference = true;
      }
    } catch { /* Ordinary or malformed code stays visible when requested. */ }
    if (!reference && options.preserveCodeFences) segments.push({type: "text", value: raw, rawLength: raw.length});
    last = finish;
  }
  if (last < content.length) {
    const value = content.slice(last);
    segments.push({type: "text", value, rawLength: value.length});
  }
  return segments;
}
